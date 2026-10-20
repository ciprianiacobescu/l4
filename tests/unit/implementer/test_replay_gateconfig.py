"""A replayed step meets the guards an agent step meets after the agent returns: the runner-configuration revert
(L4-IMP-040) too. A saved patch (saved by 0.4.17, which had no such revert) that adds `addopts` to the pytest section is
reverted with a `guard.violation` when it is replayed after an accept."""

from l4.implementer.loop import run_task

from .test_earlier_red import NEW, TASK
from .test_held_accept import forge_hold, held_new
from .test_held_answers import answer


def test_a_replayed_step_loses_a_runner_configuration_change_like_an_agent_step(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    wb = bench.wb
    py = (wb.worktree / "pyproject.toml").read_text()
    loosened = py.replace('pythonpath = ["src"]\n', 'pythonpath = ["src"]\naddopts = "-p no:warnings"\n')
    assert loosened != py
    forge_hold(bench, raw, {"tests/test_new.py": NEW, "pyproject.toml": loosened})
    answer(bench, raw, "accept: fine")
    outcome = run_task(wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.events("held.replayed")) == 1
    runner = [e for e in bench.events("guard.violation") if "configuration" in str(e.get("rule"))]
    committed = wb.git.run("show", "HEAD:pyproject.toml").stdout
    assert [e["path"] for e in runner] == ["pyproject.toml"]
    assert "addopts" not in committed
    assert "tests/test_new.py" in wb.git.run("show", "--name-only", "--format=", "HEAD").stdout
