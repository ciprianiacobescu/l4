"""The plan step of a CI run waits out the hand-off CI window and merges, instead of idling until the next trigger
(L4-YOLO-012, L4-YOLO-013, L4-CI-014; SCN-YOLO-240..245). The clock is a fake that a sleep advances."""

from datetime import UTC, datetime, timedelta

import pytest

import l4.yolo.cycle as cycle
from l4.forge.base import ForgeError

from .test_merge_safety_ci_gate import Requires, configure, merged, ready, waits
from .yolo_cycle_world import CycleWorld, MergingForge, ev, unit_id
from .yolo_review_world import make_cfg

A = unit_id("a")
T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
AMPLE = 40 * 60


class Clock:
    """`now` and a `sleep` that moves it; `hook` runs after each sleep (something that happens during the wait)."""

    def __init__(self, hook=None) -> None:
        self.t, self.slept, self.hook = T0, [], hook

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)

    def budget(self, total: float):
        """A job budget of `total` seconds from T0 that runs down with this clock, as the real one does."""
        return lambda: total - (self.t - T0).total_seconds()

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.advance(seconds)
        if self.hook is not None:
            self.hook(len(self.slept))


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def handed_off(world: CycleWorld, minutes: float, **state):
    """A unit in review whose hand-off was `minutes` before T0, with no CI on H."""
    return ready(world, ci=None, ready_at=T0 - timedelta(minutes=minutes), **state)


def step(world: CycleWorld, snap, clock: Clock, budget=lambda: AMPLE, **kw):
    return world.step({"a": snap}, now=clock.now, sleep=clock.sleep, budget=budget, **kw)


def test_the_step_waits_out_the_window_and_merges(world):
    """SCN-YOLO-240: 4 minutes handed off, 40 minutes of budget: sleeps in slices of at most 60 s until the window is
    over (the 15 s slack only bounds it), asks the guard again and merges on record; no wait is recorded."""
    head, snap = handed_off(world, 4)
    clock = Clock()
    result = step(world, snap, clock)
    assert [m["ci"] for m in merged(world)] == ["not_run"] and waits(world) == []
    assert max(clock.slept) <= 60 and 360 <= sum(clock.slept) <= 375
    assert any("waiting up to 375 s for the hand-off window" in a for a in result.actions)


def test_ci_that_appears_ends_the_wait(world):
    """SCN-YOLO-241: a running job on H at the third read: the wait ends there and the normal path records the wait."""
    head, snap = handed_off(world, 4)

    def appears(count):
        if count == 3:
            world.forge.script_jobs(head, [("test", "running")])

    clock = Clock(appears)
    result = step(world, snap, clock)
    assert clock.slept == [60, 60, 60] and "unit.merged" not in world.kinds()
    detail = waits(world)[-1]
    assert detail.data["reason"] == "merge_not_ready" and "unfinished: test" in detail.data["detail"]
    assert result.start_next_run is False


def test_a_short_budget_waits_what_it_can_and_chains_one_run(world):
    """SCN-YOLO-242: the budget less the 150 s reserve allows 2 of the 6 minutes: it waits 2, records the wait and
    starts the next run, and the guard is not waited on twice."""
    head, snap = handed_off(world, 4)
    clock = Clock()
    result = step(world, snap, clock, budget=clock.budget(120 + 150))
    assert clock.slept == [60, 60] and "unit.merged" not in world.kinds()
    note = waits(world)[-1].data
    assert note["reason"] == "merge_not_ready" and "less than 10 minutes" in note["detail"]
    assert result.start_next_run is True


@pytest.mark.parametrize("room", [150, 100, 0])
def test_a_budget_with_no_room_for_the_merge_does_not_wait_and_chains_no_run(world, room):
    """D3, D6: nothing to wait with, so the wait is recorded as before and no run is started."""
    head, snap = handed_off(world, 4)
    clock = Clock()
    result = step(world, snap, clock, budget=clock.budget(room))
    assert clock.slept == [] and waits(world)[-1].data["reason"] == "merge_not_ready"
    assert result.start_next_run is False


def test_a_later_run_waits_for_the_rest_and_merges(world):
    """SCN-YOLO-243: the wait is on record (a run without a budget); a run with ample budget 3 minutes before the window
    closes waits for it, and the plan goes on and merges the unit."""
    head, snap = handed_off(world, 7)
    first = step(world, snap, Clock(), budget=None)
    assert first.start_next_run is False and waits(world)[-1].data["reason"] == "merge_not_ready"
    clock = Clock()
    step(world, snap, clock)
    assert 180 <= sum(clock.slept) <= 195 and max(clock.slept) <= 60
    kinds = world.kinds()
    assert "plan.resumed" in kinds and [m["ci"] for m in merged(world)] == ["not_run"]
    assert len(waits(world)) == 1


def test_a_run_that_cannot_wait_keeps_the_plan_waiting(world):
    """D2: the wake path asks the guard, and without a budget it sleeps no more than before."""
    head, snap = handed_off(world, 7)
    step(world, snap, Clock(), budget=None)
    clock = Clock()
    step(world, snap, clock, budget=None)
    assert clock.slept == [] and "unit.merged" not in world.kinds() and len(waits(world)) == 1


def test_the_wait_never_runs_for_a_read_only_step_or_without_ci_budget(world):
    """SCN-YOLO-244: a read-only step (`l4 run --unit`) and a run outside CI (no budget) never sleep."""
    head, snap = handed_off(world, 4)
    clock = Clock()
    world.step({"a": snap}, now=clock.now, sleep=clock.sleep, budget=lambda: AMPLE, read_only=True)
    step(world, snap, clock, budget=None)
    assert clock.slept == [] and "unit.merged" not in world.kinds()


def test_require_ci_never_waits_for_the_window(world):
    """SCN-YOLO-244: with `yolo.merge.require_ci` the outcome is the one before this change."""
    configure(world, require_ci=True)
    head, snap = handed_off(world, 4)
    clock = Clock()
    result = step(world, snap, clock)
    assert clock.slept == [] and waits(world)[-1].data["reason"] == "merge_not_ready"
    assert result.start_next_run is False


def test_a_required_check_that_has_not_reported_is_not_waited_for(world):
    """SCN-YOLO-244: the base branch requires `lint`, which H has not reported: it blocks after the window too."""
    head, snap = handed_off(world, 4)
    forge = Requires(origin=world.origin)
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    clock = Clock()
    result = step(world, snap, clock, forge=forge)
    assert clock.slept == [] and "unit.merged" not in world.kinds()
    assert waits(world)[-1].data["reason"] == "merge_not_ready" and result.start_next_run is False


def test_the_wait_reads_the_window_on_gitlab_too(world):
    """SCN-YOLO-245: a merge request without a pipeline yet reads as the window on GitLab as well."""
    world.cfg = make_cfg(forge={"type": "gitlab", "base_branch": "main", "merge_policy": "auto"})
    head, snap = handed_off(world, 4)
    clock = Clock()
    step(world, snap, clock)
    assert 360 <= sum(clock.slept) <= 375 and [m["ci"] for m in merged(world)] == ["not_run"]


def test_a_cancel_during_the_wait_merges_nothing(world):
    """D5: the guard asks again from the start and reads the plan under the lease, so a cancel made during the wait
    holds."""
    head, snap = handed_off(world, 4)

    def cancelled(count):
        if count == 2:
            world.seed(ev("plan.cancelled", by="alice", reason="stop"))

    clock = Clock(cancelled)
    step(world, snap, clock)
    assert "unit.merged" not in world.kinds() and "unit.merge_requested" not in world.kinds()
    assert not world.landed(head)


class SlowReads(MergingForge):
    """A forge whose every read of the jobs takes `cost` seconds of the clock (retries, rate limits); it can fail."""

    cost = 0.0
    clock: Clock | None = None
    broken = False

    def list_pipeline_jobs(self, sha, *, settled=False):
        if self.broken:
            raise ForgeError("the forge is down")
        if self.clock is not None:
            self.clock.advance(self.cost)
        return super().list_pipeline_jobs(sha, settled=settled)


def slow_forge(world: CycleWorld, clock: Clock, cost: float = 0.0) -> SlowReads:
    forge = SlowReads(origin=world.origin)
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    forge.clock, forge.cost = clock, cost
    return forge


def test_a_cut_wait_on_the_wake_path_starts_the_next_run_once(world):
    """D6 on the wake path: the plan waits with the window's detail; a run with 120 usable seconds of 6 minutes waits
    them, stays waiting with the one record it has, and starts the next run."""
    head, snap = handed_off(world, 4)
    first = step(world, snap, Clock(), budget=None)
    assert first.start_next_run is False and len(waits(world)) == 1
    clock = Clock()
    result = step(world, snap, clock, budget=clock.budget(120 + 150))
    assert clock.slept == [60, 60] and "unit.merged" not in world.kinds()
    assert result.start_next_run is True and len(waits(world)) == 1


def test_reads_that_take_time_are_counted_against_the_budget(world):
    """Each read of H's CI costs 100 s of the clock: the budget is read before every slice, so the step stops when it
    less the reserve is used up (three slices), not after the sleeping it planned; the window is still open then."""
    head, snap = handed_off(world, 0)
    clock = Clock()
    forge = slow_forge(world, clock, cost=100)
    result = step(world, snap, clock, budget=clock.budget(700), forge=forge)
    assert clock.slept == [60, 60, 60] and "unit.merged" not in world.kinds()
    assert result.start_next_run is True  # the budget is what ended the wait; the window is still open


def test_a_fast_clock_does_not_end_the_wait_early_or_chain_a_run(world):
    """pr.ready one minute ahead of the read: the first read clamps it and gives 600 s, the window really ends 60 s
    later. The wait follows the window from each read, so it merges and starts no run."""
    head, snap = handed_off(world, -1)
    clock = Clock()
    step(world, snap, clock)
    assert [m["ci"] for m in merged(world)] == ["not_run"] and waits(world) == []
    assert 660 <= sum(clock.slept) <= 675 and "plan.waiting" not in world.kinds()


def test_a_read_error_during_the_wait_ends_it_and_the_guard_says_so_once(world):
    """D4: the guard asks again from the start and records the unreadable CI as any wait; no more sleeping."""
    head, snap = handed_off(world, 4)
    clock = Clock()
    forge = slow_forge(world, clock)

    def breaks(count):
        forge.broken = count == 2

    clock.hook = breaks
    result = step(world, snap, clock, forge=forge)
    assert clock.slept == [60, 60] and "unit.merged" not in world.kinds()
    assert len(waits(world)) == 1 and "could not be read" in waits(world)[-1].data["detail"]
    assert result.start_next_run is False  # the budget did not end it


def test_the_window_of_a_unit_is_waited_for_once_in_a_step(world, monkeypatch):
    """`_window_waited`: the same step run again (as after a lost lease) does not sleep for the same unit again."""
    head, snap = handed_off(world, 4)
    clock = Clock()
    runs: list[int] = []
    original = cycle._Step.run

    def twice(self):
        runs.append(1)
        original(self)
        runs.append(2)
        return original(self)

    monkeypatch.setattr(cycle._Step, "run", twice)
    cut = clock.budget(120 + 150)
    step(world, snap, clock, budget=lambda: AMPLE if len(runs) > 1 else cut())
    assert clock.slept == [60, 60]
