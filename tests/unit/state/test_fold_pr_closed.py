"""A closed then reopened MR returns the unit to the state it left, previous phase included (L4-OPS-009, review H2):
`abandoned` is a parking phase, so without the return state a retry after the reopen went to `abandoned` again."""

from datetime import UTC, datetime, timedelta

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent
from l4.state.lifecycle import Trigger, transition

T0 = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)


class Writer:
    def __init__(self, events: list[LedgerEvent], *, close_event: bool = True) -> None:
        self.events, self.close_event = events, close_event

    def append(self, type_: str, **data: object) -> None:
        self.events.append(
            LedgerEvent(T0 + timedelta(seconds=len(self.events)), "r1", "openspec:x", len(self.events), type_, data)
        )


class Unit:
    def __init__(self, phase: str, previous: str | None = None) -> None:
        self.events: list[LedgerEvent] = []
        self.writer = Writer(self.events)
        if previous is not None:
            self.writer.append("phase.changed", **{"from": None, "to": previous, "trigger": "seed"})
            self.writer.append("phase.changed", **{"from": previous, "to": phase, "trigger": "seed"})
        else:
            self.writer.append("phase.changed", **{"from": None, "to": phase, "trigger": "seed"})

    def state(self):
        return fold(self.events, "openspec:x")

    def go(self, trigger: Trigger, **ctx: object):
        transition(self.writer, self.state(), trigger, **ctx)
        return self.state()

    def close(self, *, event_fields: bool = False):
        if event_fields:  # a sweeper that writes the return state itself
            s = self.state()
            self.writer.append("pr.closed", number=7, from_phase=s.phase, from_previous=s.previous_phase)
        else:
            self.writer.append("pr.closed", number=7)
        return self.go(Trigger.PR_CLOSED, pr=7)


def test_escalated_closed_reopened_then_retry_goes_to_verifying():
    unit = Unit("escalated", previous="verifying")
    assert unit.close().phase == "abandoned"
    reopened = unit.go(Trigger.PR_REOPENED, pr=7)
    assert (reopened.phase, reopened.previous_phase) == ("escalated", "verifying")
    assert unit.go(Trigger.RESUMED).phase == "verifying"


def test_waiting_capacity_closed_reopened_then_capacity_restored_goes_to_the_original_phase():
    unit = Unit("waiting_capacity", previous="implementing")
    unit.close()
    reopened = unit.go(Trigger.PR_REOPENED, pr=7)
    assert (reopened.phase, reopened.previous_phase) == ("waiting_capacity", "implementing")
    assert unit.go(Trigger.CAPACITY_RESTORED).phase == "implementing"


def test_a_close_without_the_pr_closed_event_is_folded_the_same():
    unit = Unit("halted", previous="fixing")
    unit.go(Trigger.PR_CLOSED, pr=7)
    reopened = unit.go(Trigger.PR_REOPENED, pr=7)
    assert (reopened.phase, reopened.previous_phase) == ("halted", "fixing")


def test_the_event_may_carry_the_return_state_and_it_wins():
    unit = Unit("escalated", previous="verifying")
    unit.close(event_fields=True)
    reopened = unit.go(Trigger.PR_REOPENED, pr=7)
    assert (reopened.phase, reopened.previous_phase) == ("escalated", "verifying")


def test_an_explicit_return_state_in_the_event_is_used():
    unit = Unit("escalated", previous="verifying")
    unit.writer.append("pr.closed", number=7, from_phase="escalated", from_previous="implementing")
    unit.go(Trigger.PR_CLOSED, pr=7)
    assert unit.go(Trigger.PR_REOPENED, pr=7).previous_phase == "implementing"


def test_a_phase_that_does_not_park_closes_and_reopens_as_before():
    unit = Unit("in_review")
    assert unit.close().previous_phase == "in_review"
    reopened = unit.go(Trigger.PR_REOPENED, pr=7)
    assert (reopened.phase, reopened.previous_phase) == ("in_review", None)


def test_two_close_reopen_cycles_each_restore_their_own_state():
    unit = Unit("escalated", previous="verifying")
    for _ in range(2):
        unit.close()
        assert unit.go(Trigger.PR_REOPENED, pr=7).previous_phase == "verifying"
