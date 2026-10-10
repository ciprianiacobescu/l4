from l4.vcs.refresh import refresh_in_ci


def test_github_actions_refreshes_lock_refs(make_repo, git_for):
    """`actions/checkout` fetches one ref and never `refs/l4/locks/*`: the fold would miss a hand-off."""
    git = git_for(make_repo(remote=True))
    assert refresh_in_ci(git, environ={"GITHUB_ACTIONS": "true"}, branch_prefix="l4/", run_id="r1") is True
    [argv] = [a for a in git.history if "fetch" in a]
    assert "--prune" in argv and "+refs/l4/locks/*:refs/l4/locks/*" in argv


def test_other_environments_still_fetch_nothing(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    assert refresh_in_ci(git, environ={"GITHUB_ACTIONS": "false"}, branch_prefix="l4/", run_id="r1") is False
    assert not [a for a in git.history if "fetch" in a]
