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
