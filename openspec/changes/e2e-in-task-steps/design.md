## Context

Read at 0.4.58 (f0bc8a3c):

- `run_green` (`src/l4/implementer/tdd.py` ~2143): the agent step (`step_or_replay`), `_check_opened`, the put-back of
  the frozen manifest and `freeze_test_paths(keep=unfreeze.paths, phase="green")`, `run_setup`, `arm_replay_guard`,
  `mark = wb.mark_tested()`, the test gate, `green_failures`; with no failure `worse_static_gates` (L4-IMP-096, the near
  pass's `static`), `_undiscriminating` (the test-at-red run, which may hold), `restore_replay`, `stop_on_unsafe`,
  `outside_links_reason`; on a reason the near pass (L4-IMP-100) and `wb.discard_changes()`; else the tick, `task.done`,
  the commit and `wb.keep_tested(mark, gate.report, sha)` (L4-IMP-088).
- `run_red` (~1578): the red verdict is built from the unit gate's report only (`new_test_ids(base_report, report)`);
  `finish_already_satisfied` (~1824) commits a task whose every cited criterion is pre-satisfied, with no green step.
- The fix chore's e2e run (L4-IMP-090): `_e2e_chore_reason` (~2822) takes `_tree_state` before, runs `_e2e_chore_run`
  (`run_build_only`, then `run_e2e(wb, name="e2e-chore", must_contain=ids)`, `ServerNotReady` caught as a failed attempt
  with `_log_tail`), and in a `finally` `_drop_gate_output(wb, task, base, before, keep)`, which removes a planted link
  first (`wb.refused_write`), puts back what the runs wrote and runs `freeze_test_paths(..., phase="single")` again.
- `run_e2e` (`src/l4/gates/e2e.py`): runs the project's whole e2e command under the launcher; `must_contain` makes the
  gate fail when the report lacks one of those exact ids; it raises `ServerNotReady` (an `L4Exit(INTERNAL_ERROR)`) and,
  for a refused configuration, `L4Exit(USAGE_ERROR)`. `e2e_configured(cfg)` needs `command`, `serve.command` and
  `serve.ready_url`; the verifier's `e2e_gate_configured` needs only `command` and lets `run_e2e` refuse the rest.
- `e2e_test_dir(gate, tree)` gives the directory the e2e command runs from (default `e2e`); the red prompt already
  tells the agent to put browser tests there (`prompt.py`, `ctx.e2e_dir`).
- `tamper.facts_of(source)` gives, per test name of a Python file, its `parts` and `closure`; `tamper.names_test_id(id,
  path, name)` matches a report id to a module and function, a parametrised `name[...]` included.
- `deadline.cap_s(phase, gates_timeout_s)`: the agent's time limit plus one `gates.timeout` for red, green and single.

## Goals / Non-Goals

**Goals:** a browser test that a task's red step wrote runs, with the app served, before that task is done; a failure
of it reaches the next attempt's prompt with its message; no task that did not touch a browser test pays for an e2e run.

**Non-Goals:** a red-step run of a red commit; running a subset of the e2e suite; judging e2e tests that are not the
task's; browser tests in another language; a configuration key.

## Decisions

### D1. Which tests are the task's

`task_browser_tests(wb, before: str, after: str | None) -> tuple[tuple[str, str], ...]`, sorted `(path, name)` pairs:

- the changed paths between `before` and `after` (`after` None: the work tree; `git diff --name-only --no-renames`)
  that lie under `e2e_test_dir(wb.cfg.gates.e2e, wb.worktree)`, match pytest's default `python_files` (`test_*.py`,
  `*_test.py`, which also leaves out `conftest.py` and `__init__.py`), match no `tdd.test_support_globs` glob, and are
  regular files at `after` (no link on the way, `linked_component`);
- in each, the names that pytest would collect (`browser_tests.collectable_tests`): a module-level `def test*` /
  `async def test*` without a `@pytest.fixture` (or `pytest_asyncio.fixture`) decorator, and `Class.test*` for a
  module-level class named `Test*` with no `__init__` of its own or of an in-file base; and that `tamper.facts_of` knows
  as tests (`Facts.test`) at `after`, whose own definition (`Facts.parts`) is absent at `before` or differs. What a test
  reads in its file (`Facts.closure`: an autouse fixture, `pytestmark`, a constant) does not make it the task's: a new
  autouse fixture would otherwise make every test of an existing file the task's, and each of them would have to be in the
  report. A file that does not parse at `after` gives none (the unit gate's collection or red's own checks speak for it).
- A git error (`GitError`) while reading is a warning and a ledger note (`e2e.task_tests_unread`) and gives none: the
  step goes on and nothing runs for it.

For green, `before` is the red commit's parent and `after` the red commit (`red.manifest.red_sha`), so a red that
`resume_red` restores counts the same and nothing of the agent's own record (`tests_added`) is trusted. For the
already-satisfied path, `before` is the step base and `after` None. A support file alone (a helper in `e2e/conftest.py`
with no test function changed) adds no test: the task is then not one whose red touched a browser test. A test the red
step deleted is not run. A file in another language (a `.spec.ts`) adds none: no AST tells its tests apart (Non-Goal).
`tamper.names_test_id` and `facts_of` are not changed: the tamper guard protects a test by suffix and by name, and what
is decided here is only whether a report names a test.

### D2. Red does not run the e2e gate, the already-satisfied finish does

Considered: run the e2e gate in every red step that adds browser tests and require them to fail "properly". Rejected:

1. The live test failed before and after the implementation (its page was the test's own), so a red run would have
   recorded it as a good red. Only a run after the code tells a wrong expectation from missing code.
2. A browser test's honest red failure is usually an error raised in the browser library (a locator that times out
   because the button is not built yet), not an assertion, so red could not ask for an assertion as it does for unit
   tests (the docstring of `repairs._usage_error` makes the same point). All a red run could refuse is a missing test,
   a collection error or a usage error (`TypeError`, `must be a string`), the 0.4.43 case.
3. Each red attempt would pay a build and a served suite, and red attempts fail more often than green ones.

A usage error that slips through red is now met in green, where the agent can ask for the test to be unfrozen (D9),
instead of at verification, where nothing can be unfrozen.

The already-satisfied finish (`finish_already_satisfied`) is the one red step that completes a task with no green
after it, and the agent that wrote the test may still change it there. It runs the task's browser tests (D1 with the
step base and the work tree) the same way as green, after the restored test run and its `tampered(...)` check and
before `outside_links_reason`; a failure fails the red attempt (`RedOutcome("failed", reason, excerpt=...)`).

### D3. Where the run sits in green

Last before the commit: in `run_green`, after the hold decision of the test-at-red run (`held` handled) and before
`reason = reason or stuck or restore_replay(wb, "before the green commit")`, only when no reason and no `stuck` is set:

    if not reason and not stuck and browser:
        reason, excerpt = _task_e2e_reason(wb, task, base, browser, keep=unfreeze.paths)
        stuck = stuck or restore_replay(wb, "e2e run")

So an attempt that fails its test gate, its static gates or the test-at-red run pays no e2e run; a held step pays none
until a person's accept replays it, and the replay runs it like every other check. A near pass (L4-IMP-100) stops at the
static gates, before the e2e run, and is carried as today; an attempt whose e2e run fails has `static == ""`, so it is no
near pass (`alone` is false). The `mark = wb.mark_tested()` taken before the test gate stays valid: D6 puts the tree
back as it was tested.

### D4. How the run is judged (fail-safe)

`run_e2e(wb, name="e2e-task")` with no `must_contain`: those are exact report ids, and pytest-playwright reports a test
once per browser (`e2e.test_layout::test_width[chromium]`), which the harness cannot know before the run. The attempt is
refused only for what the run itself shows. In this order:

1. a timed-out gate (`gate.timed_out`): its reason;
2. no readable report: `the e2e gate produced no readable report (<gate reason>)`;
3. a collection error of a module that resolves (below) to one of the task's files: `browser tests not collected:
   <modules>`; a module name that two files fit resolves to none and is not an error here;
4. a task test with an id that failed or errored: `the task's browser tests do not pass: <ids, ...>`, and the excerpt
   `excerpter(wb)(report, <failing ids>)` (the retry prompt's text: the `E` lines, the deepest repository frame; redacted).

A task test that the report does not show does **not** block green: it has no id (not collected, deselected, a fixture
or helper that slipped through, an id that cannot be mapped, a test a person's answer removed, a class pytest skipped),
or every id was skipped. The step records `e2e.task_tests_unseen{task, phase, tests, ambiguous}` and logs that they were
not seen and that verification step 3 runs them as before. A check that refused them would halt a task for good on a test
no step can make appear; the only cost of letting them pass is what happened before this change, a failure first seen at
step 3. The same goes for a collection error of a module the harness cannot map: unseen, not blocking. A collection error
of a module that does map to a task file stays refusing: that module's tests errored.

Matching a report id to a task test (`browser_tests.match_task_tests`): the module of an id is resolved with
`evidence.testsran.file_of_test(id, tree, tree)` over every Python file of the tree (tracked, or new and not ignored): the
exact path wins, else the one file whose path ends with the classname's module path, because pytest writes the classname
from its rootdir (`test_layout`, not `e2e.test_layout`, under an `e2e/pytest.ini`). Two files that fit give no answer: the
id is left out, listed in `ambiguous` and logged, never guessed. The class between module and function (the trailing
capitalised parts of the classname) must be the test's own class, so `TestA::test_x` is not `TestB.test_x` and a
module-level function has none; the function name ends at a `[param]` suffix.

Lists use `_list` (at most `MAX_LISTED`). Every other test of the e2e report, failing or not, and the gate's exit code
are not judged: a task step has no e2e baseline, and step 3 judges the whole gate.

### D5. Not configured, not ready, refused

- `e2e_configured(wb.cfg)` false (no `command`, `serve.command` or `serve.ready_url`): `task_browser_tests` is not
  computed and nothing runs; the task is judged as today. A half-configured gate (a command only) is refused at step 3
  with exit 2 as before.
- `gates.build` fails: `gates.build failed before the e2e gate: <detail>`, no e2e run.
- `ServerNotReady`: the attempt fails with `the e2e server was not ready (see <log name>)` and `_log_tail` of the log
  (2,000 characters, redacted) as the excerpt; it is counted like any failed attempt. The agent's code may be what keeps
  the server from starting, so the next attempt needs the log; a runner that cannot serve the app at all ends the task
  on `max_task_attempts` with that reason as the last failure, which names the log.
- Any other `L4Exit` of `run_e2e` (a refused format, no `reports`) is not caught: the run stops with that exit, as for
  a fix chore.

### D6. The tree after the run

`_task_e2e_reason` is `_e2e_chore_reason`'s shape: `before = _tree_state(wb)`; try the build and the run; finally
`_drop_gate_output(wb, task, base, before, keep, freeze_phase=...)`. `_drop_gate_output` gains a keyword
`freeze_phase: str | None = "single"` passed to `freeze_test_paths` as its `phase`; None skips that freeze. The fix chore
keeps `"single"`, green passes `"green"` (with `keep=unfreeze.paths`), and the already-satisfied finish passes None: in
red the test files are the step's own work, and a freeze back to the base would delete them. In red the run is also
followed by `tampered("e2e run")` (the `ProductionGuard` of the step: test code a gate ran may not move production
files). A link a gate planted is removed and recorded as today (it stops the unit through `stop_on_unsafe`). The tree
that is committed is the tree the test gate tested, so `keep_tested` stays right.

### D7. The prompts

- Green: `PromptContext.browser_tests: tuple[str, ...]` (`path::name`, from D1; empty when the run is skipped, D10).
  When not empty, `render_prompt` adds after the unfrozen and named blocks: `# Browser tests of this task` and the
  sentence "After your step the harness builds the app, serves it and runs the e2e gate; this task is not green while
  one of these browser tests, which its red step wrote, fails there (one the report does not show is not judged here: it
  is run at verification). You cannot run them in this sandbox. They are frozen like the other red tests: if one is
  wrong, report status blocked with one technical question whose first option is the exact edit." followed by a data
  block `browser tests of this task` with one `one_line` per test.
- Red: the existing `ctx.e2e_dir` paragraph gains one sentence: "The step that completes this task runs them with the app
  served[ and they are frozen after this step], so check what each one expects against the spec: a page a test builds
  itself (`page.set_content`) has the browser's default styles, not the app's." (it is the green step, or this very step
  for an already-satisfied finish, which is why it is not named "green"). The bracketed clause is there only when
  `tdd.test_globs` covers the e2e directory (`PromptContext.e2e_frozen`, from a probe path `<e2e dir>/test_probe.py`);
  otherwise the browser tests are not frozen and the prompt does not say so.

Both are built in `prompt.py`, not in a template, so no template version changes.

### D8. Cost and the run deadline

Per task with browser tests: at most one `gates.build` run and one e2e gate run per green attempt, and only for an
attempt that passed every other check; none for any other task. Each run is a gate bounded by `gates.timeout`. A green
step of such a task can therefore take the agent's limit plus three gate runs (the test gate, the build, the e2e gate),
where `deadline.cap_s` allows one: `cap_s(phase, gates_timeout_s, agent_timeout_s=..., *, e2e: bool = False)` returns
the agent's limit plus `3 * gates_timeout_s` for `green` when `e2e` is true (every other phase, and `e2e` false, as
today); `deadline.check` gains the keyword `e2e: bool = False` and passes it to `cap_s`. `loop._check_step` passes
`e2e=True` only for a green step whose task will run the e2e gate (`tdd.task_runs_e2e(wb, red_sha, unit_ids)`:
`gates.e2e` configured, browser tests in the red commit, and the run not skipped, D10), and only when a deadline is armed
(the git read is not paid otherwise). The red commit is `red.manifest.red_sha` in the green branch of `_run_task`, and
for the first check of a task resumed at green (made before `resume_red`) the commit of `_last_checkpoint`. The shared
directory test of D10 reads the unit gate's report of the step, which a check before the step does not have, so it uses
the baseline and red ids; a skip that only the step's own report shows leaves the cap a little high, which can only
defer a step. The estimate stays the longest measured step of the phase (L4-IMP-067), so only a run whose green steps
are long sees a larger estimate.

### D9. What the next attempt can do

The failure text (D4 5) is the previous failure of the next attempt, which may change product code, a support file
the task's own text opened (L4-IMP-014: new statements only, L4-IMP-016), or report blocked with a technical question
that names the edit of the frozen test; a person's answer that accepts it unfreezes the file for the task (L4-IMP-015),
and a delegate's accept does so for a test file where `delegate.unfreeze` allows it (L4-DLG-014). When every attempt
fails, the halt reason ends with `last failure: the task's browser tests do not pass: ...`.

### D10. When the run is skipped

`_e2e_skip_reason(wb, unit_ids)`: the e2e command selects tests with `-m` or `-k` after its `pytest` word
(`browser_tests.selecting_option`; its report holds only part of the directory), or the ids of the unit gate's report
(`unit_ids`) resolve to files under `e2e_test_dir` (`browser_tests.shared_with_unit_gate`; `pytest tests -m browser`, where
`e2e_test_dir` is `tests` and every unit test would be a "browser test"). The run is then skipped: no build, no e2e run,
`e2e.task_run_skipped{task, phase, reason, tests}` and a warning, and verification step 3 runs the browser tests. It is
decided in `run_green` before the step from the baseline and red ids (`red.base_report`, `red.new_ids`), so the green
prompt lists no browser tests and promises no run, and again after the step's test gate from its own report. The
already-satisfied finish decides from the red gate's report.

## Risks / Trade-offs

- The e2e suite runs whole: on a large suite each green attempt of such a task pays for it. Bounded by D3 and D8.
- Other e2e tests that the green step breaks are found at step 3, as before (no baseline here).
- A flaky browser test can fail a green attempt; the next attempt is a new run, and `max_task_attempts` bounds it. Step
  3's repeat of a flaky gate (L4-VER-076) is not used here.
- A browser test whose red step changed only its support file (no test function) is not run until step 3.
- A browser test the report does not show passes the step unseen (D4): a never-collected test is found at step 3, as before this change.
