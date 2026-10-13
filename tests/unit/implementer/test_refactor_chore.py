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


# --- a retaken item whose work is already done (L4-FBK-005, review #8 follow-up) ------------------------------------


def test_a_retaken_refactor_with_nothing_to_change_completes_as_already_done(make_bench):
    bench = make_bench([Step(structured=result("single"))])
    src_before = (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1, kind="refactor", retake=True)
    assert done.status == "ok", done.reason
    assert (bench.wb.worktree / "src/pytdd/pricing.py").read_text() == src_before
    [event] = bench.events("task.done")
    assert event["tdd"] == "already-done" and event["reason"] == "retaken FB-001: nothing left to change"
    assert bench.events("task.tdd_exempt") == [] and bench.events("task.attempt_failed") == []
    # only the tick of the task and the ledger are committed: no source or test file
    changed = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert all(c.endswith("tasks.md") or "/.l4/" in c or c.startswith(".l4") for c in changed), changed
    assert "L4-TDD: already-done" in bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert "- [x] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_retaken_refactor_that_only_touched_a_test_is_nothing_left_too(make_bench):
    step = Step(writes={TEST_FILE: "# weakened\n"}, structured=result("single"))
    bench = make_bench([step])
    before = (bench.wb.worktree / TEST_FILE).read_text()
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1, kind="refactor", retake=True)
    assert done.status == "ok" and (bench.wb.worktree / TEST_FILE).read_text() == before
    assert [e["tdd"] for e in bench.events("task.done")] == ["already-done"]


def test_a_first_take_with_nothing_to_change_still_fails(make_bench):
    bench = make_bench([Step(structured=result("single"))])
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1, kind="refactor")
    assert done.status == "failed" and done.reason == "nothing changed"
    assert bench.events("task.done") == []


def test_a_retaken_refactor_that_changes_something_is_an_ordinary_chore(make_bench):
    bench = make_bench([Step(writes={"src/pytdd/pricing.py": REFACTORED}, structured=result("single"))])
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1, kind="refactor", retake=True)
    assert done.status == "ok", done.reason
    assert [e["tdd"] for e in bench.events("task.done")] == ["exempt"]
