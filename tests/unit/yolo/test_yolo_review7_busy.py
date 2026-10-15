"""Review 7, LOW-1: a unit skipped as busy (another run holds its lease) does not chain a run after every run."""

from dataclasses import replace

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult, UnitOutcome

from .test_yolo_cycle_run import run, world  # noqa: F401 - the fixtures
from .yolo_cycle_world import StubProvider, unit_id

A = unit_id("a")


def test_a_busy_unit_of_the_plan_chains_no_run(world, run, monkeypatch):  # noqa: F811
    calls = []

    def runner(app, cfg, git, chosen, *, adapters):
        calls.append([ref.id for _, ref in chosen])
        out = UnitOutcome(
            unit=A, phase_before="none", phase_after="none", exit_reason="skipped: the unit is locked by another run"
        )
        return CommandResult(ExitCode.OK, [out], busy=[A])

    monkeypatch.setattr(orch, "run_units", runner)
    world.plan(deps={}, limits={"max_runs": 6})
    world.activate()
    for i in range(3):
        world.app = replace(world.app, run_id=f"r-20261015T1600Z-{i:04d}")
        run()
        assert len(calls) == i + 1 and run.forge.started == []  # the other run's end or the cron is the next trigger


def test_run_units_carries_the_busy_units(world, monkeypatch):  # noqa: F811
    snap = world.snapshot("a", None)
    monkeypatch.setattr(orch, "run_unit_in_worktree", lambda *a, **k: orch._busy(None, snap.ref))
    monkeypatch.setattr(orch, "_phase_of", lambda *a: "none")
    result = orch.run_units(world.app, world.cfg, world.git, [(StubProvider(), snap.ref)], adapters=None)
    assert result.busy == [A] and result.not_started == {} and result.began == []
