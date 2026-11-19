"""L4-IMP-101: the step that completes a task runs that task's own browser tests (e2e-in-task-steps)."""

import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from l4.agents.fake import Step
from l4.gates.e2e import E2eRun, ServerNotReady
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.loop import run_task
from l4.implementer.prompt import data_block, render_prompt
from l4.implementer.tdd import resume_red, run_green, run_red, task_browser_tests
from l4.specs.base import Task
from l4.vcs.errors import GitError

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


def test_a_changed_constant_that_a_test_reads_does_not_make_it_the_tasks(make_bench):
    """Finding 10: only a test whose own definition the red commit added or changed counts, not what it reads."""
    bench = bench_with(make_bench)
    before = commit(bench, {"e2e/test_old.py": OLD})
    after = commit(bench, {"e2e/test_old.py": OLD.replace("LIMIT = 10", "LIMIT = 11")})
    assert task_browser_tests(bench.wb, before, after) == ()


AUTOUSE = (
    "import pytest\n\npytestmark = pytest.mark.slow\n\n\n@pytest.fixture(autouse=True)\ndef reset():\n    yield\n\n\n"
)


def test_a_new_autouse_fixture_or_pytestmark_does_not_make_every_test_the_tasks(make_bench):
    bench = bench_with(make_bench)
    before = commit(bench, {"e2e/test_old.py": OLD})
    after = commit(bench, {"e2e/test_old.py": AUTOUSE + OLD})
    assert task_browser_tests(bench.wb, before, after) == ()
    changed = commit(bench, {"e2e/test_old.py": AUTOUSE + OLD.replace("1 == 1", "2 == 2")})
    assert task_browser_tests(bench.wb, after, changed) == (("e2e/test_old.py", "test_b"),)


COLLECTABLE = (
    "import pytest\n\n\n@pytest.fixture\ndef test_user():\n    return 1\n\n\n"
    "def test_real():\n    assert 1\n\n\nasync def test_async():\n    assert 1\n\n\n"
    "class Helper:\n    def test_helper(self):\n        pass\n\n\n"
    "class TestA:\n    def test_x(self):\n        assert 1\n\n\n"
    "class TestInit:\n    def __init__(self):\n        pass\n\n    def test_y(self):\n        pass\n"
)


def test_only_what_pytest_would_collect_is_a_browser_test(make_bench):
    """Finding 1: a fixture or a helper named `test*`, a method of a class that is not `Test*` or that has an
    `__init__`, and a helper module that `python_files` does not match are no tests."""
    bench = bench_with(make_bench)
    before = bench.wb.head()
    after = commit(
        bench,
        {
            "e2e/test_pages.py": COLLECTABLE,
            "e2e/helpers.py": "def testid(page):\n    return page\n",
            "e2e/layout_test.py": "def test_suffix():\n    assert 1\n",
            "e2e/check_layout.py": "def test_unmatched():\n    assert 1\n",
        },
    )
    assert task_browser_tests(bench.wb, before, after) == (
        ("e2e/layout_test.py", "test_suffix"),
        ("e2e/test_pages.py", "TestA.test_x"),
        ("e2e/test_pages.py", "test_async"),
        ("e2e/test_pages.py", "test_real"),
    )


def test_a_git_error_is_a_ledger_note_not_a_silent_empty_answer(make_bench, monkeypatch):
    bench = bench_with(make_bench)

    def broken(*args, **kwargs):
        raise GitError(["git", *args], 128, "bad revision")

    monkeypatch.setattr(bench.wb.git, "run_bytes", broken)
    assert task_browser_tests(bench.wb, "nope", "nope2") == ()
    noted = bench.events("e2e.task_tests_unread")
    assert len(noted) == 1 and "bad revision" in noted[0]["reason"]


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


def unseen_of(bench) -> list[dict]:
    return bench.events("e2e.task_tests_unseen")


def test_scn_imp_552_a_browser_test_with_no_id_in_the_report_does_not_block_green(make_bench, monkeypatch, caplog):
    """The browser-test check is fail-safe: a test the report does not show is noted, and step 3 runs it as before."""
    bench, red = red_then(make_bench, [green_step()], red=browser_red(TWO_BROWSER))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_ID: "passed"})
    with caplog.at_level("WARNING", logger="l4.implementer"):
        green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    [note] = unseen_of(bench)
    assert note["task"] == "1.1" and note["phase"] == "green" and note["tests"] == ["e2e/test_layout.py::test_b"]
    assert any("not seen" in r.getMessage() and "verification step 3" in r.getMessage() for r in caplog.records)
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_scn_imp_552_a_skipped_only_browser_test_does_not_block_green(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()], red=browser_red(TWO_BROWSER))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_ID: "passed", B_ID: "skipped"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    [note] = unseen_of(bench)
    assert note["tests"] == ["e2e/test_layout.py::test_b"]


def test_scn_imp_552_a_failing_test_blocks_even_when_another_is_unseen(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()], red=browser_red(TWO_BROWSER))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_ID: "failed"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("the task's browser tests do not pass")
    assert A_ID in green.reason and "test_b" not in green.reason
    assert [n["tests"] for n in unseen_of(bench)] == [["e2e/test_layout.py::test_b"]]


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


ROOT_WIDTH = "test_layout::test_width[chromium]"  # pytest's classname under an `e2e/pytest.ini`: no `e2e.` prefix


def test_a_rootdir_relative_report_id_is_matched_by_the_module_suffix(make_bench, monkeypatch):
    """Finding 3: both id shapes name the task's test."""
    bench, red = red_then(make_bench, [green_step(), green_step()])
    calls: list = []
    stub_e2e(
        monkeypatch, bench, calls, statuses=[{ROOT_WIDTH: "failed"}, {ROOT_WIDTH: "passed"}],
        details={ROOT_WIDTH: "E   assert 1508 == 1500"},
    )  # fmt: skip
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and ROOT_WIDTH in green.reason and "assert 1508 == 1500" in green.excerpt
    assert unseen_of(bench) == []
    assert run_green(bench.wb, TASK, red, attempt=2).status == "ok"
    assert unseen_of(bench) == []


def test_two_modules_that_fit_the_suffix_leave_the_id_unseen_and_logged(make_bench, monkeypatch, caplog):
    """Finding 3: with `e2e/test_layout.py` and `e2e/other/test_layout.py`, `test_layout::test_width` is not guessed."""
    bench = make_bench([browser_red(), green_step()], e2e=e2e_config(free_port()))
    commit_files(bench, {"e2e/other/test_layout.py": BROWSER})
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={"test_layout::test_width[chromium]": "failed"})
    with caplog.at_level("WARNING", logger="l4.implementer"):
        green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    [note] = unseen_of(bench)
    assert note["tests"] == ["e2e/test_layout.py::test_width"] and note["ambiguous"] == [ROOT_WIDTH]
    assert any("ambiguous" in r.getMessage() for r in caplog.records)


CLASSES = (
    "class TestA:\n    def test_x(self):\n        assert 1\n\n\nclass TestB:\n    def test_x(self):\n        assert 1\n"
)
A_X, B_X = "e2e.test_layout.TestA::test_x[chromium]", "e2e.test_layout.TestB::test_x[chromium]"


def test_a_class_test_matches_only_its_own_class(make_bench, monkeypatch):
    """Finding 5: `TestA::test_x` passing does not stand for `TestB.test_x`."""
    bench, red = red_then(make_bench, [green_step()], red=browser_red(CLASSES))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_X: "passed", B_X: "failed"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and B_X in green.reason and A_X not in green.reason


def test_a_failing_test_of_another_class_is_not_the_tasks(make_bench, monkeypatch):
    only_a = "class TestA:\n    def test_x(self):\n        assert 1\n"
    bench, red = red_then(make_bench, [green_step()], red=browser_red(only_a))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_X: "passed", B_X: "failed"})  # `TestB` is another test's
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"


def test_a_class_test_absent_from_the_report_is_unseen_not_blocking(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()], red=browser_red(CLASSES))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={A_X: "passed"})
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    [note] = unseen_of(bench)
    assert note["tests"] == ["e2e/test_layout.py::TestB.test_x"]


def test_a_module_level_test_is_not_matched_by_a_class_method_of_the_same_name(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={"e2e.test_layout.TestZ::test_width[chromium]": "failed"})
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    assert unseen_of(bench)[0]["tests"] == ["e2e/test_layout.py::test_width"]


def test_a_collection_error_of_an_ambiguous_module_is_unseen(make_bench, monkeypatch):
    bench = make_bench([browser_red(), green_step()], e2e=e2e_config(free_port()))
    commit_files(bench, {"e2e/other/test_layout.py": BROWSER})
    red = run_red(bench.wb, TASK, attempt=1)
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={}, collection=("test_layout",))
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"


# 2b. when the task-step run is skipped (finding 4)


def skipped_of(bench) -> list[dict]:
    return bench.events("e2e.task_run_skipped")


def build_probe(bench) -> None:
    commit_files(bench, {"scripts/build.py": BUILD_OK})


def test_a_selecting_e2e_command_skips_the_task_step_run(make_bench, monkeypatch):
    config = e2e_config(free_port())
    config["command"] += " -m browser"
    bench = make_bench([browser_red(), green_step()], e2e=config, build=[f"{sys.executable} scripts/build.py"])
    build_probe(bench)
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "failed"})
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert calls == [] and "build" not in [e["name"] for e in bench.events("gate.finished")]
    [note] = skipped_of(bench)
    assert note["task"] == "1.1" and note["phase"] == "green" and "-m" in note["reason"]
    assert "# Browser tests of this task" not in bench.adapter.requests[1].prompt  # the prompt promises no run


def test_an_e2e_directory_that_holds_unit_tests_skips_the_task_step_run(make_bench, monkeypatch):
    config = e2e_config(free_port())
    config["command"] = config["command"].removesuffix(" e2e") + " tests"  # `pytest tests`: the unit gate's directory
    bench = make_bench(
        [Step(writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
              structured=result("red", tests_added=["tests/test_discount.py::test_known_code"],
                                criteria_ids=[KNOWN, UNKNOWN])),
         green_step()],
        e2e=config, build=[f"{sys.executable} scripts/build.py"],
    )  # fmt: skip
    build_probe(bench)
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={"tests.test_discount::test_known_code": "failed"})
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert calls == [] and "build" not in [e["name"] for e in bench.events("gate.finished")]
    [note] = skipped_of(bench)
    assert "unit gate" in note["reason"] and "tests/" in note["reason"]
    assert "# Browser tests of this task" not in bench.adapter.requests[1].prompt


def test_a_shared_directory_found_only_after_the_test_gate_skips_the_run_too(make_bench, monkeypatch):
    """The unit report of this very step decides when the baseline did not hold a test of the e2e directory."""
    bench, red = red_then(make_bench, [green_step()])
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "failed"})
    seen: list = []

    def shared(directory, ids, files):  # the baseline and red ids hold none; this step's report does
        seen.append(sorted(ids))
        return [] if len(seen) == 1 else ["e2e.test_layout::x"]

    monkeypatch.setattr("l4.implementer.tdd.shared_with_unit_gate", shared)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok" and calls == [] and len(skipped_of(bench)) == 1


def test_an_already_satisfied_finish_with_a_selecting_command_runs_no_e2e_gate(make_bench, monkeypatch):
    config = e2e_config(free_port())
    config["command"] += " -k ui"
    bench = make_bench([satisfied_step()], e2e=config)
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={EXISTING_UI: "failed"})
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert calls == [] and [n["phase"] for n in skipped_of(bench)] == ["red"]


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
    assert (
        "not green while one of these browser tests" in text
        and "one the report does not show is not judged here" in text
    )
    assert "report status blocked with one technical question whose first option is the exact edit" in text
    assert data_block("browser tests of this task", "- e2e/test_layout.py::test_width") in text


def test_a_green_prompt_without_browser_tests_is_unchanged():
    text = render_prompt("green", prompt_ctx()).text
    assert (
        "Browser tests of this task" not in text and text == render_prompt("green", prompt_ctx(browser_tests=())).text
    )
    assert "Browser tests of this task" not in render_prompt("red", prompt_ctx(browser_tests=("e2e/a.py::t",))).text


def test_the_red_prompt_says_the_completing_step_runs_the_browser_tests():
    red = render_prompt("red", prompt_ctx(e2e_dir="e2e")).text
    assert "The step that completes this task runs them" in red and "`page.set_content`" in red
    assert "the green step of this task runs them" not in red.lower()
    assert "frozen after this step" not in red  # the e2e directory is not under `tdd.test_globs` here
    frozen = render_prompt("red", prompt_ctx(e2e_dir="e2e", e2e_frozen=True)).text
    assert "frozen after this step" in frozen
    assert "frozen after this step" not in render_prompt("red", prompt_ctx()).text


def test_the_green_step_is_prompted_with_the_tasks_browser_tests(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    stub_e2e(monkeypatch, bench, [], statuses={WIDTH: "passed"})
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    prompt = bench.adapter.requests[1].prompt
    assert "e2e/test_layout.py::test_width" in prompt and "# Browser tests of this task" in prompt
    assert "# Browser tests of this task" not in bench.adapter.requests[0].prompt


# 5. the run deadline's cap counts the e2e run only for a green step that will run it (finding 9, L4-IMP-067)


def deadline_calls(monkeypatch) -> list[tuple[str, bool | None]]:
    """Arm a far deadline and record the `e2e` keyword of every `deadline.check` the loop makes."""
    import threading

    from l4 import deadline
    from l4.availability.cooldown import FakeClock
    from l4.deadline import RunDeadline

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    deadline.arm(
        RunDeadline(at=clock.now() + timedelta(hours=10), clock=clock, event=threading.Event()),
        timer=lambda seconds, function: SimpleNamespace(start=lambda: None, cancel=lambda: None, daemon=True),
    )
    calls: list[tuple[str, bool | None]] = []
    real = deadline.check

    def spy(phase, task, attempt, round_, **kwargs):
        calls.append((phase, kwargs.get("e2e")))
        return real(phase, task, attempt, round_, **kwargs)

    monkeypatch.setattr(deadline, "check", spy)
    return calls


def disarm() -> None:
    from l4 import deadline

    deadline.disarm()


def green_checks(calls) -> list[bool | None]:
    return [e2e for phase, e2e in calls if phase == "green"]


def test_a_green_step_with_browser_tests_is_checked_with_the_e2e_cap(make_bench, monkeypatch):
    bench = make_bench([browser_red(), green_step()], e2e=e2e_config(free_port()))
    stub_e2e(monkeypatch, bench, [], statuses={WIDTH: "passed"})
    calls = deadline_calls(monkeypatch)
    try:
        assert run_task(bench.wb, TASK).status == "done"
    finally:
        disarm()
    assert {c for c in calls if c[0] == "red"} == {("red", False)} and green_checks(calls) == [True]


def test_a_green_step_without_browser_tests_is_checked_with_the_plain_cap(make_bench, monkeypatch):
    """M9: `gates.e2e` configured is not enough; the task must have browser tests that will run."""
    unit_only = Step(
        writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )  # fmt: skip
    bench = make_bench([unit_only, green_step()], e2e=e2e_config(free_port()))
    stub_e2e(monkeypatch, bench, [], statuses={})
    calls = deadline_calls(monkeypatch)
    try:
        assert run_task(bench.wb, TASK).status == "done"
    finally:
        disarm()
    assert green_checks(calls) == [False]


def test_a_skipped_e2e_run_leaves_the_plain_cap(make_bench, monkeypatch):
    config = e2e_config(free_port())
    config["command"] += " -m browser"
    bench = make_bench([browser_red(), green_step()], e2e=config)
    stub_e2e(monkeypatch, bench, [], statuses={WIDTH: "passed"})
    calls = deadline_calls(monkeypatch)
    try:
        assert run_task(bench.wb, TASK).status == "done"
    finally:
        disarm()
    assert green_checks(calls) == [False]


def test_a_task_resumed_at_green_is_checked_with_the_e2e_cap_from_its_first_check(make_bench, monkeypatch):
    bench, red = red_then(make_bench, [green_step()])
    stub_e2e(monkeypatch, bench, [], statuses={WIDTH: "passed"})
    calls = deadline_calls(monkeypatch)
    try:
        assert run_task(bench.wb, TASK).status == "done"
    finally:
        disarm()
    assert [c[0] for c in calls][:2] == ["green", "green"] and green_checks(calls) == [True, True]


def test_no_e2e_gate_means_no_e2e_cap(make_bench, monkeypatch):
    config = e2e_config(free_port())
    del config["serve"]
    bench = make_bench([browser_red(), green_step()], e2e=config)
    calls = deadline_calls(monkeypatch)
    try:
        assert run_task(bench.wb, TASK).status == "done"
    finally:
        disarm()
    assert green_checks(calls) == [False]


# 6. pins of the behaviours a mutation run showed untested


def test_a_persons_unfreeze_survives_the_e2e_run_and_is_in_the_commit(make_bench, monkeypatch, raw):
    """M11: the test-path freeze after the e2e run keeps the files a person's answer unfroze, as the one after the test
    gate does, so the commit holds the edited test and not the red version."""
    from .test_tdd_green import CORRECTED, answer_naming, two_test_red

    red_step_ = two_test_red()
    red_step_.writes = {**red_step_.writes, "e2e/test_layout.py": BROWSER}
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([red_step_, fix], e2e=e2e_config(free_port()))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses={WIDTH: "passed"})
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py:9` to use a 100.0 amount.")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert [c.name for c in calls] == ["e2e-task"]
    assert bench.wb.git.run("show", f"{green.sha}:tests/test_discount.py").stdout == CORRECTED
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == CORRECTED


def test_scn_imp_551_the_attempt_of_a_server_that_is_not_ready_is_counted(make_bench, monkeypatch):
    bench = make_bench([browser_red(), green_step()], e2e=e2e_config(free_port()), implementer={"max_task_attempts": 1})
    stub_e2e(monkeypatch, bench, [], raises=True, log_text="Error: listen EADDRINUSE :::3000\n")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "max_task_attempts (1) reached in green" in outcome.reason
    assert "last failure: the e2e server was not ready (see x.log)" in outcome.reason
    [failed] = bench.events("task.attempt_failed")
    assert failed["phase"] == "green" and failed["reason"].startswith("the e2e server was not ready")


def test_scn_imp_554_the_next_red_attempt_may_change_the_test_after_an_already_satisfied_failure(
    make_bench, monkeypatch
):
    fixed = Step(
        writes={
            "tests/test_existing.py": EXISTING,
            "e2e/test_existing_ui.py": "def test_ui():\n    assert 1500 == 1500\n",
        },
        structured=result("red", criteria_ids=[KNOWN]),
    )  # fmt: skip
    bench = make_bench([satisfied_step(), fixed], e2e=e2e_config(free_port()))
    calls: list = []
    stub_e2e(monkeypatch, bench, calls, statuses=[{EXISTING_UI: "failed"}, {EXISTING_UI: "passed"}])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome
    assert [c.name for c in calls] == ["e2e-task", "e2e-task"]
    committed = bench.wb.git.run("show", "HEAD:e2e/test_existing_ui.py").stdout
    assert "1500 == 1500" in committed  # the second attempt's version, not the one that failed
    assert [e["phase"] for e in bench.events("task.attempt_failed")] == ["red"]


def test_the_real_red_prompt_says_the_browser_tests_are_frozen_when_the_test_globs_cover_them(make_bench):
    """`_prompt` sets `PromptContext.e2e_frozen` from `tdd.test_globs` and the e2e directory."""
    bench = make_bench([browser_red()], e2e=e2e_config(free_port()))
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    prompt = bench.adapter.requests[0].prompt
    assert "The step that completes this task runs them" in prompt and "frozen after this step" in prompt


def test_the_real_red_prompt_does_not_say_frozen_when_the_test_globs_miss_the_e2e_directory(make_bench, monkeypatch):
    monkeypatch.setattr("l4.implementer.tdd._matches", lambda globs, path: False)
    bench = make_bench([browser_red()], e2e=e2e_config(free_port()))
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    prompt = bench.adapter.requests[0].prompt
    assert "The step that completes this task runs them" in prompt and "frozen after this step" not in prompt
