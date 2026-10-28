"""The extra proofs of tests people or a test chore wrote, when a run could not decide (L4-VER-050, L4-VER-009;
SCN-VER-152): the test is not rejected as "passes against the zero values", the reason says why it has no proof."""

from types import SimpleNamespace

from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import discrimination
from l4.implementer.discrimination import ExtraRun, ZeroRun
from l4.implementer.variant import classify
from l4.redact import Redactor
from l4.verifier import ladder
from l4.verifier.traceability import NO_PROOF
from l4.verifier.types import CriterionEvidence

TEST = "tests.test_middleware::test_wrap"
OTHER = "tests.test_middleware::test_other"
ERROR = "E   ImportError: cannot import name 'middleware'"
REAL = TestReport({TEST: TestCase(TEST, "passed"), OTHER: TestCase(OTHER, "passed")})


def gate(tmp_path, name: str, report: TestReport) -> GateResult:
    log = tmp_path / f"{name}.log"
    log.write_text("")
    return GateResult(name, "fail", "exit code 1", 1, log, report)


def missing(tmp_path, name: str) -> GateResult:
    """A run in which the tests did not run: their module is a new collection error."""
    ok = "tests.test_other_module::test_ok"
    detail = f"src/x.py:1: in <module>\n{ERROR}\n"
    report = TestReport({ok: TestCase(ok, "passed")}, ["tests.test_middleware"], {"tests.test_middleware": detail})
    return gate(tmp_path, name, report)


def test_scn_ver_152_an_extra_test_whose_runs_were_inconclusive_says_so(tmp_path, monkeypatch):
    zero = missing(tmp_path, "test-extra-zero")
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: {"src/pytdd/middleware.py"})
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: ["src/pytdd/middleware.py"])
    monkeypatch.setattr(discrimination, "worktree_files", lambda wb: [])
    wb = SimpleNamespace(redactor=Redactor({}))
    monkeypatch.setattr(
        discrimination,
        "zeroed_run",
        lambda *a, **k: ZeroRun(zero, classify(zero, REAL, redact=wb.redactor.redact_text), {}, 0, frozenset()),
    )
    monkeypatch.setattr(discrimination, "run_with_code_of", lambda *a, **k: missing(tmp_path, "test-extra-base"))
    outcome = discrimination.discriminate_extra(wb, [TEST], "base", real=REAL)
    assert outcome.accepted == {} and outcome.rejected == (TEST,)
    assert outcome.inconclusive == {TEST: f"{TEST} did not run in test-extra-zero: {ERROR}"}


def test_the_ladder_gives_an_inconclusive_extra_test_its_own_reason(monkeypatch):
    wb = SimpleNamespace(emit=lambda *a, **k: None, git=None)
    vc = SimpleNamespace(wb=wb, round=1)
    seen = {}

    def fake(wb, tests, base, *, real=None):
        seen["real"] = real
        return ExtraRun(inconclusive={TEST: f"{TEST} did not run in test-extra-zero: {ERROR}"})

    monkeypatch.setattr(ladder, "discriminate_extra", fake)
    monkeypatch.setattr(ladder, "human_only", lambda git, base, head, path: True)
    monkeypatch.setattr(ladder, "file_of_test", lambda wb, test: "tests/test_middleware.py")
    trace = [CriterionEvidence("C-aaaaaaaa", "a", "uncovered", ignored=((TEST, f"{NO_PROOF} for it"),))]
    run = SimpleNamespace(report=REAL)
    decided = ladder._extra_proof_step(vc, run, trace, [], "base", "head")
    assert decided is not None and decided.proofs == {}
    assert decided.reasons[TEST].startswith("inconclusive: ") and ERROR in decided.reasons[TEST]
    assert seen["real"] is REAL


TS_TEST = "src.pricing.total.test.ts::C-0a1b2c3d total of two prices"


def nothing_to_vary(monkeypatch) -> None:
    """A project whose tests import no Python module and whose unit changed no Python production file (TypeScript)."""
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: set())
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: [])
    monkeypatch.setattr(discrimination, "own_test_files", lambda wb: frozenset())
    monkeypatch.setattr(discrimination, "worktree_files", lambda wb: [])

    def no_run(*a, **k):
        raise AssertionError("no run can be made")

    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    monkeypatch.setattr(discrimination, "run_with_code_of", no_run)


def test_scn_ver_242_an_extra_test_no_run_could_be_made_for_is_inconclusive(monkeypatch):
    """A TypeScript test, and a Python test that imports no project module in a unit that changed no Python production
    file: neither run can be made, so each is inconclusive with why, not rejected as passing both runs."""
    nothing_to_vary(monkeypatch)
    outcome = discrimination.discriminate_extra(
        SimpleNamespace(redactor=Redactor({})), [TS_TEST, TEST], "base", real=REAL
    )
    assert outcome.accepted == {} and outcome.rejected == (TS_TEST, TEST) and outcome.runs == 0
    assert outcome.inconclusive == {TS_TEST: discrimination.NO_RUN, TEST: discrimination.NO_RUN}
    assert outcome.reasons == {}
    assert "Python" in discrimination.NO_RUN and "passes" not in discrimination.NO_RUN


def test_the_ladder_says_why_no_run_could_be_made(monkeypatch):
    """A Python test a person wrote that imports no project module, in a unit that changed no Python production file:
    step 4 makes no run and says why the test has no proof."""
    nothing_to_vary(monkeypatch)
    wb = SimpleNamespace(emit=lambda *a, **k: None, git=None, redactor=Redactor({}))
    vc = SimpleNamespace(wb=wb, round=1)
    monkeypatch.setattr(ladder, "human_only", lambda git, base, head, path: True)
    monkeypatch.setattr(ladder, "file_of_test", lambda wb, test: "tests/test_middleware.py")
    trace = [CriterionEvidence("C-0a1b2c3d", "a", "covered", ignored=((TEST, f"{NO_PROOF} for it"),))]
    decided = ladder._extra_proof_step(vc, SimpleNamespace(report=REAL), trace, [], "base", "head")
    assert decided is not None and decided.proofs == {}
    assert decided.reasons[TEST] == f"inconclusive: {discrimination.NO_RUN}"


def test_a_test_in_another_language_is_no_step_4_candidate(tmp_path, monkeypatch):
    """Step 4 takes only a test whose file is a Python file (`file_of_test`): a TypeScript test is no candidate, no run
    is made for it, and it keeps its no-proof finding (SCN-VER-242)."""
    nothing_to_vary(monkeypatch)
    (tmp_path / "src" / "pricing").mkdir(parents=True)
    (tmp_path / "src" / "pricing" / "total.test.ts").write_text("test('total of two prices', () => {})\n")

    def no_check(*a, **k):
        raise AssertionError("a TypeScript test is no candidate")

    monkeypatch.setattr(ladder, "discriminate_extra", no_check)
    monkeypatch.setattr(ladder, "human_only", lambda git, base, head, path: True)
    wb = SimpleNamespace(emit=lambda *a, **k: None, git=None, redactor=Redactor({}), worktree=tmp_path)
    vc = SimpleNamespace(wb=wb, round=1)
    trace = [CriterionEvidence("C-0a1b2c3d", "a", "covered", ignored=((TS_TEST, f"{NO_PROOF} for it"),))]
    assert discrimination.file_of_test(wb, TS_TEST) is None
    assert ladder._extra_proof_step(vc, SimpleNamespace(report=REAL), trace, [], "base", "head") is None


def test_the_runs_stay_bounded(tmp_path, monkeypatch):
    """Two runs plus at most two keep reruns of the zero-value run."""
    zero = missing(tmp_path, "test-extra-zero")
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: {"src/pytdd/middleware.py"})
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: ["src/pytdd/middleware.py"])
    monkeypatch.setattr(discrimination, "worktree_files", lambda wb: [])
    wb = SimpleNamespace(redactor=Redactor({}))
    monkeypatch.setattr(
        discrimination,
        "zeroed_run",
        lambda *a, **k: ZeroRun(zero, classify(zero, REAL, redact=wb.redactor.redact_text), {}, 2, frozenset()),
    )
    monkeypatch.setattr(discrimination, "run_with_code_of", lambda *a, **k: missing(tmp_path, "test-extra-base"))
    outcome = discrimination.discriminate_extra(wb, [TEST], "base", real=REAL)
    assert outcome.runs <= 4 and outcome.runs == 4


# --- a test the runs cannot reach, and runs that were not made (test-file-reach 2.1) ---------------------------------

TS_FILE = "src/pricing/total.test.ts"
SEED = "deploy/seed.py"
PY_TEST = "tests.test_total::test_total"


def passing(tmp_path, name: str, *ids: str) -> GateResult:
    log = tmp_path / f"{name}.log"
    log.write_text("")
    report = TestReport({i: TestCase(i, "passed") for i in ids})
    return GateResult(name, "pass", "", 0, log, report)


def failing(tmp_path, name: str, test: str, kind: str, *passed: str) -> GateResult:
    log = tmp_path / f"{name}.log"
    log.write_text("")
    cases = {test: TestCase(test, "failed", failure_kind=kind)} | {i: TestCase(i, "passed") for i in passed}
    return GateResult(name, "fail", "exit code 1", 1, log, TestReport(cases))


def mixed_project(
    monkeypatch,
    *,
    scope=(SEED,),
    production=(SEED,),
    files=(TS_FILE, SEED, "tests/test_total.py", "src/pricing/total.py", "src.py"),
):
    """A project with Python and TypeScript: what the collectors and the work tree's listing say."""
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: set(scope))
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: list(production))
    monkeypatch.setattr(discrimination, "own_test_files", lambda wb: frozenset())
    monkeypatch.setattr(discrimination, "worktree_files", lambda wb: list(files))


def fake_runs(monkeypatch, zero: GateResult | None, base: GateResult | None, real: TestReport) -> None:
    redact = Redactor({}).redact_text
    monkeypatch.setattr(
        discrimination,
        "zeroed_run",
        lambda *a, **k: (
            None if zero is None else ZeroRun(zero, classify(zero, real, redact=redact), {}, 0, frozenset())
        ),
    )

    def base_run(*a, **k):
        assert base is not None, "no base run may be made"
        return base

    monkeypatch.setattr(discrimination, "run_with_code_of", base_run)


def test_scn_ver_243_a_typescript_test_that_passes_both_runs_is_inconclusive_with_its_file_named(tmp_path, monkeypatch):
    real = TestReport({TS_TEST: TestCase(TS_TEST, "passed")})
    mixed_project(monkeypatch)
    fake_runs(
        monkeypatch, passing(tmp_path, "test-extra-zero", TS_TEST), passing(tmp_path, "test-extra-base", TS_TEST), real
    )
    outcome = discrimination.discriminate_extra(SimpleNamespace(redactor=Redactor({})), [TS_TEST], "base", real=real)
    assert outcome.accepted == {} and outcome.rejected == (TS_TEST,)
    assert outcome.inconclusive == {TS_TEST: discrimination.NOT_PYTHON.format(file=TS_FILE)}
    assert outcome.reasons == {} and outcome.runs == 2
    assert outcome.made == ("test-extra-zero", "test-extra-base")
    assert (
        "Python files only" in outcome.inconclusive[TS_TEST]
        and f"{TS_FILE} is not a Python file" in outcome.inconclusive[TS_TEST]
    )


def test_a_python_test_that_passes_both_runs_is_still_rejected(tmp_path, monkeypatch):
    real = TestReport({PY_TEST: TestCase(PY_TEST, "passed")})
    mixed_project(monkeypatch)
    fake_runs(
        monkeypatch, passing(tmp_path, "test-extra-zero", PY_TEST), passing(tmp_path, "test-extra-base", PY_TEST), real
    )
    outcome = discrimination.discriminate_extra(SimpleNamespace(redactor=Redactor({})), [PY_TEST], "base", real=real)
    assert (
        outcome.rejected == (PY_TEST,)
        and outcome.inconclusive == {}
        and outcome.made == ("test-extra-zero", "test-extra-base")
    )


def test_a_typescript_test_that_fails_on_the_base_by_an_error_is_rejected_with_that_reason(tmp_path, monkeypatch):
    real = TestReport({TS_TEST: TestCase(TS_TEST, "passed")})
    mixed_project(monkeypatch)
    fake_runs(
        monkeypatch,
        passing(tmp_path, "test-extra-zero", TS_TEST),
        failing(tmp_path, "test-extra-base", TS_TEST, "error"),
        real,
    )
    outcome = discrimination.discriminate_extra(SimpleNamespace(redactor=Redactor({})), [TS_TEST], "base", real=real)
    assert outcome.rejected == (TS_TEST,) and outcome.inconclusive == {}
    assert outcome.reasons == {TS_TEST: discrimination.ERROR_AT_BASE}


def test_scn_ver_244_when_no_function_can_be_varied_and_no_production_file_changed_no_run_is_made(monkeypatch):
    real = TestReport({TS_TEST: TestCase(TS_TEST, "passed"), PY_TEST: TestCase(PY_TEST, "passed")})
    mixed_project(monkeypatch, production=())
    fake_runs(monkeypatch, None, None, real)  # zeroed_run returns None; a base run would fail the test
    outcome = discrimination.discriminate_extra(
        SimpleNamespace(redactor=Redactor({})), [TS_TEST, PY_TEST], "base", real=real
    )
    assert outcome.accepted == {} and outcome.rejected == (TS_TEST, PY_TEST) and outcome.runs == 0
    assert outcome.made == () and outcome.reasons == {}
    assert outcome.inconclusive == dict.fromkeys([TS_TEST, PY_TEST], discrimination.NO_ZERO)
    assert (
        "no run could be made" in discrimination.NO_ZERO
        and "unit changed no Python production file" in discrimination.NO_ZERO
    )


def test_no_run_for_an_empty_scope_and_no_production_file_keeps_no_run_and_names_no_run_made(monkeypatch):
    nothing_to_vary(monkeypatch)
    monkeypatch.setattr(discrimination, "worktree_files", lambda wb: [])
    outcome = discrimination.discriminate_extra(SimpleNamespace(redactor=Redactor({})), [TEST], "base", real=REAL)
    assert outcome.inconclusive == {TEST: discrimination.NO_RUN} and outcome.made == ()


def test_scn_ver_246_a_python_test_that_fails_by_assertion_in_the_zero_value_run_is_accepted_as_before(
    tmp_path, monkeypatch
):
    real = TestReport({PY_TEST: TestCase(PY_TEST, "passed"), TS_TEST: TestCase(TS_TEST, "passed")})
    mixed_project(monkeypatch)
    zero = failing(tmp_path, "test-extra-zero", PY_TEST, "assertion", TS_TEST)
    fake_runs(monkeypatch, zero, passing(tmp_path, "test-extra-base", TS_TEST), real)
    outcome = discrimination.discriminate_extra(
        SimpleNamespace(redactor=Redactor({})), [PY_TEST, TS_TEST], "base", real=real
    )
    assert outcome.accepted == {PY_TEST: "zero_value"} and outcome.rejected == (TS_TEST,)
    assert outcome.inconclusive == {TS_TEST: discrimination.NOT_PYTHON.format(file=TS_FILE)}
    assert outcome.made == ("test-extra-zero", "test-extra-base")


def test_only_the_zero_value_run_made_is_named_in_made(tmp_path, monkeypatch):
    real = TestReport({PY_TEST: TestCase(PY_TEST, "passed")})
    mixed_project(monkeypatch, production=())
    fake_runs(monkeypatch, passing(tmp_path, "test-extra-zero", PY_TEST), None, real)
    outcome = discrimination.discriminate_extra(SimpleNamespace(redactor=Redactor({})), [PY_TEST], "base", real=real)
    assert outcome.made == ("test-extra-zero",) and outcome.runs == 1 and outcome.rejected == (PY_TEST,)
    assert outcome.inconclusive == {}


def test_a_test_whose_file_is_not_found_keeps_todays_rules(tmp_path, monkeypatch):
    real = TestReport({PY_TEST: TestCase(PY_TEST, "passed")})
    mixed_project(monkeypatch, files=())
    fake_runs(
        monkeypatch, passing(tmp_path, "test-extra-zero", PY_TEST), passing(tmp_path, "test-extra-base", PY_TEST), real
    )
    outcome = discrimination.discriminate_extra(SimpleNamespace(redactor=Redactor({})), [PY_TEST], "base", real=real)
    assert outcome.rejected == (PY_TEST,) and outcome.inconclusive == {}
