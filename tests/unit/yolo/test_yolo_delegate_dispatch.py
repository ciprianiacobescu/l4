"""A waiting plan takes the planner action `delegate` (delegate-answers 9.3; L4-DLG-003, L4-YOLO-012; SCN-DLG-10): the
unit's question has something to ask, so the plan is no longer waiting for a person, wakes by itself, and dispatches
the unit; the run that takes the action does the pass and decides about the next run itself."""

from dataclasses import replace

import pytest

from l4.yolo.cycle import ACTIONABLE, still_waits

from .yolo_cycle_world import CycleWorld, ev, unit_id

A = unit_id("a")
DUE = (("Q-001", None),)


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def test_the_actionable_actions_include_the_delegate():
    from l4.orchestrator import ACTIONABLE as RUN_ACTIONABLE

    assert {"implement", "clarify", "verify", "hand_off", "delegate"} == set(ACTIONABLE) == set(RUN_ACTIONABLE)


def test_still_waits_is_false_while_the_action_is_due(world):
    snap = world.snapshot("a", "awaiting_human")
    assert still_waits(snap) is True
    assert still_waits(replace(snap, delegate_due=DUE)) is False
    assert still_waits(replace(snap, delegate_due=(("Q-001", "2999-01-01T00:00:00Z"),))) is True  # a deferral to come


def test_the_plan_dispatches_the_delegate_action(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.waiting", reason="unit_awaiting_human", unit=A))
    waiting = world.step({"a": world.snapshot("a", "awaiting_human")})
    assert waiting.allow == frozenset() and "plan.resumed" not in world.kinds()  # still waiting for a person
    kinds = len(world.kinds())
    step = world.step({"a": replace(world.snapshot("a", "awaiting_human"), delegate_due=DUE)})
    assert world.kinds()[kinds:][:1] == ["plan.resumed"]
    resumed = next(e for e in reversed(world.events()) if e.type == "plan.resumed")
    assert resumed.data["by"] == "harness"
    assert world.kinds()[-2:] == ["plan.charged", "unit.dispatched"]
    assert step.allow == frozenset({A})
    assert step.start_next_run is False  # the run that takes the action starts the next run when it answers
