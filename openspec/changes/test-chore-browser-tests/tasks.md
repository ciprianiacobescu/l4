Read `design.md` first; it names the code each decision touches (D1-D8). Requirements: L4-IMP-108..111 (`docs/SPEC.md`),
scenarios SCN-IMP-586..600. Run single test files only (`uv run --frozen pytest <file> -q`), never a whole directory,
never two runs at once, and never a wait loop on `pgrep`.

Test setup for every task below: `run_tests_chore(make_bench, step)` of `tests/unit/implementer/test_single_phase.py`
(copy it, or import it, into the new `tests/unit/implementer/test_test_chore_browser.py`), with
`make_bench(script, e2e=e2e_config(free_port()))` (`tests/unit/_web_helpers.py`; add `build=[...]` for a build). Stub
`l4.implementer.tdd.run_e2e` with `stub_e2e` of `tests/unit/implementer/test_fix_chore_e2e.py` (import it; extend it
with an optional `details` mapping if a failing case needs a message). A browser test is
`BROWSER = "def test_regions():\n    assert 88 < 40\n"` written as `e2e/test_layout.py` (any parseable test function: the
e2e run is stubbed). A retake is a fix marker with the finding under `test_chores` and `retakes`, as
`test_a_retaken_tests_item_with_no_test_to_add_completes_as_already_done` sets it up.

## 1. The e2e run of a test chore (L4-IMP-108; D1-D4, D6)

- [ ] 1.1 Write the tests first in `tests/unit/implementer/test_test_chore_browser.py`:
  - SCN-IMP-586: the stub reports `test_layout::test_regions[chromium]` passed; done; the stub was called once with
    `name="e2e-test-chore"` and `must_contain == []`; `task.tests_added` has `files == ["e2e/test_layout.py"]`,
    `tests == []` and the id in `e2e_tests`;
  - SCN-IMP-587: the stub reports it failed with the message `assert 88 < 40`: `done.status == "failed"`, the reason
    starts with `the task's browser tests do not pass:`, `done.excerpt` holds `assert 88 < 40`, HEAD did not move;
  - SCN-IMP-588: the stub reports no id of `test_regions`, then (a second test) only `skipped`: failed, the reason
    starts with `no tests added:` and holds `e2e/test_layout.py::test_regions`; `e2e.task_tests_unseen` has
    `phase == "single"`;
  - SCN-IMP-589: a step that writes only `tests/test_more.py` (as `test_a_test_chore_keeps_a_new_test_file`), with and
    without `e2e=`: the stub is never called; done;
  - SCN-IMP-590: the stub raises `ServerNotReady` with a log `Error: listen EADDRINUSE`: failed, the reason starts with
    `the e2e server was not ready (see`, the excerpt holds `EADDRINUSE`;
  - SCN-IMP-591: `build=[f"{sys.executable} scripts/build.py"]` writes `.l4-out/built`; the stub's
    `writes={"test-results/trace.zip": "x", "src/pytdd/pricing.py": "# rewritten\n"}`; done; `git show --stat HEAD`
    holds `e2e/test_layout.py` only (with the tasks file), and `src/pytdd/pricing.py` is its base content;
  - SCN-IMP-592: a retake whose step writes nothing new: done as already done (`task.done{tdd: "already-done"}`), the
    stub never called (no browser test kept);
  - SCN-IMP-600: a retake whose step writes the browser test and a stub report that does not show it: failed, the
    reason starts with `no tests added:` and names `e2e/test_layout.py::test_regions`, no `task.done`;
  - a step that writes a unit test that breaks an existing one and the browser test: the stub is not called;
  - a selecting e2e command (`pytest e2e -m browser`): the stub is not called, `e2e.task_run_skipped` has
    `phase == "single"`.
  Run the file and see the tests fail.
- [ ] 1.2 Then implement in `src/l4/implementer/tdd.py`:
  - `_task_e2e_run(wb, task, tests, phase, name="e2e-task")` returns a `TaskE2e(reason, excerpt, passed, unseen,
    report)` dataclass: `passed` maps each id of a task test that `passed` (for a test with no failed or errored id)
    to its `TestCase`, `unseen` is the list it builds today; `_task_e2e_reason` returns `(run.reason, run.excerpt)` as
    before, so green and the already-satisfied finish do not change;
  - `_chore_browser_tests(wb, task, base, tests) -> TaskE2e` in the shape of `_task_e2e_reason`: `_tree_state`, then
    `_task_e2e_run(..., phase="single", name="e2e-test-chore")`, and in a `finally`
    `_drop_gate_output(wb, task, base, before, (), freeze_phase=None)`;
  - in `run_single` for `adds_tests` (D2): `browser` from `task_browser_tests(wb, base, None)` limited to
    `review.kept`, only when `e2e_configured(wb.cfg)`; after `green_failures`, when no reason and `gate.report` is not
    None, `_runnable_browser_tests(wb, task, "single", browser, gate.report.tests)` and, when that leaves tests,
    `_chore_browser_tests`, `restore_replay(wb, "e2e run")`; `added_unit`, `added_e2e`, `added = added_unit +
    added_e2e` (D6) for the `no tests added` and `decision_calling_code_wrong` checks; `_already_done` of a retake only
    when `review.kept` is empty (D6); `task.tests_added` keeps `tests=added_unit` and gets `e2e_tests=added_e2e` when
    not empty.
  Run the new tests, then `tests/unit/implementer/test_single_phase.py`, `tests/unit/implementer/test_e2e_task_steps.py`,
  `tests/unit/implementer/test_fix_chore_e2e.py` and `tests/unit/implementer/test_already_satisfied.py`, one at a time.

## 2. The text of `no tests added` (L4-IMP-109; D5)

- [ ] 2.1 Write the tests first (SCN-IMP-593), one per form of the e2e clause, and one for a step that kept nothing
  (`this step kept no new test file and appended no test` first). Update the three equality checks of
  `test_single_phase.py` (`done.reason == "no tests added"`) to the new text, and see the tests fail.
- [ ] 2.2 Then add `_no_tests_text(wb, kept, e2e)` (D5) and use it at the `reason = "no tests added"` of `run_single`.
  The command is `" ".join(command.split())` cut at 120 characters, lists use `_list`. Leave the red step's
  `RedVerdict(False, "no tests added")` alone. Run the tests and `tests/unit/archive/test_hooks.py`.

## 3. The cap and the discrimination runs (L4-IMP-110; D6, D7)

- [ ] 3.1 Write the tests first:
  - SCN-IMP-594: the task title cites a criterion; the step writes `tests/test_more.py` with a test that fails in the
    zero-value run, and the browser test; stub `l4.implementer.tdd.discriminate_extra` (or let it run, as the tests of
    `test_single_phase.py` for a criterion-citing chore do) and assert it was asked about the unit id only;
  - SCN-IMP-595: the task title cites a criterion and only the browser test is added: `done.status == "held"`, the
    held check has `check == "tests"`, `tests == ("test_layout::test_regions[chromium]",)`, `runs == ()` and a reason
    that holds `the discrimination runs use the unit gate, which does not run browser tests`; no gate named
    `test-extra-zero` or `test-extra-base` ran; then an accepted override (as the existing held-test-chore tests make
    one) replays the step to done with `discriminating == ["test_layout::test_regions[chromium]"]`;
  - SCN-IMP-596: `verifier.max_criteria_per_test: 2` and a browser id that names three of the unit's criterion ids:
    failed with `too many criteria on one test:` naming it.
  Run them and see them fail.
- [ ] 3.2 Then implement (D6, D7): `over_cap_text` gets the merged mapping; `_discriminating_tests` gets `added_unit`;
  a browser-only chore of a cited criterion builds the `HeldCheck` of D7 with the constant `BROWSER_ONLY` and no run,
  and goes through the same `accepted_overrides` / `capture` path as the existing hold. Run the tests and
  `tests/unit/implementer/test_single_phase.py`.

## 4. The prompts and the question note (L4-IMP-111; D8)

- [ ] 4.1 Write the tests first (in `tests/unit/implementer/test_prompt.py` with `render_prompt` and a `PromptContext`,
  and in `tests/unit/implementer/test_loop.py` or the new file for the note):
  - SCN-IMP-599: role `single`, `adds_tests=True`, `e2e_dir="e2e"`, `e2e_frozen=True` and `False`: `# Browser tests`
    and `counts as an added test` in both, `a file there is not a test file for this task` only when not frozen; with
    `e2e_dir=None` no such block; `template_version` unchanged;
  - SCN-IMP-598: `retake_tests=True` gives `# This item was taken before` and `in a new test file`; False gives
    neither;
  - SCN-IMP-597: `chore_question_note(unit, kind="tests")` starts with `Harness note: this is a fix task. It adds
    tests:` and holds `a missing check can go into a new test file`; `kind="fix"` (the default) is the text of 0.4.59;
    a blocked test chore's question in `questions.md` holds the tests note and its `question.raised` has `chore: true`.
  Run and see them fail.
- [ ] 4.2 Then add `PromptContext.retake_tests: bool = False`, the two blocks for role `single` with `adds_tests` in
  `src/l4/implementer/prompt.py`, pass `retake_tests` from `run_single` (`retake`) through `step_or_replay`,
  `agent_step` and `_prompt` in `src/l4/implementer/tdd.py`; give `chore_question_note` the `kind` keyword and
  `_with_note` a `chore_kind` keyword in `src/l4/implementer/loop.py`, and pass `chore_kind(wb.ref.path, task.title) or
  "fix"` from the chore branch of `_run_task` into `_raise_blocked`. Run the prompt tests
  (`tests/unit/implementer/test_prompt.py`, `test_prompt_context.py`, `test_prompt_cap.py`), the note tests and
  `tests/unit/delegate/test_pass.py` (the delegate's chore fallback reads the first sentence).

## 5. Checks

- [ ] 5.1 `docs/SPEC.md` holds L4-IMP-108..111, SCN-IMP-586..600, change-table row 138 and the L4-VER-006 amendment.
  Check them against the code and tell the orchestrator where they differ; do not edit `docs/SPEC.md`, `CHANGELOG.md`
  or `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [ ] 5.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
