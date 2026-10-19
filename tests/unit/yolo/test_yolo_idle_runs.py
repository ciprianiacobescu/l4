# ruff: noqa: F401, F811  (the fixtures are imported by name)
"""Idle runs (delegate-answers 11.1; L4-YOLO-014, L4-YOLO-012; SCN-DLG-48, SCN-DLG-50, SCN-DLG-51, SCN-DLG-52,
SCN-DLG-53): a run that did nothing for its unit is recorded `plan.run_idle`, is not counted against `max_runs` and
chains no next run; a run that worked, a run that never started the unit and a capacity park stay charged."""

import json
from datetime import UTC, datetime

import pytest

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult
from l4.state.ledger import LedgerEvent
from l4.yolo.model import PlanEvent
from l4.yolo.state import fold_plan

from .test_yolo_cycle_run import run, world
from .yolo_cycle_world import ev, unit_id

A = unit_id("a")
RUN = "r-20261014T1000Z-0001"


def led(kind, run_id=RUN, **data):
    return LedgerEvent(datetime(2026, 10, 14, tzinfo=UTC), run_id, A, 1, kind, data)


def dispatch_with(monkeypatch, **result):
    monkeypatch.setattr(orch, "run_units", lambda *a, **k: CommandResult(ExitCode.AWAITING_HUMAN, [], **result))


# --- the plan step: record, charge, chain -----------------------------------------------------------------------------


def test_an_idle_run_is_recorded_and_not_counted(world, run, monkeypatch):  # SCN-DLG-48, SCN-DLG-50
    world.plan()
    world.activate()
    dispatch_with(monkeypatch, idle=[A])
    run()
    idle = [e for e in world.events() if e.type == "plan.run_idle"]
    assert len(idle) == 1 and idle[0].data == {"unit": A, "attempt": 1, "run": world.app.run_id}
    assert run.forge.started == []  # an idle run chains nothing
    used = fold_plan("p1", world.events()).used
    assert (used.runs, used.idle_runs) == (0, 1)  # charged at the dispatch, subtracted by the record


def test_a_run_that_worked_is_charged(world, run, monkeypatch):  # SCN-DLG-51
    world.plan()
    world.activate()
    dispatch_with(monkeypatch, idle=[])
    run()
    assert "plan.run_idle" not in world.kinds()
    assert run.forge.started == ["main"]
    assert fold_plan("p1", world.events()).used.runs == 1


def test_not_started_and_capacity_parks_stay_charged(world, run, monkeypatch):  # SCN-DLG-52
    world.plan()
    world.activate()
    dispatch_with(monkeypatch, not_started={A: (2, "cannot prepare the worktree")}, idle=[])
    run()
    assert "plan.run_idle" not in world.kinds() and fold_plan("p1", world.events()).used.runs == 1
    # a capacity park changes the phase into waiting_capacity: that is work, not a wait (the ledger rule)
    parked = [led("run.started"), led("phase.changed", to="waiting_capacity", **{"from": "implementing"})]
    assert orch.is_idle_run(parked, RUN) is False


def test_a_waiting_step_charges_nothing(world, run):  # SCN-DLG-53
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.waiting", reason="unit_awaiting_human", unit=A))
    run.snapshots["a"] = world.snapshot("a", "awaiting_human")
    before = fold_plan("p1", world.events()).used.runs
    run()
    after = fold_plan("p1", world.events())
    assert after.used.runs == before and "plan.run_idle" not in world.kinds()
    assert run.forge.started == [] and run.runner.chosen == []


def test_a_named_run_is_never_recorded_idle(world, run, monkeypatch):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    dispatch_with(monkeypatch, idle=[A])
    run(units=(A,))  # the plan did not dispatch this run: nothing to subtract
    assert "plan.run_idle" not in world.kinds()


# --- the rule on a run's ledger ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("events", "idle"),
    [
        ([led("run.started")], True),
        ([led("run.started"), led("phase.changed", to="awaiting_human", **{"from": "awaiting_human"})], True),
        ([led("run.started"), led("phase.changed", to="clarifying", **{"from": "implementing"})], True),
        ([led("run.started"), led("agent.finished", task="1.1", phase="implementer")], False),
        ([led("run.started"), led("gate.finished", name="lint", status="pass")], False),
        ([led("run.started"), led("phase.changed", to="implementing", **{"from": "awaiting_human"})], False),
        ([led("run.started"), led("delegate.asked", question="Q-001")], False),
        ([led("run.started"), led("budget.cost", usd=1.75, role="clarifier")], False),  # review F8: a paid call is work
        ([led("run.started"), led("budget.cost", usd=0.4, role="s1")], False),
        ([led("agent.finished", run_id="r-earlier-0000")], True),  # another run's events are not this run's
    ],
)
def test_the_rule_on_a_ledger(events, idle):
    assert orch.is_idle_run(events, RUN) is idle


# --- the fold ---------------------------------------------------------------------------------------------------------


def idle_event(unit, attempt, run_id):
    return PlanEvent("plan.run_idle", "2026-10-14T10:00:00Z", {"unit": unit, "attempt": attempt, "run": run_id})


def charged(unit, attempt, runs):
    return PlanEvent(
        "plan.charged", "2026-10-14T10:00:00Z", {"unit": unit, "attempt": attempt, "cost_usd": 0, "runs": runs}
    )


def test_the_fold_subtracts_per_attempt_never_below_zero():
    state = fold_plan(
        "p1",
        [
            charged(A, 1, 12), *(idle_event(A, 1, f"r{i}") for i in range(9)),
            charged(A, 2, 2), *(idle_event(A, 2, f"s{i}") for i in range(5)),  # more idle than charged: zero, not -3
        ],
    )  # fmt: skip
    assert state.used.runs == 3 and state.used.idle_runs == 9 + 2


def test_one_record_per_run():
    state = fold_plan("p1", [charged(A, 1, 3), idle_event(A, 1, "r1"), idle_event(A, 1, "r1")])
    assert (state.used.runs, state.used.idle_runs) == (2, 1)


def test_an_idle_record_before_its_charge_still_counts_once_charged():
    state = fold_plan("p1", [idle_event(A, 1, "r1"), charged(A, 1, 1)])
    assert state.used.runs == 0


def test_a_repeated_record_of_the_hook_is_written_once(world, run, monkeypatch):
    from l4.yolo.cycle import PlanStep, record_idle_runs

    world.plan()
    world.activate()
    dispatch_with(monkeypatch, idle=[A])
    run()
    step = PlanStep(allow=frozenset({A}), plan_id="p1", start_next_run=True)
    assert record_idle_runs(world.app, world.cfg, world.git, step, [A]) is True  # recorded already: no second line
    assert [e.type for e in world.events()].count("plan.run_idle") == 1


# --- the status -------------------------------------------------------------------------------------------------------


def test_the_status_shows_idle_runs():
    from l4.yolo.commands import _render

    data = {
        "plan_id": "p1", "status": "active", "target": "main", "merge": "human", "activated_by": None,
        "units": [], "batches": [],
        "next": "x",
        "usage": {
            "cost_usd": 0.0, "cost_limit": 10.0, "runs": 3, "idle_runs": 9, "runs_limit": 10, "attempts": {},
            "attempts_limit": 2, "deadline": None,
        },
    }  # fmt: skip
    text = _render(data)
    assert "runs 3 of 10 (9 idle, not counted);" in text
    data["usage"]["idle_runs"] = 0
    assert "runs 3 of 10;" in _render(data)


def test_run_units_lists_the_units_whose_run_was_idle(monkeypatch):
    from types import SimpleNamespace

    from l4.outcome import UnitOutcome

    def done(app, cfg, git, provider, ref, **kw):
        outcome = UnitOutcome(unit=ref.id, phase_before="awaiting_human", phase_after="awaiting_human")
        return orch.UnitRunResult(outcome, ExitCode.AWAITING_HUMAN, idle=True)

    monkeypatch.setattr(orch, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="x")))
    monkeypatch.setattr(orch, "run_unit_in_worktree", done)
    cfg = SimpleNamespace(
        forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget="auto", soft_deadline_margin="20m")
    )
    app = SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda t: t), environ={})
    out = orch.run_units(app, cfg, None, [(object(), SimpleNamespace(id=A))], adapters=None)
    assert list(out.idle) == [A]
