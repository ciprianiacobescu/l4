"""L4-IMP-121 and L4-IMP-122 (SCN-IMP-640..647): after a targeted red, a regression that green's whole run shows
switches the unit back to whole-suite red runs and says so in green's reason. The gates are the real ones on the fixture
unit; FAKE wrappers (`failing`, `dropping`) change what green's whole run and its re-run report."""

from dataclasses import replace
from pathlib import Path

from l4.agents.fake import Step
from l4.implementer import red_check
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task
from l4.state import restart
from l4.state.fold import HANDLERS, fold
from l4.state.ledger import LedgerWriter, read_ledger
from l4.verifier.gates import run_test_gate

from ._targeted import FILE, PRE, TASK, FakeGates, bench_of, dropping, failing, red
from .conftest import UNKNOWN, green_step, red_step, result

AGAIN = "; failed again on a re-run (L4-IMP-105): "
REGRESSED = (
    "; the red step of this task ran only its new test files (L4-IMP-122): if no change of the code can make these "
    "tests pass, report status blocked with a question that names the test file"
)
MISSING = (
    "; the red step of this task ran only its new test files (L4-IMP-122): the whole suite reports these tests under "
    "other ids than the targeted command did, so no change of the code can make them pass: report status blocked and "
    "say so; a person fixes gates.test.targeted and runs l4 restart"
)
COLLECTION = (
    "; the red step of this task ran only its new test files (L4-IMP-122): if no change of the code can make this "
    "file collect, report status blocked with a question that names the test file"
)
MODULE = FILE[:-3].replace("/", ".")
RED_ID = f"{MODULE}::test_codes_exist"


def targeted_red(make_bench, *greens: Step, task: Task = TASK, **over):
    bench = bench_of(make_bench, [red(), *greens], **over)
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok" and out.check == "targeted", out.reason
    return bench, out


def disabled(bench) -> list[dict]:
    return bench.events("task.red_check_disabled")


# --- SCN-IMP-640, 641: a regressed base test ---------------------------------------------------------------------


def test_scn_imp_640_a_regression_that_fails_the_run_and_the_re_run_records_the_switch_and_says_why(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed"
    assert done.reason == f"green broke existing tests: {PRE}{AGAIN}{PRE}{REGRESSED}"
    [event] = disabled(bench)
    assert (event["task"], event["attempt"], event["why"]) == ("1.1", 1, "regressed")
    assert event["tests"] == [PRE] and event["red_sha"] == out.sha


def test_scn_imp_641_a_regression_that_passes_on_the_re_run_records_nothing(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": failing(PRE)})  # the re-run is the real one: the test passes
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "ok", done.reason
    assert [e["stopped"] for e in bench.events("task.tests_rechecked")] == ["passed"]
    assert disabled(bench) == [] and bench.events("task.done")


def test_the_tests_of_the_record_are_at_most_twenty(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    many = [f"tests.test_pricing::test_old_{i:02}" for i in range(25)]
    bench_base = out.base_report
    for i in many:  # FAKE: a base that holds 25 more passing tests, all of which fail in green's run
        bench_base.tests[i] = type(bench_base.tests[PRE])(i, "passed")
    FakeGates(bench, change={"test": failing(*many), "test-recheck": failing(*many)})
    run_green(bench.wb, TASK, out, attempt=1)
    [event] = disabled(bench)
    assert len(event["tests"]) == 20


# --- SCN-IMP-643: a red test missing from green's report ---------------------------------------------------------


def test_scn_imp_643_a_red_test_missing_from_the_report_records_the_switch_and_names_the_command(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": dropping(RED_ID)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed"
    assert done.reason == f"red tests still failing: {RED_ID}{MISSING}"
    [event] = disabled(bench)
    assert event["why"] == "ids_missing" and event["tests"] == [RED_ID] and event["red_sha"] == out.sha
    assert "unfreeze" not in done.reason


def test_a_red_test_that_is_present_and_still_failing_records_nothing_and_has_no_suffix(make_bench):
    bench, out = targeted_red(make_bench, Step(structured=result("green")))
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed" and done.reason.startswith("red tests still failing: ")
    assert "L4-IMP-122" not in done.reason and disabled(bench) == []


# --- SCN-IMP-642: the switch lasts -------------------------------------------------------------------------------

SECOND = Task("1.2", "1.2", "1.2 More", False, " ", 0, 2, 3)
OTHER_FILE = "tests/test_second.py"
SECOND_TESTS = (
    "import pytest\nfrom pytdd import pricing\n\n\n"
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_second_exists():\n    assert hasattr(pricing, "SECOND")\n'
)


def second_red() -> Step:
    return Step(
        writes={OTHER_FILE: SECOND_TESTS},
        structured=result("red", task_ids=["1.2"], tests_added=[f"{OTHER_FILE}::test_second_exists"],
                          criteria_ids=[UNKNOWN]),
    )  # fmt: skip


def switched_unit(make_bench, *extra: Step):
    bench, out = targeted_red(make_bench, green_step(), *extra)
    fake = FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    assert run_green(bench.wb, TASK, out, attempt=1).status == "failed" and len(disabled(bench)) == 1
    fake.restore()  # the real gates again
    return bench


def test_scn_imp_642_a_later_red_step_runs_the_whole_suite_with_unit_switched(make_bench):
    bench = switched_unit(make_bench, second_red())
    fake = FakeGates(bench)
    out = run_red(bench.wb, SECOND, attempt=1)
    assert out.check == "full" and "test-targeted" not in fake.names and "test" in fake.names
    [why] = bench.events("task.red_check_full")
    assert why["why"] == "unit_switched" and why["task"] == "1.2"
    assert bench.events("task.red_ok")[-1]["check"] == "full"


def test_scn_imp_642_a_fix_unit_runs_the_whole_suite_too(make_bench):
    bench = switched_unit(make_bench, second_red())
    bench.wb.event_context = {"fix_unit": "fix-1"}
    fake = FakeGates(bench)
    out = run_red(bench.wb, SECOND, attempt=1)
    assert out.check == "full" and "test-targeted" not in fake.names
    assert bench.events("task.red_check_full")[-1]["why"] == "unit_switched"


def test_scn_imp_642_a_new_run_of_the_unit_reads_the_switch_from_its_ledger(make_bench):
    bench = switched_unit(make_bench)
    later = LedgerWriter.open(bench.wb.ref.path, bench.wb.ref.id, "r-20261101T0000Z-beef", redactor=bench.wb.redactor)
    later.append("run.started", iteration=2)  # `l4 retry` and a new run keep the unit's earlier ledgers
    assert red_check.unit_switched(read_ledger(bench.wb.ref.path).events)


def test_scn_imp_642_a_restarted_unit_has_a_new_ledger_with_no_switch(tmp_path: Path):
    """`l4 restart` starts the unit on a new branch with a new ledger (state/restart.py): no record, so the key is read
    again. Only the reading is exercised here, not the restart."""
    assert not red_check.unit_switched(read_ledger(tmp_path).events)


# --- SCN-IMP-644, 645, 647 ---------------------------------------------------------------------------------------


STUB_TESTS = (
    "import pytest\nfrom pytdd.second import second\n\n\n"
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_second():\n    assert second() == 2\n'
)


def test_scn_imp_644_a_regression_in_a_later_task_whose_own_red_ran_whole_still_records_the_switch(make_bench):
    stub_red = Step(  # a stub of its own: this red step runs the whole suite
        writes={OTHER_FILE: STUB_TESTS, "src/pytdd/second.py": "def second():\n    raise NotImplementedError\n"},
        structured=result("red", task_ids=["1.2"], tests_added=[f"{OTHER_FILE}::test_second"], criteria_ids=[UNKNOWN]),
    )  # fmt: skip
    second_green = Step(
        writes={"src/pytdd/second.py": "def second():\n    return 2\n"}, structured=result("green", task_ids=["1.2"])
    )
    bench, out = targeted_red(make_bench, green_step(), stub_red, second_green)
    assert run_green(bench.wb, TASK, out, attempt=1).status == "ok"
    second = run_red(bench.wb, SECOND, attempt=1)
    assert second.status == "ok" and second.check == "full", second.reason
    assert [e["check"] for e in bench.events("task.red_ok")] == ["targeted", "full"]
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    done = run_green(bench.wb, SECOND, second, attempt=1)
    assert done.status == "failed" and done.reason == f"green broke existing tests: {PRE}{AGAIN}{PRE}"  # no suffix
    [event] = disabled(bench)
    assert (event["task"], event["why"], event["tests"]) == ("1.2", "regressed", [PRE])


def test_scn_imp_645_the_switch_is_recorded_once(make_bench):
    bench, out = targeted_red(make_bench, green_step(), green_step())
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    first = run_green(bench.wb, TASK, out, attempt=1)
    second = run_green(bench.wb, TASK, out, attempt=2)
    assert first.status == second.status == "failed" and len(disabled(bench)) == 1
    assert second.reason.endswith(REGRESSED)  # the suffix follows the task's own red, on every failing attempt


def test_scn_imp_647_a_unit_with_no_targeted_red_records_no_switch_and_no_suffix(make_bench):
    bench = bench_of(make_bench, [red_step(), green_step()])  # a stub: red ran the whole suite (`check: full`)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok" and out.check == "full"
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.reason == f"green broke existing tests: {PRE}{AGAIN}{PRE}"
    assert disabled(bench) == []


def test_scn_imp_647_a_0460_unit_has_no_check_key_and_no_switch(make_bench):
    bench = make_bench([red_step(), green_step()])  # no `red_check`: the events carry no `check`
    out = run_red(bench.wb, TASK, attempt=1)
    assert "check" not in bench.events("task.red_ok")[0]
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert "L4-IMP-122" not in done.reason and disabled(bench) == []


# --- SCN-IMP-646: verification stays whole-suite -----------------------------------------------------------------


def test_scn_imp_646_verification_runs_the_whole_command_of_0460_on_a_unit_with_targeted_reds(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    assert run_green(bench.wb, TASK, out, attempt=1).status == "ok"
    fake = FakeGates(bench)
    run_test_gate(bench.wb, must_contain=())  # step 3's test gate
    [(name, command)] = fake.calls
    assert (name, command) == ("test", bench.wb.cfg.gates.test.command) and "{files}" not in command
    sources = [p for p in (Path(__file__).parents[3] / "src" / "l4" / "verifier").glob("*.py")]
    assert sources and not [p.name for p in sources if "red_check" in p.read_text() or ".targeted" in p.read_text()]


# --- SCN-IMP-642, SCN-IMP-645, SCN-IMP-647: more cases of the switch ---------------------------------------------


def test_scn_imp_645_a_switch_first_seen_on_a_later_attempt_names_that_attempt(make_bench):
    bench, out = targeted_red(make_bench, Step(structured=result("green")), green_step())
    first = run_green(bench.wb, TASK, out, attempt=1)  # a red test still fails: no regression, nothing recorded
    assert first.status == "failed" and first.reason.startswith("red tests still failing") and disabled(bench) == []
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    second = run_green(bench.wb, TASK, out, attempt=2, previous_failure=first.reason)
    assert second.status == "failed" and second.reason.endswith(REGRESSED)
    [event] = disabled(bench)
    assert (event["attempt"], event["why"]) == (2, "regressed")


def test_scn_imp_647_a_red_test_missing_after_a_whole_red_records_nothing_and_has_no_suffix(make_bench):
    bench = bench_of(make_bench, [red_step(), green_step()])  # a stub: this red step ran the whole suite
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok" and out.check == "full"
    gone = sorted(out.new_ids)[0]
    FakeGates(bench, change={"test": dropping(gone)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed" and done.reason == f"red tests still failing: {gone}"
    assert disabled(bench) == []


def test_scn_imp_652_a_unit_set_back_to_full_still_records_the_switch_from_its_ledger(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    bench.wb.cfg.gates.test.red_check = "full"  # the key is read for a red step only: green decides from the ledger
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed" and done.reason.endswith(REGRESSED)
    assert [e["why"] for e in disabled(bench)] == ["regressed"]


def test_scn_imp_652_a_red_step_of_a_full_configuration_writes_no_new_record_even_after_a_switch(make_bench):
    bench = switched_unit(make_bench, second_red())
    bench.wb.cfg.gates.test.red_check = "full"
    out = run_red(bench.wb, SECOND, attempt=1)
    assert out.status == "ok" and out.check == "full"
    assert "check" not in bench.events("task.red_ok")[-1] and len(bench.events("task.red_check_full")) == 0


# --- SCN-IMP-650, 651: a failure that a frozen red file can cause and green cannot fix ----------------------------


def collecting(*names: str):
    """FAKE: the result with a collection error for each of `names` (a module that does not import)."""

    def change(out):
        return replace(out, report=replace(out.report, collection_errors=list(names)))

    return change


def no_report(out):
    """FAKE: a whole run that wrote no report."""
    return replace(out, report=None, status="fail", reason="report missing: .l4-out/junit.xml")


def timed_out(out):
    """FAKE: a whole run that hit `gates.timeout`."""
    return replace(out, report=None, status="fail", timed_out=True, reason="gate test timed out after 5s")


def test_scn_imp_650_a_collection_error_that_names_a_file_of_the_red_records_the_switch_and_says_why(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": collecting(FILE)})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed" and done.reason == f"tests not collected: {FILE}{COLLECTION}"
    [event] = disabled(bench)
    assert (event["why"], event["tests"], event["red_sha"]) == ("green_collection", [FILE], out.sha)


def test_scn_imp_650_a_collection_error_of_another_file_records_nothing(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": collecting("tests/test_pricing.py")})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.reason == "tests not collected: tests/test_pricing.py" and disabled(bench) == []


def test_scn_imp_650_a_collection_error_after_a_whole_red_records_nothing(make_bench):
    bench = bench_of(make_bench, [red_step(), green_step()])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.check == "full"
    FakeGates(bench, change={"test": collecting("tests/test_discount.py")})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.reason == "tests not collected: tests/test_discount.py" and disabled(bench) == []


def test_scn_imp_650_a_collection_error_names_a_file_of_the_resumed_targeted_red_too(make_bench):
    from l4.implementer.tdd import resume_red

    bench, out = targeted_red(make_bench, green_step())
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.files == (FILE,)
    FakeGates(bench, change={"test": collecting(MODULE)})  # the dotted module of the file
    done = run_green(bench.wb, TASK, resumed, attempt=1)
    assert done.reason.endswith(COLLECTION) and [e["why"] for e in disabled(bench)] == ["green_collection"]


def test_scn_imp_651_a_whole_run_with_no_readable_report_after_a_targeted_red_records_the_switch(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": no_report})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed"
    assert done.reason == "the test gate produced no readable report (report missing: .l4-out/junit.xml)"
    [event] = disabled(bench)
    assert (event["why"], event["tests"], event["red_sha"]) == ("green_no_report", [], out.sha)


def test_scn_imp_651_a_whole_run_that_times_out_after_a_targeted_red_records_the_switch(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": timed_out})
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed" and "L4-IMP-122" not in done.reason
    assert [e["why"] for e in disabled(bench)] == ["green_no_report"]


def test_scn_imp_651_a_whole_run_with_no_report_after_a_whole_red_records_nothing(make_bench):
    bench = bench_of(make_bench, [red_step(), green_step()])
    out = run_red(bench.wb, TASK, attempt=1)
    FakeGates(bench, change={"test": no_report})
    assert run_green(bench.wb, TASK, out, attempt=1).status == "failed" and disabled(bench) == []


def test_scn_imp_651_the_switch_of_a_failure_without_a_report_is_recorded_once(make_bench):
    bench, out = targeted_red(make_bench, green_step(), green_step())
    FakeGates(bench, change={"test": no_report})
    run_green(bench.wb, TASK, out, attempt=1)
    run_green(bench.wb, TASK, out, attempt=2)
    assert len(disabled(bench)) == 1


# --- SCN-IMP-642, SCN-IMP-639: a restarted unit has no switch; the ledger folds ---------------------------------------


def test_scn_imp_642_the_folder_that_l4_restart_builds_has_no_switch(make_bench, tmp_path: Path):
    bench = switched_unit(make_bench)
    git, ref = bench.wb.git, bench.wb.ref
    assert red_check.unit_switched(read_ledger(ref.path).events)  # the old unit has it
    relative = ref.path.resolve().relative_to(bench.wb.worktree.resolve()).as_posix()
    git.run("add", "-f", "--", relative)
    git.run("commit", "-q", "-m", "the old unit's ledger")
    old_head = git.rev_parse("HEAD")
    private = tmp_path / "private"
    git.run("worktree", "add", "--quiet", "--detach", str(private), "main")
    unit_dir = private / relative
    restart._build_folder(git, ref, old_head, relative, unit_dir, "main")  # the step that `l4 restart` makes (step 3)
    assert not (unit_dir / ".l4" / "ledger").exists()
    assert not red_check.unit_switched(read_ledger(unit_dir).events)
    assert not red_check.unit_targeted(read_ledger(unit_dir).events)


NEW_TYPES = {"task.red_check_full", "task.red_check_disabled"}


def test_scn_imp_639_a_ledger_with_the_new_records_folds_as_one_without_them(make_bench):
    bench, out = targeted_red(make_bench, green_step())
    FakeGates(bench, change={"test": failing(PRE), "test-recheck": failing(PRE)})
    run_green(bench.wb, TASK, out, attempt=1)  # records `task.red_check_disabled`
    events = read_ledger(bench.wb.ref.path).events
    assert {e.type for e in events} >= {"task.red_ok", "task.red_check_disabled"}
    assert [e for e in events if e.type == "task.red_ok" and e.data.get("check") == "targeted"]
    # a harness that does not know them reads a type it does not fold as a plain record (fold.py): the same state
    assert not (NEW_TYPES | {"task.red_ok", "gate.finished"}) & HANDLERS.keys()
    known = [e for e in events if e.type not in NEW_TYPES]
    unit = bench.wb.ref.id
    new, old = (fold(e, unit).model_dump(exclude={"updated_at"}) for e in (events, known))  # the time of the last line
    assert new == old


def test_scn_imp_639_a_ledger_of_0460_folds_with_every_check_read_as_full_and_no_switch(make_bench):
    bench = make_bench([red_step(), green_step()])  # no `red_check` in the configuration: a 0.4.60 ledger
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok" and run_green(bench.wb, TASK, out, attempt=1).status == "ok"
    events = read_ledger(bench.wb.ref.path).events
    assert not NEW_TYPES & {e.type for e in events}
    assert all("check" not in e.data for e in events if e.type == "task.red_ok")
    assert not red_check.unit_switched(events) and not red_check.unit_targeted(events)  # a missing `check` is `full`
    assert fold(events, bench.wb.ref.id).tasks.done == ["1.1"]
