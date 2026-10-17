"""M1.13 lines 11-12 (W-C1, SPEC L4-VER-006, L4-VER-009): a tests chore that cites a criterion needs a test that looks
at the answer (fails by assertion on the zero values), as the verifier would find out a round later; a coverage chore
does not."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .conftest import KNOWN, green_step, red_step, result
from .test_single_phase import NEW_TESTS, UNIT_TASK

BOUND = Task("1.2", "1.2", f"1.2 New tests bypass the server (F-0a1b2c3d; {KNOWN})", False, " ", 0, 3, 3)
FINDINGS = ["F-0a1b2c3d"]
PASSES_ON_ZERO = "from pytdd.pricing import total\n\n\ndef test_total_of_nothing_is_zero():\n    assert not total([])\n"


def run_bound(make_bench, step: Step, *, task: Task = BOUND):
    bench = make_bench([red_step(), green_step(), step])
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().rstrip("\n") + f"\n- [ ] {task.title}\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a second task")
    red = run_red(bench.wb, UNIT_TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert run_green(bench.wb, UNIT_TASK, red, attempt=1).status == "ok"
    return bench, run_single(bench.wb, task, FINDINGS, attempt=1, kind="tests")


def test_a_test_that_fails_on_the_zero_values_is_accepted_and_recorded_as_discriminating(make_bench):
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single")))
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert added["tests"] == ["tests.test_more::test_total_of_two"]
    assert added["discriminating"] == ["tests.test_more::test_total_of_two"]


def test_tests_that_pass_on_the_zero_values_and_the_base_fail_the_attempt_naming_them(make_bench):
    bench, done = run_bound(
        make_bench, Step(writes={"tests/test_more.py": PASSES_ON_ZERO}, structured=result("single"))
    )
    assert done.status == "failed"
    assert "tests.test_more::test_total_of_nothing_is_zero" in done.reason
    assert "zero" in done.reason and "assertion" in done.reason
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_one_discriminating_test_is_enough_when_others_only_run_the_code(make_bench):
    both = NEW_TESTS + "\n\n" + PASSES_ON_ZERO.split("\n\n\n", 1)[1]
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": both}, structured=result("single")))
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert added["discriminating"] == ["tests.test_more::test_total_of_two"] and len(added["tests"]) == 2


def test_a_coverage_chore_without_a_criterion_is_not_discriminated_early(make_bench):
    task = Task("1.2", "1.2", "1.2 Changed code that no test runs (H-0a1b2c3d)", False, " ", 0, 3, 3)
    bench, done = run_bound(
        make_bench, Step(writes={"tests/test_more.py": PASSES_ON_ZERO}, structured=result("single")), task=task
    )
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert "discriminating" not in added


def test_single_tests_tells_the_agent_to_tag_with_the_cited_criterion_and_to_use_the_interface_the_design_names():
    from l4.implementer.prompt import load_template, render_prompt

    from .test_prompt import ctx

    template = load_template("single_tests")
    assert template.version == 5
    assert "cites a criterion" in template.body and "fail by assertion" in template.body
    assert "interface the design names" in template.body and "new names" in template.body
    assert render_prompt("single", ctx(adds_tests=True)).template_version == "contract@11+single_tests@5"
