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


def test_the_runs_stay_bounded(tmp_path, monkeypatch):
    """Two runs plus at most two keep reruns of the zero-value run."""
    zero = missing(tmp_path, "test-extra-zero")
    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: {"src/pytdd/middleware.py"})
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: ["src/pytdd/middleware.py"])
    wb = SimpleNamespace(redactor=Redactor({}))
    monkeypatch.setattr(
        discrimination,
        "zeroed_run",
        lambda *a, **k: ZeroRun(zero, classify(zero, REAL, redact=wb.redactor.redact_text), {}, 2, frozenset()),
    )
    monkeypatch.setattr(discrimination, "run_with_code_of", lambda *a, **k: missing(tmp_path, "test-extra-base"))
    outcome = discrimination.discriminate_extra(wb, [TEST], "base", real=REAL)
    assert outcome.runs <= 4 and outcome.runs == 4
