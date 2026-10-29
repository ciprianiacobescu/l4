from pathlib import Path

from l4.vcs.refresh import refresh_in_ci, unit_refspecs

CI = {"GITLAB_CI": "true"}


def test_refspecs_cover_the_unit_branches_and_the_lock_refs():
    assert unit_refspecs("l4/") == (
        "+refs/heads/l4/*:refs/remotes/origin/l4/*",
        "+refs/l4/locks/*:refs/l4/locks/*",
    )
    assert unit_refspecs("bot/", remote="up")[0] == "+refs/heads/bot/*:refs/remotes/up/bot/*"


def fetches(git) -> list[list[str]]:
    return [argv for argv in git.history if "fetch" in argv]


def test_outside_ci_nothing_is_fetched(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    assert refresh_in_ci(git, environ={}, branch_prefix="l4/", run_id="r1") is False
    assert fetches(git) == []


def test_ci_true_alone_is_not_a_job_and_fetches_nothing(make_repo, git_for):
    """SCN-CLI-12: the refresh follows the one rule (L4-CLI-004), so a laptop with `CI=true` stays local."""
    git = git_for(make_repo(remote=True))
    assert refresh_in_ci(git, environ={"CI": "true"}, branch_prefix="l4/", run_id="r1") is False
    assert fetches(git) == []


def test_in_ci_the_fetch_prunes_and_runs_once_per_process(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    assert refresh_in_ci(git, environ=CI, branch_prefix="l4/", run_id="r1") is True
    assert refresh_in_ci(git, environ=CI, branch_prefix="l4/", run_id="r1") is False  # once per process
    assert refresh_in_ci(git, environ=CI, branch_prefix="l4/", run_id="r2") is True  # another process
    argv = fetches(git)[0]
    assert "--prune" in argv and "+refs/l4/locks/*:refs/l4/locks/*" in argv
    assert "+refs/heads/main:refs/remotes/origin/main" not in argv  # the base is not this call's business


def test_the_credential_helper_is_passed_to_the_fetch(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    helper = (("credential.helper", ""), ("credential.helper", "!f() { :; }; f"))
    refresh_in_ci(git, environ=CI, branch_prefix="l4/", run_id="r1", config=helper)
    [argv] = fetches(git)
    assert "credential.helper=!f() { :; }; f" in argv


def test_a_repository_without_origin_is_skipped(tmp_path: Path, git_for, raw):
    repo = tmp_path / "solo"
    repo.mkdir()
    raw(repo, "init", "-q")
    assert refresh_in_ci(git_for(repo), environ=CI, branch_prefix="l4/", run_id="r1") is False
