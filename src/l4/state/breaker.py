"""The verifier's circuit breaker (L4-VER-010, HB-9), counted from the ledger and from nothing else."""

from collections.abc import Iterable

from l4.state.ledger import LedgerEvent

LIMIT = 3  # consecutive internal verifier errors on one unit before it is escalated


def consecutive_verifier_errors(events: Iterable[LedgerEvent]) -> int:
    """The `verify.error` events at the end of the ledger, in order. A verdict (`verify.verdict`) or any phase change
    ends the streak: the verifier answered, or the unit moved on, so the errors before it say nothing about the next
    try. Other events (a run starting or finishing, a push) neither add nor reset."""
    streak = 0
    for event in events:
        if event.type == "verify.error":
            streak += 1
        elif event.type in ("verify.verdict", "phase.changed"):
            streak = 0
    return streak
