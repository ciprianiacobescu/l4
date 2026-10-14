"""L4-OPS-015: which cited criteria the red step of a reopened task need not write a new test for."""

from types import SimpleNamespace

from l4.gates.junit import TestCase
from l4.implementer import tdd
from l4.state.ledger import LedgerEvent

from ..verifier._integrity_helpers import STAMP, UNIT

OLD, NEW, KEPT = "C-00000001", "C-00000002", "C-00000003"


def ev(seq: int, kind: str, **data: object) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", UNIT, seq, kind, data)


def reopened(**over: object) -> LedgerEvent:
    change = {"requirement": "1.2", "old_id": OLD, "new_id": NEW}
    return ev(2, "tasks.reopened", tasks=["1.1"], requirements=["1.2"], stale_criteria=[OLD], changes=[change], **over)


def base():
    tests = {
        "t::test_old": TestCase("t::test_old", "passed", criteria=(OLD,)),
        "t::test_kept": TestCase("t::test_kept", "passed", criteria=(KEPT,)),
    }
    return SimpleNamespace(tests=tests)


def unchanged(monkeypatch, events: list[LedgerEvent]) -> frozenset[str]:
    monkeypatch.setattr(tdd, "_ledger_events", lambda wb: events)
    return tdd.unchanged_criteria(None, SimpleNamespace(key="1.1"), base())


def test_a_reopened_task_exempts_the_criteria_whose_tests_exist_less_the_changed_new_id(monkeypatch):
    assert unchanged(monkeypatch, [ev(1, "task.done", task="1.1"), reopened()]) == {OLD, KEPT}  # OLD is replaced


def test_a_task_nothing_reopened_exempts_nothing(monkeypatch):
    assert unchanged(monkeypatch, [ev(1, "task.done", task="1.1")]) == frozenset()


def test_a_reopened_task_that_is_done_again_exempts_nothing(monkeypatch):
    assert unchanged(monkeypatch, [reopened(), ev(3, "task.done", task="1.1")]) == frozenset()
