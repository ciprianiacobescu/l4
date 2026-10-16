"""The contracts of escalate-and-note 0.1: no behaviour yet (L4-IMP-017, L4-OPS-018)."""

import inspect

import pytest

from l4.agents.factory import Factory
from l4.implementer import retrynote
from l4.implementer.loop import EscalationRequest, run_task
from l4.implementer.workbench import PreviousAttempt
from l4.state.fold import UnitState
from l4.verifier.selection import independence_keeper


def test_previous_attempt_of_today_is_a_limit_block():
    prev = PreviousAttempt("p", "usage", "1.1")
    assert (prev.why, prev.phase, prev.failures) == ("limit", None, ())
    assert PreviousAttempt("p", None).limit_kind is None


def test_escalation_request_fields():
    req = EscalationRequest("1.1", "red", "deepseek", (("deepseek", "r"),), 3)
    assert (req.task, req.phase, req.profile, req.failures, req.attempt) == (
        "1.1",
        "red",
        "deepseek",
        (("deepseek", "r"),),
        3,
    )


def test_run_task_has_a_keyword_only_escalate_defaulting_to_none():
    param = inspect.signature(run_task).parameters["escalate"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is None


def test_unit_state_halt_fields_default_to_none():
    state = UnitState(unit="u")
    assert (state.halt_task, state.halt_fix_unit) == (None, None)


def test_new_functions_are_not_implemented():
    with pytest.raises(NotImplementedError):
        Factory.next_profile(object(), "implementer", "u", "a")
    with pytest.raises(NotImplementedError):
        independence_keeper(None, ())
    with pytest.raises(NotImplementedError):
        retrynote.retry_note([], "1.1", None)
    with pytest.raises(NotImplementedError):
        retrynote.note_block(retrynote.RetryNote("unit.retried", "t", "x"))
