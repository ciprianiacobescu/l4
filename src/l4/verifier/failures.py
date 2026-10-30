"""Which tests a stored round's findings are about (L4-VER-069), from its `failures` map and its findings: the leaf
of the fix unit's task grouping (`fixunit`) and of the fix chore's browser-test gate (`tdd.run_single`). Plain data in,
plain data out: it imports nothing of the harness, so both can use it."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

GATE_FINDING_GATES = {"test gate failed": "test", "e2e gate failed": "e2e"}  # title -> the gate whose tests it names
TESTS_RAN_TITLES = ("new tests failed", "new tests errored")  # `check_tests_ran`: the new tests that did not pass
_CUT_LIST = re.compile(r" and \d+ more$")


def failing_ids(verdict: Mapping[str, Any] | None, gate: str) -> set[str]:
    """The test ids a stored round recorded as failed or errored in `gate` (`failures`, L4-VER-069); none for a verdict
    that predates the map."""
    failures = (verdict or {}).get("failures")
    if not isinstance(failures, dict):
        return set()
    return {str(i) for i, record in failures.items() if isinstance(record, dict) and record.get("gate") == gate}


def named_test_ids(detail: str) -> tuple[list[str], bool]:
    """The ids a `new tests failed` / `new tests errored` finding names in its detail (up to five, sorted, joined with
    `, `; `testsran._named`) and whether the list was cut (`and <n> more`): then the ids named are not all of them."""
    cut = _CUT_LIST.search(detail)
    body = detail[: cut.start()] if cut else detail
    return [i for i in body.split(", ") if i], cut is not None


def e2e_ids_of(verdict: Mapping[str, Any] | None, finding_ids: Sequence[str]) -> list[str]:
    """L4-IMP-090: the e2e tests a fix task's findings are about, from the round that spawned the fix unit: all the ids
    the round recorded under the e2e gate for the finding `e2e gate failed`, those of them a `new tests failed` /
    `new tests errored` finding names for that one. Sorted; empty for a task that is not about the e2e gate."""
    e2e = failing_ids(verdict, "e2e")
    found: set[str] = set()
    for stored in (verdict or {}).get("findings") or []:
        if not isinstance(stored, dict) or stored.get("id") not in finding_ids:
            continue
        if GATE_FINDING_GATES.get(stored.get("title")) == "e2e":
            found |= e2e
        elif stored.get("title") in TESTS_RAN_TITLES:
            found |= e2e & set(named_test_ids(str(stored.get("detail") or ""))[0])
    return sorted(found)
