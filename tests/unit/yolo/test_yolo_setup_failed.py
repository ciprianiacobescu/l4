"""rv18-ops 3a: a unit whose started run ends with exit 3 (`gates.setup` failed, no usable sandbox) stops its plan with
`setup_failed` instead of being dispatched again every minute until `max_runs`."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from l4 import orchestrator
from l4.exitcodes import ExitCode
from l4.orchestrator import UnitRunResult
from l4.outcome import UnitOutcome
from l4.yolo.cycle import record_setup_failures
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A = unit_id("a")
WHY = "gates.setup failed (exit 1); see /w/.l4-out/gates/setup.log"


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path, units=("a",))


def state(world):
    return fold_plan("p1", world.events())


def step(world):
    world.app = replace(world.app, run_id=f"r-20261014T1000Z-{len(world.events()):04d}")
    return world.step({"a": world.snapshot("a", "implementing")})


def test_run_units_lists_a_started_unit_that_exited_3(monkeypatch):
    monkeypatch.setattr(
        orchestrator, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="implementing"))
    )

    def fake(app, cfg, git, provider, ref, *, waits=None, **kw):
        waits.started.add(ref.id)  # `run.started` was written, then the setup gate failed
        return UnitRunResult(
            UnitOutcome(unit=ref.id, phase_before="implementing", phase_after="implementing", exit_reason=WHY),
            ExitCode.DOCTOR_FAILED,
        )

    monkeypatch.setattr(orchestrator, "run_unit_in_worktree", fake)
    cfg = SimpleNamespace(
        forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget="auto", soft_deadline_margin="20m")
    )
    app = SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda t: t), environ={})
    unit = (object(), SimpleNamespace(id=A))
    out = orchestrator.run_units(app, cfg, None, [unit], adapters=None)
    assert dict(out.setup_failed) == {A: WHY} and out.began == [A] and not out.not_started


def test_a_plan_whose_unit_fails_its_setup_stops_instead_of_chaining_runs(world):
    world.plan(limits={"max_runs": 50})
    world.activate()
    chained = []
    for _ in range(6):
        s = step(world)
        chained.append(s.start_next_run)
        if s.start_next_run:
            record_setup_failures(world.app, world.cfg, world.git, s, {A: WHY})
    assert chained == [True, False, False, False, False, False]
    done = state(world)
    assert (done.status, done.stop_reason, done.stop_unit) == ("stopped", "setup_failed", A)
    assert "gates.setup failed" in done.stop_detail and "setup.log" in done.stop_detail and done.used.runs == 1


def test_a_persons_resume_dispatches_the_unit_again(world):
    world.plan(limits={"max_runs": 50})
    world.activate()
    record_setup_failures(world.app, world.cfg, world.git, step(world), {A: WHY})
    step(world)
    assert state(world).stop_reason == "setup_failed"
    world.seed(ev("plan.resumed", by="alice", reason="setup fixed"))
    s = step(world)
    assert s.allow == frozenset({A}) and s.start_next_run is True and state(world).status == "active"


def test_a_failure_is_recorded_only_for_the_unit_the_step_let_run_and_once(world):
    world.plan()
    world.activate()
    s = step(world)
    record_setup_failures(world.app, world.cfg, world.git, s, {unit_id("zzz"): "x"})
    assert "unit.setup_failed" not in world.kinds()
    record_setup_failures(world.app, world.cfg, world.git, s, {A: WHY})
    record_setup_failures(world.app, world.cfg, world.git, s, {A: WHY})
    assert world.kinds().count("unit.setup_failed") == 1
