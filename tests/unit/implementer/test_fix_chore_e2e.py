"""L4-IMP-090: a fix chore for a browser-test finding runs `gates.build` and the e2e gate after the test gate, with the
finding's e2e tests as tests that must be in the report and pass (fix-chore-e2e)."""

import json
import sys
from types import SimpleNamespace

from l4.agents.fake import Step
from l4.gates.e2e import E2eRun, ServerNotReady
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.tdd import run_single
from l4.specs.base import Task
from l4.verifier.failures import e2e_ids_of
from l4.verifier.report import VERDICT_SCHEMA_ID
from l4.verifier.types import finding_id

from .._web_helpers import e2e_config, free_port
from .conftest import IMPL, result

TASK = Task("1.1", "1.1", "1.1 e2e gate failed (F-6eb0cc43)", False, " ", 0, 3, 3)
E2E_FINDING, NEW_FINDING, OTHER_FINDING = (finding_id(t) for t in ("e2e gate failed", "new tests failed", "other"))
TEST_X, TEST_Z, UNIT_ID = "e2e.test_cart::test_x", "e2e.test_cart::test_z", "tests.test_pricing::test_total"
FAILURES = {
    TEST_X: {"gate": "e2e", "kind": "other", "message": "Error: value must be a string or regular expression"},
    TEST_Z: {"gate": "e2e", "kind": "assertion", "message": "assert 1 == 2"},
    UNIT_ID: {"gate": "test", "kind": "assertion", "message": "assert 0"},
}
STORED = [
    {"id": E2E_FINDING, "title": "e2e gate failed", "detail": "`pytest e2e` failed", "severity": "blocker"},
    {"id": NEW_FINDING, "title": "new tests failed", "detail": TEST_X, "severity": "blocker"},
    {"id": OTHER_FINDING, "title": "other", "detail": "x", "severity": "blocker"},
]
FIXED = IMPL + "\n\n# fixed\n"
FIX = Step(writes={"src/pytdd/pricing.py": FIXED}, structured=result("single"))
NOOP = Step(structured=result("single"))
BUILD_OK = (
    "import pathlib\npathlib.Path('.l4-out').mkdir(exist_ok=True)\npathlib.Path('.l4-out/built').write_text('x')\n"
)
BUILD_BAD = "import sys\nsys.exit(1)\n"


def commit_files(bench, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = bench.wb.worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    bench.wb.git.run("add", "--", *files)
    bench.wb.git.run("commit", "-q", "-m", "seed")


def seed_round(bench, findings=STORED, failures=FAILURES, *, spawned: bool = True) -> None:
    """Round 1 of the parent has a verdict.json, and the ledger says this fix unit was spawned from it."""
    body = {"schema": VERDICT_SCHEMA_ID, "round": 1, "findings": findings, "failures": failures}
    commit_files(bench, {f"{bench.wb.unit_rel}/.l4/evidence/round-1/verdict.json": json.dumps(body)})
    if spawned:
        bench.writer.append(
            "fix.spawned", parent=bench.wb.ref.id, fix_unit=bench.wb.ref.name, round=1, verify_round=1,
            findings=[f["id"] for f in findings], consumed=[],
        )  # fmt: skip


def stub_e2e(monkeypatch, bench, calls: list, *, statuses=None, raises: bool = False) -> None:
    """`run_e2e` as the verifier's e2e tests stub it: no server. `statuses(wb)` -> {test id: status}."""

    def fake(wb, worktree=None, *, name="e2e", must_contain=(), extra_env=None):
        calls.append(
            SimpleNamespace(
                name=name, must_contain=sorted(must_contain), built=(wb.worktree / ".l4-out/built").exists()
            )
        )
        if raises:
            raise ServerNotReady("gates.e2e: the server was not ready (see x.log)", wb.out_dir / "x.log")
        got = (statuses or (lambda w: {}))(wb)
        report = TestReport({i: TestCase(i, s) for i, s in got.items()})
        ok = all(s == "passed" for s in got.values())
        return E2eRun(
            GateResult(
                name,
                "pass" if ok else "fail",
                "" if ok else "exit code 1",
                0 if ok else 1,
                wb.out_dir / "e2e.log",
                report,
            ),
            None,
        )

    monkeypatch.setattr("l4.implementer.tdd.run_e2e", fake)


def fixed_when_marked(wb) -> dict[str, str]:
    marked = "# fixed" in (wb.worktree / "src/pytdd/pricing.py").read_text()
    return {TEST_X: "passed" if marked else "failed", TEST_Z: "passed" if marked else "failed"}


def bench_with(make_bench, script, **gates):
    return make_bench(script, e2e=e2e_config(free_port()), **gates)


def test_a_no_op_cannot_pass_a_browser_test_finding(make_bench, monkeypatch):  # SCN-IMP-446
    bench, calls = bench_with(make_bench, [NOOP]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and TEST_X in done.reason and TEST_Z in done.reason
    assert [(c.name, c.must_contain) for c in calls] == [
        ("e2e-chore", [TEST_X, TEST_Z])
    ]  # the unit-gate failure is not asked
    assert bench.wb.head() == before and "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    assert bench.events("task.done") == []


def test_a_change_that_leaves_the_browser_test_failing_fails_naming_it(make_bench, monkeypatch):  # SCN-IMP-446
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "failed", TEST_Z: "passed"})
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and TEST_X in done.reason and TEST_Z not in done.reason


def test_a_real_fix_passes(make_bench, monkeypatch):  # SCN-IMP-447
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "ok", done.reason
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"] and len(calls) == 1


def test_a_server_that_is_not_ready_is_a_failed_attempt_not_a_crash(make_bench, monkeypatch):  # SCN-IMP-448
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, raises=True)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and done.reason == "the e2e server was not ready"
    assert bench.events("task.done") == []


def test_a_report_without_the_test_fails_the_attempt(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "passed"})  # test_z never ran
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and TEST_Z in done.reason and TEST_X not in done.reason


def test_the_build_runs_before_the_e2e_gate(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX], build=[f"{sys.executable} scripts/build.py"]), []
    seed_round(bench)
    commit_files(bench, {"scripts/build.py": BUILD_OK})
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "ok", done.reason
    assert [c.built for c in calls] == [True]  # the stub saw the file the build wrote
    names = [e["name"] for e in bench.events("gate.finished")]
    assert names.index("test") < names.index("build")


def test_a_failed_build_fails_the_attempt_before_the_e2e_gate(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX], build=[f"{sys.executable} scripts/build.py"]), []
    seed_round(bench)
    commit_files(bench, {"scripts/build.py": BUILD_BAD})
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and "gates.build failed" in done.reason and calls == []


def test_a_chore_of_another_finding_runs_no_e2e_gate(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    done = run_single(bench.wb, TASK, [OTHER_FINDING], attempt=1)
    assert done.status == "ok", done.reason
    assert calls == []


def test_a_round_that_recorded_no_e2e_failure_runs_no_e2e_gate(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, failures={UNIT_ID: FAILURES[UNIT_ID]})  # a verdict of an older harness has no `failures` at all
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    assert run_single(bench.wb, TASK, [E2E_FINDING], attempt=1).status == "ok" and calls == []


def test_a_fix_unit_with_no_spawning_round_on_record_runs_no_e2e_gate(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, spawned=False)  # no `fix.spawned`: the round is not known
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    assert run_single(bench.wb, TASK, [E2E_FINDING], attempt=1).status == "ok" and calls == []


def test_a_project_without_the_e2e_gate_runs_none(make_bench, monkeypatch):
    bench, calls = make_bench([FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    assert run_single(bench.wb, TASK, [E2E_FINDING], attempt=1).status == "ok" and calls == []


def test_a_new_tests_finding_asks_for_the_e2e_tests_it_names(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    done = run_single(bench.wb, TASK, [NEW_FINDING], attempt=1)  # the finding names TEST_X only
    assert done.status == "ok", done.reason
    assert [c.must_contain for c in calls] == [[TEST_X]]


def test_the_e2e_ids_of_a_task_come_from_its_findings_and_the_e2e_gate_only():
    verdict = {"findings": STORED, "failures": FAILURES}
    assert e2e_ids_of(verdict, [E2E_FINDING]) == [TEST_X, TEST_Z]
    assert e2e_ids_of(verdict, [NEW_FINDING]) == [TEST_X]
    assert e2e_ids_of(verdict, [NEW_FINDING, E2E_FINDING]) == [TEST_X, TEST_Z]
    assert e2e_ids_of(verdict, [OTHER_FINDING]) == [] and e2e_ids_of({"findings": STORED}, [E2E_FINDING]) == []
    assert e2e_ids_of(None, [E2E_FINDING]) == []
    unit_only = {"findings": [{"id": "F-1", "title": "test gate failed", "detail": ""}], "failures": FAILURES}
    assert e2e_ids_of(unit_only, ["F-1"]) == []
