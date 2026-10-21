from datetime import UTC, datetime, timedelta

import pytest

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
RUN = "r-20261016T1200Z-aaaa"
TRIP = ("breaker.tripped", {"reason": "max_task_attempts", "task": "4.1"})


def state_of(*rows: tuple[str, dict]):
    events = [
        LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:p", n, kind, data) for n, (kind, data) in enumerate(rows)
    ]
    return fold(events, "openspec:p")


def test_a_halt_on_a_task_sets_halt_task():
    state = state_of(TRIP)
    assert state.halt_task == "4.1" and state.halt_fix_unit is None


def test_a_fix_units_breaker_sets_halt_fix_unit():
    state = state_of(("breaker.tripped", {"reason": "max_task_attempts", "task": "1.2", "fix_unit": "p-fix-1"}))
    assert (state.halt_task, state.halt_fix_unit) == ("1.2", "p-fix-1")


def test_the_last_trip_wins_and_drops_an_older_fix_unit():
    state = state_of(
        ("breaker.tripped", {"reason": "max_task_attempts", "task": "1.2", "fix_unit": "p-fix-1"}),
        ("breaker.tripped", {"reason": "max_task_attempts", "task": "4.1"}),
    )
    assert (state.halt_task, state.halt_fix_unit) == ("4.1", None)


@pytest.mark.parametrize("kind", ["unit.retried", "unit.resumed", "unit.restarted"])
def test_a_retry_resume_or_restart_clears_both(kind):
    state = state_of(("breaker.tripped", {**TRIP[1], "fix_unit": "p-fix-1"}), (kind, {}))
    assert state.halt_task is None and state.halt_fix_unit is None


def test_another_reason_sets_nothing():
    state = state_of(("breaker.tripped", {"reason": "no_progress", "task": "4.1"}))
    assert state.halt_task is None and state.halt_fix_unit is None and state.breaker_trips == 1


def test_an_escalated_selection_keeps_fallback_from_and_adds_the_profile():
    state = state_of(
        ("availability.selected", {"role": "implementer", "selected": "deepseek", "fallback_from": "claude"}),
        ("availability.selected", {"role": "implementer", "selected": "glm", "escalated_from": "deepseek"}),
    )
    assert state.profiles_used["implementer"] == ["deepseek", "glm"]
    assert state.fallback_from == {"implementer": "claude"}


def test_a_plain_selection_still_clears_fallback_from():
    state = state_of(
        ("availability.selected", {"role": "implementer", "selected": "deepseek", "fallback_from": "claude"}),
        ("availability.selected", {"role": "implementer", "selected": "claude"}),
    )
    assert state.fallback_from == {}
