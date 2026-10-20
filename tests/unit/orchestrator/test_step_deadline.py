"""The step deadline end to end (L4-IMP-066 to L4-IMP-069): a real `l4 run` of the fixture unit with the fake agent."""

import pytest

from ..implementer.conftest import green_step, red_step
from .conftest import UNIT  # noqa: F401 - the fixtures below come with it

BUDGET = {"L4_JOB_TIMEOUT_MINUTES": "180", "L4_JOB_STARTED_AT": "2025-12-31T23:50:00Z"}


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


def test_run_started_records_the_job_budget_and_start(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-334: `job_timeout_s` is the budget before the margin; neither key without a budget."""
    tdd_repo.environ.update(BUDGET)
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert started["job_timeout_s"] == 10800
    assert started["job_started_at"] == "2025-12-31T23:50:00Z"
    assert run.code == 0


def test_run_started_has_neither_key_without_a_budget(run_l4, tdd_repo, fake_clock):
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert "job_timeout_s" not in started and "job_started_at" not in started


def test_run_started_has_the_budget_but_no_start_when_the_start_is_unknown(run_l4, tdd_repo, fake_clock):
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert started["job_timeout_s"] == 10800 and "job_started_at" not in started
