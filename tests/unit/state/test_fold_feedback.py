"""human-feedback 2.1 (L4-FBK-004, L4-FBK-006, L4-FBK-007; D7, D8): the fold of the feedback events, the feedback round
count and the feedback budget. Later work emits the events; this is the state they read."""

from datetime import UTC, datetime, timedelta

from l4.config.schema import L4Config
from l4.state.budget import FEEDBACK_ROUNDS_EXHAUSTED, feedback_round_limit, feedback_rounds_left
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
RUN = "r-20261012T1200Z-aaaa"


def events(*rows: tuple[str, dict]) -> list[LedgerEvent]:
    return [
        LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:p", n, kind, data) for n, (kind, data) in enumerate(rows)
    ]


def state(*rows: tuple[str, dict]):
    return fold(events(*rows), "openspec:p")


def taken(item: str = "FB-001", sha: str = "a" * 64, round_: int = 1, fix_unit: str = "p-fix-1") -> tuple[str, dict]:
    return "feedback.taken", {"id": item, "kind": "refactor", "sha256": sha, "round": round_, "fix_unit": fix_unit}


def test_taken_records_the_hash_of_the_last_take():
    """L4-FBK-004, D7: the sha256 of a take is what a later edit is compared with."""
    item = state(taken(sha="1" * 64)).feedback["FB-001"]
    assert (item.status, item.sha256, item.round, item.fix_unit, item.kind) == (
        "taken",
        "1" * 64,
        1,
        "p-fix-1",
        "refactor",
    )


def test_a_second_take_replaces_the_hash_and_the_round():
    """D7: an edit makes the item takeable again; its next take is the new last take."""
    item = state(
        taken(sha="1" * 64),
        ("feedback.changed", {"id": "FB-001", "previous_sha256": "1" * 64, "sha256": "2" * 64}),
        taken(sha="2" * 64, round_=2, fix_unit="p-fix-2"),
    ).feedback["FB-001"]
    assert (item.status, item.sha256, item.round, item.fix_unit) == ("taken", "2" * 64, 2, "p-fix-2")


def test_changed_before_a_take_keeps_the_hash_and_says_so():
    """D7: `feedback.changed` alone does not move the last-take hash; the status shows the item waits to be taken."""
    item = state(
        taken(sha="1" * 64), ("feedback.changed", {"id": "FB-001", "previous_sha256": "1" * 64, "sha256": "2" * 64})
    ).feedback["FB-001"]
    assert item.sha256 == "1" * 64 and item.status == "taken" and item.changed_sha256 == "2" * 64


def test_addressed_and_not_addressed_carry_their_evidence():
    """L4-FBK-007: the judge's answer per item."""
    got = state(
        taken("FB-001"),
        taken("FB-002"),
        ("feedback.addressed", {"id": "FB-001", "round": 2, "sha": "abc123", "evidence": "extracted helper"}),
        ("feedback.not_addressed", {"id": "FB-002", "round": 2, "evidence": "still duplicated"}),
    ).feedback
    assert (got["FB-001"].status, got["FB-001"].sha, got["FB-001"].evidence) == (
        "addressed",
        "abc123",
        "extracted helper",
    )
    assert (got["FB-002"].status, got["FB-002"].evidence, got["FB-002"].sha256) == (
        "not_addressed",
        "still duplicated",
        "a" * 64,
    )


def test_withdrawn_invalid_and_waiting():
    got = state(
        taken("FB-001"),
        ("feedback.withdrawn", {"id": "FB-001"}),
        ("feedback.invalid", {"id": "FB-002", "problem": "the place is not in the diff"}),
        ("feedback.waiting", {"ids": ["FB-003", "FB-004"], "reason": "fix_unit_full"}),
    ).feedback
    assert got["FB-001"].status == "withdrawn" and got["FB-001"].sha256 == "a" * 64
    assert (got["FB-002"].status, got["FB-002"].problem) == ("invalid", "the place is not in the diff")
    assert {i: (got[i].status, got[i].reason) for i in ("FB-003", "FB-004")} == {
        "FB-003": ("waiting", "fix_unit_full"),
        "FB-004": ("waiting", "fix_unit_full"),
    }


def test_a_malformed_feedback_event_is_ignored():
    assert (
        state(
            ("feedback.taken", {"kind": "refactor"}),
            ("feedback.waiting", {"ids": "FB-001"}),
            ("feedback.addressed", {"id": 7}),
        ).feedback
        == {}
    )


def test_feedback_rounds_used_counts_only_feedback_only_fix_units():
    """D8: a feedback fix unit is counted apart; `feedback_only` absent is false."""
    got = state(
        ("fix.spawned", {"fix_unit": "p-fix-1", "round": 1}),
        ("fix.spawned", {"fix_unit": "p-fix-2", "round": 2, "feedback_only": True}),
        ("fix.spawned", {"fix_unit": "p-fix-3", "round": 3, "feedback_only": False}),
        ("fix.spawned", {"fix_unit": "p-fix-4", "round": 4, "feedback_only": True}),
    )
    assert got.feedback_rounds_used == 2 and got.fix_round == 4


def test_feedback_extensions_add_up_apart_from_fix_round_extensions():
    got = state(
        ("budget.extended", {"feedback_rounds": 1, "by": "member", "signal": "label:7"}),
        ("budget.extended", {"fix_rounds": 4, "by": "human", "reason": "more"}),
        ("budget.extended", {"feedback_rounds": 2, "by": "human", "reason": "more"}),
        ("budget.extended", {"feedback_rounds": True}),
        ("budget.extended", {"feedback_rounds": -1}),
        ("budget.extended", {"feedback_rounds": "3"}),
    )
    assert (got.feedback_rounds_extra, got.fix_rounds_extra) == (3, 4)


def test_feedback_round_limit_and_rounds_left():
    cfg = L4Config.model_validate({"version": 1, "feedback": {"max_rounds": 2}})
    base = state(("fix.spawned", {"fix_unit": "p-fix-1", "round": 1, "feedback_only": True}))
    assert (feedback_round_limit(cfg, base), feedback_rounds_left(cfg, base)) == (2, 1)
    more = state(
        ("fix.spawned", {"fix_unit": "p-fix-1", "round": 1, "feedback_only": True}),
        ("fix.spawned", {"fix_unit": "p-fix-2", "round": 2, "feedback_only": True}),
        ("fix.spawned", {"fix_unit": "p-fix-3", "round": 3, "feedback_only": True}),
        ("budget.extended", {"feedback_rounds": 1}),
    )
    assert (feedback_round_limit(cfg, more), feedback_rounds_left(cfg, more)) == (3, 0)  # never negative: 3 used of 3
    assert feedback_round_limit(L4Config.model_validate({"version": 1}), base) == 5


def test_the_halt_reason_names_the_feedback_limit():
    """The escalation reason later work records on `phase.changed{to: escalated, reason}` is read from halt_reason."""
    got = state(("phase.changed", {"from": "verifying", "to": "escalated", "reason": FEEDBACK_ROUNDS_EXHAUSTED}))
    assert got.halt_reason == FEEDBACK_ROUNDS_EXHAUSTED == "feedback_rounds_exhausted"
