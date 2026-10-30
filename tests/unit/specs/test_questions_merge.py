"""state-vcs-locks 4.6: `questions.md` merged per question id when both sides changed it (a base merge into a unit
branch). Rules in order: identical, changed on one side only, one side has a human answer, newer commit wins."""

from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    raise_questions,
)
from l4.specs.questions_merge import merge_questions
from l4.vcs.merge import Escalate

ASKED = "2026-10-05T10:00:00Z by implementer `codex`, run r-1, task 1.1"


def ask(unit: Path, *titles: str, asked: str = ASKED) -> bytes:
    raise_questions(
        unit, "x",
        [NewQuestion(t, QuestionKind.PRODUCT, ("1.1",), "ctx", asked) for t in titles],
        redactor=Redactor({}),
    )  # fmt: skip
    return (unit / "questions.md").read_bytes()


def answered(data: bytes, qid: str, text: str, status: QuestionStatus = QuestionStatus.ANSWERED) -> bytes:
    file = QuestionsFile.parse(data).set_status(qid, status)
    body = file.get(qid).answer.body  # type: ignore[union-attr]
    return QuestionsFile.parse(file.data[: body.end] + text.encode() + b"\n" + file.data[body.end :]).data


def suggested(data: bytes, qid: str, text: str) -> bytes:
    file = QuestionsFile.parse(data).set_suggestion(qid, text, redactor=Redactor({}))
    return file.set_status(qid, QuestionStatus.ANSWERED_BY_CLARIFIER).data


def answer_of(data: bytes, qid: str) -> str:
    return QuestionsFile.parse(data).get(qid).answer_text  # type: ignore[union-attr]


@pytest.fixture
def opened(tmp_path: Path) -> bytes:
    return ask(tmp_path, "Should clear() forget the code?")


def test_add_add_without_base(opened):
    branch = answered(opened, "Q-001", "yes: branch")
    main = answered(opened, "Q-001", "yes: main")
    newer = merge_questions(None, branch, main, ours_newer=True)
    assert newer == branch and answer_of(newer, "Q-001") == "yes: branch"
    older = merge_questions(None, branch, main, ours_newer=False)
    assert older == main and "| Q-001 | answered |" in older.decode()
    # the side with the human answer wins over a newer side that has none (rule 3)
    assert merge_questions(None, opened, main, ours_newer=True) == main
    assert merge_questions(None, branch, opened, ours_newer=False) == branch
    # a clarifier's answer is not a human's: the human side wins even when it is the older one
    clarifier = suggested(opened, "Q-001", "the clarifier says yes")
    assert merge_questions(None, clarifier, main, ours_newer=True) == main
    # two clarifier answers (or two humans) are decided by the commit time
    other = suggested(opened, "Q-001", "the clarifier says no")
    assert merge_questions(None, clarifier, other, ours_newer=True) == clarifier
    assert merge_questions(None, clarifier, other, ours_newer=False) == other


def test_unit_side_winning_all_is_byte_identical(opened):
    branch = answered(opened, "Q-001", "yes: branch")
    assert merge_questions(opened, branch, opened, ours_newer=False) == branch  # theirs unchanged: ours
    assert merge_questions(opened, branch, branch, ours_newer=False) == branch  # identical
    assert merge_questions(opened, opened, branch, ours_newer=True) == branch  # only theirs changed: theirs
    main = answered(opened, "Q-001", "yes: main")
    assert merge_questions(opened, branch, main, ours_newer=True) == branch  # both changed: the newer


def test_one_sided_question_kept_and_index_refreshed(tmp_path: Path):
    mine = tmp_path / "a"
    mine.mkdir()
    ours = ask(mine, "First question")
    theirs_dir = tmp_path / "b"
    theirs_dir.mkdir()
    ask(theirs_dir, "First question")
    theirs = ask(theirs_dir, "Second question")  # main raised a Q-002 as well
    merged = merge_questions(ours, ours, theirs, ours_newer=True)
    file = QuestionsFile.parse(merged)
    assert [q.id for q in file.questions] == ["Q-001", "Q-002"]
    assert "| Q-002 | open | 1.1 | product | Second question |" in merged.decode()
    assert merged.decode().count("| Q-001 |") == 1
    # a question only the unit branch has is kept as it is
    only_ours = merge_questions(theirs, theirs, ours, ours_newer=False)
    assert [q.id for q in QuestionsFile.parse(only_ours).questions] == ["Q-001", "Q-002"]


def test_same_id_different_question_escalates(tmp_path: Path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    ours = ask(one, "Should clear() forget the code?")
    theirs = ask(two, "Is the VAT rate configurable?")
    with pytest.raises(Escalate, match="Q-001"):
        merge_questions(None, ours, theirs, ours_newer=True)
    other_ask = ask(tmp_path, "Should clear() forget the code?", asked="2026-10-06T00:00:00Z by implementer `x`")
    with pytest.raises(Escalate, match="Q-001"):
        merge_questions(None, ours, other_ask, ours_newer=True)


# --- a person's answer beats the delegate's (L4-RACE-001, design D3, SCN-RACE-02) ------------------------------------


def by_delegate(data: bytes, qid: str, text: str) -> bytes:
    """The delegate's answer: `answered` and the harness-owned `Answered by:` line (L4-DLG-006)."""
    file = QuestionsFile.parse(answered(data, qid, text))
    return file.set_field(qid, "Answered by", "the delegate (m via c; profile p)").data


def accepted_by_delegate(data: bytes, qid: str, text: str) -> bytes:
    file = QuestionsFile.parse(data).set_suggestion(qid, text, redactor=Redactor({}))
    file = file.set_status(qid, QuestionStatus.ACCEPTED)
    return file.set_field(qid, "Answered by", "the delegate (m via c; profile p)").data


def escalated_by_delegate(data: bytes, qid: str) -> bytes:
    return QuestionsFile.parse(data).set_field(qid, "Escalated by", "the delegate: needs a person").data


@pytest.fixture
def four(tmp_path: Path) -> bytes:
    return ask(tmp_path, "First?", "Second?", "Third?", "Fourth?")


@pytest.mark.parametrize("ours_newer", [True, False])
def test_a_persons_answer_beats_the_delegates_accept_and_escalation_in_either_order_of_time(four, ours_newer):
    """SCN-RACE-02: the run's delegate accepted Q-001 and escalated Q-002 (ours); a person answered both on the forge
    (theirs). Q-003 only the person changed, Q-004 only the run: each keeps its side."""
    ours = accepted_by_delegate(four, "Q-001", "take option 1")
    ours = escalated_by_delegate(ours, "Q-002")
    ours = by_delegate(ours, "Q-004", "delegate on four")
    theirs = answered(four, "Q-001", "yes: person one")
    theirs = answered(theirs, "Q-002", "yes: person two")
    theirs = answered(theirs, "Q-003", "yes: person three")
    merged = merge_questions(four, ours, theirs, ours_newer)
    assert answer_of(merged, "Q-001") == "yes: person one" and answer_of(merged, "Q-002") == "yes: person two"
    assert answer_of(merged, "Q-003") == "yes: person three" and answer_of(merged, "Q-004") == "delegate on four"
    kept = QuestionsFile.parse(merged)
    assert kept.get("Q-001").answered_by == "" and kept.get("Q-002").escalated_by == ""  # type: ignore[union-attr]
    assert kept.get("Q-004").answered_by.startswith("the delegate")  # type: ignore[union-attr]
    assert "| Q-001 | answered |" in merged.decode()


@pytest.mark.parametrize("ours_newer", [True, False])
def test_a_delegates_answer_loses_to_a_persons_also_when_the_person_is_on_the_unit_side(four, ours_newer):
    ours = answered(four, "Q-001", "yes: person")
    theirs = by_delegate(four, "Q-001", "yes: delegate")
    merged = merge_questions(four, ours, theirs, ours_newer)
    assert merged == ours and answer_of(merged, "Q-001") == "yes: person"


@pytest.mark.parametrize("ours_newer", [True, False])
def test_the_delegates_escalation_loses_to_a_persons_answer_on_either_side(four, ours_newer):
    escalated, human = escalated_by_delegate(four, "Q-001"), answered(four, "Q-001", "yes: person")
    assert merge_questions(four, escalated, human, ours_newer) == human
    assert merge_questions(four, human, escalated, ours_newer) == human


def test_two_persons_answers_and_two_delegates_answers_are_still_settled_by_time(four):
    one, two = answered(four, "Q-001", "yes: one"), answered(four, "Q-001", "yes: two")
    assert answer_of(merge_questions(four, one, two, True), "Q-001") == "yes: one"
    assert answer_of(merge_questions(four, one, two, False), "Q-001") == "yes: two"
    d_one, d_two = by_delegate(four, "Q-001", "yes: one"), by_delegate(four, "Q-001", "yes: two")
    assert answer_of(merge_questions(four, d_one, d_two, True), "Q-001") == "yes: one"
    assert answer_of(merge_questions(four, d_one, d_two, False), "Q-001") == "yes: two"


def test_a_clarifiers_suggestion_is_still_not_a_persons_answer(four):
    """The old rule kept: `answered-by-clarifier` is no human answer; a person's answer beats it."""
    suggestion, human = suggested(four, "Q-001", "yes: clarifier"), answered(four, "Q-001", "yes: person")
    assert merge_questions(four, suggestion, human, True) == human
    assert merge_questions(four, human, suggestion, False) == human
