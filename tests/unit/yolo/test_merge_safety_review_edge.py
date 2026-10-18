"""A review edge comes before the merge (L4-YOLO-041; SCN-YOLO-110, SCN-YOLO-111): an in-review unit whose planner
action is `verify` (red CI recorded on H) is dispatched, never merged."""

from l4.planner import facts_of, next_action
from l4.state.fold import CiFailure
from l4.yolo.merge import merge_guarded

from .yolo_cycle_world import CycleWorld, ev, unit_id

A = unit_id("a")


def _world(tmp_path, *, pr=True):
    world = CycleWorld(tmp_path)
    world.plan(merge="auto")
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    if pr:
        world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    red = CiFailure(head=head, jobs=[{"name": "unit-tests"}], preexisting=[], pipeline=7)
    return world, head, world.in_review("a", head, ci_failure=red)


def test_red_ci_recorded_on_h_is_verified_not_merged(tmp_path):
    """SCN-YOLO-110"""
    world, head, snap = _world(tmp_path)
    assert next_action(facts_of(snap))[0] == "verify"
    step = world.step({"a": snap})
    assert "unit.merge_requested" not in world.kinds() and "unit.merged" not in world.kinds()
    assert not world.landed(head)
    assert step.allow == frozenset({A})
    assert any("dispatched openspec:a (in_review)" in action for action in step.actions)


def test_without_a_pr_the_unit_is_dispatched_for_verification(tmp_path):
    """The control of the reproduction."""
    world, head, snap = _world(tmp_path, pr=False)
    step = world.step({"a": snap})
    assert "unit.merged" not in world.kinds() and step.allow == frozenset({A})


def test_the_guarded_merge_refuses_recorded_red_ci_on_h(tmp_path):
    """SCN-YOLO-111"""
    world, head, snap = _world(tmp_path)
    out = merge_guarded(
        world.app, world.cfg, world.git, world.forge, snap, before_push=lambda _: True, sleep=lambda s: None
    )
    assert out.status == "not_ready"
    for part in ("the repository CI failed on the hand-off commit", "unit-tests", "(recorded)"):
        assert part in out.detail
    assert not world.landed(head)
