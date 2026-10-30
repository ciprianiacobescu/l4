"""L4-RACE-001 and the delegate pass (review fix 2): the pass pushes before it asks, and that push can merge a person's
answers. A question that is no longer open when the pass gets to it is skipped: no call, no event, no edit."""

import pytest

from l4.delegate import run as pass_module
from l4.specs.questions import QuestionsFile, QuestionStatus

from .conftest import BRANCH, UNIT_DIR, blocked, reply

QUESTIONS = f"{UNIT_DIR}/questions.md"


@pytest.fixture
def person_answers_after_the_pass_commit(monkeypatch, tdd_repo, raw, tmp_path):
    """A person answers Q-001 on the forge right after the pass committed its questions and before it pushes."""
    real = pass_module.commit_questions
    fired = []

    def commit_questions(*args, **kwargs):
        out = real(*args, **kwargs)
        if not fired:
            fired.append(1)
            clone = tmp_path / "person"
            raw(tmp_path, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
            file = QuestionsFile.parse((clone / QUESTIONS).read_bytes())
            file = file.set_answer("Q-001", "A person says: raise ValueError.").set_status(
                "Q-001", QuestionStatus.ANSWERED
            )
            (clone / QUESTIONS).write_bytes(file.data)
            raw(clone, "add", "-A")
            raw(clone, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "answer Q-001")
            raw(clone, "push", "-q", "origin", BRANCH)
        return out

    monkeypatch.setattr(pass_module, "commit_questions", commit_questions)
    return fired


def test_a_question_a_person_answered_at_the_pass_push_is_not_asked_nor_edited(
    delegate_run, person_answers_after_the_pass_commit
):
    run = delegate_run([blocked("technical"), reply("Q-001")])
    assert person_answers_after_the_pass_commit == [1]
    assert run.events("delegate.asked") == [] and run.events("delegate.result") == []
    assert len(run.adapter.requests) == 1  # the implementer's step only: the delegate was never called
    merged = run.events("push.merged")
    assert [m["commits"] for m in merged] == [1]
    file = QuestionsFile.parse(run.pushed(QUESTIONS).encode())
    question = file.get("Q-001")
    assert question.status is QuestionStatus.ANSWERED and question.answer_text == "A person says: raise ValueError."
    assert question.escalated_by == "" and question.answered_by == ""
