"""The tests a unit's red steps added (`_red_green`, the gate's `must_contain` and `check_tests_ran`'s new tests) after
a reopened task's red step replaced stale tests (L4-OPS-015)."""

from l4.evidence.testsran import check_tests_ran
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import judge_test_gate
from l4.state.ledger import LedgerEvent
from l4.verifier.ladder import _red_green

SOON = "tests.test_priority.TestPickPrioritySoon::test_on_hand_at_reorder_point_returns_soon"
LOW = "tests.test_priority.TestPickPriorityLow::test_on_hand_at_reorder_point_returns_low"
KEPT = "tests.test_priority.TestPickPriorityKept::test_kept"


def ev(seq: int, kind: str, **data) -> LedgerEvent:
    return LedgerEvent(None, "run-a", "openspec:x", seq, kind, data)  # type: ignore[arg-type]


def two_cycles(*, superseded: bool = True, reopened: bool = True) -> list[LedgerEvent]:
    events = [ev(1, "task.red_ok", task="1.1", tests=[SOON, KEPT]), ev(2, "task.done", task="1.1")]
    if reopened:
        events.append(ev(3, "tasks.reopened", tasks=["1.1"], stale_criteria=["1.2"]))
    if superseded:
        events.append(ev(4, "tests.superseded", task="1.1", tests=[SOON], criteria=["1.2"]))
    events.append(ev(5, "task.red_ok", task="1.1", tests=[LOW]))
    return events


def report(*ids: str) -> TestReport:
    return TestReport({i: TestCase(i, "passed") for i in ids})


def test_superseded_tests_of_a_reopened_task_are_no_longer_expected():
    assert _red_green(two_cycles()) == {KEPT: "1.1", LOW: "1.1"}


def test_without_a_superseded_record_the_earlier_cycle_stays_expected():
    """Only `tests.superseded` releases a test: a reopened task whose red step dropped a test without that record
    (an unchanged criterion's test, say) keeps it expected, so the gate reports it."""
    assert _red_green(two_cycles(superseded=False)) == {SOON: "1.1", KEPT: "1.1", LOW: "1.1"}


def test_a_superseded_test_listed_again_by_the_later_cycle_stays_expected():
    events = two_cycles()
    events[-1] = ev(5, "task.red_ok", task="1.1", tests=[LOW, SOON])
    assert set(_red_green(events)) == {LOW, SOON, KEPT}


def test_a_unit_that_was_never_reopened_expects_every_red_test():
    events = two_cycles(superseded=False, reopened=False)
    assert _red_green(events) == {SOON: "1.1", KEPT: "1.1", LOW: "1.1"}


def test_a_reopen_of_another_task_replaces_nothing():
    events = two_cycles(superseded=False)
    events[2] = ev(3, "tasks.reopened", tasks=["2.1"])
    assert set(_red_green(events)) == {SOON, KEPT, LOW}


def test_a_red_test_that_vanishes_without_a_record_stays_a_blocker():
    events = [ev(1, "task.red_ok", task="1.1", tests=[SOON])]
    expected = set(_red_green(events))
    ok, reason = judge_test_gate(0, report(LOW), expected)
    assert not ok and "expected tests missing" in reason and SOON in reason
    out = check_tests_ran(report(LOW), expected, set(), gate_passed=True)
    assert [f.title for f in out.findings] == ["new tests did not run"]


def test_the_live_case_passes_the_gate_and_the_tests_ran_check():
    expected = set(_red_green(two_cycles()))
    now = report(LOW, KEPT)
    assert judge_test_gate(0, now, expected) == (True, "")
    out = check_tests_ran(now, expected, set(), gate_passed=True)
    assert out.findings == [] and out.label is True


def test_a_test_a_later_task_changed_in_place_stays_expected():  # L4-IMP-082
    """A `tests.superseded{reason: "named_by_task"}` lists a test that a later task's red step changed in place because
    its reviewed text named it: the test still exists, so the gate still expects it."""
    events = [
        ev(1, "task.red_ok", task="1.1", tests=[SOON, KEPT]),
        ev(2, "tests.superseded", task="1.2", tests=[SOON], criteria=[], reason="named_by_task", source="plan:p@abc"),
        ev(3, "task.red_ok", task="1.2", tests=[LOW]),
    ]
    assert _red_green(events) == {SOON: "1.1", KEPT: "1.1", LOW: "1.2"}
    events[1] = ev(2, "tests.superseded", task="1.2", tests=[SOON], criteria=["1.2"], reason="stale")
    assert _red_green(events) == {KEPT: "1.1", LOW: "1.2"}
