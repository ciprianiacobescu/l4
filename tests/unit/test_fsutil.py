import os
from pathlib import Path

import pytest

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file


def test_atomic_write_replaces_and_keeps_mode(tmp_path: Path):
    target = tmp_path / "f.txt"
    target.write_bytes(b"old")
    target.chmod(0o640)
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new" and target.stat().st_mode & 0o777 == 0o640
    fresh = tmp_path / "fresh.txt"
    atomic_write_bytes(fresh, b"x")
    assert fresh.read_bytes() == b"x"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]


def test_failed_write_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "f.txt"
    target.write_bytes(b"old")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["f.txt"]


def test_read_regular_file_refuses_symlinks_directories_and_oversize(tmp_path: Path):
    real = tmp_path / "real.md"
    real.write_bytes(b"12345")
    assert read_regular_file(real, limit=5) == b"12345"
    with pytest.raises(UnsafeFile, match="larger"):
        read_regular_file(real, limit=4)
    (tmp_path / "link.md").symlink_to(real)
    with pytest.raises(UnsafeFile, match="symlink"):
        read_regular_file(tmp_path / "link.md", limit=100)
    with pytest.raises(UnsafeFile, match="regular"):
        read_regular_file(tmp_path, limit=100)
    with pytest.raises(FileNotFoundError):
        read_regular_file(tmp_path / "nope", limit=100)


def test_atomic_write_syncs_the_file_and_the_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr("l4.fsutil.os.fsync", lambda fd: (synced.append(fd), real(fd))[1])
    atomic_write_bytes(tmp_path / "f.txt", b"x")
    assert len(synced) == 2
