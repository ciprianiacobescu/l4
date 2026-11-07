"""named-tests-trace (L4-IMP-093, SCN-IMP-490..493): a test the task names, that red changed in place, that passed
before the step and fails at red by assertion, traces its cited criterion like a new test."""

import pytest

from l4.agents.fake import Step
from l4.gates.hang import TIMEOUT_MARKER
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.result import TRACE_HINT_PYTEST, ImplementerResult, check_criteria, parse_result
from l4.implementer.tamper import Tampered
from l4.implementer.tdd import (
    NAMED_NOT_NEW,
    NO_NEW_TEST,
    NamedTracing,
    classify_red,
    green_failures,
    named_tracing,
    resume_red,
    run_red,
)

from .conftest import HEADER, KNOWN, STUB, UNKNOWN, UNKNOWN_TEST
from .conftest import result as step_result
from .test_red_preexisting_tests import (
    BASE_TEST,
    CODES,
    FAKE_RUNNER,
    SIXTEEN,
    count,
    reviewed,
    superseded_events,
    ts_bench,
)

A, B, C, D = "C-aaaaaaaa", "C-bbbbbbbb", "C-cccccccc", "C-dddddddd"
FAMILY = {A, B, C, D}
PY = "tests.test_registry::test_registry_lists_all"
PY_FILE, PY_NAME = "tests/test_registry.py", "test_registry_lists_all"
TS = f"src.registry.test.ts::{A} the registry lists every tool"
CAP = 3


def result(*criteria_ids: str) -> ImplementerResult:
    return parse_result(
        {"status": "done", "phase": "red", "task_ids": ["1"], "summary": "s", "criteria_ids": list(criteria_ids)}
    )


def case(test_id: str, status: str = "failed", *, kind: str | None = "assertion", ids: tuple[str, ...] = (A,),
         message: str = "") -> TestCase:  # fmt: skip
    return TestCase(test_id, status, message, criteria=ids, failure_kind=kind)  # type: ignore[arg-type]


def reports(test_id: str = PY, **over) -> tuple[TestReport, TestReport]:
    """(base, red): the named test passed at the base and fails by assertion at red."""
    base = TestReport({test_id: case(test_id, "passed", kind=None, ids=over.get("ids", (A,)))})
    head = TestReport({test_id: case(test_id, **{k: v for k, v in over.items() if k != "base"})})
    return over.get("base", base), head


CHANGED = [Tampered(PY_FILE, PY_NAME, "changed", "")]


def tracing(python=CHANGED, other=(), base=None, head=None, family=FAMILY, universe=None, cap=CAP) -> NamedTracing:
    b, h = reports()
    return named_tracing(python, other, base or b, head or h, family, universe or family, cap)


# --- check_criteria(named=...) ---


def test_a_counted_named_test_fills_tracing_for_a_cited_criterion():  # SCN-IMP-490
    check = check_criteria(result(A), FAMILY, {}, named={PY: case(PY)})
    assert check.error == "" and check.cited == (A,) and check.tracing == {A: (PY,)}
    assert check.untraced == ()


def test_a_counted_named_test_sits_beside_the_new_test_of_another_criterion():  # SCN-IMP-491
    new = {"t::test_b": case("t::test_b", ids=(B,))}
    check = check_criteria(result(A, B), FAMILY, new, named={PY: case(PY)})
    assert check.error == "" and check.tracing == {A: (PY,), B: ("t::test_b",)}


def test_both_a_new_and_a_named_test_trace_the_same_criterion():
    new = {"t::test_a": case("t::test_a")}
    check = check_criteria(result(A), FAMILY, new, named={PY: case(PY)})
    assert check.tracing == {A: ("t::test_a", PY)}  # sorted


def test_without_criteria_ids_the_unit_criteria_a_named_test_traces_are_cited():
    new = {"t::test_b": case("t::test_b", ids=(B,))}
    check = check_criteria(result(), FAMILY, new, named={PY: case(PY, ids=(A, C))})
    assert check.error == "" and check.cited == (A, B, C)


def test_a_named_test_never_makes_an_id_outside_the_family_cited():
    named = {PY: case(PY, ids=(A, "C-99999999"))}
    check = check_criteria(result(), FAMILY, {}, named=named)
    assert check.error == "" and check.cited == (A,)
    declared = check_criteria(result(A), FAMILY, {}, named=named)
    assert declared.error == "" and declared.cited == (A,)  # only criteria_ids can name an unknown id


def test_a_named_test_is_never_untraced():
    check = check_criteria(result(A), FAMILY, {}, named={PY: case(PY, ids=(A,)), "t::x": case("t::x", ids=())})
    assert check.untraced == ()


def test_a_cited_criterion_no_new_and_no_named_test_traces_still_fails():
    check = check_criteria(result(A, B), FAMILY, {}, named={PY: case(PY)})
    assert check.error.startswith(f"no new test traces {B}: ")


def test_an_exempt_criterion_is_still_waived_beside_a_named_test():
    check = check_criteria(result(A, B), FAMILY, {}, named={PY: case(PY)}, exempt={B})
    assert check.error == "" and check.tracing == {A: (PY,)}  # B is waived, as before


def test_a_counted_named_test_satisfies_a_kiro_leafs_required_criterion():  # L4-KSP-012
    ok = check_criteria(result(), FAMILY, {}, required={A}, aliases={A: "Req 1.1"}, links="1.1", named={PY: case(PY)})
    assert ok.error == "" and ok.tracing == {A: (PY,)}
    missing = check_criteria(
        result(), FAMILY, {}, required={A, B}, aliases={B: "Req 1.2"}, links="1.1, 1.2", named={PY: case(PY)}
    )
    assert missing.error.startswith(f"no new test traces {B} (Req 1.2), which the task's _Requirements:")


# --- classify_red(named_proofs=...) ---

OLD = TestReport({PY: case(PY, "passed", kind=None)})
RED = TestReport({PY: case(PY)})


def test_a_step_with_no_new_test_and_one_named_proof_is_ok():  # SCN-IMP-490
    verdict = classify_red(
        OLD, RED, test_files_changed=True, failure_kinds=True, named_changed=[(PY_FILE, PY_NAME)], named_proofs=(PY,)
    )
    assert verdict.ok, verdict.reason


def test_without_a_named_proof_the_no_new_test_reasons_stay():  # SCN-IMP-493
    kw = {"test_files_changed": True, "failure_kinds": True}
    assert classify_red(OLD, RED, named_changed=[(PY_FILE, PY_NAME)], **kw).reason == NAMED_NOT_NEW
    assert classify_red(OLD, RED, named_other=[PY], **kw).reason == NAMED_NOT_NEW
    assert classify_red(OLD, OLD, **kw).reason == NO_NEW_TEST
    assert classify_red(OLD, OLD, named_proofs=(), **kw).reason == NO_NEW_TEST


# --- named_tracing ---


def test_a_changed_python_test_that_passed_and_fails_by_assertion_and_traces_counts():  # SCN-IMP-490
    got = tracing()
    assert list(got.counted) == [PY] and got.refused == {}


def test_every_parametrised_id_of_a_changed_python_test_is_judged_alone():
    ok, bad = f"{PY}[a]", f"{PY}[b]"
    base = TestReport({ok: case(ok, "passed", kind=None), bad: case(bad, "passed", kind=None)})
    head = TestReport({ok: case(ok), bad: case(bad, "error", kind="other")})
    got = tracing(base=base, head=head)
    assert list(got.counted) == [ok] and got.refused == {bad: "it does not fail by assertion at red"}


def test_a_changed_typescript_id_counts():  # SCN-IMP-490
    base = TestReport({TS: case(TS, "passed", kind=None)})
    head = TestReport({TS: case(TS)})
    got = tracing(python=[], other=[TS], base=base, head=head)
    assert list(got.counted) == [TS] and got.refused == {}


@pytest.mark.parametrize(
    ("status", "kind", "message"),
    [
        ("error", "other", "TypeError: f() got an unexpected keyword argument"),
        ("failed", "other", "TypeError: boom"),
        ("failed", "not_implemented", "NotImplementedError"),
        ("passed", None, ""),
    ],
)
def test_a_changed_named_test_that_does_not_fail_by_assertion_is_refused(status, kind, message):  # SCN-IMP-492
    base, _ = reports()
    head = TestReport({PY: case(PY, status, kind=kind, message=message)})
    got = tracing(base=base, head=head)
    assert got.counted == {} and got.refused == {PY: "it does not fail by assertion at red"}


def test_a_changed_named_test_that_hangs_is_refused():  # SCN-IMP-492
    base, _ = reports()
    head = TestReport({PY: case(PY, message=f"Failed: {TIMEOUT_MARKER} 10s")})
    got = tracing(base=base, head=head)
    assert got.counted == {} and got.refused == {PY: "it hangs at red"}


@pytest.mark.parametrize("status", ["failed", "error", "skipped"])
def test_a_changed_named_test_that_did_not_pass_at_the_base_is_refused(status):  # SCN-IMP-492
    base = TestReport({PY: case(PY, status, kind="assertion")})
    got = tracing(base=base)
    assert got.counted == {} and got.refused == {PY: "it did not pass before this step"}


def test_a_changed_named_test_missing_from_the_base_report_is_refused():  # SCN-IMP-492
    got = tracing(base=TestReport({}))
    assert got.counted == {} and got.refused == {PY: "it did not pass before this step"}


def test_the_first_reason_wins():
    base = TestReport({PY: case(PY, "failed", kind="assertion")})
    head = TestReport({PY: case(PY, "error", kind="other")})
    assert tracing(base=base, head=head).refused == {PY: "it did not pass before this step"}


def test_a_changed_named_test_over_the_cap_is_refused():  # SCN-IMP-493
    four = (A, B, C, D)
    base, head = reports(ids=four)
    got = tracing(base=base, head=head)
    assert got.counted == {} and got.refused == {PY: "it traces more than 3 of this unit's criteria"}


def test_ids_outside_the_cap_universe_do_not_count_against_the_cap():
    ids = (A, B, C, "C-99999999")
    base, head = reports(ids=ids)
    assert list(tracing(base=base, head=head).counted) == [PY]


def test_the_cap_reads_the_universe_not_the_family():
    parent = "C-eeeeeeee"
    base, head = reports(ids=(A, B, parent, D))
    got = tracing(base=base, head=head, universe=FAMILY | {parent})
    assert got.refused == {PY: "it traces more than 3 of this unit's criteria"}


def test_a_changed_named_test_that_traces_none_of_the_unit_is_in_neither_map():  # SCN-IMP-493
    for ids in ((), ("C-99999999",)):
        base, head = reports(ids=ids)
        got = tracing(base=base, head=head)
        assert got.counted == {} and got.refused == {}


def test_an_unchanged_named_test_is_in_neither_map():
    assert tracing(python=[], other=[]) == NamedTracing({}, {})


def test_a_changed_test_gone_from_the_red_report_is_in_neither_map():
    assert tracing(head=TestReport({})) == NamedTracing({}, {})


def test_only_the_changed_python_test_is_judged_not_a_test_of_another_module():
    other = "tests.test_other::test_registry_lists_all"
    base = TestReport({other: case(other, "passed", kind=None)})
    head = TestReport({other: case(other)})
    assert tracing(base=base, head=head) == NamedTracing({}, {})


# --- run_red: SCN-IMP-490..493 (the SCN-IMP-439 setup of test_red_preexisting_tests) ---

REGISTRY_K = f"{KNOWN} The registry holds exactly the 16 codes of the API with status and message"
TS_ID = f"{CODES}::{REGISTRY_K}"
TS_SOURCE = SIXTEEN.replace("C-96e47324", KNOWN)
TS_TEXT = f"- [ ] 1.1 Add `apply_discount`; change `{CODES}::{REGISTRY_K}` to count 22 codes\n"
PY_ID = "tests.test_pricing::test_total_adds_prices"
PY_TEXT = "- [ ] 1.1 Add `apply_discount`; update `tests/test_pricing.py::test_total_adds_prices` in place\n"


def tagged(*ids: str, body: str = "    assert total([1.25, 2.5]) == 3.75\n") -> str:
    marks = "".join(f'@pytest.mark.l4("{i}")\n' for i in ids)
    return (
        "import pytest\n\nfrom pytdd import total\n\n\n"
        + marks
        + f"def test_total_adds_prices():\n{body}\n\ndef test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
    )


def failing(*ids: str, body: str = "    assert total([1.25, 2.5]) == 99\n") -> str:
    return tagged(*ids, body=body)


def python_bench(make_bench, base_source: str, **gates):
    bench = make_bench([], **gates)
    (bench.wb.worktree / BASE_TEST).write_text(base_source)
    return bench, reviewed(bench, PY_TEXT)


def python_red(named_source: str, *, new: bool = True, criteria=(KNOWN, UNKNOWN)) -> Step:
    writes = {BASE_TEST: named_source}
    if new:
        writes |= {"tests/test_discount.py": HEADER + UNKNOWN_TEST, "src/pytdd/pricing.py": STUB}
    return Step(writes=writes, structured=step_result("red", criteria_ids=list(criteria)))


def ts_named_red(source: str) -> Step:
    return Step(writes={CODES: source}, structured=step_result("red", criteria_ids=[KNOWN]))


def typescript_bench(make_bench, tmp_path, **kw):
    return ts_bench(make_bench, tmp_path, text=TS_TEXT, source=TS_SOURCE, runner_source=FAKE_RUNNER, **kw)


def count_of(codes: int) -> str:
    return count(codes).replace("C-96e47324", KNOWN)


def red_ok(bench):
    return bench.events("task.red_ok")[-1]


def test_scn_imp_490_a_named_typescript_test_that_fails_by_assertion_is_its_criterions_red_test(make_bench, tmp_path):
    bench, task = typescript_bench(make_bench, tmp_path)
    bench.adapter._script.append(ts_named_red(count_of(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    event = red_ok(bench)
    assert event["tests"] == [] and "already" not in str(event.get("tdd", ""))
    proof = event["criteria"][KNOWN]
    assert proof["tests"] == [TS_ID] and proof["discriminating"] == [TS_ID]
    assert proof["proof"] in ("red_assertion", "zero_value")
    [superseded] = superseded_events(bench)
    assert superseded["tests"] == [TS_ID] and superseded["reason"] == "named_by_task"
    assert superseded["language"] == "typescript"
    assert "L4-TDD: red" in bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert out.new_ids == frozenset() and not bench.events("criterion.pre_satisfied")
    assert bench.events("test.untraced") == []


def test_scn_imp_490_green_must_make_the_named_test_pass_again(make_bench, tmp_path):
    bench, task = typescript_bench(make_bench, tmp_path)
    bench.adapter._script.append(ts_named_red(count_of(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    log = bench.wb.worktree / "green.log"

    def gate(status: str) -> GateResult:
        tests = {i: TestCase(i, "passed") for i in out.base_report.tests}
        tests[TS_ID] = TestCase(TS_ID, status)  # type: ignore[arg-type]
        return GateResult("test", "pass", "", 0, log, TestReport(tests))

    reason, ids = green_failures(out.base_report, sorted(out.new_ids), gate("failed"), out.superseded)
    assert reason == f"green broke existing tests: {TS_ID}" and ids == [TS_ID]
    assert green_failures(out.base_report, sorted(out.new_ids), gate("passed"), out.superseded) == ("", [])


def test_scn_imp_491_a_named_python_test_counts_beside_a_new_test_for_another_criterion(make_bench):
    bench, task = python_bench(make_bench, tagged(KNOWN))
    bench.adapter._script.append(python_red(failing(KNOWN)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    proofs = red_ok(bench)["criteria"]
    assert proofs[KNOWN]["tests"] == [PY_ID] and proofs[UNKNOWN]["tests"] == ["tests.test_discount::test_unknown_code"]
    assert red_ok(bench)["tests"] == ["tests.test_discount::test_unknown_code"]
    assert [e["tests"] for e in superseded_events(bench)] == [[PY_ID]]
    assert bench.events("test.untraced") == []


def refused_reason(criterion: str, test: str, why: str) -> str:
    return (
        f"no new test traces {criterion}: {TRACE_HINT_PYTEST}; "
        f"{test}, which the task names, does not count for {criterion}: {why}"
    )


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("    assert total([1.25, 2.5], 99) == 3.75\n", "it does not fail by assertion at red"),  # TypeError
        ("    raise NotImplementedError\n", "it does not fail by assertion at red"),
        ("    pytest.fail('l4-test-timeout: 10s')\n", "it hangs at red"),
    ],
)
def test_scn_imp_492_a_named_python_test_that_errors_or_hangs_does_not_count(make_bench, body, why):
    bench, task = python_bench(make_bench, tagged(KNOWN))
    bench.adapter._script.append(python_red(failing(KNOWN, body=body)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == refused_reason(KNOWN, PY_ID, why)
    assert bench.wb.git.run("log", "--oneline", "main..HEAD").stdout.count("\n") == 1  # only the task text commit
    assert superseded_events(bench) == []


def test_scn_imp_492_a_named_python_test_that_failed_at_the_base_does_not_count(make_bench):
    base = tagged(KNOWN, body="    assert total([1.25, 2.5]) == 4\n")  # fails at the base already
    bench, task = python_bench(make_bench, base)
    bench.adapter._script.append(python_red(failing(KNOWN)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == refused_reason(KNOWN, PY_ID, "it did not pass before this step")


def test_scn_imp_492_a_named_python_test_that_passes_at_red_does_not_count(make_bench):
    bench, task = python_bench(make_bench, tagged(KNOWN))
    bench.adapter._script.append(python_red(tagged(KNOWN, body="    assert total([1.25, 2.5]) == 3.75 and True\n")))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == refused_reason(KNOWN, PY_ID, "it does not fail by assertion at red")


def test_scn_imp_493_a_named_test_that_traces_no_cited_criterion_is_no_new_test(make_bench):
    bench, task = python_bench(make_bench, tagged())
    bench.adapter._script.append(python_red(failing(), new=False))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed" and out.reason == NAMED_NOT_NEW


def test_scn_imp_493_a_named_test_over_the_cap_is_no_new_test_and_says_why(make_bench):
    bench, task = python_bench(make_bench, tagged(KNOWN, UNKNOWN), verifier={"max_criteria_per_test": 1})
    bench.adapter._script.append(python_red(failing(KNOWN, UNKNOWN), new=False))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == (
        f"{NAMED_NOT_NEW}; {PY_ID}, which the task names, does not count for {KNOWN}, {UNKNOWN}: "
        "it traces more than 1 of this unit's criteria"
    )


def test_a_named_test_beside_no_cited_criterion_changes_nothing_for_a_normal_red(make_bench):
    bench = make_bench([])
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": HEADER + UNKNOWN_TEST, "src/pytdd/pricing.py": STUB},
            structured=step_result("red", criteria_ids=[UNKNOWN]),
        )
    )
    out = run_red(bench.wb, reviewed(bench, PY_TEXT), attempt=1)
    assert out.status == "ok", out.reason
    assert red_ok(bench)["criteria"][UNKNOWN]["tests"] == ["tests.test_discount::test_unknown_code"]


def test_f1_a_resumed_red_still_makes_green_pass_the_named_test(make_bench, tmp_path):
    """A run that died after the red commit resumes at green: the rebuilt base report must still hold the named test
    as passing (it failed at the red head), so green that leaves it failing is refused as after an unbroken red."""
    bench, task = typescript_bench(make_bench, tmp_path)
    bench.adapter._script.append(ts_named_red(count_of(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    resumed = resume_red(bench.wb, task)
    assert resumed is not None and resumed.status == "ok"
    assert resumed.new_ids == frozenset()
    assert resumed.base_report.tests[TS_ID].status == "passed"
    log = bench.wb.worktree / "green.log"

    def gate(status: str) -> GateResult:
        tests = {i: TestCase(i, "passed") for i in resumed.base_report.tests}
        tests[TS_ID] = TestCase(TS_ID, status)  # type: ignore[arg-type]
        return GateResult("test", "pass", "", 0, log, TestReport(tests))

    reason, ids = green_failures(resumed.base_report, sorted(resumed.new_ids), gate("failed"), resumed.superseded)
    assert reason == f"green broke existing tests: {TS_ID}" and ids == [TS_ID]
    assert green_failures(resumed.base_report, sorted(resumed.new_ids), gate("passed"), resumed.superseded) == ("", [])


def test_f1_a_resumed_red_keeps_a_new_test_out_of_the_base_and_a_named_python_test_in(make_bench):
    bench, task = python_bench(make_bench, tagged(KNOWN))
    bench.adapter._script.append(python_red(failing(KNOWN)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    resumed = resume_red(bench.wb, task)
    assert resumed is not None
    assert resumed.new_ids == frozenset({"tests.test_discount::test_unknown_code"})
    assert resumed.base_report.tests[PY_ID].status == "passed"
    assert "tests.test_discount::test_unknown_code" not in resumed.base_report.tests
