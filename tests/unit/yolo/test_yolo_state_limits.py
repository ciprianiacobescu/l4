"""limits.py: the effective limits, which one is reached, what a resume allows (R3, R12; L4-YOLO-017..).

The limit validators of the plan file (review #21, R12) are tested here too."""

from datetime import UTC, datetime, timedelta

import pytest

from l4.yolo.limits import effective_limits, reached, reached_at, resume_allows
from l4.yolo.model import PlanInvalid, load_plan
from l4.yolo.state import fold_plan

from .yolo_ledger_world import ev

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def active(limits, *later):
    return fold_plan("p1", [ev("plan.activated", plan_digest="pd", digests={}, limits=limits, by="me"), *later])


def resumed(**extend):
    """A stop and the resume that extends the limits (a resume counts only from `stopped` or `waiting`)."""
    return [ev("plan.stopped", reason="limit"), ev("plan.resumed", by="x", extend=extend)]


def charge(unit="openspec:a", attempt=1, cost=0.0, runs=0):
    return ev("plan.charged", unit=unit, attempt=attempt, cost_usd=cost, runs=runs)


def test_no_limits_are_never_reached_and_attempts_default_to_two():
    s = active({}, charge(cost=999, runs=999))
    assert reached(s, now=NOW) is None
    assert effective_limits(s).attempts == 2 and effective_limits(s).cost_usd is None


def test_cost_and_runs_are_reached_when_used_equals_the_limit():
    assert reached(active({"max_cost_usd": 5}, charge(cost=4.99)), now=NOW) is None
    code, detail = reached(active({"max_cost_usd": 5}, charge(cost=5.0)), now=NOW)
    assert code == "limit_cost" and "$5.00" in detail
    assert reached(active({"max_runs": 3}, charge(runs=2)), now=NOW) is None
    assert reached(active({"max_runs": 3}, charge(runs=3)), now=NOW)[0] == "limit_runs"


def test_a_zero_cost_limit_is_reached_at_once():
    assert reached(active({"max_cost_usd": 0}), now=NOW)[0] == "limit_cost"


def test_attempts_are_exceeded_when_greater_than_the_limit():
    """Review #1 / SCN-YOLO-27: the third attempt of a unit with max_unit_attempts 2 stops the plan."""
    limits = {"max_unit_attempts": 2}
    assert reached(active(limits, charge(attempt=1), charge(attempt=2)), now=NOW) is None
    hit = reached_at(active(limits, charge(attempt=3)), now=NOW)
    assert hit is not None and hit[0] == "limit_attempts" and hit[2] == "openspec:a" and "attempt 3 of 2" in hit[1]


def test_attempt_extensions_for_every_unit_and_for_one():
    limits = {"max_unit_attempts": 1}
    over = [charge("a", 3), charge("b", 3)]
    s = active(limits, *over, *resumed(**{"attempts": 1}))
    assert effective_limits(s).attempts_of("a") == 2 and reached_at(s, now=NOW)[2] == "a"
    s = active(limits, *over, *resumed(**{"attempts": {"a": 2}}))
    assert effective_limits(s).attempts_of("a") == 3 and effective_limits(s).attempts_of("b") == 1
    assert reached_at(s, now=NOW)[2] == "b"  # a (3 <= 3) is fine, b (3 > 1) is not


def test_integrated_units_and_plan_keys_are_not_checked_for_attempts():
    s = active(
        {"max_unit_attempts": 1},
        charge("openspec:a", 5),
        ev("unit.integrated", unit="openspec:a", revision="r"),
        charge("plan:review", 0, cost=1.0),
    )
    assert reached(s, now=NOW) is None


def test_deadline_is_reached_at_the_deadline_and_extended_by_resume():
    limits = {"deadline": "2026-10-14T12:00:00Z"}
    assert reached(active(limits), now=NOW - timedelta(seconds=1)) is None
    assert reached(active(limits), now=NOW)[0] == "limit_deadline"
    s = active(limits, *resumed(**{"deadline": "2026-10-15T00:00:00Z"}))
    assert effective_limits(s).deadline == datetime(2026, 10, 15, tzinfo=UTC)
    assert reached(s, now=NOW) is None
    earlier = active(limits, *resumed(**{"deadline": "2026-10-01T00:00:00Z"}))
    assert effective_limits(earlier).deadline == datetime(2026, 10, 14, 12, tzinfo=UTC)  # never earlier than frozen
    assert reached(active(limits), now=datetime(2026, 10, 14, 13, 0)) is not None  # a naive clock is read as UTC


def test_the_order_is_cost_runs_attempts_deadline():
    limits = {"max_cost_usd": 1, "max_runs": 1, "max_unit_attempts": 1, "deadline": "2026-01-01T00:00:00Z"}
    s = active(limits, charge(attempt=2, cost=1, runs=1))
    assert reached(s, now=NOW)[0] == "limit_cost"
    s = active({**limits, "max_cost_usd": 100}, charge(attempt=2, cost=1, runs=1))
    assert reached(s, now=NOW)[0] == "limit_runs"
    s = active({**limits, "max_cost_usd": 100, "max_runs": 100}, charge(attempt=2))
    assert reached(s, now=NOW)[0] == "limit_attempts"
    s = active({**limits, "max_cost_usd": 100, "max_runs": 100}, charge(attempt=1))
    assert reached(s, now=NOW)[0] == "limit_deadline"


def test_the_fallback_stands_in_before_activation_but_the_frozen_limits_win():
    s = fold_plan("p1", [ev("plan.admitted", plan_digest="d")])
    assert effective_limits(s, {"max_runs": 4}).runs == 4
    assert effective_limits(active({"max_runs": 9}), {"max_runs": 4}).runs == 9


def test_resume_allows_only_when_the_extension_clears_every_limit():
    s = active({"max_cost_usd": 5, "max_runs": 2}, charge(cost=5, runs=1), ev("plan.stopped", reason="limit_cost"))
    assert resume_allows(s, None, now=NOW)[0] == "limit_cost"
    assert resume_allows(s, {"cost_usd": 0.5}, now=NOW) is None
    assert resume_allows(s, {"cost_usd": 3, "runs": 0}, now=NOW) is None
    before = s.model_copy(deep=True)
    assert resume_allows(s, {"cost_usd": 10, "runs": 1, "attempts": {"openspec:a": 1}}, now=NOW) is None
    assert s == before  # the state is not changed
    s2 = active({"max_runs": 1}, charge(runs=1))
    assert resume_allows(s2, {"cost_usd": 100}, now=NOW)[0] == "limit_runs"
    assert resume_allows(s2, {"runs": 1}, now=NOW) is None
    s3 = active({"deadline": "2026-10-01T00:00:00Z"})
    assert resume_allows(s3, {"deadline": "2026-10-02T00:00:00Z"}, now=NOW)[0] == "limit_deadline"
    assert resume_allows(s3, {"deadline": "2026-11-01T00:00:00Z"}, now=NOW) is None


# --- R12: the plan file's limits (review #21) ---------------------------------------------------------------------


def plan_text(limits: str) -> str:
    return (
        '{"schema":"l4/delivery-plan@1","plan_id":"p","target":"main","merge":"human",'
        f'"limits":{limits},"batches":[{{"id":"b","units":[{{"id":"openspec:a"}}]}}]}}'
    )


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        ('{"max_unit_attempts": 0}', "max_unit_attempts"),
        ('{"max_unit_attempts": -1}', "max_unit_attempts"),
        ('{"max_cost_usd": -5}', "max_cost_usd"),
        ('{"max_runs": 0}', "max_runs"),
        ('{"deadline": "2026-12-31T18:00:00"}', "time zone"),
    ],
)
def test_bad_limits_are_refused(limits, message):
    result = load_plan(plan_text(limits))
    assert isinstance(result, PlanInvalid) and any(message in e for e in result.errors), result


@pytest.mark.parametrize(
    "limits",
    ['{}', '{"max_cost_usd": 0}', '{"max_cost_usd": 12.5, "max_runs": 1, "max_unit_attempts": 1}',
     '{"deadline": "2026-12-31T18:00:00Z"}', '{"deadline": "2026-12-31T18:00:00+02:00"}'],
)  # fmt: skip
def test_good_limits_are_accepted(limits):
    result = load_plan(plan_text(limits))
    assert not isinstance(result, PlanInvalid), result
    if "deadline" in limits:
        assert result.limits.deadline.utcoffset() is not None
