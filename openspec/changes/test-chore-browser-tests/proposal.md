## Why

A TypeScript web consumer runs its browser tests with Python (Playwright under pytest, in `e2e/`, as `gates.e2e`); its
unit gate is a Node command. A person's feedback item of kind `tests` asked for "a browser test for the layout of six
admin regions". The item became a test chore (`kind="tests"`). Attempts 1, 3 and 4 added the browser test in `e2e/` and
failed with `no tests added`; attempt 2 idled out. Attempt 5 passed only by adding a Node meta-test that reads the
browser test's file, and its discrimination check was then inconclusive, so the chore was held until an answer came.
One requested browser test took five attempts and nearly 80 minutes, and the browser test itself never ran before
verification.

The verifier then judged the item not addressed: the new browser test did not call a helper the item asked for. The
fix unit's task was a test chore again; the step edited the browser test that the earlier take had written, the guard
put the edit back, and the agent asked a question that a person answered with a commit by hand. The question's harness
note said "this is a fix task. It cannot unfreeze a test or test-support file".

Verified at 0.4.59 (62188257):

- `run_single` (`src/l4/implementer/tdd.py:3552`) counts a test chore's new tests from the unit gate's report only:
  `added = sorted(i for i in new_test_ids(base_report, gate.report) if ... == "passed")` (`:3644-3648`), then
  `reason = "no tests added"` (`:3653`) with no excerpt and no word on which gate was read. The e2e gate runs in a chore
  only for kind `fix` (`e2e_scope = _e2e_chore_scope(...) if kind == "fix" else None`, `:3590`).
- A `tests` feedback item already becomes a test chore, and so does a finding that says it was not addressed:
  `fixunit._feedback_candidate` sets `tests=ref.kind == "tests"` (`src/l4/verifier/fixunit.py:347`), `plan_fix_unit`
  makes the task `chore=True, tests=True` (`:434`), the provider lists it under `test_chores` (`specs/openspec.py:341`),
  and `chore_kind` returns `tests` (`specs/fixmark.py:103`). The consumer's fix-unit marker listed the finding under
  `test_chores`, and its prompt was `single_tests@5`. The claim that the finding became a plain fix chore is wrong.
- What stopped the fix unit's test chore is `review_test_chore` (`tdd.py:2630`): it keeps new test files and new tests
  appended to `own_tests`, and `own_tests` is `proved_test_files` (`tdd.py:2351`), the files of `task.red_ok.frozen`
  only. The browser test file an earlier test chore added (its `task.tests_added.files`) is an existing test file that is
  not the unit's own, so the edit was put back (`guard.test_tamper`). A new test file with the missing check was allowed,
  but it would not have counted either (the first point).
- `chore_question_note` (`src/l4/implementer/loop.py:137`) is added to every technical question of every chore kind
  (`_with_note`, `loop.py:196-198`; `chore_unit=wb.ref.id` for every chore at `loop.py:680`), so a test chore's
  question says that it is a fix task that cannot change a test.

## What Changes

- A test chore whose kept files hold browser tests (the tests pytest would collect from the Python files under the e2e
  test directory that the step added or whose own definition it changed, as L4-IMP-101 reads them) runs `gates.build`
  and the e2e gate after its test gate, when `gates.e2e` is configured. A browser test of the step counts as an added
  test when the e2e report shows one of its ids passed. A browser test of the step that failed or errored fails the
  attempt with its failure text, as in green. One the report does not show is not counted and is a ledger note. What the
  runs write is not committed, and the step's own test files stay.
- A test chore that adds no test says, after `no tests added:`, what each gate found: the test gate, and the e2e gate
  (not configured, no browser test written, the run skipped and why, or the browser tests the report did not show
  passing).
- The discrimination runs of a test chore that cites a criterion get the unit gate's tests only, which are the only
  tests they can run. A chore whose only new tests are browser tests is held with a harness question, as an inconclusive
  check is today, and the question says that the browser tests passed in the e2e gate and that the runs cannot reach
  them. The per-test cap reads each test from the report that holds it.
- A test chore's prompt says, when `gates.e2e` is configured, that a browser test it adds under the e2e directory counts
  and runs after the step, and whether `tdd.test_globs` covers that directory. The prompt of a test chore that retakes
  a feedback item says that the test files an earlier take added are existing test files, and that what the item still
  asks for goes into new tests in a new test file. A technical question of a test chore gets a harness note that says
  what a test chore may keep, not the fix chore's note.

Non-goals: letting a test chore edit the test files that an earlier take of the same item added (considered in
design.md D9, not proposed); browser tests in another language; a deadline cap for a chore's e2e run; a change to the
fix chore (L4-IMP-090), to the repair chore or to green (L4-IMP-101).

## Capabilities

### New Capabilities

- `test-chore-browser-tests`: L4-IMP-108 (a test chore counts the browser tests it writes), L4-IMP-109 (`no tests
  added` says what each gate found), L4-IMP-110 (the discrimination runs and the cap read the right report), L4-IMP-111
  (a test chore's prompt and questions say what it may change).

### Modified Capabilities

- L4-VER-006: the test chore's "at least one new test must pass" counts a browser test the e2e gate ran.

## Impact

- `src/l4/implementer/tdd.py`: `run_single`, a new `_chore_browser_tests`, `_task_e2e_run` returns the passed ids too
  (`_task_e2e_reason` keeps its return value), a new `_no_tests_text`, `_discriminating_tests` callers.
- `src/l4/implementer/prompt.py`: two new `PromptContext` fields and two blocks for the `single_tests` role (no
  template file changes, so no template version moves).
- `src/l4/implementer/loop.py`: `chore_question_note` takes the chore kind; `_with_note` and `_raise_blocked` pass it.
- `docs/SPEC.md` (L4-IMP-108..111, SCN-IMP-586..599, change-table row 138, the L4-VER-006 amendment), `CHANGELOG.md`,
  `docs/runbook.md`.
- Ledger: `gate.finished` for `build` and `e2e-test-chore`; the notes `e2e.task_tests_unseen` and
  `e2e.task_run_skipped` with `phase: "single"`; `task.tests_added` gains `e2e_tests` (an older reader ignores it). No
  new event type, no configuration key.
- Cost: per test-chore attempt that kept a browser test and passed its test gate, one build and one e2e suite run.
