from l4.vcs.refresh import refresh_remote_refs


def test_the_lock_refs_are_refreshed(make_repo, git_for):
    """`actions/checkout` fetches one ref and never `refs/l4/locks/*`: the fold would miss a hand-off."""
    git = git_for(make_repo(remote=True))
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is True
    [argv] = [a for a in git.history if "fetch" in a]
    assert "--prune" in argv and "+refs/l4/locks/*:refs/l4/locks/*" in argv


def test_no_fetch_leaves_the_lock_refs_alone(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1", fetch=False) is False
    assert not [a for a in git.history if "fetch" in a]
