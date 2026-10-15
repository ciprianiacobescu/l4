import sys
import time
from pathlib import Path

import pytest

from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateSpec, judge_test_gate, run_gate
from l4.redact import Redactor
from l4.sandbox.base import SandboxSpec
from l4.sandbox.none import NoSandbox

HOST = {"PATH": "/usr/bin:/bin", "HOME": "/home/u", "L4_FORGE_TOKEN": "glpat-supersecretvalue123456"}


def passed(*ids: str) -> TestReport:
    return TestReport({i: TestCase(i, "passed") for i in ids})


@pytest.fixture
def work(tmp_path: Path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "tmp").mkdir()
    spec = SandboxSpec("gate", tmp_path / "wt", tmp_path / "git", tmp_path / "tmp", tmp_path / "home")
    return tmp_path, spec


def go(work, spec: GateSpec, **kw):
    tmp, sandbox_spec = work
    return run_gate(
        spec, worktree=tmp / "wt", sandbox=NoSandbox(allow_none=True), sandbox_spec=sandbox_spec, host_env=HOST,
        log_path=tmp / "logs" / f"{spec.name}.log", redactor=kw.pop("redactor", Redactor({})), **kw,
    )  # fmt: skip


def test_zero_tests_and_missing_report_fail():
    assert judge_test_gate(0, passed("a::b")) == (True, "")
    assert judge_test_gate(1, passed("a::b")) == (False, "exit code 1")
    assert judge_test_gate(0, None) == (False, "report missing")
    assert judge_test_gate(0, TestReport()) == (False, "vacuous: 0 tests executed")
    skipped = TestReport({"a::b": TestCase("a::b", "skipped")})
    assert judge_test_gate(0, skipped) == (False, "vacuous: 0 tests executed")
    assert judge_test_gate(0, passed("a::b"), {"a::b", "a::c"}) == (False, "expected tests missing: a::c")
    assert judge_test_gate(1, None) == (False, "exit code 1")  # the exit code is judged first


def test_hanging_command_is_killed_and_log_kept(work):
    started = time.monotonic()
    result = go(work, GateSpec("hang", "sh -c 'echo started; sleep 60'", timeout_s=1))
    assert time.monotonic() - started < 20
    assert (result.status, result.timed_out) == ("fail", True)
    assert "timed out after 1s" in result.reason
    assert "started" in result.log_path.read_text()


def test_a_passing_command_without_reports_passes_on_its_exit_code(work):
    assert go(work, GateSpec("setup", "true")).status == "pass"
    failing = go(work, GateSpec("lint", "false"))
    assert (failing.status, failing.exit_code, failing.reason) == ("fail", 1, "exit code 1")


def test_a_test_gate_parses_the_report_even_when_tests_fail(work):
    tmp, _ = work
    (tmp / "wt" / "test_a.py").write_text("def test_ok():\n    pass\n\ndef test_bad():\n    assert 1 == 2\n")
    cmd = f"{sys.executable} -m pytest -p no:cacheprovider -o junit_family=xunit1 --junitxml=.l4-out/junit.xml"
    result = go(work, GateSpec("test", cmd, reports=(".l4-out/junit.xml",)))
    assert (result.status, result.exit_code, result.reason) == ("fail", 1, "exit code 1")
    assert result.report is not None
    assert {i: c.status for i, c in result.report.tests.items()} == {
        "test_a::test_ok": "passed",
        "test_a::test_bad": "failed",
    }


def test_a_stale_report_never_stands_in_for_a_missing_one(work):
    tmp, _ = work
    stale = tmp / "wt" / ".l4-out" / "junit.xml"
    stale.parent.mkdir()
    stale.write_text('<testsuite><testcase name="old"/></testsuite>')
    result = go(work, GateSpec("test", "true", reports=(".l4-out/junit.xml",)))
    assert (result.status, result.report, result.reason) == ("fail", None, "report missing: .l4-out/junit.xml")


def test_an_unreadable_report_fails_the_gate(work):
    cmd = f"{sys.executable} -c \"import pathlib; pathlib.Path('r.xml').write_text('<nope/>')\""
    result = go(work, GateSpec("test", cmd, reports=("r.xml",)))
    assert result.status == "fail" and result.reason.startswith("report unreadable")


def test_the_gate_sees_the_allow_listed_environment_only_and_the_log_is_redacted(work):
    result = go(
        work,
        GateSpec("env", "sh -c 'env; echo ghp_abcdefghijklmnopqrstuvwx'"),
        redactor=Redactor({"T": "supersecretvalue"}),
    )
    text = result.log_path.read_text()
    assert "L4_FORGE_TOKEN" not in text and "glpat-" not in text
    assert "ghp_abcdefghijklmnopqrstuvwx" not in text and "[REDACTED:github-token]" in text
    assert "TMPDIR=" in text


@pytest.mark.parametrize("report", ["/etc/passwd", "../x.xml", ""])
def test_a_report_path_outside_the_worktree_is_refused(work, report: str):
    with pytest.raises(ValueError, match="report path"):
        go(work, GateSpec("test", "true", reports=(report,)))


def test_a_command_that_cannot_start_or_parse_fails_cleanly(work):
    assert "cannot start" in go(work, GateSpec("x", "/no/such/binary --flag")).reason
    assert "cannot be parsed" in go(work, GateSpec("x", "echo 'unterminated")).reason
    assert go(work, GateSpec("x", "")).reason == "no command configured"


TRACE_ENV = {"PYTEST_ADDOPTS": "-p l4_trace"}


class _NoRun:
    def run(self, *args, **kwargs):
        raise AssertionError("no process may start")


@pytest.mark.parametrize(
    ("relative", "name"),
    [("l4_trace.py", "l4_trace"), ("l4_cov/__init__.py", "l4_cov")],
)
def test_a_root_module_with_a_plugin_name_stops_the_gate(work, relative, name):
    tmp, _ = work
    target = tmp / "wt" / relative
    target.parent.mkdir(exist_ok=True)
    target.write_text("")
    addopts = "-p l4_trace" if name == "l4_trace" else "-p l4_cov"
    result = go(work, GateSpec("test", "true"), runner=_NoRun(), extra_env={"PYTEST_ADDOPTS": addopts})
    assert result.status == "fail" and result.exit_code is None
    assert relative.split("/")[0] in result.reason and name in result.reason
    assert result.reason in result.log_path.read_text()


def test_a_nested_module_or_a_root_coverage_py_is_no_shadow(work):
    tmp, _ = work
    (tmp / "wt" / "src" / "pkg").mkdir(parents=True)
    (tmp / "wt" / "src" / "pkg" / "l4_trace.py").write_text("")
    (tmp / "wt" / "coverage.py").write_text("")
    assert go(work, GateSpec("test", "true"), extra_env=TRACE_ENV).status == "pass"


def test_without_the_plugin_option_a_root_module_is_not_checked(work):
    tmp, _ = work
    (tmp / "wt" / "l4_trace.py").write_text("")
    assert go(work, GateSpec("test", "true")).status == "pass"


def test_gates_keep_their_import_path(work):
    from l4.sandbox.env import build_gate_env

    tmp, sandbox_spec = work
    assert "PYTHONSAFEPATH" not in build_gate_env(HOST, sandbox_spec, extra=TRACE_ENV)
    (tmp / "wt" / "scripts").mkdir()
    (tmp / "wt" / "scripts" / "helper.py").write_text("VALUE = 1\n")
    (tmp / "wt" / "scripts" / "check.py").write_text("import helper\nassert helper.VALUE == 1\n")
    result = go(work, GateSpec("lint", f"{sys.executable} scripts/check.py"), extra_env=TRACE_ENV)
    assert result.status == "pass", result.reason
