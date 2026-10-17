"""A capacity wait never chains runs, and a wait only a fix can end stops the plan (L4-YOLO-035, SCN-YOLO-90..92)."""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from l4.state.ledger import LedgerEvent
from l4.state.parks import FixPark, fix_parks
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A = unit_id("a")
AUTH = "opencode authentication failed (login expired or rejected)"


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def _active(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))


def _park(at: str, *names: str, step: str = "hello", reason: str = AUTH) -> FixPark:
    profiles = tuple((n, step, reason) for n in names)
    return FixPark(datetime.fromisoformat(at), "implementer", profiles)


def _parked(world, *parks: FixPark, retry_after: str = "2026-10-14T10:30:00Z"):
    snap = world.snapshot("a", "waiting_capacity", retry_after=retry_after, previous_phase="implementing")
    return {"a": dataclasses.replace(snap, fix_parks=parks)}


# a park from before the plan's clock ran: the plan ledger's events are all at 2026-10-14T10:00:00Z
FIRST, SECOND = "2026-10-14T10:10:00+00:00", "2026-10-14T10:20:00+00:00"


def test_scn_yolo_90_a_failed_login_does_not_chain_runs(world):
    """SCN-YOLO-90: the step dispatches the parked unit and starts no next run."""
    _active(world)
    snaps = _parked(world, _park(FIRST, "deepseek", "kimi"), retry_after="2026-10-14T10:10:00Z")
    step = world.step(snaps)
    assert step.allow == frozenset({A}) and step.start_next_run is False
    assert "unit.dispatched" in world.kinds() and "plan.stopped" not in world.kinds()


def test_scn_yolo_90_a_unit_that_is_not_parked_still_chains(world):
    """SCN-YOLO-90: L4-YOLO-012 is unchanged for every other phase."""
    _active(world)
    step = world.step({"a": world.snapshot("a", "implementing")})
    assert step.allow == frozenset({A}) and step.start_next_run is True


def test_scn_yolo_91_the_second_identical_park_stops_the_plan_with_the_fix_named(world):
    """SCN-YOLO-91: two parks, the same two profiles, nothing cooling."""
    _active(world)
    snaps = _parked(world, _park(FIRST, "deepseek", "kimi"), _park(SECOND, "kimi", "deepseek"))
    step = world.step(snaps)
    assert step.allow == frozenset() and step.start_next_run is False
    stopped = [e for e in world.events() if e.type == "plan.stopped"][-1].data
    assert stopped["reason"] == "capacity_needs_fix" and stopped["unit"] == A
    detail = stopped["detail"]
    assert "deepseek" in detail and "kimi" in detail and "opencode authentication failed" in detail
    assert "OPENCODE_API_KEY" in detail and "l4 yolo resume p1 --reason" in detail
    state = fold_plan("p1", world.events())
    assert state.status == "stopped" and state.stop_reason == "capacity_needs_fix"


def test_scn_yolo_91_one_park_does_not_stop(world):
    """SCN-YOLO-91: a single fix-only park is probed again (once, no chained run)."""
    _active(world)
    step = world.step(_parked(world, _park(SECOND, "deepseek")))
    assert step.allow == frozenset({A}) and "plan.stopped" not in world.kinds()


def test_scn_yolo_91_parks_for_other_profiles_do_not_stop(world):
    """SCN-YOLO-91: the same set of unusable profiles is what makes the second park the same."""
    _active(world)
    step = world.step(_parked(world, _park(FIRST, "deepseek"), _park(SECOND, "kimi")))
    assert step.allow == frozenset({A}) and "plan.stopped" not in world.kinds()


def test_scn_yolo_91_parks_from_before_a_resume_do_not_stop_again(world):
    """SCN-YOLO-91: after `l4 yolo resume` the next run probes; two new parks are needed to stop again."""
    _active(world)
    world.seed(ev("plan.stopped", reason="capacity_needs_fix", unit=A), ev("plan.resumed", by="alice", reason="key"))
    snaps = _parked(
        world, _park("2026-10-14T09:00:00+00:00", "deepseek"), _park("2026-10-14T09:30:00+00:00", "deepseek")
    )
    step = world.step(snaps)
    assert step.allow == frozenset({A}) and step.start_next_run is False
    assert fold_plan("p1", world.events()).status == "active"


def test_scn_yolo_92_a_cooling_profile_still_waits_for_its_reset(world):
    """SCN-YOLO-92: retry_after in the future: the plan waits, starts no run, does not stop."""
    _active(world)
    soon = (datetime.now(UTC) + timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    step = world.step(_parked(world, retry_after=soon))
    assert step.start_next_run is False
    assert world.kinds()[-1] == "plan.waiting"
    assert [e for e in world.events() if e.type == "plan.waiting"][-1].data["reason"] == "unit_waiting_capacity"
    assert "plan.stopped" not in world.kinds()


# --- the park, read from the unit's ledger ---------------------------------------------------------------------------


def _e(seq: int, kind: str, **data) -> LedgerEvent:
    ts = datetime(2026, 10, 14, 10, seq, tzinfo=UTC)
    return LedgerEvent(ts, "r1", A, seq, kind, data)


def _unavailable(seq: int, skipped, retry_after: str | None = "2026-10-14T10:00:00Z", required=True) -> LedgerEvent:
    return _e(seq, "availability.unavailable", role="implementer", required=required, skipped=skipped,
              retry_after=retry_after)  # fmt: skip


def _park_events(seq: int, skipped, **kw) -> list[LedgerEvent]:
    return [_unavailable(seq, skipped, **kw), _e(seq + 1, "phase.changed", to="waiting_capacity")]


HELLO = [{"profile": "deepseek", "step": "hello", "reason": AUTH}]
COOLING = [{"profile": "deepseek", "step": "cooling", "reason": "cooling (limit)", "resets_at": "2026-10-14T11:00:00Z"}]


def test_a_park_with_nothing_cooling_is_fix_only():
    parks = fix_parks([*_park_events(1, HELLO), _e(3, "phase.changed", to="fixing"), *_park_events(4, HELLO)])
    assert [p.profiles for p in parks] == [(("deepseek", "hello", AUTH),)] * 2


def test_a_cooling_profile_or_a_future_retry_after_is_not_fix_only():
    assert fix_parks(_park_events(1, COOLING, retry_after="2026-10-14T11:00:00Z")) == ()
    assert (
        fix_parks(_park_events(1, HELLO, retry_after="2026-10-14T11:00:00Z")) == ()
    )  # a cool-down elsewhere in the chain


def test_a_cooling_park_between_two_fix_only_parks_ends_the_run():
    events = [
        *_park_events(1, HELLO),
        *_park_events(3, COOLING, retry_after="2026-10-14T11:00:00Z"),
        *_park_events(5, HELLO),
    ]
    assert len(fix_parks(events)) == 1


def test_task_progress_between_parks_ends_the_run():
    for progress in (
        _e(3, "task.done", task="1.1"),
        _e(3, "task.red_ok", task="1.1"),
        _e(3, "step.finished", status="ok"),
    ):
        assert len(fix_parks([*_park_events(1, HELLO), progress, *_park_events(4, HELLO)])) == 1


def test_a_park_without_a_record_or_a_judge_miss_is_not_a_fix_only_park():
    assert fix_parks([_e(1, "phase.changed", to="waiting_capacity")]) == ()
    assert fix_parks([_unavailable(1, HELLO, required=False), _e(2, "phase.changed", to="waiting_capacity")]) == ()
