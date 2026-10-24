"""L4-SEC-039: the private trees of a step are removed also when Go made them read-only (SCN-PRV-141)."""

import os
import shutil
import stat
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

from l4.config.schema import CacheCfg
from l4.sandbox import base
from l4.sandbox.base import CacheMount, readonly_with_scratch, remove_tree, scratch_of
from l4.sandbox.caches import verifier_caches

KEY = "proj-0123456789"


def go_layout(root: Path, *, planted_to: Path | None = None) -> Path:
    """What Go leaves in GOMODCACHE: a module directory with mode 0o555 that holds a file with mode 0o444. An agent can
    also plant a symlink (to `planted_to`) in it."""
    module = root / "github.com" / "x" / "y@v1.0.0"
    module.mkdir(parents=True)
    (module / "go.mod").write_text("module github.com/x/y\n")
    (module / "go.mod").chmod(0o444)
    if planted_to is not None:
        (module.parent / "planted").symlink_to(planted_to, target_is_directory=planted_to.is_dir())
    for directory in (module, module.parent, module.parent.parent):
        directory.chmod(0o555)
    return module


def make_writable(root: Path) -> None:
    """So pytest can clean up whatever a failing test leaves."""
    if not root.exists() or root.is_symlink():
        return
    root.chmod(0o700)
    for current, dirs, _files in os.walk(root):
        dirs[:] = [d for d in dirs if not Path(current, d).is_symlink()]
        for name in dirs:  # before os.walk lists them: a directory with mode 0o000 cannot be listed
            os.chmod(Path(current, name), 0o700)


@pytest.fixture
def tree(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "work"
    root.mkdir()
    yield root
    make_writable(root)


def test_remove_tree_removes_go_layout(tree: Path):
    scratch = tree / "GOMODCACHE"
    go_layout(scratch)
    remove_tree(scratch)
    assert not scratch.exists()


def test_a_missing_path_is_no_error(tree: Path):
    remove_tree(tree / "nothing-here")


def test_a_file_at_the_path_is_unlinked(tree: Path):
    path = tree / "a-file"
    path.write_text("x")
    remove_tree(path)
    assert not path.exists()


def test_a_symlink_at_the_path_is_unlinked_and_its_target_kept(tree: Path):
    target = tree / "target"
    inside = go_layout(target)
    link = tree / "link"
    link.symlink_to(target, target_is_directory=True)
    remove_tree(link)
    assert not link.is_symlink()
    assert (inside / "go.mod").read_text() == "module github.com/x/y\n"
    assert stat.S_IMODE(inside.stat().st_mode) == 0o555  # nothing under the target was made writable


def test_a_planted_link_does_not_make_the_removal_touch_a_file_outside(tree: Path):
    outside = tree / "outside.txt"
    outside.write_text("keep me")
    outside.chmod(0o444)
    scratch = tree / "scratch"
    go_layout(scratch, planted_to=outside)  # a link in a read-only directory, to a read-only file
    remove_tree(scratch)
    assert not scratch.exists()
    assert outside.read_text() == "keep me" and stat.S_IMODE(outside.stat().st_mode) == 0o444


def test_a_planted_link_to_a_read_only_directory_outside_is_left_alone(tree: Path):
    outside = tree / "outside"
    module = go_layout(outside)
    scratch = tree / "scratch"
    go_layout(scratch, planted_to=outside)
    remove_tree(scratch)
    assert not scratch.exists()
    assert stat.S_IMODE(module.stat().st_mode) == 0o555 and (module / "go.mod").exists()
    assert stat.S_IMODE((outside / "github.com").stat().st_mode) == 0o555


def test_readonly_with_scratch_gives_an_empty_scratch_after_go_filled_the_last_one(tree: Path):  # SCN-PRV-141
    cache = CacheMount(tree / "cache" / "go", "GOMODCACHE")
    cache.path.mkdir(parents=True)
    tmp_dir = tree / "agent-tmp"
    for _ in range(2):
        (mounted,) = readonly_with_scratch([cache], tmp_dir, create=True)
        scratch = scratch_of(tmp_dir, cache)
        assert mounted.scratch == scratch and scratch.is_dir() and list(scratch.iterdir()) == []
        go_layout(scratch)  # the step's Go commands fill it, read-only


def test_verifier_caches_are_emptied_each_round_also_after_go_filled_them(tmp_path: Path):
    root = tmp_path / "cache"
    caches = {"go": CacheCfg(path="$L4_CACHE/units/{unit}/cache/go", env="GOMODCACHE")}
    try:
        for _ in range(2):
            (mount,) = verifier_caches(caches, root, "openspec:add-x", KEY)
            assert mount.path.is_dir() and list(mount.path.iterdir()) == []
            go_layout(mount.path)
    finally:
        make_writable(root)


def test_a_directory_the_step_cannot_read_is_removed(tree: Path):  # SCN-PRV-142
    """A test suite that checks permission errors can leave a directory with mode 0o000 (or 0o300) in the temp
    directory: rmtree cannot open it, and the retry removes it as a whole once it is readable."""
    scratch = tree / "agent-tmp"
    for mode, name in ((0o000, "none"), (0o300, "write-only")):
        unreadable = scratch / "pytest-of-runner" / name
        (unreadable / "sub").mkdir(parents=True)
        (unreadable / "sub" / "f").write_text("x")
        unreadable.chmod(mode)
    remove_tree(scratch)
    assert not scratch.exists()


def test_a_root_the_step_made_unreadable_is_removed(tree: Path):
    scratch = tree / "scratch"
    (scratch / "sub").mkdir(parents=True)
    (scratch / "sub" / "f").write_text("x")
    scratch.chmod(0o000)
    remove_tree(scratch)
    assert not scratch.exists()


def test_the_removal_works_without_onexc(tree: Path, monkeypatch: pytest.MonkeyPatch):
    """`rmtree(onexc=...)` is Python 3.12; the harness supports 3.11, where the handler goes in as `onerror`."""
    real = shutil.rmtree

    def rmtree_311(path, ignore_errors=False, onerror=None, *, dir_fd=None):  # noqa: ANN001 - 3.11's signature
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            real(path, ignore_errors, onerror, dir_fd=dir_fd)

    monkeypatch.setattr(base.shutil, "rmtree", rmtree_311)
    monkeypatch.setattr(base.sys, "version_info", (3, 11, 9))
    scratch = tree / "GOMODCACHE"
    go_layout(scratch)
    (scratch / "locked").mkdir()
    (scratch / "locked").chmod(0o000)
    remove_tree(scratch)
    assert not scratch.exists()
