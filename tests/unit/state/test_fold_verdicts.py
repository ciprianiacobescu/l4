"""The fold's fields for verdicts and fix units (state-vcs-locks 1.20 delta)."""

from datetime import UTC, datetime, timedelta

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

START = datetime(2026, 10, 4, tzinfo=UTC)


def events(*items: tuple[str, dict]) -> list[LedgerEvent]:
    return [
        LedgerEvent(START + timedelta(seconds=n), "r-1", "openspec:u", n, kind, data)
        for n, (kind, data) in enumerate(items, 1)
    ]


def test_human_verdicts_are_consumed_once_per_question():
    state = fold(
        events(
            ("human.verdict", {"question": "Q-001", "target": "C-aaaaaaaa", "decision": "accept"}),
            ("human.verdict", {"question": "Q-001", "target": "C-aaaaaaaa", "decision": "reject"}),
            ("human.verdict", {"question": "Q-002"}),
            ("human.verdict", {"target": "no question id"}),
        ),
        "openspec:u",
    )
    assert state.verdicts_consumed == ["Q-001", "Q-002"]


def test_fix_units_open_and_close_in_order():
    state = fold(events(("fix.spawned", {"fix_unit": "u-fix-1", "round": 1})), "openspec:u")
    assert (state.fix_round, state.children, state.open_fix_unit) == (1, ["u-fix-1"], "u-fix-1")
    state = fold(
        events(
            ("fix.spawned", {"fix_unit": "u-fix-1", "round": 1}),
            ("fix.done", {"fix_unit": "u-fix-1", "round": 1}),
            ("fix.spawned", {"fix_unit": "u-fix-2", "round": 2}),
            ("fix.done", {"fix_unit": "u-fix-1"}),  # an old one finishing late closes nothing
        ),
        "openspec:u",
    )
    assert (state.fix_round, state.children, state.open_fix_unit) == (2, ["u-fix-1", "u-fix-2"], "u-fix-2")
    closed = fold(
        events(("fix.spawned", {"fix_unit": "u-fix-1", "round": 1}), ("fix.done", {"fix_unit": "u-fix-1"})), "x"
    )
    assert closed.open_fix_unit is None and closed.children == ["u-fix-1"]


def test_verdicts_raised_names_the_verdict_questions_of_the_ledgers_and_no_other():  # L4-VER-070
    from l4.verifier.verdicts import _raised

    found = events(
        ("question.raised", {"id": "Q-001", "kind": "technical"}),
        ("question.raised", {"id": "Q-002", "kind": "verdict"}),
        ("question.raised", {"id": "Q-002", "kind": "verdict"}),
        ("question.raised", {"id": "Q-004", "kind": "verdict"}),
    )
    state = fold(found, "openspec:u")
    assert state.verdicts_raised == ["Q-002", "Q-004"]
    assert set(state.verdicts_raised) == set(_raised(found))  # the rule `consume_verdicts` applies
    assert fold([], "openspec:u").verdicts_raised == []
