"""`l4 run` gives the plan step the seconds left of the CI job, so the step can wait out the hand-off window inside
the run (merge-window-wait D3; L4-YOLO-013): a callable in a CI run, none outside CI."""

from datetime import timedelta

import pytest

from l4 import orchestrator
from l4.yolo.cycle import PlanStep

from ..implementer.conftest import green_step, red_step
from .test_step_deadline import RecordingForge, budget


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch, tdd_repo):
    """The keywords `yolo_step` was called with, and a forge that records what a CI run asks of it."""
    kept: dict = {}
    monkeypatch.setattr(orchestrator, "make_forge", lambda cfg, environ, **kw: RecordingForge())
    monkeypatch.setattr(orchestrator, "yolo_step", lambda *a, **kw: kept.update(kw) or PlanStep(allow=None))
    return kept


def test_a_ci_run_with_a_job_timeout_gives_the_step_a_budget_that_runs_down(run_l4, tdd_repo, fake_clock, seen):
    tdd_repo.environ["GITHUB_ACTIONS"] = "true"
    budget(tdd_repo, fake_clock, left_at_start=1700)
    assert run_l4([red_step(), green_step()]).code == 0
    left = seen["budget"]
    assert callable(left) and left() == 1700
    fake_clock.advance(timedelta(seconds=300))
    assert left() == 1400  # read when asked, not when the run began


def test_a_gitlab_job_timeout_gives_the_step_a_budget(run_l4, tdd_repo, fake_clock, seen):
    tdd_repo.environ.update({"GITLAB_CI": "true", "CI_JOB_TIMEOUT": "3600"})
    assert run_l4([red_step(), green_step()]).code == 0
    assert seen["budget"]() == 3600 - 1200  # the timeout less the default soft-deadline margin, counted from the run


def test_a_ci_run_without_a_known_budget_gives_a_callable_that_answers_none(run_l4, tdd_repo, fake_clock, seen):
    tdd_repo.environ["GITLAB_CI"] = "true"
    run_l4([red_step(), green_step()])
    assert callable(seen["budget"]) and seen["budget"]() is None


def test_a_local_run_gives_the_step_no_budget(run_l4, tdd_repo, fake_clock, seen):
    budget(tdd_repo, fake_clock, left_at_start=1700)  # the variables alone do not make a run a CI run
    for name in ("GITHUB_ACTIONS", "GITLAB_CI", "CI"):
        tdd_repo.environ.pop(name, None)
    assert run_l4([red_step(), green_step()]).code == 0
    assert seen["budget"] is None
