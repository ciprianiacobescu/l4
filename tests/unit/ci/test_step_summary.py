"""L4-OBS-005: the GitHub job summary observer (SCN-OBS-05, SCN-OBS-06)."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.ci.step_summary import StepSummary, step_summary_for
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 1, 1, tzinfo=UTC)
UNIT = "openspec:add-x"


def ev(kind: str, minutes: float = 0, unit: str = UNIT, **data: object) -> LedgerEvent:
    return LedgerEvent(T0 + timedelta(minutes=minutes), "run-1", unit, 1, kind, data)


def feed(summary: StepSummary, *events: LedgerEvent) -> None:
    for e in events:
        summary(e)


def test_job_summary_lists_the_tasks_that_ended(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    path.write_text("# existing\n")
    s = StepSummary(path)
    feed(
        s,
        ev("task.started", 0, task="2.1"),
        ev("step.started", 1, task="2.1", phase="green", attempt=1, agent="kiro"),
        ev("step.started", 5, task="2.1", phase="green", attempt=2, agent="deepseek"),
        ev("task.done", 11, task="2.1", notes="a sentence of the agent"),
        ev("task.started", 12, task="2.2"),
        ev("task.red_ok", 13, task="2.2", tdd="already-satisfied", tests=["t"]),
        ev("task.done", 13, task="2.2", tdd="already-satisfied", notes=""),
        ev("task.started", 14, task="2.3"),
        ev("breaker.tripped", 15, task="2.3", reason="max_task_attempts", detail="free text"),
        ev("task.started", 16, task="1.1", fix_unit="add-x-fix-1"),
        ev("step.started", 16, task="1.1", phase="green", attempt=1, agent="deepseek", fix_unit="add-x-fix-1"),
        ev("task.done", 18, task="1.1", fix_unit="add-x-fix-1"),
        ev("task.started", 19, task="2.4"),
        ev("task.done", 19, task="2.4", tdd="already-done", reason="why"),
    )
    lines = path.read_text().splitlines()
    assert lines[0] == "# existing"
    assert lines[1:] == [
        "- openspec:add-x task 2.1: done (2 attempts, deepseek, 11m)",
        "- openspec:add-x task 2.2: already satisfied (no green step)",
        "- openspec:add-x task 2.3: halted (max_task_attempts)",
        "- openspec:add-x [add-x-fix-1] task 1.1: done (1 attempts, deepseek, 2m)",
        "- openspec:add-x task 2.4: done (closed with no open required task)",
    ]


def test_no_agent_text_in_the_line(tmp_path: Path) -> None:
    path = tmp_path / "s.md"
    feed(StepSummary(path), ev("task.started", task="1"), ev("task.done", 1, task="1", notes="secret sentence"))
    assert "secret" not in path.read_text()


def test_other_events_write_nothing(tmp_path: Path) -> None:
    path = tmp_path / "s.md"
    feed(StepSummary(path), ev("run.started"), ev("gate.finished", task="1"))
    assert not path.exists()


def test_environment_gate(tmp_path: Path) -> None:
    f = str(tmp_path / "s.md")
    assert step_summary_for({}) is None
    assert step_summary_for({"GITLAB_CI": "true", "GITHUB_STEP_SUMMARY": f}) is None
    assert step_summary_for({"GITHUB_ACTIONS": "false", "GITHUB_STEP_SUMMARY": f}) is None
    assert step_summary_for({"GITHUB_ACTIONS": "true"}) is None
    assert step_summary_for({"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": ""}) is None
    assert isinstance(step_summary_for({"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": f}), StepSummary)


def test_failed_write_warns_once_and_does_not_raise(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    s = StepSummary(tmp_path / "missing-dir" / "s.md")
    with caplog.at_level(logging.WARNING):
        feed(s, ev("task.done", task="1"), ev("task.done", 1, task="2"))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
