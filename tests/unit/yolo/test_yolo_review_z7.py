"""Review round 6, area Z7: the wait of a unit with nothing to run is not the wait of a run that never started it."""

from dataclasses import replace

from l4.state.status import UnitSnapshot
from l4.yolo.state import fold_plan

from .test_yolo_review_z6 import never_started, step, world  # noqa: F401 - the fixture
from .yolo_cycle_world import unit_id

A = unit_id("a")


def no_tasks(world, name):  # noqa: F811
    snap = world.snapshot(name, None)
    return UnitSnapshot(ref=snap.ref, state=snap.state, source=snap.source, tasks=[])


def test_a_unit_with_nothing_to_run_waits_once_and_the_triggers_add_nothing(world):  # noqa: F811
    world.plan(deps={}, limits={"max_runs": 5})
    world.activate()
    after = []
    for i in range(6):
        world.app = replace(world.app, run_id=f"r-20261014T1000Z-{i:04d}")
        s = world.step({"a": no_tasks(world, "a"), "b": world.snapshot("b", None)})
        assert s.allow == (frozenset({A}) if i == 0 else frozenset()) and s.start_next_run is False
        after.append(len(world.events()))
    kinds = world.kinds()
    assert kinds.count("plan.waiting") == 1 and kinds.count("plan.resumed") == 0
    assert after[1:] == [after[0]] * 5  # silence after the first wait
    waiting = [e for e in world.events() if e.type == "plan.waiting"]
    assert waiting[0].data["reason"] == "unit_not_started"
    assert fold_plan("p1", world.events()).used.runs == 0


def test_a_run_that_never_started_the_unit_waits_with_its_own_reason(world):  # noqa: F811
    world.plan(deps={})
    world.activate()
    never_started(world, step(world))
    step(world)
    waiting = [e for e in world.events() if e.type == "plan.waiting"]
    assert [e.data["reason"] for e in waiting] == ["run_not_started"]
    assert fold_plan("p1", world.events()).wait_reason == "run_not_started"
