"""The plan report lists the delegate's decisions (delegate-answers 13.1; L4-DLG-010, SCN-DLG-31a): per unit, each
question with its kind, the decision, the model via the CLI and the cost, and the escalation with its reason."""

from datetime import UTC, datetime

import pytest

from l4.state.ledger import LedgerEvent
from l4.yolo.report import render_report
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")
STAMP = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def unit_event(seq: int, type_: str, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", A, seq, type_, data)


def decisions() -> tuple[LedgerEvent, ...]:
    return (
        unit_event(1, "question.raised", id="Q-001", kind="technical"),
        unit_event(2, "question.raised", id="Q-002", kind="verdict"),
        unit_event(3, "question.raised", id="Q-003", kind="product"),
        unit_event(
            4, "delegate.result", question="Q-001", id="Q-001", kind="technical", status="answered",
            decision="answer", model="claude-opus-5-5", cli="claude-code", cost_usd=0.2, reason="proposal.md says so",
        ),
        unit_event(
            5, "delegate.result", question="Q-002", id="Q-002", kind="verdict", status="answered",
            decision="accept", model="gpt-6.1-sol", cli="codex", cost_usd=1.25, reason="the test covers it",
        ),
        unit_event(
            6, "delegate.result", question="Q-003", id="Q-003", kind="product", status="escalated",
            decision="escalate", model="gpt-6.1-sol", cli="codex", cost_usd=0.4, called=True,
            reason="no project document decides this",
        ),
        unit_event(7, "delegate.result", question="Q-003", id="Q-003", kind="product", status="deferred",
                   reason="cooling"),
    )  # fmt: skip


def report(world, delegate=None):
    from l4.yolo.plans import plan_files

    if not plan_files(world.repo):
        world.plan()
    (file,) = plan_files(world.repo)
    events = [ev("plan.charged", unit=A, attempt=1, cost_usd=2.0, runs=2)]
    return render_report(
        repository="r", plan=file.plan, state=fold_plan("p1", events), events=events, target_revision="abc",
        units={}, generated_at="t", **({"delegate": delegate} if delegate is not None else {}),
    )  # fmt: skip


def test_the_report_lists_the_delegate_decisions(world):  # SCN-DLG-31a
    text = report(world, {A: decisions()})
    unit = text.split(f"### {A}")[1].split("### ")[0]
    assert "- Delegate decisions:" in unit
    assert "  - Q-001 (technical): answer by the delegate (claude-opus-5-5 via claude-code), $0.20" in unit
    assert "  - Q-002 (verdict): accept by the delegate (gpt-6.1-sol via codex), $1.25" in unit
    escalated = "  - Q-003 (product): escalated by the delegate (gpt-6.1-sol via codex), $0.40: no project document"
    assert escalated + " decides this" in unit
    assert "deferred" not in unit  # a deferral is not a decision


def test_a_report_without_delegate_decisions_is_unchanged(world):
    assert "Delegate decisions" not in report(world)
    assert report(world, {A: ()}) == report(world)


def test_the_decisions_of_a_unit_do_not_show_under_another(world):
    text = report(world, {B: decisions()})
    assert "Delegate decisions" not in text.split(f"### {A}")[1].split("### ")[0]


def test_an_escalation_without_a_call_has_no_model_and_no_cost(world):
    limit = unit_event(
        8, "delegate.result", question="Q-009", id="Q-009", kind="technical", status="escalated", called=False,
        reason="delegate answer limit of task 3.1 reached (3)",
    )  # fmt: skip
    raised = unit_event(9, "question.raised", id="Q-009", kind="technical")
    # the raise comes first in a ledger: put it before the result
    unit = report(world, {A: (raised, limit)}).split(f"### {A}")[1].split("### ")[0]
    assert "  - Q-009 (technical): escalated: delegate answer limit of task 3.1 reached (3)" in unit
    assert "$" not in unit.split("Delegate decisions:")[1]


def test_the_plan_step_feeds_the_report_with_the_units_decisions(world, monkeypatch):
    from dataclasses import replace

    import l4.yolo.cycle as cycle

    seen = []
    real = cycle.render_report
    monkeypatch.setattr(cycle, "render_report", lambda **kw: seen.append(kw) or real(**kw))
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    snap = world.snapshot("a", "halted")
    events = (
        unit_event(1, "question.raised", id="Q-001", kind="technical"),
        unit_event(
            2, "delegate.result", question="Q-001", id="Q-001", kind="technical", status="answered",
            decision="answer", model="claude-opus-5-5", cli="claude-code", cost_usd=0.2, reason="r",
        ),
    )  # fmt: skip
    world.step({"a": replace(snap, events=events)})
    assert seen, "the halted unit stops the plan and the stop writes the report"
    (decision,) = seen[-1]["delegate"][A]
    assert (decision.data["question"], decision.data["model"], decision.data["cli"]) == (
        "Q-001", "claude-opus-5-5", "claude-code",
    )  # fmt: skip
