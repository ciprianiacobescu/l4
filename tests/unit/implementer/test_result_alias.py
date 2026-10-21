"""M1.13 lines 1-3 (MAG, SPEC 8.1 prompt contract, L4-SEC-004): a short result path inside the worktree that is an alias
of the step's private directory, never a second place a result is read from."""

import os
import subprocess
from pathlib import Path

from l4.implementer import resultalias
from l4.implementer.workbench import HARNESS_EXCLUDES
from l4.security.protected import CONTRACT_PROTECTED_GLOBS, glob_match


def test_link_makes_the_alias_resolve_to_the_step_directory(tmp_path: Path):
    worktree, step = tmp_path / "wt", tmp_path / "units" / "agent-tmp"
    worktree.mkdir()
    step.mkdir(parents=True)
    resultalias.link(worktree, step)
    assert (worktree / ".l4-result").is_symlink()
    (worktree / resultalias.RESULT_ALIAS / "result.json").write_text("{}", encoding="utf-8")
    assert (step / "result.json").read_text(encoding="utf-8") == "{}"


def test_link_replaces_a_leftover_of_any_kind(tmp_path: Path):
    worktree, step = tmp_path / "wt", tmp_path / "agent-tmp"
    worktree.mkdir()
    step.mkdir()
    alias = worktree / ".l4-result"
    for leftover in ("symlink", "directory", "file"):
        if alias.is_symlink() or alias.is_file():
            alias.unlink()
        elif alias.is_dir():
            import shutil

            shutil.rmtree(alias)
        if leftover == "symlink":
            alias.symlink_to(tmp_path)
        elif leftover == "directory":
            alias.mkdir()
            (alias / "planted").write_text("x", encoding="utf-8")
        else:
            alias.write_text("x", encoding="utf-8")
        resultalias.link(worktree, step)
        assert alias.is_symlink() and alias.resolve() == step.resolve()


def test_drop_removes_the_alias_and_never_what_it_points_to(tmp_path: Path):
    worktree, step = tmp_path / "wt", tmp_path / "agent-tmp"
    worktree.mkdir()
    step.mkdir()
    (step / "result.json").write_text("{}", encoding="utf-8")
    resultalias.link(worktree, step)
    resultalias.drop(worktree)
    assert not (worktree / ".l4-result").exists() and not (worktree / ".l4-result").is_symlink()
    assert (step / "result.json").exists()
    resultalias.drop(worktree)  # nothing there: a no-op


def test_drop_removes_a_real_directory_without_following_a_link_inside_it(tmp_path: Path):
    worktree, outside = tmp_path / "wt", tmp_path / "outside"
    worktree.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    alias = worktree / ".l4-result"
    alias.mkdir()
    (alias / "result.json").write_text("{}", encoding="utf-8")
    (alias / "link").symlink_to(outside, target_is_directory=True)
    resultalias.drop(worktree)
    assert not alias.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return done.stdout


def test_the_alias_is_excluded_from_git_as_a_symlink_and_as_a_directory(tmp_path: Path):
    repo, step = tmp_path / "repo", tmp_path / "agent-tmp"
    repo.mkdir()
    step.mkdir()
    (step / "result.json").write_text("{}", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    excludes = tmp_path / "excludes"
    excludes.write_text("\n".join(HARNESS_EXCLUDES) + "\n", encoding="utf-8")
    config = ("-c", f"core.excludesFile={excludes}")
    (repo / "keep.txt").write_text("x", encoding="utf-8")
    for make in ("symlink", "directory"):
        resultalias.drop(repo)
        if make == "symlink":
            resultalias.link(repo, step)
        else:
            (repo / ".l4-result").mkdir()
            (repo / ".l4-result" / "result.json").write_text("{}", encoding="utf-8")
        assert ".l4-result" not in git(repo, *config, "status", "--porcelain", "--untracked-files=all")
        git(repo, *config, "add", "-A")
        assert ".l4-result" not in git(repo, "ls-files", "--cached")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    assert git(repo, "ls-tree", "-r", "--name-only", "HEAD").split() == ["keep.txt"]


def test_the_alias_is_a_contract_protected_path():
    assert any(glob_match(glob, ".l4-result/result.json") for glob in CONTRACT_PROTECTED_GLOBS)
    assert any(glob_match(glob, ".l4-result") for glob in CONTRACT_PROTECTED_GLOBS)
