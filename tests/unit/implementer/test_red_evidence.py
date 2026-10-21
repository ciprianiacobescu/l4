"""Red with evidence (L4-IMP-002): the stub guard, tracing, vacuity and failure kinds, end to end on the fixture repo
with the fake adapter and the real pytest."""

from collections.abc import Callable
from pathlib import Path

from l4.agents.fake import Step
from l4.gates.junit import parse_junit
from l4.implementer.tdd import RedOutcome, run_red
from l4.specs.base import Task

from .conftest import IMPL, KNOWN, STUB, TESTS, UNKNOWN, Bench, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
TYPED_STUB = (
    "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n"
    "def apply_discount(amount: float, code: str) -> float:\n    raise NotImplementedError\n"
)
HEADER = "import pytest\n\nfrom pytdd.pricing import apply_discount\n\n\n"


def red(tests: str, stub: str = STUB, **over: object) -> Step:
    return Step(
        writes={"tests/test_discount.py": tests, "src/pytdd/pricing.py": stub},
        structured=result("red", criteria_ids=over.pop("criteria_ids", [KNOWN, UNKNOWN])),  # type: ignore[arg-type]
        **over,
    )  # fmt: skip


def run(make_bench: Callable[..., Bench], step: Step) -> tuple[Bench, RedOutcome]:
    bench = make_bench([step])
    return bench, run_red(bench.wb, TASK, attempt=1)


def test_real_code_in_red_in_an_existing_module_is_rebuilt_as_head_plus_stubs(make_bench):
    bench, outcome = run(make_bench, red(TESTS, stub=IMPL))
    assert outcome.status == "ok", outcome.reason
    pricing = (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
    assert pricing == "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n" + (
        "def apply_discount(amount, code):\n    raise NotImplementedError\n"
    )  # HEAD, then the stub: CODES (a module value) and the real body are gone
    violations = bench.events("guard.violation")
    assert violations and {v["phase"] for v in violations} == {"red"}
    purity = bench.events("stub.purity")[0]
    assert purity["task"] == "1.1" and purity["stubs"] == ["src/pytdd/pricing.py:apply_discount"]


def test_a_call_only_test_is_vacuous(make_bench):
    tests = HEADER + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    apply_discount(50.0, "SAVE10")\n'
    bench, outcome = run(make_bench, red(tests, TYPED_STUB, criteria_ids=[KNOWN]))
    assert outcome.status == "failed"
    assert outcome.reason.startswith(f"vacuous: {KNOWN}") and "test_known_code" in outcome.reason
    assert (
        bench.wb.worktree / "src/pytdd/pricing.py"
    ).read_text() == "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n"


def test_a_zero_answer_test_beside_a_discriminating_sibling_passes(make_bench):
    tests = (
        HEADER
        + f'@pytest.mark.l4("{KNOWN}")\ndef test_zero_is_the_answer():\n'
        + '    assert apply_discount(0.0, "SAVE10") == 0.0\n\n\n'
        + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    assert apply_discount(50.0, "SAVE10") == 45.0\n'
    )
    bench, outcome = run(make_bench, red(tests, TYPED_STUB, criteria_ids=[KNOWN]))
    assert outcome.status == "ok", outcome.reason
    assert outcome.criteria[KNOWN]["proof"] == "zero_value"
    assert outcome.criteria[KNOWN]["discriminating"] == ["tests.test_discount::test_known_code"]  # not the zero edge
    assert outcome.criteria[KNOWN]["tests"] == [
        "tests.test_discount::test_known_code",
        "tests.test_discount::test_zero_is_the_answer",
    ]
    assert bench.events("task.red_ok")[0]["criteria"] == {KNOWN: outcome.criteria[KNOWN]}


def test_a_type_error_red_is_refused_with_feedback(make_bench):
    tests = (
        HEADER
        + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n'
        + '    assert apply_discount(50.0, "S", rounding="up") == 45.0\n'
    )
    _, outcome = run(make_bench, red(tests, TYPED_STUB, criteria_ids=[KNOWN]))
    assert outcome.status == "failed"
    assert "test_known_code" in outcome.reason and "TypeError" in outcome.reason and "guarded" in outcome.reason


def test_the_report_maps_the_new_tests_to_their_criterion_ids(make_bench):
    bench, outcome = run(make_bench, red_step())
    assert outcome.status == "ok", outcome.reason
    cases = parse_junit(bench.wb.worktree / ".l4-out/junit.xml").tests
    assert cases["tests.test_discount::test_known_code"].criteria == (KNOWN,)
    assert cases["tests.test_discount::test_unknown_code"].criteria == (UNKNOWN,)
    assert cases["tests.test_discount::test_known_code"].failure_kind == "not_implemented"
    assert outcome.criteria == {
        KNOWN: {
            "tests": ["tests.test_discount::test_known_code"],
            "proof": "zero_value",
            "discriminating": ["tests.test_discount::test_known_code"],
        },
        UNKNOWN: {
            "tests": ["tests.test_discount::test_unknown_code"],
            "proof": "zero_value",
            "discriminating": ["tests.test_discount::test_unknown_code"],
        },
    }


def test_tests_that_trace_no_criterion_fail_red_and_a_loose_test_is_recorded(make_bench):
    loose = TESTS.replace(f'@pytest.mark.l4("{UNKNOWN}")\n', "")
    bench, outcome = run(make_bench, red(loose, criteria_ids=[KNOWN, UNKNOWN]))
    assert outcome.status == "failed" and UNKNOWN in outcome.reason and "@pytest.mark.l4" in outcome.reason
    assert [e["test"] for e in bench.events("test.untraced")] == ["tests.test_discount::test_unknown_code"]


def test_a_traced_test_without_the_declared_ids_still_counts(make_bench):
    bench, outcome = run(make_bench, red(TESTS, criteria_ids=[]))
    assert outcome.status == "ok", outcome.reason
    assert set(outcome.criteria) == {KNOWN, UNKNOWN}


def test_the_declared_suppressions_reach_task_red_ok(make_bench):
    step = red_step()
    step.structured["suppressions"] = [
        {"file": "src/pytdd/pricing.py", "line": 1, "rule": "F401", "reason": "re-export"}
    ]  # type: ignore[index]
    bench, outcome = run(make_bench, step)
    assert outcome.status == "ok", outcome.reason
    assert bench.events("task.red_ok")[0]["suppressions"][0]["rule"] == "F401"


def test_non_python_production_files_are_restored_and_new_ones_deleted(make_bench):
    step = red_step()
    step.writes = {**step.writes, "notes.txt": "x\n"}  # type: ignore[misc]
    bench, outcome = run(make_bench, step)
    assert outcome.status == "ok" and not (Path(bench.wb.worktree) / "notes.txt").exists()


def test_a_guarded_parameter_stub_is_a_valid_red_for_a_new_keyword(make_bench):
    guarded = (
        "def total(prices: list[float], rounding: str | None = None) -> float:\n"
        "    if rounding is not None:\n        raise NotImplementedError\n    return round(sum(prices), 2)\n"
    )
    tests = (
        'import pytest\nfrom pytdd import total\n\n\n@pytest.mark.l4("' + KNOWN + '")\n'
        'def test_rounds_up():\n    assert total([1.2, 2.2], rounding="up") == 3.4\n'
    )
    bench, outcome = run(make_bench, red(tests, guarded, criteria_ids=[KNOWN]))
    assert outcome.status == "ok", outcome.reason
    assert outcome.criteria[KNOWN]["proof"] == "zero_value"
    assert bench.events("stub.purity")[0]["stubs"] == ["src/pytdd/pricing.py:total (guard)"]
    assert "if rounding is not None" in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
