from pathlib import Path

import pytest

from l4.forge.base import PullRequest
from l4.postmerge import MergeDetector, MergeVerdict
from l4.vcs.git import BOT_IDENTITY

BRANCH = "l4/openspec/add-x"
FOLDER = Path("openspec/changes/add-x")
IDENTITY = (("user.name", "h"), ("user.email", "h@example.invalid"))


def pr(sha: str | None, state: str = "merged") -> PullRequest:
    return PullRequest(7, "https://gl.example.test/-/merge_requests/7", BRANCH, "main", "[l4] add-x", False, state, (),
                       sha)  # type: ignore[arg-type]  # fmt: skip


@pytest.fixture
def world(make_repo, git_for, raw, trailers):
    """main holds the change folder; the unit branch adds a file; a human merges it with a merge commit."""
    repo = make_repo(remote=True)
    git = git_for(repo)
    (repo / FOLDER).mkdir(parents=True)
    (repo / FOLDER / "tasks.md").write_text("- [x] 1.1 a\n")
    git.run("add", "-A")
    git.commit("add the change", trailers, BOT_IDENTITY)

    class World:
        def merge(self, *, archive_in_merge: bool = False) -> str:
            git.run("checkout", "-q", "-b", BRANCH)
            (repo / "code.py").write_text("x = 1\n")
            if archive_in_merge:
                git.run("rm", "-q", "-r", FOLDER.as_posix())
            git.run("add", "-A")
            git.commit("implement", trailers, BOT_IDENTITY)
            git.run("checkout", "-q", "main")
            git.run("merge", "-q", "--no-ff", "-m", "Merge branch", BRANCH, config=IDENTITY)
            return git.rev_parse("HEAD")

    w = World()
    w.repo, w.git, w.raw = repo, git, raw  # type: ignore[attr-defined]
    return w


def detector(world) -> MergeDetector:
    return MergeDetector(world.git, base_branch="main")


def test_unarchived_tree_at_merge_commit_needs_archive(world):
    sha = world.merge()
    assert detector(world).classify(pr(sha), "add-x") is MergeVerdict.NEEDS_ARCHIVE


def test_a_tree_without_the_folder_is_archived(world):
    sha = world.merge(archive_in_merge=True)
    assert detector(world).classify(pr(sha), "add-x") is MergeVerdict.ARCHIVED


def test_history_without_archive_commit_is_not_decisive(world, trailers):
    """A commit that says 'archive' and a tree that still holds the folder: the tree wins, in both directions."""
    world.git.run("commit", "-q", "--allow-empty", "-m", "chore(add-x): archive", config=IDENTITY)
    sha = world.merge()
    assert detector(world).classify(pr(sha), "add-x") is MergeVerdict.NEEDS_ARCHIVE
    world.git.run("rm", "-q", "-r", FOLDER.as_posix())  # a later removal does not change the answer at the merge sha
    world.git.commit("remove", trailers, BOT_IDENTITY)
    assert detector(world).classify(pr(sha), "add-x") is MergeVerdict.NEEDS_ARCHIVE


def test_a_merge_without_a_merge_commit_asks_the_head_of_the_base(world):
    world.merge()
    world.git.fetch("origin")
    world.raw(world.repo, "push", "-q", "origin", "main")
    world.git.fetch("origin")
    assert detector(world).classify(pr(None), "add-x") is MergeVerdict.NEEDS_ARCHIVE


def test_a_merge_commit_that_is_not_in_the_clone_is_unknown_after_one_fetch(world):
    world.merge()
    assert detector(world).classify(pr("f" * 40), "add-x") is MergeVerdict.UNKNOWN
    fetches = [a for a in world.git.history if a[:2] == ["git", "-c"] and "fetch" in a]
    assert len(fetches) == 1


def test_a_merge_commit_the_fetch_brings_is_read(world, tmp_path):
    sha = world.merge()
    world.raw(world.repo, "push", "-q", "origin", "main")
    other = tmp_path / "ci-clone"
    world.raw(tmp_path, "clone", "-q", str(tmp_path / "repo-origin.git"), str(other))
    ci = world.git.at(other)
    world.raw(other, "update-ref", "-d", "refs/remotes/origin/main")
    world.raw(other, "reset", "-q", "--hard", f"{sha}~1")  # a clone that has not caught up
    world.raw(other, "gc", "-q", "--prune=now")
    assert MergeDetector(ci, base_branch="main").classify(pr(sha), "add-x") is MergeVerdict.NEEDS_ARCHIVE


@pytest.mark.parametrize("state", ["open", "closed"])
def test_only_a_merged_mr_is_classified(world, state):
    with pytest.raises(ValueError, match="not merged"):
        detector(world).classify(pr(None, state), "add-x")
