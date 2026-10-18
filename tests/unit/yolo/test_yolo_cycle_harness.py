"""A unit held by a harness question makes the plan wait, with the cause named (L4-IMP-063, L4-OPS-006, L4-YOLO-012)."""

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, raise_questions
from l4.state.ledger import LedgerEvent
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A = unit_id("a")
REASON = "the test-presatisfied run ran no test (exit 2, 45 collection errors)"


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def harness_questions(folder: Path) -> QuestionsFile:
    question = NewQuestion(
        "Task 1.1: the pre-satisfied check could not decide", QuestionKind.HARNESS, ("1.1",), "ctx", "asked",
        ("accept: count these on the evidence of the real run", "retry: run the check again"),
    )  # fmt: skip
    raise_questions(folder, "a", [question], redactor=Redactor({}))
    file = QuestionsFile.load(folder / "questions.md")
    assert file is not None
    return file


def held_snapshot(world: CycleWorld, tmp_path: Path):
    snap = world.snapshot("a", "awaiting_human")
    inconclusive = LedgerEvent(
        datetime(2026, 10, 14, tzinfo=UTC), "r-20261014T0000Z-0001", A, 1, "check.inconclusive",
        {"task": "1.1", "phase": "red", "check": "pre_satisfied", "reason": REASON, "question": "Q-001"},
    )  # fmt: skip
    (tmp_path / "q").mkdir()
    return dataclasses.replace(snap, questions=harness_questions(tmp_path / "q"), events=(inconclusive,))


def test_a_plan_waits_on_a_unit_held_by_a_harness_question(world, tmp_path):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    step = world.step({"a": held_snapshot(world, tmp_path)})
    assert step.start_next_run is False
    state = fold_plan("p1", world.events())
    assert state.status == "waiting" and state.wait_reason == "unit_awaiting_human"
    waiting = [e for e in world.events() if e.type == "plan.waiting"][-1].data
    assert "harness check inconclusive: Q-001" in waiting["detail"]
