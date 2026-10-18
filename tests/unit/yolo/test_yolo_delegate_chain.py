# ruff: noqa: F401, F811  (the fixtures are imported by name)
"""A delegate answer chains the next run in a plan (delegate-answers 10.1; L4-DLG-007, L4-YOLO-012; SCN-DLG-23,
SCN-DLG-25, SCN-DLG-49): the run that took the action `delegate` asks the forge for exactly one next run when it
answered, although the plan step waited; an escalation leaves the plan waiting with no run."""

from dataclasses import replace

import pytest

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult

from .test_yolo_cycle_run import run, world
from .yolo_cycle_world import ev, unit_id

A = unit_id("a")


@pytest.fixture
def waiting(world, run):
    """An active plan that waits on unit A, whose question the delegate has still to decide."""
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.waiting", reason="unit_awaiting_human", unit=A))
    run.snapshots["a"] = replace(world.snapshot("a", "awaiting_human"), delegate_due=(("Q-001", None),))
    return run


def test_an_answer_chains_once_while_the_plan_waited(world, waiting, monkeypatch):  # SCN-DLG-49
    monkeypatch.setattr(
        orch, "run_units", lambda *a, **k: CommandResult(ExitCode.AWAITING_HUMAN, [], delegate_answered=[A])
    )
    result = waiting()
    assert result.code == ExitCode.AWAITING_HUMAN
    assert waiting.forge.started == ["main"]  # exactly one request, although the plan step chained none
    assert world.kinds()[-2:] == ["plan.charged", "unit.dispatched"]


def test_the_next_step_resumes_and_dispatches(world, monkeypatch):  # SCN-DLG-23
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.waiting", reason="unit_awaiting_human", unit=A))
    monkeypatch.setattr("l4.planner.answers_unblock", lambda questions, tasks: ("Q-001",))  # the delegate's answer
    step = world.step({"a": world.snapshot("a", "awaiting_human")})
    resumed = next(e for e in reversed(world.events()) if e.type == "plan.resumed")
    assert resumed.data["by"] == "harness"
    assert step.allow == frozenset({A}) and step.start_next_run is True
    assert world.kinds()[-2:] == ["plan.charged", "unit.dispatched"]


def test_an_escalation_waits_without_a_run(world, waiting, monkeypatch):  # SCN-DLG-25
    monkeypatch.setattr(orch, "run_units", lambda *a, **k: CommandResult(ExitCode.AWAITING_HUMAN, []))
    waiting()  # the run took the action, the delegate escalated: nothing was answered
    assert waiting.forge.started == []
    waiting.snapshots["a"] = world.snapshot("a", "awaiting_human")  # the final record: no action is due any more
    kinds = len(world.kinds())
    waiting()
    assert "plan.waiting" in world.kinds()[kinds:] and waiting.forge.started == []
