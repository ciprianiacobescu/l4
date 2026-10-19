"""Helpers for the actor tests: a unit repository whose `questions.md` is committed the way `l4 questions` does."""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from l4.clarifier.actor import Actor, answer_actor
from l4.redact import Redactor
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions
from l4.specs.questions_cli import commit_message
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git

REDACTOR = Redactor({})
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def sh(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **ENV}, capture_output=True, text=True, check=True
    )
    return done.stdout


def ask(repo: Path, kind: QuestionKind = QuestionKind.TECHNICAL, n: int = 2, commit: bool = True) -> None:
    for i in range(n):
        raise_questions(
            repo, "add-login", [NewQuestion(f"About {i}?", kind, ("1.1",), "ctx", "asked")], redactor=REDACTOR
        )
    if commit:
        sh(repo, "add", "questions.md")
        sh(repo, "commit", "-q", "-m", "raised")


def set_answer(repo: Path, qid: str, text: str, status: QuestionStatus = QuestionStatus.ANSWERED) -> None:
    file = QuestionsFile.load(repo / "questions.md")
    assert file is not None
    file = file.set_status(qid, status)
    q = file.get(qid)
    assert q is not None and q.answer is not None
    data = file.data[: q.answer.body.end] + text.encode() + b"\n" + file.data[q.answer.body.end :]
    QuestionsFile.parse(data).save(repo / "questions.md")


def answer_commit(repo: Path, qid: str, text: str, by: str, *, form: str = "answer") -> None:
    """A commit with the message `l4 questions` writes (the real `commit_message`), `by` being `person` or a marker."""
    set_answer(repo, qid, text)
    file = QuestionsFile.load(repo / "questions.md")
    assert file is not None
    edit = SimpleNamespace(
        form=form, status=QuestionStatus.ANSWERED, replaced=False,
        folder=SimpleNamespace(unit="openspec:add-login"), question=file.get(qid),
    )  # fmt: skip
    message = commit_message(edit, "t", "person" if by == "person" else "agent", None if by == "person" else by)  # type: ignore[arg-type]
    sh(repo, "add", "questions.md")
    sh(repo, "commit", "-q", "-m", message)


def plain_commit(repo: Path, qid: str, text: str) -> None:
    set_answer(repo, qid, text)
    sh(repo, "add", "questions.md")
    sh(repo, "commit", "-q", "-m", "fix a typo")


def actor_of(repo: Path, qid: str, events: list[LedgerEvent] | None = None) -> Actor:
    file = QuestionsFile.load(repo / "questions.md")
    assert file is not None
    question = file.get(qid)
    assert question is not None
    return answer_actor(Git(repo), repo, question, events or [])


def event(type_: str, **data: object) -> LedgerEvent:
    return LedgerEvent(
        ts=datetime(2026, 10, 18, tzinfo=UTC), run_id="r-1", unit="openspec:add-login", seq=1, type=type_, data=data
    )
