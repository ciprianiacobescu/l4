from datetime import UTC, datetime, timedelta

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 4, 9, 0, 0, tzinfo=UTC)
RUN = "r-20261004T0900Z-aaaa"


def ev(n: int, type_: str, **data) -> LedgerEvent:
    return LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:x", n, type_, data)


def park(n: int, source: str, **extra) -> LedgerEvent:
    edge = {"from": source, "to": "waiting_capacity", "trigger": "required_role_unavailable"}
    return ev(n, "phase.changed", **edge, **extra)


def test_retry_after_comes_from_the_park_edge_and_goes_with_the_unit_leaving_it():
    parked = fold([park(1, "implementing", retry_after="2026-10-04T14:00:00Z")], "openspec:x")
    assert parked.phase == "waiting_capacity" and parked.retry_after == "2026-10-04T14:00:00Z"
    back = fold(
        [
            park(1, "implementing", retry_after="2026-10-04T14:00:00Z"),
            ev(2, "phase.changed", **{"from": "waiting_capacity", "to": "implementing", "trigger": "restored"}),
        ],
        "openspec:x",
    )
    assert back.phase == "implementing" and back.retry_after is None


def test_a_park_without_retry_after_leaves_it_unset():
    assert fold([park(1, "ready")], "openspec:x").retry_after is None


def test_fallback_from_is_kept_per_role_and_dropped_when_the_preferred_profile_is_back():
    state = fold(
        [
            ev(1, "availability.selected", role="implementer", selected="b", fallback_from="a", fallback_index=1),
            ev(2, "availability.selected", role="judges", selected="j1", fallback_index=0),
        ],
        "openspec:x",
    )
    assert state.fallback_from == {"implementer": "a"}
    assert state.profiles_used == {"implementer": ["b"], "judges": ["j1"]}
    later = fold(
        [
            ev(1, "availability.selected", role="implementer", selected="b", fallback_from="a"),
            ev(2, "availability.selected", role="implementer", selected="a"),
        ],
        "openspec:x",
    )
    assert later.fallback_from == {}
