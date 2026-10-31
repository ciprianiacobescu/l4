"""Which tests a stored round's findings are about (L4-VER-069), from its `failures` map and its findings: the leaf
of the fix unit's task grouping (`fixunit`) and of the fix chore's browser-test gate (`tdd.run_single`). Plain data in,
plain data out: it imports nothing of the harness, so both can use it."""

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

GATE_FINDING_GATES = {"test gate failed": "test", "e2e gate failed": "e2e"}  # title -> the gate whose tests it names
TESTS_RAN_TITLES = ("new tests failed", "new tests errored")  # `check_tests_ran`: the new tests that did not pass
COLLECTION_KIND = "collection"  # the `kind` of a module the gate could not collect
_CUT_LIST = re.compile(r" and \d+ more$")


def failing_ids(failures: Any, gate: str) -> set[str]:
    """The test ids a round's `failures` map (L4-VER-069) holds for `gate`; none for a verdict that predates the map. A
    module that failed to collect (kind `collection`) is no test id: no report holds it."""
    if not isinstance(failures, Mapping):
        return set()
    return {
        str(i)
        for i, record in failures.items()
        if isinstance(record, Mapping) and record.get("gate") == gate and record.get("kind") != COLLECTION_KIND
    }


def named_known_ids(detail: str, known: Collection[str]) -> tuple[set[str], bool]:
    """The ids of `known` that a `new tests failed` / `new tests errored` finding names in its detail
    (`testsran._named`: up to five, sorted, joined with `, `, then ` and <n> more`), and whether the detail is wholly
    those ids: the list was not cut and every item matched. An id is matched whole, anchored on the start or a `, `
    before it and the end or a `, ` after it, so an id that holds a comma is no two ids."""
    cut = _CUT_LIST.search(detail)
    body = detail[: cut.start()] if cut else detail
    longest_first = sorted(known, key=len, reverse=True)
    found: set[str] = set()
    pos = 0
    while pos < len(body):
        hit = next(
            (
                k
                for k in longest_first
                if body.startswith(k, pos) and (pos + len(k) == len(body) or body.startswith(", ", pos + len(k)))
            ),
            None,
        )
        if hit is None:
            return found, False
        found.add(hit)
        pos += len(hit) + 2
    return found, cut is None


def finding_test_ids(title: str, detail: str, failures: Any, dropped: int = 0) -> set[str] | None:
    """The test ids a gate finding fails on, or None when they are not known whole (own-test-repair, L4-IMP-091): the
    finding `test gate failed` / `e2e gate failed` fails on every test its gate recorded, and not whole when the gate
    also holds a module that did not collect or (the unit gate) the round cut its records; a `new tests failed` /
    `new tests errored` finding fails on the ids it names, and not whole when its list was cut or does not match. Any
    other finding, or a verdict that predates the `failures` map, gives None."""
    if not isinstance(failures, Mapping):
        return None
    records = {str(i): r for i, r in failures.items() if isinstance(r, Mapping)}
    if (gate := GATE_FINDING_GATES.get(title)) is not None:
        in_gate = {i for i, r in records.items() if r.get("gate") == gate}
        collected = {i for i in in_gate if records[i].get("kind") == COLLECTION_KIND}
        return in_gate if in_gate and not collected and not (gate == "test" and dropped) else None
    if title in TESTS_RAN_TITLES:
        named, whole = named_known_ids(detail, {i for i, r in records.items() if r.get("kind") != COLLECTION_KIND})
        return named if named and whole else None
    return None


def e2e_ids_of(verdict: Mapping[str, Any] | None, finding_ids: Sequence[str]) -> list[str]:
    """L4-IMP-090: the e2e tests a fix task's findings are about, from the round that spawned the fix unit: all the ids
    the round recorded under the e2e gate for the finding `e2e gate failed`; for a `new tests failed` / `new tests
    errored` finding those of them it names, and all of them when its list is cut or cannot be matched wholly (too many
    is safe, too few is the hole). Sorted; empty for a task that is not about the e2e gate."""
    failures = (verdict or {}).get("failures")
    e2e, unit = failing_ids(failures, "e2e"), failing_ids(failures, "test")
    found: set[str] = set()
    for stored in (verdict or {}).get("findings") or []:
        if not isinstance(stored, dict) or stored.get("id") not in finding_ids:
            continue
        if GATE_FINDING_GATES.get(stored.get("title")) == "e2e":
            found |= e2e
        elif stored.get("title") in TESTS_RAN_TITLES:
            named, whole = named_known_ids(str(stored.get("detail") or ""), e2e | unit)
            found |= e2e & named if whole and named else e2e
    return sorted(found)
