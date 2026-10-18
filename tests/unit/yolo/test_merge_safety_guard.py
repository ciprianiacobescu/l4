"""The guarded merge lands exactly the recorded hand-off commit H (L4-YOLO-040, L4-YOLO-008, L4-YOLO-032; SCN-YOLO-105,
SCN-YOLO-106, SCN-YOLO-108, SCN-YOLO-109)."""

from dataclasses import replace

from l4.config.schema import L4Config
from l4.state.review import AfterHandoff
from l4.yolo.merge import merge_guarded

from .test_yolo_merge_guard import BRANCH, FakeForge, World, pull  # noqa: F401  (the World fixture)
from .test_yolo_merge_guard import world as world  # noqa: F401
from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_ledger_world import sh


def merge(world: World, snapshot):
    return merge_guarded(world.app, world.cfg, world.git, FakeForge(pull()), snapshot, sleep=lambda _s: None)


def test_a_head_that_is_not_the_recorded_h_is_not_merged(world):
    """SCN-YOLO-108"""
    h = world.handoff
    world.raw(world.work, "checkout", "-q", BRANCH)
    x = world.commit(world.work, "later.txt", "a later commit")
    world.raw(world.work, "push", "-q", "origin", BRANCH)
    world.raw(world.work, "fetch", "-q", "origin")
    tip = world.target()
    snap = replace(world.snapshot(ready_head=h), review=AfterHandoff(handoff=x, head=x))
    out = merge(world, snap)
    assert out.status == "not_ready" and x[:10] in out.detail and h[:10] in out.detail
    assert world.target() == tip
    assert not any(a[:2] == ["push", "--"] for a in world.git.history)


def test_no_recorded_h_is_not_merged(world):
    """SCN-YOLO-109"""
    tip = world.target()
    out = merge(world, world.snapshot(ready_head=None))
    assert out.status == "not_ready" and "l4 retry --unit openspec:x" in out.detail
    assert world.target() == tip
    assert not any(a[:2] == ["push", "--"] for a in world.git.history)


def test_a_fast_forward_pushes_the_recorded_h(world):
    """SCN-YOLO-105"""
    out = merge(world, world.snapshot(ready_head=world.handoff))
    assert out.status == "merged" and out.head == out.landed == world.handoff
    assert world.target() == world.handoff


def test_the_squash_merge_is_pinned_to_the_recorded_h(tmp_path):
    """SCN-YOLO-106"""
    world = CycleWorld(tmp_path)
    world.plan(merge="auto")
    world.activate()
    a = unit_id("a")
    world.seed(ev("unit.dispatched", unit=a, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    assert L4Config.model_validate({"version": 1}).yolo.merge.method == "squash"
    world.step({"a": world.in_review("a", head)})
    merged = [e for e in world.events() if e.type == "unit.merged"]
    assert len(merged) == 1 and merged[0].data["head"] == head and merged[0].data["ci"] == "green"
    assert world.forge.get_pr(1).head_sha == head
    landed = merged[0].data["merge_commit"]
    assert sh(world.origin, "rev-parse", f"{landed}^{{tree}}") == sh(world.origin, "rev-parse", f"{head}^{{tree}}")
