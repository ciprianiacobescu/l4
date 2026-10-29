"""L4-IMP-088: a task's baseline reuses the green gate run of the same tree within a job (SCN-IMP-432 to 437)."""

import contextlib
import re

import pytest

from l4.agents.fake import Step
from l4.implementer.tdd import BaselineFailed, baseline, run_green, run_red
from l4.implementer.workbench import Workbench
from l4.specs.base import Task

from .conftest import IMPL, KNOWN, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
NEXT = Task("1.2", "1.2", "1.2 Add `tip`", False, " ", 0, 3, 3)
STAMPED = IMPL + '\n\nwith open(__file__ + ".stamp", "w") as _stamp:\n    _stamp.write("written by the gate\\n")\n'
TIP_TEST = (
    f'import pytest\n\nfrom pytdd.pricing import total\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_total_of_nothing():\n'
    "    assert total([]) == 1\n"
)


def names(bench) -> list[str]:
    return [e["name"] for e in bench.events("gate.finished")]


def green_done(make_bench, *, green: Step | None = None, more: list[Step] | None = None, **gates):
    """Task 1.1 through red and green in one job; the bench is ready for the baseline of the next task."""
    bench = make_bench([red_step(), green or green_step(), *(more or [])], **gates)
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    done = run_green(bench.wb, TASK, red, attempt=1)
    assert done.status == "ok", done.reason
    return bench, done


def commit_note(wb, rel: str, text: str = "a line\n") -> str:
    """A commit of one file outside the code, as `_close_parents` or a ledger checkpoint makes them."""
    (wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
    with (wb.worktree / rel).open("a", encoding="utf-8") as handle:
        handle.write(text)
    return wb.commit("chore: note [skip ci]", task="1.1", attempt=1, phase="green", tdd=None, paths=[rel])


def test_the_next_task_reuses_the_green_run_of_the_task_before(make_bench):
    """SCN-IMP-432"""
    bench, done = green_done(make_bench)
    wb = bench.wb
    ran = names(bench)
    assert ran.count("baseline") == 1
    base = wb.head()
    assert base not in wb.baselines  # the cache is keyed by commit: the green commit was never measured

    report = baseline(wb, base, task="1.2")

    assert names(bench) == ran  # nothing ran: neither the gate nor setup
    [event] = bench.events("gate.reused")
    assert (event["name"], event["from"], event["task"], event["source_sha"]) == ("baseline", "test", "1.2", done.sha)
    assert re.fullmatch(r"[0-9a-f]{40}", event["tree"])
    assert wb.baselines[base] is report  # the verifier reads wb.baselines[base_sha]
    assert report.ids_with("failed") == set() and len(report.tests) >= 2
    assert baseline(wb, base, task="1.2") is report and len(bench.events("gate.reused")) == 1


def test_the_second_task_of_a_job_goes_red_on_the_reused_baseline(make_bench):
    other = Step(
        writes={"tests/test_total.py": TIP_TEST},
        structured=result("red", task_ids=["1.2"], criteria_ids=[KNOWN]),
    )
    bench, done = green_done(make_bench, more=[other])
    outcome = run_red(bench.wb, NEXT, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert names(bench).count("baseline") == 1  # the job measured once: task 1.1's, before its red step
    [event] = bench.events("gate.reused")
    assert event["task"] == "1.2"
    assert event["source_sha"] == done.sha and outcome.base_report is bench.wb.baselines[done.sha]


def test_the_first_baseline_of_a_job_is_measured(make_bench):
    bench = make_bench([red_step()])
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    assert names(bench).count("baseline") == 1 and bench.events("gate.reused") == []


def test_a_tasks_md_only_commit_between_the_tasks_still_reuses(make_bench):
    """SCN-IMP-433"""
    bench, _ = green_done(make_bench)
    wb = bench.wb
    commit_note(wb, f"{wb.unit_rel}/tasks.md", "- [ ] 1.2 Next\n")
    commit_note(wb, f"{wb.unit_rel}/.l4/held/1.1-at_red.json", "{}\n")
    baseline(wb, wb.head(), task="1.2")
    assert names(bench).count("baseline") == 1
    assert len(bench.events("gate.reused")) == 1


def test_a_commit_of_anything_else_between_the_tasks_is_measured(make_bench):
    bench, _ = green_done(make_bench)
    wb = bench.wb
    commit_note(wb, f"{wb.unit_rel}/proposal.md")
    baseline(wb, wb.head(), task="1.2")
    assert names(bench).count("baseline") == 2 and bench.events("gate.reused") == []


def test_a_green_gate_that_wrote_a_tracked_file_is_not_reused(make_bench):
    """SCN-IMP-434: the gate wrote the file after the tree was taken, so the commit holds what no test ran against."""
    bench, done = green_done(
        make_bench, green=Step(writes={"src/pytdd/pricing.py": STAMPED}, structured=result("green"))
    )
    wb = bench.wb
    assert "src/pytdd/pricing.py.stamp" in wb.git.run("show", "--name-only", "--format=", done.sha).stdout.split()
    baseline(wb, wb.head(), task="1.2")
    assert names(bench).count("baseline") == 2 and bench.events("gate.reused") == []


def test_a_fix_units_green_gate_is_not_reused(make_bench, monkeypatch):
    """SCN-IMP-435"""
    monkeypatch.setattr("l4.implementer.tdd.fix_gate_env", lambda wb: {"L4_TEST_FIX_COVERAGE": "1"})
    bench, _ = green_done(make_bench)
    baseline(bench.wb, bench.wb.head(), task="1.2")
    assert names(bench).count("baseline") == 2 and bench.events("gate.reused") == []


@pytest.mark.parametrize("event", ["guard.violation", "env.rebuilt"])
def test_a_guard_restore_or_an_environment_rebuild_during_the_gate_is_not_reused(make_bench, event):
    """SCN-IMP-436"""
    bench = make_bench([red_step(), green_step()])
    wb = bench.wb
    red = run_red(wb, TASK, attempt=1)
    real = wb.run_gate

    def gate(name, *args, **kwargs):
        done = real(name, *args, **kwargs)
        if name == "test":
            wb.emit(event, path="x", rule="environment", action="removed", phase="gate")
        return done

    wb.run_gate = gate  # type: ignore[method-assign]
    assert run_green(wb, TASK, red, attempt=1).status == "ok"
    baseline(wb, wb.head(), task="1.2")
    assert names(bench).count("baseline") == 2 and bench.events("gate.reused") == []


def test_an_event_before_the_gate_does_not_stop_the_reuse(make_bench):
    bench = make_bench([red_step(), green_step()])
    wb = bench.wb
    red = run_red(wb, TASK, attempt=1)
    wb.emit("guard.violation", path="x", rule="environment", action="removed", phase="green")  # before the gate
    assert run_green(wb, TASK, red, attempt=1).status == "ok"
    baseline(wb, wb.head(), task="1.2")
    assert len(bench.events("gate.reused")) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda g: setattr(g.test, "command", g.test.command + " -q"),
        lambda g: setattr(g.test, "reports", [".l4-out/other.xml"]),
        lambda g: setattr(g.test, "format", "tap"),
        lambda g: setattr(g, "timeout", "29m"),
        lambda g: setattr(g, "test_timeout", "7m"),
        lambda g: setattr(g, "network", "none"),
    ],
)
def test_a_changed_gate_configuration_is_not_reused(make_bench, change):
    """SCN-IMP-436"""
    bench, _ = green_done(make_bench)
    wb = bench.wb
    change(wb.cfg.gates)
    with contextlib.suppress(BaselineFailed):  # a report path or format nothing wrote: measuring it is the claim
        baseline(wb, wb.head(), task="1.2")
    assert names(bench).count("baseline") == 2 and bench.events("gate.reused") == []


def test_a_changed_sandbox_mode_is_not_reused(make_bench):
    bench, _ = green_done(make_bench)
    wb = bench.wb
    wb.cfg.sandbox.mode = "user"
    baseline(wb, wb.head(), task="1.2")
    assert bench.events("gate.reused") == []


def test_an_agent_step_after_the_green_ends_the_reuse(make_bench):
    """SCN-IMP-437"""
    stuck = Step(structured=result("red", task_ids=["1.2"]))  # an attempt that adds no test and is discarded
    bench, _ = green_done(make_bench, more=[stuck])
    wb = bench.wb
    assert run_red(wb, NEXT, attempt=1).status == "failed"
    assert len(bench.events("gate.reused")) == 1  # the attempt itself reused the green run before its agent step
    commit_note(wb, f"{wb.unit_rel}/tasks.md", "- [ ] 1.3 Later\n")  # a tasks.md-only commit: reusable but for the step
    baseline(wb, wb.head(), task="1.3")
    assert names(bench).count("baseline") == 2 and len(bench.events("gate.reused")) == 1


def test_a_discard_after_the_green_ends_the_reuse(make_bench):
    """SCN-IMP-437: a failed green is discarded; whatever the next baseline sees is measured."""
    bench, _ = green_done(make_bench)
    wb = bench.wb
    wb.discard_changes()
    commit_note(wb, f"{wb.unit_rel}/tasks.md")
    baseline(wb, wb.head(), task="1.2")
    assert names(bench).count("baseline") == 2 and bench.events("gate.reused") == []


def test_a_new_workbench_starts_with_nothing_kept():
    assert Workbench.__dataclass_fields__["last_tested"].default is None  # the orchestrator carries only the baselines


def test_a_failed_green_keeps_nothing(make_bench):
    bench = make_bench([red_step(), Step(structured=result("green"))])
    red = run_red(bench.wb, TASK, attempt=1)
    assert run_green(bench.wb, TASK, red, attempt=1).status == "failed"
    assert bench.wb.last_tested is None
