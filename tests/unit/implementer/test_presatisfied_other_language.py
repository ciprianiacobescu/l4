"""L4-IMP-092 (SCN-IMP-485..489): the pre-satisfied run varies Python files only, so a test in a file of another
language that it did not reach is inconclusive, not refuted; Python tests and tests with no file found keep the rules
they have; the hold names the runs that were made and, in its reason, what the base run saw."""

from types import SimpleNamespace

import pytest

from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import discrimination, tdd
from l4.implementer.base_run import BaseRunResult, combine
from l4.implementer.discrimination import PRE_NOT_PYTHON, ZeroRun, confirm_pre_satisfied
from l4.implementer.tdd import RedOutcome, _decide_pre_satisfied
from l4.implementer.variant import classify
from l4.redact import Redactor
from l4.specs.base import Task

C1, C2 = "C-cb0c606e", "C-dd11ee22"
TS_FILE = "src/durable/queue.test.ts"
TS_TEST = f"src.durable.queue.test.ts::{C1} launch again"
TS_ERROR = "src.durable.queue.test.ts::boot fails"
BOOT_FILE = "src/durable/boot.test.ts"
BOOT_TEST = "src.durable.boot.test.ts::boot fails"
PY_FILE = "tests/test_x.py"
PY_TEST = "tests.test_x::test_x"
PY_SECOND = "tests.test_x::test_y"
LOST_TEST = "tests.test_lost::test_lost"
SEEN_PASSES = "the base run: every new test passes against the unit base code too"
NO_IMPORT = "no project source module is imported by those tests"
SEED = "deploy/seed.py"
FILES = (TS_FILE, BOOT_FILE, PY_FILE, SEED)
REAL = TestReport({t: TestCase(t, "passed") for t in (TS_TEST, TS_ERROR, BOOT_TEST, PY_TEST, PY_SECOND, LOST_TEST)})
WB = SimpleNamespace(redactor=Redactor({}))


def project(monkeypatch, *, scope=(), files=FILES):
    """A project as the collectors and the work tree's listing describe it; nothing is dependency-only."""
    monkeypatch.setattr(discrimination, "import_roots", lambda wb: ("src",))
    monkeypatch.setattr(discrimination, "_criterion_texts", lambda wb: {})
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: set(scope))
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "own_test_files", lambda wb: frozenset())
    monkeypatch.setattr(discrimination, "worktree_files", lambda wb: list(files))


def zero_run(monkeypatch, tmp_path, *, passed=(), failed=(), cases=(), collection=(), reruns=0):
    """The zero-value run: `passed` ids passed in it, `failed` are (id, failure kind) pairs that failed, `cases` are
    other test cases as they are, `collection` names modules that failed to import."""
    log = tmp_path / "test-presatisfied.log"
    log.write_text("")
    found = {t: TestCase(t, "passed") for t in passed}
    found |= {t: TestCase(t, "failed", failure_kind=kind) for t, kind in failed}
    found |= {case.id: case for case in cases}
    report = TestReport(found, list(collection), dict.fromkeys(collection, "ImportError: no module named x"))
    bad = bool(failed or collection)
    gate = GateResult("test-presatisfied", "fail" if bad else "pass", "", 1 if bad else 0, log, report)
    redact = Redactor({}).redact_text
    monkeypatch.setattr(
        discrimination,
        "zeroed_run",
        lambda *a, **k: ZeroRun(gate, classify(gate, REAL, redact=redact), {}, reruns, frozenset()),
    )


def no_run(*a, **k):
    raise AssertionError("no zero-value run may be made")


def test_scn_imp_485_a_typescript_test_with_no_scope_is_inconclusive_and_the_base_run_cannot_refute_it(monkeypatch):
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert got.unconfirmed == {} and got.confirmed == {} and got.reason == ""
    assert got.inconclusive == {C1: PRE_NOT_PYTHON.format(file=TS_FILE)}
    assert "Python files only" in got.message and f"{TS_FILE} is not a Python file" in got.message
    decision = combine(got, BaseRunResult(reason="none of its new tests fails by assertion against the unit base code"))
    assert decision.refuted == {} and set(decision.inconclusive) == {C1}


def test_scn_imp_485_the_task_is_held_with_a_pre_satisfied_question_not_failed(monkeypatch):
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    wb = SimpleNamespace(discard_changes=lambda: None)
    monkeypatch.setattr(tdd, "accepted_overrides", lambda *a, **k: {})
    monkeypatch.setattr(tdd, "capture", lambda wb, held, result: held)
    task = Task("2.3", "2.3", "2.3 Launch again", False, " ", 0, 1, 3)
    based = BaseRunResult(reason="none of its new tests fails by assertion against the unit base code")
    out, overrides = _decide_pre_satisfied(wb, task, {C1: [TS_TEST]}, got, based, SimpleNamespace())
    assert isinstance(out, RedOutcome) and out.status == "held" and overrides == {}
    assert out.held.check == "pre_satisfied" and out.held.subjects == (C1,) and out.held.tests == (TS_TEST,)
    assert PRE_NOT_PYTHON.format(file=TS_FILE) in out.held.reason


def test_scn_imp_486_a_mixed_criterion_is_inconclusive_with_the_typescript_reason(monkeypatch, tmp_path):
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(PY_TEST, TS_TEST))
    got = confirm_pre_satisfied(WB, {C1: [PY_TEST, TS_TEST]}, real=REAL)
    assert got.unconfirmed == {} and got.confirmed == {}
    assert got.inconclusive == {C1: PRE_NOT_PYTHON.format(file=TS_FILE)}


def test_scn_imp_487_a_typescript_test_the_zero_value_run_reached_is_still_refuted(monkeypatch, tmp_path):
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, failed=((TS_ERROR, "error"),))
    got = confirm_pre_satisfied(WB, {C1: [TS_ERROR]}, real=REAL)
    assert got.unconfirmed == {C1: (TS_ERROR,)} and got.inconclusive == {} and got.confirmed == {}


def test_scn_imp_488_python_tests_and_tests_with_no_file_found_are_refuted_with_no_scope(monkeypatch):
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [PY_TEST], C2: [LOST_TEST]}, real=REAL)
    assert got.unconfirmed == {C1: (PY_TEST,), C2: (LOST_TEST,)} and got.reason == NO_IMPORT
    assert got.inconclusive == {} and got.confirmed == {}


def test_a_criterion_with_both_kinds_is_split_with_no_scope_and_the_reason_is_kept(monkeypatch):
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST], C2: [PY_TEST]}, real=REAL)
    assert got.inconclusive == {C1: PRE_NOT_PYTHON.format(file=TS_FILE)}
    assert got.unconfirmed == {C2: (PY_TEST,)} and got.reason == NO_IMPORT


def test_the_first_out_of_reach_test_names_the_reason(monkeypatch):
    project(monkeypatch, files=(*FILES, "src/durable/other.test.ts"))
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    other = "src.durable.other.test.ts::second"
    got = confirm_pre_satisfied(WB, {C1: [PY_TEST, other, TS_TEST]}, real=REAL)
    assert got.inconclusive == {C1: PRE_NOT_PYTHON.format(file="src/durable/other.test.ts")}


def test_a_python_criterion_the_zero_value_run_refuted_stays_refuted(monkeypatch, tmp_path):
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(PY_TEST,))
    got = confirm_pre_satisfied(WB, {C1: [PY_TEST]}, real=REAL)
    assert got.unconfirmed == {C1: (PY_TEST,)} and got.inconclusive == {}


def test_a_criterion_the_zero_value_run_confirmed_stays_confirmed(monkeypatch, tmp_path):
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(TS_TEST,), failed=((PY_TEST, "assertion"),))
    got = confirm_pre_satisfied(WB, {C1: [PY_TEST, TS_TEST]}, real=REAL)
    assert got.confirmed == {C1: (PY_TEST,)} and got.unconfirmed == {} and got.inconclusive == {}


@pytest.mark.parametrize("scope", [(), (SEED,)])
def test_a_typescript_test_with_no_file_found_keeps_the_rule_it_has(monkeypatch, tmp_path, scope):
    project(monkeypatch, scope=scope, files=(PY_FILE, SEED))
    if scope:
        zero_run(monkeypatch, tmp_path, passed=(TS_TEST,))
    else:
        monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert got.unconfirmed == {C1: (TS_TEST,)} and got.inconclusive == {}


# --- the review (R1..R4) ----------------------------------------------------------------------------------------


def test_a_typescript_test_with_the_status_error_in_the_zero_value_run_stays_refuted(monkeypatch, tmp_path):
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(PY_TEST,), cases=(TestCase(TS_ERROR, "error"),))
    got = confirm_pre_satisfied(WB, {C1: [TS_ERROR]}, real=REAL)
    assert got.unconfirmed == {C1: (TS_ERROR,)} and got.inconclusive == {} and got.confirmed == {}


def test_a_criterion_with_a_reached_and_an_unreached_typescript_test_is_inconclusive_with_the_unreached_file(
    monkeypatch, tmp_path
):
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(TS_TEST,), cases=(TestCase(BOOT_TEST, "error"),))
    got = confirm_pre_satisfied(WB, {C1: [BOOT_TEST, TS_TEST]}, real=REAL)
    assert got.unconfirmed == {} and got.inconclusive == {C1: PRE_NOT_PYTHON.format(file=TS_FILE)}


def test_a_criterion_the_zero_value_run_left_inconclusive_keeps_its_own_reason(monkeypatch, tmp_path):
    """The Python test's module failed to import in the run: that reason stays, though the criterion also has a
    TypeScript test the run did not reach."""
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(PY_SECOND, TS_TEST), collection=("tests.test_x",))
    got = confirm_pre_satisfied(WB, {C1: [PY_TEST, TS_TEST]}, real=REAL)
    assert got.unconfirmed == {} and got.confirmed == {} and set(got.inconclusive) == {C1}
    assert "did not run in test-presatisfied" in got.inconclusive[C1]
    assert "not a Python file" not in got.inconclusive[C1]


def test_a_typescript_test_skipped_only_in_the_zero_value_run_stays_refuted(monkeypatch, tmp_path):
    """L4-IMP-060: a test that skipped in the zero-value run is no proof, never inconclusive; the run reached it."""
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(PY_TEST,), cases=(TestCase(TS_TEST, "skipped"),))
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert got.unconfirmed == {C1: (TS_TEST,)} and got.inconclusive == {}


def test_r2_no_readable_report_applies_the_same_rule_and_made_no_run(monkeypatch):
    project(monkeypatch, scope=(SEED,))
    monkeypatch.setattr(discrimination, "zeroed_run", lambda *a, **k: None)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST], C2: [PY_TEST]}, real=REAL)
    assert got.inconclusive == {C1: PRE_NOT_PYTHON.format(file=TS_FILE)}
    assert got.unconfirmed == {C2: (PY_TEST,)}
    assert got.reason == "the zero-value run produced no readable report (nothing to vary)"
    assert got.ran is False


def test_r2_no_readable_report_with_only_typescript_tests_leaves_no_reason(monkeypatch):
    project(monkeypatch, scope=(SEED,))
    monkeypatch.setattr(discrimination, "zeroed_run", lambda *a, **k: None)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert got.unconfirmed == {} and got.reason == "" and set(got.inconclusive) == {C1} and got.ran is False


def test_the_exits_that_make_no_zero_value_run_say_so(monkeypatch, tmp_path):
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    assert confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL).ran is False  # the empty scope
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: {SEED})
    zero_run(monkeypatch, tmp_path, passed=(PY_TEST,))
    assert confirm_pre_satisfied(WB, {C1: [PY_TEST]}, real=REAL).ran is True


def test_the_dependency_only_exit_makes_no_zero_value_run(monkeypatch):
    from l4.implementer import depcheck

    project(monkeypatch)
    monkeypatch.setattr(discrimination, "_criterion_texts", lambda wb: {C1: "uses a library"})
    monkeypatch.setattr(depcheck, "dependency_only", lambda *a, **k: True)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert set(got.inconclusive) == {C1} and got.ran is False


def test_the_runs_line_names_only_the_runs_that_were_made(monkeypatch, tmp_path):
    based = BaseRunResult(base_sha="abc", reason="none of its new tests fails by assertion against the unit base code")
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    none = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert tdd._runs_of(none, based) == ("test-base-run",)
    project(monkeypatch, scope=(SEED,))
    zero_run(monkeypatch, tmp_path, passed=(TS_TEST,), reruns=1)
    made = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    assert made.ran is True and made.reruns == 1
    assert tdd._runs_of(made, based) == ("test-presatisfied", "test-presatisfied", "test-base-run")
    assert tdd._runs_of(made, BaseRunResult(reason="base run skipped: x")) == ("test-presatisfied", "test-presatisfied")


def test_scn_imp_489_the_hold_shows_what_the_base_run_saw(monkeypatch):
    project(monkeypatch)
    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    got = confirm_pre_satisfied(WB, {C1: [TS_TEST]}, real=REAL)
    based = BaseRunResult(
        base_sha="abc",
        reason="none of its new tests fails by assertion against the unit base code",
        seen={C1: SEEN_PASSES},
    )
    decision = combine(got, based)
    assert decision.refuted == {}
    assert decision.inconclusive[C1] == f"{PRE_NOT_PYTHON.format(file=TS_FILE)}; {SEEN_PASSES}"
    wb = SimpleNamespace(discard_changes=lambda: None)
    monkeypatch.setattr(tdd, "accepted_overrides", lambda *a, **k: {})
    monkeypatch.setattr(tdd, "capture", lambda wb, held, result: held)
    task = Task("2.3", "2.3", "2.3 Launch again", False, " ", 0, 1, 3)
    out, _ = _decide_pre_satisfied(wb, task, {C1: [TS_TEST]}, got, based, SimpleNamespace())
    assert out.status == "held" and out.held.runs == ("test-base-run",)
    assert out.held.reason.endswith(SEEN_PASSES)


def test_an_inconclusive_note_of_the_base_run_comes_before_what_it_saw():
    zero = discrimination.PreSatisfied(inconclusive={C1: "zero"})
    based = BaseRunResult(base_sha="b", inconclusive={C1: "it did not run"}, seen={C1: SEEN_PASSES})
    assert combine(zero, based).inconclusive == {C1: "zero; it did not run"}
