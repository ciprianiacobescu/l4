"""worktree.snapshot and worktree.clean (review-resolution 1.10, L4-YOLO-026): a commit of the working tree that
leaves HEAD, the index and every ref alone."""

import subprocess
from pathlib import Path

import pytest

from l4.vcs.git import Git
from l4.yolo import worktree
from l4.yolo.digest import unit_digest

FOLDER = "openspec/changes/add-x"
PLAN = "plan.md"


def sh(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    sh(root, "init", "-q", "-b", "main")
    write(root, ".gitignore", "*.log\n")
    write(root, PLAN, "plan\n")
    write(root, f"{FOLDER}/proposal.md", "why\n")
    write(root, f"{FOLDER}/tasks.md", "- [ ] 1.1 a\n")
    write(root, "other.txt", "other\n")
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "c")
    return root


@pytest.fixture
def git(repo: Path, tmp_path: Path) -> Git:
    return Git(
        repo, environ={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "L4_CACHE": str(tmp_path / "cache")}
    )


def state(repo: Path) -> tuple[str, str, str, str]:
    return (
        sh(repo, "rev-parse", "HEAD"),
        sh(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        sh(repo, "for-each-ref"),
        sh(repo, "ls-files", "-s"),
    )


def test_untracked_file_is_in_the_snapshot_and_nothing_else_moves(repo: Path, git: Git) -> None:
    write(repo, f"{FOLDER}/specs/x/spec.md", "new\n")
    write(repo, f"{FOLDER}/tasks.md", "- [ ] 1.1 changed\n")
    before = state(repo)
    sha = worktree.snapshot(git, [PLAN, FOLDER])
    assert state(repo) == before
    assert git.rev_parse(sha) == sha
    assert sh(repo, "show", f"{sha}:{FOLDER}/specs/x/spec.md") == "new\n"
    assert sh(repo, "show", f"{sha}:{FOLDER}/tasks.md") == "- [ ] 1.1 changed\n"
    assert sh(repo, "rev-parse", f"{sha}^").strip() == before[0].strip()


def test_ignored_file_is_not_in_the_snapshot(repo: Path, git: Git) -> None:
    write(repo, f"{FOLDER}/debug.log", "noise\n")
    sha = worktree.snapshot(git, [PLAN, FOLDER])
    assert "debug.log" not in sh(repo, "ls-tree", "-r", "--name-only", sha)


def test_paths_outside_the_list_keep_the_head_state(repo: Path, git: Git) -> None:
    write(repo, "other.txt", "edited\n")
    sha = worktree.snapshot(git, [PLAN, FOLDER])
    assert sh(repo, "show", f"{sha}:other.txt") == "other\n"


def test_a_deleted_file_is_deleted_in_the_snapshot(repo: Path, git: Git) -> None:
    (repo / FOLDER / "proposal.md").unlink()
    sha = worktree.snapshot(git, [PLAN, FOLDER])
    assert "proposal.md" not in sh(repo, "ls-tree", "-r", "--name-only", sha)


def test_the_same_tree_gives_the_same_sha(repo: Path, git: Git) -> None:
    write(repo, f"{FOLDER}/tasks.md", "- [ ] 1.1 changed\n")
    assert worktree.snapshot(git, [PLAN, FOLDER]) == worktree.snapshot(git, [PLAN, FOLDER])


def test_a_staged_index_is_not_read_or_changed(repo: Path, git: Git) -> None:
    write(repo, "other.txt", "staged\n")
    sh(repo, "add", "other.txt")
    write(repo, f"{FOLDER}/tasks.md", "- [ ] 1.1 changed\n")
    before = state(repo)
    sha = worktree.snapshot(git, [PLAN, FOLDER])
    assert state(repo) == before
    assert sh(repo, "show", f"{sha}:other.txt") == "other\n"


def test_unit_digest_at_the_snapshot_equals_the_digest_of_a_commit_of_the_same_content(repo: Path, git: Git) -> None:
    write(repo, f"{FOLDER}/specs/x/spec.md", "new\n")
    snap = worktree.snapshot(git, [PLAN, FOLDER])
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "same")
    assert unit_digest(git, snap, FOLDER) == unit_digest(git, "HEAD", FOLDER)


def test_a_repository_without_head_snapshots_against_an_empty_tree(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    sh(root, "init", "-q", "-b", "main")
    write(root, PLAN, "plan\n")
    g = Git(
        root, environ={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "L4_CACHE": str(tmp_path / "cache")}
    )
    sha = worktree.snapshot(g, [PLAN])
    assert sh(root, "show", f"{sha}:{PLAN}") == "plan\n"
    assert sh(root, "rev-list", "--parents", "-n1", sha).split() == [sha]
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root, capture_output=True).returncode != 0


def test_clean_true_when_nothing_changed(repo: Path, git: Git) -> None:
    assert worktree.clean(git, [PLAN, FOLDER])


@pytest.mark.parametrize("kind", ["untracked", "unstaged", "staged", "deleted"])
def test_clean_false_for_each_kind_of_change(repo: Path, git: Git, kind: str) -> None:
    if kind == "untracked":
        write(repo, f"{FOLDER}/new.md", "x\n")
    elif kind == "unstaged":
        write(repo, PLAN, "edited\n")
    elif kind == "staged":
        write(repo, PLAN, "edited\n")
        sh(repo, "add", PLAN)
    else:
        (repo / FOLDER / "proposal.md").unlink()
    assert not worktree.clean(git, [PLAN, FOLDER])


def test_clean_ignores_changes_outside_the_paths(repo: Path, git: Git) -> None:
    write(repo, "other.txt", "edited\n")
    assert worktree.clean(git, [PLAN, FOLDER])
