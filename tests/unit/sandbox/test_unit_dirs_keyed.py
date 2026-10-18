"""sandbox-security-1 (L4-SEC-034): two projects with a unit of the same name on one runner share no directory.
Ported from the review's r1_unitcache_real.py: everything goes through the real `make_workbench`."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from l4.config.schema import L4Config, SandboxCfg
from l4.context import AppContext
from l4.implementer.workbench import Workbench, make_workbench
from l4.redact import Redactor
from l4.sandbox.caches import mount_caches
from l4.sandbox.none import NoSandbox
from l4.sandbox.seed import is_new
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git
from l4.vcs.repokey import repository_key


@dataclass
class Project:
    key: str
    wb: Workbench


@pytest.fixture
def world(tmp_path: Path):
    cache = tmp_path / "l4cache"
    (tmp_path / "home").mkdir()
    env = {
        "PATH": os.environ["PATH"], "HOME": str(tmp_path / "home"), "L4_CACHE": str(cache),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
    }  # fmt: skip

    def project(name: str, origin: str, run_id: str) -> Project:
        repo = tmp_path / name
        unit_dir = repo / "openspec" / "changes" / "add-login"
        unit_dir.mkdir(parents=True)
        (unit_dir / "proposal.md").write_text("x\n")

        def git(*a: str) -> None:
            subprocess.run(["git", "-C", str(repo), *a], check=True, env=env, capture_output=True)

        git("init", "-q", "-b", "main")
        git("remote", "add", "origin", origin)
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        app = AppContext(repo, None, "human", 0, run_id, env, Redactor({}))
        ref = UnitRef(Framework.OPENSPEC, "add-login", unit_dir)
        wb = make_workbench(
            cfg=L4Config(), app=app, ref=ref, provider=None, worktree=repo, git=Git(repo, environ=env),  # type: ignore[arg-type]
            ledger=None, sandbox=NoSandbox(allow_none=True), selected=None, iteration=1,  # type: ignore[arg-type]
        )  # fmt: skip
        return Project(repository_key(repo, env), wb)

    a = project("projecta", "https://gitlab.example.com/team-a/projecta.git", "r-20261017T1200Z-aaaa")
    b = project("projectb", "https://gitlab.example.com/team-b/projectb.git", "r-20261017T1201Z-bbbb")
    return a, b


def test_two_projects_with_the_same_unit_share_no_directory(world):  # SCN-SEC-81
    a, b = world
    assert a.key != b.key
    pairs = [
        (a.wb.unit_cache, b.wb.unit_cache),
        (a.wb.agent_tmp, b.wb.agent_tmp),
        (a.wb.unit_cache / "gate-tmp", b.wb.unit_cache / "gate-tmp"),
        (a.wb.excludes, b.wb.excludes),
        *[(x.path, y.path) for x, y in zip(a.wb.caches, b.wb.caches, strict=True) if not x.read_only],
    ]
    for mine, theirs in pairs:
        assert mine != theirs
    for path in (a.wb.unit_cache, a.wb.agent_tmp, a.wb.excludes, *[c.path for c in a.wb.caches if not c.read_only]):
        assert a.key in path.parts
    for path in (b.wb.unit_cache, b.wb.agent_tmp, b.wb.excludes, *[c.path for c in b.wb.caches if not c.read_only]):
        assert b.key in path.parts
    (b.wb.agent_tmp / "result.json").write_text('{"status": "done", "phase": "green"}')
    a.wb.reset_agent_tmp()
    (a.wb.agent_tmp / "result.json").write_text('{"written_by": "project A"}')
    assert (b.wb.agent_tmp / "result.json").read_text() == '{"status": "done", "phase": "green"}'


def test_another_projects_uv_cache_is_new(world):  # SCN-SEC-82
    a, b = world
    uv_a = next(c.path for c in a.wb.caches if c.env == "UV_CACHE_DIR")
    uv_b = next(c.path for c in b.wb.caches if c.env == "UV_CACHE_DIR")
    (uv_a / "poisoned-wheel.whl").write_text("evil")
    assert is_new(uv_b)
    assert not (uv_b / "poisoned-wheel.whl").exists()


def test_the_unit_placeholder_carries_the_key(tmp_path: Path):
    root = tmp_path / "root"
    mounts = mount_caches(SandboxCfg().caches, root, "openspec:add-x", repo_key="proj-0123456789")
    uv = next(m for m in mounts if m.env == "UV_CACHE_DIR")
    assert uv.path == root.resolve() / "units" / "proj-0123456789" / "openspec" / "add-x" / "cache" / "uv"
    configured = {"c": SandboxCfg().caches["uv"].model_copy(update={"path": "$L4_CACHE/custom/{unit}/npm"})}
    (custom,) = mount_caches(configured, root, "openspec:add-x", repo_key="proj-0123456789")
    assert custom.path == root.resolve() / "custom" / "proj-0123456789" / "openspec" / "add-x" / "npm"
    shared = root / "shared" / "ms-playwright"
    shared.mkdir(parents=True)
    again = mount_caches(SandboxCfg().caches, root, "openspec:add-x", repo_key="proj-0123456789")
    assert any(m.env == "PLAYWRIGHT_BROWSERS_PATH" and m.path == shared.resolve() and m.read_only for m in again)
