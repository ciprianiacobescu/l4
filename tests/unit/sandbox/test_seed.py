import json
import os
from pathlib import Path

from l4.sandbox.seed import copy_seed, seed_complete, seed_dir, seed_key, write_seed_record

LOCK = b"version = 1\n"
SETUP = ["uv sync --frozen"]


def test_the_key_is_per_project_and_per_lock(tmp_path: Path):
    root = tmp_path / "cache"
    a = seed_dir(root, "https://git.example.test/team/one.git")
    assert a != seed_dir(root, "https://git.example.test/team/two.git")  # one project's members never fill another's
    assert a.parent.parent == root / "seed" and a.name == "uv"
    # a credential in the URL never reaches the key, nor the path
    with_token = seed_dir(root, "https://oauth2:glpat-SECRET0123456789@git.example.test/team/one.git")
    assert with_token == a and "SECRET" not in str(with_token)
    assert seed_dir(root, "git@git.example.test:team/one.git") == seed_dir(root, "ssh://git@git.example.test/team/one")
    assert seed_key(LOCK, SETUP) == seed_key(LOCK, SETUP)
    assert seed_key(LOCK, SETUP) != seed_key(LOCK + b"# new pin\n", SETUP)  # a new lock is a new seed
    assert seed_key(LOCK, SETUP) != seed_key(LOCK, ["uv sync"])  # and so is another setup


def filled(seed: Path, key: str = "k1") -> Path:
    (seed / "wheels").mkdir(parents=True)
    (seed / "wheels" / "pkg.whl").write_bytes(b"wheel bytes")
    (seed / "archive").mkdir()
    (seed / "archive" / "real.txt").write_text("real")
    os.symlink(seed / "archive" / "real.txt", seed / "archive" / "abs-link")  # points into the seed
    os.symlink("real.txt", seed / "archive" / "rel-link")
    os.symlink("/etc/hosts", seed / "archive" / "outside-link")  # points somewhere else: left as it is
    write_seed_record(seed, key, seconds=12.5)
    return seed


def test_copy_re_points_symlinks_into_the_copy(tmp_path: Path):
    seed = filled(tmp_path / "seed" / "h" / "uv")
    target = tmp_path / "units" / "u" / "cache" / "uv"
    assert copy_seed(seed, target, "k1") is True
    assert (target / "wheels" / "pkg.whl").read_bytes() == b"wheel bytes"
    assert os.readlink(target / "archive" / "abs-link") == str(target / "archive" / "real.txt")  # not into the seed
    assert (target / "archive" / "abs-link").read_text() == "real"
    assert os.readlink(target / "archive" / "rel-link") == "real.txt"
    assert os.readlink(target / "archive" / "outside-link") == "/etc/hosts"
    (target / "wheels" / "pkg.whl").write_bytes(b"changed by the unit")
    assert (seed / "wheels" / "pkg.whl").read_bytes() == b"wheel bytes"  # no inode is shared: the seed stays as it was
    assert (seed / "archive" / "real.txt").stat().st_ino != (target / "archive" / "real.txt").stat().st_ino


def test_a_non_empty_unit_cache_is_never_overwritten(tmp_path: Path):
    seed = filled(tmp_path / "seed" / "h" / "uv")
    target = tmp_path / "unit-cache"
    (target / "mine").mkdir(parents=True)
    (target / "mine" / "file").write_text("kept")
    assert copy_seed(seed, target, "k1") is False
    assert [p.name for p in target.iterdir()] == ["mine"] and (target / "mine" / "file").read_text() == "kept"
    empty = tmp_path / "empty-cache"
    empty.mkdir()  # `mount_caches` creates the directory: an empty one is new
    assert copy_seed(seed, empty, "k1") is True


def test_an_incomplete_seed_is_not_copied(tmp_path: Path):
    seed = tmp_path / "seed" / "h" / "uv"
    (seed / "wheels").mkdir(parents=True)
    (seed / "wheels" / "half.whl").write_bytes(b"cut off")  # a fill that never finished: no record
    assert seed_complete(seed, "k1") is False
    target = tmp_path / "unit-cache"
    assert copy_seed(seed, target, "k1") is False and not target.exists()
    write_seed_record(seed, "k1", seconds=1.0)
    assert seed_complete(seed, "k1") is True and seed_complete(seed, "another-key") is False
    assert copy_seed(seed, target, "another-key") is False  # the record is for a lock this unit does not have
    record = json.loads((seed.parent / "seed.json").read_text())
    assert record["key"] == "k1" and record["seconds"] == 1.0
