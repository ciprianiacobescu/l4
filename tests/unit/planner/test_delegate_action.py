"""The planner names the action `delegate` (delegate-answers 9.3; L4-DLG-003, design D6; SCN-DLG-10, SCN-DLG-11): a unit
in the delegate's scope that waits for an answer, with an open question of a kind it answers and no final delegate
record for the question's current raise, and no deferral in the future."""

from dataclasses import replace
from datetime import UTC, datetime

from l4.config.schema import DelegateCfg
from l4.delegate.due import due_questions, stamp_due
from l4.delegate.scope import PlansView
from l4.planner import facts_of, next_action
from l4.specs.base import Framework, Task, UnitRef
from l4.specs.questions import QuestionsFile
from l4.state.fold import UnitState
from l4.state.ledger import LedgerEvent
from l4.state.status import ChildSnapshot, UnitSnapshot
from l4.yolo.model import PlanState
from l4.yolo.plans import _plan_file

from ..specs.questions_world import questions_md

CFG = DelegateCfg(enabled=True, scope="all")
STAMP = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
TASKS = [Task("1.1", "1.1", "do it", False, " ", 0, 1, 2), Task("1.2", "1.2", "and it", False, " ", 0, 2, 2)]


def event(seq: int, event_type: str, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", "u", seq, event_type, data)


def questions(*specs) -> QuestionsFile:
    return QuestionsFile.parse(questions_md("openspec:a", *specs).encode())


def snapshot(*specs, events=(), phase="awaiting_human", **state) -> UnitSnapshot:
    ref = UnitRef(Framework.OPENSPEC, "a", "openspec/changes/a")  # type: ignore[arg-type]
    return UnitSnapshot(
        ref, UnitState(unit="openspec:a", phase=phase, **state), TASKS, "branch",
        questions=questions(*(specs or ({"title": "Which hash?"},))), events=tuple(events),
    )  # fmt: skip


def action(snap: UnitSnapshot, due=None, now=None) -> tuple[str, str]:
    stamped = replace(snap, delegate_due=due_questions(snap, CFG) if due is None else due)
    return next_action(facts_of(stamped), now)


def test_an_undecided_question_is_the_delegate_action():  # SCN-DLG-10
    snap = snapshot({"title": "Which hash?"}, events=[event(1, "question.raised", id="Q-001", kind="technical")])
    assert due_questions(snap, CFG) == (("Q-001", None),)
    assert action(snap) == ("delegate", "delegate: Q-001 to ask")


def test_a_question_of_a_kind_the_delegate_does_not_answer_is_no_action():
    snap = snapshot({"title": "Which hash?", "kind": "product"})
    assert due_questions(snap, DelegateCfg(enabled=True, kinds=["technical"])) == ()
    assert action(snap, ())[0] == "none"


def test_a_fix_units_question_is_a_delegate_action():
    fix = ChildSnapshot("a-fix-1", TASKS[:1], questions({"title": "Which flag?"}))
    snap = replace(snapshot(phase="fixing", open_fix_unit="a-fix-1"), questions=None, children=(fix,))
    assert due_questions(snap, CFG) == (("a-fix-1/Q-001", None),)
    assert action(snap) == ("delegate", "delegate: a-fix-1/Q-001 to ask")


def test_no_action_after_a_final_record():  # SCN-DLG-11
    raised = event(1, "question.raised", id="Q-001", kind="technical")
    for status in ("escalated", "answered", "discarded"):
        done = event(2, "delegate.result", question="Q-001", status=status)
        snap = snapshot(events=[raised, done])
        assert due_questions(snap, CFG) == (), status
        assert action(snap)[0] == "none", status
    # a deferral is not final; a new raise of the same id starts the question again
    deferred = event(2, "delegate.result", question="Q-001", status="deferred", retry_after="2026-01-01T10:30:00Z")
    assert due_questions(snapshot(events=[raised, deferred]), CFG) == (("Q-001", "2026-01-01T10:30:00Z"),)
    escalated = event(2, "delegate.result", question="Q-001", status="escalated")
    assert due_questions(snapshot(events=[raised, escalated, event(3, "question.raised", id="Q-001")]), CFG) != ()


def test_no_action_before_retry_after():
    deferred = event(2, "delegate.result", question="Q-001", status="deferred", retry_after="2026-01-01T10:30:00Z")
    snap = snapshot(events=[event(1, "question.raised", id="Q-001", kind="technical"), deferred])
    before, after = datetime(2026, 1, 1, 10, 29, tzinfo=UTC), datetime(2026, 1, 1, 10, 31, tzinfo=UTC)
    assert action(snap, now=before)[0] == "none"
    assert action(snap, now=after) == ("delegate", "delegate: Q-001 to ask")


def test_an_answer_that_frees_a_task_comes_before_the_delegate():
    snap = snapshot(
        {"title": "Which hash?", "tasks": ("1.1",)},
        {"title": "Done?", "tasks": ("1.2",), "status": "answered", "answer": "yes"},
    )
    assert action(snap, (("Q-001", None),))[0] == "implement"


def plan_view(status: str, current: str) -> PlansView:
    import json

    text = json.dumps(
        {
            "schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "main", "merge": "human",
            "batches": [{"id": "b1", "units": [{"id": "openspec:a"}, {"id": "openspec:b"}]}],
        }
    )  # fmt: skip
    state = PlanState(plan_id="p1", status=status, current=current)
    return PlansView((_plan_file(".l4/plans/p1.json", text),), {"p1": state}, "main", ())


def test_no_action_out_of_scope():
    snap = snapshot(events=[event(1, "question.raised", id="Q-001", kind="technical")])

    def stamped(cfg: DelegateCfg, view: PlansView) -> tuple:
        (one,) = stamp_due([snap], cfg, lambda: view)
        return one.delegate_due

    nothing = PlansView()
    assert stamped(CFG, nothing) == (("Q-001", None),)  # scope all, no plan: in scope
    assert stamped(DelegateCfg(enabled=True, scope="yolo"), nothing) == ()  # scope yolo: a unit in no plan is not
    assert stamped(DelegateCfg(enabled=False, scope="all"), nothing) == ()  # off by default
    assert stamped(CFG, plan_view("active", "openspec:b")) == ()  # an active plan keeps other units out
    assert stamped(DelegateCfg(enabled=True, scope="yolo"), plan_view("waiting", "openspec:a")) == (("Q-001", None),)
    assert stamped(CFG, plan_view("stopped", "openspec:a")) == ()  # a stopped plan holds its units
    other = replace(snap, state=UnitState(unit="openspec:a", phase="implementing"))
    assert stamp_due([other], CFG, lambda: nothing)[0].delegate_due == ()  # not waiting: nothing to ask


def test_an_escalated_unit_has_no_delegate_action():  # SCN-DLG-85, L4-DLG-025: `ci_not_fixed` is a phase change
    from l4.state.next_step import CI_NOT_FIXED

    snap = snapshot(
        {"title": "Which hash?"}, phase="escalated", halt_reason=CI_NOT_FIXED,
        events=[event(1, "question.raised", id="Q-001", kind="technical")],
    )  # fmt: skip
    assert due_questions(snap, CFG) == ()  # no question of an escalated unit is due
    forced = (("Q-001", None),)  # even a due list that reached the snapshot by mistake names no action
    assert action(snap, forced)[0] != "delegate"

def test_an_upgrade_does_not_reask():  # SCN-DLG-93 (delegate-answers 27.1, P3)
    """A reply discarded under an older harness stays final: the question is a person's, and the label stays."""
    raised = event(1, "question.raised", id="Q-001", kind="technical")
    discarded = event(
        2, "delegate.result", question="Q-001", status="discarded", harness="0.4.20", prompt="delegate@2",
        reason="the reply cited questions.md, which is no evidence",
    )  # fmt: skip
    snap = snapshot({"title": "Which hash?"}, events=[raised, discarded])
    assert due_questions(snap, CFG) == ()
    assert action(snap)[0] == "none"
    later = event(3, "run.started")  # runs of a newer harness, a changed config: nothing reopens the question
    assert (
        due_questions(
            snapshot({"title": "Which hash?"}, events=[raised, discarded, later]),
            DelegateCfg(enabled=True, scope="all", timeout="20m"),
        )
        == ()
    )


def test_a_new_raise_is_asked():  # SCN-DLG-94
    raised = event(1, "question.raised", id="Q-001", kind="technical")
    escalated = event(2, "delegate.result", question="Q-001", status="escalated", reason="no document decides this")
    again = event(3, "question.raised", id="Q-001", kind="technical")
    snap = snapshot({"title": "Which hash?"}, events=[raised, escalated, again])
    assert due_questions(snap, CFG) == (("Q-001", None),)
    assert action(snap) == ("delegate", "delegate: Q-001 to ask")
