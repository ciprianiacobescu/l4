"""One classification of every variant run against the real run (SPEC L4-IMP-060, L4-IMP-002, L4-IMP-003).

A variant run is the test gate run again against changed production code: the zero-value runs, the base run, the run
at the red commit, the audit's run and the extra-proof runs. Each is judged against the real run, per test:

* a *proof*: the test failed by assertion (or errored by assertion in the setup of a fixture of the unit's own files);
* *no proof*: it passed, or failed or errored by another kind of error (an error shows the test touched the answer,
  not that it checked it);
* *inconclusive*: the run did not run it (no report, no test executed, the test absent from the report because its
  module failed to import only there, skipped only there, or a setup assertion in a file the unit did not write).

A criterion is confirmed when any of its tests is a proof, inconclusive when none is and any is inconclusive, and
refuted ("not discriminating") only when every test ran and none is a proof. Pure: no run is made here.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from l4.gates.collection import deepest_location, first_error_line
from l4.gates.junit import TestReport
from l4.gates.runner import GateResult

Outcome = Literal["proof", "none", "inconclusive"]
MAX_REASON = 300
_LOG_TAIL = 40_000


@dataclass(frozen=True)
class VariantRun:
    name: str
    report: TestReport | None
    reason: str = ""  # set only when the whole run is inconclusive
    new_errors: tuple[str, ...] = ()  # the collection errors the real run does not have, in report order


@dataclass(frozen=True)
class CriterionResult:
    state: Literal["confirmed", "refuted", "inconclusive"]
    tests: tuple[str, ...]
    reason: str = ""


def _bound(text: str, redact: Callable[[str], str] | None = None) -> str:
    """Redacted whole first (a cut must not split a secret the redactor would then miss), then cut."""
    return (redact(text) if redact else text)[:MAX_REASON]


def classify(gate: GateResult, real: TestReport | None, *, redact: Callable[[str], str]) -> VariantRun:
    name, report = gate.name, gate.report
    if report is None:
        reason = f"the {name} run wrote no readable report ({gate.reason})"
        try:
            tail = gate.log_path.read_text(encoding="utf-8", errors="replace")[-_LOG_TAIL:]
        except OSError:
            tail = ""
        if line := first_error_line(tail):
            reason += f": {line}"
        return VariantRun(name, None, _bound(reason, redact))
    known = set(real.collection_errors) if real is not None else set()
    new = tuple(e for e in report.collection_errors if e not in known)
    if report.executed == 0:
        reason = (
            f"the {name} run ran no test (exit {gate.exit_code}, {len(report.collection_errors)} collection errors)"
        )
        first = (new or tuple(report.collection_errors))[:1]
        if first and (line := first_error_line(report.collection_details.get(first[0], ""))):
            reason += f": {line}"
        return VariantRun(name, report, _bound(reason, redact), new)
    return VariantRun(name, report, "", new)


def test_outcome(
    run: VariantRun,
    test_id: str,
    real: TestReport | None,
    own_files: Collection[str],
    *,
    redact: Callable[[str], str] | None = None,
) -> tuple[Outcome, str]:
    if run.reason:
        return "inconclusive", run.reason
    assert run.report is not None
    case = run.report.tests.get(test_id)
    if case is None:
        reason = f"{test_id} did not run in {run.name}"
        if run.new_errors and (line := first_error_line(run.report.collection_details.get(run.new_errors[0], ""))):
            reason += f": {line}"
        return "inconclusive", _bound(reason, redact)
    if case.status == "skipped":
        before = real.tests.get(test_id) if real is not None else None
        if before is None or before.status != "skipped":
            return "inconclusive", _bound(f"{test_id} was skipped only in {run.name}", redact)
        return "none", ""
    if case.failure_kind != "assertion":
        return "none", ""
    if case.status == "failed":
        return "proof", ""
    if case.status == "error" and case.when == "setup":
        where = deepest_location(case.detail)
        if where is not None and where[0] in own_files:
            return "proof", ""
        shown = f"{where[0]}:{where[1]}" if where else "unknown location"
        reason = f"{test_id} failed by assertion in the setup of a fixture outside the unit's test files ({shown})"
        return "inconclusive", _bound(reason, redact)
    return "none", ""


def judge(
    run: VariantRun,
    candidates: Mapping[str, Sequence[str]],
    real: TestReport | None,
    own_files: Collection[str],
    *,
    redact: Callable[[str], str] | None = None,
) -> dict[str, CriterionResult]:
    results: dict[str, CriterionResult] = {}
    for criterion, tests in candidates.items():
        outcomes = [(t, *test_outcome(run, t, real, own_files, redact=redact)) for t in tests]
        proving = tuple(t for t, outcome, _ in outcomes if outcome == "proof")
        undecided = [(t, why) for t, outcome, why in outcomes if outcome == "inconclusive"]
        if proving:
            results[criterion] = CriterionResult("confirmed", proving)
        elif undecided:
            results[criterion] = CriterionResult("inconclusive", tuple(tests), undecided[0][1])
        else:
            results[criterion] = CriterionResult("refuted", tuple(tests))
    return results
