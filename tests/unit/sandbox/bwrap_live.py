"""Helpers for the tests that run a real bubblewrap (skipped where there is none): `requires_bwrap`, the scratch
directory under /var/tmp (never /tmp: every sandbox covers /tmp with a tmpfs, so a canary there passes before any fix),
and one runner-shaped world (fake home, one repository, two units) built through the real `make_workbench`."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.implementer.workbench import Workbench, make_workbench
from l4.redact import Redactor
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.env import build_agent_env, build_gate_env
from l4.sandbox.none import NoSandbox
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git

VAR_TMP = Path("/var/tmp")


def _bwrap_usable() -> bool:
    exe = shutil.which("bwrap")
    if sys.platform != "linux" or exe is None:
        return False
    try:
        return BwrapSandbox(exe).available().ok
    except Exception:  # noqa: BLE001 - a probe that cannot even run is "not usable"
        return False


requires_bwrap = pytest.mark.skipif(not _bwrap_usable(), reason="needs Linux with a working bwrap")


GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}  # fmt: skip

SECRETS = {
    ".git-credentials": "https://bot:glpat-GITCRED@gitlab.example.com",
    ".netrc": "machine h login u password NETRC",
    ".ssh/id_ed25519": "-----BEGIN OPENSSH PRIVATE KEY----- SSHKEY",
    ".config/gh/hosts.yml": "oauth_token: gho_GHTOKEN",
    ".docker/config.json": '{"auths":{"r":{"auth":"DOCKERAUTH"}}}',
    ".codex/auth.json": '{"token":"CODEXLOGIN"}',
}


@dataclass
class LiveWorld:
    home: Path
    cache: Path
    host_env: dict[str, str]
    bwrap: BwrapSandbox
    bench: Callable[[str, str, str], Workbench]

    def run(
        self, wb: Workbench, kind: str, script: str, *, path: str | None = None, timeout: int = 60,
        builds_env: bool = False,
    ) -> subprocess.CompletedProcess[str]:  # fmt: skip
        """`script` under `sh -c` in the real sandbox of `wb`'s unit: the gate (`gate_spec`) or the agent one."""
        host = {**self.host_env, **({"PATH": path} if path else {})}
        if kind == "gate":
            spec = wb.gate_spec(network=True, builds_env=builds_env)
            env = build_gate_env(host, spec)
        else:
            spec = wb.agent_spec()
            env = build_agent_env(host, spec)
        cmd = self.bwrap.wrap(["/bin/sh", "-c", script], spec, env)
        return subprocess.run(cmd.argv, env=cmd.env, capture_output=True, text=True, timeout=timeout)

    def read(self, wb: Workbench, kind: str, paths: Sequence[Path]) -> dict[str, bool]:
        """path -> whether `cat` read it inside the sandbox."""
        script = 'for f in "$@"; do if cat "$f" >/dev/null 2>&1; then echo "READ $f"; else echo "DENIED $f"; fi; done'
        quoted = " ".join(f"'{p}'" for p in paths)
        done = self.run(wb, kind, script.replace('"$@"', quoted))
        assert done.returncode == 0, done.stderr
        return {line.split(" ", 1)[1]: line.startswith("READ") for line in done.stdout.splitlines()}


def make_world(
    base: Path, *, l4_cache: Path | None = None, path: str = "/usr/local/bin:/usr/bin:/bin", cfg: L4Config | None = None
) -> LiveWorld:
    home = base / "home"
    home.mkdir()
    host_env = {"PATH": path, "HOME": str(home), "USER": "runner", "LANG": "C.UTF-8", **GIT_ENV}
    if l4_cache is not None:
        host_env["L4_CACHE"] = str(l4_cache)
    repo = home / "proj"
    for unit in ("add-login", "add-search"):
        (repo / "openspec" / "changes" / unit).mkdir(parents=True)
        (repo / "openspec" / "changes" / unit / "proposal.md").write_text("x\n")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, env={**os.environ, **host_env}, capture_output=True)

    git("init", "-q", "-b", "main")
    git("remote", "add", "origin", "https://gitlab.example.com/g/proj.git")
    git("add", "-A")
    git("commit", "-qm", "base")

    def bench(unit: str, run_id: str, adapter: str) -> Workbench:
        app = AppContext(repo, None, "human", 0, run_id, host_env, Redactor({}))
        ref = UnitRef(Framework.OPENSPEC, unit, repo / "openspec" / "changes" / unit)
        selected = SimpleNamespace(profile=SimpleNamespace(adapter=adapter))
        return make_workbench(
            cfg=cfg or L4Config(), app=app, ref=ref, provider=None, worktree=repo, git=Git(repo, environ=host_env),  # type: ignore[arg-type]
            ledger=None, sandbox=NoSandbox(allow_none=True), selected=selected, iteration=1,  # type: ignore[arg-type]
        )  # fmt: skip

    cache = l4_cache if l4_cache is not None else home / ".cache" / "l4"
    bwrap = BwrapSandbox(shutil.which("bwrap") or "bwrap")
    return LiveWorld(home, cache, host_env, bwrap, bench)
