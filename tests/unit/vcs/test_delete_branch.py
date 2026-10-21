"""Deleting a merged branch under a lease, and the ref that keeps its verified head (squash-and-delete D6, 4.1): on a
local bare repository. A lease that holds deletes the branch and the local tracking ref; a branch a stranger pushed to
is kept; a branch that is not there is `gone`; the keep ref is create-only and idempotent."""

import pytest

from l4.vcs.git import BOT_IDENTITY
from l4.vcs.push import ForcedPushRefused, delete_branch, keep_ref, merged_ref

BRANCH = "l4/openspec/x"


@pytest.fixture
def world(make_repo, raw, git_for, trailers, tmp_path):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    (repo / "a.txt").write_text("a\n")
    git.run("add", "-A")
    head = git.commit("one", trailers, BOT_IDENTITY)
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    raw(repo, "fetch", "-q", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    origin = tmp_path / "repo-origin.git"

    def tip(ref: str) -> str:
        return raw(origin, "for-each-ref", "--format=%(objectname)", ref).strip()

    def stranger() -> str:
        other = tmp_path / "stranger"
        raw(tmp_path, "clone", "-q", str(origin), str(other))
        raw(other, "checkout", "-q", BRANCH)
        (other / "s.txt").write_text("s\n")
        raw(other, "add", "-A")
        raw(other, "commit", "-q", "-m", "a person's commit")
        raw(other, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}")
        return raw(other, "rev-parse", "HEAD").strip()

    return git, repo, head, tip, stranger


def test_a_lease_that_holds_deletes_the_branch_and_the_tracking_ref(world):
    git, repo, head, tip, _ = world
    assert git.rev_parse(f"refs/remotes/origin/{BRANCH}") == head
    assert delete_branch(git, BRANCH, head) == "deleted"
    assert tip(f"refs/heads/{BRANCH}") == ""
    assert git.rev_parse(f"refs/remotes/origin/{BRANCH}") is None


def test_a_branch_a_stranger_pushed_to_is_kept(world):
    git, repo, head, tip, stranger = world
    moved = stranger()
    assert delete_branch(git, BRANCH, head) == "kept"
    assert tip(f"refs/heads/{BRANCH}") == moved
    assert git.rev_parse(f"refs/remotes/origin/{BRANCH}") == head  # nothing was pushed, the tracking ref is as it was


def test_a_stranger_who_moves_the_tip_after_the_check_is_refused_by_the_server_lease(world, monkeypatch):
    git, repo, head, tip, stranger = world
    from l4.vcs import push

    real = push.remote_branch_tip
    moved = []

    def late(git_, branch, **kw):
        found = real(git_, branch, **kw)
        if not moved:
            moved.append(stranger())  # between the check and the push
        return found

    monkeypatch.setattr(push, "remote_branch_tip", late)
    assert delete_branch(git, BRANCH, head) == "kept"
    assert tip(f"refs/heads/{BRANCH}") == moved[0]


def test_a_branch_that_is_not_there_is_gone_not_an_error(world):
    git, repo, head, tip, _ = world
    assert delete_branch(git, "l4/openspec/never", head) == "gone"
    assert delete_branch(git, BRANCH, head) == "deleted"
    assert delete_branch(git, BRANCH, head) == "gone"


def test_the_delete_never_forces_and_takes_only_a_branch_and_a_sha(world):
    git, repo, head, tip, _ = world
    for bad in ("", "-d", "a..b", "refs/heads/x y"):
        with pytest.raises(ForcedPushRefused):
            delete_branch(git, bad, head)
    with pytest.raises(ForcedPushRefused):
        delete_branch(git, BRANCH, "not-a-sha")
    assert tip(f"refs/heads/{BRANCH}") == head


def test_the_keep_ref_is_create_only_and_idempotent(world, raw):
    git, repo, head, tip, _ = world
    ref = merged_ref("openspec:x")
    assert ref == "refs/l4/merged/openspec/x"
    assert keep_ref(git, ref, head) == "created"
    assert tip(ref) == head
    assert keep_ref(git, ref, head) == "present"  # the same sha again: fine
    other = raw(repo, "rev-parse", "main").strip()
    assert keep_ref(git, ref, other) == "differs"  # never moved
    assert tip(ref) == head


def test_the_keep_ref_takes_only_the_merged_namespace(world):
    git, repo, head, tip, _ = world
    for bad in ("refs/heads/main", "refs/l4/locks/openspec/x", "refs/l4/merged/../x"):
        with pytest.raises(ForcedPushRefused):
            keep_ref(git, bad, head)
