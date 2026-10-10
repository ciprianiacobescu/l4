"""Step 3's end-to-end gate (plan line 33): judged on its JUnit report like the test gate, never vacuous."""

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.verifier.gates import e2e_gate_configured, run_e2e_gate

from .._web_helpers import PY, e2e_config, free_port, stage
from ..implementer.conftest import make_bench  # noqa: F401


@pytest.fixture
def bench(make_bench):  # noqa: F811
    bench = make_bench([], e2e=e2e_config(free_port()))
    stage(bench.wb.worktree)
    return bench


def test_a_passing_e2e_gate_returns_its_report_and_the_page_snapshot(bench):
    out = run_e2e_gate(bench.wb)
    assert out.ok and out.gate.name == "e2e" and out.gate.status == "pass"
    assert out.report is not None and out.report.executed == 1
    assert out.snapshot is not None and "items" in out.snapshot
    assert out.gate.log and out.gate.log.endswith("e2e.log")


def test_a_failing_e2e_test_is_a_deterministic_blocker_that_names_it(bench):
    (bench.wb.worktree / "e2e/test_broken.py").write_text("def test_broken():\n    assert False\n")
    out = run_e2e_gate(bench.wb)
    assert not out.ok and out.gate.status == "fail"
    (finding,) = out.findings
    assert (finding.severity.value, finding.source, finding.title) == ("blocker", "deterministic", "e2e gate failed")
    assert "test_broken" in finding.detail and finding.log == out.gate.log


def test_an_e2e_command_that_runs_no_test_is_vacuous_and_fails(bench):
    empty = "import pathlib; pathlib.Path('.l4-out/e2e.xml').write_text('<testsuites/>')"
    bench.wb.cfg.gates.e2e.command = f'{PY} -c "{empty}"'
    out = run_e2e_gate(bench.wb)
    assert not out.ok and "vacuous" in out.gate.reason and out.findings[0].title == "e2e gate failed"


def test_a_server_that_is_never_ready_is_an_internal_error_not_a_finding(bench):
    bench.wb.cfg.gates.e2e.serve.command = f"{PY} -c 'import time; time.sleep(120)'"
    bench.wb.cfg.gates.e2e.serve.timeout = "1s"
    with pytest.raises(L4Exit) as err:
        run_e2e_gate(bench.wb)
    assert err.value.code == ExitCode.INTERNAL_ERROR


def test_the_gate_is_configured_by_its_command_alone(bench):
    assert e2e_gate_configured(bench.wb.cfg)
    bench.wb.cfg.gates.e2e.command = " "
    assert not e2e_gate_configured(bench.wb.cfg)
