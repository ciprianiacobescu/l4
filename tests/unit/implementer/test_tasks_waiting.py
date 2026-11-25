"""`waiting_questions` (L4-VER-095): the open questions of a fix unit when a person's answer is all its tasks await."""

from itertools import count

from l4.implementer.tasks import waiting_questions
from l4.specs.base import Task
from l4.specs.questions import QuestionsFile

_LINES = count(1)


def task(key: str, *, done: bool = False, depth: int = 0) -> Task:
    return Task(key, key, f"task {key}", done, "x" if done else " ", depth, next(_LINES), 0)


def file(*rows: tuple[str, str, str]) -> QuestionsFile:
    return QuestionsFile.parse(
        "\n---\n\n".join(
            f"## {qid}: q\n\n- **Status:** {status}\n- **Blocking tasks:** {blocking}\n"
            for qid, status, blocking in rows
        )
    )


def test_every_pending_task_held_by_an_open_question_is_waiting():
    tasks = [task("1.1"), task("1.2")]
    assert waiting_questions(file(("Q-001", "open", "1.1"), ("Q-002", "open", "1.2")), tasks) == ["Q-001", "Q-002"]


def test_a_pending_task_that_no_question_holds_can_run_so_nothing_waits():
    tasks = [task("1.1"), task("1.2")]
    assert waiting_questions(file(("Q-001", "open", "1.1")), tasks) == []


def test_an_answered_question_holds_nothing():
    tasks = [task("1.1")]
    answered = file(("Q-001", "answered", "1.1")).data.decode() + "\n### Answer\n\nuse the second option\n"
    assert waiting_questions(QuestionsFile.parse(answered), tasks) == []


def test_a_task_that_is_done_is_not_waited_for():
    tasks = [task("1.1", done=True), task("1.2")]
    assert waiting_questions(file(("Q-001", "open", "1.2")), tasks) == ["Q-001"]


def test_no_pending_task_and_no_file_wait_for_nothing():
    assert waiting_questions(file(("Q-001", "open", "1.1")), [task("1.1", done=True)]) == []
    assert waiting_questions(None, [task("1.1")]) == []


def test_a_question_that_cannot_be_read_is_not_set_aside():
    """Its Blocking tasks line is unreadable, so it holds everything, and the harness cannot write its Status."""
    tasks = [task("1.1")]
    assert waiting_questions(file(("Q-001", "open", "see the design")), tasks) == []


def test_a_question_on_a_parent_waits_for_its_children():
    tasks = [task("1", depth=0), task("1.1", depth=2)]
    assert waiting_questions(file(("Q-001", "open", "1")), tasks) == ["Q-001"]
