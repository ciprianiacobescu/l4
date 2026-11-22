"""L4-IMP-105 (SCN-IMP-571..576): a task step runs its test gate once more before it fails an attempt on a few
pre-existing tests. The gate is the real one on the fixture unit; FAKE wrappers flip the status of a pre-existing test
in run 1 (and in the re-run, as each test says), so that a test fails once and passes, or fails again."""

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from l4 import deadline
from l4.agents.fake import Step
from l4.availability.cooldown import FakeClock
from l4.deadline import RunDeadline
from l4.gates.hang import TIMEOUT_MARKER
from l4.gates.junit import TestCase, TestReport
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .conftest import IMPL, STUB, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
CHORE = Task("1.1", "1.1", "1.1 an inline suppression was not declared (F-6eb0cc43)", False, " ", 0, 3, 3)
FINDINGS = ["F-6eb0cc43"]
PRE = "tests.test_pricing::test_total_adds_prices"  # a test of the base, in a file the unit does not change
OTHER = "tests.test_pricing::test_total_of_nothing_is_zero"
FIX = Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single"))
PRICING_TESTS = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert total([1.25, 2.5]) == 3.75\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
AGAIN = "; failed again on a re-run (L4-IMP-105): "


def failing(report: TestReport | None, *ids: str, message: str = "boom") -> TestReport | None:
    if report is None:
        return None
    return replace(report, tests={**report.tests, **{i: TestCase(i, "failed", message) for i in ids}})


class FakeFlaky:
    """FAKE: wraps `wb.run_gate` of a bench. Run 1 (the first `test` run after `install`) fails `ids`; the re-run does
    what `rerun` says: `pass` (the real report), `fail` (the same ids fail again), `other` (another test that passed in
    run 1 fails), `gone` (a test of run 1 is missing), or one of `unusable` (no report), `collection`, `vacuous` and
    `lacks` (a report that cannot be used). `seconds` is the duration run 1 reports; `calls` lists the names of every
    gate the step ran."""

    def __init__(self, bench, *ids: str, rerun: str = "pass", seconds: float = 1.0, message: str = "boom") -> None:
        self.ids, self.rerun, self.seconds, self.message = ids, rerun, seconds, message
        self.calls: list[str] = []
        self.original = bench.wb.run_gate
        bench.wb.run_gate = self.run_gate

    def run_gate(self, name, command, **kw):
        out = self.original(name, command, **kw)
        first = name == "test" and "test" not in self.calls
        self.calls.append(name)
        if first:
            return replace(out, report=failing(out.report, *self.ids, message=self.message), seconds=self.seconds)
        if name == "test-recheck":
            report = out.report
            if self.rerun == "fail":
                report = failing(report, *self.ids)
            elif self.rerun == "other":
                report = failing(report, OTHER)
            elif self.rerun == "unusable":
                report = None
            elif self.rerun == "collection":  # a module that did not collect
                report = replace(report, collection_errors=["tests.test_broken"])
            elif self.rerun == "vacuous":  # every test skipped: none executed
                report = replace(report, tests={i: TestCase(i, "skipped") for i in report.tests})
            elif self.rerun == "lacks":  # the regressed test is not in the re-run's report
                report = replace(report, tests={i: c for i, c in report.tests.items() if i != PRE})
            elif self.rerun == "gone":
                report = replace(report, tests={i: c for i, c in report.tests.items() if i != OTHER})
            return replace(out, report=report)
        return out


def rechecks(bench) -> list[dict]:
    return bench.events("task.tests_rechecked")


def green_bench(make_bench):
    bench = make_bench([red_step(), green_step()])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    return bench, red


def arm(left_s: float) -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    deadline.arm(
        RunDeadline(at=clock.now() + timedelta(seconds=left_s), clock=clock, event=threading.Event()),
        timer=lambda seconds, function: SimpleNamespace(start=lambda: None, cancel=lambda: None, daemon=True),
    )


@pytest.fixture(autouse=True)
def _disarmed():
    yield
    deadline.disarm()


# --- green ----------------------------------------------------------------------------------------------------------


def test_scn_imp_571_a_pre_existing_test_that_fails_once_and_passes_on_the_re_run_does_not_fail_green(make_bench):
    bench, red = green_bench(make_bench)
    flaky = FakeFlaky(bench, PRE)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "ok", out.reason
    assert flaky.calls.count("test") >= 1 and flaky.calls.count("test-recheck") == 1
    assert flaky.calls.index("test") < flaky.calls.index("test-recheck")
    [event] = rechecks(bench)
    assert (event["task"], event["phase"], event["attempt"], event["stopped"]) == ("1.1", "green", 1, "passed")
    assert (
        event["tests"] == [PRE] and event["flaky"] == [PRE] and event["failing"] == [] and event["new_failures"] == []
    )
    assert bench.events("task.done") and bench.wb.last_tested is not None
    assert bench.wb.last_tested.report.tests[PRE].status == "passed"  # `keep_tested` got the merged report
    assert [e["name"] for e in bench.events("gate.finished") if e["name"] == "test-recheck"] == ["test-recheck"]


def test_scn_imp_572_a_test_that_fails_again_fails_the_attempt_with_both_runs_in_the_reason(make_bench):
    bench, red = green_bench(make_bench)
    FakeFlaky(bench, PRE, rerun="fail")
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed"
    assert out.reason == f"green broke existing tests: {PRE}{AGAIN}{PRE}"
    [event] = rechecks(bench)
    assert event["stopped"] == "failed" and event["failing"] == [PRE] and event["flaky"] == []
    assert bench.events("task.done") == []


def test_scn_imp_576_a_test_that_passed_in_run_1_and_fails_in_the_re_run_fails_the_attempt(make_bench):
    bench, red = green_bench(make_bench)
    FakeFlaky(bench, PRE, rerun="other")
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}{AGAIN}{OTHER}"
    [event] = rechecks(bench)
    assert event["stopped"] == "failed" and event["flaky"] == [PRE] and event["new_failures"] == [OTHER]


def test_a_test_that_passed_in_run_1_and_is_missing_in_the_re_run_is_a_new_failure(make_bench):
    bench, red = green_bench(make_bench)
    FakeFlaky(bench, PRE, rerun="gone")
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason.endswith(AGAIN + OTHER)
    assert rechecks(bench)[0]["new_failures"] == [OTHER]


@pytest.mark.parametrize("rerun", ["unusable", "collection", "vacuous", "lacks"])
def test_an_unusable_re_run_fails_the_attempt_and_says_so(make_bench, rerun):
    bench, red = green_bench(make_bench)
    FakeFlaky(bench, PRE, rerun=rerun)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}; its re-run was not usable"
    assert rechecks(bench)[0]["stopped"] == "unusable"


def test_a_later_reason_still_fails_the_attempt_on_the_merged_report(make_bench):
    """The re-run passes the flaky test, and green then adds a failing test of its own: `new failing tests added in
    green` is found on the merged report, and no second re-run is made."""
    extra = "def test_extra():\n    assert False\n"
    sneaky = Step(writes={"src/pytdd/pricing.py": IMPL, "tests/test_extra.py": extra}, structured=result("green"))
    bench = make_bench([red_step(), sneaky])
    red = run_red(bench.wb, replace(TASK, title=f"{TASK.title} [test-infra]"), attempt=1)
    flaky = FakeFlaky(bench, PRE)
    out = run_green(bench.wb, replace(TASK, title=f"{TASK.title} [test-infra]"), red, attempt=1)
    assert out.status == "failed" and out.reason == "new failing tests added in green: tests.test_extra::test_extra"
    assert flaky.calls.count("test-recheck") == 1
    assert rechecks(bench)[0]["stopped"] == "passed"


# --- no re-run (SCN-IMP-573) ----------------------------------------------------------------------------------------


def no_rerun(bench, flaky) -> None:
    assert "test-recheck" not in flaky.calls and rechecks(bench) == []


def test_scn_imp_573_a_test_in_a_file_the_unit_changed_gets_no_re_run(make_bench):
    bench, red = green_bench(make_bench)
    bench.wb.branch_changed_files = lambda: ["tests/test_pricing.py"]
    flaky = FakeFlaky(bench, PRE)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}"
    no_rerun(bench, flaky)


def test_scn_imp_573_a_test_in_a_file_the_step_changed_gets_no_re_run(make_bench):
    """A `[test-infra]` task may edit a test file in green; a regressed test of that file is the step's own."""
    edit = Step(
        writes={"src/pytdd/pricing.py": IMPL, "tests/test_pricing.py": "# edited by the step\n" + PRICING_TESTS},
        structured=result("green"),
    )
    task = replace(TASK, title=f"{TASK.title} [test-infra]")
    bench = make_bench([red_step(), edit])
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    flaky = FakeFlaky(bench, PRE)
    out = run_green(bench.wb, task, red, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}"
    no_rerun(bench, flaky)


def test_scn_imp_573_a_hung_test_gets_no_re_run(make_bench):
    bench, red = green_bench(make_bench)
    flaky = FakeFlaky(bench, PRE, message=f"{TIMEOUT_MARKER} the test ran longer than 5s")
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed"
    no_rerun(bench, flaky)


def test_scn_imp_573_another_reason_besides_the_regression_gets_no_re_run(make_bench):
    lazy = Step(structured=result("green"))  # the red tests still fail: that is the reason, not the regression
    bench = make_bench([red_step(), lazy])
    red = run_red(bench.wb, TASK, attempt=1)
    flaky = FakeFlaky(bench, PRE)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason.startswith("red tests still failing")
    no_rerun(bench, flaky)


def test_scn_imp_573_a_regressed_id_the_report_lacks_gets_no_re_run(make_bench):
    bench, red = green_bench(make_bench)

    class Gone(FakeFlaky):
        """FAKE: run 1's report lacks the regressed id."""

        def run_gate(self, name, command, **kw):
            out = self.original(name, command, **kw)
            self.calls.append(name)
            if name == "test" and self.calls.count("test") == 1:
                report = replace(out.report, tests={i: c for i, c in out.report.tests.items() if i != PRE})
                return replace(out, report=report)
            return out

    flaky = Gone(bench, PRE)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}"
    no_rerun(bench, flaky)


def test_scn_imp_573_a_step_with_nothing_regressed_makes_no_re_run_and_records_nothing(make_bench):
    bench, red = green_bench(make_bench)
    calls: list[str] = []
    original = bench.wb.run_gate
    bench.wb.run_gate = lambda name, command, **kw: (calls.append(name), original(name, command, **kw))[1]
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    assert "test-recheck" not in calls and rechecks(bench) == []


# --- time and tree (SCN-IMP-574) ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("left_s", "stopped"), [(259, "budget"), (200, "budget"), (261, "passed")])
def test_scn_imp_574_the_re_run_needs_twice_run_1s_duration_plus_the_margin(make_bench, left_s, stopped):
    """Run 1 took 100 s: the delegate's rule is room for 2 x 100 s and the larger of 60 s and a tenth of 100 s. 200 s is
    enough for run 1's duration plus the margin and not for the rule."""
    bench, red = green_bench(make_bench)
    arm(left_s)
    flaky = FakeFlaky(bench, PRE, seconds=100.0)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert [e["stopped"] for e in rechecks(bench)] == [stopped]
    if stopped == "budget":
        assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}"
        assert "test-recheck" not in flaky.calls
    else:
        assert out.status == "ok" and "test-recheck" in flaky.calls


def test_scn_imp_574_a_tree_that_cannot_be_put_back_gets_no_re_run(make_bench, monkeypatch):
    bench, red = green_bench(make_bench)
    monkeypatch.setattr("l4.implementer.tdd.tree_before", lambda wb: None)
    flaky = FakeFlaky(bench, PRE)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}"
    assert [e["stopped"] for e in rechecks(bench)] == ["tree"] and "test-recheck" not in flaky.calls


def test_a_file_run_1_wrote_is_removed_before_the_re_run_and_the_step_s_own_files_stay(make_bench):
    bench, red = green_bench(make_bench)
    seen: dict[str, bool] = {}
    flaky = FakeFlaky(bench, PRE)
    original = flaky.run_gate

    def writing(name, command, **kw):
        """FAKE gate: run 1 leaves an untracked file; the re-run checks that it is gone."""
        if name == "test" and "test" not in flaky.calls:
            (bench.wb.worktree / "run1-leftover.txt").write_text("x")  # an untracked file run 1 leaves
        if name == "test-recheck":
            seen["leftover"] = (bench.wb.worktree / "run1-leftover.txt").exists()
            seen["impl"] = "def apply_discount" in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
        return original(name, command, **kw)

    bench.wb.run_gate = writing
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    assert seen == {"leftover": False, "impl": True}


def test_the_guard_after_a_gate_run_runs_after_the_re_run(make_bench, monkeypatch):
    bench, red = green_bench(make_bench)
    order: list[str] = []
    flaky = FakeFlaky(bench, PRE)
    original = flaky.run_gate
    bench.wb.run_gate = lambda name, command, **kw: (order.append(f"gate {name}"), original(name, command, **kw))[1]
    from l4.implementer import tdd

    real = tdd.restore_replay
    monkeypatch.setattr(tdd, "restore_replay", lambda wb, where: (order.append(f"guard {where}"), real(wb, where))[1])
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    assert order.index("gate test-recheck") < order.index("guard test re-run")


# --- red and a fix chore (SCN-IMP-575) ------------------------------------------------------------------------------


def test_scn_imp_575_red_commits_when_the_regressed_test_passes_on_the_re_run(make_bench):
    bench = make_bench([red_step()])
    flaky = FakeFlaky(bench, PRE)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    [event] = rechecks(bench)
    assert (event["phase"], event["stopped"], event["flaky"]) == ("red", "passed", [PRE])
    assert flaky.calls.count("test-recheck") == 1 and bench.events("task.red_ok")


def test_scn_imp_575_red_fails_with_both_runs_in_the_reason_when_it_fails_again(make_bench):
    bench = make_bench([red_step()])
    FakeFlaky(bench, PRE, rerun="fail")
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and f"red broke existing tests: {PRE}{AGAIN}{PRE}" in out.reason
    assert bench.events("task.red_ok") == []


def test_scn_imp_575_red_s_tamper_check_runs_after_the_re_run(make_bench, monkeypatch):
    from l4.implementer.stubs import ProductionGuard

    bench = make_bench([red_step()])
    order: list[str] = []
    flaky = FakeFlaky(bench, PRE)
    original = flaky.run_gate
    bench.wb.run_gate = lambda name, command, **kw: (order.append(f"gate {name}"), original(name, command, **kw))[1]
    check = ProductionGuard.check
    monkeypatch.setattr(
        ProductionGuard, "check", lambda self, where: (order.append(f"guard {where}"), check(self, where))[1]
    )
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    assert order.index("gate test-recheck") < order.index("guard test re-run")
    assert order.index("guard test run") < order.index("gate test-recheck")


def test_scn_imp_575_a_production_file_a_test_wrote_during_the_re_run_fails_red(make_bench):
    bench = make_bench([red_step()])
    flaky = FakeFlaky(bench, PRE)
    original = flaky.run_gate

    def writing(name, command, **kw):
        """FAKE gate: a test that writes a production file while the re-run runs."""
        if name == "test-recheck":  # a test that writes a production file while the re-run runs
            (bench.wb.worktree / "src/pytdd/pricing.py").write_text(STUB + "# written by a test\n")
        return original(name, command, **kw)

    bench.wb.run_gate = writing
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and "test code changed production files while a gate ran" in out.reason


def test_scn_imp_575_a_fix_chore_commits_when_the_regressed_test_passes_on_the_re_run(make_bench):
    bench = make_bench([FIX])
    flaky = FakeFlaky(bench, PRE)
    out = run_single(bench.wb, CHORE, FINDINGS, attempt=1)
    assert out.status == "ok", out.reason
    [event] = rechecks(bench)
    assert (event["phase"], event["stopped"], event["flaky"]) == ("single", "passed", [PRE])
    assert flaky.calls.count("test-recheck") == 1
    assert bench.wb.last_tested is not None and bench.wb.last_tested.report.tests[PRE].status == "passed"


def test_a_fix_chore_whose_re_run_fails_again_fails_with_both_runs_in_the_reason(make_bench):
    bench = make_bench([FIX])
    FakeFlaky(bench, PRE, rerun="fail")
    out = run_single(bench.wb, CHORE, FINDINGS, attempt=1)
    assert out.status == "failed" and out.reason == f"green broke existing tests: {PRE}{AGAIN}{PRE}"


def test_the_repair_chore_makes_no_re_run():
    """`_run_repair` calls `green_failures` and no `recheck_step`: the re-run is not wired into it."""
    import inspect

    from l4.implementer import tdd

    source = inspect.getsource(tdd._run_repair)
    assert "recheck_step" not in source and "test-recheck" not in source


def test_a_guard_that_cannot_put_the_tree_back_after_the_re_run_fails_the_attempt(make_bench, monkeypatch):
    """The replay guard (`restore_replay`) that runs after the re-run fails green when it says the tree is not back."""
    from l4.implementer import tdd

    bench, red = green_bench(make_bench)
    FakeFlaky(bench, PRE)
    real = tdd.restore_replay
    monkeypatch.setattr(
        tdd, "restore_replay", lambda wb, where: "replay broke the tree" if where == "test re-run" else real(wb, where)
    )
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and "replay broke the tree" in out.reason
    assert bench.events("task.done") == []
