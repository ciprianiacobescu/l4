"""Review round 5, area Z6: a unit whose run never started is not dispatched in a loop (live defect), a rejection
caused by the configuration is not a dead end (MEDIUM-1), a failed fetch holds only the units the plan files list
(MEDIUM-2), the fetch-failure line keeps git's cause (LOW-d)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from l4 import orchestrator
from l4.exitcodes import ExitCode
from l4.orchestrator import RunWaits, UnitRunResult
from l4.outcome import UnitOutcome
from l4.yolo.cycle import record_rejections
from l4.yolo.digest import plan_digest
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_ledger_world import sh

A, B, C = unit_id("a"), unit_id("b"), unit_id("c")
WORKTREE = "cannot prepare the worktree: the unit branch is not usable"


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path, units=("a", "b"))


def state(world):
    return fold_plan("p1", world.events())


def step(world, phase=None):
    world.app = replace(world.app, run_id=f"r-20261014T1000Z-{len(world.events()):04d}")  # every trigger: its own run
    return world.step({"a": world.snapshot("a", phase), "b": world.snapshot("b", None)})


def never_started(world, s, detail=WORKTREE, code=2):
    """What `run_command` does after a dispatched unit's run ended before the unit started."""
    from l4.yolo.cycle import record_run_starts

    return record_run_starts(world.app, world.cfg, world.git, s, {A: (code, detail)}, ())


def started(world, s):
    from l4.yolo.cycle import record_run_starts

    return record_run_starts(world.app, world.cfg, world.git, s, {}, (A,))


# --- the live defect: a unit that never starts is dispatched again and again ----------------------------------------


def test_a_unit_whose_run_never_started_is_not_chained_into_a_loop(world):
    world.plan(deps={}, limits={"max_runs": 50})
    world.activate()
    s1 = step(world)
    assert s1.start_next_run is True and s1.allow == frozenset({A})
    never_started(world, s1)
    chains = []
    for _ in range(4):  # every trigger runs the unit once; none of the runs starts it
        s = step(world)
        assert s.allow == frozenset({A})
        chains.append(s.start_next_run)
        never_started(world, s, "again")
    assert chains == [False] * 4
    waiting = [e for e in world.events() if e.type == "plan.waiting"]
    assert waiting and waiting[0].data["reason"] == "unit_not_started" and waiting[0].data["unit"] == A
    assert WORKTREE in waiting[0].data["detail"] and state(world).status == "waiting"
    assert state(world).used.runs == 5  # the waiting runs are charged: max_runs still bounds the plan


def test_the_wait_is_recorded_once_per_failed_run_and_the_record_carries_the_exit(world):
    world.plan(deps={})
    world.activate()
    never_started(world, step(world))
    step(world)
    step(world)  # no run in between: the wait is on record already
    assert [e.data["reason"] for e in world.events() if e.type == "plan.waiting"] == ["unit_not_started"]
    (record,) = [e for e in world.events() if e.type == "unit.not_started"]
    assert record.data["unit"] == A and record.data["exit"] == 2 and WORKTREE in record.data["detail"]


def test_a_run_that_starts_the_unit_clears_the_wait_and_the_plan_goes_on(world):
    world.plan(deps={})
    world.activate()
    never_started(world, step(world))
    s = step(world)
    assert s.start_next_run is False
    assert started(world, s) is True  # the caller chains the next run
    s = step(world, "implementing")
    assert s.start_next_run is False or s.allow == frozenset({A})  # the plan is woken, not stuck
    assert state(world).status == "active" and "unit.started" in world.kinds()


def test_a_run_that_started_a_unit_nothing_waited_for_records_nothing(world):
    world.plan(deps={})
    world.activate()
    s = step(world)
    assert started(world, s) is False and "unit.started" not in world.kinds()


def test_a_new_activation_clears_the_not_started_wait(world):
    text = world.plan(deps={})
    world.activate()
    never_started(world, step(world))
    assert step(world).start_next_run is False
    world.seed(ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="p",
                  reason="fixed", current=A))  # fmt: skip
    s = step(world)
    assert s.start_next_run is True and s.allow == frozenset({A})


def test_a_not_started_record_is_only_for_the_unit_the_step_let_run(world):
    world.plan(deps={})
    world.activate()
    s = step(world)
    from l4.yolo.cycle import record_run_starts

    record_run_starts(world.app, world.cfg, world.git, s, {B: (2, "x")}, ())
    assert "unit.not_started" not in world.kinds()
    never_started(world, s)
    never_started(world, s)  # the same run twice: recorded once
    assert world.kinds().count("unit.not_started") == 1


# --- run_units: which units never started ---------------------------------------------------------------------------


def _unit(name):
    return (object(), SimpleNamespace(id=f"openspec:{name}"))


def _cfg_app():
    cfg = SimpleNamespace(
        forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget="auto", soft_deadline_margin="20m")
    )
    app = SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda t: t), environ={})
    return app, cfg


def test_run_units_lists_the_units_that_ended_before_they_started(monkeypatch):
    monkeypatch.setattr(
        orchestrator, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="implementing"))
    )

    def fake(app, cfg, git, provider, ref, *, waits=None, **kw):
        if ref.id.endswith("a"):
            raise orchestrator.L4Exit(ExitCode.USAGE_ERROR, WORKTREE)  # before the ledger was opened
        waits.started.add(ref.id)  # what the run does once `run.started` is written
        return UnitRunResult(UnitOutcome(unit=ref.id, phase_before="ready", phase_after="in_review"), 0)

    monkeypatch.setattr(orchestrator, "run_unit_in_worktree", fake)
    app, cfg = _cfg_app()
    out = orchestrator.run_units(app, cfg, None, [_unit("a"), _unit("b")], adapters=None)
    assert list(out.not_started) == ["openspec:a"]
    code, detail = out.not_started["openspec:a"]
    assert code == 2 and WORKTREE in detail
    assert out.began == ["openspec:b"]


def test_run_waits_starts_empty():
    assert RunWaits().started == set()


# --- MEDIUM-1: a rejection caused by the configuration --------------------------------------------------------------


def test_after_a_configuration_fix_and_a_new_activation_the_rejected_unit_is_dispatched(world):
    text = world.plan(deps={})
    world.activate()
    record_rejections(
        world.app, world.cfg, world.git, step(world), {A: "rejected: gates.test.command is not configured"}
    )
    step(world)
    assert state(world).stop_reason == "unit_rejected"
    # the person sets the command (no spec change) and activates again
    world.seed(ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="p",
                  reason="config fixed", current=A))  # fmt: skip
    s = step(world)
    assert s.allow == frozenset({A}) and s.start_next_run is True and state(world).status == "active"
    # still broken: rejected again, and the plan stops again
    record_rejections(world.app, world.cfg, world.git, s, {A: "rejected: still no command"})
    step(world)
    assert state(world).stop_reason == "unit_rejected" and "still no command" in state(world).stop_detail


def test_the_texts_for_a_rejected_unit_name_the_configuration_too():
    from l4.yolo.commands import _next_line, resume_blocker  # noqa: F401
    from l4.yolo.state import PlanState

    st = PlanState(plan_id="p1", status="stopped", stop_reason="unit_rejected", stop_unit=A)
    line = _next_line("p1", st, None, None)
    assert "configuration" in line


# --- MEDIUM-2: a failed fetch holds the units the plan files list, not the others -----------------------------------


@pytest.fixture
def three(tmp_path):
    return CycleWorld(tmp_path, units=("a", "b", "c"))


def broken_origin(w):
    good = sh(w.repo, "remote", "get-url", "origin")
    sh(w.repo, "remote", "set-url", "origin", str(w.root / "no-such-origin.git"))
    return good


@pytest.mark.parametrize("status", ["new", "cancelled"])
def test_a_failed_fetch_lets_a_unit_in_no_plan_run(three, status):
    w = three
    w.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A, "depends_on": []}, {"id": B, "depends_on": []}]}])
    if status == "cancelled":
        w.activate()
        w.seed(ev("plan.cancelled", by="x", reason="done"))
    snaps = {n: w.snapshot(n, "implementing" if n == "c" else None) for n in "abc"}
    good = broken_origin(w)
    try:
        full = w.step(snaps)
        named = w.step(snaps, read_only=True)
    finally:
        sh(w.repo, "remote", "set-url", "origin", good)
    assert full.allow == frozenset({C}) and named.allow == frozenset({C})
    assert full.start_next_run is False


def test_a_failed_fetch_holds_every_unit_while_the_last_known_ledger_says_the_plan_is_active(three):
    w = three
    w.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A, "depends_on": []}, {"id": B, "depends_on": []}]}])
    w.activate()
    snaps = {n: w.snapshot(n, "implementing" if n == "c" else None) for n in "abc"}
    w.step(snaps)  # the ledger ref is fetched into the clone
    before = w.events()
    good = broken_origin(w)
    try:
        full = w.step(snaps)
    finally:
        sh(w.repo, "remote", "set-url", "origin", good)
    assert full.allow == frozenset() and w.events() == before


# --- LOW-d: the fetch-failure line keeps the cause ------------------------------------------------------------------


def test_the_fetch_failure_line_starts_with_the_cause_and_is_short(world):
    from l4.yolo.cycle import _fetch_failure

    world.plan()
    good = broken_origin(world)
    try:
        line = _fetch_failure(world.app, world.cfg, world.git)
    finally:
        sh(world.repo, "remote", "set-url", "origin", good)
    assert line is not None and line.startswith("the target main could not be fetched (")
    assert "no-such-origin" in line and "core.hooksPath" not in line
