"""`run_unit` reconciles first (M14, state-vcs-locks 1.23): before any agent call, and the result is in the ledger."""

from l4 import orchestrator
from l4.agents.fake import FakeAdapter

from ..implementer.conftest import green_step, red_step
from .conftest import new_origin_main

TASKS = "## 1. Pricing\n\n- [ ] 1.1 Add `apply_discount`\n"


def test_reconcile_runs_before_the_first_agent_call(run_l4, tdd_repo, raw, monkeypatch):
    order: list[str] = []
    real_reconcile, real_run = orchestrator.reconcile, FakeAdapter.run

    def reconcile_spy(git, ref, ledger):
        order.append("reconcile")
        return real_reconcile(git, ref, ledger)

    def run_spy(self, req):
        order.append("agent")
        return real_run(self, req)

    monkeypatch.setattr(orchestrator, "reconcile", reconcile_spy)
    monkeypatch.setattr(FakeAdapter, "run", run_spy)
    new_origin_main(tdd_repo, raw, {"openspec/changes/add-discount-codes/tasks.md": TASKS})
    assert run_l4([red_step(), green_step()]).code == 0
    assert order == ["reconcile", "agent", "agent"]  # once, before the red step


def test_a_step_a_dead_run_left_behind_is_reconciled_and_recorded(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {"openspec/changes/add-discount-codes/tasks.md": TASKS})
    crashed = run_l4([red_step()])  # the script ends in green: an AdapterError, exit 1, a snapshot of the green step
    assert crashed.code == 1
    resumed = run_l4([green_step()])
    assert resumed.code == 0
    [event] = resumed.events("step.reconciled")
    assert event["action"] == "rerun" and event["step"] == "1.1/green/1"  # the ledger commit moved the head on
    assert [e["task"] for e in resumed.events("task.done")] == ["1.1"]
    greens = [s for s in resumed.subjects() if s.startswith("feat(")]
    assert len(greens) == 1  # exactly one green commit for the task


def test_nothing_is_recorded_when_no_run_died(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {"openspec/changes/add-discount-codes/tasks.md": TASKS})
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.events("step.reconciled") == []
