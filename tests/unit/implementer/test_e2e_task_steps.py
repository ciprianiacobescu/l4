"""L4-IMP-101: the step that completes a task runs that task's own browser tests (e2e-in-task-steps)."""

import sys
from types import SimpleNamespace

from l4.agents.fake import Step
from l4.gates.e2e import E2eRun, ServerNotReady
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.loop import run_task
from l4.implementer.prompt import data_block, render_prompt
from l4.implementer.tdd import resume_red, run_green, run_red, task_browser_tests
from l4.specs.base import Task

from .._web_helpers import e2e_config, free_port
from .conftest import IMPL, KNOWN, STUB, TESTS, UNKNOWN, green_step, result
from .test_fix_chore_e2e import BUILD_OK, commit_files
from .test_near_pass_carry import LINT_IMPL, lint_bad
from .test_prompt import ctx as prompt_ctx

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
WIDTH = "e2e.test_layout::test_width[chromium]"

BROWSER = "def test_width():\n    assert 1508 == 1500\n"
OLD = "LIMIT = 10\n\n\ndef test_a():\n    assert LIMIT == 10\n\n\ndef test_b():\n    assert 1 == 1\n"


def bench_with(make_bench, script=(), **gates):
    return make_bench(list(script), e2e=e2e_config(free_port()), **gates)


def commit(bench, files: dict[str, str]) -> str:
    commit_files(bench, files)
    return bench.wb.head()


# 1. which tests are the task's (D1)


def test_a_red_commit_that_added_a_browser_test_names_it(make_bench):
    bench = bench_with(make_bench)
    before = bench.wb.head()
    after = commit(bench, {"e2e/test_layout.py": BROWSER, "tests/test_unit.py": "def test_u():\n    assert 1\n"})
    assert task_browser_tests(bench.wb, before, after) == (("e2e/test_layout.py", "test_width"),)


def test_support_files_and_other_languages_add_no_browser_test(make_bench):
    bench = bench_with(make_bench)
    before = bench.wb.head()
    after = commit(
        bench,
        {
            "e2e/conftest.py": "def test_helper():\n    pass\n",
            "e2e/__init__.py": "def test_init():\n    pass\n",
            "e2e/fixtures/test_data.py": "def test_data():\n    pass\n",
            "e2e/page.spec.ts": "test('width', () => {})\n",
            "tests/test_unit.py": "def test_u():\n    assert 1\n",
        },
    )
    assert task_browser_tests(bench.wb, before, after) == ()


def test_a_changed_conftest_with_no_test_function_adds_none(make_bench):
    bench = bench_with(make_bench)
    before = commit(bench, {"e2e/conftest.py": "X = 1\n", "e2e/test_old.py": OLD})
    after = commit(bench, {"e2e/conftest.py": "X = 2\n"})
    assert task_browser_tests(bench.wb, before, after) == ()


def test_only_the_changed_test_of_an_existing_file_is_the_tasks(make_bench):
    bench = bench_with(make_bench)
    before = commit(bench, {"e2e/test_old.py": OLD})
    after = commit(bench, {"e2e/test_old.py": OLD.replace("1 == 1", "2 == 2")})
    assert task_browser_tests(bench.wb, before, after) == (("e2e/test_old.py", "test_b"),)


def test_a_changed_constant_that_a_test_reads_makes_it_the_tasks(make_bench):
    bench = bench_with(make_bench)
    before = commit(bench, {"e2e/test_old.py": OLD})
    after = commit(bench, {"e2e/test_old.py": OLD.replace("LIMIT = 10", "LIMIT = 11")})
    assert task_browser_tests(bench.wb, before, after) == (("e2e/test_old.py", "test_a"),)


def test_a_deleted_browser_test_is_not_run(make_bench):
    bench = bench_with(make_bench)
    before = commit(bench, {"e2e/test_old.py": OLD})
    after = commit(bench, {"e2e/test_old.py": OLD.split("\n\n\ndef test_b")[0] + "\n"})  # test_b is gone
    assert task_browser_tests(bench.wb, before, after) == ()


def test_an_unparsable_file_gives_none(make_bench):
    bench = bench_with(make_bench)
    before = bench.wb.head()
    after = commit(bench, {"e2e/test_broken.py": "def test_x(:\n"})
    assert task_browser_tests(bench.wb, before, after) == ()


def test_the_work_tree_is_read_when_after_is_none(make_bench):
    bench = bench_with(make_bench)
    before = bench.wb.head()
    path = bench.wb.worktree / "e2e" / "test_new.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BROWSER)  # uncommitted and untracked
    assert task_browser_tests(bench.wb, before, None) == (("e2e/test_new.py", "test_width"),)


def test_a_test_outside_the_e2e_directory_is_not_a_browser_test(make_bench):
    bench = bench_with(make_bench)
    before = bench.wb.head()
    after = commit(bench, {"tests/test_layout.py": BROWSER})
    assert task_browser_tests(bench.wb, before, after) == ()


# 2. green runs them last (D3, D4, D5, D6)


def browser_red(browser: str = BROWSER, extra: dict[str, str] | None = None) -> Step:
    return Step(
        writes={
            "tests/test_discount.py": TESTS,
            "src/pytdd/pricing.py": STUB,
            "e2e/test_layout.py": browser,
            **(extra or {}),
        },
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )  # fmt: skip


def stub_e2e(
    monkeypatch,
    bench,
    calls: list,
    *,
    statuses=None,
    raises: bool = False,
    log_text: str = "",
    writes: dict[str, str] | None = None,
    details: dict[str, str] | None = None,
    collection: tuple[str, ...] = (),
    timed_out: bool = False,
    no_report: bool = False,
) -> None:
    """`run_e2e` with no server (the stub of `test_fix_chore_e2e`, with failure details). `statuses`: {test id: status},
    or a list of them, one per call (the last one repeats)."""

    def fake(wb, worktree=None, *, name="e2e", must_contain=(), extra_env=None):
        calls.append(
            SimpleNamespace(
                name=name, must_contain=sorted(must_contain), built=(wb.worktree / ".l4-out/built").exists()
            )
        )
        for rel, text in (writes or {}).items():
            (wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
            (wb.worktree / rel).write_text(text)
        if raises:
            log = wb.out_dir / "x.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(log_text)
            raise ServerNotReady("gates.e2e: the server was not ready (see x.log)", log)
        chosen = statuses[min(len(calls), len(statuses)) - 1] if isinstance(statuses, list) else statuses or {}
        cases = {
            i: TestCase(i, st, message=(details or {}).get(i, ""), detail=(details or {}).get(i, ""))
            for i, st in chosen.items()
        }
        report = None if no_report else TestReport(cases, collection_errors=list(collection))
        code = 0 if all(st == "passed" for st in chosen.values()) and not timed_out else 1
        gate = GateResult(
            name, "pass" if code == 0 else "fail", "timed out after 600s" if timed_out else "", code,
            wb.out_dir / "e2e.log", report, timed_out,
        )  # fmt: skip
        return E2eRun(gate, None)

    monkeypatch.setattr("l4.implementer.tdd.run_e2e", fake)


FAILING = {WIDTH: "failed"}
ASSERT_1508 = {WIDTH: "E       assert 1508 == 1500"}


def red_then(make_bench, greens, *, red: Step | None = None, **gates):
    bench = make_bench([red or browser_red(), *greens], e2e=e2e_config(free_port()), **gates)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    return bench, outcome


def test_scn_imp_548_a_wrong_browser_test_is_met_in_green(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step(), green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses=[FAILING, {WIDTH: "passed"}], details=ASSERT_1508)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("the task's browser tests do not pass")
    assert WIDTH in green.reason and "assert 1508 == 1500" in green.excerpt and green.near_pass is None
    assert [(c.name, c.must_contain) for c in calls] == [("e2e-task", [])]
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text() and bench.events("task.done") == []
    assert bench.wb.is_clean()


def test_the_next_green_prompt_holds_the_failure_text(make_bench, monkeypatch):
    bench = make_bench([browser_red(), green_step(), green_step()], e2e=e2e_config(free_port()))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses=[FAILING, {WIDTH: "passed"}], details=ASSERT_1508)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome
    assert "assert 1508 == 1500" in bench.adapter.requests[2].prompt
    assert [c.name for c in calls] == ["e2e-task", "e2e-task"]


def test_scn_imp_549_passing_browser_tests_let_the_task_be_green(make_bench, monkeypatch):
    bench = make_bench(
        [browser_red(), green_step()], e2e=e2e_config(free_port()), build=[f"{sys.executable} scripts/build.py"]
    )
    commit_files(bench, {"scripts/build.py": BUILD_OK})
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed"}, writes={"test-results/trace.zip": "x"})
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert calls == []  # a red step that commits a red runs no e2e gate
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert [(c.name, c.built) for c in calls] == [("e2e-task", True)]  # the build ran first, once
    names = [e["name"] for e in bench.events("gate.finished")]
    assert names.count("build") == 1 and names.index("test") < names.index("build")
    shown = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "test-results/trace.zip" not in shown and not any(p.startswith(".l4-out") for p in shown)
    assert not (bench.wb.worktree / "test-results" / "trace.zip").exists() and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_a_failing_build_fails_the_attempt_before_the_e2e_run(make_bench, monkeypatch):
    bench = make_bench([browser_red(), green_step()], e2e=e2e_config(free_port()), build=["false"])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed"})
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("gates.build failed before the e2e gate")
    assert calls == []


def test_scn_imp_550_a_task_without_a_browser_test_runs_no_e2e_gate(make_bench, monkeypatch):
    unit_only = Step(
        writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "e2e/conftest.py": "X = 1\n"},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )
    bench, red = red_then(make_bench, [green_step()], red=unit_only)
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={})
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok" and calls == []


def test_scn_imp_550_an_e2e_gate_without_a_server_is_not_run(make_bench, monkeypatch):
    config = e2e_config(free_port())
    del config["serve"]
    bench = make_bench([browser_red(), green_step()], e2e=config)
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "failed"})
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok" and calls == []


def test_scn_imp_551_a_server_that_is_not_ready_is_a_failed_attempt(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, raises=True, log_text="Error: listen EADDRINUSE :::3000\n")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("the e2e server was not ready (see x.log")
    assert "EADDRINUSE" in green.excerpt and green.near_pass is None
    assert bench.events("task.done") == []


TWO_BROWSER = "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 1\n"
A_ID, B_ID = "e2e.test_layout::test_a[chromium]", "e2e.test_layout::test_b[chromium]"


def test_scn_imp_552_a_browser_test_with_no_id_in_the_report_fails(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()], red=browser_red(TWO_BROWSER))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_ID: "passed"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "not in the e2e report" in green.reason
    assert "e2e/test_layout.py::test_b" in green.reason and "test_a" not in green.reason


def test_scn_imp_552_a_skipped_browser_test_does_not_pass(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()], red=browser_red(TWO_BROWSER))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_ID: "passed", B_ID: "skipped"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and B_ID in green.reason and A_ID not in green.reason


def test_scn_imp_552_a_skip_next_to_a_pass_is_fine_and_other_e2e_tests_are_not_judged(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()], red=browser_red(TWO_BROWSER))
    calls: list = []
    statuses = {
        A_ID: "passed",
        B_ID: "passed",
        "e2e.test_other::test_z": "failed",
        "e2e.test_layout::test_b[firefox]": "skipped",
    }
    stub_e2e(monkeypatch, bench, calls, statuses=statuses)
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"


def test_a_test_with_one_failing_id_among_passing_ones_fails(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed", "e2e.test_layout::test_width[firefox]": "error"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "test_width[firefox]" in green.reason


def test_scn_imp_553_a_failing_unit_test_runs_no_e2e_gate(make_bench, monkeypatch):
    breaker = Step(
        writes={"src/pytdd/pricing.py": IMPL.replace("round(sum(prices), 2)", "0")}, structured=result("green")
    )
    bench, red = red_then(make_bench, [breaker])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and calls == []


def test_scn_imp_553_a_lint_failure_runs_no_e2e_gate_and_is_a_near_pass(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [lint_bad()], lint=[LINT_IMPL])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and calls == [] and green.near_pass is not None


def test_a_timed_out_gate_fails_the_attempt(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed"}, timed_out=True)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "timed out after 600s" in green.reason


def test_a_run_with_no_readable_report_fails_the_attempt(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, no_report=True)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("the e2e gate produced no readable report")


def test_a_collection_error_of_the_tasks_file_fails_the_attempt(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={}, collection=("e2e.test_layout",))
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason == "browser tests not collected: e2e.test_layout"


def test_scn_imp_555_a_resumed_red_still_has_its_browser_tests(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "failed"}, details=ASSERT_1508)
    resumed = resume_red(bench.wb, TASK)
    assert resumed is not None and resumed.status == "ok"
    green = run_green(bench.wb, TASK, resumed, attempt=1)
    assert green.status == "failed" and WIDTH in green.reason and len(calls) == 1


# 3. the already-satisfied finish (D2)

EXISTING = (
    'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("' + KNOWN + '")\n'
    "def test_total_adds():\n    assert total([1.0, 2.0]) == 3.0\n"
)
EXISTING_UI = "e2e.test_existing_ui::test_ui[chromium]"


def satisfied_step() -> Step:
    return Step(
        writes={"tests/test_existing.py": EXISTING, "e2e/test_existing_ui.py": "def test_ui():\n    assert 1\n"},
        structured=result("red", criteria_ids=[KNOWN]),
    )


def test_scn_imp_554_an_already_satisfied_tasks_failing_browser_test_fails_red(make_bench, monkeypatch):
    bench = make_bench([satisfied_step()], e2e=e2e_config(free_port()))
    calls: list = []
    stub_e2e(
        monkeypatch, bench, calls, statuses={EXISTING_UI: "failed"}, details={EXISTING_UI: "E   assert 1508 == 1500"}
    )
    before = bench.wb.head()
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and EXISTING_UI in outcome.reason and "assert 1508 == 1500" in outcome.excerpt
    assert [c.name for c in calls] == ["e2e-task"]
    assert bench.wb.head() == before and bench.events("task.done") == [] and bench.wb.is_clean()


def test_scn_imp_554_a_passing_browser_test_lets_the_task_finish_as_already_satisfied(make_bench, monkeypatch):
    bench = make_bench([satisfied_step()], e2e=e2e_config(free_port()))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={EXISTING_UI: "passed"})
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert "e2e/test_existing_ui.py" in bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


# 4. the prompts (D7)


def test_the_green_prompt_names_the_browser_tests_and_says_the_harness_runs_them():
    text = render_prompt("green", prompt_ctx(browser_tests=("e2e/test_layout.py::test_width",))).text
    assert "# Browser tests of this task" in text
    assert "After your step the harness builds the app, serves it and runs the e2e gate" in text
    assert "report status blocked with one technical question whose first option is the exact edit" in text
    assert data_block("browser tests of this task", "- e2e/test_layout.py::test_width") in text


def test_a_green_prompt_without_browser_tests_is_unchanged():
    text = render_prompt("green", prompt_ctx()).text
    assert (
        "Browser tests of this task" not in text and text == render_prompt("green", prompt_ctx(browser_tests=())).text
    )
    assert "Browser tests of this task" not in render_prompt("red", prompt_ctx(browser_tests=("e2e/a.py::t",))).text


def test_the_red_prompt_says_the_green_step_runs_the_browser_tests_and_they_are_frozen():
    red = render_prompt("red", prompt_ctx(e2e_dir="e2e")).text
    assert "The green step of this task runs them with the app served" in red
    assert "frozen after this step" in red and "`page.set_content`" in red
    assert "frozen after this step" not in render_prompt("red", prompt_ctx()).text


def test_the_green_step_is_prompted_with_the_tasks_browser_tests(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    stub_e2e(monkeypatch, bench, [], statuses={WIDTH: "passed"})
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    prompt = bench.adapter.requests[1].prompt
    assert "e2e/test_layout.py::test_width" in prompt and "# Browser tests of this task" in prompt
    assert "# Browser tests of this task" not in bench.adapter.requests[0].prompt
