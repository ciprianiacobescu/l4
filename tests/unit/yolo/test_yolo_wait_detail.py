"""A plan that waits on an escalated question says so (delegate-answers 12.1; L4-DLG-008, SCN-DLG-25): the detail of
`plan.waiting{reason: unit_awaiting_human}` names the escalated questions, and the run chains nothing."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from l4.planner import facts_of, next_action
from l4.state.fold import QuestionState
from l4.state.ledger import LedgerEvent

from .yolo_cycle_world import CycleWorld, ev, unit_id

A = unit_id("a")
STAMP = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def event(seq: int, type_: str, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", A, seq, type_, data)


def escalated(world, status="escalated", *, answered=False):
    events = (
        event(1, "question.raised", id="Q-004", kind="product"),
        event(2, "delegate.result", question="Q-004", id="Q-004", status=status, reason="no document decides this"),
        *((event(3, "question.answered", id="Q-004", by="human"),) if answered else ()),
    )  # fmt: skip
    snap = world.snapshot("a", "awaiting_human")
    return replace(snap, events=events, state=snap.state.model_copy(
        update={"questions": QuestionState(open=[] if answered else ["Q-004"])}
    ))  # fmt: skip


def test_the_wait_detail_names_escalated_questions(world):  # SCN-DLG-25
    snap = escalated(world)
    action, reason = next_action(facts_of(snap))
    assert action == "none" and reason.endswith("(escalated to a person: Q-004)")
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    step = world.step({"a": snap})
    waiting = next(e for e in reversed(world.events()) if e.type == "plan.waiting")
    assert waiting.data["reason"] == "unit_awaiting_human" and waiting.data["unit"] == A
    assert "(escalated to a person: Q-004)" in waiting.data["detail"]
    assert step.start_next_run is False


def test_a_discarded_reply_is_an_escalation_too(world):
    assert "(escalated to a person: Q-004)" in next_action(facts_of(escalated(world, "discarded")))[1]


def test_an_answered_question_is_no_longer_escalated(world):
    assert "escalated" not in next_action(facts_of(escalated(world, answered=True)))[1]


def test_a_question_the_delegate_answered_is_not_escalated(world):
    assert "escalated" not in next_action(facts_of(escalated(world, "answered")))[1]
