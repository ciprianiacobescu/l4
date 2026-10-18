"""Review F1 (R3, owner decision): the per-unit package caches are read-only in every sandbox but a `gates.setup`
command, a step or gate works in a private scratch cache that is discarded, and the verifier builds from a cache of its
own that no implementer step touched. Argv and workbench level; the live twin is test_bwrap_live_caches.py."""

from pathlib import Path

from l4.config.schema import SandboxCfg
from l4.sandbox.base import gate_sandbox_spec
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.caches import SCRATCH_DIR, mount_caches
from l4.sandbox.env import build_gate_env

from .mountsim import visible

KEY = "proj-0123456789"
EMPTY_ROOT = Path("/nonexistent-l4-host-root")


def gate(tmp_path: Path, *, builds_env: bool):
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "gate-tmp").mkdir(exist_ok=True)
    (tmp_path / "wt").mkdir(exist_ok=True)
    (tmp_path / "git").mkdir(exist_ok=True)
    shared = mount_caches(SandboxCfg().caches, tmp_path / "root", "openspec:add-x", KEY)
    spec = gate_sandbox_spec(
        worktree=tmp_path / "wt", git_common_dir=tmp_path / "git", tmp_dir=tmp_path / "gate-tmp",
        home=tmp_path / "home", configured_credential_paths={}, caches=shared, network=True,
        cache_root=tmp_path / "root", tool_paths=(), builds_env=builds_env,
    )  # fmt: skip
    return shared, spec


def test_a_gate_other_than_setup_gets_read_only_caches_and_a_private_scratch(tmp_path):  # SCN-PRV-109
    shared, spec = gate(tmp_path, builds_env=False)
    writable = [c for c in shared if not c.read_only]
    assert writable and {c.env for c in writable} == {c.env for c in spec.caches if c.env != "PLAYWRIGHT_BROWSERS_PATH"}
    for mount in spec.caches:
        if mount.env in {"PLAYWRIGHT_BROWSERS_PATH", "GOMODCACHE"}:
            continue
        assert mount.read_only and mount.scratch is not None
        assert tmp_path / "gate-tmp" / SCRATCH_DIR in mount.scratch.parents and mount.scratch.is_dir()
        assert list(mount.scratch.iterdir()) == []
    env = build_gate_env({"PATH": "/usr/bin", "HOME": str(tmp_path / "home")}, spec)
    uv = next(c for c in spec.caches if c.env == "UV_CACHE_DIR")
    assert env["UV_CACHE_DIR"] == str(uv.scratch) and env["UV_CACHE_DIR"] != str(uv.path)
    assert env["UV_LINK_MODE"] == "copy"
    argv = BwrapSandbox("bwrap", host_root=EMPTY_ROOT).build_argv(["true"], spec, env)
    i = argv.index(str(uv.path))
    assert argv[i - 1 : i + 2] == ["--ro-bind", str(uv.path), str(uv.path)]  # read-only
    assert visible(argv, uv.scratch / "file")  # the scratch is inside the step's writable temp directory


def test_the_setup_gate_alone_writes_the_shared_cache(tmp_path):  # SCN-PRV-109
    shared, spec = gate(tmp_path, builds_env=True)
    assert [c for c in spec.caches if not c.read_only] == [c for c in shared if not c.read_only]
    assert all(c.scratch is None for c in spec.caches)
    env = build_gate_env({"PATH": "/usr/bin", "HOME": str(tmp_path / "home")}, spec)
    uv = next(c for c in spec.caches if c.env == "UV_CACHE_DIR")
    assert env["UV_CACHE_DIR"] == str(uv.path)


def test_a_gate_reads_the_go_module_cache_where_it_is(tmp_path):
    """Go's module cache is read-only by design: a test gate with `gates.network: none` has no other source."""
    _, spec = gate(tmp_path, builds_env=False)
    mod = next(c for c in spec.caches if c.env == "GOMODCACHE")
    assert mod.read_only and mod.scratch is None
    env = build_gate_env({"PATH": "/usr/bin", "HOME": str(tmp_path / "home")}, spec)
    assert env["GOMODCACHE"] == str(mod.path)
    assert next(c for c in spec.caches if c.env == "GOCACHE").scratch is not None  # the build cache is written


def test_each_gate_starts_from_an_empty_scratch(tmp_path):
    _, spec = gate(tmp_path, builds_env=False)
    uv = next(c for c in spec.caches if c.env == "UV_CACHE_DIR")
    (uv.scratch / "left-by-the-last-gate").write_text("x")
    _, again = gate(tmp_path, builds_env=False)
    assert list(next(c for c in again.caches if c.env == "UV_CACHE_DIR").scratch.iterdir()) == []
