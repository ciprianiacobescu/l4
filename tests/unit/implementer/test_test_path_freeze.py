"""The test-path freeze (SPEC L4-IMP-006 (7)): green and a fix chore may not change any path of the test globs."""

from dataclasses import replace

from l4.agents.fake import Step
from l4.implementer.guardnotes import guard_note_text, note_of
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .conftest import IMPL, red_step, result
from .test_single_phase import NEW_TESTS, run_tests_chore
from .test_tdd_green import CORRECTED, TASK, answer_naming, two_test_red

NEW_FILE = "tests/test_more.py"
PRE_EXISTING = "tests/test_pricing.py"  # in the base commit, not a file any red step of the task wrote
RULE = "test path freeze"


def green_after_red(make_bench, green: Step, task: Task = TASK):
    bench = make_bench([red_step(), green])
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    return bench, red, run_green(bench.wb, task, red, attempt=1)


def freeze_events(bench) -> list[dict]:
    return [e for e in bench.events("guard.test_tamper") if e.get("rule") == RULE]


def test_green_that_adds_a_new_test_file_has_it_removed_and_the_retry_note_names_it(make_bench):
    """SCN-IMP-150"""
    step = Step(writes={"src/pytdd/pricing.py": IMPL, NEW_FILE: NEW_TESTS}, structured=result("green"))
    bench, _, green = green_after_red(make_bench, step)
    assert green.status == "ok", green.reason
    assert not (bench.wb.worktree / NEW_FILE).exists()
    [event] = freeze_events(bench)
    assert event["path"] == NEW_FILE and event["action"] == "removed" and event["phase"] == "green"
    note = guard_note_text([note_of("guard.test_tamper", event)])
    assert f"green may not change test files: {NEW_FILE} was put back" in note
    assert "ask a question if a test is wrong" in note


def test_green_that_changes_a_pre_existing_test_has_it_restored(make_bench):
    """SCN-IMP-151"""
    bench = make_bench([red_step(), Step(structured=result("green"))])
    before = (bench.wb.worktree / PRE_EXISTING).read_text()
    weakened = before.replace("== 3.75", "== 3.75 or True")
    assert weakened != before
    bench.adapter._script[1] = Step(
        writes={"src/pytdd/pricing.py": IMPL, PRE_EXISTING: weakened}, structured=result("green")
    )
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / PRE_EXISTING).read_text() == before
    [event] = freeze_events(bench)
    assert event["path"] == PRE_EXISTING and event["action"] == "restored"


def test_a_path_a_task_unfrozen_event_names_is_kept(make_bench, raw):
    """SCN-IMP-152"""
    step = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), step])
    red = run_red(bench.wb, TASK, attempt=1)
    answer_naming(bench, raw, "Change `tests/test_discount.py:9` to use a 100.0 amount.")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == CORRECTED
    assert freeze_events(bench) == []


def test_a_test_infra_task_may_change_test_paths_in_green(make_bench):
    """SCN-IMP-152 (the human `[test-infra]` tag frees every test path of the task)"""
    tagged = replace(TASK, title=f"{TASK.title} [test-infra]")
    step = Step(writes={"src/pytdd/pricing.py": IMPL, NEW_FILE: NEW_TESTS}, structured=result("green"))
    bench, _, green = green_after_red(make_bench, step, tagged)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / NEW_FILE).exists() and freeze_events(bench) == []


def test_a_fix_chore_loses_a_new_test_file_and_a_test_chore_keeps_it(make_bench):
    """SCN-IMP-153"""
    step = Step(writes={NEW_FILE: NEW_TESTS, "src/pytdd/pricing.py": IMPL}, structured=result("single"))
    bench, done = run_tests_chore(make_bench, step, kind="fix")
    assert done.status == "ok", done.reason
    assert not (bench.wb.worktree / NEW_FILE).exists()
    [event] = freeze_events(bench)
    assert event["path"] == NEW_FILE and event["action"] == "removed" and event["phase"] == "single"
    assert "a fix chore may not change test files" in guard_note_text([note_of("guard.test_tamper", event)])


def test_a_test_chore_keeps_its_new_test_file_as_before(make_bench):
    """SCN-IMP-153"""
    bench, kept = run_tests_chore(make_bench, Step(writes={NEW_FILE: NEW_TESTS}, structured=result("single")))
    assert kept.status == "ok", kept.reason
    assert (bench.wb.worktree / NEW_FILE).exists() and freeze_events(bench) == []


def test_a_test_infra_fix_chore_may_change_test_paths(make_bench):
    """SCN-IMP-152 (the human `[test-infra]` tag, on a fix chore)"""
    step = Step(writes={NEW_FILE: NEW_TESTS, "src/pytdd/pricing.py": IMPL}, structured=result("single"))
    bench = make_bench([step])
    task = replace(TASK, title=f"{TASK.title} [test-infra]")
    done = run_single(bench.wb, task, ["F-6eb0cc43"], attempt=1, kind="fix")
    assert done.status == "ok", done.reason
    assert (bench.wb.worktree / NEW_FILE).exists() and freeze_events(bench) == []


def test_configured_test_folders_of_other_stacks_are_frozen_too(make_bench):
    """SCN-IMP-154"""
    shop, web = "Api/Shop.Tests/PriceTests.cs", "web/tests/price.test.ts"
    bench = make_bench([red_step(), Step(structured=result("green"))])
    tdd = bench.wb.cfg.tdd
    tdd.test_globs = [*tdd.test_globs, "**/*.Tests/**", "web/tests/**"]
    for rel in (shop, web):
        (bench.wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (bench.wb.worktree / rel).write_text("// the proof\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "stack tests")
    bench.adapter._script[1] = Step(
        writes={"src/pytdd/pricing.py": IMPL, shop: "// weakened\n", web: "// weakened\n"},
        structured=result("green"),
    )
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / shop).read_text() == "// the proof\n"
    assert (bench.wb.worktree / web).read_text() == "// the proof\n"
    assert sorted((e["path"], e["action"]) for e in freeze_events(bench)) == [(shop, "restored"), (web, "restored")]
