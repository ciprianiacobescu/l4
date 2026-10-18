"""One classification of every variant run against the real run (SPEC L4-IMP-060, L4-IMP-002, L4-IMP-003).

A variant run is the test gate run again against changed production code: the zero-value runs, the base run, the run
at the red commit, the audit's run and the extra-proof runs. Each is judged against the real run, per test:

* a *proof*: the test failed by assertion (or errored by assertion in the setup of a fixture of the unit's own files);
* *no proof*: it passed, or failed or errored by another kind of error (an error shows the test touched the answer,
  not that it checked it);
* *inconclusive*: the run did not run it (no report, no test executed, the test absent from the report because a
  production module failed to import there, or a setup assertion in a file the unit did not write). In a zero-value
  run a test the unit's OWN files made unrunnable (it skipped itself, its test or support file raised at collection, a
  parametrize lost its id) is *no proof*, like a setup assertion in the unit's own fixture: an agent must not be able to
  turn "not discriminating" into "the check could not decide" by writing such a test.

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
        if line := first_error_line(redact(tail)):  # redacted whole first: a cut must not split a secret
            reason += f": {line}"
        return VariantRun(name, None, _bound(reason, redact))
    known = set(real.collection_errors) if real is not None else set()
    new = tuple(e for e in report.collection_errors if e not in known)
    if report.executed == 0:
        reason = (
            f"the {name} run ran no test (exit {gate.exit_code}, {len(report.collection_errors)} collection errors)"
        )
        first = (new or tuple(report.collection_errors))[:1]
        if first and (line := first_error_line(redact(report.collection_details.get(first[0], "")))):
            reason += f": {line}"
        return VariantRun(name, report, _bound(reason, redact), new)
    return VariantRun(name, report, "", new)


def _module_names(test_id: str) -> set[str]:
    """The dotted module names a test id can belong to (`tests.test_x.TestY::t` gives `tests`, `tests.test_x`,
    `tests.test_x.TestY`): a collection error is named by its module."""
    parts = test_id.split("::", 1)[0].split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def _error_name(name: str) -> str:
    return name.removesuffix(".py").replace("/", ".")


def _absent(
    run: VariantRun, test_id: str, own_files: Collection[str], zero_value: bool, redact: Callable[[str], str] | None
) -> tuple[Outcome, str]:
    """A test the variant's report lacks. In a zero-value run the cause decides: the unit's own file (a collection error
    whose deepest repository frame is a test or support file the unit wrote, or a module that collected but lost the
    id) is no proof; a production module that failed to import is inconclusive."""
    assert run.report is not None
    error = next((e for e in run.report.collection_errors if _error_name(e) in _module_names(test_id)), None)
    if zero_value:
        if error is None:
            return "none", ""  # the module collected and the id is gone: collection-time code read a production answer
        where = deepest_location(run.report.collection_details.get(error, ""))
        if where is not None and where[0] in own_files:
            return "none", ""
    if run.reason:
        return "inconclusive", run.reason  # the whole run ran nothing: its reason names the cause
    reason = f"{test_id} did not run in {run.name}"
    first = run.new_errors[0] if run.new_errors else error
    detail = run.report.collection_details.get(first, "") if first is not None else ""
    if line := first_error_line(redact(detail) if redact else detail):
        reason += f": {line}"
    return "inconclusive", _bound(reason, redact)


def test_outcome(
    run: VariantRun,
    test_id: str,
    real: TestReport | None,
    own_files: Collection[str],
    *,
    redact: Callable[[str], str] | None = None,
    zero_value: bool = True,
) -> tuple[Outcome, str]:
    """`zero_value`: the run varies production code (the zero-value runs). The base run only confirms and passes False:
    there a test it could not run stays inconclusive whatever the cause."""
    if run.report is None:
        return "inconclusive", run.reason
    case = run.report.tests.get(test_id)
    if case is None:
        return _absent(run, test_id, own_files, zero_value, redact)
    if case.status == "skipped":
        before = real.tests.get(test_id) if real is not None else None
        if before is not None and before.status == "skipped":
            return "none", ""
        if zero_value:  # a test that skips itself on the zero answer proves nothing, and is not the harness's doing
            return "none", ""
        return "inconclusive", _bound(f"{test_id} was skipped only in {run.name}", redact)
    if run.reason:
        return "inconclusive", run.reason
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
    zero_value: bool = True,
) -> dict[str, CriterionResult]:
    results: dict[str, CriterionResult] = {}
    for criterion, tests in candidates.items():
        outcomes = [(t, *test_outcome(run, t, real, own_files, redact=redact, zero_value=zero_value)) for t in tests]
        proving = tuple(t for t, outcome, _ in outcomes if outcome == "proof")
        undecided = [(t, why) for t, outcome, why in outcomes if outcome == "inconclusive"]
        if proving:
            results[criterion] = CriterionResult("confirmed", proving)
        elif undecided:
            results[criterion] = CriterionResult("inconclusive", tuple(tests), undecided[0][1])
        else:
            results[criterion] = CriterionResult("refuted", tuple(tests))
    return results
