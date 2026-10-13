"""Which criteria an e2e test traces, for step 5's targets: the rule is M1.3's `trace_ids` (the `l4` marker, or
`C-<hex>`, `C_<hex>`, `c_<hex>` in any case in the test id), applied to the e2e report only. A unit test never covers
a UI criterion for step 5, which is why this reads the e2e report alone.
"""

from collections.abc import Sequence

from l4.gates.junit import TestReport
from l4.specs.base import Criterion
from l4.specs.criteria import trace_ids


def e2e_coverage(
    criteria: Sequence[Criterion], report: TestReport | None, *, max_criteria_per_test: int = 3
) -> dict[str, list[str]]:
    """criterion id -> ids of the e2e tests that trace it, for the covered criteria only. A skipped test traces
    nothing (it did not run), and a test that traces more than `max_criteria_per_test` criteria counts for none: one
    test that mentions everything proves nothing about any of them."""
    known = {c.id for c in criteria}
    covered: dict[str, list[str]] = {}
    for case in report.tests.values() if report else ():
        if case.status == "skipped":
            continue
        traced = trace_ids(case) & known
        if not traced or len(traced) > max_criteria_per_test:
            continue
        for criterion_id in sorted(traced):
            covered.setdefault(criterion_id, []).append(case.id)
    return covered


def trace_e2e(
    criteria: Sequence[Criterion], report: TestReport | None, *, max_criteria_per_test: int = 3
) -> list[Criterion]:
    """The criteria no e2e test traces, in the order given: what step 5 has to write tests for."""
    covered = e2e_coverage(criteria, report, max_criteria_per_test=max_criteria_per_test)
    return [c for c in criteria if c.id not in covered]
