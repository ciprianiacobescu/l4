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
TEST_W = "e2e.test_cart::test_w"
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


def seed_round(
    bench,
    findings=STORED,
    failures=FAILURES,
    *,
    spawned: bool = True,
    tests=None,
    verify_round: int | None = 1,
    parent_rel: str | None = None,
) -> None:
    """Round 1 of the parent has a verdict.json, and the ledger says this fix unit was spawned from it. `failures`
    None: a verdict of an older harness, which has no such key. `parent_rel`: the parent's folder (the unit's own by
    default)."""
    body = {"schema": VERDICT_SCHEMA_ID, "round": 1, "findings": findings, "tests": tests or {}}
    if failures is not None:
        body["failures"] = failures
    folder = parent_rel or bench.wb.unit_rel
    commit_files(bench, {f"{folder}/.l4/evidence/round-1/verdict.json": json.dumps(body)})
    if spawned:
        bench.writer.append(
            "fix.spawned", parent=bench.wb.ref.id, fix_unit=bench.wb.ref.name, round=1, verify_round=verify_round,
            findings=[f["id"] for f in findings], consumed=[],
        )  # fmt: skip


def stub_e2e(
    monkeypatch,
    bench,
    calls: list,
    *,
    statuses=None,
    raises: bool = False,
    exit_code: int | None = None,
    writes: dict[str, str] | None = None,
    collection: tuple[str, ...] = (),
    log_text: str = "",
) -> None:
    """`run_e2e` as the verifier's e2e tests stub it: no server. `statuses(wb)` -> {test id: status}. `exit_code`:
    what the gate's command exited with (default: 0 when every test passed). `writes`: files the run leaves in the
    tree (a snapshot, a trace)."""

    def fake(wb, worktree=None, *, name="e2e", must_contain=(), extra_env=None):
        calls.append(
            SimpleNamespace(
                name=name, must_contain=sorted(must_contain), built=(wb.worktree / ".l4-out/built").exists()
            )
        )
        for rel, text in (writes or {}).items():
            (wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
            (wb.worktree / rel).write_text(text)
        if raises:
            log = wb.out_dir / "x.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(log_text)
            raise ServerNotReady("gates.e2e: the server was not ready (see x.log)", log)
        got = (statuses or (lambda w: {}))(wb)
        report = TestReport({i: TestCase(i, s) for i, s in got.items()}, collection_errors=list(collection))
        code = exit_code if exit_code is not None else (0 if all(s == "passed" for s in got.values()) else 1)
        gate = GateResult(
            name,
            "pass" if code == 0 else "fail",
            "" if code == 0 else f"exit code {code}",
            code,
            wb.out_dir / "e2e.log",
            report,
        )
        return E2eRun(gate, None)

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
    stub_e2e(monkeypatch, bench, calls, raises=True, log_text="Error: listen EADDRINUSE :::3000\n")
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and done.reason.startswith("the e2e server was not ready")
    assert "x.log" in done.reason  # the log is named, and its end is the excerpt
    assert "EADDRINUSE" in done.excerpt
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


def test_an_e2e_gate_finding_always_runs_the_gate_whatever_the_round_recorded(make_bench, monkeypatch):
    """Review 2: no recorded id (an older verdict, no failing test case) is not a pass; the gate must pass."""
    for failures in (None, {UNIT_ID: FAILURES[UNIT_ID]}):
        bench, calls = bench_with(make_bench, [FIX]), []
        seed_round(bench, failures=failures)
        stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "failed"})
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
        assert done.status == "failed" and "exit code 1" in done.reason and TEST_X in done.reason
        assert [c.must_contain for c in calls] == [[]]
        bench.wb.discard_changes()


def test_a_collection_error_of_the_e2e_gate_is_a_failure_to_fix_and_the_gate_must_pass_after(make_bench, monkeypatch):
    broken = {"e2e.test_broken": {"gate": "e2e", "kind": "collection", "message": "ImportError: no module"}}
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, failures=broken)
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "passed"}, collection=("e2e.test_broken",))
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and "not collected" in done.reason  # judged as step 3 judges the gate
    assert [c.must_contain for c in calls] == [[]]  # a module is no test id: it is not asked for in the report


def test_an_e2e_gate_finding_needs_the_gate_to_pass_not_only_its_ids(make_bench, monkeypatch):
    """Review 1: the step fixes test_x and test_z and breaks test_w, which passed in the parent round."""
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, tests={TEST_W: "passed"})
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "passed", TEST_Z: "passed", TEST_W: "failed"})
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and TEST_W in done.reason
    assert bench.events("task.done") == []


def test_a_gate_that_exits_1_for_another_reason_is_not_a_pass(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench)
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "passed", TEST_Z: "passed"}, exit_code=1)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and "exit code 1" in done.reason


def test_a_new_tests_task_fails_on_a_regression_against_the_parent_round(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, tests={TEST_W: "passed", TEST_X: "failed"})
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "passed", TEST_W: "error"})
    done = run_single(bench.wb, TASK, [NEW_FINDING], attempt=1)
    assert done.status == "failed" and TEST_W in done.reason and TEST_X not in done.reason


def test_a_new_tests_task_without_a_regression_is_done(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, tests={TEST_W: "passed", TEST_X: "failed"})
    stub_e2e(
        monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "passed", TEST_W: "passed", "e2e.t::other": "failed"}
    )
    done = run_single(bench.wb, TASK, [NEW_FINDING], attempt=1)
    assert done.status == "ok", done.reason  # `other` failed in the e2e run but was not a passing test of the round


def test_an_unparseable_new_tests_detail_asks_for_all_the_failing_e2e_tests(make_bench, monkeypatch):
    stored = [{"id": NEW_FINDING, "title": "new tests failed", "detail": "see the log, not a list of ids"}]
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, findings=stored)
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    assert run_single(bench.wb, TASK, [NEW_FINDING], attempt=1).status == "ok"
    assert [c.must_contain for c in calls] == [[TEST_X, TEST_Z]]


def test_a_fix_unit_recovered_without_its_round_still_runs_the_gate(make_bench, monkeypatch):
    """`adopt_orphans` records `fix.spawned` with `verify_round: null`."""
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, verify_round=None)
    stub_e2e(monkeypatch, bench, calls, statuses=lambda wb: {TEST_X: "failed"})
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "failed" and len(calls) == 1


def test_the_parents_verdict_is_read_from_the_parents_folder_not_the_fix_units(make_bench, monkeypatch):
    """The real layout: the fix unit's folder differs from the parent's, where the evidence and the ledger are."""
    bench, calls = bench_with(make_bench, [FIX]), []
    parent = bench.wb.unit_rel
    seed_round(bench, parent_rel=parent)
    monkeypatch.setattr(bench.wb, "unit_rel", f"{parent}-fix-1")
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    assert run_single(bench.wb, TASK, [E2E_FINDING], attempt=1).status == "ok"
    assert [c.must_contain for c in calls] == [[TEST_X, TEST_Z]]


def test_what_the_build_and_the_e2e_run_leave_in_the_tree_is_not_committed(make_bench, monkeypatch):
    """Review 4: a build artefact, a new snapshot baseline under the test globs, a tracked file a gate rewrote."""
    build = (
        "import pathlib\npathlib.Path('dist').mkdir(exist_ok=True)\npathlib.Path('dist/app.js').write_text('x')\n"
        "pathlib.Path('notes.txt').write_text('rewritten')\n"
    )
    bench, calls = bench_with(make_bench, [FIX], build=[f"{sys.executable} scripts/build.py"]), []
    seed_round(bench)
    commit_files(bench, {"scripts/build.py": build, "notes.txt": "original"})
    stub_e2e(
        monkeypatch, bench, calls, statuses=fixed_when_marked,
        writes={"tests/e2e-snapshots/cart.png": "baseline", "test-results/trace.zip": "t"},
    )  # fmt: skip
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    assert done.status == "ok", done.reason
    committed = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "src/pytdd/pricing.py" in committed
    assert not {"dist/app.js", "notes.txt", "tests/e2e-snapshots/cart.png", "test-results/trace.zip"} & set(committed)
    assert (bench.wb.worktree / "notes.txt").read_text() == "original"
    assert not (bench.wb.worktree / "dist/app.js").exists()
    assert not (bench.wb.worktree / "tests/e2e-snapshots/cart.png").exists()


def test_a_fix_unit_with_no_spawning_round_on_record_still_runs_the_gate_without_ids(make_bench, monkeypatch):
    bench, calls = bench_with(make_bench, [FIX]), []
    seed_round(bench, spawned=False)  # no `fix.spawned`: the round is not known, so no id; the gate must pass
    stub_e2e(monkeypatch, bench, calls, statuses=fixed_when_marked)
    assert run_single(bench.wb, TASK, [E2E_FINDING], attempt=1).status == "ok"
    assert [c.must_contain for c in calls] == [[]]


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


def test_an_id_with_a_comma_is_matched_against_the_rounds_ids_not_split():
    comma = "e2e.test_cart::test_total[1, 2]"
    failures = {**FAILURES, comma: {"gate": "e2e", "kind": "other", "message": "m"}}
    finding = {"id": "F-9", "title": "new tests failed", "detail": f"{TEST_X}, {comma}"}
    assert e2e_ids_of({"findings": [finding], "failures": failures}, ["F-9"]) == sorted([TEST_X, comma])
    only = {"id": "F-9", "title": "new tests failed", "detail": comma}
    assert e2e_ids_of({"findings": [only], "failures": failures}, ["F-9"]) == [comma]


def test_a_cut_or_unmatched_list_takes_all_the_rounds_failing_e2e_ids():
    cut = {"id": "F-9", "title": "new tests failed", "detail": f"{TEST_X} and 4 more"}
    odd = {"id": "F-8", "title": "new tests errored", "detail": f"{TEST_X}, something else"}
    verdict = {"findings": [cut, odd], "failures": FAILURES}
    assert e2e_ids_of(verdict, ["F-9"]) == [TEST_X, TEST_Z] and e2e_ids_of(verdict, ["F-8"]) == [TEST_X, TEST_Z]


def test_a_collection_record_is_no_test_id():
    verdict = {
        "findings": STORED,
        "failures": {"e2e.test_broken": {"gate": "e2e", "kind": "collection", "message": "m"}},
    }
    assert e2e_ids_of(verdict, [E2E_FINDING]) == []
