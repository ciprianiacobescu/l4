"""M1.12 lines 24-25 (F1, L4-VER-006): a test chore that a human decision opens must assert that decision.

The damage line: a failing test accepted as a result must never become a way to hand off a red test."""

from l4.agents.fake import Step
from l4.implementer.prompt import load_template, render_prompt
from l4.implementer.tdd import run_single

from .conftest import result
from .test_prompt import ctx
from .test_single_phase import HOLD, NEW_TESTS, TESTS_TASK

DECISION = "the code is wrong: total must refuse an empty list instead of returning 0"
FAILING = "from pytdd.pricing import total\n\n\ndef test_total_refuses_an_empty_list():\n    assert total([]) is None\n"
QUESTION = [
    {
        "title": "total([]) disagrees with the decision",
        "context": "the test tests/test_more.py::test_total_refuses_an_empty_list asserts Q-001 and fails",
        "kind": "technical",
    }
]


def seed_decision(bench, text: str) -> None:
    proposal = bench.wb.ref.path / "proposal.md"
    line = (
        f"\n- {HOLD[0]} (major): Changed code that no test runs: Decided by human in Q-001: {text}. "
        "Add tests that run the changed code the hold names: `src/pytdd/pricing.py::total`.\n"
    )
    proposal.write_text(proposal.read_text() + line)
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "the decision")


def run_decided(make_bench, step: Step, text: str = DECISION, *, attempt: int = 1):
    from l4.implementer.tdd import run_green, run_red

    from .conftest import green_step, red_step
    from .test_single_phase import UNIT_TASK

    bench = make_bench([red_step(), green_step(), step])
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().rstrip("\n") + "\n- [ ] 1.2 Changed code that no test runs (H-0a1b2c3d)\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a second task")
    red = run_red(bench.wb, UNIT_TASK, attempt=1)
    assert run_green(bench.wb, UNIT_TASK, red, attempt=1).status == "ok"
    seed_decision(bench, text)
    return bench, run_single(bench.wb, TESTS_TASK, HOLD, attempt=attempt, kind="tests")


def test_single_tests_and_single_state_the_rule_for_a_task_a_decision_opens():
    for name, version in (("single_tests", 5), ("single", 3)):
        template = load_template(name)
        assert template.version == version
        assert "begins with a decision by a human" in template.body
    assert "MUST assert the behaviour that decision describes" in load_template("single_tests").body
    assert "report status blocked" in load_template("single_tests").body
    text = render_prompt("single", ctx(adds_tests=True)).text
    assert (
        "begins with a decision by a human" in text
        and (render_prompt("single", ctx(adds_tests=True)).template_version) == "contract@13+single_tests@5"
    )


def test_a_failing_test_with_a_blocked_report_raises_the_question_and_is_never_committed(make_bench):
    step = Step(
        writes={"tests/test_more.py": FAILING},
        structured=result("single", status="blocked", questions=QUESTION),
    )
    bench, done = run_decided(make_bench, step)
    assert done.status == "blocked" and [q.kind for q in done.questions] == ["technical"]
    assert "Q-001" in done.questions[0].context and "test_total_refuses_an_empty_list" in done.questions[0].context
    assert bench.wb.is_clean() and not (bench.wb.worktree / "tests" / "test_more.py").exists()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"] and bench.events("task.tests_added") == []


def test_a_red_test_reported_as_done_is_still_a_failure_and_is_discarded(make_bench):
    """Adversarial: the way to hand off a red test is to report `done` with one. It stays a failed step."""
    step = Step(writes={"tests/test_more.py": FAILING}, structured=result("single"))
    before_head = None
    bench, done = run_decided(make_bench, step)
    assert done.status == "failed"
    assert not (bench.wb.worktree / "tests" / "test_more.py").exists() and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"] and before_head is None


def test_tests_that_all_pass_against_code_the_decision_calls_wrong_get_a_retry_naming_the_decision(make_bench):
    step = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, done = run_decided(make_bench, step)
    assert done.status == "failed"
    assert "Q-001" in done.reason and "asserts what the code does now" in done.reason
    assert "the decision above says otherwise" in done.reason
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()


def test_the_retry_is_one_attempt_not_a_trap(make_bench):
    """After being told once the agent may explain in its notes: attempt 2 is judged by the gate alone."""
    step = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, done = run_decided(make_bench, step, attempt=2)
    assert done.status == "ok", done.reason


def test_a_decision_that_does_not_call_the_code_wrong_leaves_passing_tests_alone(make_bench):
    step = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, done = run_decided(make_bench, step, "add tests, do not remove the code")
    assert done.status == "ok", done.reason
