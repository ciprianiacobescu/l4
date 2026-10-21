import sys

from l4.verifier.gates import run_build_gates, run_test_gate
from l4.verifier.types import Severity

WRITE_REPORT = (
    f"{sys.executable} -c \"import os; os.makedirs('.l4-out', exist_ok=True); "
    "open('.l4-out/junit.xml', 'w').write('<testsuites><testsuite tests=\\\"0\\\"/></testsuites>')\""
)


def test_lint_failure_is_blocker_with_log_link(make_bench):
    bench = make_bench([], lint=["sh -c 'echo E501 line too long; exit 1'"])
    out = run_build_gates(bench.wb)
    assert not out.ok
    [finding] = out.findings
    assert finding.severity is Severity.BLOCKER and finding.source == "deterministic" and finding.blocking
    assert finding.log and finding.log.startswith(".l4-out/gates/") and finding.log.endswith("lint.log")
    assert "E501 line too long" in (bench.wb.out_dir.parent / finding.log).read_text()
    assert [(g.name, g.status) for g in out.gates] == [("setup", "pass"), ("lint", "fail")]


def test_the_first_failing_gate_stops_the_step_and_later_gates_do_not_run(make_bench):
    bench = make_bench([], lint=["false", "echo second"], typecheck=["echo ty"])
    out = run_build_gates(bench.wb)
    assert [g.name for g in out.gates] == ["setup", "lint"]


def test_setup_build_lint_and_typecheck_run_in_that_order_and_all_pass(make_bench):
    bench = make_bench([], build=["echo build"], lint=["echo lint"], typecheck=["echo ty"])
    out = run_build_gates(bench.wb)
    assert out.ok and out.findings == []
    assert [g.name for g in out.gates] == ["setup", "build", "lint", "typecheck"]
    assert [e["name"] for e in bench.events("gate.finished")] == ["setup", "build", "lint", "typecheck"]


def test_a_setup_failure_is_a_blocker_finding_not_exit_3(make_bench):
    bench = make_bench([])
    bench.wb.cfg.gates.setup[:] = ["sh -c 'echo no network; exit 7'"]
    out = run_build_gates(bench.wb)
    assert not out.ok and out.findings[0].title.startswith("setup") and "exit code 7" in out.findings[0].detail


def test_the_real_test_gate_passes_and_reports_every_test(make_bench):
    bench = make_bench([])
    run_build_gates(bench.wb)
    out = run_test_gate(bench.wb, must_contain=())
    assert out.ok and out.findings == [] and out.report is not None and out.report.total >= 1
    assert out.gate.name == "test" and out.gate.status == "pass"


def test_zero_tests_executed_is_vacuous_fail(make_bench):
    bench = make_bench([], test={"command": WRITE_REPORT})
    out = run_test_gate(bench.wb, must_contain=())
    assert not out.ok
    [finding] = out.findings
    assert finding.severity is Severity.BLOCKER and "vacuous" in finding.detail and finding.log


def test_a_missing_report_fails(make_bench):
    bench = make_bench([], test={"command": "true"})
    out = run_test_gate(bench.wb, must_contain=())
    assert not out.ok and "report missing" in out.findings[0].detail


def test_a_new_test_that_did_not_run_fails_even_though_the_exit_code_is_zero(make_bench):
    bench = make_bench([])
    run_build_gates(bench.wb)
    out = run_test_gate(bench.wb, must_contain={"tests.test_discount::test_known_code"})
    assert not out.ok and "expected tests missing" in out.findings[0].detail


def test_failing_tests_are_named_in_the_finding(make_bench):
    bench = make_bench([])
    (bench.wb.worktree / "tests" / "test_broken.py").write_text("def test_broken():\n    assert 1 == 2\n")
    run_build_gates(bench.wb)
    out = run_test_gate(bench.wb, must_contain=())
    assert not out.ok and "test_broken" in out.findings[0].detail


def test_a_collection_error_fails_the_gate(make_bench):
    bench = make_bench([])
    (bench.wb.worktree / "tests" / "test_nomod.py").write_text("import not_a_module_xyz\n")
    run_build_gates(bench.wb)
    out = run_test_gate(bench.wb, must_contain=())
    assert not out.ok


def test_a_report_with_a_collection_failure_fails_even_when_the_command_exited_zero(make_bench):
    xml = (
        '<testsuites><testsuite tests="2"><testcase classname="t" name="test_ok"/>'
        '<testcase name="tests/test_bad.py"><error message="collection failure"/></testcase></testsuite></testsuites>'
    )
    bench = make_bench([], test={"command": "sh -c 'mkdir -p .l4-out && cp canned.xml .l4-out/junit.xml'"})
    (bench.wb.worktree / "canned.xml").write_text(xml)
    out = run_test_gate(bench.wb, must_contain=())
    assert not out.ok and "not collected" in out.findings[0].detail and "tests/test_bad.py" in out.findings[0].detail


def test_an_empty_reports_list_cannot_pass_the_test_gate_on_the_exit_code_alone(make_bench):
    bench = make_bench([], test={"command": "true", "reports": []})
    out = run_test_gate(bench.wb, must_contain=("tests.test_discount::test_known_code",))
    assert not out.ok and out.gate.status == "fail"
    [finding] = out.findings
    assert finding.severity is Severity.BLOCKER and "gates.test.reports is empty" in finding.detail

