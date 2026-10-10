"""Static gates (lint, typecheck) across red and green: the baseline at the step base decides what counts as worse."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task

from .conftest import STUB, TESTS, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
LINT_TEST_FILE = "sh -c 'if grep -q LINTBAD tests/test_discount.py; then echo E999 bad test file; exit 1; fi'"
ALWAYS_FAILS = "sh -c 'echo preexisting lint error; exit 1'"
FAILS_ON_IMPL = "sh -c 'if grep -q round.amount src/pytdd/pricing.py; then echo F401 in impl; exit 1; fi'"


def lint_failing_red() -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS + "\n# LINTBAD\n", "src/pytdd/pricing.py": STUB},
        structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
    )


def test_red_with_a_lint_failing_test_is_retried_with_the_gate_output_and_then_green_passes(make_bench):
    bench = make_bench([lint_failing_red(), red_step(), green_step()], lint=[LINT_TEST_FILE])
    base = bench.wb.head()
    first = run_red(bench.wb, TASK, attempt=1)
    assert first.status == "failed" and "lint gate" in first.reason and "E999 bad test file" in first.reason
    assert bench.wb.head() == base and bench.wb.is_clean()  # discarded, nothing committed
    second = run_red(bench.wb, TASK, attempt=2, previous_failure=first.reason)
    assert second.status == "ok", second.reason
    assert "E999 bad test file" in bench.adapter.requests[1].prompt  # the retry sees why
    green = run_green(bench.wb, TASK, second, attempt=1)
    assert green.status == "ok", green.reason
    assert bench.events("gate.static_baseline_failed") == []


def test_red_prompt_names_the_static_gates_and_says_new_tests_must_pass_them(make_bench):
    bench = make_bench([red_step()], lint=["true"], typecheck=["echo ty"])
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    assert "`true`" in req.prompt and "`echo ty`" in req.prompt
    assert "new tests" in req.prompt and "must pass" in req.prompt


def test_a_repo_whose_lint_already_fails_at_the_base_does_not_block_red_or_green(make_bench):
    bench = make_bench([red_step(), green_step()], lint=[ALWAYS_FAILS])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    [warning] = [e for e in bench.events("gate.static_baseline_failed") if e["phase"] == "green"]
    assert warning["name"] == "lint" and "preexisting lint error" in warning["output"]


def test_green_that_breaks_a_gate_that_passed_at_the_base_fails_even_if_another_gate_already_failed(make_bench):
    bench = make_bench([red_step(), green_step()], lint=[ALWAYS_FAILS], typecheck=[FAILS_ON_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "typecheck gate" in green.reason and "F401 in impl" in green.reason
    assert "preexisting" not in green.reason  # only what got worse is reported
    assert bench.events("task.done") == [] and bench.wb.head() == red.sha


def test_the_static_baseline_runs_once_per_head(make_bench):
    bench = make_bench([lint_failing_red(), red_step()], lint=[LINT_TEST_FILE])
    run_red(bench.wb, TASK, attempt=1)
    run_red(bench.wb, TASK, attempt=2)
    runs = [e for e in bench.events("gate.finished") if e["name"] == "lint-baseline"]
    assert len(runs) == 1


def test_the_lint_reason_is_bounded_and_deduplicated(make_bench):
    noise = (
        'for i in $(seq 1 120); do echo "src/mod.py:$i:1: E501 line too long"; done; '
        'for i in 1 2 3 4; do echo "  repeated hint line number one"; done; echo "Found 120 errors."; exit 1'
    )
    noisy = f"sh -c 'if grep -q LINTBAD tests/test_discount.py; then {noise}; fi'"
    bench = make_bench([lint_failing_red()], lint=[noisy])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "lint gate" in outcome.reason
    lines = outcome.reason.splitlines()
    assert len(lines) <= 45 and lines[-1] == "Found 120 errors."
    assert sum("repeated hint" in line for line in lines) <= 1
    assert "src/mod.py:1:1" in outcome.reason and "src/mod.py:120:1" not in outcome.reason
