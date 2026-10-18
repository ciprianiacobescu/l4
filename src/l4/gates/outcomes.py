"""The record of a pytest run against its JUnit report (detect-test-tamper, third review, item 2).

The harness's pytest plugin (`l4_trace`) appends one JSON line per test phase to a file the gate was given by
`L4_OUTCOME_FILE` (under the runner's gate-tmp, outside the worktree; the plugin drops the variable from its process
environment). Code that rewrites the JUnit report after pytest wrote it (an `atexit` hook, `os._exit`, a session-end
hook) cannot make the record agree: `altered` names the tests on which the two disagree. A runner without the plugin
leaves no record and is not checked (a documented limit)."""

import json
from collections.abc import Mapping
from pathlib import Path

from l4.gates.junit import TestReport

MAX_RECORD_BYTES = 64 * 1024 * 1024


def junit_id(nodeid: str) -> str:
    """`tests/test_a.py::TestC::test_m[x]` -> `tests.test_a.TestC::test_m[x]`, the id the JUnit parser builds."""
    parts = nodeid.split("::")
    module = parts[0].removesuffix(".py").replace("/", ".")
    if len(parts) == 1:
        return module
    return f"{'.'.join([module, *parts[1:-1]])}::{parts[-1]}"


def read_record(path: Path) -> dict[str, str] | None:
    """junit id -> `passed`, `failed` or `skipped`, from the last report of each phase; None when there is no record."""
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    phases: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("when"), str):
            phases.setdefault(junit_id(row["id"]), {})[row["when"]] = str(row.get("outcome", ""))
    final: dict[str, str] = {}
    for test_id, seen in phases.items():
        if "failed" in seen.values():
            final[test_id] = "failed"
        elif "skipped" in seen.values():
            final[test_id] = "skipped"
        elif seen.get("call") == "passed":
            final[test_id] = "passed"
    return final


def _by_name(record: Mapping[str, str], test_id: str) -> list[str]:
    tail = test_id.split("::")[-1]
    return [outcome for key, outcome in record.items() if key.split("::")[-1] == tail]


def altered(report: TestReport, record: Mapping[str, str] | None) -> list[str]:
    """The tests on which the JUnit report and the record disagree: a pass the record says was not one, and a failure
    the report no longer shows. Sorted. A JUnit id the conversion does not know is matched by its last name."""
    if record is None:
        return []
    bad: set[str] = set()
    for test_id, case in report.tests.items():
        if case.status != "passed":
            continue
        seen = record.get(test_id)
        outcomes = [seen] if seen is not None else _by_name(record, test_id)
        if any(o != "passed" for o in outcomes):  # no entry: a case another runner wrote into the file, not checked
            bad.add(test_id)
    for test_id, outcome in record.items():
        if outcome != "failed":
            continue
        case = report.tests.get(test_id)
        if case is not None:
            if case.status not in ("failed", "error"):
                bad.add(test_id)
        else:
            same = [c for i, c in report.tests.items() if i.split("::")[-1] == test_id.split("::")[-1]]
            if not same:
                bad.add(test_id)  # the testcase of a failure is gone from the report
            elif not any(c.status in ("failed", "error") for c in same) and not any(c.status == "passed" for c in same):
                bad.add(test_id)  # (a passed one is named by its own id above)
    return sorted(bad)
