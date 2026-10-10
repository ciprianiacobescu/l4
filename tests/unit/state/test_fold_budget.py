"""M1.13 line 14 (W-C2, SPEC L4-IMP-013): `budget.extended{fix_rounds}` adds to the fix-round limit (a sum)."""

from datetime import UTC, datetime, timedelta

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
RUN = "r-20261007T1200Z-aaaa"


def events(*rows: tuple[str, dict]) -> list[LedgerEvent]:
    return [
        LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:p", n, kind, data) for n, (kind, data) in enumerate(rows)
    ]


def test_extensions_add_up_and_a_later_resume_does_not_reset_them():
    state = fold(
        events(
            ("budget.extended", {"fix_rounds": 1, "by": "member", "signal": "label:7"}),
            ("unit.resumed", {"reason": "again"}),
            ("budget.extended", {"fix_rounds": 2, "by": "human", "reason": "more"}),
        ),
        "openspec:p",
    )
    assert state.fix_rounds_extra == 3


def test_a_unit_with_no_extension_has_none():
    assert fold(events(("unit.resumed", {"reason": "x"})), "openspec:p").fix_rounds_extra == 0


def test_a_malformed_extension_is_ignored():
    rows = events(
        ("budget.extended", {"fix_rounds": True}),  # a bool is not a count
        ("budget.extended", {"fix_rounds": -2}),
        ("budget.extended", {"fix_rounds": "3"}),
        ("budget.extended", {"iterations": 5, "cost_usd": 20.0}),  # other budgets are not folded here
        ("budget.extended", {"fix_rounds": 1}),
    )
    assert fold(rows, "openspec:p").fix_rounds_extra == 1
