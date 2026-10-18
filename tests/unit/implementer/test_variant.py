"""The classifier of a variant run against the real run (L4-IMP-060, SCN-IMP-300): per test, a proof, no proof or
inconclusive; per criterion, confirmed, refuted or inconclusive."""

from pathlib import Path

from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import variant
from l4.implementer.variant import classify, judge
from l4.redact import Redactor

TRACE = (
    "src/pytdd/store.py:12: in <module>\n    class Store:\n"
    'src/pytdd/store.py:14: in Store\n    @telemetry.traced("store.add")\n     ^^^^^^^^^^^^^^^^^^^^^^^^^^^\n'
    "E   TypeError: 'NoneType' object is not callable\n"
)
NAME = "test-presatisfied"
OWN = frozenset({"tests/test_spans.py"})
T1, T2 = "tests.test_spans::test_one", "tests.test_spans::test_two"
CANDIDATES = {"C-aaaaaaaa": (T1, T2)}


def passed(test_id: str) -> TestCase:
    return TestCase(test_id, "passed")


def assertion(test_id: str) -> TestCase:
    return TestCase(test_id, "failed", "assert 1 == 2", failure_kind="assertion")


def real_report(*ids: str) -> TestReport:
    return TestReport({i: passed(i) for i in ids})


def gate(tmp_path: Path, report: TestReport | None, *, exit_code: int = 1, reason: str = "") -> GateResult:
    log = tmp_path / "gate.log"
    log.write_text("", encoding="utf-8")
    return GateResult(NAME, "fail", reason or f"exit code {exit_code}", exit_code, log, report)


def run_of(tmp_path: Path, report: TestReport | None, real: TestReport | None, **kw):
    return classify(gate(tmp_path, report, **kw), real, redact=Redactor({}).redact_text)


def test_scn_imp_300_a_report_with_collection_errors_and_no_test_is_inconclusive(tmp_path):
    names = [f"tests.test_m{i}" for i in range(45)]
    report = TestReport({}, names, {n: "...\n" + TRACE for n in names})
    run = run_of(tmp_path, report, real_report(T1, T2), exit_code=2)
    result = judge(run, CANDIDATES, real_report(T1, T2), OWN)["C-aaaaaaaa"]
    assert result.state == "inconclusive"
    assert result.reason.startswith("the test-presatisfied run ran no test (exit 2, 45 collection errors)")
    assert result.reason.endswith("E   TypeError: 'NoneType' object is not callable")
    assert result.tests == (T1, T2)


def test_no_report_is_inconclusive_with_the_gate_reason(tmp_path):
    run = run_of(tmp_path, None, real_report(T1, T2), exit_code=2, reason="exit code 2")
    outcome, reason = variant.test_outcome(run, T1, real_report(T1, T2), OWN)
    assert outcome == "inconclusive"
    assert reason.startswith("the test-presatisfied run wrote no readable report (exit code 2)")


def test_a_missing_test_is_inconclusive_and_names_the_new_collection_error(tmp_path):
    report = TestReport({T2: assertion(T2)}, ["tests.test_other"], {"tests.test_other": TRACE})
    run = run_of(tmp_path, report, real_report(T1, T2))
    assert run.new_errors == ("tests.test_other",)
    outcome, reason = variant.test_outcome(run, T1, real_report(T1, T2), OWN)
    assert outcome == "inconclusive"
    assert reason == f"{T1} did not run in {NAME}: E   TypeError: 'NoneType' object is not callable"


def test_a_test_that_ran_is_judged_on_its_own_result_beside_an_unrelated_collection_error(tmp_path):
    report = TestReport({T1: passed(T1), T2: assertion(T2)}, ["tests.test_other"], {"tests.test_other": TRACE})
    run = run_of(tmp_path, report, real_report(T1, T2))
    results = judge(run, {"C-aaaaaaaa": (T1,), "C-bbbbbbbb": (T2,)}, real_report(T1, T2), OWN)
    assert results["C-aaaaaaaa"].state == "refuted"
    assert results["C-bbbbbbbb"].state == "confirmed" and results["C-bbbbbbbb"].tests == (T2,)


def test_an_unrelated_collection_error_the_real_run_has_too_is_not_new(tmp_path):
    real = TestReport({T1: passed(T1)}, ["tests.test_other"], {"tests.test_other": TRACE})
    report = TestReport({T1: assertion(T1)}, ["tests.test_other"], {"tests.test_other": TRACE})
    assert run_of(tmp_path, report, real).new_errors == ()


def test_a_test_skipped_only_in_the_variant_is_inconclusive(tmp_path):
    skipped = TestCase(T1, "skipped")
    run = run_of(tmp_path, TestReport({T1: skipped, T2: assertion(T2)}), real_report(T1, T2))
    outcome, reason = variant.test_outcome(run, T1, real_report(T1, T2), OWN)
    assert (outcome, reason) == ("inconclusive", f"{T1} was skipped only in {NAME}")
    both = TestReport({T1: skipped, T2: passed(T2)})
    run = run_of(tmp_path, TestReport({T1: skipped, T2: assertion(T2)}), both)
    assert variant.test_outcome(run, T1, both, OWN) == ("none", "")


def setup_assertion(test_id: str, where: str) -> TestCase:
    detail = f">       assert telemetry.init(out) is True\nE       assert False is True\n\n{where}: AssertionError"
    return TestCase(test_id, "error", 'failed on setup with "assert False is True"', (), "assertion", detail, "setup")


def test_a_setup_assertion_in_the_units_file_is_a_proof_and_elsewhere_inconclusive(tmp_path):
    report = TestReport(
        {
            T1: setup_assertion(T1, "tests/test_spans.py:9"),
            T2: setup_assertion(T2, "tests/conftest.py:9"),
        }
    )
    run = run_of(tmp_path, report, real_report(T1, T2))
    assert variant.test_outcome(run, T1, real_report(T1, T2), OWN) == ("proof", "")
    outcome, reason = variant.test_outcome(run, T2, real_report(T1, T2), OWN)
    assert outcome == "inconclusive" and "tests/conftest.py:9" in reason


def test_an_error_of_another_kind_is_no_proof(tmp_path):
    call = TestCase(T1, "failed", "TypeError: x", (), "other", "")
    setup = TestCase(
        T2, "error", 'failed on setup with "RuntimeError: x"', (), "other", "tests/test_spans.py:9", "setup"
    )
    run = run_of(tmp_path, TestReport({T1: call, T2: setup}), real_report(T1, T2))
    assert variant.test_outcome(run, T1, real_report(T1, T2), OWN) == ("none", "")
    assert variant.test_outcome(run, T2, real_report(T1, T2), OWN) == ("none", "")


def test_the_reason_is_bounded_and_redacted(tmp_path):
    secret = "glpat-" + "x" * 20
    names = ["tests.test_m"]
    report = TestReport({}, names, {"tests.test_m": f"E   RuntimeError: {secret} " + "y" * 600})
    run = run_of(tmp_path, report, real_report(T1), exit_code=2)
    result = judge(run, {"C-aaaaaaaa": (T1,)}, real_report(T1), OWN)["C-aaaaaaaa"]
    assert secret not in result.reason and len(result.reason) <= 300
