# ruff: noqa: F811
"""gate-flake-rerun 1.3 (L4-VER-076, SCN-VER-288, 295, 297): step 3 through the ladder. Real git, a real pytest for the
test gate and a scripted e2e gate (`ladder.run_e2e_gate` replaced by a script keyed on the gate's name) on the
`py_multi` fixture of `test_ladder_evidence`; the repeat of the real e2e gate on a real bench."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.verifier import gate_repeat, gates, ladder
from l4.verifier.gates import E2eGateOutcome, TestGateOutcome
from l4.verifier.types import Finding, GateLine, Severity

from .._web_helpers import PY, e2e_config, free_port, stage
from ..implementer.conftest import make_bench  # noqa: F401
from .test_ladder_evidence import (  # noqa: F401  (fixtures and scripts)
    UNIT_DIR,
    evidence,
    green,
    judge,
    multi,
    red,
    report,
    run_multi,
    steps,
)

FLAKY_ID = "tests.test_stock::test_probe"  # tests/test_stock.py is in the base, and the unit does not change it
E2E_CONFIG = {
    "command": "true", "reports": [".l4-out/e2e.xml"], "format": "junit",
    "serve": {"command": "true", "ready_url": "http://127.0.0.1:9/"},
}  # fmt: skip
FLAKY_TITLE = "a pre-existing test is flaky in the e2e gate"


def with_e2e(body: dict) -> None:
    body.setdefault("gates", {})["e2e"] = E2E_CONFIG
    body["verifier"]["playwright"] = {"enabled": False}  # no UI step: the e2e gate of step 3 is what runs


def scripted_e2e(wb, name: str, statuses: dict[str, str]) -> E2eGateOutcome:
    """The e2e outcome of a run with these test statuses, judged the way `run_e2e_gate` judges it."""
    cases = {i: TestCase(i, s, message="boom" if s == "failed" else "") for i, s in statuses.items()}
    status = "fail" if "failed" in statuses.values() else "pass"
    result = GateResult(
        name, status, "" if status == "pass" else "exit code 1", 0, wb.out_dir / f"{name}.log", TestReport(cases)
    )
    out = gates._judged(wb, name, "pytest e2e", "gates.e2e.reports", result)
    return E2eGateOutcome(out.gate, out.report, out.findings, snapshot="<html>")


@pytest.fixture
def e2e_runs(monkeypatch):
    """`ladder.run_e2e_gate` answers from `script[name]`, the names it was called with are recorded."""
    calls: list[str] = []
    script: dict[str, dict[str, str]] = {}

    def fake(wb, *, name="e2e"):
        calls.append(name)
        return scripted_e2e(wb, name, script[name])

    monkeypatch.setattr(ladder, "run_e2e_gate", fake)
    return calls, script


def verdict(run, round_no: int = 1) -> dict:
    return json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-{round_no}/verdict.json"))


def test_a_pre_existing_e2e_test_that_flips_does_not_fail_the_round(run_multi, e2e_runs):  # SCN-VER-288
    calls, script = e2e_runs
    script["e2e"] = {FLAKY_ID: "failed"}
    script["e2e-repeat-1"] = {FLAKY_ID: "passed"}
    run = run_multi([red(), green(), judge()], edit=with_e2e)
    assert calls == ["e2e", "e2e-repeat-1"]
    assert run.code == 0 and run.outcome["units"][0]["verdict"] == "PASS"
    assert steps(run)["3"] == "ok"
    [event] = run.events("verify.gate_repeat")
    assert {k: v for k, v in event.items() if k in ("round", "gate", "runs", "flaky", "failing", "stopped")} == {
        "round": 1, "gate": "e2e", "runs": 2, "flaky": [FLAKY_ID], "failing": [], "stopped": "passed",
    }  # fmt: skip
    data = verdict(run)
    assert {g["name"]: g["status"] for g in data["gates"] if g["name"].startswith("e2e")} == {
        "e2e": "flaky", "e2e-repeat-1": "pass",
    }  # fmt: skip
    assert data["tests"][FLAKY_ID] == "passed" and FLAKY_ID not in data["failures"] and FLAKY_ID in data["e2e_tests"]
    assert [f["title"] for f in data["findings"] if f["severity"] == "minor"] == [FLAKY_TITLE]
    text = report(run)
    assert "| e2e | flaky |" in text and "| e2e-repeat-1 | pass |" in text
    assert f"e2e: 2 runs (L4-VER-076); flaky: {FLAKY_ID}" in text and f"[minor, deterministic] {FLAKY_TITLE}" in text
    assert run.events("fix.spawned") == []


def test_a_pre_existing_e2e_test_that_fails_in_every_run_fails_the_round(run_multi, e2e_runs):  # SCN-VER-289
    calls, script = e2e_runs
    script.update({n: {FLAKY_ID: "failed"} for n in ("e2e", "e2e-repeat-1", "e2e-repeat-2")})
    run = run_multi([red(), green(), judge()], edit=with_e2e)
    assert calls == ["e2e", "e2e-repeat-1", "e2e-repeat-2"]
    assert run.code == 10 and run.outcome["units"][0]["verdict"] == "FAIL"
    data = verdict(run)
    assert [g["name"] for g in data["gates"] if g["name"].startswith("e2e")] == ["e2e", "e2e-repeat-1", "e2e-repeat-2"]
    assert data["failures"][FLAKY_ID]["gate"] == "e2e"
    assert "(3 runs); failing: " + FLAKY_ID in report(run) and "| 3 | tests | failed |" in report(run)


def test_the_test_gates_repeat_runs_without_the_coverage_environment_before_the_e2e_gate(
    run_multi, e2e_runs, monkeypatch
):  # SCN-VER-295
    calls, script = e2e_runs
    script["e2e"] = {}
    seen: dict[str, object] = {}
    real_run = {}
    real = ladder.run_test_gate

    def fake(wb, must_contain, *, extra_env=None, name="test"):
        seen[name] = extra_env
        if (
            name == "test"
        ):  # the first run is the real gate with its real coverage, and a pre-existing test failed in it
            real_run["out"] = out = real(wb, must_contain, extra_env=extra_env)
            cases = {**out.report.tests, FLAKY_ID: TestCase(FLAKY_ID, "failed", message="boom")}
            blocker = Finding(
                Severity.BLOCKER, "test gate failed", "`pytest` failed", "deterministic", log=out.gate.log
            )
            return TestGateOutcome(replace(out.gate, status="fail", reason="exit code 1"), TestReport(cases), [blocker])
        out = real_run["out"]
        cases = {**out.report.tests, FLAKY_ID: TestCase(FLAKY_ID, "passed")}
        return TestGateOutcome(GateLine(name, out.gate.command, "pass", "", out.gate.log), TestReport(cases), [])

    monkeypatch.setattr(ladder, "run_test_gate", fake)
    run = run_multi([red(), green(), judge()], edit=with_e2e, coverage="warn")
    assert list(seen) == ["test", "test-repeat-1"] and calls == ["e2e"]
    first = seen["test"]
    assert first["PYTEST_ADDOPTS"] == "-p l4_cov" and "L4_COV_RC" in first
    assert seen["test-repeat-1"] is None  # no `extra_env`: no `L4_COV_RC`, no `-p l4_cov`
    assert run.code == 0 and steps(run)["3"] == "ok"
    assert evidence(run)["diff_coverage"]["status"] == "ok"  # the first run's coverage
    assert {g["name"]: g["status"] for g in verdict(run)["gates"] if g["name"].startswith("test")} == {
        "test": "flaky", "test-repeat-1": "pass",
    }  # fmt: skip


# --- the real e2e gate ---------------------------------------------------------------------------------------


@pytest.fixture
def bench(make_bench):  # noqa: F811
    bench = make_bench([], e2e=e2e_config(free_port()))
    stage(bench.wb.worktree)
    return bench


def test_an_e2e_repeat_serves_the_app_again_under_its_own_name(bench):
    first = gates.run_e2e_gate(bench.wb)
    second = gates.run_e2e_gate(bench.wb, name="e2e-repeat-1")
    assert first.ok and second.ok
    assert (first.gate.name, second.gate.name) == ("e2e", "e2e-repeat-1")
    assert second.gate.log and second.gate.log.endswith("e2e-repeat-1.log") and second.snapshot is not None
    assert [e["name"] for e in bench.events("gate.finished")] == ["e2e", "e2e-repeat-1"]
    assert gate_repeat.is_repeat(second.gate.name)


def test_a_failing_e2e_repeat_keeps_its_own_row_and_the_flaky_verdict_uses_the_first_runs_log(bench):
    wb = bench.wb
    (wb.worktree / "e2e/test_broken.py").write_text("def test_broken():\n    assert False\n")
    first = gates.run_e2e_gate(wb)
    outcomes = []

    def again(name):
        (wb.worktree / "e2e/test_broken.py").write_text("def test_broken():\n    assert True\n")
        outcomes.append(gates.run_e2e_gate(wb, name=name))
        return outcomes[-1]

    out = gate_repeat.settle(
        wb, first, gate="e2e", command=wb.cfg.gates.e2e.command, must_contain=set(), again=again,
        is_pre_existing=lambda _: True, runs=3, round_no=1,
    )  # fmt: skip
    assert out.ok and out.gate.status == "flaky" and out.gate.name == "e2e"
    assert [r.name for r in out.repeats] == ["e2e-repeat-1"] and out.repeats[0].status == "pass"
    [finding] = out.findings
    assert finding.title == FLAKY_TITLE and finding.log == first.gate.log and finding.log.endswith("e2e.log")
    assert out.snapshot == first.snapshot
    assert [e["name"] for e in bench.events("gate.finished")] == ["e2e", "e2e-repeat-1"]
    assert [e["gate"] for e in bench.events("verify.gate_repeat")] == ["e2e"]


def test_a_server_that_never_gets_ready_in_a_repeat_is_an_internal_error(bench):  # SCN-VER-297
    wb = bench.wb
    (wb.worktree / "e2e/test_broken.py").write_text("def test_broken():\n    assert False\n")
    first = gates.run_e2e_gate(wb)  # the first run's server came up
    assert not first.ok

    def again(name):
        wb.cfg.gates.e2e.serve.command = f"{PY} -c 'import time; time.sleep(120)'"
        wb.cfg.gates.e2e.serve.timeout = "1s"
        return gates.run_e2e_gate(wb, name=name)

    with pytest.raises(L4Exit) as err:
        gate_repeat.settle(
            wb, first, gate="e2e", command=wb.cfg.gates.e2e.command, must_contain=set(), again=again,
            is_pre_existing=lambda _: True, runs=3, round_no=1,
        )  # fmt: skip
    assert err.value.code == ExitCode.INTERNAL_ERROR
    assert bench.events("verify.gate_repeat") == [] and Path(wb.worktree).exists()
