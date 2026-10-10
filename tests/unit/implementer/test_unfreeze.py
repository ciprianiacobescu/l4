"""What a human answer unfreezes for a task's green (M1.10 decision 6; L4-IMP-002, L4-QMD-005, L4-QMD-006)."""

from datetime import UTC, datetime
from pathlib import Path

from l4.implementer.guards import FreezeManifest, FrozenFile
from l4.implementer.unfreeze import unfrozen
from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    answered_by,
    raise_questions,
)
from l4.state.ledger import LedgerEvent

TEST = "tests/test_notices.py"
SUGGESTION = (
    "Change `tests/test_notices.py:8` to expect the 30-day wording, and update the notice in `src/pricing/notices.py`."
)
MANIFEST = FreezeManifest(
    "r" * 40,
    {
        TEST: FrozenFile("a" * 64, "test"),
        "tests/test_other.py": FrozenFile("b" * 64, "test"),
        "tests/conftest.py": FrozenFile("c" * 64, "support"),
    },
    ("**/conftest.py",),
)
SCOPE = frozenset({"1.1", "1"})


def sub(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


CONTEXT = f"`{TEST}` calls `RETURN_POLICY()`. The criteria require a `str`."  # the live Q-002 names its test


def ask(
    tmp_path: Path, *, kind=QuestionKind.TECHNICAL, tasks=("1.1",), title="The test freezes a wrong constant",
    context: str = CONTEXT,
):  # fmt: skip
    raise_questions(
        tmp_path, "add-x", [NewQuestion(title, kind, tasks, context, "now", ("a", "b"))], redactor=Redactor({})
    )
    return QuestionsFile.load(tmp_path / "questions.md")


def with_status(file, status: QuestionStatus, *, suggestion: str = SUGGESTION, answer: str | None = None):
    if suggestion:
        file = file.set_suggestion("Q-001", suggestion, redactor=Redactor({}))
    file = file.set_status("Q-001", status)
    if answer is not None:
        body = file.get("Q-001").answer.body
        file = QuestionsFile.parse(file.data[: body.end] + answer.encode() + b"\n" + file.data[body.end :])
    return file


def recorded(file, qid: str = "Q-001", by: str | None = None, digest: str | None = None) -> list[LedgerEvent]:
    question = file.get(qid)
    data = {"id": qid, "by": by or answered_by(question), "answer_sha256": digest or answer_sha256(question)}
    return [LedgerEvent(datetime(2026, 10, 6, tzinfo=UTC), "r-20261006T0000Z-0001", "openspec:add-x", 1,
                        "question.answered", data)]  # fmt: skip


def test_the_live_q002_accepted_suggestion_unfreezes_its_test(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED)
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == (TEST,) and got.question == "Q-001" and got.answer_sha256 == answer_sha256(file.get("Q-001"))
    assert got.kept == ()  # the other frozen files are not named
    answered = with_status(ask(sub(tmp_path, "b")), QuestionStatus.ANSWERED,
                           suggestion="", answer=f"Yes: edit {TEST}, line 8.")  # fmt: skip
    assert unfrozen(answered.questions, recorded(answered), SCOPE, MANIFEST).paths == (TEST,)


def test_answered_by_clarifier_never_unfreezes(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ANSWERED_BY_CLARIFIER)
    assert unfrozen(file.questions, recorded(file), SCOPE, MANIFEST).paths == ()
    open_ = with_status(ask(sub(tmp_path, "x")), QuestionStatus.OPEN)
    assert unfrozen(open_.questions, recorded(open_), SCOPE, MANIFEST).paths == ()
    forged = with_status(ask(sub(tmp_path, "y")), QuestionStatus.ACCEPTED)
    assert unfrozen(forged.questions, recorded(forged, by="clarifier"), SCOPE, MANIFEST).paths == ()


def test_an_answer_edited_after_it_was_recorded_does_not_count(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED)
    events = recorded(file)
    edited = file.set_suggestion("Q-001", SUGGESTION + " Also tests/test_other.py.", redactor=Redactor({}))
    assert unfrozen(edited.questions, events, SCOPE, MANIFEST).paths == ()  # the digest no longer matches
    assert unfrozen(file.questions, [], SCOPE, MANIFEST).paths == ()  # never recorded at a re-entry


def test_a_named_support_file_stays_frozen(tmp_path):
    text = (
        "Update `tests/conftest.py` and tests/test_notices.py, plus tests/test_unknown.py and src/pricing/notices.py."
    )
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=text)
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == (TEST,)
    assert [p for p, _ in got.kept] == ["tests/conftest.py"] and "support" in got.kept[0][1]


def test_a_question_of_another_task_or_a_verdict_does_not_count(tmp_path):
    other = with_status(ask(tmp_path, tasks=("2.1",)), QuestionStatus.ACCEPTED)
    assert unfrozen(other.questions, recorded(other), SCOPE, MANIFEST).paths == ()
    parent = with_status(ask(sub(tmp_path, "p"), tasks=("1",)),
                         QuestionStatus.ACCEPTED)  # fmt: skip
    assert unfrozen(parent.questions, recorded(parent), SCOPE, MANIFEST).paths == (TEST,)  # a parent holds its children
    verdict = with_status(
        ask(sub(tmp_path, "v"), kind=QuestionKind.VERDICT),
        QuestionStatus.ACCEPTED,
    )
    assert unfrozen(verdict.questions, recorded(verdict), SCOPE, MANIFEST).paths == ()


def test_path_tokens_with_line_and_punctuation(tmp_path):
    cases = {
        "see tests/test_notices.py.": True,
        "(tests/test_notices.py:8)": True,
        "tests/test_notices.py:8-12, then": True,
        '"tests/test_notices.py"': True,
        "tests/test_notices.pyc": False,
        "mytests/test_notices.py": False,
        "tests/test_notices.py.bak": False,
        "tests/test_notices": False,
        "the test_notices.py file": False,
    }
    for index, (text, expected) in enumerate(cases.items()):
        folder = tmp_path / str(index)
        folder.mkdir()
        file = with_status(ask(folder), QuestionStatus.ACCEPTED, suggestion=text)
        got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST).paths
        assert (got == (TEST,)) is expected, text
    many = " ".join(f"tests/test_{n}.py" for n in "abcde")
    wide = FreezeManifest("r" * 40, {f"tests/test_{n}.py": FrozenFile("a" * 64, "test") for n in "abcde"}, ())
    folder = tmp_path / "many"
    folder.mkdir()
    file = with_status(ask(folder, context=many), QuestionStatus.ACCEPTED, suggestion=many)
    got = unfrozen(file.questions, recorded(file), SCOPE, wide)
    assert len(got.paths) == 3 and len(got.kept) == 2  # at most 3 per question


def test_an_accepted_suggestion_unfreezes_only_tests_the_question_names(tmp_path):
    """An accepted answer is the clarifier's text, not the human's: it unfreezes only a test the question itself names
    (title, Context, Options), never one it adds (review of M1.10 line 10). A human's own answer may name any test."""
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=f"Change {TEST}:8 and tests/test_other.py.")
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == (TEST,)
    assert [p for p, _ in got.kept] == ["tests/test_other.py"] and "question" in got.kept[0][1]
    unnamed = with_status(ask(sub(tmp_path, "u"), context="The constant is wrong."), QuestionStatus.ACCEPTED)
    assert unfrozen(unnamed.questions, recorded(unnamed), SCOPE, MANIFEST).paths == ()
    titled = with_status(ask(sub(tmp_path, "t"), title=f"{TEST} is wrong", context="ctx"), QuestionStatus.ACCEPTED)
    assert unfrozen(titled.questions, recorded(titled), SCOPE, MANIFEST).paths == (TEST,)
    human = with_status(ask(sub(tmp_path, "h"), context="The constant is wrong."), QuestionStatus.ANSWERED,
                        suggestion="", answer=f"Edit {TEST} and tests/test_other.py.")  # fmt: skip
    assert unfrozen(human.questions, recorded(human), SCOPE, MANIFEST).paths == (TEST, "tests/test_other.py")
