"""The plan step squash-merges a verified unit (squash-and-delete D3, D4; L4-YOLO-032): SCN-YOLO-76 and 77 (the landed
commit is recorded, post-checked and receipted), SCN-YOLO-78 (fast-forward stays an option), SCN-YOLO-79 (a refusal
stops the plan), SCN-YOLO-80 (a moved head waits), SCN-YOLO-81 (a target that moved during the merge is recorded)."""

import json

import pytest

from l4.forge.base import MergeCall
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, MergingForge, ev, unit_id
from .yolo_review_world import make_cfg

A, B = unit_id("a"), unit_id("b")


class CountingForge(MergingForge):
    """The merging local forge; `answer` replaces the forge's merge call, `before` runs just before it."""

    def __init__(self, *, origin, answer: MergeCall | None = None, before=None) -> None:
        super().__init__(origin=origin)
        self.answer, self.before, self.squashes = answer, before, 0

    def merge_pr(self, number, *, sha, title, message):
        self.squashes += 1
        if self.before is not None:
            self.before()
        if self.answer is not None:
            return self.answer
        return super().merge_pr(number, sha=sha, title=title, message=message)


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def state(world):
    return fold_plan("p1", world.events())


def last(world, kind):
    return [e for e in world.events() if e.type == kind][-1].data


def ready(world, **forge):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge = CountingForge(origin=world.origin, **forge)
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a [skip ci]", "b", draft=False)
    return head, {"a": world.in_review("a", head)}


def test_scn_yolo_76_a_verified_unit_is_squash_merged_and_recorded_with_the_landed_commit(world):
    head, snaps = ready(world)
    tip = world.tip()
    world.step(snaps)
    landed = world.tip()
    assert landed != head and world.git.run("rev-parse", f"{landed}^").stdout.strip() == tip
    assert last(world, "unit.merged") == {
        "unit": A, "head": head, "pr": 1, "merge_commit": landed, "method": "squash", "raced": False, "ci": "green",
    }  # fmt: skip
    assert world.forge.squashes == 1 and state(world).merged[A] == landed


def test_scn_yolo_77_the_post_merge_check_and_the_receipt_name_the_landed_commit(world):
    head, snaps = ready(world)
    step = world.step(snaps)
    landed = world.tip()
    assert world.profile_calls == [(landed, "all")]
    assert last(world, "unit.postcheck")["revision"] == landed
    assert last(world, "unit.integrated") == {"unit": A, "revision": landed}
    receipt = json.loads(world.store().read().files["receipts/openspec-a.json"])
    assert (receipt["merge_commit"], receipt["reviewed_head"], receipt["integrated_revision"]) == (landed, head, landed)
    assert step.start_next_run is True and state(world).integrated[A] == landed


def test_scn_yolo_78_fast_forward_stays_an_option(world):
    head, snaps = ready(world)
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        yolo={"merge": {"method": "fast-forward"}},
    )
    world.step(snaps)
    assert world.tip() == head and world.forge.squashes == 0
    assert last(world, "unit.merged") == {
        "unit": A, "head": head, "pr": 1, "merge_commit": head, "method": "fast-forward", "raced": False, "ci": "green",
    }  # fmt: skip
    assert world.profile_calls == [(head, "all")]
    receipt = json.loads(world.store().read().files["receipts/openspec-a.json"])
    assert (receipt["merge_commit"], receipt["reviewed_head"]) == (head, head)


def test_scn_yolo_79_a_forge_that_refuses_a_squash_stops_the_plan(world):
    refusal = "Squash merges are not allowed on this repository"
    head, snaps = ready(world, answer=MergeCall("refused", None, refusal))
    tip = world.tip()
    step = world.step(snaps)
    got = state(world)
    assert (got.status, got.stop_reason, got.stop_unit) == ("stopped", "merge_refused", A)
    assert refusal in got.stop_detail and world.tip() == tip
    assert "unit.merged" not in world.kinds() and step.allow == frozenset() and step.start_next_run is False
    assert [e.data["unit"] for e in world.events() if e.type == "unit.dispatched"] == [A]


def test_scn_yolo_80_a_head_that_moved_is_not_merged_and_the_plan_waits(world):
    head, snaps = ready(world, answer=MergeCall("head_moved", None, "Head branch was modified"))
    tip = world.tip()
    step = world.step(snaps)
    got = state(world)
    assert (got.status, got.wait_reason) == ("waiting", "merge_not_ready")
    assert "Head branch was modified" in last(world, "plan.waiting")["detail"]
    assert world.tip() == tip and "unit.merged" not in world.kinds()
    assert step.allow == frozenset({A}) and step.start_next_run is False


def test_scn_yolo_81_a_target_that_moved_during_the_merge_is_recorded_and_checked(world):
    people = []
    head, snaps = ready(world, before=lambda: people.append(world.person_moves_target()))
    world.step(snaps)
    landed = world.tip()
    merged = last(world, "unit.merged")
    assert merged["raced"] is True and merged["merge_commit"] == landed
    assert world.git.run("rev-parse", f"{landed}^").stdout.strip() == people[0]
    assert world.profile_calls == [(landed, "all")]  # the post-merge check of the landed commit decides
    assert state(world).integrated[A] == landed
