"""L4-IMP-118, L4-IMP-119, L4-IMP-120, L4-GAT-007, L4-GAT-009 (SCN-IMP-626/627, 633..639, 648 and SCN-GAT-13,
15..20): a red step of a `targeted` configuration runs only its new test files and falls back to the whole suite when
the run cannot decide. The gates are the real ones on the fixture unit; FAKE wrappers change what a gate run reports."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.deadline import DeadlineReached
from l4.gates.junit import TestCase
from l4.implementer import red_check as red_check_module
from l4.implementer import tdd
from l4.implementer.tdd import resume_red, run_green, run_red

from ..conftest import TEST_COMMAND
from ._targeted import CODES, FILE, HEAD, NEW_TESTS, PRE, TARGETED, TASK, FakeGates, bench_of, ok_red, red, two_files
from .conftest import KNOWN, RUN_ID, UNKNOWN, green_step, red_step, result


def finished(bench, *names: str) -> list[str]:
    return [e["name"] for e in bench.events("gate.finished") if e["name"] in names]


# --- SCN-IMP-626, SCN-GAT-13, SCN-IMP-638: a targeted step --------------------------------------------------------


def test_scn_imp_626_a_step_that_adds_only_a_test_module_runs_only_it(make_bench):
    bench, fake, out = ok_red(make_bench)
    assert out.status == "ok", out.reason
    assert fake.names == ["test-targeted"]  # the baseline ran before the wrapper; no `test` gate in the step
    command = next(c for n, c in fake.calls if n == "test-targeted")
    assert command == f"{TEST_COMMAND} {FILE}"
    [event] = bench.events("task.red_ok")
    assert event["check"] == "targeted" and event["files"] == [FILE]
    assert bench.events("task.red_check_full") == []
    module = FILE[:-3].replace("/", ".")
    assert out.check == "targeted" and out.new_ids == {
        f"{module}::test_codes_exist",
        f"{module}::test_save10_is_ten_percent",
    }


def test_scn_gat_13_the_targeted_run_is_its_own_gate_and_does_not_count_for_the_longest_run(make_bench):
    bench, fake, out = ok_red(make_bench)
    assert out.status == "ok", out.reason
    assert finished(bench, "test-targeted", "test") == ["test-targeted"]
    peak = bench.wb.gate_peak
    assert peak is None or peak[0] != "test-targeted"  # L4-IMP-099 counts only `baseline` and `test`


def test_scn_imp_627_full_changes_nothing_and_records_nothing(make_bench, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("choose must not run with red_check: full")

    monkeypatch.setattr(red_check_module, "choose", boom)
    bench = make_bench([red()], test={"command": TEST_COMMAND, "targeted": "not used {files}", "red_check": "full"})
    fake = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert fake.names == ["test"] and out.check == "full"
    [event] = bench.events("task.red_ok")
    assert "check" not in event and "files" not in event
    assert bench.events("task.red_check_full") == []


def test_scn_imp_627_a_0460_configuration_without_the_key_is_full(make_bench):
    bench = make_bench([red()])
    fake = FakeGates(bench)
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    assert fake.names == ["test"] and "check" not in bench.events("task.red_ok")[0]


# --- the eligibility rules, end to end (SCN-IMP-628, 629, 632) ------------------------------------------------------


def test_scn_imp_632_a_step_with_a_stub_runs_the_whole_suite(make_bench):
    bench = bench_of(make_bench, [red_step()])
    fake = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert fake.names[0] == "test" and "test-targeted" not in fake.names
    [why] = bench.events("task.red_check_full")
    assert why["why"] == "stubs" and why["task"] == "1.1" and why["attempt"] == 1 and len(why["detail"]) <= 300
    assert bench.events("task.red_ok")[0]["check"] == "full" and "files" not in bench.events("task.red_ok")[0]


def test_scn_imp_628_a_step_that_changes_an_existing_test_file_runs_the_whole_suite(make_bench):
    old = (Path(__file__).parents[2] / "fixtures" / "py_tdd" / "tests" / "test_pricing.py").read_text()
    step = Step(
        writes={"tests/test_pricing.py": old + "\n\n" + CODES.split("\n\n\n")[0].replace("pricing.", "pricing_mod."),
                FILE: NEW_TESTS},
        structured=result("red", tests_added=[f"{FILE}::test_codes_exist"], criteria_ids=[KNOWN, UNKNOWN]),
    )  # fmt: skip
    bench = bench_of(make_bench, [step])
    fake = FakeGates(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert fake.names[0] == "test" and "test-targeted" not in fake.names
    assert bench.events("task.red_check_full")[0]["why"] == "existing_file_changed"


def test_scn_imp_629_a_helper_in_the_step_runs_the_whole_suite(make_bench):
    step = red()
    step.writes["tests/conftest.py"] = "import pytest\n"
    bench = bench_of(make_bench, [step])
    fake = FakeGates(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert fake.names[0] == "test" and bench.events("task.red_check_full")[0]["why"] == "not_a_test_module"


# --- SCN-GAT-15..17, 20: the fallback ---------------------------------------------------------------------------------


def no_report(out):
    return replace(out, report=None, status="fail", reason="report missing: .l4-out/junit.xml")


def with_collection_error(out):
    return replace(out, report=replace(out.report, collection_errors=["tests.test_targeted"]))


def with_old_test(out):
    return replace(out, report=replace(out.report, tests={**out.report.tests, PRE: TestCase(PRE, "failed")}))


def drop_file_b(out):
    kept = {i: c for i, c in out.report.tests.items() if "test_b" not in i}
    return replace(out, report=replace(out.report, tests=kept))


def with_stray_id(out):
    return replace(out, report=replace(out.report, tests={**out.report.tests, "x": TestCase("x", "failed")}))


def one_passes(out):
    first = sorted(out.report.tests)[0]
    return replace(out, report=replace(out.report, tests={**out.report.tests, first: TestCase(first, "passed")}))


def one_skipped(out):
    first = sorted(out.report.tests)[0]
    return replace(out, report=replace(out.report, tests={**out.report.tests, first: TestCase(first, "skipped")}))


@pytest.mark.parametrize(
    ("why", "change", "step"),
    [
        ("no_report", no_report, red),
        ("collection_errors", with_collection_error, red),
        ("existing_tests_ran", with_old_test, red),
        ("file_without_tests", drop_file_b, two_files),
        ("id_without_file", with_stray_id, red),
        ("new_test_not_failing", one_passes, red),
        ("new_test_not_failing", one_skipped, red),
    ],
)
def test_scn_gat_15_to_17_each_unusable_run_runs_the_whole_suite_in_the_same_step(make_bench, why, change, step):
    bench = bench_of(make_bench, [step()])
    fake = FakeGates(bench, change={"test-targeted": change})
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason  # the whole run's verdict is the one a `full` step gets
    assert fake.names == ["test-targeted", "test"]
    [event] = bench.events("task.red_check_full")
    assert event["why"] == why and event["task"] == "1.1" and len(event["detail"]) <= 300
    [ok] = bench.events("task.red_ok")
    assert ok["check"] == "full" and "files" not in ok and out.check == "full"
    assert finished(bench, "test-targeted", "test") == ["test-targeted", "test"]


def test_scn_gat_15_the_no_report_detail_names_the_reason(make_bench):
    bench = bench_of(make_bench, [red()])
    FakeGates(bench, change={"test-targeted": no_report})
    run_red(bench.wb, TASK, attempt=1)
    assert "report missing" in bench.events("task.red_check_full")[0]["detail"]


def test_scn_gat_16_a_targeted_report_that_ran_an_old_test_is_not_judged(make_bench):
    """The old test fails in the targeted report; judged, that would be `red broke existing tests`."""
    bench = bench_of(make_bench, [red()])
    FakeGates(bench, change={"test-targeted": with_old_test})
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok" and not (out.reason or "").startswith("red broke existing tests")


def test_scn_gat_17_a_new_test_that_passes_gives_the_base_run_the_whole_runs_duration(make_bench, monkeypatch):
    seen: list[float] = []
    original = tdd.confirmed_by_base_run

    def spy(*args, **kw):
        seen.append(kw["head_seconds"])
        return original(*args, **kw)

    monkeypatch.setattr(tdd, "confirmed_by_base_run", spy)
    passing = HEAD + CODES.split("\n\n\n")[0] + "\n\n\n" + CODES.split("\n\n\n")[1].replace(
        '.get("SAVE10") == 10', ".get('SAVE10', 10) == 10"
    )  # fmt: skip
    bench = bench_of(make_bench, [red(tests=passing)])
    fake = FakeGates(
        bench,
        change={
            "test-targeted": lambda out: replace(out, seconds=0.5),
            "test": lambda out: replace(out, seconds=123.0),
        },
    )
    run_red(bench.wb, TASK, attempt=1)
    assert fake.names[:2] == ["test-targeted", "test"]
    assert bench.events("task.red_check_full")[0]["why"] == "new_test_not_failing"
    assert 0.5 not in seen and all(s == 123.0 for s in seen)  # never the targeted run's seconds


def test_scn_gat_18_a_targeted_run_that_times_out_fails_the_attempt_with_no_whole_run(make_bench):
    def timed_out(out):
        return replace(out, report=None, status="fail", timed_out=True, reason="timed out after 5s")

    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench, change={"test-targeted": timed_out})
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed"
    assert out.reason == "the test gate produced no readable report (timed out after 5s)"
    assert fake.names == ["test-targeted"] and bench.events("task.red_check_full") == []
    assert not (bench.wb.worktree / FILE).exists()


LEAK = (
    HEAD
    + "import sys\n\n\n"
    + f'@pytest.mark.l4("{KNOWN}")\ndef test_codes_exist():\n'
    + '    if any("test_pricing" in m for m in sys.modules):\n'
    + '        open("src/pytdd/leak.py", "w").write("x = 1\\n")\n'
    + '    assert hasattr(pricing, "CODES")\n\n\n'
    + f'@pytest.mark.l4("{UNKNOWN}")\ndef test_other():\n'
    + '    assert getattr(pricing, "CODES", {}).get("SAVE10") == 10\n'
)


def test_scn_gat_19_the_guard_runs_after_a_targeted_run(make_bench):
    leak = LEAK.replace('if any("test_pricing" in m for m in sys.modules):', "if True:")
    bench = bench_of(make_bench, [red(tests=leak)])
    fake = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith("test code changed production files while a gate ran")
    assert fake.names == ["test-targeted"] and not (bench.wb.worktree / "src" / "pytdd" / "leak.py").exists()


def test_scn_gat_19_the_guard_runs_after_the_whole_run_of_a_fallback(make_bench):
    bench = bench_of(
        make_bench, [red(tests=LEAK)]
    )  # the targeted run does not import `test_pricing`: it writes nothing
    fake = FakeGates(bench, change={"test-targeted": no_report})
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith("test code changed production files while a gate ran")
    assert fake.names == ["test-targeted", "test"] and not (bench.wb.worktree / "src" / "pytdd" / "leak.py").exists()


def test_scn_gat_20_the_fallback_starts_on_the_tree_the_step_had_before_the_targeted_run(make_bench):
    bench = bench_of(make_bench, [red()])
    leftover = bench.wb.worktree / "tests" / "leftover.txt"
    seen: dict[str, bool] = {}

    def litter(out):
        leftover.write_text("left by the targeted run\n")
        return no_report(out)

    fake = FakeGates(
        bench, change={"test-targeted": litter}, before={"test": lambda: seen.update(present=leftover.exists())}
    )
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert fake.names == ["test-targeted", "test"] and seen == {"present": False}  # removed before the gate `test` ran


def test_scn_gat_20_when_the_tree_cannot_be_put_back_the_gate_test_runs_anyway(make_bench, monkeypatch):
    monkeypatch.setattr(tdd, "tree_before", lambda wb: lambda: False)
    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench, change={"test-targeted": no_report})
    out = run_red(bench.wb, TASK, attempt=1)
    assert fake.names == ["test-targeted", "test"] and out.status == "ok", out.reason


def test_scn_gat_20_a_missing_put_back_does_not_stop_the_whole_run(make_bench, monkeypatch):
    monkeypatch.setattr(tdd, "tree_before", lambda wb: None)
    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench, change={"test-targeted": no_report})
    assert run_red(bench.wb, TASK, attempt=1).status == "ok" and fake.names == ["test-targeted", "test"]


# --- SCN-IMP-633: a flaky old test -----------------------------------------------------------------------------------


def test_scn_imp_633_a_flaky_old_test_cannot_fail_a_targeted_red(make_bench):
    def flaky(out):
        return replace(out, report=replace(out.report, tests={**out.report.tests, PRE: TestCase(PRE, "failed")}))

    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench, change={"test": flaky})  # a whole run would fail the old test once
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert "test" not in fake.names and "test-recheck" not in fake.names
    assert bench.events("task.tests_rechecked") == []


# --- SCN-IMP-634: every other verdict is the one a whole run gives ----------------------------------------------------

NOT_ASSERTION = (
    HEAD
    + f'@pytest.mark.l4("{KNOWN}")\ndef test_codes_exist():\n    raise RuntimeError("boom")\n\n\n'
    + f'@pytest.mark.l4("{UNKNOWN}")\ndef test_other():\n    raise RuntimeError("boom")\n'
)
UNCITED = (
    HEAD + 'def test_codes_exist():\n    assert hasattr(pricing, "CODES")\n\n\n'
    'def test_other():\n    assert hasattr(pricing, "CODES")\n'
)


@pytest.mark.parametrize("mode", ["full", "targeted"])
@pytest.mark.parametrize(
    ("name", "tests", "prefix"),
    [
        ("error", NOT_ASSERTION, "new tests fail with an error that is neither an assertion nor NotImplementedError"),
        ("uncited", UNCITED, "no new test traces"),
    ],
)
def test_scn_imp_634_a_reason_is_the_same_text_for_full_and_targeted(make_bench, mode, name, tests, prefix):
    bench = make_bench([red(tests=tests)], test={**TARGETED, "red_check": mode})
    fake = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    assert fake.names == (["test-targeted"] if mode == "targeted" else ["test"])
    assert out.status == "failed", out.reason
    assert out.reason.startswith(prefix) or prefix in out.reason, out.reason
    assert bench.events("task.red_check_full") == []
    SEEN.setdefault(name, {})[mode] = out.reason
    if len(SEEN[name]) == 2:  # both modes ran in this process (the order of the parameters is fixed)
        assert SEEN[name]["full"] == SEEN[name]["targeted"]


SEEN: dict[str, dict[str, str]] = {}


# --- SCN-IMP-635, SCN-IMP-636: green and a resumed red ------------------------------------------------------------


def test_scn_imp_635_green_judges_with_the_baseline_after_a_targeted_red(make_bench):
    bench = bench_of(make_bench, [red(), green_step()])
    run_gates = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert out.base_report is not None and PRE in out.base_report.tests
    assert out.new_ids.isdisjoint(out.base_report.tests)  # the baseline: none of the new tests is in it
    assert out.base_report.collection_errors == []
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "ok", done.reason
    assert run_gates.names == ["test-targeted", "test"]  # green's gate is the whole suite
    assert bench.events("task.tests_rechecked") == []


def test_scn_imp_635_a_red_test_missing_from_green_is_judged_as_after_a_full_red(make_bench):
    bench = bench_of(make_bench, [red(), Step(structured=result("green"))])
    out = run_red(bench.wb, TASK, attempt=1)
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert out.check == "targeted"
    assert done.status == "failed" and done.reason.startswith("red tests still failing: tests.test_targeted::")


def test_scn_imp_636_a_resumed_red_reads_its_check_from_its_record(make_bench):
    bench, fake, out = ok_red(make_bench)
    assert out.check == "targeted"
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "targeted"
    assert resumed.base_report is not None and PRE in resumed.base_report.tests
    assert resumed.new_ids == out.new_ids and resumed.new_ids.isdisjoint(resumed.base_report.tests)
    # the base is measured with a whole run at the red commit, as before
    assert [e["name"] for e in bench.events("gate.finished")][-1] == "baseline"


def test_scn_imp_636_a_red_commit_of_0460_resumes_as_full(make_bench):
    bench = make_bench([red()])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok" and "check" not in bench.events("task.red_ok")[0]
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "full"


# --- SCN-IMP-637: the variant runs ------------------------------------------------------------------------------------

TIP_STUB = "def tip(bill, percent):\n    raise NotImplementedError\n"
TIP_TESTS = (
    "import pytest\nfrom pytdd.tip import tip\n\n\n"
    f'@pytest.mark.l4("{KNOWN}")\ndef test_tip_is_rounded():\n    assert str(tip(10, 12.5)) == "1.25"\n\n\n'
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_tip_of_zero():\n    assert tip(10, 0) == 0\n'
)


def test_scn_imp_637_the_zero_value_run_is_the_whole_command_judged_against_the_overlay(make_bench):
    bench = bench_of(make_bench, [red(path="tests/test_tip.py", tests=TIP_TESTS)])
    (bench.wb.worktree / "src" / "pytdd" / "tip.py").write_text(TIP_STUB)
    bench.wb.git.run("add", "src/pytdd/tip.py")
    bench.wb.git.run("commit", "-q", "-m", "an earlier task's stub")
    fake = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert fake.names[0] == "test-targeted" and "test-zero" in fake.names and "test" not in fake.names
    zero = next(c for n, c in fake.calls if n == "test-zero")
    assert zero == TEST_COMMAND  # the whole command, the code zeroed
    [ok] = bench.events("task.red_ok")
    assert ok["check"] == "targeted" and ok["files"] == ["tests/test_tip.py"]
    assert {info["proof"] for info in ok["criteria"].values()} == {"zero_value"}


# --- SCN-IMP-648, 649: a resumed targeted red measures its base without its files ---------------------------------

BREAKS = (
    HEAD
    + "import pytdd\n\npytdd.total = lambda prices: -1  # breaks `test_pricing` once the whole suite is collected\n\n\n"
    + CODES
)
BREAKING = "tests/test_aaa_targeted.py"


def breaking_red(make_bench, *more: Step):
    bench = bench_of(make_bench, [red(path=BREAKING, tests=BREAKS), *more])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason  # a whole run would have failed: red broke existing tests
    return bench, out


def edit_red_ok(bench, **changes) -> None:
    """FAKE: rewrite the record of the one `task.red_ok` of the ledger (a record that the red commit does not match)."""
    path = bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines:
        if line["type"] == "task.red_ok":
            line.update(changes)
            for key in [k for k, v in changes.items() if v is None]:
                del line[key]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_scn_imp_648_a_resumed_targeted_red_measures_its_base_with_its_files_absent(make_bench):
    bench, out = breaking_red(make_bench, green_step())
    path = bench.wb.worktree / BREAKING
    before, mode = path.read_bytes(), path.stat().st_mode
    seen: list[bool] = []
    FakeGates(bench, before={"baseline": lambda: seen.append(path.exists())})
    resumed = resume_red(bench.wb, TASK)
    assert seen == [False]  # the one whole run of the resume ran without the red's files
    assert resumed is not None and resumed.check == "targeted" and resumed.files == (BREAKING,)
    assert resumed.base_report.tests[PRE].status == "passed"  # the base the red commit's parent would measure
    assert resumed.new_ids.isdisjoint(resumed.base_report.tests) and resumed.manifest is not None
    assert path.read_bytes() == before and path.stat().st_mode == mode  # put back byte for byte
    assert bench.wb.git.run("status", "--porcelain", "--", "tests", "src").stdout == ""
    assert bench.events("task.red_check_disabled") == []
    assert [e["name"] for e in bench.events("gate.finished")][-1] == "baseline"


def test_scn_imp_648_green_after_a_resumed_targeted_red_sees_the_old_test_and_records_the_switch(make_bench):
    bench, out = breaking_red(make_bench, green_step())
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None
    done = run_green(bench.wb, TASK, resumed, attempt=1)
    assert done.status == "failed" and done.reason.startswith(f"green broke existing tests: {PRE}")
    assert "L4-IMP-122" in done.reason  # the own red of the task was targeted: the agent is told to ask
    [event] = bench.events("task.red_check_disabled")
    assert (event["why"], event["red_sha"]) == ("regressed", out.sha) and PRE in event["tests"]


def test_scn_imp_648_a_resume_whose_red_ran_whole_measures_with_the_files_in_place(make_bench):
    bench = make_bench([red()])  # no `red_check`: a red commit of 0.4.60
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok"
    seen: list[bool] = []
    FakeGates(bench, before={"baseline": lambda: seen.append((bench.wb.worktree / FILE).exists())})
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "full" and resumed.files == ()
    assert seen == [True] and bench.events("task.red_check_disabled") == []


@pytest.mark.parametrize(
    ("changes", "step"),
    [
        ({"files": ["tests/test_not_there.py"]}, None),  # a file the red commit does not hold
        ({"files": ["tests/test_pricing.py", BREAKING]}, None),  # a file the parent already had
        ({"files": None}, None),  # a record with no list of files
        ({"files": []}, None),
        ({"files": [BREAKING, "../outside.py"]}, None),  # a path that leaves the work tree
        ({"files": ["tests/test_a.py"]}, "two"),  # the red commit holds another file that the record does not name
    ],
)
def test_scn_imp_649_a_record_that_the_red_commit_does_not_match_falls_back_and_records_the_switch(
    make_bench, changes, step
):
    bench = bench_of(make_bench, [two_files() if step else red(path=BREAKING, tests=BREAKS)])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    edit_red_ok(bench, **changes)
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "targeted"
    for path in ("tests/test_pricing.py", *(("tests/test_a.py", "tests/test_b.py") if step else (BREAKING,))):
        assert (bench.wb.worktree / path).is_file(), path  # nothing was removed that stays removed
    if not step:  # today's rebuild: the red's files are in the tree and the old test fails in the base
        assert resumed.base_report.tests[PRE].status == "failed"
    [event] = bench.events("task.red_check_disabled")
    assert (event["why"], event["task"], event["attempt"], event["red_sha"]) == ("resume_files", "1.1", 0, out.sha)
    assert event["tests"] == []


def test_scn_imp_649_a_put_back_that_is_not_exact_falls_back_and_records_the_switch(make_bench, monkeypatch):
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    before = path.read_bytes()

    def broken(*args, **kwargs):  # FAKE: the put-back cannot write the file
        raise OSError("disk full")

    monkeypatch.setattr(tdd, "_write_file", broken)
    fake = FakeGates(bench)
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "targeted"
    assert [n for n, _ in fake.calls].count("baseline") == 2  # the run without the files, then today's rebuild
    assert path.read_bytes() == before  # the files are back, from git, whatever happened to the first put-back
    assert resumed.base_report.tests[PRE].status == "failed"  # today's rebuild, files in place
    [event] = bench.events("task.red_check_disabled")
    assert event["why"] == "resume_put_back" and event["red_sha"] == out.sha


def test_scn_imp_649_the_switch_of_a_resume_is_recorded_once(make_bench):
    bench, out = breaking_red(make_bench)
    edit_red_ok(bench, files=["tests/test_not_there.py"])
    assert resume_red(bench.wb, TASK) is not None
    assert len(bench.events("task.red_check_disabled")) == 1
    edit_red_ok(bench, files=["tests/test_not_there.py"])  # the ledger restore undid the hand edit
    assert resume_red(bench.wb, TASK) is not None  # the second resume falls back for the same reason
    assert [e["why"] for e in bench.events("task.red_check_disabled")] == ["resume_files"]


def test_scn_imp_649_the_files_are_back_when_the_whole_run_is_stopped(make_bench):
    """A soft deadline stops the gate inside the files-absent run (a retry or a resume starts again from there)."""
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    before, mode = path.read_bytes(), path.stat().st_mode

    def stop() -> None:
        assert not path.exists()  # the run really was on the tree without the file
        raise DeadlineReached("during", during="gate", gate="baseline")

    FakeGates(bench, before={"baseline": stop})
    with pytest.raises(DeadlineReached):
        resume_red(bench.wb, TASK)
    assert path.read_bytes() == before and path.stat().st_mode == mode


def test_scn_imp_649_files_left_removed_by_a_killed_run_are_back_when_the_resume_returns(make_bench):
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    before = path.read_bytes()
    path.unlink()  # what a kill inside the files-absent run leaves in the work tree
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.base_report.tests[PRE].status == "passed"
    assert path.read_bytes() == before  # not left to the freeze, which would call it tampering
    assert bench.events("task.red_check_disabled") == [] and bench.events("guard.test_tamper") == []


@pytest.mark.parametrize(
    "listed",
    [
        [BREAKING, BREAKING],  # a duplicate
        ["./" + BREAKING],  # not the path git lists
        ["tests/../" + BREAKING],  # a path that climbs, and comes back
        ["/" + BREAKING],  # an absolute path
    ],
)
def test_scn_imp_649_a_record_with_a_path_that_is_not_a_plain_relative_one_falls_back(make_bench, listed):
    bench, out = breaking_red(make_bench)
    edit_red_ok(bench, files=listed)
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.base_report.tests[PRE].status == "failed"  # the files stayed in place
    assert [e["why"] for e in bench.events("task.red_check_disabled")] == ["resume_files"]


def test_scn_imp_649_a_record_with_more_files_than_a_targeted_step_may_have_falls_back(make_bench, monkeypatch):
    bench = bench_of(make_bench, [two_files()])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok" and out.files == ("tests/test_a.py", "tests/test_b.py")
    monkeypatch.setattr(red_check_module, "MAX_FILES", 1)
    assert resume_red(bench.wb, TASK) is not None
    assert [e["why"] for e in bench.events("task.red_check_disabled")] == ["resume_files"]


def test_scn_imp_649_the_commit_may_hold_tool_caches_and_the_ledger_folder_of_a_fix_unit(make_bench):
    """`_red_files_present` against a commit that holds the red's file, a tool cache and the run's ledger only."""
    bench, out = breaking_red(make_bench)
    git, wb = bench.wb.git, bench.wb
    cache = wb.worktree / "tests" / "__pycache__" / "test_x.cpython-312.pyc"
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(b"\0")
    git.run("add", "-f", "--", "tests/__pycache__")
    git.run("commit", "-q", "-m", "a tool cache")
    parent = git.rev_parse(f"{out.sha}~1")
    held = tdd._red_files_present(wb, git.rev_parse("HEAD"), parent, [BREAKING])
    assert held is not None and list(held) == [BREAKING]  # the cache and the ledger are not the red's files
    elsewhere = replace(wb.ref, path=wb.worktree / "elsewhere")  # a fix unit: the ledger is the parent's
    wb.ref = elsewhere
    assert tdd._red_files_present(wb, git.rev_parse("HEAD"), parent, [BREAKING]) is not None
    git.run("commit", "-q", "--allow-empty", "-m", "nothing")
    (wb.worktree / "tests" / "test_extra.py").write_text("x = 1\n")
    git.run("add", "tests/test_extra.py")
    git.run("commit", "-q", "-m", "a file that the record does not name")
    assert tdd._red_files_present(wb, git.rev_parse("HEAD"), parent, [BREAKING]) is None


# --- SCN-IMP-630: the task's own text and a reopened task reach the choice from run_red --------------------------


def test_scn_imp_630_a_task_that_names_an_existing_test_runs_the_whole_suite(make_bench, monkeypatch):
    named = tdd.NamedTests("tasks.md", tests=(("tests/test_pricing.py", "test_total_adds_prices"),))
    monkeypatch.setattr(tdd, "named_tests", lambda *a, **k: named)
    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert fake.names[0] == "test" and "test-targeted" not in fake.names
    [event] = bench.events("task.red_check_full")
    assert event["why"] == "named_tests" and event["task"] == "1.1"


def test_scn_imp_630_a_task_that_names_a_test_of_another_language_runs_the_whole_suite(make_bench, monkeypatch):
    named = tdd.NamedTests("tasks.md", other=(("test/a.test.ts", "test/a.test.ts::x"),))
    monkeypatch.setattr(tdd, "named_tests", lambda *a, **k: named)
    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert fake.names[0] == "test" and bench.events("task.red_check_full")[0]["why"] == "named_tests"


def test_scn_imp_630_a_reopened_task_with_stale_tests_runs_the_whole_suite(make_bench, monkeypatch):
    stale = tdd.StaleTests({PRE: ("C-0",)}, ())
    monkeypatch.setattr(tdd, "stale_for", lambda *a, **k: stale)
    bench = bench_of(make_bench, [red()])
    fake = FakeGates(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert fake.names[0] == "test" and "test-targeted" not in fake.names
    [event] = bench.events("task.red_check_full")
    assert event["why"] == "stale_tests"


# --- the put-back, the files a resume finds, and the paths git is given ----------------------------------------------


def _commit_file(wb, rel: str, data: bytes, mode: int = 0o644) -> str:
    """Add `rel` in a commit of its own on the unit's branch and give the commit."""
    path = wb.worktree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    wb.git.run("add", "--", rel)
    wb.git.run("commit", "-q", "-m", f"add {rel}")
    return wb.git.rev_parse("HEAD")


def test_scn_imp_649_the_fallback_restore_names_its_files_literally(make_bench, monkeypatch):
    """A red file whose name holds glob characters must not bring a neighbour back from the red commit."""
    bench, out = breaking_red(make_bench)
    wb = bench.wb
    _commit_file(wb, "tests/test_a.py", b"x = 1\n")
    sha = _commit_file(wb, "tests/test_[a].py", b"y = 2\n")
    neighbour = wb.worktree / "tests" / "test_a.py"
    neighbour.write_bytes(b"x = 'edited after the red commit'\n")

    def broken(*args, **kwargs):  # FAKE: the put-back cannot write the file
        raise OSError("disk full")

    monkeypatch.setattr(tdd, "_write_file", broken)
    _gate, exact = tdd._run_without(wb, sha, {"tests/test_[a].py": (b"y = 2\n", 0o644)})
    assert exact is False
    assert (wb.worktree / "tests" / "test_[a].py").read_bytes() == b"y = 2\n"  # restored from the red commit
    assert neighbour.read_bytes() == b"x = 'edited after the red commit'\n"  # the neighbour is not a match


def test_scn_imp_649_a_file_that_is_present_but_modified_is_left_as_it_is(make_bench):
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    edited = path.read_bytes() + b"# a person's edit\n"
    path.write_bytes(edited)  # work in progress: the resume sets it aside for its runs and puts it back
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "targeted"
    assert path.read_bytes() == edited  # only a missing file is brought back from the red commit
    path.write_bytes(edited)
    tdd._restore_missing(bench.wb, out.sha, [BREAKING])  # the file is there: not touched
    assert path.read_bytes() == edited


def _commit_mode(wb, mode: int) -> None:
    """A person's commit after the red that makes the red's file `mode` (a mode change of the head)."""
    path = wb.worktree / BREAKING
    path.chmod(mode)
    wb.git.run("add", "--", BREAKING)
    wb.git.run("commit", "-q", "-m", "a person changes the mode of the red's file")


def test_scn_imp_649_an_executable_red_file_comes_back_with_its_bytes_and_its_mode(make_bench):
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    _commit_mode(bench.wb, 0o755)
    before = path.read_bytes()
    seen: list[bool] = []
    FakeGates(bench, before={"baseline": lambda: seen.append(path.exists())})
    resumed = resume_red(bench.wb, TASK)
    assert seen == [False] and resumed is not None  # measured without the file
    assert resumed.base_report.tests[PRE].status == "passed"
    assert path.read_bytes() == before and path.stat().st_mode & 0o7777 == 0o755
    assert bench.events("task.red_check_disabled") == []


@pytest.mark.parametrize(
    "wrong",
    [
        lambda data, mode: (data + b"# stray\n", mode),  # the bytes differ
        lambda data, mode: (data, mode ^ 0o111),  # the mode differs
    ],
    ids=["bytes", "mode"],
)
def test_scn_imp_649_a_put_back_with_other_bytes_or_another_mode_falls_back(make_bench, monkeypatch, wrong):
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    _commit_mode(bench.wb, 0o755)
    before = path.read_bytes()
    real = tdd._write_file
    monkeypatch.setattr(tdd, "_write_file", lambda root, rel, data, mode: real(root, rel, *wrong(data, mode)))
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "targeted"
    [event] = bench.events("task.red_check_disabled")
    assert event["why"] == "resume_put_back" and event["red_sha"] == out.sha
    assert path.read_bytes() == before  # git put the red commit's bytes back
    assert path.stat().st_mode & 0o7777 == 0o644  # and its mode: the red commit holds the file as 0644


def _resume_with_files_changed(make_bench, change):
    bench, out = breaking_red(make_bench)
    change(bench.wb, bench.wb.worktree / BREAKING)
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.check == "targeted"
    assert [e["why"] for e in bench.events("task.red_check_disabled")] == ["resume_files"]
    return bench, resumed


def test_scn_imp_649_a_red_file_that_is_a_symlink_falls_back(make_bench):
    def link(wb, path):  # a person's commit after the red turns the file into a link
        path.unlink()
        path.symlink_to("test_pricing.py")
        wb.git.run("add", "--", BREAKING)
        wb.git.run("commit", "-q", "-m", "a person links the red's file")

    bench, resumed = _resume_with_files_changed(make_bench, link)
    assert (bench.wb.worktree / BREAKING).is_symlink()  # left as the person had it


def test_scn_imp_649_a_red_file_that_cannot_be_read_falls_back(make_bench):
    import os

    if os.geteuid() == 0:
        pytest.skip("root reads any file")
    bench, out = breaking_red(make_bench)
    path = bench.wb.worktree / BREAKING
    path.chmod(0o000)
    try:
        assert tdd._red_files_present(bench.wb, out.sha, bench.wb.git.rev_parse(f"{out.sha}~1"), [BREAKING]) is None
    finally:
        path.chmod(0o644)


def test_scn_imp_649_a_red_file_that_a_person_edited_after_the_red_commit_falls_back(make_bench):
    def edit(wb, path):
        wb.git.run("config", "user.name", "x")
        path.write_bytes(path.read_bytes() + b"# edited later\n")
        wb.git.run("add", "--", BREAKING)
        wb.git.run("commit", "-q", "-m", "a person edits the red's file")

    bench, resumed = _resume_with_files_changed(make_bench, edit)
    assert (bench.wb.worktree / BREAKING).read_bytes().endswith(b"# edited later\n")


def test_scn_imp_649_a_red_file_that_is_empty_is_not_one_a_resume_leaves_out(make_bench):
    """The code treats an empty blob like an unreadable one: no files-absent run, today's rebuild."""
    bench, out = breaking_red(make_bench)
    wb = bench.wb
    parent = wb.git.rev_parse("HEAD")
    sha = _commit_file(wb, "tests/test_empty.py", b"")
    assert tdd._red_files_present(wb, sha, parent, ["tests/test_empty.py"]) is None
    sha = _commit_file(wb, "tests/test_full.py", b"z = 3\n")
    assert tdd._red_files_present(wb, sha, f"{sha}~1", ["tests/test_full.py"]) is not None
