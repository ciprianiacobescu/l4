"""`l4 plan` with delivery plans (L4-YOLO-010, L4-YOLO-015, SCN-YOLO-30): a held unit shows why and is not actionable,
a waiting unit of the active plan shows what it waits for, a unit outside the active plan says so. Read-only: the plan
state is the local `refs/l4/plans/*`."""

import json

import pytest

import l4.planner as planner
from l4.exitcodes import ExitCode

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


@pytest.fixture
def plan(world, monkeypatch, capsys):
    snapshots = {}
    monkeypatch.setattr(planner, "load_app_config", lambda app: (app, world.cfg))
    monkeypatch.setattr(planner, "snapshots", lambda app, cfg, units: [s for _, s in world.found(snapshots)])

    def go():
        result = planner.run_plan(world.app, units=(), as_json=True, probe=False, sweep=False, detailed_exitcode=True)
        rows = {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}
        return result, rows

    go.snapshots = snapshots
    return go


def test_no_plan_file_leaves_the_plan_as_it_was(plan):
    result, rows = plan()
    assert rows[A]["reason"] == "pending tasks" and rows[A]["actionable"] is True
    assert result.code == ExitCode.CONTINUE


def test_scn_yolo_30_held_units_show_the_plan_and_its_status(world, plan):
    world.plan()
    world.reviewed()
    result, rows = plan()
    assert rows[A]["reason"] == rows[B]["reason"] == "held by plan p1 (reviewed)"
    assert not rows[A]["actionable"] and not rows[B]["actionable"] and rows[A]["next_action"] == "none"
    assert result.code == ExitCode.OK and result.actionable == ()  # nothing to run


def test_a_unit_that_waits_for_another_shows_what_it_waits_for(world, plan):
    world.plan()
    world.activate()
    result, rows = plan()
    assert rows[A]["actionable"] is True and rows[A]["reason"] == "pending tasks"  # the eligible unit
    assert rows[B]["reason"] == "waits for openspec:a (not integrated)" and rows[B]["actionable"] is False
    assert result.actionable == (A,)


def test_a_unit_outside_the_active_plan_is_not_actionable(world, plan):
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    world.activate(order=[A])
    _, rows = plan()
    assert rows[B]["reason"] == "not in the active plan p1" and rows[B]["actionable"] is False


def test_a_stopped_plan_holds_its_units_and_frees_the_others(world, plan):
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    world.activate(order=[A])
    world.seed(ev("plan.stopped", reason="unit_halted", unit=A))
    _, rows = plan()
    assert rows[A]["reason"] == "held by plan p1 (stopped)" and rows[B]["actionable"] is True


def test_the_plan_reads_the_local_refs_and_writes_nothing(world, plan):
    world.plan()
    world.activate()
    before = world.git.run("for-each-ref").stdout
    plan()
    assert world.git.run("for-each-ref").stdout == before
