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
}


@pytest.mark.parametrize("command", ARGV)
def test_no_fetch_reaches_the_refresh(tdd_repo, monkeypatch, command):
    """`--no-fetch` is accepted by every command that refreshes and arrives as `fetch=False`; without it `True`."""
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


def _library(tdd_repo, run_id: str):
    from l4.config.redaction import load_app_config
    from l4.context import AppContext
    from l4.redact import Redactor
    from l4.vcs.git import Git

    app = AppContext(tdd_repo.repo, None, "human", 0, run_id, tdd_repo.environ, Redactor({}))
    app, cfg = load_app_config(app)
    return app, cfg, Git(tdd_repo.repo, environ=tdd_repo.environ)


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
