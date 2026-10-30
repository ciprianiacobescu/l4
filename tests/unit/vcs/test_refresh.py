from pathlib import Path

from l4.vcs.refresh import PLAN_REFSPEC, mark_refreshed, refresh_remote_refs, unit_refspecs


def test_refspecs_cover_the_unit_branches_and_the_lock_refs():
    assert unit_refspecs("l4/") == (
        "+refs/heads/l4/*:refs/remotes/origin/l4/*",
        "+refs/l4/locks/*:refs/l4/locks/*",
    )
    assert unit_refspecs("bot/", remote="up")[0] == "+refs/heads/bot/*:refs/remotes/up/bot/*"


def fetches(git) -> list[list[str]]:
    return [argv for argv in git.history if "fetch" in argv]


def test_the_fetch_prunes_the_unit_branches_the_lock_refs_and_the_plan_refs(make_repo, git_for):
    """L4-CLI-005: the refresh does not look at the environment, a person's computer fetches as a job does."""
    git = git_for(make_repo(remote=True))
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is True
    [argv] = fetches(git)
    assert "--prune" in argv and "+refs/l4/locks/*:refs/l4/locks/*" in argv and PLAN_REFSPEC in argv
    assert "+refs/heads/main:refs/remotes/origin/main" not in argv  # the base is not this call's business


def test_fetch_false_fetches_nothing(make_repo, git_for):
    """L4-CLI-005 `--no-fetch`: the local refs are read."""
    git = git_for(make_repo(remote=True))
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1", fetch=False) is False
    assert fetches(git) == []
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is True  # the turn of the process is still there


def test_the_fetch_runs_once_per_process(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is True
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is False  # once per process
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r2") is True  # another process
    assert len(fetches(git)) == 2


def test_a_fetch_made_elsewhere_in_the_process_counts(make_repo, git_for):
    """`l4 retry` and `l4 restart` fetch the unit refs themselves; the refresh that follows must not fetch again (it
    would prune what `l4 restart` keeps on purpose)."""
    git = git_for(make_repo(remote=True))
    mark_refreshed(git, "r1")
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is False
    assert fetches(git) == []


def test_the_credential_helper_is_passed_to_the_fetch(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    helper = (("credential.helper", ""), ("credential.helper", "!f() { :; }; f"))
    refresh_remote_refs(git, branch_prefix="l4/", run_id="r1", config=helper)
    [argv] = fetches(git)
    assert "credential.helper=!f() { :; }; f" in argv


def test_a_repository_without_origin_is_skipped(tmp_path: Path, git_for, raw):
    repo = tmp_path / "solo"
    repo.mkdir()
    raw(repo, "init", "-q")
    git = git_for(repo)
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is False
    assert fetches(git) == []


def test_a_remote_ahead_of_the_tracking_refs_is_brought_in(make_repo, git_for, raw, tmp_path: Path):
    """SCN-CLI-15 at the git level: a branch a person pushed from another clone, and one the forge deleted."""
    repo = make_repo(remote=True)
    git = git_for(repo)
    other = tmp_path / "other"
    raw(tmp_path, "clone", "-q", str(tmp_path / "repo-origin.git"), str(other))
    raw(other, "checkout", "-q", "-b", "l4/openspec/a")
    (other / "spec.md").write_text("an edit\n")
    raw(other, "add", "-A")
    raw(other, "commit", "-q", "-m", "a spec edit")
    raw(other, "push", "-q", "origin", "l4/openspec/a")
    assert git.rev_parse("refs/remotes/origin/l4/openspec/a") is None
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r1") is True
    pushed = raw(other, "rev-parse", "HEAD").strip()
    assert git.rev_parse("refs/remotes/origin/l4/openspec/a") == pushed
    raw(other, "push", "-q", "origin", "--delete", "l4/openspec/a")
    assert refresh_remote_refs(git, branch_prefix="l4/", run_id="r2") is True
    assert git.rev_parse("refs/remotes/origin/l4/openspec/a") is None  # pruned
