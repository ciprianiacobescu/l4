"""L4-QMD-009 / D11: one function says who answered, from the status, the ledger and the `By:` line of the commit."""

from pathlib import Path

import pytest

from l4.clarifier.actor import Actor
from l4.specs.questions import QuestionKind, QuestionsFile, QuestionStatus, answer_sha256

from .answer_world import actor_of, answer_commit, ask, event, plain_commit, set_answer, sh


def test_clarifier_status_is_the_clarifier(repo: Path):
    ask(repo)
    set_answer(repo, "Q-001", "Use cents.", QuestionStatus.ANSWERED_BY_CLARIFIER)
    assert actor_of(repo, "Q-001") == Actor("clarifier")


@pytest.mark.parametrize("kind", ["technical", "product", "ambiguous", "verdict", "harness"])
def test_an_agent_commit_is_the_agent_for_every_kind(repo: Path, kind: str):
    ask(repo, QuestionKind(kind))
    answer_commit(repo, "Q-002", "accept: the test covers it", "CLAUDECODE")
    assert actor_of(repo, "Q-002") == Actor("agent", marker="CLAUDECODE")


def test_a_person_commit_is_the_person(repo: Path):
    ask(repo)
    answer_commit(repo, "Q-001", "Use cents.", "person")
    assert actor_of(repo, "Q-001") == Actor("human")


def test_a_hand_edit_after_the_agent_is_the_person(repo: Path):  # SCN-DLG-42
    ask(repo)
    answer_commit(repo, "Q-001", "Use cents.", "CLAUDECODE")
    file = QuestionsFile.load(repo / "questions.md")
    assert file is not None
    data = file.data.replace(b"Use cents.", b"Use dollars.")
    (repo / "questions.md").write_bytes(data)
    sh(repo, "add", "questions.md")
    sh(repo, "commit", "-q", "-m", "edit by hand")
    assert actor_of(repo, "Q-001") == Actor("human")


def test_another_question_commit_does_not_decide(repo: Path):  # SCN-DLG-41
    ask(repo)
    answer_commit(repo, "Q-001", "Use cents.", "CLAUDECODE")
    answer_commit(repo, "Q-002", "Use dollars.", "person")
    assert actor_of(repo, "Q-001") == Actor("agent", marker="CLAUDECODE")
    assert actor_of(repo, "Q-002") == Actor("human")


def test_an_unrelated_commit_of_the_file_does_not_hide_the_agent(repo: Path):
    ask(repo)
    answer_commit(repo, "Q-001", "Use cents.", "CLAUDECODE")
    plain_commit(repo, "Q-002", "Use dollars.")
    assert actor_of(repo, "Q-001") == Actor("agent", marker="CLAUDECODE")
    assert actor_of(repo, "Q-002") == Actor("human")


def _forge_delegate(repo: Path) -> None:
    set_answer(repo, "Q-001", "Use cents.")
    sh(repo, "add", "questions.md")
    sh(repo, "commit", "-q", "-m", "answer Q-001 (add-login): About 0?\n\nStatus: answered\nBy: delegate (x via y)\n")


def test_the_delegate_needs_its_ledger_record(repo: Path):  # SCN-DLG-43
    ask(repo)
    _forge_delegate(repo)
    assert actor_of(repo, "Q-001") == Actor("agent")
    file = QuestionsFile.load(repo / "questions.md")
    assert file is not None
    digest = answer_sha256(file.get("Q-001"))
    stale = event("question.answered", id="Q-001", by="delegate", profile="p", model="m", answer_sha256="0" * 64)
    assert actor_of(repo, "Q-001", [stale]) == Actor("agent")
    current = event("question.answered", id="Q-001", by="delegate", profile="p", model="m", answer_sha256=digest)
    assert actor_of(repo, "Q-001", [current]) == Actor("delegate", profile="p", model="m")


def test_a_delegate_result_with_the_digest_is_the_delegate(repo: Path):
    ask(repo)
    set_answer(repo, "Q-001", "Use cents.")
    file = QuestionsFile.load(repo / "questions.md")
    assert file is not None
    result = event(
        "delegate.result", id="Q-001", status="answered", profile="p", model="m",
        answer_sha256=answer_sha256(file.get("Q-001")),
    )  # fmt: skip
    assert actor_of(repo, "Q-001", [result]) == Actor("delegate", profile="p", model="m")


def test_history_is_bounded(repo: Path):
    ask(repo)
    answer_commit(repo, "Q-001", "Use cents.", "CLAUDECODE")
    # only commits that touched the file count: touch it 201 times, none an `l4 questions` commit of Q-001
    for i in range(201):
        set_answer(repo, "Q-002", f"v{i}")
        sh(repo, "add", "questions.md")
        sh(repo, "commit", "-q", "-m", f"hand {i}")
    assert actor_of(repo, "Q-001") == Actor("human")


def test_no_repository_is_a_person(tmp_path: Path):
    ask(tmp_path, commit=False)  # a directory that is no git repository: git cannot say, so a person
    set_answer(tmp_path, "Q-001", "Use cents.")
    assert actor_of(tmp_path, "Q-001") == Actor("human")
