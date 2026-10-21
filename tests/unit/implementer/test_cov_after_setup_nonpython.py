"""The run's COV-001 check after `gates.setup` skips a project whose test gate is not Python (SCN-VER-59)."""

from types import SimpleNamespace

from l4.config.schema import L4Config
from l4.implementer.tdd import check_coverage_after_setup


def _wb(command: str, tmp_path):
    cfg = L4Config.model_validate({"gates": {"setup": ["npm ci"], "test": {"command": command}}})
    events: list[dict] = []
    wb = SimpleNamespace(
        coverage_checked=False, cfg=cfg, host_env={"PATH": "/usr/bin"}, worktree=tmp_path, ref=SimpleNamespace(id="u"),
        emit=lambda kind, **data: events.append({"kind": kind, **data}),
        run_gate=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no gate must run")),
    )  # fmt: skip
    return wb, events


def test_a_node_project_records_a_skip_that_does_not_promise_an_interpreter(tmp_path):
    wb, events = _wb("npm test", tmp_path)
    check_coverage_after_setup(wb)
    [event] = events
    assert event["id"] == "COV-001" and event["status"] == "skip"
    assert event["message"] == "no python test gate: diff coverage does not apply"


def test_a_project_interpreter_keeps_the_check_whatever_runs_the_tests(tmp_path):
    """`make test` names no Python, but a `.venv` the setup created is still checked for coverage.py."""
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    wb, events = _wb("make test", tmp_path)
    wb.run_gate = lambda name, command: SimpleNamespace(status="pass")
    check_coverage_after_setup(wb)
    [event] = events
    assert event["status"] == "pass" and event["message"] == "coverage.py imports in .venv/bin/python"
