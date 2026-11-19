## Why

A consumer unit added browser tests (Playwright, run by pytest under `gates.e2e`) in the red steps of its TDD tasks.
One of them had a wrong expectation: it built its page with `page.set_content`, which keeps the browser's default 8px
body margin, so the page's scroll width was 1508 and not the 1500 the test asserted. Red and green run only
`gates.test`, and the unit gate does not run the e2e directory, so the test went through all nine tasks without ever
running. It ran first at verification step 3, which failed. The verifier spawned a fix unit; its fix chore may not
change a test or a support file (ci-evidence D11), so the guard put back the implementer's edit of the support file the
test uses, the implementer asked a question, and the delegate escalated it to a person. In the parent task's green step
the same failure would have had a way out: the support file was open to that task by its own text, and a technical
question with an `Edit` option can unfreeze a red test there (L4-IMP-014, L4-IMP-015).

Verified at 0.4.58: `run_e2e` is called by a fix chore (`_e2e_chore_run`, L4-IMP-090), by the repair step's base proof
(`_e2e_base_proof`, L4-IMP-091), by step 3 (`verifier/gates.py` `run_e2e_gate`) and by step 5 (`verifier/generate.py`).
No red or green step calls it.

## What Changes

- A task's *browser tests* are the test functions that pytest would collect from the Python files under the e2e test
  directory (`e2e_test_dir(gates.e2e, worktree)`; `python_files` `test_*.py` or `*_test.py`): module-level `def test*`
  that is not a fixture, and `test*` methods of `Test*` classes without an `__init__`. A fixture or helper named `test*`
  is no test. They are the task's when its red step added them or changed their own definition (what a test reads, an
  autouse fixture or `pytestmark`, does not count), read from git between the red commit's parent and the red commit.
- When `gates.e2e` is configured and the task has browser tests, its green step runs `gates.build` (when configured) and
  the e2e gate (`run_e2e`, name `e2e-task`) last, after the test gate, the static gates, the test-at-red run and any held
  check, and before the commit. **The check is fail-safe**: the attempt is refused only when a browser test of the task is
  in the report as failed or errored (or the gate timed out, no report is readable, a module of the task did not
  collect, the build failed or the server was not ready). A task test that the report does not show (not collected, a
  module name two files fit, a person's answer removed it, only skipped) does not block: it is a ledger note
  (`e2e.task_tests_unseen`) and a log line, and verification step 3 runs it as before. Report ids are matched by module
  suffix (`test_layout` under an `e2e/pytest.ini`, `e2e.test_layout` otherwise) and by class. The failure text of the
  failing ones goes to the next attempt's prompt, as for the unit gate.
- The task-step run is skipped (no build, no e2e run, a ledger note `e2e.task_run_skipped`) when the e2e gate cannot tell
  the task's tests from the rest of the directory: the e2e command selects with `-m` or `-k`, or the unit gate's report
  holds tests of the e2e directory (`pytest tests -m browser`).
- A task that red finishes as already satisfied (L4-IMP-003) runs its browser tests the same way before its commit.
- A red step that commits a red does not run the e2e gate (design D2: it could not have told the live test from a good
  one, and the run costs a build and a served suite per attempt).
- A server that never gets ready is a failed attempt with the end of its log, as for a fix chore; `gates.e2e` not
  configured means no run (today's behaviour).
- The green prompt names the task's browser tests and says the harness runs them after the step and that one the report
  does not show is run at verification; the red prompt's browser-test paragraph says the step that completes the task
  runs them, and says they are frozen only when `tdd.test_globs` covers the e2e directory.
- The run deadline's cap of a green step is the agent's limit plus three `gates.timeout` only for a green step whose task
  has browser tests that will run (L4-IMP-067 amendment): the test gate, the build and the e2e gate.

Non-goals: selecting tests inside the e2e command (the project's command runs whole, as in every other e2e run of the
harness); judging the e2e tests that are not the task's (there is no e2e baseline at a task step; step 3 judges the
whole gate); browser tests in a language other than Python; a red-step run; a configuration key.

## Capabilities

### New Capabilities

- `e2e-in-task-steps`: L4-IMP-101, the step that completes a task runs that task's own browser tests.

### Modified Capabilities

- L4-IMP-067 (amendment): the cap of a green step's estimate when `gates.e2e` is configured.

## Impact

- `src/l4/implementer/browser_tests.py` (new): the pytest-collectable filter, the report-id matcher, the `-m`/`-k` and
  shared-directory tests. `src/l4/implementer/tdd.py`: a new `task_browser_tests`, a new `_task_e2e_reason` beside `_e2e_chore_reason`
  (sharing `_tree_state`, `_drop_gate_output`, `_log_tail`), `run_green`, `run_red`'s `finish_already_satisfied`,
  `_prompt`; `_drop_gate_output` takes the phase.
- `src/l4/implementer/prompt.py`: `PromptContext.browser_tests`, the green block, the red paragraph.
- `src/l4/deadline.py` (`cap_s`) and `src/l4/implementer/loop.py` (`_check_step`).
- `docs/SPEC.md` (L4-IMP-101, the L4-IMP-067 amendment, SCN-IMP-548..556 and 562..564, change-table row 133), `CHANGELOG.md`.
- Ledger: the runs record `gate.finished` (`build`, `e2e-task`) as every gate run does; three notes are new,
  `e2e.task_tests_unseen`, `e2e.task_run_skipped` and `e2e.task_tests_unread` (a git error while reading the tests).
- Cost: per task with browser tests, one build and one e2e suite run per green attempt that passed every other check.
