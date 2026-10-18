"""detect-test-tamper (third review, item 2): the harness's pytest plugin records every test's outcome outside the
worktree, and a JUnit report that disagrees with the record is altered."""

import json
import subprocess
import sys
from pathlib import Path

from l4.gates.outcomes import altered, junit_id, read_record

from l4.gates.junit import TestCase, TestReport
from l4.gates.trace import trace_env

TESTS = (
    "def test_ok():\n    assert True\n\n\ndef test_bad():\n    assert False\n\n\n"
    "class TestC:\n    def test_m(self):\n        assert True\n"
)
SEEN = (
    "import os\n\n\ndef pytest_sessionfinish(session):\n"
    "    open('seen.txt', 'w').write(str('L4_OUTCOME_FILE' in os.environ))\n"
)


def run(tmp_path: Path, record: Path, extra_conftest: str = ""):
    (tmp_path / "test_x.py").write_text(TESTS)
    if extra_conftest:
        (tmp_path / "conftest.py").write_text(extra_conftest)
    env = {"PATH": "/usr/bin:/bin", **trace_env(), "L4_OUTCOME_FILE": str(record)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_x.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )  # fmt: skip


def test_the_plugin_records_each_tests_outcome_per_phase_and_hides_the_path(tmp_path):
    record = tmp_path.parent / f"{tmp_path.name}-record.jsonl"
    done = run(tmp_path, record, SEEN)
    assert done.returncode == 1
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert {(r["id"], r["when"], r["outcome"]) for r in rows} >= {
        ("test_x.py::test_ok", "call", "passed"),
        ("test_x.py::test_bad", "call", "failed"),
        ("test_x.py::TestC::test_m", "call", "passed"),
    }
    assert (tmp_path / "seen.txt").read_text() == "False"  # the conftest cannot read where the record is


def test_the_record_is_read_as_final_outcomes_with_junit_ids(tmp_path):
    record = tmp_path / "r.jsonl"
    lines = [
        {"id": "tests/test_a.py::test_ok", "when": "setup", "outcome": "passed"},
        {"id": "tests/test_a.py::test_ok", "when": "call", "outcome": "passed"},
        {"id": "tests/test_a.py::test_ok", "when": "teardown", "outcome": "passed"},
        {"id": "tests/test_a.py::TestC::test_m[x]", "when": "call", "outcome": "failed"},
        {"id": "tests/test_a.py::test_skip", "when": "setup", "outcome": "skipped"},
    ]
    record.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    assert read_record(record) == {
        "tests.test_a::test_ok": "passed",
        "tests.test_a.TestC::test_m[x]": "failed",
        "tests.test_a::test_skip": "skipped",
    }
    assert read_record(tmp_path / "missing.jsonl") is None
    assert junit_id("tests/test_a.py::TestC::test_m[x]") == "tests.test_a.TestC::test_m[x]"


def report(**statuses):
    return TestReport({k.replace("__", "::"): TestCase(k.replace("__", "::"), v) for k, v in statuses.items()})


def test_a_report_that_agrees_with_the_record_is_not_altered():
    record = {"a::t1": "passed", "a::t2": "failed", "a::t3": "skipped"}
    assert altered(report(a__t1="passed", a__t2="failed", a__t3="skipped"), record) == []
    assert altered(report(a__t1="passed", a__t2="error"), record) == []  # an error is a failure too


def test_a_failure_turned_into_a_pass_or_removed_is_altered_and_named():
    record = {"a::t1": "passed", "a::t2": "failed", "a::t3": "failed"}
    assert altered(report(a__t1="passed", a__t2="passed", a__t3="passed"), record) == ["a::t2", "a::t3"]
    assert altered(report(a__t1="passed"), record) == ["a::t2", "a::t3"]  # the testcase element was deleted


def test_a_case_the_record_does_not_know_is_not_checked():
    """A runner that wraps pytest may add cases of its own (Go, TypeScript) to the report; hiding a failure needs a
    record entry, which the other rule covers."""
    assert altered(report(a__t1="passed", a__other="passed"), {"a::t1": "passed"}) == []


def test_a_junit_id_the_conversion_does_not_know_is_matched_by_its_last_name():
    assert altered(report(**{"odd.layout::t1": "passed"}), {"tests.real::t1": "passed"}) == []
    assert altered(report(**{"odd.layout::t1": "passed"}), {"tests.real::t1": "failed"}) == ["odd.layout::t1"]


def test_no_record_means_no_check():
    assert altered(report(a__t1="passed"), None) == []
