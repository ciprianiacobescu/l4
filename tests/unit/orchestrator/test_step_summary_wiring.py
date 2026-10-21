"""The job summary observer is attached to a unit's ledger when the run is on GitHub Actions (L4-OBS-005)."""

import pytest

from ..implementer.conftest import green_step, red_step
from .conftest import UNIT


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GitHub job refuses to start without a forge token (exit 3); these tests are about the summary file."""
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


def test_a_github_run_writes_the_lines_of_its_done_tasks(run_l4, tdd_repo):
    summary = tdd_repo.repo.parent / "step-summary.md"
    tdd_repo.environ.update({"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)})
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    lines = summary.read_text().splitlines()
    assert len(lines) == 1 and lines[0].startswith(f"- {UNIT} task 1.1: done (2 attempts, ")


def test_without_the_variables_nothing_is_written(run_l4, tdd_repo):
    summary = tdd_repo.repo.parent / "step-summary.md"
    tdd_repo.environ["GITHUB_STEP_SUMMARY"] = str(summary)  # no GITHUB_ACTIONS=true
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert not summary.exists()


def test_run_started_carries_the_command_and_the_ci_url(run_l4, tdd_repo):
    tdd_repo.environ.update(
        {"GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r",
         "GITHUB_RUN_ID": "42"}
    )  # fmt: skip
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert started["command"] == "run" and started["ci_url"].endswith(
        "/o/r/actions/runs/42"
    )  # the ledger scrubs the forge host
