"""Pre-satisfied criteria and `already_satisfied` (L4-IMP-002, L4-IMP-003): the harness proves it, no green step."""

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from .conftest import KNOWN, Bench, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
EXISTING = (
    'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("' + KNOWN + '")\n'
    "def test_total_adds():\n    assert total([1.0, 2.0]) == 3.0\n"
)
TAUTOLOGY = EXISTING.replace("assert total([1.0, 2.0]) == 3.0", "assert total([]) == total([])")


def step(tests: str) -> Step:
    return Step(writes={"tests/test_existing.py": tests}, structured=result("red", criteria_ids=[KNOWN]))


def test_tests_of_existing_behaviour_are_pre_satisfied_and_commit_as_already_satisfied(make_bench):
    bench: Bench = make_bench([step(EXISTING)])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.adapter.requests) == 1  # no green step
    message = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert message.splitlines()[0] == "test(add-discount-codes): 1.1 already satisfied [skip ci]"
    assert "L4-TDD: already-satisfied" in message and "L4-Task: 1.1" in message
    assert "[x] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    pre = bench.events("criterion.pre_satisfied")[0]
    assert (pre["task"], pre["criterion"], pre["tests"]) == ("1.1", KNOWN, ["tests.test_existing::test_total_adds"])
    red_ok = bench.events("task.red_ok")[0]
    assert red_ok["criteria"][KNOWN]["proof"] == "pre_satisfied"
    assert red_ok["criteria"][KNOWN]["discriminating"] == ["tests.test_existing::test_total_adds"]
    done = bench.events("task.done")[0]
    assert done["task"] == "1.1" and done["tdd"] == "already-satisfied" and done["base"] == red_ok["base"]
    assert bench.pushes  # published like any other checkpoint


def test_a_tautology_is_not_discriminating(make_bench):
    bench: Bench = make_bench([step(TAUTOLOGY)])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason.startswith(f"not discriminating: {KNOWN}")
    assert bench.events("criterion.pre_satisfied") == []


def test_stubs_that_no_test_needs_are_not_committed_with_an_already_satisfied_task(make_bench):
    stub = (
        "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n"
        "def unused():\n    raise NotImplementedError\n"
    )
    bench: Bench = make_bench(
        [
            Step(
                writes={"tests/test_existing.py": EXISTING, "src/pytdd/pricing.py": stub},
                structured=result("red", criteria_ids=[KNOWN]),
            )
        ]
    )
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done"
    assert "unused" not in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()


def test_a_test_that_errors_on_the_zero_value_without_asserting_is_not_discriminating(make_bench):
    erroring = EXISTING.replace("assert total([1.0, 2.0]) == 3.0", "1 / total([2.0])")
    bench: Bench = make_bench([step(erroring)])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason.startswith(f"not discriminating: {KNOWN}")
    assert bench.events("criterion.pre_satisfied") == []


def test_a_test_that_imports_a_stub_name_it_never_calls_does_not_leave_a_head_that_cannot_collect(make_bench):
    stub = (
        "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n"
        "def apply_discount(amount, code):\n    raise NotImplementedError\n"
    )
    tests = EXISTING.replace("from pytdd import total", "from pytdd.pricing import apply_discount, total")
    bench: Bench = make_bench(
        [Step(writes={"tests/test_existing.py": tests, "src/pytdd/pricing.py": stub},
              structured=result("red", criteria_ids=[KNOWN]))]
    )  # fmt: skip
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "import a name only a stub defines" in outcome.reason
    assert "apply_discount" not in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
    assert bench.events("task.red_ok") == []
