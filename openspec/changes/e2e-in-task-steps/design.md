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
  that lie under `e2e_test_dir(wb.cfg.gates.e2e, wb.worktree)`, end in `.py`, are regular files at `after` (no link on
  the way, `linked_component`), and match no `tdd.test_support_globs` glob and are not named `conftest.py` or
  `__init__.py`;
- in each, the names `facts_of` reports as tests (`Facts.test`) at `after` that are absent at `before` or whose `(parts,
  closure)` differ. A file that does not parse at `after` gives none (the unit gate's collection or red's own checks
  speak for it).

For green, `before` is the red commit's parent and `after` the red commit (`red.manifest.red_sha`), so a red that
`resume_red` restores counts the same and nothing of the agent's own record (`tests_added`) is trusted. For the
already-satisfied path, `before` is the step base and `after` None. A support file alone (a helper in `e2e/conftest.py`
with no test function changed) adds no test: the task is then not one whose red touched a browser test. A test the red
step deleted is not run. A file in another language (a `.spec.ts`) adds none: no AST tells its tests apart (Non-Goal).

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

### D4. How the run is judged

`run_e2e(wb, name="e2e-task")` with no `must_contain`: those are exact report ids, and pytest-playwright reports a test
once per browser (`e2e.test_layout::test_width[chromium]`), which the harness cannot know before the run. After the run,
for each `(path, name)` of D1 the report ids `i` with `names_test_id(i, path, name)` are its ids. In this order:

1. a timed-out gate (`gate.timed_out`): its reason;
2. no readable report: `the e2e gate produced no readable report (<gate reason>)`;
3. a collection error of a module that is one of D1's files: `browser tests not collected: <modules>`;
4. a test with no id: `the task's browser tests are not in the e2e report: <path::name, ...>`;
5. a test with an id that failed or errored, or whose every id was skipped:
   `the task's browser tests do not pass: <ids, ...>`, and the excerpt `excerpter(wb)(report, <failing ids>)` (the
   retry prompt's text: the `E` lines, the deepest repository frame; redacted).

Lists use `_list` (at most `MAX_LISTED`). Every other test of the e2e report, failing or not, and the gate's exit code
are not judged: a task step has no e2e baseline, and step 3 judges the whole gate as before.

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

- Green: `PromptContext.browser_tests: tuple[str, ...]` (`path::name`, from D1). When not empty, `render_prompt` adds
  after the unfrozen and named blocks: `# Browser tests of this task` and the sentence "After your step the harness
  builds the app, serves it and runs the e2e gate; this task is green only when these browser tests, which its red step
  wrote, pass there. You cannot run them in this sandbox. They are frozen like the other red tests: if one is wrong,
  report status blocked with one technical question whose first option is the exact edit." followed by a data block
  `browser tests of this task` with one `one_line` per test.
- Red: the existing `ctx.e2e_dir` paragraph gains one sentence: "The green step of this task runs them with the app
  served, and they are frozen after this step, so check what each one expects against the spec: a page a test builds
  itself (`page.set_content`) has the browser's default styles, not the app's."

Both are built in `prompt.py`, not in a template, so no template version changes.

### D8. Cost and the run deadline

Per task with browser tests: at most one `gates.build` run and one e2e gate run per green attempt, and only for an
attempt that passed every other check; none for any other task. Each run is a gate bounded by `gates.timeout`. A green
step of such a task can therefore take the agent's limit plus three gate runs (the test gate, the build, the e2e gate),
where `deadline.cap_s` allows one: `cap_s(phase, gates_timeout_s, agent_timeout_s=..., *, e2e: bool = False)` returns
the agent's limit plus `3 * gates_timeout_s` for `green` when `e2e` is true (every other phase, and `e2e` false, as
today); `deadline.check` gains the keyword `e2e: bool = False` and passes it to `cap_s`; `_check_step` in
`src/l4/implementer/loop.py` passes `e2e=e2e_configured(wb.cfg)` (it is called with the phase, so only a green check
uses it). The estimate stays the longest measured step of the phase (L4-IMP-067), so only a run whose green steps are long
sees a larger estimate; reading git in `_check_step` to tell tasks apart is not worth it.

### D9. What the next attempt can do

The failure text (D4 5) is the previous failure of the next attempt, which may change product code, a support file
the task's own text opened (L4-IMP-014: new statements only, L4-IMP-016), or report blocked with a technical question
that names the edit of the frozen test; a person's answer that accepts it unfreezes the file for the task (L4-IMP-015),
and a delegate's accept does so for a test file where `delegate.unfreeze` allows it (L4-DLG-014). When every attempt
fails, the halt reason ends with `last failure: the task's browser tests do not pass: ...`.

## Risks / Trade-offs

- The e2e suite runs whole: on a large suite each green attempt of such a task pays for it. Bounded by D3 and D8.
- Other e2e tests that the green step breaks are found at step 3, as before (no baseline here).
- A flaky browser test can fail a green attempt; the next attempt is a new run, and `max_task_attempts` bounds it. Step
  3's repeat of a flaky gate (L4-VER-076) is not used here.
- A browser test whose red step changed only its support file (no test function) is not run until step 3.
