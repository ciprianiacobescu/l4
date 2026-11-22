"""L4-IMP-108..110 (test-chore-browser-tests): a test chore runs the browser tests it writes in the e2e gate and counts
those that passed, says what each gate found when it added none, and checks each new test against the report that
holds it."""

import sys

from l4.agents.fake import Step
from l4.implementer import loop, tdd
from l4.implementer.discrimination import ExtraRun
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .._web_helpers import e2e_config, free_port
from .conftest import KNOWN, UNKNOWN, green_step, red_step, result
from .test_criterion_tests_chore import BOUND
from .test_e2e_task_steps import stub_e2e
from .test_fix_chore_e2e import BUILD_OK, commit_files
from .test_held_accept import answer_q
from .test_single_phase import HOLD, NEW_TESTS, TESTS_TASK, UNIT_TASK

BROWSER = "def test_regions():\n    assert 88 < 40\n"  # the e2e run is stubbed: only the parse matters
BROWSER_PATH = "e2e/test_layout.py"
BROWSER_ID = "test_layout::test_regions[chromium]"
SHOWN = "e2e/test_layout.py::test_regions"
WRITE_BROWSER = Step(writes={BROWSER_PATH: BROWSER}, structured=result("single"))
UNIT_AND_BROWSER = Step(
    writes={"tests/test_more.py": NEW_TESTS, BROWSER_PATH: BROWSER}, structured=result("single")
)  # fmt: skip


def chore(
    make_bench,
    monkeypatch,
    step: Step,
    *,
    task: Task = TESTS_TASK,
    findings=HOLD,
    e2e: bool = True,
    selecting: bool = False,
    build: bool = False,
    retake: bool = False,
    stub: bool = True,
    kind: str = "tests",
    verifier: dict | None = None,
    **stub_kw,
):
    """The unit's red and green are done, then a test chore runs `step`; the e2e gate is stubbed. -> bench, outcome,
    the calls of the stubbed gate."""
    gates: dict = {}
    if e2e:
        gates["e2e"] = e2e_config(free_port())
        if selecting:
            gates["e2e"]["command"] += " -m browser"
    if build:
        gates["build"] = [f"{sys.executable} scripts/build.py"]
    if verifier:
        gates["verifier"] = verifier
    bench = make_bench([red_step(), green_step(), step], **gates)
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().rstrip("\n") + f"\n- [ ] {task.title}\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a second task")
    if build:
        commit_files(bench, {"scripts/build.py": BUILD_OK})
    red = run_red(bench.wb, UNIT_TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert run_green(bench.wb, UNIT_TASK, red, attempt=1).status == "ok"
    calls: list = []
    if stub:
        stub_e2e(monkeypatch, bench, calls, **stub_kw)
    before = bench.wb.head()
    bench.before = before
    return bench, run_single(bench.wb, task, findings, attempt=1, kind=kind, retake=retake), calls


def test_scn_imp_586_a_new_browser_test_of_a_test_chore_counts(make_bench, monkeypatch):
    bench, done, calls = chore(make_bench, monkeypatch, WRITE_BROWSER, statuses={BROWSER_ID: "passed"})
    assert done.status == "ok", done.reason
    assert [(c.name, c.must_contain) for c in calls] == [("e2e-test-chore", [])]
    [added] = bench.events("task.tests_added")
    assert added["files"] == [BROWSER_PATH] and added["tests"] == [] and added["e2e_tests"] == [BROWSER_ID]
    assert BROWSER_PATH in bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout


def test_scn_imp_587_a_failing_browser_test_fails_the_attempt_with_its_text(make_bench, monkeypatch):
    bench, done, calls = chore(
        make_bench, monkeypatch, WRITE_BROWSER, statuses={BROWSER_ID: "failed"}, details={BROWSER_ID: "assert 88 < 40"}
    )
    assert done.status == "failed" and done.reason.startswith("the task's browser tests do not pass:")
    assert BROWSER_ID in done.reason and "assert 88 < 40" in done.excerpt
    assert bench.wb.head() == bench.before and bench.events("task.tests_added") == []
    assert "[ ] 1.2" in (bench.wb.ref.path / "tasks.md").read_text()
    assert bench.wb.is_clean()


def test_scn_imp_588_a_browser_test_the_report_does_not_show_is_not_counted(make_bench, monkeypatch):
    bench, done, calls = chore(make_bench, monkeypatch, WRITE_BROWSER, statuses={})
    assert done.status == "failed" and done.reason.startswith("no tests added:") and SHOWN in done.reason
    [note] = bench.events("e2e.task_tests_unseen")
    assert note["phase"] == "single" and note["tests"] == [SHOWN]
    assert bench.events("task.tests_added") == [] and bench.wb.head() == bench.before


def test_scn_imp_588_a_skipped_only_browser_test_is_not_counted_either(make_bench, monkeypatch):
    bench, done, _ = chore(make_bench, monkeypatch, WRITE_BROWSER, statuses={BROWSER_ID: "skipped"})
    assert done.status == "failed" and done.reason.startswith("no tests added:") and SHOWN in done.reason
    assert bench.events("e2e.task_tests_unseen")[0]["phase"] == "single"


def test_scn_imp_589_a_test_chore_with_no_browser_test_runs_no_e2e_gate(make_bench, monkeypatch):
    step = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, done, calls = chore(make_bench, monkeypatch, step, build=True)
    assert done.status == "ok", done.reason
    assert calls == [] and "build" not in [e["name"] for e in bench.events("gate.finished")]
    [added] = bench.events("task.tests_added")
    assert "e2e_tests" not in added and added["tests"] == ["tests.test_more::test_total_of_two"]


def test_scn_imp_589_without_gates_e2e_nothing_runs_either(make_bench, monkeypatch):
    step = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, done, calls = chore(make_bench, monkeypatch, step, e2e=False)
    assert done.status == "ok", done.reason
    assert calls == []


def test_scn_imp_590_a_server_that_never_gets_ready_fails_the_attempt(make_bench, monkeypatch):
    bench, done, calls = chore(
        make_bench, monkeypatch, WRITE_BROWSER, raises=True, log_text="Error: listen EADDRINUSE :::3000\n"
    )
    assert done.status == "failed" and done.reason.startswith("the e2e server was not ready (see")
    assert "EADDRINUSE" in done.excerpt and bench.events("task.tests_added") == []
    assert bench.wb.head() == bench.before


def test_scn_imp_591_what_the_e2e_run_writes_is_not_committed_and_the_chores_files_stay(make_bench, monkeypatch):
    bench, done, calls = chore(
        make_bench, monkeypatch, WRITE_BROWSER, build=True, statuses={BROWSER_ID: "passed"},
        writes={"test-results/trace.zip": "x", "src/pytdd/pricing.py": "# rewritten\n"},
    )  # fmt: skip
    assert done.status == "ok", done.reason
    assert calls[0].built  # the build ran before the e2e gate
    shown = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert BROWSER_PATH in shown
    assert not {"test-results/trace.zip", "src/pytdd/pricing.py"} & set(shown)
    assert not any(p.startswith(".l4-out") for p in shown)
    assert (bench.wb.worktree / "src/pytdd/pricing.py").read_text() != "# rewritten\n"
    assert (bench.wb.worktree / BROWSER_PATH).read_text() == BROWSER  # the freeze did not put it back


def test_scn_imp_592_a_retake_that_keeps_no_test_file_is_already_done(make_bench, monkeypatch):
    bench, done, calls = chore(make_bench, monkeypatch, Step(structured=result("single")), retake=True)
    assert done.status == "ok", done.reason
    assert [e["tdd"] for e in bench.events("task.done") if e["task"] == "1.2"] == ["already-done"]
    assert calls == [] and bench.events("task.tests_added") == []


def test_scn_imp_600_a_retake_whose_browser_test_no_gate_counted_fails_and_is_not_ticked(make_bench, monkeypatch):
    bench, done, calls = chore(make_bench, monkeypatch, WRITE_BROWSER, retake=True, statuses={})
    assert done.status == "failed" and done.reason.startswith("no tests added:") and SHOWN in done.reason
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]
    assert "[ ] 1.2" in (bench.wb.ref.path / "tasks.md").read_text()
    assert bench.wb.head() == bench.before and bench.wb.is_clean()


def test_a_retake_whose_run_was_skipped_is_not_discarded_with_the_task_ticked(make_bench, monkeypatch):
    bench, done, calls = chore(make_bench, monkeypatch, WRITE_BROWSER, retake=True, selecting=True)
    assert done.status == "failed" and "the e2e gate did not run" in done.reason
    assert [e["tdd"] for e in bench.events("task.done") if e["task"] == "1.2"] == []


def test_a_retake_that_keeps_a_helper_with_no_test_fails_once(make_bench, monkeypatch):
    step = Step(writes={"tests/test_helpers.py": "VALUE = 1\n"}, structured=result("single"))
    bench, done, _ = chore(make_bench, monkeypatch, step, retake=True, e2e=False)
    assert done.status == "failed" and done.reason.startswith("no tests added:")


def test_a_selecting_e2e_command_skips_the_run_and_says_so(make_bench, monkeypatch):
    bench, done, calls = chore(make_bench, monkeypatch, WRITE_BROWSER, selecting=True, statuses={BROWSER_ID: "passed"})
    assert calls == [] and done.status == "failed"
    [note] = bench.events("e2e.task_run_skipped")
    assert note["phase"] == "single" and "-m" in note["reason"] and note["tests"] == [SHOWN]


def test_a_failing_unit_test_next_to_the_browser_test_is_refused_by_the_test_gate(make_bench, monkeypatch):
    step = Step(
        writes={BROWSER_PATH: BROWSER, "tests/test_bad.py": "def test_bad():\n    assert 0\n"},
        structured=result("single"),
    )
    _, done, calls = chore(make_bench, monkeypatch, step, statuses={BROWSER_ID: "passed"})
    assert done.status == "failed" and calls == []


# --- L4-IMP-109: the reason says what each gate found (SCN-IMP-593) --------------------------------------------------


def test_scn_imp_593_without_gates_e2e_the_reason_says_a_browser_test_does_not_count(make_bench, monkeypatch):
    _, done, _ = chore(make_bench, monkeypatch, WRITE_BROWSER, e2e=False)
    assert done.status == "failed" and done.reason.startswith("no tests added: the test gate (")
    assert "reports no new passing test; " in done.reason
    assert "the e2e gate is not configured, so a browser test does not count" in done.reason


def test_scn_imp_593_a_step_that_kept_no_browser_test_says_the_e2e_gate_did_not_run(make_bench, monkeypatch):
    step = Step(writes={"tests/test_helpers.py": "VALUE = 1\n"}, structured=result("single"))
    _, done, calls = chore(make_bench, monkeypatch, step)
    assert done.reason.startswith("no tests added: the test gate (") and calls == []
    assert "this step kept no browser test under e2e/, so the e2e gate did not run" in done.reason


def test_scn_imp_593_a_selecting_command_gives_the_skip_reason(make_bench, monkeypatch):
    _, done, _ = chore(make_bench, monkeypatch, WRITE_BROWSER, selecting=True)
    assert done.reason.startswith("no tests added: the test gate (")
    assert "the e2e gate did not run: the e2e command selects tests with" in done.reason


def test_scn_imp_593_a_report_that_does_not_show_the_test_names_it(make_bench, monkeypatch):
    _, done, _ = chore(make_bench, monkeypatch, WRITE_BROWSER, statuses={})
    assert done.reason.startswith("no tests added: the test gate (") and "the e2e gate (" in done.reason
    assert f"reports none of this step's browser tests as passed: {SHOWN}" in done.reason


def test_a_step_that_kept_nothing_says_so_first(make_bench, monkeypatch):
    _, done, _ = chore(make_bench, monkeypatch, Step(structured=result("single")), e2e=False)
    assert done.reason.startswith("no tests added: this step kept no new test file and appended no test; the test gate")


def test_a_long_test_command_is_shown_on_one_line_and_cut(make_bench, monkeypatch):
    _, done, _ = chore(make_bench, monkeypatch, Step(structured=result("single")), e2e=False)
    command = done.reason.split("the test gate (", 1)[1].split(")", 1)[0]
    assert "\n" not in command and len(command) <= 120


# --- L4-IMP-110: the cap and the discrimination runs ------------------------------------------------------------------


def spy_discriminate(monkeypatch) -> list:
    asked: list = []

    def fake(wb, tests, base, **kw):  # FAKE: every asked test fails by assertion on the zero values
        asked.append(sorted(tests))
        return ExtraRun(accepted=dict.fromkeys(tests, "zero_value"))

    monkeypatch.setattr(tdd, "discriminate_extra", fake)
    return asked


def test_scn_imp_594_the_discrimination_runs_get_the_unit_tests_only(make_bench, monkeypatch):
    asked = spy_discriminate(monkeypatch)
    bench, done, calls = chore(make_bench, monkeypatch, UNIT_AND_BROWSER, task=BOUND, statuses={BROWSER_ID: "passed"})
    assert done.status == "ok", done.reason
    assert asked == [["tests.test_more::test_total_of_two"]]
    [added] = bench.events("task.tests_added")
    assert added["discriminating"] == ["tests.test_more::test_total_of_two"] and added["e2e_tests"] == [BROWSER_ID]


def test_scn_imp_595_a_cited_criterion_with_only_browser_tests_is_held_and_says_why(make_bench, monkeypatch, raw):
    asked: list = []
    monkeypatch.setattr(tdd, "discriminate_extra", lambda wb, tests, base, **kw: asked.append(tests))
    bench, first, calls = chore(make_bench, monkeypatch, WRITE_BROWSER, task=BOUND, statuses={BROWSER_ID: "passed"})
    assert first.status == "held" and first.held is not None and first.held.check == "tests"
    assert first.held.tests == (BROWSER_ID,) and first.held.runs == ()
    assert "the discrimination runs use the unit gate, which does not run browser tests" in first.held.reason
    assert "the harness cannot check that they fail when the code is wrong" in first.held.reason
    assert asked == [] and not any(e["name"].startswith("test-extra") for e in bench.events("gate.finished"))
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    [qid] = loop._raise_held(bench.wb, BOUND, first.held, 1)
    answer_q(bench, raw, qid, "accept: the browser test cannot be run against wrong code here")
    stub_e2e(monkeypatch, bench, calls, statuses={BROWSER_ID: "passed"})
    requests = len(bench.adapter.requests)
    second = run_single(bench.wb, BOUND, HOLD, attempt=2, kind="tests")
    assert second.status == "ok", second.reason
    assert len(bench.adapter.requests) == requests  # the saved step was replayed: no agent ran
    assert bench.events("task.tests_added")[-1]["discriminating"] == [BROWSER_ID]


def test_scn_imp_595_the_unit_tests_are_judged_and_the_browser_tests_go_along(make_bench, monkeypatch):
    """When every unit test is inconclusive the chore is held on the unit ids, not on the browser ones."""
    monkeypatch.setattr(
        tdd,
        "discriminate_extra",
        lambda wb, tests, base, **kw: ExtraRun(inconclusive=dict.fromkeys(tests, "did not run in test-extra-zero")),
    )
    bench, done, _ = chore(make_bench, monkeypatch, UNIT_AND_BROWSER, task=BOUND, statuses={BROWSER_ID: "passed"})
    assert done.status == "held" and done.held is not None
    assert done.held.tests == ("tests.test_more::test_total_of_two",)


def test_scn_imp_596_the_cap_counts_a_browser_tests_criteria(make_bench, monkeypatch):
    wide = f"e2e.test_layout::test_regions[{KNOWN}-{UNKNOWN}]"  # the report's id names two criteria of the unit
    bench, done, _ = chore(
        make_bench, monkeypatch, WRITE_BROWSER, task=BOUND, verifier={"max_criteria_per_test": 1},
        statuses={wide: "passed"},
    )  # fmt: skip
    assert done.status == "failed"
    assert done.reason.startswith("too many criteria on one test:") and "test_regions" in done.reason
    assert bench.events("task.tests_added") == []


def test_a_task_that_cites_no_criterion_is_not_discriminated(make_bench, monkeypatch):
    asked = spy_discriminate(monkeypatch)
    bench, done, _ = chore(make_bench, monkeypatch, UNIT_AND_BROWSER, statuses={BROWSER_ID: "passed"})
    assert done.status == "ok", done.reason
    assert asked == []
    assert "discriminating" not in bench.events("task.tests_added")[0]


# --- L4-IMP-111: the prompt and the question note ---------------------------------------------------------------------


def test_scn_imp_599_a_test_chores_prompt_names_the_e2e_gate_when_the_project_has_one():
    from l4.implementer.prompt import render_prompt

    from .test_prompt import ctx

    frozen = render_prompt("single", ctx(adds_tests=True, e2e_dir="e2e", e2e_frozen=True))
    open_ = render_prompt("single", ctx(adds_tests=True, e2e_dir="e2e", e2e_frozen=False))
    plain = render_prompt("single", ctx(adds_tests=True))
    for text in (frozen.text, open_.text):
        assert "# Browser tests" in text and "counts as an added test" in text
        assert "e2e/test_<name>.py" in text and "You cannot run it in this sandbox" in text
    assert "a file there is not a test file for this task" not in frozen.text
    assert "a file there is not a test file for this task" in open_.text
    assert "# Browser tests" not in plain.text
    assert frozen.template_version == open_.template_version == plain.template_version == "contract@13+single_tests@5"
    assert "# Browser tests" not in render_prompt("single", ctx(e2e_dir="e2e")).text  # a fix chore: unchanged


def test_scn_imp_598_a_retakes_prompt_says_the_earlier_tests_stay_and_new_tests_go_in_a_new_file():
    from l4.implementer.prompt import render_prompt

    from .test_prompt import ctx

    taken = render_prompt("single", ctx(adds_tests=True, retake_tests=True))
    first = render_prompt("single", ctx(adds_tests=True))
    assert "# This item was taken before" in taken.text and "in a new test file" in taken.text
    assert "# This item was taken before" not in first.text and "in a new test file" not in first.text
    assert taken.template_version == first.template_version == "contract@13+single_tests@5"
    assert "# This item was taken before" not in render_prompt("single", ctx(retake_tests=True)).text


def test_scn_imp_598_a_retaking_chores_prompt_reaches_the_agent(make_bench, monkeypatch):
    bench, _, _ = chore(make_bench, monkeypatch, WRITE_BROWSER, retake=True, statuses={BROWSER_ID: "passed"})
    assert "# This item was taken before" in bench.adapter.requests[2].prompt
    assert "# Browser tests" in bench.adapter.requests[2].prompt


def test_scn_imp_597_the_test_chores_question_note_says_what_a_test_chore_may_keep():
    note = loop.chore_question_note("add-x-fix-1", kind="tests")
    assert note.startswith("Harness note: this is a fix task. It adds tests:")
    assert "a missing check can go into a new test file" in note
    assert "put back whatever the answer says" in note and "a person must commit the change" in note.lower()
    assert 'l4 questions answer Q-NNN --unit add-x-fix-1 --text "..."' in note
    assert loop.chore_question_note("add-x-fix-1") == loop.chore_question_note("add-x-fix-1", kind="fix")
    assert "It cannot unfreeze a test or test-support file" in loop.chore_question_note("add-x-fix-1")


def test_scn_imp_597_a_blocked_test_chores_question_holds_the_tests_note(make_bench, monkeypatch):
    asking = {"title": "Which layout?", "context": "the item is unclear", "kind": "technical", "options": []}
    monkeypatch.setattr(loop, "chore_findings", lambda path, title: ("F-00000001",))
    monkeypatch.setattr(loop, "chore_kind", lambda path, title: "tests")
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[asking]))])
    outcome = loop.run_task(bench.wb, UNIT_TASK)
    assert outcome.status == "blocked"
    text = " ".join((bench.wb.ref.path / "questions.md").read_text().split())  # the file wraps its lines
    assert "Harness note: this is a fix task. It adds tests:" in text
    assert "a missing check can go into a new test file" in text
    assert "It cannot unfreeze a test or test-support file" not in text
    [raised] = bench.events("question.raised")
    assert raised["chore"] is True
