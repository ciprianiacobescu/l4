"""escalate-and-note 2.3, SCN-IMP-183 (L4-IMP-017): a fix unit's task runs without the escalation hook, so it stays on
the run's profile and halts after that profile's `max_task_attempts`."""

import pytest

from l4.agents.fake import Step

from ..implementer.conftest import red_step
from ..orchestrator.test_fallback import TWO
from .test_ladder_fix import noqa_green


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in `test_ladder_fix`."""


def test_the_tasks_of_a_fix_unit_do_not_move(run_l4, valid_spec, fake_clock):
    invalid = Step()  # no result object: a failed attempt
    run = run_l4([red_step(), noqa_green(), invalid, invalid, invalid], **TWO)
    assert run.code == 13
    assert run.events("implementer.escalated") == [] and run.events("implementer.escalation_skipped") == []
    assert len(run.adapter.requests) == 5
    assert len({r.profile.vendor for r in run.adapter.requests}) == 1  # never the second profile
    assert [e["profile"] for e in run.events("task.attempt_failed")] == ["impl"] * 3
    (tripped,) = run.events("breaker.tripped")
    assert tripped["reason"] == "max_task_attempts" and tripped["profiles"] == [{"profile": "impl", "failures": 3}]
