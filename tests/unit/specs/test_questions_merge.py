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
