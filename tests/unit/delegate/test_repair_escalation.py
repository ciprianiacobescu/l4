"""own-test-repair (L4-IMP-091, design D4): the delegate never answers a repair proposal. The question is escalated
without a model call, with the reason "a repair of a test is a person's decision"; every other harness question keeps
its rule."""

import pytest

from l4.delegate.run import _Pass
from l4.redact import Redactor
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, raise_questions
from l4.state.ledger import LedgerEvent

ASKED = "2026-10-16T10:00:00Z by implementer `codex`, run r-20261016T1000Z-aaaa, task 1.1"
REASON = "a repair of a test is a person's decision"


def question(tmp_path, kind=QuestionKind.HARNESS):
    batch = [NewQuestion(title="Task 1.1: x", kind=kind, blocking_tasks=("1.1",), context="c", asked=ASKED)]
    raise_questions(tmp_path, "add-login", batch, redactor=Redactor({}))
    return QuestionsFile.load(tmp_path / "questions.md").get("Q-001")


def raised(**data) -> LedgerEvent:
    return LedgerEvent("2026-10-16T10:00:00Z", "r-1", "u", 1, "question.raised", {"id": "Q-001", **data})


def without_a_call(q, event):
    return object.__new__(_Pass)._without_a_call(None, q, event)  # type: ignore[arg-type]


def test_a_harness_question_of_a_repair_is_escalated_without_a_call(tmp_path):  # SCN-IMP-472
    event = raised(kind="harness", check="repair", task="1.1")
    assert without_a_call(question(tmp_path), event) == REASON


@pytest.mark.parametrize("check", ["pre_satisfied", "vacuity", "at_red", "tests"])
def test_the_other_harness_checks_are_answered_by_the_delegate_as_before(tmp_path, check):
    event = raised(kind="harness", check=check, task="1.1")
    assert without_a_call(question(tmp_path), event) is None


def test_a_harness_question_with_no_raise_on_record_keeps_its_rule(tmp_path):
    assert without_a_call(question(tmp_path), None) is None


def test_only_a_harness_question_is_escalated_for_the_repair_reason(tmp_path):
    event = raised(kind="technical", check="repair", task="1.1")  # a forged check on another kind's raise
    assert without_a_call(question(tmp_path, QuestionKind.TECHNICAL), event) is None
