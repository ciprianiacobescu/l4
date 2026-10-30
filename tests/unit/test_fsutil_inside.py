"""The confined file primitives (L4-SEC-020, design D1): no read, write or removal below a root follows a link."""

import os
import shutil
import signal
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from l4.fsutil import (
    LinkedPath,
    UnsafeFile,
    linked_component,
    read_inside,
    remove_link,
    unlink_inside,
    unlink_matching_inside,
    write_inside,
)


@pytest.fixture(autouse=True)
def _alarm() -> Iterator[None]:
    """A primitive that blocks (on a FIFO) must fail the test, not hang the run."""

    def boom(*_: object) -> None:
        raise TimeoutError("the primitive blocked for 5 s")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(5)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    """(root, outside): `root/pkg/mod.py` is a real file; `outside` holds a file of its own."""
    root = tmp_path / "root"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_bytes(b"original\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mod.py").write_bytes(b"outside\n")
    return root, outside


def link_pkg(root: Path, outside: Path) -> None:
    shutil.rmtree(root / "pkg")
    (root / "pkg").symlink_to(outside)


def test_linked_component_finds_a_linked_parent_a_linked_last_component_or_nothing(tree):
    root, outside = tree
    assert linked_component(root, "pkg/mod.py") is None
    assert linked_component(root, "missing/deeper/file.py") is None
    (root / "pkg" / "alias.py").symlink_to(outside / "mod.py")
    assert linked_component(root, "pkg/alias.py") == "pkg/alias.py"
    link_pkg(root, outside)
    assert linked_component(root, "pkg/mod.py") == "pkg"


def test_remove_link_removes_the_link_and_leaves_its_target(tree):
    root, outside = tree
    link_pkg(root, outside)
    assert remove_link(root, "pkg") is True
    assert not (root / "pkg").exists() and not (root / "pkg").is_symlink()
    assert (outside / "mod.py").read_bytes() == b"outside\n"
    assert remove_link(root, "pkg") is False  # nothing left to remove


def test_remove_link_leaves_a_real_directory_alone(tree):
    root, _ = tree
    assert remove_link(root, "pkg") is False
    assert (root / "pkg" / "mod.py").is_file()


def test_read_write_and_unlink_under_a_linked_parent_raise_linked_path_and_touch_nothing(tree):
    root, outside = tree
    link_pkg(root, outside)
    with pytest.raises(LinkedPath) as read:
        read_inside(root, "pkg/mod.py", limit=100)
    assert read.value.link == "pkg"
    with pytest.raises(LinkedPath) as write:
        write_inside(root, "pkg/new.py", b"planted\n")
    assert write.value.link == "pkg"
    with pytest.raises(LinkedPath) as gone:
        unlink_inside(root, "pkg/mod.py")
    assert gone.value.link == "pkg"
    assert sorted(p.name for p in outside.iterdir()) == ["mod.py"]
    assert (outside / "mod.py").read_bytes() == b"outside\n"


def test_linked_path_is_an_unsafe_file():
    assert issubclass(LinkedPath, UnsafeFile)


def test_read_inside_of_a_linked_last_component_raises_linked_path(tree):
    root, outside = tree
    (root / "pkg" / "alias.py").symlink_to(outside / "mod.py")
    with pytest.raises(LinkedPath) as raised:
        read_inside(root, "pkg/alias.py", limit=100)
    assert raised.value.link == "pkg/alias.py"


def test_read_inside_returns_content_and_mode_and_none_for_missing(tree):
    root, _ = tree
    data, mode = read_inside(root, "pkg/mod.py", limit=100)  # type: ignore[misc]
    assert data == b"original\n" and stat.S_IMODE(mode) == stat.S_IMODE((root / "pkg/mod.py").stat().st_mode)
    assert read_inside(root, "pkg/none.py", limit=100) is None
    assert read_inside(root, "nodir/none.py", limit=100) is None


def test_read_inside_refuses_a_file_over_the_limit(tree):
    root, _ = tree
    with pytest.raises(UnsafeFile):
        read_inside(root, "pkg/mod.py", limit=3)


def test_write_inside_over_a_link_replaces_the_name_and_leaves_the_other_file(tree):
    root, outside = tree
    (root / "pkg" / "mod.py").unlink()
    (root / "pkg" / "mod.py").symlink_to(outside / "mod.py")
    write_inside(root, "pkg/mod.py", b"new\n")
    assert (outside / "mod.py").read_bytes() == b"outside\n"
    target = root / "pkg" / "mod.py"
    assert not target.is_symlink() and target.is_file() and target.read_bytes() == b"new\n"


def test_write_inside_over_a_hard_link_leaves_the_other_inode_alone(tree):
    root, outside = tree
    (root / "pkg" / "mod.py").unlink()
    os.link(outside / "mod.py", root / "pkg" / "mod.py")
    write_inside(root, "pkg/mod.py", b"new\n")
    assert (outside / "mod.py").read_bytes() == b"outside\n"
    assert (root / "pkg" / "mod.py").read_bytes() == b"new\n"


def test_write_inside_over_a_fifo_does_not_block_and_makes_a_regular_file(tree):
    root, _ = tree
    (root / "pkg" / "mod.py").unlink()
    os.mkfifo(root / "pkg" / "mod.py")
    write_inside(root, "pkg/mod.py", b"new\n")
    info = (root / "pkg" / "mod.py").lstat()
    assert stat.S_ISREG(info.st_mode) and (root / "pkg" / "mod.py").read_bytes() == b"new\n"


def test_read_inside_of_a_fifo_raises_unsafe_file_at_once(tree):
    root, _ = tree
    (root / "pkg" / "mod.py").unlink()
    os.mkfifo(root / "pkg" / "mod.py")
    with pytest.raises(UnsafeFile):
        read_inside(root, "pkg/mod.py", limit=100)


def test_write_inside_creates_missing_parents_as_real_directories(tree):
    root, _ = tree
    write_inside(root, "a/b/c.txt", b"x")
    assert (root / "a" / "b").is_dir() and not (root / "a").is_symlink()
    assert (root / "a/b/c.txt").read_bytes() == b"x"


def test_write_inside_applies_the_mode(tree):
    root, _ = tree
    write_inside(root, "pkg/run.sh", b"#!/bin/sh\n", mode=0o100755)
    assert stat.S_IMODE((root / "pkg/run.sh").stat().st_mode) == 0o755


def test_a_directory_at_the_name_raises_unsafe_file_and_leaves_no_temporary_file(tree):
    root, _ = tree
    (root / "pkg" / "sub").mkdir()
    with pytest.raises(UnsafeFile):
        write_inside(root, "pkg/sub", b"x")
    assert sorted(p.name for p in (root / "pkg").iterdir()) == ["mod.py", "sub"]
    with pytest.raises(UnsafeFile):
        unlink_inside(root, "pkg/sub")


def test_unlink_inside_removes_a_file_or_a_link_never_the_target(tree):
    root, outside = tree
    (root / "pkg" / "alias.py").symlink_to(outside / "mod.py")
    assert unlink_inside(root, "pkg/alias.py") is True
    assert (outside / "mod.py").read_bytes() == b"outside\n"
    assert unlink_inside(root, "pkg/mod.py") is True
    assert unlink_inside(root, "pkg/mod.py") is False
    assert unlink_inside(root, "nodir/file.py") is False


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/passwd", ""])
def test_a_parent_reference_or_absolute_path_raises_value_error(tree, bad):
    root, _ = tree
    for call in (
        lambda: read_inside(root, bad, limit=10),
        lambda: write_inside(root, bad, b"x"),
        lambda: unlink_inside(root, bad),
    ):
        with pytest.raises(ValueError):
            call()


def test_a_root_whose_own_path_holds_a_link_works(tree, tmp_path):
    root, _ = tree
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)  # the worktree's own absolute path may hold a link (/var)
    write_inside(alias, "pkg/new.py", b"ok\n")
    assert read_inside(alias, "pkg/new.py", limit=10) is not None
    assert (root / "pkg" / "new.py").read_bytes() == b"ok\n"
    assert linked_component(alias, "pkg/new.py") is None


def test_unlink_matching_inside_removes_matches_and_follows_nothing(tree):
    root, outside = tree
    cache = root / "pkg" / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-312.pyc").write_bytes(b"x")
    (cache / "other.cpython-312.pyc").write_bytes(b"x")
    assert unlink_matching_inside(root, "pkg/__pycache__", "mod.*.pyc") == 1
    assert [p.name for p in cache.iterdir()] == ["other.cpython-312.pyc"]
    shutil.rmtree(cache)
    (outside / "mod.cpython-312.pyc").write_bytes(b"outside")
    cache.symlink_to(outside)  # a linked last component is removed itself
    assert unlink_matching_inside(root, "pkg/__pycache__", "mod.*.pyc") == 0
    assert not cache.exists() and not cache.is_symlink()
    assert (outside / "mod.cpython-312.pyc").read_bytes() == b"outside"
    assert unlink_matching_inside(root, "nodir/__pycache__", "*.pyc") == 0


# --- a bounded prefix of a file (L4-SEC-042) --------------------------------------------------------------------------


def test_read_inside_prefix_returns_at_most_limit_bytes_of_a_large_file(tree):
    from l4.fsutil import read_inside_prefix

    root, _ = tree
    (root / "pkg" / "big.py").write_bytes(b"x" * 1000)
    data, mode = read_inside_prefix(root, "pkg/big.py", limit=100)
    assert data == b"x" * 100 and stat.S_ISREG(mode)
    assert read_inside_prefix(root, "pkg/mod.py", limit=100)[0] == b"original\n"
    assert read_inside_prefix(root, "pkg/none.py", limit=100) is None


def test_read_inside_prefix_never_follows_a_link_or_waits_for_a_fifo(tree):
    from l4.fsutil import read_inside_prefix

    root, outside = tree
    (root / "pkg" / "link.py").symlink_to(outside / "mod.py")
    with pytest.raises(LinkedPath):
        read_inside_prefix(root, "pkg/link.py", limit=10)
    os.mkfifo(root / "pkg" / "pipe.py")
    with pytest.raises(UnsafeFile):
        read_inside_prefix(root, "pkg/pipe.py", limit=10)
