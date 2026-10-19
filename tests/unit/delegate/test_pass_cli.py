"""The CLI that served an answer is on every record the downstream labels read (delegate-answers 13.1; L4-DLG-010):
`delegate.result` and `question.answered` carry `cli` beside `model`, and `answer_actor` returns it, so that the
judge's list, `verification.md` and the report can say `(<model> via <cli>)`."""

from datetime import UTC, datetime

from l4.clarifier.actor import Actor, answer_actor
from l4.specs.questions import QuestionKind, QuestionsFile, QuestionStatus, answer_sha256
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git

from ..clarifier.answer_world import ask, set_answer, sh
from .conftest import blocked, reply


def test_the_records_of_an_answer_name_the_cli(delegate_run):
    run = delegate_run([blocked("technical"), reply()])
    (result,) = run.events("delegate.result")
    (answered,) = run.events("question.answered")
    assert (result["model"], result["cli"]) == ("delegate-model-1", "fake")
    assert (answered["model"], answered["cli"]) == ("delegate-model-1", "fake")


def test_answer_actor_returns_the_cli(tmp_path):
    sh(tmp_path, "init", "-q", "-b", "unit")
    ask(tmp_path, QuestionKind.TECHNICAL)
    set_answer(tmp_path, "Q-001", "Use cents.", QuestionStatus.ANSWERED)
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert file is not None
    question = file.get("Q-001")
    assert question is not None
    event = LedgerEvent(
        datetime(2026, 10, 18, tzinfo=UTC), "r", "u", 1, "question.answered",
        {"id": "Q-001", "by": "delegate", "profile": "dlg", "model": "gpt-6.1-sol", "cli": "codex",
         "answer_sha256": answer_sha256(question)},
    )  # fmt: skip
    actor = answer_actor(Git(tmp_path), tmp_path, question, [event])
    assert actor == Actor("delegate", profile="dlg", model="gpt-6.1-sol", cli="codex")
    assert actor.fields() == {"profile": "dlg", "model": "gpt-6.1-sol", "cli": "codex"}
