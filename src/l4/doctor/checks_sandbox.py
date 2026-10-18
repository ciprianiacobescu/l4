"""SANDBOX-002 (HB-1, SPEC L4-SEC-005): no container-daemon socket is reachable from the bwrap sandboxes. Registered
at import. SANDBOX-003 (L4-SEC-038) proves the home and the runner cache are hidden; SANDBOX-004 (L4-SEC-033) warns
while `sandbox.setup_paths` hands a registry login to setup code.

`--ro-bind / /` does not stop `connect()` on a unix socket, so a runner user in group `docker` reached
`/var/run/docker.sock` (root on the host) from inside the sandbox. The check runs a tiny probe with the real base argv
(`l4.sandbox.bwrap.base_flags`, the part both kinds share) once with the network shared (the agent kind) and once
unshared (a gate with `gates.network: none`), and FAILS when a socket is visible or connectable. It is the narrow
check; the full SANDBOX-001 (credentials, ancestor environment) is separate.
"""

import os
import secrets
import shutil
from pathlib import Path

from l4.config.defaults import cache_root
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register
from l4.exitcodes import L4Exit
from l4.sandbox.base import SandboxSpec, expand_credential_paths, gate_sandbox_spec
from l4.sandbox.bwrap import BwrapSandbox, base_flags
from l4.sandbox.env import build_agent_env, build_gate_env
from l4.sandbox.home import spec_paths

CLEAN = "L4-SOCKETS-OK"
REACHABLE = "L4-SOCKETS-REACHABLE:"
PROBE_TIMEOUT_S = 30.0

# Runs INSIDE the sandbox. Known daemon sockets are connected to; anything that is a socket under /run or /var/run is
# also reported, because after the mask nothing but a resolver file is supposed to be there.
PROBE = f"""
import os, socket, stat
found = []
uid = os.getuid()
for path in ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd/containerd.sock", "/run/podman/podman.sock",
             "/run/dbus/system_bus_socket", f"/run/user/{{uid}}/podman/podman.sock", f"/run/user/{{uid}}/bus"):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    try:
        s.connect(path)
        found.append("connect:" + path)
    except OSError:
        pass
    finally:
        s.close()
for top in ("/run", "/var/run"):
    for dirpath, dirs, files in os.walk(top, onerror=lambda e: None):
        if dirpath.count("/") > 5:
            dirs[:] = []
        for name in dirs + files:
            full = os.path.join(dirpath, name)
            try:
                if stat.S_ISSOCK(os.lstat(full).st_mode):
                    found.append("socket:" + full)
            except OSError:
                pass
print({REACHABLE!r} + " " + ", ".join(sorted(set(found))) if found else {CLEAN!r})
"""

KINDS = ((True, "agent sandbox (network shared)"), (False, "gate sandbox (--unshare-net)"))


def _sandbox_002(ctx: DoctorContext) -> CheckResult:
    if ctx.cfg.sandbox.mode not in ("auto", "bwrap"):
        return CheckResult("skip", f"sandbox.mode is {ctx.cfg.sandbox.mode}: not a bwrap sandbox")
    bwrap, python = ctx.which("bwrap"), ctx.which("python3")
    if not bwrap:
        return CheckResult("skip", "bwrap was not found on PATH (the sandbox is unavailable, so nothing runs in it)")
    if not python:
        return CheckResult("fail", "python3 was not found on PATH: the sandbox probe cannot run")
    leaks: list[str] = []
    for network, label in KINDS:
        argv = [bwrap, *base_flags(network=network), "--", python, "-c", PROBE]
        done = ctx.run(argv, timeout=PROBE_TIMEOUT_S, env={"PATH": "/usr/bin:/bin"})
        out = done.stdout.strip().splitlines()
        last = out[-1] if out else ""
        if last.startswith(REACHABLE):
            leaks.append(f"{label}: {last.removeprefix(REACHABLE).strip()}")
        elif last != CLEAN:
            detail = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1][:200]
            return CheckResult("fail", f"the sandbox probe did not run in the {label}: {detail}")
    if leaks:
        return CheckResult(
            "fail",
            "a daemon socket is reachable from inside the sandbox (root-equivalent if it is the docker socket): "
            + "; ".join(leaks),
            "the bwrap argv must cover /run and /var/run with a tmpfs (l4.sandbox.bwrap.daemon_socket_masks); "
            "also check for a socket outside /run, and remove the runner user from the docker group if no job needs it",
        )
    return CheckResult("pass", "no container-daemon socket is reachable from the agent or the gate sandbox")


SANDBOX_002 = register(Check("SANDBOX-002", "No daemon socket reachable from the sandboxes", "error", _sandbox_002))


# --- SANDBOX-003: the home and the runner cache are hidden (L4-SEC-038) ----------------------------------------------

READ = "L4-READ:"
DONE = "L4-CANARY-DONE"
SEEN = "L4-SEEN:"
SPLIT = "L4-SPLIT"
# the paths before the marker must not be readable, the ones after it must be (a tool that was bound on purpose)
READ_SCRIPT = (
    f'mode=hide; for f; do if [ "$f" = {SPLIT} ]; then mode=show; continue; fi; '
    f'if [ -r "$f" ]; then if [ $mode = hide ]; then echo "{READ}$f"; else echo "{SEEN}$f"; fi; fi; done; echo {DONE}'
)


def _canaries(home: Path, cache: Path, token: str) -> list[Path]:
    """A file in the home outside every credential path, a credential file in another unit's step directory, and a lock
    file. Each holds a random marker only, never anything that was in the user's files."""
    return [
        home / f".l4-canary-{token}",
        cache / "units" / f"l4-canary-{token}" / "x" / "y" / "agent-tmp" / "credential",
        cache / "locks" / f"l4-canary-{token}.lock",
    ]


def _tool_traps(home: Path, token: str) -> tuple[Path, list[Path], list[Path], list[Path]]:
    """Two symlinked tools in a PATH directory of their own, each with a secret beside its target: a plain file tool,
    and a shim into a project's `node_modules` (review F2). Returns (the PATH directory, the secrets that must stay
    hidden, the tool files that must be visible, the directories to remove). The sandbox binds the target file and
    the package, never what is around them."""
    bin_dir = home / f".l4-canary-{token}-bin"
    tool = home / f".l4-canary-{token}-tool"
    project = home / f".l4-canary-{token}-proj"
    package = project / "node_modules" / "pkg"
    for directory in (bin_dir, tool, package):
        directory.mkdir(parents=True, exist_ok=True)
    (tool / "real.sh").write_text("#!/bin/sh\n")
    (package / "cli.js").write_text("// tool\n")
    for secret in (tool / "secret", project / "secret"):
        secret.write_text(secrets.token_hex(16))
    (bin_dir / "plain").symlink_to(tool / "real.sh")
    (bin_dir / "shim").symlink_to(package / "cli.js")
    return (
        bin_dir,
        [tool / "secret", project / "secret"],
        [tool / "real.sh", package / "cli.js"],
        [bin_dir, tool, project],
    )


def _sandbox_003(ctx: DoctorContext) -> CheckResult:
    if ctx.cfg.sandbox.mode not in ("auto", "bwrap"):
        return CheckResult("skip", f"sandbox.mode is {ctx.cfg.sandbox.mode}: not a bwrap sandbox")
    bwrap = ctx.which("bwrap")
    if not bwrap:
        return CheckResult("skip", "bwrap was not found on PATH (the sandbox is unavailable, so nothing runs in it)")
    home = Path(ctx.env["HOME"]) if ctx.env.get("HOME") else Path.home()
    try:
        cache = cache_root(ctx.env, repo=ctx.repo)
    except L4Exit as exc:
        return CheckResult("fail", str(exc))
    if not home.is_dir():
        return CheckResult("fail", "HOME is not an existing directory: the sandbox cannot hide it")
    token = secrets.token_hex(6)
    canaries = _canaries(home, cache, token)
    trap_dirs: list[Path] = []
    base = cache / "doctor" / f"sandbox-003-{token}"
    worktree, tmp_dir, git_dir = base / "wt", base / "tmp", base / "git"
    try:
        for directory in (worktree, tmp_dir, git_dir):
            directory.mkdir(parents=True, mode=0o700)
        for canary in canaries:
            canary.parent.mkdir(parents=True, exist_ok=True)
            canary.write_text(secrets.token_hex(16))
        bin_dir, trap_secrets, trap_tools, trap_dirs = _tool_traps(home, token)
        probe_env = {**ctx.env, "PATH": os.pathsep.join([str(bin_dir), ctx.env.get("PATH", "")])}
        hidden = [*canaries, *trap_secrets]
        logins = expand_credential_paths(ctx.cfg.sandbox.credential_paths, home)
        chain = ctx.cfg.roles.implementer
        adapter = ctx.cfg.profiles[chain[0]].adapter if chain and chain[0] in ctx.cfg.profiles else "codex"
        sandbox = BwrapSandbox(bwrap)
        for kind in ("gate", "agent"):
            tools, _ = spec_paths(
                probe_env, home=home, cache_root=cache, kind=kind, sandbox_cfg=ctx.cfg.sandbox, credential_paths=logins,
                forbid=(worktree, base),
            )  # fmt: skip
            if kind == "gate":
                spec = gate_sandbox_spec(
                    worktree=worktree, git_common_dir=git_dir, tmp_dir=tmp_dir, home=home,
                    configured_credential_paths=ctx.cfg.sandbox.credential_paths, caches=(), network=True,
                    cache_root=cache, tool_paths=tools, builds_env=False,
                )  # fmt: skip
                env = build_gate_env(ctx.env, spec)
            else:
                spec = SandboxSpec(
                    "agent", worktree, git_dir, tmp_dir, home, logins, adapter=adapter, network=True,
                    cache_root=cache, tool_paths=tools,
                )  # fmt: skip
                env = build_agent_env(ctx.env, spec)
            wrapped = sandbox.wrap(
                ["/bin/sh", "-c", READ_SCRIPT, "sh", *map(str, hidden), SPLIT, *map(str, trap_tools)], spec, env
            )
            done = ctx.run(wrapped.argv, timeout=PROBE_TIMEOUT_S, env=wrapped.env)
            lines = done.stdout.strip().splitlines()
            readable = [line.removeprefix(READ) for line in lines if line.startswith(READ)]
            if DONE not in lines:
                detail = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1][:200]
                return CheckResult("fail", f"the canary probe did not run in the {kind} sandbox: {detail}")
            seen = {line.removeprefix(SEEN) for line in lines if line.startswith(SEEN)}
            if not readable and not {str(t) for t in trap_tools} <= seen:
                return CheckResult(
                    "fail",
                    f"the {kind} sandbox lost a symlinked tool it should have kept: the tool paths of the sandbox "
                    "(l4.sandbox.home) did not bind the file a PATH symlink points to",
                    "set sandbox.tool_paths for the tool, or fix l4.sandbox.home",
                )
            if readable:
                return CheckResult(
                    "fail",
                    f"the {kind} sandbox can read a file it must not see: {', '.join(readable)}",
                    "the bwrap argv must cover the home and the runner cache with a tmpfs and bind back only the tool "
                    "paths (l4.sandbox.bwrap, l4.sandbox.home); a tool that is missing inside the sandbox goes into "
                    "sandbox.tool_paths",
                )
    finally:
        for canary in canaries:
            canary.unlink(missing_ok=True)
        for directory in trap_dirs:
            shutil.rmtree(directory, ignore_errors=True)
        shutil.rmtree(cache / "units" / f"l4-canary-{token}", ignore_errors=True)
        shutil.rmtree(base, ignore_errors=True)
    return CheckResult(
        "pass",
        "the gate and the agent sandbox read none of the canaries (home, another unit's directory, lock directory, the "
        "secrets beside a symlinked tool) and keep the tools",
    )


SANDBOX_003 = register(Check("SANDBOX-003", "The sandboxes hide the home and the runner cache", "error", _sandbox_003))


# --- SANDBOX-004: setup_paths is a registry login in reach of setup code (owner decision Q1) --------------------------


def _sandbox_004(ctx: DoctorContext) -> CheckResult:
    if not ctx.cfg.sandbox.setup_paths:
        return CheckResult("pass", "sandbox.setup_paths is empty: no login is bound into a setup gate")
    return CheckResult(
        "fail",
        f"sandbox.setup_paths binds {len(ctx.cfg.sandbox.setup_paths)} path(s), read-only, into the sandbox of every "
        "gates.setup command: a registry login there is in reach of setup code an agent can influence (a build hook, "
        "a postinstall script)",
        "keep it to a token that can only read packages; remove the entry when the project needs no private registry",
        severity="warn",
    )


SANDBOX_004 = register(Check("SANDBOX-004", "sandbox.setup_paths hands a login to setup code", "warn", _sandbox_004))
