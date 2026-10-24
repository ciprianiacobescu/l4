"""L4-SEC-035 at argv level: a gate that does not build the environment sees `.venv` and every `node_modules`
read-only, and the tool caches inside start empty. The live twin is test_bwrap_live_env.py."""

import os
from pathlib import Path

from l4.sandbox import envdirs
from l4.sandbox.base import gate_sandbox_spec
from l4.sandbox.bwrap import BwrapSandbox

EMPTY_ROOT = Path("/nonexistent-l4-host-root")


def tree(tmp_path: Path) -> Path:
    wt = tmp_path / "work" / "wt"
    (wt / ".venv" / "lib").mkdir(parents=True)
    (wt / "node_modules" / ".vite" / "deps").mkdir(parents=True)
    (wt / "node_modules" / ".vite" / "deps" / "x.js").write_text("cached")
    (wt / ".claude" / "skills").mkdir(parents=True)  # a guidance directory: its mask stays the last
    (tmp_path / "home").mkdir()
    (tmp_path / "main" / ".git").mkdir(parents=True)
    (tmp_path / "res").mkdir()
    return wt


def spec_of(tmp_path: Path, wt: Path, *, builds_env: bool, tracked=()):
    return gate_sandbox_spec(
        worktree=wt, git_common_dir=tmp_path / "main" / ".git", tmp_dir=tmp_path / "res", home=tmp_path / "home",
        configured_credential_paths={}, caches=(), network=True, cache_root=tmp_path / "cache", tool_paths=(),
        builds_env=builds_env, tracked=tracked,
    )  # fmt: skip


def argv_of(spec) -> list[str]:
    return BwrapSandbox("bwrap", host_root=EMPTY_ROOT).build_argv(["true"], spec, {"PATH": "/usr/bin"})


def at(argv: list[str], flag: str, path: Path) -> int:
    return next(i for i, a in enumerate(argv) if a == flag and argv[i + 1] == str(path))


def test_tool_caches_start_empty_in_every_gate(tmp_path):  # SCN-SEC-87
    wt = tree(tmp_path)
    envdirs.reset_tool_caches(wt)  # as `Workbench.run_gate_spec` does before every gate that does not build
    assert list((wt / "node_modules" / ".vite").iterdir()) == [] and (wt / "node_modules" / ".cache").is_dir()
    assert (wt / "node_modules" / ".vite-temp").is_dir()  # Vite 5+ bundles a TypeScript config there
    argv = argv_of(spec_of(tmp_path, wt, builds_env=False))
    git_at = at(argv, "--ro-bind", tmp_path / "main" / ".git")
    for env in (wt / ".venv", wt / "node_modules"):
        assert argv[at(argv, "--ro-bind", env) + 2] == str(env) and at(argv, "--ro-bind", env) > git_at
    for cache in (wt / "node_modules" / ".vite", wt / "node_modules" / ".cache", wt / "node_modules" / ".vite-temp"):
        assert at(argv, "--tmpfs", cache) > at(argv, "--ro-bind", wt / "node_modules")
        assert at(argv, "--tmpfs", cache) < at(argv, "--tmpfs", wt / ".claude")  # the guidance masks come last
    setup = argv_of(spec_of(tmp_path, wt, builds_env=True))
    assert str(wt / ".venv") not in setup and str(wt / "node_modules") not in setup


def test_reset_replaces_a_symlinked_cache_and_empties_a_used_one(tmp_path):
    wt = tree(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (wt / "node_modules" / ".cache").symlink_to(target)
    envdirs.reset_tool_caches(wt)
    cache = wt / "node_modules" / ".cache"
    assert cache.is_dir() and not cache.is_symlink() and os.listdir(cache) == []
    assert list((wt / "node_modules" / ".vite").iterdir()) == []
    assert target.is_dir()  # what the symlink pointed at is untouched


def test_vite_temp_is_made_emptied_and_replaced_like_the_other_tool_caches(tmp_path):  # SCN-SEC-87
    wt = tree(tmp_path)
    temp = wt / "node_modules" / ".vite-temp"
    assert not temp.exists()
    envdirs.reset_tool_caches(wt)
    assert temp.is_dir() and not temp.is_symlink() and os.listdir(temp) == []  # a missing one is made
    (temp / "vite.config.ts.timestamp-1.mjs").write_text("export default {}")
    envdirs.reset_tool_caches(wt)
    assert os.listdir(temp) == []  # one holding a file is emptied
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("kept")
    temp.rmdir()
    temp.symlink_to(target)
    envdirs.reset_tool_caches(wt)
    assert temp.is_dir() and not temp.is_symlink() and os.listdir(temp) == []  # a link is replaced, not followed
    assert (target / "keep.txt").read_text() == "kept"  # what the link pointed at is untouched
    _, empty = envdirs.read_only_mounts(wt)
    assert temp in empty


def test_a_tracked_node_modules_and_a_symlinked_one_are_not_mounted(tmp_path):
    wt = tree(tmp_path)
    (wt / "vendor" / "node_modules").mkdir(parents=True)
    (wt / "vendor" / "node_modules" / "a.js").write_text("1")
    (wt / "pkg").mkdir()
    (wt / "pkg" / "node_modules").symlink_to(tmp_path)
    found = envdirs.env_dirs(wt, tracked=["vendor/node_modules/a.js"])
    assert wt / "vendor" / "node_modules" not in found
    assert wt / "pkg" / "node_modules" in found  # returned so the harness can remove it ...
    ro, _ = envdirs.read_only_mounts(wt, ["vendor/node_modules/a.js"])
    assert wt / "pkg" / "node_modules" not in ro and wt / ".venv" in ro  # ... never mounted
