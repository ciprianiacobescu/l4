"""L4-VER-069: step 3 records why each test failed and in which gate, as `failures` in the round's verdict."""

import json

from l4.gates.junit import TestCase, TestReport, failure_kind
from l4.redact import Redactor
from l4.verifier.evidence import VERDICT_SCHEMA_ID, read_verdict, restore_round
from l4.verifier.gates import MAX_FAILURE_CHARS, failure_records
from l4.verifier.report import verdict_json
from l4.verifier.types import Verdict, VerifyResult

from .test_report import BASE, HEAD

TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2"
E2E_ID, UNIT_ID = "e2e.test_a::test_x", "tests.test_b::test_y"


def case(test_id: str, status: str, message: str = "") -> TestCase:
    return TestCase(test_id, status, message, failure_kind=failure_kind(status, message))  # type: ignore[arg-type]


def test_the_kind_and_gate_of_a_failing_browser_test_are_recorded():  # SCN-VER-254
    unit = TestReport(
        {UNIT_ID: case(UNIT_ID, "failed", "assert 1 == 2"), "tests.test_b::ok": case("tests.test_b::ok", "passed")}
    )
    e2e = TestReport(
        {E2E_ID: case(E2E_ID, "failed", f"TypeError: value must be a string or regular expression\nmore {TOKEN}")}
    )
    records = failure_records(unit, e2e, Redactor({}).redact_text)
    assert records == {
        UNIT_ID: {"gate": "test", "kind": "assertion", "message": "assert 1 == 2"},
        E2E_ID: {"gate": "e2e", "kind": "other", "message": "TypeError: value must be a string or regular expression"},
    }  # passed and skipped tests have no record, only the first line of a message is kept


def test_a_token_in_the_first_line_is_redacted_and_the_line_is_capped():
    long = f"Error: token {TOKEN} " + "x" * 400
    records = failure_records(None, TestReport({E2E_ID: case(E2E_ID, "error", long)}), Redactor({}).redact_text)
    message = records[E2E_ID]["message"]
    assert TOKEN not in message and len(message) <= MAX_FAILURE_CHARS and message.startswith("Error: token ")


def test_an_error_without_a_kind_is_recorded_as_error_and_a_failure_without_one_as_other():
    reports = TestReport({"a::e": TestCase("a::e", "error", "boom"), "a::f": TestCase("a::f", "failed", "")})
    records = failure_records(reports, None, str)
    assert (records["a::e"]["kind"], records["a::f"]["kind"]) == ("error", "other")


def test_no_report_and_no_failure_record_nothing():
    assert failure_records(None, None, str) == {}
    assert failure_records(TestReport({"t::ok": case("t::ok", "passed")}), TestReport(), str) == {}


def test_the_e2e_record_wins_for_an_id_both_gates_report():
    both = TestReport({"x::t": case("x::t", "failed", "assert 0")})
    assert failure_records(both, both, str)["x::t"]["gate"] == "e2e"


def test_verdict_json_holds_the_failures_and_the_tests_map_keeps_its_form():
    failures = {E2E_ID: {"gate": "e2e", "kind": "other", "message": "TypeError: x"}}
    result = VerifyResult("openspec:x", 1, Verdict.FAIL, BASE, HEAD, tests={E2E_ID: "failed"}, failures=failures)
    body = verdict_json(result)
    assert body["failures"] == failures and body["tests"] == {E2E_ID: "failed"}
    assert json.loads(json.dumps(body)) == body
    assert verdict_json(VerifyResult("openspec:x", 1, Verdict.PASS, BASE, HEAD))["failures"] == {}


def test_a_verdict_without_failures_is_still_read(tmp_path):
    folder = tmp_path / ".l4" / "evidence" / "round-1"
    folder.mkdir(parents=True)
    (folder / "verdict.json").write_text(
        json.dumps({"schema": VERDICT_SCHEMA_ID, "round": 1, "tests": {"a::b": "failed"}})
    )
    old = read_verdict(tmp_path, 1)
    assert old is not None and old.get("failures") is None and old["tests"] == {"a::b": "failed"}
    (folder / "verdict.json").write_text(
        json.dumps({"schema": VERDICT_SCHEMA_ID, "failures": {"a::b": {"gate": "e2e"}}})
    )
    assert read_verdict(tmp_path, 1)["failures"] == {"a::b": {"gate": "e2e"}}  # type: ignore[index]


def test_a_reused_round_keeps_the_failures_and_an_old_one_has_none():
    failures = {E2E_ID: {"gate": "e2e", "kind": "other", "message": "TypeError: x"}}
    stored = json.loads(
        json.dumps(verdict_json(VerifyResult("openspec:x", 1, Verdict.FAIL, BASE, HEAD, failures=failures)))
    )
    assert restore_round(stored, "openspec:x", 2).failures == failures
    del stored["failures"]
    assert restore_round(stored, "openspec:x", 2).failures == {}
