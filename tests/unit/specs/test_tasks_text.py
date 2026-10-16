"""task_text: the checkbox line of a task and every line below it up to the next task line or heading (L4-IMP-014)."""

from l4.specs.base import Framework
from l4.specs.kiro import parse_kiro_tasks
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.tasks_text import task_text

KIRO = (
    "# Tasks\n"
    "\n"
    "- [ ] 1. Parent\n"
    "  - [ ] 1.1 Build the thing\n"
    "    - detail one\n"
    "    - detail two\n"
    "    _Requirements: 2.1, 3.3_\n"
    "  - [x] 1.2 Next\n"
    "\n"
    "## Notes\n"
    "- [ ] 2. Last task\n"
    "  - the last detail\n"
)


def kiro(text: str, index: int, newline: str = "\n") -> str:
    data = text.replace("\n", newline).encode()
    return task_text(data, parse_kiro_tasks(data)[index], Framework.KIRO)


def test_openspec_one_line_task():
    data = b"## 1. Group\n\n- [ ] 1.1 First task\n- [ ] 1.2 Second task\n"
    tasks = parse_openspec_tasks(data)
    assert task_text(data, tasks[0], Framework.OPENSPEC) == "- [ ] 1.1 First task\n"
    assert task_text(data, tasks[1], Framework.OPENSPEC) == "- [ ] 1.2 Second task\n"


def test_openspec_detail_lines_up_to_a_heading():
    data = b"- [ ] 1.1 First\n  more words\n\n## 2. Next\n- [ ] 2.1 Other\n"
    task = parse_openspec_tasks(data)[0]
    assert task_text(data, task, Framework.OPENSPEC) == "- [ ] 1.1 First\n  more words\n\n"


def test_kiro_task_with_detail_bullets_and_requirements_line():
    assert kiro(KIRO, 1) == (
        "  - [ ] 1.1 Build the thing\n    - detail one\n    - detail two\n    _Requirements: 2.1, 3.3_\n"
    )


def test_kiro_parent_stops_at_its_first_child():
    assert kiro(KIRO, 0) == "- [ ] 1. Parent\n"


def test_kiro_stops_at_a_heading():
    assert kiro(KIRO, 2) == "  - [ ] 1.2 Next\n\n"


def test_last_task_of_a_file_runs_to_the_end():
    assert kiro(KIRO, 3) == "- [ ] 2. Last task\n  - the last detail\n"


def test_last_line_without_a_terminator():
    assert kiro("- [ ] 1. Only\n  - tail", 0) == "- [ ] 1. Only\n  - tail\n"


def test_ticked_task_equals_unticked_form():
    for mark in "xX-~":
        ticked = f"- [{mark}] 1.1 Build\n  - detail\n"
        assert kiro(ticked, 0) == "- [ ] 1.1 Build\n  - detail\n"
    data = b"- [x] 1.1 First\n"
    assert task_text(data, parse_openspec_tasks(data)[0], Framework.OPENSPEC) == "- [ ] 1.1 First\n"


def test_crlf_is_normalised():
    assert kiro(KIRO, 1, "\r\n") == kiro(KIRO, 1)


def test_bom_is_dropped():
    data = "﻿- [x] 1. First\n  - detail\n".encode()
    assert task_text(data, parse_kiro_tasks(data)[0], Framework.KIRO) == "- [ ] 1. First\n  - detail\n"
