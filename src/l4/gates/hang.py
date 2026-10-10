"""The tests that hung in a gate run (W-D1, SPEC L4-GAT-004), read from what the `l4_trace` plugin leaves behind.

Two shapes: a JUnit failure whose message carries `l4-test-timeout:` (the soft limit; the failure body holds the
frame the test was waiting in), and an `L4_TEST_HANG: <nodeid>` line in the gate log with the threads' tracebacks after
it (the hard limit: the run ended without a report). Ids are returned in the report's own form, `classname::name`.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from l4.gates.junit import TestReport

TIMEOUT_MARKER = "l4-test-timeout:"  # the plugin's (`pytest_trace/l4_trace.py` imports nothing from l4)
HANG_MARKER = "L4_TEST_HANG: "
MAX_FRAME_LINES = 24
_LOG_HANG = re.compile(rf"^{re.escape(HANG_MARKER)}(\S+)[ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class HungTest:
    id: str
    frame: str  # where it was waiting, as pytest or faulthandler print it; "" when unknown


def junit_id(nodeid: str) -> str:
    """`tests/test_x.py::TestC::test_m[p]` -> `tests.test_x.TestC::test_m[p]` (what `parse_junit` calls the test)."""
    path, *rest = nodeid.split("::")
    if not rest:
        return nodeid
    module = path.removesuffix(".py").replace("/", ".")
    return f"{'.'.join([module, *rest[:-1]])}::{rest[-1]}"


def hung_tests(report: TestReport | None, log_text: str = "") -> list[HungTest]:
    found: dict[str, HungTest] = {}
    if report is not None:
        for test_id, case in report.tests.items():
            if case.status in ("failed", "error") and TIMEOUT_MARKER in case.message:
                found[test_id] = HungTest(test_id, case.detail.strip())
    for match in _LOG_HANG.finditer(log_text):
        test_id = junit_id(match.group(1))
        tail = log_text[match.end() :].lstrip("\n").splitlines()[:MAX_FRAME_LINES]
        found.setdefault(test_id, HungTest(test_id, "\n".join(tail)))
    return list(found.values())


def hung_ids(hung: list[HungTest]) -> list[str]:
    return [h.id for h in hung]


def frames(hung: list[HungTest]) -> Mapping[str, str]:
    return {h.id: h.frame for h in hung}
