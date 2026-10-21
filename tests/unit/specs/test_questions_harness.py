"""The question kind `harness` (L4-IMP-063, L4-QMD-004): a check L4 could not decide holds its task, and only
`accept` or `retry` answers it."""

from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    harness_answer,
    is_answered,
    raise_questions,
)

ASKED = "2026-10-16T10:00:00Z by implementer `codex`, run r-20261016T1000Z-aaaa, task 3.1"


def harness_file(tmp_path: Path) -> QuestionsFile:
    batch = [
        NewQuestion(
            title="Task 3.1: the pre-satisfied check could not decide",
            kind=QuestionKind.HARNESS,
            blocking_tasks=("3.1",),
            context="L4 could not run the check.",
            asked=ASKED,
            options=("accept: count these on the evidence of the real run", "retry: run the check again"),
        )
    ]
    raise_questions(tmp_path, "add-login", batch, redactor=Redactor({}))
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert file is not None
    return file


def test_a_harness_question_renders_and_parses_back(tmp_path):
    file = harness_file(tmp_path)
    assert "- **Kind:** harness" in (tmp_path / "questions.md").read_text(encoding="utf-8")
    question = file.get("Q-001")
    assert question is not None and question.kind is QuestionKind.HARNESS and question.blocking_tasks == ("3.1",)


def test_a_new_file_header_names_the_harness_answers(tmp_path):
    harness_file(tmp_path)
    header = (tmp_path / "questions.md").read_text(encoding="utf-8")
    assert "Kind values: technical · product · ambiguous · verdict · harness." in header
    assert "for a `harness` question, with `accept` or `retry`" in header


@pytest.mark.parametrize(
    ("text", "status", "expected"),
    [
        ("accept: the run broke", QuestionStatus.ANSWERED, "accept"),
        ("Accept", QuestionStatus.ANSWERED, "accept"),
        ("retry: after the upgrade", QuestionStatus.ANSWERED, "retry"),
        ("retry, upgraded", QuestionStatus.ANSWERED, "retry"),
        ("looks fine", QuestionStatus.ANSWERED, None),
        ("", QuestionStatus.DISMISSED, "retry"),
        ("accept: fine", QuestionStatus.OPEN, None),
    ],
)
def test_harness_answer_reads_the_first_word(tmp_path, text, status, expected):
    file = harness_file(tmp_path)
    if text:
        file = file.set_answer("Q-001", text)
    file = file.set_status("Q-001", status)
    question = file.get("Q-001")
    assert question is not None
    assert harness_answer(question) == expected
    assert is_answered(question) == (expected is not None)
