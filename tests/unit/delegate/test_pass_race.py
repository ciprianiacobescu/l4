"""L4-RACE-001 and the delegate pass (review fix 2): the pass pushes before it asks, and that push can merge a person's
answers. A question that is no longer open when the pass gets to it is skipped: no call, no event, no edit."""

import pytest

from l4.delegate import run as pass_module
from l4.specs.questions import QuestionsFile, QuestionStatus

from ..orchestrator.test_push_secret_scan import fold_events
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


def test_a_failed_final_push_publishes_no_answer_the_branch_does_not_have(
    delegate_run, tdd_repo, raw, tmp_path, monkeypatch
):
    """L4-RACE-002: the delegate answers Q-001 and commits it; a person pushes a file that is no answer; the run's
    final push fails. Its published tail must not make the question final (it is open on the branch), must keep the
    money, and must leave the fold's phase and `status` where the branch has them."""
    from l4.config.schema import DelegateCfg
    from l4.delegate.due import due_questions
    from l4.delegate.limits import delegate_cost
    from l4.specs.openspec import OpenSpecProvider
    from l4.state.status import load_snapshot
    from l4.vcs.git import Git

    fired = []
    real = Git.commit

    def commit(self, message, *args, **kwargs):
        sha = real(self, message, *args, **kwargs)
        if message.startswith("answer Q-001") and not fired:
            fired.append(1)
            clone = tmp_path / "person"
            raw(tmp_path, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
            (clone / "README.md").write_text("a person edited this\n")
            raw(clone, "add", "-A")
            raw(clone, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "readme")
            raw(clone, "push", "-q", "origin", BRANCH)
        return sha

    monkeypatch.setattr(Git, "commit", commit)
    run = delegate_run([blocked("technical"), reply("Q-001")])
    assert fired == [1] and run.code == 1
    provider = OpenSpecProvider(tdd_repo.repo, tdd_repo.environ)
    (ref,) = provider.list_units()
    snap = load_snapshot(provider, Git(tdd_repo.repo, environ=tdd_repo.environ), ref, branch_prefix="l4/")
    assert QuestionsFile.parse(run.pushed(QUESTIONS).encode()).get("Q-001").status is QuestionStatus.OPEN
    cfg = DelegateCfg(enabled=True)
    assert [key for key, _ in due_questions(snap, cfg)] == ["Q-001"]  # the delegate has still to decide it
    assert delegate_cost(snap.events) == 0.2  # the money was spent
    assert snap.open_run is None  # the run ended
    assert snap.state.phase == fold_events(run.branch_ledger()).phase  # the branch's phase, not the lost tail's
