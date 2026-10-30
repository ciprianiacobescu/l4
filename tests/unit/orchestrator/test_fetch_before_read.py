"""L4-CLI-005 on a person's computer: `l4 resume`, `l4 run --unit` and `l4 run --dry-run` fetch before they read, and
stop when they cannot, naming `--no-fetch` (SCN-CLI-18, SCN-CLI-19)."""

import pytest

from l4.cli import main

from ..conftest import UNIT


def go_offline(tdd_repo, raw) -> None:
    raw(tdd_repo.repo, "remote", "set-url", "origin", str(tdd_repo.repo.parent / "gone.git"))


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--unit", UNIT],
        ["run", "--dry-run"],
        ["resume", "--unit", UNIT, "--reason", "try again"],
    ],
    ids=["run", "dry-run", "resume"],
)
def test_scn_cli_18_an_offline_command_stops_before_it_reads_and_names_no_fetch(tdd_repo, raw, capsys, argv):
    tdd_repo.write_config()
    go_offline(tdd_repo, raw)
    before = raw(tdd_repo.repo, "for-each-ref")
    assert main([*argv, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 1
    err = capsys.readouterr().err
    assert "could not refresh from the forge" in err and "gone.git" in err and "--no-fetch" in err
    assert raw(tdd_repo.repo, "for-each-ref") == before


def test_scn_cli_18_a_refused_credential_stops_a_run_with_exit_3(tdd_repo, raw, capsys, monkeypatch):
    from l4.vcs.errors import GitError

    def refuse(*args, **kwargs):
        raise GitError(["git", "fetch"], 128, "remote: HTTP Basic: Access denied\nfatal: Authentication failed")

    tdd_repo.write_config()
    monkeypatch.setattr("l4.state.status.refresh_remote_refs", refuse)
    assert main(["run", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 3
    err = capsys.readouterr().err
    assert "Access denied" in err and "--no-fetch" in err


def test_scn_cli_19_a_local_run_that_cannot_sandbox_fetches_nothing(tdd_repo, raw, capsys, monkeypatch):
    """L4-SEC-041: the refusal comes before the fetch, so even an unreachable origin does not matter."""
    monkeypatch.setattr("l4.sandbox.select.resolve_tool", lambda *a, **k: None)
    tdd_repo.write_config(sandbox={"mode": "auto"})
    go_offline(tdd_repo, raw)
    assert main(["run", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 3
    err = capsys.readouterr().err
    assert "could not refresh from the forge" not in err


ARGV = {
    "status": ["status", "--unit", UNIT],
    "plan": ["plan"],
    "resume": ["resume", "--unit", UNIT, "--reason", "try again"],
    "run": ["run", "--unit", UNIT],
    "dry-run": ["run", "--dry-run"],
    "archive": ["archive", "--unit", UNIT],
}


@pytest.mark.parametrize("command", ARGV)
def test_no_fetch_reaches_the_refresh(tdd_repo, monkeypatch, command):
    """`--no-fetch` is accepted by every command that refreshes and arrives as `fetch=False`; without it `True`
    (outside a job: `l4 archive` fetches like the others)."""
    seen: list[bool] = []

    def stop(git, **kwargs):
        seen.append(kwargs["fetch"])
        raise RuntimeError("stop here")  # nothing after the refresh is this test's business

    monkeypatch.setattr("l4.state.status.refresh_remote_refs", stop)
    tdd_repo.write_config()
    for flags in ([], ["--no-fetch"]):
        main([*ARGV[command], *flags, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    assert seen == [True, False]


def test_a_dry_run_with_no_fetch_exits_as_it_does_with_the_local_refs(tdd_repo, raw, capsys):
    tdd_repo.write_config()
    go_offline(tdd_repo, raw)
    assert main(["run", "--dry-run", "--no-fetch", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    assert "would exit 0" in capsys.readouterr().out


def _library(tdd_repo, run_id: str, environ: dict | None = None):
    from l4.config.redaction import load_app_config
    from l4.context import AppContext
    from l4.redact import Redactor
    from l4.vcs.git import Git

    environ = environ or tdd_repo.environ
    app = AppContext(tdd_repo.repo, None, "human", 0, run_id, environ, Redactor({}))
    app, cfg = load_app_config(app)
    return app, cfg, Git(tdd_repo.repo, environ=environ)


def test_retry_and_restart_fetch_once_per_command_outside_a_job(tdd_repo):
    """`fetch_unit_refs` is their fetch; the refresh that follows must not run git fetch a second time."""
    from l4.state.retry import fetch_unit_refs
    from l4.state.status import refresh_refs

    tdd_repo.write_config()
    app, cfg, git = _library(tdd_repo, "r-once-retry")
    fetch_unit_refs(app, cfg, git)
    refresh_refs(app, cfg, git)
    assert len([argv for argv in git.history if "fetch" in argv]) == 1


def test_restart_keeps_the_tracking_ref_of_a_branch_the_forge_deleted(tdd_repo, raw):
    from l4.state.retry import fetch_unit_refs
    from l4.state.status import refresh_refs

    tdd_repo.write_config()
    raw(tdd_repo.repo, "push", "-q", "origin", "HEAD:refs/heads/l4/openspec/gone")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    raw(tdd_repo.origin, "branch", "-D", "l4/openspec/gone")
    app, cfg, git = _library(tdd_repo, "r-once-restart")
    fetch_unit_refs(app, cfg, git, prune=False)
    refresh_refs(app, cfg, git)  # would prune it if it fetched again
    assert git.rev_parse("refs/remotes/origin/l4/openspec/gone") is not None


def _plan_ref_on_origin(tdd_repo, raw, plan_id: str = "p1") -> str:
    head = raw(tdd_repo.origin, "rev-parse", "main").strip()
    raw(tdd_repo.origin, "update-ref", f"refs/l4/plans/{plan_id}", head)
    return head


def test_retry_outside_a_job_fetches_the_plan_refs(tdd_repo, raw):
    """`stopped_plan_holding` and what runs after it read the plans the forge has, not the ones of the last fetch."""
    from l4.state.retry import fetch_unit_refs

    tdd_repo.write_config()
    head = _plan_ref_on_origin(tdd_repo, raw)
    app, cfg, git = _library(tdd_repo, "r-plans-retry")
    assert git.rev_parse("refs/l4/plans/p1") is None
    fetch_unit_refs(app, cfg, git)
    assert git.rev_parse("refs/l4/plans/p1") == head
    [argv] = [a for a in git.history if "fetch" in a]
    assert "+refs/l4/plans/*:refs/l4/plans/*" in argv


def test_restart_fetches_the_plan_refs_and_still_keeps_the_branch_the_forge_deleted(tdd_repo, raw):
    from l4.state.retry import fetch_unit_refs

    tdd_repo.write_config()
    raw(tdd_repo.repo, "push", "-q", "origin", "HEAD:refs/heads/l4/openspec/gone")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    raw(tdd_repo.origin, "branch", "-D", "l4/openspec/gone")
    head = _plan_ref_on_origin(tdd_repo, raw)
    app, cfg, git = _library(tdd_repo, "r-plans-restart")
    fetch_unit_refs(app, cfg, git, prune=False)
    assert git.rev_parse("refs/remotes/origin/l4/openspec/gone") is not None  # kept: its last head is the old work
    assert git.rev_parse("refs/l4/plans/p1") == head
    # a plan ref that moved to a commit that is not a descendant (the forge rewrote it) is force-updated, no --prune
    raw(tdd_repo.repo, "commit", "-q", "--allow-empty", "-m", "other")
    raw(tdd_repo.repo, "push", "-q", "origin", "HEAD:refs/heads/side")
    side = raw(tdd_repo.repo, "rev-parse", "HEAD").strip()
    raw(tdd_repo.origin, "update-ref", "refs/l4/plans/p1", side)
    fetch_unit_refs(app, cfg, git, prune=False)
    assert git.rev_parse("refs/l4/plans/p1") == side
    raw(tdd_repo.origin, "update-ref", "refs/l4/plans/p1", head)  # back to the older commit: not a fast-forward
    fetch_unit_refs(app, cfg, git, prune=False)
    assert git.rev_parse("refs/l4/plans/p1") == head


# --- review fixes -------------------------------------------------------------------------------------------------

RUN_HINT = (
    "a run needs the forge (its worktree fetches the unit); fix the connection, "
    "or read the local state with `l4 status --no-fetch`"
)


@pytest.mark.parametrize(
    "argv",
    [["run", "--unit", UNIT], ["resume", "--unit", UNIT, "--reason", "try again"]],
    ids=["run", "resume"],
)
def test_an_offline_run_or_resume_says_its_worktree_needs_the_forge(tdd_repo, raw, capsys, argv):
    tdd_repo.write_config()
    go_offline(tdd_repo, raw)
    assert main([*argv, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 1
    err = capsys.readouterr().err
    assert RUN_HINT in err and "pass --no-fetch" not in err and "gone.git" in err


def test_an_offline_dry_run_keeps_the_plain_hint(tdd_repo, raw, capsys):
    """A dry run makes no worktree: `--no-fetch` is all it needs."""
    tdd_repo.write_config()
    go_offline(tdd_repo, raw)
    assert main(["run", "--dry-run", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 1
    err = capsys.readouterr().err
    assert "pass --no-fetch to read the local refs" in err and "needs the forge" not in err


@pytest.mark.parametrize("command", ["dry-run", "resume", "run"])
def test_no_fetch_in_a_ci_job_stops_every_command_with_exit_2(tdd_repo, capsys, command):
    tdd_repo.write_config()
    env = {
        **tdd_repo.environ, "GITLAB_CI": "true", "L4_FORGE_TOKEN": "tok",
        "CI_API_V4_URL": "https://gitlab.example.invalid/api/v4", "CI_PROJECT_ID": "1",
    }  # fmt: skip
    argv = [*ARGV[command], "--no-fetch", "--repo", str(tdd_repo.repo)]
    assert main(argv, environ=env) == 2
    assert "--no-fetch is for a person's computer" in capsys.readouterr().err


def _denied(monkeypatch):
    from l4.vcs.errors import GitError

    def refuse(*args, **kwargs):
        raise GitError(["git", "fetch"], 128, "remote: HTTP Basic: Access denied\nfatal: Authentication failed")

    monkeypatch.setattr("l4.state.status.refresh_remote_refs", refuse)


def test_a_refused_credential_names_the_token_variable_when_it_is_set(tdd_repo, capsys, monkeypatch):
    _denied(monkeypatch)
    tdd_repo.write_config()
    env = {**tdd_repo.environ, "L4_FORGE_TOKEN": "s3cret-value"}
    assert main(["plan", "--repo", str(tdd_repo.repo)], environ=env) == 3
    err = capsys.readouterr().err
    assert "L4_FORGE_TOKEN is set, so git uses it instead of your credential helper: check or unset it" in err
    assert "s3cret-value" not in err


def test_a_refused_credential_does_not_blame_a_variable_that_is_not_set(tdd_repo, capsys, monkeypatch):
    _denied(monkeypatch)
    tdd_repo.write_config()
    assert main(["plan", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 3
    assert "is set, so git uses it" not in capsys.readouterr().err


def test_outside_a_job_the_refresh_passes_the_credential_helper_built_from_the_origin_url(tdd_repo, raw, monkeypatch):
    """The helper (and its username) follows the platform of the origin URL: github.com is `x-access-token`, where the
    CI call (no origin URL) would have said GitLab's `oauth2`."""
    from l4.state.status import refresh_refs

    seen: list[tuple] = []
    monkeypatch.setattr("l4.state.status.refresh_remote_refs", lambda git, **kw: seen.append(kw["config"]))
    tdd_repo.write_config()
    raw(tdd_repo.repo, "remote", "set-url", "origin", "https://github.com/acme/widgets.git")
    environ = {**tdd_repo.environ, "L4_FORGE_TOKEN": "s3cret-tok"}
    app, cfg, git = _library(tdd_repo, "r-helper", environ)
    refresh_refs(app, cfg, git)
    [config] = seen
    helper = dict(config)["credential.helper"]
    assert "x-access-token" in helper and "$L4_FORGE_TOKEN" in helper and "s3cret-tok" not in helper
