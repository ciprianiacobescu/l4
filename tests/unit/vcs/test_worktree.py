from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.vcs.git import BOT_IDENTITY, GitError
from l4.vcs.names import UnitNames
from l4.vcs.worktree import WorktreeManager


@pytest.fixture
def names(tmp_path: Path) -> UnitNames:
    return UnitNames.for_unit("openspec:x", branch_prefix="l4/", cache=tmp_path / "cache")


def test_created_from_base_when_branch_absent(make_repo, git_for, raw, names, tmp_path: Path):
    repo = make_repo(remote=True)
    base_head = raw(repo, "rev-parse", "origin/main").strip()
    # main moves on the remote after the clone: ensure() must fetch it
    other = tmp_path / "other"
    raw(tmp_path, "clone", "-q", str(tmp_path / "repo-origin.git"), str(other))
    (other / "n.txt").write_text("n\n")
    raw(other, "add", "-A")
    raw(other, "commit", "-q", "-m", "newer")
    raw(other, "push", "-q", "origin", "main")
    newer = raw(other, "rev-parse", "HEAD").strip()
    assert newer != base_head

    worktree = WorktreeManager(git_for(repo), base_branch="main", branch_prefix="l4/").ensure(names)
    assert worktree.path == names.worktree and worktree.source == "base"
    assert repo.resolve() not in worktree.path.resolve().parents  # outside the repository
    assert worktree.head == newer and (worktree.path / "n.txt").exists()
    assert raw(worktree.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "l4/openspec/x"
    assert raw(repo, "status", "--porcelain").strip() == ""  # the main checkout is untouched


def test_created_from_existing_remote_branch(make_repo, git_for, raw, names, tmp_path: Path, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", "l4/openspec/x")
    (repo / "work.txt").write_text("checkpoint\n")
    git.run("add", "-A")
    pushed = git.commit("checkpoint", trailers, BOT_IDENTITY)
    git.push("origin", ["HEAD:refs/heads/l4/openspec/x"])
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", "l4/openspec/x")  # a different runner has no local branch

    worktree = WorktreeManager(git, base_branch="main", branch_prefix="l4/").ensure(names)
    assert worktree.source == "remote_branch" and worktree.head == pushed
    assert (worktree.path / "work.txt").read_text() == "checkpoint\n"


def test_an_existing_worktree_is_removed_and_recreated_never_reused(make_repo, git_for, raw, names):
    repo = make_repo(remote=True)
    manager = WorktreeManager(git_for(repo), base_branch="main", branch_prefix="l4/")
    first = manager.ensure(names)
    (first.path / "dirty.txt").write_text("leftover of a crashed run\n")
    raw(first.path, "checkout", "-q", "--detach")  # and a state the next run must not inherit
    second = manager.ensure(names)
    assert second.path == first.path and not (second.path / "dirty.txt").exists()
    assert raw(second.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "l4/openspec/x"
    assert [
        line for line in raw(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree")
    ] == [
        f"worktree {repo.resolve()}",
        f"worktree {second.path.resolve()}",
    ]


def test_leftover_directory_that_is_not_a_registered_worktree_is_replaced(make_repo, git_for, names):
    repo = make_repo(remote=True)
    names.worktree.mkdir(parents=True)
    (names.worktree / "junk").write_text("x")
    worktree = WorktreeManager(git_for(repo), base_branch="main", branch_prefix="l4/").ensure(names)
    assert not (worktree.path / "junk").exists() and (worktree.path / "README.md").exists()


def test_a_worktree_path_inside_the_repository_is_refused(make_repo, git_for):
    repo = make_repo(remote=True)
    inside = UnitNames.for_unit("openspec:x", branch_prefix="l4/", cache=repo / ".l4-cache")
    with pytest.raises(L4Exit) as err:
        WorktreeManager(git_for(repo), base_branch="main", branch_prefix="l4/").ensure(inside)
    assert err.value.code is ExitCode.USAGE_ERROR and not (repo / ".l4-cache").exists()


def test_missing_base_branch_is_a_git_error(make_repo, git_for, names):
    repo = make_repo(remote=True)
    with pytest.raises(GitError, match="base branch"):
        WorktreeManager(git_for(repo), base_branch="nope", branch_prefix="l4/").ensure(names)


def test_another_repositorys_worktree_at_the_same_path_is_not_deleted(make_repo, git_for, raw, names, tmp_path: Path):
    repo = make_repo(remote=True)
    other_origin = tmp_path / "other-origin"
    raw(tmp_path, "clone", "-q", str(tmp_path / "repo-origin.git"), str(other_origin))
    other_manager = WorktreeManager(git_for(other_origin), base_branch="main", branch_prefix="l4/")
    theirs = other_manager.ensure(names)  # the other project's live worktree, same cache path
    (theirs.path / "wip.txt").write_text("their uncommitted work\n")
    with pytest.raises(L4Exit, match="another repository"):
        WorktreeManager(git_for(repo), base_branch="main", branch_prefix="l4/").ensure(names)
    assert (theirs.path / "wip.txt").read_text() == "their uncommitted work\n"
    other_manager.ensure(names)  # its own path is still replaced as before
    assert not (theirs.path / "wip.txt").exists()


def test_fetch_uses_the_credential_helper_it_was_given(make_repo, git_for, names):
    repo = make_repo(remote=True)
    git = git_for(repo)
    seen: list[tuple] = []
    real = git.fetch
    git.fetch = lambda remote, **kw: (seen.append(tuple(kw["config"])), real(remote, **kw))[1]  # type: ignore[method-assign]
    helper = (("credential.helper", ""), ("credential.helper", "!f() { :; }; f"))
    WorktreeManager(git, base_branch="main", branch_prefix="l4/", fetch_config=helper).ensure(names)
    assert seen == [helper]


def push_unit_branch(repo, git, trailers, name: str = "l4/openspec/x") -> str:
    git.run("checkout", "-q", "-b", name)
    (repo / "work.txt").write_text("checkpoint\n")
    git.run("add", "-A")
    sha = git.commit("checkpoint", trailers, BOT_IDENTITY)
    git.push("origin", [f"HEAD:refs/heads/{name}"])
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", name)
    return sha


def test_pruned_branch_is_not_resurrected(make_repo, git_for, raw, names, tmp_path: Path, trailers):
    """The project deletes merged source branches; a stale `origin/l4/...` must not bring the unit back."""
    repo = make_repo(remote=True)
    git = git_for(repo)
    manager = WorktreeManager(git, base_branch="main", branch_prefix="l4/")
    pushed = push_unit_branch(repo, git, trailers)
    first = manager.ensure(names)
    assert first.source == "remote_branch" and first.head == pushed
    bare = tmp_path / "repo-origin.git"
    raw(bare, "branch", "-D", "l4/openspec/x")  # merged and removed on the forge
    second = manager.ensure(names)
    assert second.source == "base" and not (second.path / "work.txt").exists()
    assert second.head == raw(repo, "rev-parse", "origin/main").strip()
    assert git.rev_parse("refs/remotes/origin/l4/openspec/x") is None


def test_ensure_fetches_and_prunes_the_lock_refs_but_leaves_other_refs_alone(
    make_repo, git_for, raw, names, tmp_path: Path
):  # fmt: skip
    repo = make_repo(remote=True)
    git = git_for(repo)
    bare = tmp_path / "repo-origin.git"
    head = raw(repo, "rev-parse", "HEAD").strip()
    raw(bare, "update-ref", names.lock_ref, head)
    manager = WorktreeManager(git, base_branch="main", branch_prefix="l4/")
    manager.ensure(names)
    assert git.rev_parse(names.lock_ref) == head  # the lock refs are outside the default refspec
    raw(repo, "update-ref", "refs/l4/elsewhere", head)
    raw(bare, "update-ref", "-d", names.lock_ref)
    manager.ensure(names)
    assert git.rev_parse(names.lock_ref) is None and git.rev_parse("refs/l4/elsewhere") == head


def test_a_branch_of_another_prefix_is_not_pruned(make_repo, git_for, raw, names, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("branch", "feature")
    git.push("origin", ["feature:refs/heads/feature"])
    git.fetch("origin")
    WorktreeManager(git, base_branch="main", branch_prefix="l4/").ensure(names)
    assert git.rev_parse("refs/remotes/origin/feature") is not None
