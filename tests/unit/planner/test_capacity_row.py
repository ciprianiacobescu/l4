from datetime import UTC, datetime

from l4.planner import UnitFacts, next_action

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def facts(previous: str | None, retry_after: str | None, done: int = 0) -> UnitFacts:
    return UnitFacts(
        "openspec:x", "openspec", "waiting_capacity", done, 2, retry_after=retry_after, previous_phase=previous
    )


def test_before_retry_after_nothing_is_to_be_done():
    action, reason = next_action(facts("implementing", "2026-10-04T12:00:01Z"), NOW)
    assert action == "none" and reason == "waiting_capacity until 2026-10-04T12:00:01Z"


def test_once_retry_after_has_passed_the_previous_phases_action_is_next():
    for previous, expected in (("implementing", "implement"), ("ready", "implement"), ("verifying", "verify")):
        action, reason = next_action(facts(previous, "2026-10-04T12:00:00Z"), NOW)
        assert action == expected
        assert reason == "capacity: retry_after 2026-10-04T12:00:00Z passed"


def test_the_clock_defaults_to_now():
    assert next_action(facts("implementing", "2020-01-01T00:00:00Z"))[0] == "implement"
    assert next_action(facts("implementing", "2999-01-01T00:00:00Z"))[0] == "none"


def test_without_retry_after_the_unit_stays_parked():
    action, reason = next_action(facts("implementing", None))
    assert action == "none" and "waiting_capacity" in reason


def test_an_unreadable_retry_after_or_an_unknown_previous_phase_stays_parked():
    assert next_action(facts("implementing", "soon"), NOW)[0] == "none"
    assert next_action(facts(None, "2026-10-04T11:00:00Z"), NOW)[0] == "none"
    assert next_action(facts("awaiting_human", "2026-10-04T11:00:00Z"), NOW)[0] == "none"


def test_retry_after_equal_to_now_is_due():
    """A chain with nothing cooling parks at `now` (M1.8 R4): the very next plan or run takes the unit up again."""
    action, reason = next_action(facts("verifying", "2026-10-04T12:00:00Z"), NOW)
    assert action == "verify" and "passed" in reason
