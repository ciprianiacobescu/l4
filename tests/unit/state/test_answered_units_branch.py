"""SCN-YOLO-137 end to end: the answer is pushed on a real unit branch, `load_snapshot` reads it, and the plan's view of
the unit (`answered_units`, `resume_blocker`) follows the planner's own reason (review N5)."""

from pathlib import Path

from l4.yolo.commands import Blocker, Extend, answered_units, resume_blocker
from l4.yolo.model import PlanState

from .test_status_branch import IMPLEMENTING, QUESTION, snapshot

WAITING = ("phase.changed", {"from": "implementing", "to": "awaiting_human", "trigger": "questions_blocking"})
UNIT = "openspec:add-x"


def push(unit_repo, trailers, status: str, answer: str):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING[:3], WAITING)
        (repo / "openspec/changes/add-x/questions.md").write_text(QUESTION.format(status=status, answer=answer))

    unit_repo.push_unit_branch(work, trailers)


def waiting_plan() -> PlanState:
    return PlanState(plan_id="p1", status="waiting", current=UNIT, wait_reason="unit_awaiting_human")


def test_an_open_question_on_the_branch_is_not_an_answered_unit_and_the_resume_is_refused(unit_repo, trailers):
    push(unit_repo, trailers, "open", "a draft")
    snap = snapshot(unit_repo)
    assert snap.state.phase == "awaiting_human" and answered_units([snap]) == set()
    blocker = resume_blocker("p1", waiting_plan(), [], None, {UNIT: "awaiting_human"}, Extend(), answered=set())
    assert isinstance(blocker, Blocker) and "no resume is needed" in blocker.message


def test_an_answer_pushed_on_the_branch_is_an_answered_unit_and_the_resume_goes(unit_repo, trailers):
    push(unit_repo, trailers, "answered", "21%")
    snap = snapshot(unit_repo)
    assert snap.source == "branch" and snap.state.phase == "awaiting_human"
    answered = answered_units([snap])
    assert answered == {UNIT}
    assert resume_blocker("p1", waiting_plan(), [], None, {UNIT: "awaiting_human"}, Extend(), answered=answered) is None
