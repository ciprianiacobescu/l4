"""detect-test-tamper (third review, item 2): the harness's pytest plugin records every test's outcome outside the
worktree, and a JUnit report that disagrees with the record is altered."""

import json
import subprocess
import sys
from pathlib import Path

from l4.gates.junit import TestCase, TestReport
from l4.gates.outcomes import altered, junit_id, read_record
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


# --- fourth review: fail closed, a closure instead of a module global, a failed row wins ------


def test_a_failed_row_wins_over_a_later_passed_row_of_the_same_phase(tmp_path):
    record = tmp_path / "r.jsonl"
    rows = [
        {"id": "t.py::test_a", "when": "call", "outcome": "failed"},
        {"id": "t.py::test_a", "when": "call", "outcome": "passed"},
        {"id": "t.py::test_b", "when": "setup", "outcome": "failed"},
        {"id": "t.py::test_b", "when": "setup", "outcome": "passed"},
        {"id": "t.py::test_b", "when": "call", "outcome": "passed"},
    ]
    record.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert read_record(record) == {"t::test_a": "failed", "t::test_b": "failed"}


def test_the_plugin_hides_its_descriptor_and_the_variable_from_a_conftest(tmp_path):
    record = tmp_path.parent / f"{tmp_path.name}-hidden.jsonl"
    probe = (
        "import os, sys\n"
        "plugin = sys.modules.get('l4_trace')\n"
        "seen = {'env': os.environ.get('L4_OUTCOME_FILE'),\n"
        "        'attrs': [n for n in dir(plugin) if 'OUTCOME' in n.upper() or n.lower().endswith('fd')]}\n"
        "open('seen.json', 'w').write(repr(seen))\n"
    )
    done = run(tmp_path, record, probe)
    assert done.returncode == 1
    assert (
        tmp_path / "seen.json"
    ).read_text() == "{'env': None, 'attrs': []}"  # the path and the descriptor are not reachable
    assert record.read_text().strip()  # and the record was still written


def fake_gate(tmp_path, command="python -m pytest -q"):
    from types import SimpleNamespace

    events = []
    fake = SimpleNamespace(emit=lambda kind, **data: events.append((kind, data)))
    spec = SimpleNamespace(name="test", command=command)
    result = SimpleNamespace(status="pass", reason="", report=report(a__t1="passed"))
    return fake, spec, result, events


def cross_check(tmp_path, record_text, command="python -m pytest -q"):
    import dataclasses

    from l4.gates.runner import GateResult
    from l4.implementer.workbench import Workbench

    fake, spec, _, events = fake_gate(tmp_path, command)
    result = GateResult("test", "pass", "", 0, tmp_path / "x.log", report(a__t1="passed"))
    record = tmp_path / "rec.jsonl"
    if record_text is not None:
        record.write_text(record_text)
    out = Workbench._cross_check(fake, spec, result, record)
    assert dataclasses.is_dataclass(out)
    return out, events


def test_a_pytest_gate_with_a_missing_or_empty_record_and_tests_in_the_report_is_altered(tmp_path):
    for text in (None, ""):
        out, events = cross_check(tmp_path, text)
        assert out.status == "fail" and out.report is None
        assert out.reason.startswith("the test report was altered (no outcome record)")
        assert events and events[0][0] == "guard.report_altered"


def test_a_runner_without_the_plugin_is_not_held_to_a_record(tmp_path):
    out, _ = cross_check(tmp_path, None, command=".venv/bin/python tools/fake_runner.py")
    assert out.status == "pass" and out.report is not None


def test_a_wrapper_command_whose_plugin_created_an_empty_record_is_altered(tmp_path):  # fifth review: `make test`
    out, events = cross_check(tmp_path, "", command="make test")
    assert out.status == "fail" and out.reason.startswith("the test report was altered (no outcome record)")
    assert events and events[0][0] == "guard.report_altered"


def test_a_wrapper_command_that_never_loaded_the_plugin_is_not_held_to_a_record(tmp_path):
    out, _ = cross_check(tmp_path, None, command="make test")  # no file: the plugin was never imported (Go, TypeScript)
    assert out.status == "pass" and out.report is not None
