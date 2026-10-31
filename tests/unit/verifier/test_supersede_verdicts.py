"""A verification round supersedes the unanswered verdict questions of an earlier round (L4-VER verdict questions,
L4-OPS-014): a person fixed the spec instead of answering, round 2 judged the new subject, and Q-002 of round 1 is
not a question any more. Status `superseded by round <n>`, the index row follows, `question.superseded{ids, round}`
takes the id out of `questions.open`, so `l4:needs-answers` and the "Waiting for you" note go."""

from l4.archive import labels_for
from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    blocked_tasks,
    raise_questions,
)
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent
from l4.verifier.verdicts import hold_id, raise_verdict_questions, supersede_stale_verdicts, verdict_status

from ._integrity_helpers import STAMP, UNIT
from .test_hold_verdicts import COVERAGE, SCOPE, _Sink


def round_one(tmp_path, sink):
    """Round 1 NEEDS_HUMAN: two verdict questions (Q-001 scope hold, Q-002 coverage hold) and one intake question."""
    raise_verdict_questions(
        tmp_path, "add-bulk-discount", outcomes=[], criteria=[], trace=[], findings=[],
        existing=None, consumed=(), raised=(), ledger=sink, round_no=1, redactor=Redactor({}), holds=[SCOPE, COVERAGE],
    )  # fmt: skip
    raise_questions(
        tmp_path,
        "add-bulk-discount",
        [NewQuestion("Which rounding?", QuestionKind.TECHNICAL, ("1.1",), "ctx", "2026-10-04, implementer")],
        redactor=Redactor({}),
    )
    sink.append("question.raised", id="Q-003", kind="technical", title="Which rounding?")


def _ids(sink) -> list[str]:
    return fold(sink.events, UNIT).verdicts_raised


def load(tmp_path) -> QuestionsFile:
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert file is not None
    return file


def supersede(tmp_path, sink, round_no=2, **over):
    return supersede_stale_verdicts(
        tmp_path, existing=load(tmp_path), consumed=(), events=sink.events, ledger=sink, round_no=round_no, **over
    )


def test_a_later_round_supersedes_the_open_verdict_questions_of_an_earlier_one(tmp_path):
    sink = _Sink()
    round_one(tmp_path, sink)
    state = fold(sink.events, UNIT)
    assert state.questions.open == ["Q-001", "Q-002", "Q-003"]
    assert labels_for("l4:", "in_review", needs_answers=bool(state.questions.open)) == [
        "l4:in_review",
        "l4:needs-answers",
    ]

    assert supersede(tmp_path, sink) == ["Q-001", "Q-002"]

    file = load(tmp_path)
    for qid in ("Q-001", "Q-002"):
        question = file.get(qid)
        assert question is not None and question.status is QuestionStatus.SUPERSEDED and question.superseded_by is None
        assert question.superseded_round == 2
    text = file.data.decode()
    assert text.count("- **Status:** superseded by round 2\n") == 2
    assert "| Q-001 | superseded |" in text and "| Q-002 | superseded |" in text  # the index follows
    assert verdict_status(file, raised=_ids(sink)).any is False
    [event] = [e for e in sink.events if e.type == "question.superseded"]
    assert event.data == {"ids": ["Q-001", "Q-002"], "round": 2}
    state = fold(sink.events, UNIT)
    assert state.questions.open == ["Q-003"]  # the intake question is not a verdict question
    assert state.questions.answered == []
    assert fold([e for e in sink.events if e.data.get("id") != "Q-003"], UNIT).questions.open == []
    assert labels_for("l4:", "in_review", needs_answers=bool(fold(
        [e for e in sink.events if e.data.get("id") != "Q-003"], UNIT).questions.open)) == ["l4:in_review"]  # fmt: skip


def test_an_answered_verdict_question_a_non_verdict_question_and_a_second_run_are_not_touched(tmp_path):
    sink = _Sink()
    round_one(tmp_path, sink)
    file = load(tmp_path).set_status("Q-002", QuestionStatus.ANSWERED)
    body = file.get("Q-002").answer.body  # type: ignore[union-attr]
    file = QuestionsFile.parse(file.data[: body.end] + b"accept: checked by hand\n" + file.data[body.end :])
    file.save(tmp_path / "questions.md")
    before_q2 = load(tmp_path).get("Q-002")
    assert before_q2 is not None

    assert supersede(tmp_path, sink) == ["Q-001"]

    after = load(tmp_path)
    second = after.get("Q-002")  # the spans moved with Q-001's longer Status, the question did not change
    assert second is not None and second.status is QuestionStatus.ANSWERED
    assert (second.answer_text, second.title, second.asked) == (before_q2.answer_text, before_q2.title, before_q2.asked)
    third = after.get("Q-003")
    assert third is not None and third.status is QuestionStatus.OPEN
    assert blocked_tasks(after.questions, ["1.1"]) == {"1.1"}  # the intake question still holds its task
    assert supersede(tmp_path, sink, round_no=3) == []  # nothing left to supersede, and no second event
    assert [e.data for e in sink.events if e.type == "question.superseded"] == [{"ids": ["Q-001"], "round": 2}]


def test_a_question_the_round_asks_again_and_one_of_the_same_round_stay_open(tmp_path):
    sink = _Sink()
    round_one(tmp_path, sink)
    assert supersede(tmp_path, sink, current=[hold_id(SCOPE)]) == ["Q-002"]  # round 2 still has the scope hold
    assert supersede(tmp_path, sink, round_no=1) == []  # the questions of round 1 are not earlier than round 1
    assert load(tmp_path).get("Q-001").status is QuestionStatus.OPEN  # type: ignore[union-attr]


def test_a_consumed_verdict_question_is_not_touched(tmp_path):
    sink = _Sink()
    round_one(tmp_path, sink)
    ids = supersede_stale_verdicts(
        tmp_path, existing=load(tmp_path), consumed={"Q-001"}, events=sink.events, ledger=sink, round_no=2
    )
    assert ids == ["Q-002"]


def test_the_ledger_event_is_ordered_after_the_questions_it_names():
    events = [
        LedgerEvent(STAMP, "r-1", UNIT, 1, "question.raised", {"id": "Q-001", "kind": "verdict", "round": 1}),
        LedgerEvent(STAMP, "r-1", UNIT, 2, "question.superseded", {"ids": ["Q-001", "Q-009"], "round": 2}),
    ]
    assert fold(events, UNIT).questions.open == []  # an id the fold never saw is ignored
