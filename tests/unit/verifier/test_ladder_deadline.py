"""A CLI judge stopped by the soft deadline in the real ladder (L4-IMP-068, SCN-IMP-341)."""

from l4 import deadline
from l4.agents.fake import Step
from l4.verifier import ladder

from ..implementer.conftest import green_step, red_step
from .conftest import judge_reply
from .test_ladder import CRITERIA


def fire(req) -> None:
    deadline.current().fire()


def test_a_stopped_judge_writes_the_calibration_and_fails_no_step(
    run_l4, valid_spec, tdd_repo, fake_clock, monkeypatch
):
    """The judge step's `finally` still writes the calibration rows; the round records no failed step and no
    verdict, and `run_unit` hands the round back: the unit stays `verifying` and the run exits 10."""
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    tdd_repo.environ["L4_JOB_STARTED_AT"] = "2026-01-01T00:00:00Z"
    calibrated: list[bool] = []
    real = ladder._calibrate

    def spy(vc, run):
        calibrated.append(True)
        return real(vc, run)

    monkeypatch.setattr(ladder, "_calibrate", spy)
    run = run_l4([red_step(), green_step(), Step(structured=judge_reply(CRITERIA), on_start=fire)])
    assert run.code == 10
    assert calibrated == [True]
    assert not [e for e in run.events("verify.step") if e["status"] == "failed"]
    assert not run.events("verify.verdict")
    [reached] = run.events("deadline.reached")
    assert reached["when"] == "during" and reached["during"] == "judge"
    assert reached["phase"] == "verify" and reached["round"] == 1 and "task" not in reached
    assert run.outcome["units"][0]["phase_after"] == "verifying"
    assert run.outcome["units"][0]["exit_reason"] == (
        "soft deadline: round 1 verify stopped (judge); the next run runs it again"
    )
