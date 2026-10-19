import hashlib
from pathlib import Path

import pytest

from l4.clarifier.clarifier import Clarifier
from l4.redact import Redactor
from l4.specs.base import Task
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, answer_sha256, raise_questions
from l4.state.ledger import LedgerWriter, read_ledger

UNIT = "openspec:add-x"
REDACTOR = Redactor({})
TASKS = parse_openspec_tasks(b"- [ ] 1.1 a\n- [ ] 1.2 b\n- [x] 1.3 c\n")


def ask(unit_dir: Path, *tasks: str) -> None:
    for key in tasks:
        raise_questions(
            unit_dir, "add-x", [NewQuestion(f"About {key}?", QuestionKind.TECHNICAL, (key,), "ctx", "asked")],
            redactor=REDACTOR,
        )  # fmt: skip


def edit(unit_dir: Path, qid: str, *, status: str, answer: str = "", suggestion: str | None = None) -> None:
    file = QuestionsFile.load(unit_dir / "questions.md")
    assert file is not None
    file = file.set_status(qid, QuestionStatus(status))
    if suggestion is not None:
        file = file.set_suggestion(qid, suggestion, redactor=REDACTOR)
    if answer:
        q = file.get(qid)
        assert q is not None and q.answer is not None
        data = file.data[: q.answer.body.end] + answer.encode() + b"\n" + file.data[q.answer.body.end :]
        file = QuestionsFile.parse(data)
    file.save(unit_dir / "questions.md")


def run(unit_dir: Path, run_id: str, tasks: list[Task] = TASKS):
    writer = LedgerWriter.open(unit_dir, UNIT, run_id, redactor=REDACTOR)
    result = Clarifier(unit_dir, writer).reenter(tasks)
    writer.finish(0)
    return result


def events(unit_dir: Path, *types: str) -> list[dict]:
    return [{"type": e.type, **e.data} for e in read_ledger(unit_dir).events if e.type in types]


def test_human_answer_committed_is_consumed_on_next_run(tmp_path: Path):
    ask(tmp_path, "1.1", "1.2")
    nothing = run(tmp_path, "r-20261004T0100Z-0001")
    assert nothing.answered == () and nothing.unblocks == () and nothing.drafts == () and nothing.overrides == ()
    edit(tmp_path, "Q-001", status="answered", answer="Use argon2id.")
    first = run(tmp_path, "r-20261004T0101Z-0002")
    assert [(a.id, a.by) for a in first.answered] == [("Q-001", "human")]
    assert first.unblocks == ("Q-001",)
    (event,) = events(tmp_path, "question.answered")
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert file is not None and event["id"] == "Q-001" and event["by"] == "human"
    assert event["answer_sha256"] == answer_sha256(file.get("Q-001")) == first.answered[0].answer_sha256
    # consumed once: the next run does not record it again
    again = run(tmp_path, "r-20261004T0102Z-0003")
    assert again.answered == () and again.overrides == ()
    assert len(events(tmp_path, "question.answered")) == 1


def test_a_draft_is_surfaced_and_not_consumed(tmp_path: Path):
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status="open", answer="Maybe argon2id?")
    result = run(tmp_path, "r-20261004T0100Z-0001")
    assert result.drafts == ("Q-001",) and result.answered == () and result.unblocks == ()
    digest = hashlib.sha256(b"Maybe argon2id?").hexdigest()
    drafted = {"type": "question.unsubmitted_answer", "id": "Q-001", "answer_sha256": digest}
    assert events(tmp_path, "question.unsubmitted_answer") == [drafted]
    assert events(tmp_path, "question.answered") == []


def test_a_draft_is_recorded_once_per_answer_text(tmp_path: Path):
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status="open", answer="Maybe argon2id?")
    assert run(tmp_path, "r-20261004T0100Z-0001").drafts == ("Q-001",)  # still reported: the plan shows it
    assert run(tmp_path, "r-20261004T0101Z-0002").drafts == ("Q-001",)
    assert len(events(tmp_path, "question.unsubmitted_answer")) == 1
    edit(tmp_path, "Q-001", status="open", answer="No, bcrypt.")  # a changed draft is news again
    run(tmp_path, "r-20261004T0102Z-0003")
    assert len(events(tmp_path, "question.unsubmitted_answer")) == 2


def test_accepted_and_clarifier_answers_say_who_answered(tmp_path: Path):
    ask(tmp_path, "1.1", "1.2")
    edit(tmp_path, "Q-001", status="accepted", suggestion="Use bcrypt.")
    edit(tmp_path, "Q-002", status="answered-by-clarifier", suggestion="Use 2 decimals.")
    result = run(tmp_path, "r-20261004T0100Z-0001")
    assert [(a.id, a.by) for a in result.answered] == [("Q-001", "human"), ("Q-002", "clarifier")]


def test_dismissed_has_no_hash(tmp_path: Path):
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status="dismissed")
    result = run(tmp_path, "r-20261004T0100Z-0001")
    assert [(a.id, a.by, a.answer_sha256) for a in result.answered] == [("Q-001", "human", None)]
    assert events(tmp_path, "question.answered")[0]["answer_sha256"] is None


def consume(unit_dir: Path, run_id: str, qid: str, answer: str | None) -> None:
    """What `tdd._prompt` records when a prompt carries the answer."""
    digest = hashlib.sha256(answer.encode()).hexdigest() if answer is not None else None
    writer = LedgerWriter.open(unit_dir, UNIT, run_id, redactor=REDACTOR)
    writer.append("prompt.rendered", role="red", task="1.1", answers=[{"id": qid, "answer_sha256": digest}])
    writer.finish(0)


def test_a_consumed_answer_that_changed_is_an_override_recorded_once(tmp_path: Path):
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status="answered", answer="Use argon2id.")
    first = run(tmp_path, "r-20261004T0100Z-0001")
    consume(tmp_path, "r-20261004T0100Z-0002", "Q-001", "Use argon2id.")
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert file is not None
    changed = file.data.replace(b"Use argon2id.", b"Use scrypt.")
    (tmp_path / "questions.md").write_bytes(changed)
    second = run(tmp_path, "r-20261004T0101Z-0003")
    assert second.overrides == ("Q-001",) and second.answered == ()
    (override,) = events(tmp_path, "question.override")
    assert override["id"] == "Q-001" and override["previous_sha256"] == first.answered[0].answer_sha256
    assert override["answer_sha256"] != override["previous_sha256"]
    third = run(tmp_path, "r-20261004T0102Z-0004")  # the new text was recorded: no second event
    assert third.overrides == () and len(events(tmp_path, "question.override")) == 1
    # back to the text the last prompt carried: that is what the implementer used, so it is not an override
    (tmp_path / "questions.md").write_bytes(changed.replace(b"Use scrypt.", b"Use argon2id."))
    back = run(tmp_path, "r-20261004T0103Z-0005")
    assert back.overrides == () and [a.id for a in back.answered] == ["Q-001"]
    assert len(events(tmp_path, "question.override")) == 1


def test_an_answer_edited_before_any_prompt_used_it_is_not_an_override(tmp_path: Path):
    """SCN-CLR-06: the new answer is used, no fix unit."""
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status="answered-by-clarifier", suggestion="Use 2 decimals.")
    run(tmp_path, "r-20261004T0100Z-0001")
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert file is not None
    (tmp_path / "questions.md").write_bytes(file.data.replace(b"Use 2 decimals.", b"Use 3 decimals."))
    second = run(tmp_path, "r-20261004T0101Z-0002")
    assert second.overrides == () and [a.id for a in second.answered] == ["Q-001"]
    assert events(tmp_path, "question.override") == []
    recorded = events(tmp_path, "question.answered")
    assert [e["answer_sha256"] for e in recorded][-1] == hashlib.sha256(b"Use 3 decimals.").hexdigest()
    assert run(tmp_path, "r-20261004T0102Z-0003").answered == ()  # recorded: quiet again


def test_a_dismissed_question_that_was_consumed_and_then_answered_is_an_override(tmp_path: Path):
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status="dismissed")
    run(tmp_path, "r-20261004T0100Z-0001")
    consume(tmp_path, "r-20261004T0100Z-0002", "Q-001", None)
    edit(tmp_path, "Q-001", status="answered", answer="Actually, use argon2id.")
    assert run(tmp_path, "r-20261004T0101Z-0003").overrides == ("Q-001",)


def test_an_answer_whose_tasks_are_done_unblocks_nothing(tmp_path: Path):
    ask(tmp_path, "1.3")
    edit(tmp_path, "Q-001", status="answered", answer="x")
    result = run(tmp_path, "r-20261004T0100Z-0001")
    assert [a.id for a in result.answered] == ["Q-001"] and result.unblocks == ()


def human_sets_status_in_the_section_only(unit_dir: Path, qid: str, status: str) -> None:
    path = unit_dir / "questions.md"
    path.write_bytes(path.read_bytes().replace(b"- **Status:** open", f"- **Status:** {status}".encode(), 1))


def test_the_index_row_follows_a_status_a_human_changed_in_the_section(tmp_path: Path):
    ask(tmp_path, "1.1")
    human_sets_status_in_the_section_only(tmp_path, "Q-001", "dismissed")
    assert b"| Q-001 | open |" in (tmp_path / "questions.md").read_bytes()
    result = run(tmp_path, "r-20261004T0100Z-0001")
    assert result.index_refreshed
    assert b"| Q-001 | dismissed |" in (tmp_path / "questions.md").read_bytes()
    assert not run(tmp_path, "r-20261004T0101Z-0002").index_refreshed


def test_the_index_is_left_alone_when_the_caller_may_not_commit_it(tmp_path: Path):
    ask(tmp_path, "1.1")
    human_sets_status_in_the_section_only(tmp_path, "Q-001", "dismissed")
    writer = LedgerWriter.open(tmp_path, UNIT, "r-20261004T0100Z-0001", redactor=REDACTOR)
    result = Clarifier(tmp_path, writer).reenter(TASKS, refresh_index=False)
    writer.finish(0)
    assert not result.index_refreshed and b"| Q-001 | open |" in (tmp_path / "questions.md").read_bytes()


def test_no_questions_file_is_an_empty_result(tmp_path: Path):
    result = run(tmp_path, "r-20261004T0100Z-0001")
    assert result.answered == result.drafts == result.overrides == result.unblocks == ()
    assert events(tmp_path, "question.answered") == []


@pytest.mark.parametrize("status", ["answered", "accepted"])
def test_a_status_without_text_is_not_answered_and_is_not_recorded(tmp_path: Path, status: str):
    ask(tmp_path, "1.1")
    edit(tmp_path, "Q-001", status=status)
    assert run(tmp_path, "r-20261004T0100Z-0001").answered == ()


def test_reenter_records_the_agent_for_a_technical_answer(repo: Path):
    """SCN-DLG-41: the 0.4.16 bug recorded `human` for every kind but `harness`."""
    from .answer_world import answer_commit, ask

    ask(repo)
    answer_commit(repo, "Q-001", "Use cents.", "CLAUDECODE")
    answer_commit(repo, "Q-002", "Use dollars.", "person")
    writer = LedgerWriter.open(repo, UNIT, "r-20261004T0100Z-0001", redactor=REDACTOR)
    result = Clarifier(repo, writer).reenter(TASKS, refresh_index=False)
    writer.finish(0)
    assert [(a.id, a.by) for a in result.answered] == [("Q-001", "agent"), ("Q-002", "human")]
    recorded = {e["id"]: e for e in events(repo, "question.answered")}
    assert recorded["Q-001"]["by"] == "agent" and recorded["Q-002"]["by"] == "human"


def test_reenter_records_the_marker(repo: Path):
    from .answer_world import answer_commit, ask

    ask(repo, n=1)
    answer_commit(repo, "Q-001", "Use cents.", "CLAUDECODE")
    writer = LedgerWriter.open(repo, UNIT, "r-20261004T0100Z-0001", redactor=REDACTOR)
    Clarifier(repo, writer).reenter(TASKS, refresh_index=False)
    writer.finish(0)
    (event,) = events(repo, "question.answered")
    assert event["by"] == "agent" and event["marker"] == "CLAUDECODE" and "profile" not in event
