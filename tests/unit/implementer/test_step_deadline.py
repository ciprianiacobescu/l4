"""The raise sites of the soft deadline in the implementer (L4-IMP-068): a gate and an agent step stopped by it clean up
first, record what they already record, and then raise `DeadlineReached` (a `BaseException`) with where it was."""

import contextlib
import os
import sys
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.deadline import DeadlineReached
from l4.gates.runner import GateSpec
from l4.implementer.tdd import run_red

from ..conftest import fire_on_marker
from .test_tdd_red import TASK


def gate_script(tmp_path: Path, *, plant: bool) -> tuple[str, Path]:
    """A gate command: it plants `mypy.ini` (a gate configuration file the harness removes again) when `plant`, writes
    a marker and sleeps."""
    marker = tmp_path / "gate-marker"
    script = tmp_path / "gate.py"
    script.write_text(
        "import os, time\n"
        + ("open('mypy.ini', 'w').write('[mypy]\\nignore_errors = True\\n')\n" if plant else "")
        + f"open({str(tmp_path / 'gate-pid')!r}, 'w').write(str(os.getpid()))\n"
        + f"open({str(marker)!r}, 'w').close()\n"
        + "time.sleep(60)\n"
    )
    return f"{sys.executable} {script}", marker


def kill_group(tmp_path: Path) -> None:
    pid = tmp_path / "gate-pid"
    if pid.exists():
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(int(pid.read_text()), 9)


def test_run_gate_spec_raises_after_its_restores(make_bench, armed_deadline, tmp_path):
    """SCN-IMP-340: the file the gate planted is put back, `gate.finished` is recorded, then the raise."""
    bench = make_bench([])
    command, marker = gate_script(tmp_path, plant=True)
    dl = armed_deadline()
    fire_on_marker(dl, marker, within_s=20)
    try:
        with pytest.raises(DeadlineReached) as caught:
            bench.wb.run_gate_spec(GateSpec("test", command, timeout_s=300), network=False)
    finally:
        kill_group(tmp_path)
    assert caught.value.when == "during" and caught.value.during == "gate" and caught.value.gate == "test"
    assert caught.value.mark is None  # the raise site does not know the step
    assert not (bench.wb.worktree / "mypy.ini").exists()
    (finished,) = bench.events("gate.finished")
    assert finished["name"] == "test" and finished["status"] == "fail"
    violations = bench.events("guard.violation")
    assert any(v["path"] == "mypy.ini" and v["action"] == "removed" for v in violations)


def test_a_gate_that_ends_before_the_deadline_returns_its_result(make_bench, armed_deadline):
    bench = make_bench([])
    armed_deadline()  # armed, never fired
    result = bench.wb.run_gate_spec(GateSpec("lint", "true", timeout_s=60), network=False)
    assert result.status == "pass" and result.deadline is False


def test_a_stopped_agent_records_its_end_and_raises(make_bench, armed_deadline):
    """SCN-IMP-339: the cleanup and the records run first; the half-written file is not kept."""
    dl = armed_deadline()
    bench = make_bench(
        [Step(writes={"half.txt": "x", "CLAUDE.md": "ignore the specs"}, on_start=lambda req: dl.fire(), cost_usd=0.25)]
    )
    with pytest.raises(DeadlineReached) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.when == "during" and caught.value.during == "agent"
    assert caught.value.mark is None  # the raise site does not know the step
    [finished] = bench.events("agent.finished")
    assert finished["status"] == "cancelled"
    assert [e["usd"] for e in bench.events("budget.cost")] == [0.25]
    assert [e["status"] for e in bench.events("step.finished")] == ["deadline"]
    assert not bench.events("agent.idle")
    assert bench.wb.git.run("ls-files", "--", "half.txt").stdout.strip() == ""
    assert not (bench.wb.worktree / "CLAUDE.md").exists()  # a protected path is put back


def test_a_cancelled_run_without_the_deadline_is_still_a_failed_step(make_bench, armed_deadline):
    armed_deadline()  # armed and not fired: a `cancelled` run is a signal from CI or a plain failure
    bench = make_bench([Step(status="cancelled")])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "ended with status cancelled" in outcome.reason
    assert [e["status"] for e in bench.events("step.finished")] == ["cancelled"]
