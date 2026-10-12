"""A refactor chore of a feedback fix unit (L4-FBK-005, D5): the step may not change the tests."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_single

from .conftest import IMPL, result
from .test_single_phase import NEW_TESTS, TASK

FINDINGS = ["FB-001"]
TEST_FILE = "tests/test_pricing.py"  # in the base commit
REFACTORED = IMPL + "\n# tidied\n"


def restored(bench) -> list[dict]:
    return bench.events("guard.restored")


def test_a_refactor_that_also_edits_a_test_gets_the_test_back_and_keeps_the_source_change(make_bench):
    """SCN-FBK-11"""
    bench = make_bench([Step(writes={"src/pytdd/pricing.py": REFACTORED, TEST_FILE: "# weakened\n"},
                             structured=result("single"))])  # fmt: skip
    before = (bench.wb.worktree / TEST_FILE).read_text()
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1, kind="refactor")
    assert done.status == "ok", done.reason
    assert (bench.wb.worktree / TEST_FILE).read_text() == before
    assert (bench.wb.worktree / "src/pytdd/pricing.py").read_text() == REFACTORED
    [event] = restored(bench)
    assert event["paths"] == [TEST_FILE] and event["reason"] == "feedback_refactor" and event["task"] == TASK.key
    assert [e for e in bench.events("gate.finished") if e["name"] == "test"]  # the gate ran, on the original test
    changed = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "src/pytdd/pricing.py" in changed and TEST_FILE not in changed
    [exempt] = bench.events("task.tdd_exempt")
    assert exempt["finding"] == "FB-001"


def test_a_refactor_that_changes_only_a_test_fails_as_nothing_changed(make_bench):
    """SCN-FBK-12"""
    step = Step(writes={TEST_FILE: "# weakened\n", "tests/test_new.py": NEW_TESTS}, structured=result("single"))
    bench = make_bench([step])
    head = bench.wb.head()
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1, kind="refactor")
    assert done.status == "failed" and done.reason == "nothing changed"
    [event] = restored(bench)
    assert event["paths"] == ["tests/test_new.py", TEST_FILE]
    assert bench.wb.head() == head and not (bench.wb.worktree / "tests/test_new.py").exists()
    assert bench.events("task.done") == [] and bench.events("task.tdd_exempt") == []


def test_an_ordinary_chore_is_not_a_refactor_chore(make_bench):
    """SCN-FBK-11 (regression): the `feedback_refactor` restore belongs to refactor chores only"""
    step = Step(writes={"src/pytdd/pricing.py": REFACTORED, TEST_FILE: "# weakened\n"}, structured=result("single"))
    bench = make_bench([step])
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1)
    assert done.status == "ok", done.reason
    assert restored(bench) == []  # the test-path freeze of every chore put the file back, as `guard.test_tamper`
    assert [e["path"] for e in bench.events("guard.test_tamper")] == [TEST_FILE]
