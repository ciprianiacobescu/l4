"""bubblewrap sandboxes (SPEC L4-SEC-005), M0 layout.

The base is the profile proven on `l4-runner` (docs/runner/README.md, "Nested sandbox"): the whole filesystem
read-only, a tmpfs `/tmp`, fresh PID and IPC namespaces, the network shared. M0 adds, per implementation-map "Stage B":
`--proc /proc` (the ancestors' `/proc/*/environ` hold the job's `L4_FORGE_TOKEN`), every OTHER adapter's login hidden,
the main repository's `.git` read-only, a tmpfs over each existing repo guidance directory of the worktree (HB-X1,
after every bind), the CI runner's `<CI_PROJECT_DIR>.tmp` (job-token git config) hidden, and `--clearenv` plus the
allow-listed variables.

`scripts/runner/sandbox-probe.sh` (SANDBOX=m0) builds this same argv in bash; tests/unit/sandbox/test_probe_parity.py
diffs the two, so a change here must be made there too.
`/run` (and `/var/run`) is covered by a tmpfs (HB-1): `--ro-bind / /` is read-only for files, not for `connect()` on a
unix socket, and a runner user in group `docker` would reach `/var/run/docker.sock` (root on the host). Only the file
`/etc/resolv.conf` points to is put back, read-only, so DNS keeps working. Residual: a daemon socket outside /run
(e.g. a path under the user's home) stays reachable; abstract sockets (dbus, X11) are isolated only by `--unshare-net`,
which gates get with `gates.network: none` and agent sandboxes (network on) do not.
L4-SEC-030..033: the real home and the runner cache are covered by a tmpfs right after the base flags, and the tool
paths come back read-only before the credential masks (`l4.sandbox.home`). Still open: sandbox-security 1.12-1.13.
"""

import os
import posixpath
from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.proc import Runner, run_process
from l4.sandbox.base import (
    Availability,
    SandboxSpec,
    SandboxUnavailable,
    WrappedCommand,
    hidden_credential_paths,
    repo_guidance_masks,
)
from l4.sandbox.home import cache_is_covered

PROBE_TIMEOUT_S = 30.0


ROOT = Path("/")
MAX_LINK_HOPS = 8


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base + "/")


def _link_end(root: Path, start: str) -> str:
    """Where the symlink chain at `start` (an absolute path below `root`) ends, as an absolute path below `root`."""
    path = start
    for _ in range(MAX_LINK_HOPS):
        real = root / path.lstrip("/")
        if not real.is_symlink():
            break
        target = os.readlink(real)
        path = posixpath.normpath(target if target.startswith("/") else posixpath.join(posixpath.dirname(path), target))
    return path


def daemon_socket_masks(root: Path = ROOT) -> list[str]:
    """Flags that make the container daemons' sockets unreachable (HB-1); `root` is `/` in production. Mirrored in
    `m0_masks` of scripts/runner/sandbox-probe.sh. A directory that does not exist is skipped: under a read-only root
    bwrap cannot create the mount point."""
    flags: list[str] = []
    run = root / "run"
    if run.is_dir() and not run.is_symlink():
        flags += ["--tmpfs", "/run"]
        resolver = _link_end(root, "/etc/resolv.conf")  # Ubuntu: -> /run/systemd/resolve/stub-resolv.conf
        if resolver.startswith("/run/") and not _under(resolver, "/run/user"):  # /run/user/<uid>: dbus, podman, gpg
            flags += ["--ro-bind-try", resolver, resolver]
    var_run = _link_end(root, "/var/run")  # a symlink to /run is covered above
    if not _under(var_run, "/run") and var_run != "/" and (root / var_run.lstrip("/")).is_dir():
        flags += ["--tmpfs", var_run]
    return flags


def base_flags(*, network: bool, host_root: Path = ROOT) -> list[str]:
    return [
        "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        *daemon_socket_masks(host_root),
        "--unshare-pid", "--unshare-ipc", "--share-net" if network else "--unshare-net", "--die-with-parent",
    ]  # fmt: skip


def _hide(path: Path) -> list[str]:
    """A directory is covered by a tmpfs, a file by /dev/null. A path that does not exist is skipped: under a
    read-only root bwrap cannot create the mount point, and there is nothing to hide."""
    if path.is_dir():
        return ["--tmpfs", str(path)]
    if path.exists():
        return ["--ro-bind", "/dev/null", str(path)]
    return []


def _check_home(home: Path) -> None:
    """A `HOME` that is not an existing absolute directory other than `/` means the harness does not know where the
    user's files are: fail closed (L4-SEC-030)."""
    if not home.is_absolute() or home == ROOT or not home.is_dir():
        raise SandboxUnavailable("HOME must name an existing directory other than / for the sandbox to hide it")


class BwrapSandbox:
    name = "bwrap"

    def __init__(self, exe: str, runner: Runner = run_process, host_root: Path = ROOT) -> None:
        self._exe = exe
        self._run = runner
        self._root = host_root  # `/`; tests point it at a stand-in

    def available(self) -> Availability:
        """Runs a real no-op inside bwrap: user namespaces can be blocked (AppArmor), which `which` cannot show."""
        argv = [self._exe, *base_flags(network=True, host_root=self._root), "--", "true"]
        done = self._run(argv, Path("/"), {"PATH": "/usr/bin:/bin"}, PROBE_TIMEOUT_S)
        if done.returncode == 0:
            return Availability(True)
        detail = done.stderr.strip().splitlines()[-1][:200] if done.stderr.strip() else f"exit {done.returncode}"
        return Availability(False, f"bwrap cannot start a sandbox ({detail})")

    def build_argv(
        self, argv: Sequence[str], spec: SandboxSpec, env: Mapping[str, str], cwd: Path | None = None
    ) -> list[str]:
        """`cwd` is where the command starts (default: the worktree). It must be inside a mounted path: the step's
        private dir (`spec.tmp_dir`) is, which is where the tool-less calls' empty directory lives."""
        out = [self._exe, *base_flags(network=spec.network or spec.kind == "agent", host_root=self._root)]
        _check_home(spec.home)
        out += ["--tmpfs", str(spec.home)]  # L4-SEC-030: the real home is not there; what a step needs comes back below
        if cache_is_covered(spec.cache_root, spec.home):
            out += ["--tmpfs", str(spec.cache_root)]  # L4-SEC-031: nothing of another unit or project
        for path in (*spec.tool_paths, *spec.setup_paths):
            out += ["--ro-bind", str(path), str(path)]  # L4-SEC-032/033: before the masks, so none re-exposes a login
        for path in hidden_credential_paths(spec):
            out += _hide(path)
        for path in spec.runner_tmp:
            out += _hide(path)
        for path in spec.credential_paths.get(spec.adapter or "", ()):
            if path.exists():
                out += ["--bind", str(path), str(path)]
        # the delegate's worktree is read-only (L4-DLG-004); the private directory holding its result stays writable
        out += ["--ro-bind" if spec.worktree_read_only else "--bind", str(spec.worktree), str(spec.worktree)]
        out += ["--bind", str(spec.tmp_dir), str(spec.tmp_dir)]
        if spec.record_dir is not None:
            out += ["--bind", str(spec.record_dir), str(spec.record_dir)]
        for cache in spec.caches:
            out += ["--ro-bind" if cache.read_only else "--bind", str(cache.path), str(cache.path)]
        out += ["--ro-bind", str(spec.git_common_dir), str(spec.git_common_dir)]
        for path in spec.read_only:  # L4-SEC-035: a gate that does not build the environment cannot change it ...
            out += ["--ro-bind", str(path), str(path)]
        for path in spec.empty_dirs:  # ... and its tool caches start empty (the harness made the mount points)
            out += ["--tmpfs", str(path)]
        if spec.worktree_read_only:  # again, after every other bind: a writable cache at or above it must not shadow it
            out += ["--ro-bind", str(spec.worktree), str(spec.worktree)]
        # HB-X1: no repo guidance directory is there to be loaded. After EVERY bind: a later bind of a path at or above
        # the worktree (a cache at `$L4_CACHE/worktrees` is valid config) would put the host directory back.
        for path in repo_guidance_masks(spec.worktree):
            out += ["--tmpfs", str(path)]
        out += ["--clearenv"]
        for name, value in env.items():
            out += ["--setenv", name, value]
        return [*out, "--chdir", str(cwd or spec.worktree), "--", *argv]

    def wrap(
        self, argv: Sequence[str], spec: SandboxSpec, env: Mapping[str, str], cwd: Path | None = None
    ) -> WrappedCommand:
        # bwrap itself needs only PATH; every variable the child sees was set by --setenv above
        return WrappedCommand(self.build_argv(argv, spec, env, cwd), {"PATH": env.get("PATH", "/usr/bin:/bin")})
