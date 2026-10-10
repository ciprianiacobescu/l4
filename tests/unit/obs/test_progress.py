"""The progress trace: ledger events become `[l4] <unit> <message>` lines, and a secret never reaches the console."""

import io
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.log import RedactingFormatter
from l4.progress import ProgressTrace
from l4.redact import Redactor
from l4.state.ledger import LedgerEvent, LedgerWriter

RUN = "r-20261004T1200Z-abcd"
GITLAB_TOKEN = "glpat-" + "k9L8m7N6" * 3
CONFIGURED = "hunter2-hunter2-hunter2"


@pytest.fixture
def console():
    """The `l4` logger writing into a buffer through the real formatter, as `configure_logging` wires it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(Redactor({"L4_FORGE_TOKEN": CONFIGURED}), as_json=False))
    logger = logging.getLogger("l4")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.INFO)
    yield stream
    logger.handlers, logger.level, logger.propagate = saved[0], saved[1], saved[2]


def event(type_: str, **data: object) -> LedgerEvent:
    return LedgerEvent(datetime(2026, 10, 4, 12, 0, tzinfo=UTC), RUN, "openspec:demo", 1, type_, data)


def test_a_token_in_an_event_never_reaches_the_console_through_the_ledger(console, tmp_path: Path):
    redactor = Redactor({"L4_FORGE_TOKEN": CONFIGURED})
    writer = LedgerWriter.open(tmp_path, "openspec:demo", RUN, redactor=redactor, observers=[ProgressTrace()])
    writer.append("task.started", task="1.1", title=f"use {GITLAB_TOKEN} and {CONFIGURED}")
    writer.append("question.raised", id="Q-001", kind="ambiguous", title=f"is {GITLAB_TOKEN} ok?")
    writer.append("run.finished", exit_code=0)
    out = console.getvalue()
    assert "task 1.1 started" in out and "question Q-001 raised" in out and "run finished: exit 0" in out
    assert GITLAB_TOKEN not in out and CONFIGURED not in out
    assert GITLAB_TOKEN not in (tmp_path / ".l4" / "ledger" / f"{RUN}.jsonl").read_text()


def test_a_token_handed_straight_to_the_trace_is_still_redacted_by_the_log_formatter(console):
    trace = ProgressTrace()
    trace(event("task.started", task="1.1", title=f"x {GITLAB_TOKEN} {CONFIGURED}"))
    trace(event("gate.finished", name="test", status="fail", exit_code=1, reason=f"boom {GITLAB_TOKEN}", tests=1,
                passed=0, failed=1))  # fmt: skip
    out = console.getvalue()
    assert out.count("[l4] openspec:demo ") == 2
    assert GITLAB_TOKEN not in out and CONFIGURED not in out and "[REDACTED:" in out


def test_selection_line_follows_the_spec_format(console):
    probes = {"binary": {"version": "0.160.0"}, "auth": {"auth_method": "chatgpt"}, "hello": {"ms": 4200}}
    ProgressTrace()(event("availability.selected", role="implementer", selected="codex", fallback_index=0,
                          skipped=[], probes=probes))  # fmt: skip
    assert console.getvalue() == (
        "[l4] openspec:demo implementer: codex ok (binary 0.160.0 · auth chatgpt · hello 4.2s) → selected\n"
    )


def test_an_unknown_event_prints_nothing_and_a_broken_one_does_not_raise(console):
    trace = ProgressTrace()
    trace(event("something.new", x=1))
    trace(event("gate.finished"))  # no fields at all
    assert "something" not in console.getvalue()


def test_a_fix_units_task_with_the_parents_task_key_is_told_apart_and_nothing_crashes(console):
    trace = ProgressTrace()
    trace(event("task.started", task="1.1", title="parent task"))
    trace(event("step.started", task="1.1", phase="red", attempt=1, agent="impl"))
    trace(event("agent.finished", task="1.1", phase="red", status="ok"))
    trace(event("task.started", task="1.1", title="fix task", fix_unit="demo-fix-1"))
    trace(event("step.started", task="1.1", phase="single", attempt=1, agent="impl", fix_unit="demo-fix-1"))
    trace(event("agent.finished", task="1.1", phase="single", status="ok", fix_unit="demo-fix-1"))
    trace(event("agent.finished", task="1.1", phase="single", status="ok", fix_unit="demo-fix-1"))  # no start: no crash
    lines = console.getvalue().splitlines()
    assert "[l4] openspec:demo task 1.1 started: parent task" in lines
    assert "[l4] openspec:demo [demo-fix-1] task 1.1 started: fix task" in lines
    assert all("agent single task 1.1 ok" in line for line in lines if "agent single" in line)


def test_base_merge_lines(console):
    logging.getLogger("l4").setLevel(logging.INFO)
    trace = ProgressTrace()
    trace(event("run.started", branch="l4/openspec/demo", base="a" * 40, iteration=1, harness_commit="b" * 40))
    trace(event("base.merged", base="main", base_sha="c" * 40, merge_sha="d" * 40, behind=1, resolved=[],
                frozen_touched=[]))  # fmt: skip
    trace(event("base.merged", base="main", base_sha="e" * 40, merge_sha="f" * 40, behind=4,
                resolved=["openspec/changes/demo/questions.md"], frozen_touched=[]))  # fmt: skip
    trace(event("base.conflict", base="main", base_sha="1" * 40, files=["src/a.py", "src/b.py"], resolved=[]))
    lines = [line for line in console.getvalue().splitlines() if "base" in line and "run " not in line]
    assert lines == [
        "[l4] openspec:demo base merged: main@cccccccccc into l4/openspec/demo as dddddddddd (1 commit)",
        "[l4] openspec:demo base merged: main@eeeeeeeeee into l4/openspec/demo as ffffffffff "
        "(4 commits; resolved openspec/changes/demo/questions.md)",
        "[l4] openspec:demo base merge conflict with main@1111111111: src/a.py, src/b.py; "
        "merge it by hand and push (exit 1)",
    ]


def test_a_check_the_run_makes_after_setup_is_on_the_console(console):
    trace = ProgressTrace()
    message = "coverage.py is not importable by .venv/bin/python"
    trace(event("doctor.check", id="COV-001", status="fail", message=message))
    trace(event("doctor.check", id="COV-001", status="pass", message="coverage.py imports in .venv/bin/python"))
    out = console.getvalue()
    assert "doctor COV-001 fail: coverage.py is not importable" in out and "doctor COV-001 pass:" in out


def test_review_reentry_and_ci_lines(console):
    trace = ProgressTrace()
    trace(event("run.started", branch="l4/openspec/demo", base="a" * 40, iteration=2))
    trace(event("phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="commit_after_handoff",
                handoff="h" * 40, lost=False,
                commits=[{"sha": "1" * 40, "author": "ann", "subject": "fix the CI job"}]))  # fmt: skip
    trace(event("phase.changed", **{"from": "in_review", "to": "implementing"}, trigger="spec_edit_after_handoff",
                handoff="h" * 40, lost=False,
                commits=[{"sha": "2" * 40, "author": "bob", "subject": "add a task"},
                         {"sha": "3" * 40, "author": "ann", "subject": "answer Q-001"}]))  # fmt: skip
    trace(event("phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed",
                head="h" * 40, pipeline=7, jobs=[{"name": "test"}, {"name": "lint"}], preexisting=[]))  # fmt: skip
    trace(event("ci.failed", head="h" * 40, pipeline=7, jobs=[{"name": "test"}, {"name": "lint"}], preexisting=[]))
    trace(event("ci.preexisting", head="h" * 40, pipeline=7, jobs=["always-red"]))
    lines = [line for line in console.getvalue().splitlines() if "started (iteration" not in line]
    assert lines == [
        "[l4] openspec:demo phase in_review → verifying (commit_after_handoff: 1 commit, 1111111111 fix the CI job "
        "by ann)",
        "[l4] openspec:demo phase in_review → implementing (spec_edit_after_handoff: 2 commits, 3333333333 answer "
        "Q-001 by ann)",
        "[l4] openspec:demo phase in_review → verifying (repository_ci_failed: test, lint on hhhhhhhhhh)",
        "[l4] openspec:demo repository CI failed on hhhhhhhhhh: test, lint (pipeline 7); l4 run re-verifies",
        "[l4] openspec:demo CI jobs red on H and on the base: always-red (pre-existing, no fix round)",
    ]


def test_zeroed_runs_say_they_are_expected_to_fail(console):
    trace = ProgressTrace()
    trace(event("gate.finished", name="test-presatisfied", status="fail", exit_code=1))
    trace(event("gate.finished", name="test-zero", status="fail", exit_code=1))
    trace(event("gate.finished", name="test-zero", status="pass", exit_code=0))  # a zeroed run that passes: notable
    trace(event("gate.finished", name="test", status="fail", exit_code=1))
    assert console.getvalue().splitlines() == [
        "[l4] openspec:demo gate test-presatisfied fail (expected: zero values must fail) (exit 1)",
        "[l4] openspec:demo gate test-zero fail (expected: zero values must fail) (exit 1)",
        "[l4] openspec:demo gate test-zero pass (exit 0)",
        "[l4] openspec:demo gate test fail (exit 1)",
    ]


def test_the_ci_step_and_an_unfrozen_task_have_their_own_lines(console):
    trace = ProgressTrace()
    trace(event("ci.step", job="test", status="derived", command="make test", step="make test", reason=None))
    trace(event("ci.step", job="lint", status="skipped", command=None, step="make x", reason="docker is out"))
    trace(event("task.unfrozen", task="1.1", paths=["tests/test_notices.py"], question="Q-002"))
    out = console.getvalue()
    assert "CI job test: failing step derived `make test`" in out
    assert "CI job lint: failing step skipped (docker is out) `make x`" in out
    assert "task 1.1 unfrozen by Q-002: tests/test_notices.py" in out


def test_question_raised_prints_the_title_or_the_target(console):
    trace = ProgressTrace()
    trace(event("question.raised", id="Q-001", kind="ambiguous", title="Scenarios clash"))
    trace(event("question.raised", id="Q-002", kind="verdict", target="C-0a1b2c3d"))  # a ledger without a title
    trace(event("question.raised", id="Q-003", kind="ambiguous"))
    out = console.getvalue().splitlines()
    assert out[0].endswith("question Q-001 raised (ambiguous): Scenarios clash")
    assert out[1].endswith("question Q-002 raised (verdict): C-0a1b2c3d")
    assert out[2].endswith("question Q-003 raised (ambiguous)")  # never `: None`
    assert "None" not in console.getvalue()


def test_an_already_satisfied_task_prints_the_truth_and_no_green_line(console):
    trace = ProgressTrace()
    trace(event("task.red_ok", task="2.2", tests=["t::a"], tdd="already-satisfied"))
    trace(event("task.done", task="2.2", tdd="already-satisfied"))
    out = console.getvalue()
    assert "task 2.2 already satisfied: 1 new test passes on the base, no green step" in out
    assert "red ok" not in out and "green ok" not in out and "failing as expected" not in out


def test_a_red_green_task_still_prints_red_ok_and_green_ok(console):
    trace = ProgressTrace()
    trace(event("task.red_ok", task="1.1", tests=["t::a", "t::b"]))
    trace(event("task.done", task="1.1", tdd="green"))
    out = console.getvalue()
    assert "task 1.1 red ok: 2 new test(s) failing as expected" in out
    assert "task 1.1 green ok: all tests passing" in out
