"""`_release_branch` frees the unit branch from this clone's own leftovers only (L4-WTR-001, review 7)."""

import shutil
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.vcs.names import UnitNames
from l4.vcs.repokey import repository_key
from l4.vcs.worktree import WorktreeManager


def _names(cache: Path, key: str, unit: str = "openspec:x") -> UnitNames:
    return UnitNames.for_unit(unit, branch_prefix="l4/", cache=cache, repo_key=key)


def _manager(git_for, repo: Path, cache: Path) -> WorktreeManager:
    return WorktreeManager(git_for(repo), base_branch="main", branch_prefix="l4/", cache=cache)


def test_a_stale_registration_where_another_project_now_has_a_checkout_is_refused(
    make_repo, git_for, raw, tmp_path: Path, git_environ
):
    """R1: the registration is ours but the directory holds project B's checkout and its uncommitted file."""
    a = make_repo("a", remote=True)
    b = make_repo("b", remote=True)
    cache = tmp_path / "cache"
    old = cache / "worktrees" / "openspec" / "x"
    old.parent.mkdir(parents=True, exist_ok=True)
    raw(a, "worktree", "add", "-q", "-B", "l4/openspec/x", str(old), "origin/main")
    shutil.rmtree(old)  # by hand, without `git worktree prune`
    raw(b, "worktree", "add", "-q", "-B", "l4/openspec/x", str(old), "origin/main")
    (old / "THEIR_WORK.txt").write_text("uncommitted\n")
    assert repository_key(a, git_environ) != repository_key(b, git_environ)
    with pytest.raises(L4Exit) as caught:
        _manager(git_for, a, cache).ensure(_names(cache, repository_key(a, git_environ)))
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert str(old.resolve()) in str(caught.value)
    assert (old / "THEIR_WORK.txt").exists()


def test_the_clone_itself_under_the_cache_with_the_branch_is_never_deleted(git_for, raw, tmp_path: Path, git_environ):
    """R9: the main worktree of the clone is not a leftover, wherever it lies."""
    cache = tmp_path / "cache"
    bare = tmp_path / "origin.git"
    raw(tmp_path, "init", "-q", "--bare", str(bare))
    clone = cache / "worktrees" / "clone"
    clone.mkdir(parents=True)
    raw(clone, "init", "-q")
    (clone / "README.md").write_text("hello\n")
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "init")
    raw(clone, "remote", "add", "origin", str(bare))
    raw(clone, "push", "-q", "origin", "main")
    raw(clone, "fetch", "-q", "origin")
    raw(clone, "checkout", "-q", "-b", "l4/openspec/x")
    (clone / "MINE.txt").write_text("work\n")
    with pytest.raises(L4Exit) as caught:
        _manager(git_for, clone, cache).ensure(_names(cache, repository_key(clone, git_environ)))
    assert caught.value.code == ExitCode.USAGE_ERROR and "main worktree" in str(caught.value)
    assert (clone / ".git").exists() and (clone / "MINE.txt").exists()


def test_the_main_checkout_outside_the_cache_holding_the_branch_is_refused(
    make_repo, git_for, raw, tmp_path: Path, git_environ
):
    a = make_repo("a", remote=True)
    raw(a, "checkout", "-q", "-b", "l4/openspec/x")
    (a / "MINE.txt").write_text("work\n")
    cache = tmp_path / "cache"
    with pytest.raises(L4Exit) as caught:
        _manager(git_for, a, cache).ensure(_names(cache, repository_key(a, git_environ)))
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert (a / "MINE.txt").exists()


def test_a_worktrees_directory_that_is_a_symlink_to_another_name_is_still_the_cache(
    make_repo, git_for, raw, tmp_path: Path, git_environ
):
    """R3b: "under the cache" is decided by the cache path, not by a directory called `worktrees`."""
    a = make_repo("a", remote=True)
    cache = tmp_path / "cache"
    cache.mkdir()
    store = tmp_path / "wt-store"
    store.mkdir()
    (cache / "worktrees").symlink_to(store)
    old = cache / "worktrees" / "openspec" / "x"
    old.parent.mkdir(parents=True, exist_ok=True)
    raw(a, "worktree", "add", "-q", "-B", "l4/openspec/x", str(old), "origin/main")
    names = _names(cache, repository_key(a, git_environ))
    assert _manager(git_for, a, cache).ensure(names).path == names.worktree
    assert not (store / "openspec" / "x").exists()


def test_a_symlinked_cache_root_is_the_cache(make_repo, git_for, raw, tmp_path: Path, git_environ):
    a = make_repo("a", remote=True)
    real = tmp_path / "real-cache"
    real.mkdir()
    link = tmp_path / "cache-link"
    link.symlink_to(real)
    old = link / "worktrees" / "openspec" / "x"
    old.parent.mkdir(parents=True, exist_ok=True)
    raw(a, "worktree", "add", "-q", "-B", "l4/openspec/x", str(old), "origin/main")
    names = _names(link, repository_key(a, git_environ))
    assert _manager(git_for, a, link).ensure(names).path == names.worktree
    assert not (real / "worktrees" / "openspec" / "x").exists()


def test_a_locked_old_registration_is_removed_too(make_repo, git_for, raw, tmp_path: Path, git_environ):
    """R6: one `--force` does not remove a locked registration; two do."""
    a = make_repo("a", remote=True)
    cache = tmp_path / "cache"
    old = cache / "worktrees" / "openspec" / "x"
    old.parent.mkdir(parents=True, exist_ok=True)
    raw(a, "worktree", "add", "-q", "-B", "l4/openspec/x", str(old), "origin/main")
    raw(a, "worktree", "lock", "--reason", "person", str(old))
    names = _names(cache, repository_key(a, git_environ))
    assert _manager(git_for, a, cache).ensure(names).path == names.worktree
    assert not old.exists()
    assert str(old.resolve()) not in raw(a, "worktree", "list", "--porcelain")


def test_a_unit_named_worktrees_has_its_old_leftover_removed(make_repo, git_for, raw, tmp_path: Path, git_environ):
    """R7: the unit's own name is no landmark for the cache root."""
    a = make_repo("a", remote=True)
    cache = tmp_path / "cache"
    old = cache / "worktrees" / "openspec" / "worktrees"
    old.parent.mkdir(parents=True, exist_ok=True)
    raw(a, "worktree", "add", "-q", "-B", "l4/openspec/worktrees", str(old), "origin/main")
    names = _names(cache, repository_key(a, git_environ), unit="openspec:worktrees")
    assert _manager(git_for, a, cache).ensure(names).path == names.worktree
    assert not old.exists()
