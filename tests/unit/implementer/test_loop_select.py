from pathlib import Path

from l4.implementer.tasks import (
    answers_unblock,
    open_blocking_questions,
    questions_hold,
    select_next_step,
    tick_completed_parents,
    unselectable,
)
from l4.specs.base import Framework, Marker, UnitRef
from l4.specs.openspec import OpenSpecProvider, parse_openspec_tasks
from l4.specs.questions import QuestionsFile


def tasks(text: str):
    return parse_openspec_tasks(text.encode())


def test_the_first_pending_leaf_in_document_order_is_selected():
    parsed = tasks("- [x] 1.1 a\n- [ ] 1.2 b\n- [ ] 1.3 c\n")
    assert select_next_step(parsed).key == "1.2"


def test_a_parent_with_a_pending_child_is_skipped_for_the_child():
    parsed = tasks("- [ ] 1.1 parent\n  - [x] 1.1.1 done\n  - [ ] 1.1.2 pending\n  - [ ] 1.1.3 later\n")
    assert select_next_step(parsed).key == "1.1.2"


def test_a_parent_whose_children_are_all_done_is_never_selected_it_is_closed_instead(tmp_path):
    text = "- [ ] 1.1 parent\n  - [x] 1.1.1 a\n"
    assert select_next_step(tasks(text)) is None  # a leaf has no descendants of any kind
    change = tmp_path / "openspec" / "changes" / "add-x"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(text)
    ref = UnitRef(Framework.OPENSPEC, "add-x", change)
    assert tick_completed_parents(OpenSpecProvider(tmp_path, {}), ref) == ["1.1"]
    assert (change / "tasks.md").read_text() == "- [x] 1.1 parent\n  - [x] 1.1.1 a\n"


def test_nothing_pending_selects_nothing():
    assert select_next_step(tasks("- [x] 1.1 a\n")) is None
    assert select_next_step([]) is None


def test_a_box_the_harness_cannot_tick_is_skipped_and_reported():
    parsed = tasks("- [-] 1.1 in progress marker\n- [ ] 1.2 next\n- [ ]\n")
    assert select_next_step(parsed).key == "1.2"
    assert [t.key for t in unselectable(parsed)] == ["1.1", "L3"]
    only = tasks("- [-] 1.1 in progress marker\n")
    assert select_next_step(only) is None and [t.key for t in unselectable(only)] == ["1.1"]


def test_ticking_the_last_child_ticks_the_parent(tmp_path: Path):
    change = tmp_path / "openspec" / "changes" / "add-x"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(
        "- [ ] 1.1 parent\n  - [x] 1.1.1 a\n  - [x] 1.1.2 b\n- [ ] 2.1 other\n  - [ ] 2.1.1 c\n"
    )
    provider = OpenSpecProvider(tmp_path, {})
    ref = UnitRef(Framework.OPENSPEC, "add-x", change)
    assert tick_completed_parents(provider, ref) == ["1.1"]
    assert (change / "tasks.md").read_text() == (
        "- [x] 1.1 parent\n  - [x] 1.1.1 a\n  - [x] 1.1.2 b\n- [ ] 2.1 other\n  - [ ] 2.1.1 c\n"
    )
    provider.set_marker(ref, "2.1.1", Marker.DONE)
    assert tick_completed_parents(provider, ref) == ["2.1"]
    assert tick_completed_parents(provider, ref) == []


def test_blocked_task_is_skipped_for_independent_one():
    parsed = tasks("- [ ] 1.1 a\n- [ ] 1.2 b\n- [ ] 1.3 c\n")
    assert select_next_step(parsed, {"1.1"}).key == "1.2"
    assert select_next_step(parsed, {"1.1", "1.2"}).key == "1.3"
    assert not questions_hold(parsed, {"1.1"})  # something else can still run


def test_nothing_eligible_and_questions_open_is_told_apart_from_nothing_pending():
    parsed = tasks("- [x] 1.1 a\n- [ ] 1.2 b\n- [ ] 1.3 c\n")
    assert select_next_step(parsed, {"1.2", "1.3"}) is None and questions_hold(parsed, {"1.2", "1.3"})
    done = tasks("- [x] 1.1 a\n")
    assert select_next_step(done, {"1.1"}) is None and not questions_hold(done, {"1.1"})
    assert not questions_hold(parsed, set())  # a blocked key that is not pending changes nothing


def test_a_blocked_parent_holds_its_children_and_a_blocked_child_does_not_hold_the_parent():
    parsed = tasks("- [ ] 1.1 parent\n  - [ ] 1.1.1 a\n  - [ ] 1.1.2 b\n- [ ] 2.1 other\n")
    assert select_next_step(parsed, {"1.1"}).key == "2.1"
    assert select_next_step(parsed, {"1.1.1"}).key == "1.1.2"
    assert questions_hold(tasks("- [ ] 1.1 parent\n  - [ ] 1.1.1 a\n"), {"1.1"})


def questions(*rows: tuple[str, str, str]) -> QuestionsFile:
    return QuestionsFile.parse(
        "\n---\n\n".join(
            f"## {qid}: t\n\n- **Status:** {status}\n- **Blocking tasks:** {keys}\n\n### Answer\nUse it.\n"
            for qid, status, keys in rows
        )
    )


def test_open_blocking_questions_and_answers_that_unblock_a_task():
    parsed = tasks("- [x] 1.1 a\n- [ ] 1.2 b\n- [ ] 1.3 c\n")
    file = questions(("Q-001", "open", "1.2"), ("Q-002", "answered", "1.3"), ("Q-003", "open", "1.1"))
    assert open_blocking_questions(file, parsed) == ["Q-001"]  # Q-003 only blocks a task that is done
    assert answers_unblock(file, parsed) == ["Q-002"]
    assert answers_unblock(questions(("Q-001", "open", "1.2"), ("Q-002", "open", "1.3")), parsed) == []
    assert answers_unblock(questions(("Q-001", "answered", "1.1")), parsed) == []  # nothing pending behind it
    both = questions(("Q-001", "answered", "1.2"), ("Q-002", "open", "1.3"))
    assert answers_unblock(both, parsed) == ["Q-001"] and open_blocking_questions(both, parsed) == ["Q-002"]
    assert answers_unblock(None, parsed) == [] and open_blocking_questions(None, parsed) == []


def test_an_answer_that_frees_a_parent_but_no_eligible_task_unblocks_nothing():
    parsed = tasks("- [ ] 2.1 parent\n  - [ ] 2.1.1 child\n")
    file = questions(("Q-001", "answered", "2.1"), ("Q-002", "open", "2.1.1"))
    assert open_blocking_questions(file, parsed) == ["Q-002"]
    assert answers_unblock(file, parsed) == []  # the parent has a pending child that is held: no step could run


def test_a_section_the_parser_could_not_read_holds_every_pending_task():
    parsed = tasks("- [ ] 1.1 a\n- [ ] 1.2 b\n")
    file = QuestionsFile.parse(
        "## Q-001: a\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n\n### Answer\nUse it.\n```\n"
        "## Q-002: b\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n"
    )
    assert open_blocking_questions(file, parsed) == ["Q-002"]
    assert answers_unblock(file, parsed) == []  # Q-002 holds everything, so Q-001 frees nothing
