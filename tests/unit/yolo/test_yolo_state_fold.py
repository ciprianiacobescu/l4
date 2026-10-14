"""fold_plan: every event of design D4, the status rules, usage that never goes down (L4-YOLO-006, -013, -014)."""

import logging

import pytest

from l4.yolo.state import fold_plan

from .yolo_ledger_world import ev

ACTIVATED = ev("plan.activated", plan_digest="pd", digests={"openspec:a": "da"}, limits={"max_runs": 5}, by="me")


def fold(*events):
    return fold_plan("p1", events)


def test_empty_ledger_is_new():
    s = fold()
    assert s.status == "new" and s.plan_id == "p1" and s.current is None and s.used.cost_usd == 0


def test_admitted_refused_reviewed_before_activation():
    s = fold(ev("plan.refused", findings=[{"code": "cycle", "subject": "p1", "text": "a->b->a"}]))
    assert s.status == "refused" and s.findings[0]["code"] == "cycle"
    s = fold(ev("plan.refused", findings=[{"code": "x"}]), ev("plan.admitted", plan_digest="d1", order=["openspec:a"]))
    assert s.status == "admitted" and s.findings == [] and s.plan_digest == "d1" and s.order == ["openspec:a"]
    s = fold(
        ev("plan.admitted", plan_digest="d1", merge="auto"),
        ev(
            "plan.reviewed",
            plan_digest="d1",
            units={"openspec:a": {"verdict": "READY", "digest": "da", "findings": []}},
            batches={"b1": {"verdict": "NEEDS_REVISION", "findings": []}},
        ),
    )
    assert s.status == "reviewed" and s.merge == "auto" and s.review_plan_digest == "d1"
    assert s.review == {"openspec:a": "READY", "batch:b1": "NEEDS_REVISION"}
    assert s.review_digests == {"openspec:a": "da"}


def test_a_new_review_replaces_the_old_one():
    first = ev("plan.reviewed", plan_digest="d1", units={"u": {"verdict": "BLOCKED"}})
    second = ev("plan.reviewed", plan_digest="d2", units={"u": {"verdict": "READY", "digest": "x"}})
    s = fold(first, second)
    assert s.review == {"u": "READY"} and s.review_plan_digest == "d2"


def test_activation_freezes_digests_and_limits():
    s = fold(ev("plan.admitted", plan_digest="d1"), ACTIVATED)
    assert (s.status, s.plan_digest, s.digests, s.limits, s.activated_by) == (
        "active", "pd", {"openspec:a": "da"}, {"max_runs": 5}, "me")  # fmt: skip


def test_dispatch_sets_current_and_integration_clears_it():
    s = fold(ACTIVATED, ev("unit.dispatched", unit="openspec:a", run="r1"))
    assert s.current == "openspec:a"
    s = fold(
        ACTIVATED,
        ev("unit.dispatched", unit="openspec:a"),
        ev("unit.merge_requested", unit="openspec:a", head="h", target_before="t"),
        ev("unit.merged", unit="openspec:a", head="h", pr=3, merge_commit="mc"),
        ev("unit.postcheck", unit="openspec:a", revision="mc", profile="all", status="pass", detail=""),
    )
    assert s.merged == {"openspec:a": "mc"} and s.integrated == {} and s.current == "openspec:a"
    s = fold(
        ACTIVATED,
        ev("unit.dispatched", unit="openspec:a"),
        ev("unit.merged", unit="openspec:a", head="h"),
        ev("unit.integrated", unit="openspec:a", revision="rev1"),
    )
    assert s.integrated == {"openspec:a": "rev1"} and s.current is None and s.merged == {"openspec:a": "h"}


def test_integrating_another_unit_keeps_current():
    s = fold(ACTIVATED, ev("unit.dispatched", unit="b"), ev("unit.integrated", unit="a", revision="r"))
    assert s.current == "b" and s.integrated == {"a": "r"}


def test_batches_accepted_and_failed():
    s = fold(ev("batch.failed", batch="b1", revision="r", detail="boom"))
    assert s.failed_batches == {"b1": "boom"}
    s = fold(ev("batch.failed", batch="b1", detail="boom"), ev("batch.accepted", batch="b1", revision="r2"))
    assert s.failed_batches == {} and s.accepted_batches == {"b1": "r2"}


def test_waiting_until_the_next_dispatch_merge_or_integration():
    waiting = [ACTIVATED, ev("plan.waiting", reason="awaiting_human", unit="a")]
    s = fold(*waiting)
    assert s.status == "waiting" and s.wait_reason == "awaiting_human"
    for wake in (
        ev("unit.dispatched", unit="a"),
        ev("unit.merged", unit="a", head="h"),
        ev("unit.integrated", unit="a", revision="r"),
        ev("unit.merge_requested", unit="a"),
    ):
        s = fold(*waiting, wake)
        assert s.status == "active" and s.wait_reason is None, wake.type


def test_waiting_survives_unrelated_events_and_a_second_wait_replaces_the_reason():
    s = fold(ACTIVATED, ev("plan.waiting", reason="r1"), ev("unit.postcheck", unit="a"), ev("plan.charged", unit="a"))
    assert s.status == "waiting"
    s = fold(ACTIVATED, ev("plan.waiting", reason="r1"), ev("plan.waiting", reason="r2"))
    assert s.wait_reason == "r2"


def test_waiting_before_activation_is_ignored():
    assert fold(ev("plan.admitted", plan_digest="d"), ev("plan.waiting", reason="x")).status == "admitted"


def test_stopped_until_resumed():
    stop = ev("plan.stopped", reason="unit_halted", detail="d", unit="a")
    s = fold(ACTIVATED, stop)
    assert (s.status, s.stop_reason, s.stop_detail, s.stop_unit) == ("stopped", "unit_halted", "d", "a")
    s = fold(ACTIVATED, stop, ev("unit.postcheck", unit="a"))
    assert s.status == "stopped"
    s = fold(ACTIVATED, stop, ev("plan.resumed", by="me", reason="fixed"))
    assert s.status == "active" and s.stop_reason is None and s.stop_unit is None


def test_a_stopped_plan_stays_stopped_on_a_wait():
    assert fold(ACTIVATED, ev("plan.stopped", reason="x"), ev("plan.waiting", reason="w")).status == "stopped"


def test_reactivation_after_inputs_changed_replaces_digests_and_keeps_usage():
    s = fold(
        ACTIVATED,
        ev("unit.dispatched", unit="openspec:a"),
        ev("plan.charged", unit="openspec:a", cost_usd=3.5, runs=2, attempts=1),
        ev("plan.stopped", reason="inputs_changed", unit="openspec:a"),
        ev("plan.reviewed", plan_digest="pd2", units={"openspec:a": {"verdict": "READY", "digest": "da2"}}),
        ev("plan.activated", plan_digest="pd2", digests={"openspec:a": "da2"}, limits={"max_runs": 9}, by="you"),
    )
    assert s.status == "active" and s.digests == {"openspec:a": "da2"} and s.limits == {"max_runs": 9}
    assert s.stop_reason is None and s.activated_by == "you" and s.current == "openspec:a"
    assert (s.used.cost_usd, s.used.runs, s.used.attempts) == (3.5, 2, {"openspec:a": 1})


def test_a_review_while_stopped_does_not_end_the_stop():
    s = fold(ACTIVATED, ev("plan.stopped", reason="inputs_changed"), ev("plan.reviewed", plan_digest="x"))
    assert s.status == "stopped"


def test_cancelled_and_completed_are_final():
    later = [
        ev("plan.activated", plan_digest="z"), ev("plan.resumed", by="x"), ev("plan.stopped", reason="r"),
        ev("plan.waiting", reason="w"), ev("plan.admitted", plan_digest="z"), ev("plan.cancelled", by="x"),
        ev("plan.completed", revision="r"),
    ]  # fmt: skip
    s = fold(ACTIVATED, ev("plan.cancelled", by="me", reason="no"), *later)
    assert s.status == "cancelled" and s.completed_revision is None
    s = fold(ACTIVATED, ev("plan.completed", revision="rev9"), *later)
    assert s.status == "completed" and s.completed_revision == "rev9"


def test_completed_clears_current_and_wait():
    s = fold(ACTIVATED, ev("unit.dispatched", unit="a"), ev("plan.completed", revision="r"))
    assert s.current is None and s.status == "completed"


def test_stale_merges_count_and_reset_only_when_attempts_grew():
    u = "openspec:a"
    base = [ACTIVATED, ev("plan.charged", unit=u, attempts=1), ev("unit.dispatched", unit=u)]
    s = fold(*base, ev("unit.merge_refused", unit=u, reason="stale"))
    assert s.stale_merges == {u: 1}
    s = fold(*base, ev("unit.merge_refused", unit=u, reason="stale"), ev("unit.dispatched", unit=u))
    assert s.stale_merges == {u: 1}  # same attempt: the second stale will stop the plan
    s = fold(*base, ev("unit.merge_refused", unit=u, reason="stale"), ev("unit.merge_refused", unit=u, reason="stale"))
    assert s.stale_merges == {u: 2}
    s = fold(
        *base,
        ev("unit.merge_refused", unit=u, reason="stale"),
        ev("plan.charged", unit=u, attempts=2),
        ev("unit.dispatched", unit=u),
    )
    assert s.stale_merges == {}  # a new attempt
    s = fold(*base, ev("unit.merge_refused", unit=u, reason="protected_branch"))
    assert s.stale_merges == {}


def test_usage_is_per_unit_maximum_and_summed():
    s = fold(
        ACTIVATED,
        ev("plan.charged", unit="a", cost_usd=1.0, runs=1, attempts=1),
        ev("plan.charged", unit="b", cost_usd=2.0, runs=3, attempts=1),
        ev("plan.charged", unit="a", cost_usd=1.5, runs=2, attempts=1),
    )
    assert (s.used.cost_usd, s.used.runs, s.used.attempts) == (3.5, 5, {"a": 1, "b": 1})


def test_usage_never_goes_down_after_a_restart_like_sequence():
    """SCN-YOLO-27's precondition: a unit restart resets the unit's own counters, not the plan's."""
    u = "openspec:a"
    events = [
        ACTIVATED,
        ev("unit.dispatched", unit=u),
        ev("plan.charged", unit=u, cost_usd=2.0, runs=3, attempts=1),
        ev("plan.stopped", reason="unit_halted", unit=u),
        ev("plan.resumed", by="me", reason="retry"),
        ev("plan.charged", unit=u, cost_usd=0.0, runs=0, attempts=0),  # the restart zeroed the unit's counters
        ev("unit.dispatched", unit=u),
        ev("plan.charged", unit=u, cost_usd=2.0, runs=3, attempts=2),
    ]
    seen = [fold_plan("p1", events[: i + 1]).used for i in range(len(events))]
    for before, after in zip(seen, seen[1:], strict=False):
        assert after.cost_usd >= before.cost_usd and after.runs >= before.runs
        assert all(after.attempts.get(k, 0) >= v for k, v in before.attempts.items())
    assert seen[-1].attempts == {u: 2}
    s = fold_plan("p1", events)
    assert s.status == "active" and s.used.cost_usd == 2.0


def test_resume_extends_the_limits():
    s = fold(
        ACTIVATED,
        ev("plan.stopped", reason="limit_cost"),
        ev("plan.resumed", by="me", reason="more", extend={"cost_usd": 10, "runs": 5, "attempts": {"a": 1}}),
        ev("plan.stopped", reason="limit_runs"),
        ev("plan.resumed", by="me", reason="more", extend={"cost_usd": 2.5, "attempts": 1}),
    )
    assert (s.extended.cost_usd, s.extended.runs, s.extended.attempts) == (12.5, 5, {"a": 1, "*": 1})
    assert s.used.cost_usd == 0


def test_resume_without_extend_and_junk_extend():
    s = fold(ACTIVATED, ev("plan.stopped", reason="x"), ev("plan.resumed", extend="lots"))
    assert s.status == "active" and s.extended.cost_usd == 0


def test_unknown_events_are_ignored_and_logged(caplog):
    with caplog.at_level(logging.DEBUG, logger="l4.yolo.state"):
        s = fold(ACTIVATED, ev("plan.from_the_future", x=1), ev("unit.dispatched", unit="a"))
    assert s.status == "active" and s.current == "a"
    assert "plan.from_the_future" in caplog.text


@pytest.mark.parametrize(
    "kind", ["unit.dispatched", "unit.merged", "unit.integrated", "unit.merge_refused", "plan.charged"]
)
def test_an_event_without_its_unit_changes_nothing(kind):
    assert fold(ACTIVATED, ev(kind)) == fold(ACTIVATED)
