"""Review M1 (SCN-IMP-320..323): in a zero-value run a test the unit's OWN files made unrunnable (a skip, a collection
error in its own test or support file, a parametrize that lost the id) is no proof, never inconclusive: only a
production module that failed to import holds the task. An accepted override covers the tests that were recorded."""

from pathlib import Path

from l4.agents.fake import Step
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import variant
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_red
from l4.redact import Redactor
from l4.specs.base import Task

from .conftest import KNOWN, STUB, UNKNOWN, Bench, result
from .test_held_answers import answer
from .test_held_check import held_bench, zero_says

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
T1 = "tests.test_spans::test_one"
OWN = frozenset({"tests/test_spans.py"})
PRODUCTION_TRACE = (
    "tests/test_spans.py:1: in <module>\n    import pytdd.store\nsrc/pytdd/store.py:14: in <module>\nE   TypeError: x\n"
)
OWN_TRACE = "tests/test_spans.py:7: in <module>\n    raise RuntimeError('trap')\nE   RuntimeError: trap\n"
REAL = TestReport({T1: TestCase(T1, "passed")})


def run_of(tmp_path: Path, report: TestReport):
    log = tmp_path / "gate.log"
    log.write_text("")
    gate = GateResult("test-presatisfied", "fail", "exit code 1", 1, log, report)
    return variant.classify(gate, REAL, redact=Redactor({}).redact_text)


def outcome(tmp_path, report, *, zero_value=True):
    run = run_of(tmp_path, report)
    return variant.test_outcome(run, T1, REAL, OWN, zero_value=zero_value)


OTHER = TestCase("tests.test_x::test_y", "passed")


def test_a_production_import_failure_is_inconclusive(tmp_path):
    report = TestReport({OTHER.id: OTHER}, ["tests.test_spans"], {"tests.test_spans": PRODUCTION_TRACE})
    assert outcome(tmp_path, report)[0] == "inconclusive"


def test_a_collection_error_in_the_units_own_file_is_no_proof(tmp_path):
    report = TestReport({OTHER.id: OTHER}, ["tests.test_spans"], {"tests.test_spans": OWN_TRACE})
    assert outcome(tmp_path, report) == ("none", "")
    assert outcome(tmp_path, report, zero_value=False)[0] == "inconclusive"  # the base run only confirms


def test_a_module_that_collected_but_lost_the_id_is_no_proof(tmp_path):
    assert outcome(tmp_path, TestReport({OTHER.id: OTHER})) == ("none", "")


def test_a_test_skipped_only_in_the_zero_value_run_is_no_proof(tmp_path):
    skipped = TestReport({T1: TestCase(T1, "skipped")})
    assert outcome(tmp_path, skipped) == ("none", "")
    assert outcome(tmp_path, skipped, zero_value=False)[0] == "inconclusive"


SKIP_ON_ZERO = f"""\
import pytest

from pytdd.pricing import apply_discount


@pytest.mark.l4("{KNOWN}")
def test_known_code():
    got = apply_discount(50.0, "SAVE10")
    if not got:
        pytest.skip("discount table not loaded")


@pytest.mark.l4("{UNKNOWN}")
def test_unknown_code():
    try:
        apply_discount(50.0, "NOPE")
    except ValueError:
        return
    assert False, "no ValueError"
"""


def test_b1_a_test_that_skips_on_the_zero_answer_is_vacuous_as_on_0415(make_bench):
    step = Step(
        writes={"tests/test_discount.py": SKIP_ON_ZERO, "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench: Bench = make_bench([step])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith("vacuous: "), out.reason
    assert bench.events("check.inconclusive") == [] and bench.events("question.raised") == []


def presat(name: str, body: str, head: str = "") -> Step:
    text = f'import pytest\n\nfrom pytdd import total\n\n{head}\n\n@pytest.mark.l4("{KNOWN}")\n{body}'
    return Step(writes={f"tests/{name}.py": text}, structured=result("red", criteria_ids=[KNOWN]))


def test_b2_a_presatisfied_test_that_skips_on_the_zero_answer_fails_the_attempt(make_bench):
    body = 'def test_first():\n    if not total([50.0]):\n        pytest.skip("pricing not loaded")\n'
    bench: Bench = make_bench([presat("test_first", body)])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith(f"not discriminating: {KNOWN}"), out.reason
    assert bench.events("question.raised") == []


def test_b3_a_trap_in_the_units_own_test_module_fails_the_attempt(make_bench):
    head = '_READY = total([50.0])\nif not _READY:\n    raise RuntimeError("pricing is not loaded")\n'
    bench: Bench = make_bench([presat("test_trap", "def test_known_code():\n    pass\n", head)])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith(f"not discriminating: {KNOWN}"), out.reason
    assert bench.events("question.raised") == []


def test_b4_a_parametrize_over_a_production_answer_fails_the_attempt(make_bench):
    body = (
        '@pytest.mark.parametrize("amount", [a for a in (total([50.0]),) if a])\n'
        "def test_known_code(amount):\n    pass\n"
    )
    bench: Bench = make_bench([presat("test_param", body)])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith(f"not discriminating: {KNOWN}"), out.reason
    assert bench.events("question.raised") == []


def new_test(name: str) -> Step:
    text = (
        f'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("{KNOWN}")\ndef {name}():\n'
        "    assert total([2.0, 2.0]) == 4.0\n"
    )
    return Step(writes={f"tests/{name}.py": text}, structured=result("red", criteria_ids=[KNOWN]))


def test_an_accept_does_not_cover_a_later_different_test_of_the_criterion(make_bench, monkeypatch, raw):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [new_test("test_first"), new_test("test_other_shape")])
    first = run_task(bench.wb, TASK)
    assert (first.status, first.question_ids) == ("blocked", ["Q-001"])
    [raised] = bench.events("question.raised")
    assert raised["tests"] == ["tests.test_first::test_first"]
    answer(bench, raw, "accept: the check is broken")
    second = run_task(bench.wb, TASK)
    assert second.status == "blocked" and second.question_ids == ["Q-002"]  # held again, not counted as accepted
    assert bench.events("check.accepted") == []


def test_an_accept_covers_the_same_test_again(make_bench, monkeypatch, raw):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [new_test("test_first"), new_test("test_first")])
    assert run_task(bench.wb, TASK).status == "blocked"
    answer(bench, raw, "accept: the check is broken")
    assert run_task(bench.wb, TASK).status == "done"
    assert len(bench.events("check.accepted")) == 1
