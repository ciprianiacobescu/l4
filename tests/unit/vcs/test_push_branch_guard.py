"""W-D2 (SAFETY): the unit branch is pushed under a lease on what the harness last saw. A branch a person deleted is
never recreated (job 6051: the orphaned `l4 run` would have pushed it back), a branch a person moved is not forced."""

import pytest

from l4.vcs.git import BOT_IDENTITY
from l4.vcs.push import ForcedPushRefused, PushRejected, build_branch_push_args

BRANCH = "l4/openspec/x"
REF = f"refs/heads/{BRANCH}"
SHA = "a" * 40


def test_the_branch_push_is_a_lease_on_the_last_seen_value_never_a_plus_refspec():
    assert build_branch_push_args("origin", BRANCH, SHA) == [
        "push", f"--force-with-lease={REF}:{SHA}", "--", "origin", f"HEAD:{REF}"
    ]  # fmt: skip
    assert build_branch_push_args("origin", BRANCH, "")[1] == f"--force-with-lease={REF}:"  # must not exist yet


@pytest.mark.parametrize("bad", ["", "-x", "a b", "a..b", "x/", "+x"])
def test_a_bad_branch_name_is_refused_before_git_runs(bad):
    with pytest.raises(ForcedPushRefused):
        build_branch_push_args("origin", bad, SHA)


def test_a_bad_expected_value_or_remote_is_refused():
    with pytest.raises(ForcedPushRefused):
        build_branch_push_args("origin", BRANCH, "not-a-sha")
    with pytest.raises(ForcedPushRefused):
        build_branch_push_args("-o", BRANCH, SHA)


def _commit(git, repo, name, trailers):
    (repo / name).write_text(name)
    git.run("add", "-A")
    return git.commit(name, trailers, BOT_IDENTITY)


def test_a_first_push_and_a_fast_forward_work(make_repo, raw, git_for, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    second = _commit(git, repo, "b.txt", trailers)
    git.push_branch("origin", BRANCH)
    assert raw(repo, "ls-remote", "origin", REF).split()[0] == second


def test_a_deleted_branch_is_not_recreated(make_repo, raw, git_for, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    raw(repo, "push", "origin", "--delete", BRANCH)  # the owner deletes the branch (the tracking ref stays)
    _commit(git, repo, "b.txt", trailers)
    with pytest.raises(PushRejected):
        git.push_branch("origin", BRANCH)
    assert raw(repo, "ls-remote", "origin", REF).strip() == ""


def test_a_deleted_branch_stays_deleted_even_when_a_fetch_pruned_the_tracking_ref(make_repo, raw, git_for, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    raw(repo, "push", "origin", "--delete", BRANCH)
    git.fetch("origin", prune=True)
    assert git.rev_parse(f"refs/remotes/origin/{BRANCH}") is None
    _commit(git, repo, "b.txt", trailers)
    with pytest.raises(PushRejected):
        git.push_branch("origin", BRANCH)
    assert raw(repo, "ls-remote", "origin", REF).strip() == ""


def test_a_branch_a_person_moved_is_not_forced(make_repo, raw, git_for, trailers, tmp_path):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    other = tmp_path / "human"
    raw(tmp_path, "clone", "-q", "--branch", BRANCH, raw(repo, "remote", "get-url", "origin").strip(), str(other))
    (other / "h.txt").write_text("h")
    raw(other, "add", "-A")
    raw(other, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "human")
    raw(other, "push", "-q", "origin", BRANCH)
    human = raw(other, "rev-parse", "HEAD").strip()
    _commit(git, repo, "b.txt", trailers)
    with pytest.raises(PushRejected):
        git.push_branch("origin", BRANCH)
    assert raw(repo, "ls-remote", "origin", REF).split()[0] == human


def test_a_local_branch_that_does_not_contain_the_remote_one_is_refused_without_asking_the_server(
    make_repo, raw, git_for, trailers
):
    """`--force-with-lease` would force when the lease holds, so fast-forward is checked first."""
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    first = _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    _commit(git, repo, "b.txt", trailers)
    git.push_branch("origin", BRANCH)
    git.run("reset", "-q", "--hard", first)  # local is now behind: a push would rewind the remote
    _commit(git, repo, "c.txt", trailers)
    before = len(git.history)
    with pytest.raises(PushRejected):
        git.push_branch("origin", BRANCH)
    assert not any("push" in argv for argv in git.history[before:])


def test_no_git_push_of_any_kind_runs_after_a_cancel(make_repo, git_for, trailers):
    """W-D2: the unit branch, a lock ref lease, a retire and a plain push all stop at the one chokepoint."""
    import signal

    from l4 import cancel
    from l4.cancel import RunCancelled

    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    before = list(git.history)
    cancel.request(signal.SIGTERM)
    try:
        with pytest.raises(RunCancelled):
            git.push_branch("origin", BRANCH)
        with pytest.raises(RunCancelled):
            git.push("origin", [f"HEAD:{REF}"])
        with pytest.raises(RunCancelled):
            git.push_lease("origin", SHA, "refs/l4/locks/openspec/x", "")
        with pytest.raises(RunCancelled):
            git.retire_lock_ref("origin", SHA, "refs/l4/locks/openspec/x", "refs/l4/archived/openspec/x")
    finally:
        cancel.reset()
    assert not [argv for argv in git.history[len(before) :] if "push" in argv]


def test_pushes_work_in_a_checkout_whose_remote_has_no_fetch_refspec(make_repo, raw, git_for, trailers):
    """A remote without a configured fetch refspec covering the unit branch (a `--single-branch` or shallow clone, a
    remote set up with `git config remote.origin.url`) gets no tracking-ref update from a push. The second push of a
    run must lease on what the first one pushed, not on the stale tracking ref: a fast-forward is never refused."""
    repo = make_repo(remote=True)
    raw(repo, "config", "--unset-all", "remote.origin.fetch")
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    raw(repo, "fetch", "-q", "origin", f"+{REF}:refs/remotes/origin/{BRANCH}")  # what a worktree refresh does
    _commit(git, repo, "b.txt", trailers)
    git.push_branch("origin", BRANCH)
    third = _commit(git, repo, "c.txt", trailers)
    git.push_branch("origin", BRANCH)
    assert raw(repo, "ls-remote", "origin", REF).split()[0] == third
    assert git.rev_parse(f"refs/remotes/origin/{BRANCH}") == third  # the tracking ref follows, as git's own does


def test_a_new_process_resumes_from_the_tracking_ref_and_a_human_commit_on_the_branch(
    make_repo, raw, git_for, trailers, tmp_path
):
    """The next run (a new process, a new `Git`) starts from the remote branch a person added a commit to: its push
    is a fast-forward of that commit and lands."""
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", BRANCH)
    _commit(git, repo, "a.txt", trailers)
    git.push_branch("origin", BRANCH)
    other = tmp_path / "human2"
    raw(tmp_path, "clone", "-q", "--branch", BRANCH, raw(repo, "remote", "get-url", "origin").strip(), str(other))
    (other / "h.txt").write_text("h")
    raw(other, "add", "-A")
    raw(other, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "human")
    raw(other, "push", "-q", "origin", BRANCH)
    raw(repo, "fetch", "-q", "--prune", "origin", "+refs/heads/l4/*:refs/remotes/origin/l4/*")
    nxt = git_for(repo)
    nxt.run("reset", "-q", "--hard", f"refs/remotes/origin/{BRANCH}")
    mine = _commit(nxt, repo, "b.txt", trailers)
    nxt.push_branch("origin", BRANCH)
    assert raw(repo, "ls-remote", "origin", REF).split()[0] == mine
