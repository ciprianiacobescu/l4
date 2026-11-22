## Context

Read at 0.4.59 (62188257). Each fact below was read in the code for this design.

- `run_single(wb, task, findings, *, attempt, previous_failure, kind, retake)` (`src/l4/implementer/tdd.py:3552`),
  for `kind="tests"`:
  - `own_tests = proved_test_files(wb)` (`:3587`): every file of a `task.red_ok.frozen` of the family (`:2351-2356`).
  - after the agent step, `review_test_chore(wb, base, own_tests)` (`:3608`, defined at `:2630`): a new file of
    `tdd.test_globs` is kept, a file of `own_tests` is kept when `appended_only` holds, any other change of a test file
    is put back (`guard.test_tamper`), a support file is put back (`guard.violation`), and a changed file that is no test
    file fails the attempt (`a test chore may add tests only: it changed non-test files: ...`).
  - the test gate (`:3637`), `green_failures(base_report, [], gate)` (`:3639`), the fix chore's e2e duty (`:3641-3643`,
    kind `fix` only: `e2e_scope` is None for `tests`, `:3590`).
  - `added` = the new ids of the unit gate's report that passed (`:3644-3648`). None: `_already_done` for a retake, else
    `reason = "no tests added"` (`:3649-3653`).
  - `decision_calling_code_wrong` (attempt 1, `:3654-3662`), `over_cap_text({i: gate.report.tests[i] for i in added},
    ...)` (`:3663-3668`), `worse_static_gates` and `ci_steps_reason` (`:3669`).
  - a task title that cites a criterion (`CRITERION_IN_TITLE`) runs `_discriminating_tests(wb, added, task)`
    (`:3671-3688`, defined at `:2700`): `discriminate_extra` makes a zero-value run and a base run, both of the unit gate;
    every test inconclusive gives a `HeldCheck(task.key, "green", "tests", (), tests, reason, made)`; an accepted
    override (`accepted_overrides(wb, task.key, "tests")`) lets the replayed step through.
  - `task.tests_added{task, files: kept, tests: added, discriminating?}` before the commit (`:3691-3693`).
- L4-IMP-101 (green): `task_browser_tests(wb, before, after)` (`:2848`) gives `(path, name)` of the collectable tests of
  the Python files under `e2e_test_dir(gates.e2e)` that were added or whose own definition changed between two trees
  (`after=None`: the work tree). `_runnable_browser_tests(wb, task, phase, tests, unit_ids)` (`:3038`) skips the run for
  a selecting e2e command or a directory the unit gate also runs, with `e2e.task_run_skipped{task, phase, reason,
  tests}`. `_task_e2e_reason(wb, task, base, tests, keep, freeze_phase, phase)` (`:3064`) takes `_tree_state`, runs
  `_task_e2e_run` (`:3088`: `run_build_only`, `run_e2e(wb, name="e2e-task")`, `ServerNotReady` as a failed attempt, the
  fail-safe judging) and in a `finally` `_drop_gate_output(..., freeze_phase=...)` (`:2907`). `_task_e2e_run` returns
  `(reason, excerpt)` only; the ids that passed are computed and dropped.
- `_drop_gate_output` with `freeze_phase="single"` (its default) runs `freeze_test_paths(..., phase="single")`, which
  puts back changed test files. A test chore's new test files are changed test files.
- The prompt (`src/l4/implementer/prompt.py:299`): role `single` with `ctx.adds_tests` loads `single_tests.md` (`:304`);
  the browser-test block is green only (`:339`) and the e2e paragraph red only (`:403`).
- `_with_note` (`src/l4/implementer/loop.py:179`) adds `chore_question_note(chore_unit)` (`:137`) to every technical
  question of a chore (`:196-198`); `_raise_blocked` is called with `chore_unit=wb.ref.id` for every chore kind
  (`:679-680`). The delegate finds a chore's question by `question.raised.chore` and, for an older raise, by the note's
  first sentence (`delegate/run.py:122`, `:1167-1174`).
- The feedback mapping: `fixunit._feedback_candidate` (`src/l4/verifier/fixunit.py:338-348`) and `plan_fix_unit`
  (`:430-437`) make a `tests` item, and a not-addressed finding of one (`verifier/feedback.py` `not_addressed_findings`,
  `retake=True`), a test chore; `specs/openspec.py:337-347` writes `test_chores` and `retakes`; `specs/fixmark.py:92-107`
  `chore_kind` reads them.

## Goals / Non-Goals

**Goals:** a browser test that a test chore writes runs before the chore is done and counts as an added test; a test
chore that adds nothing says what each gate saw; the discrimination runs and the cap read each test from the report that
holds it; a test chore's prompt and questions say what it may change.

**Non-Goals:** editing the test files an earlier take added (D9); browser tests in another language; a run-deadline cap
for a chore's e2e run (the fix chore's e2e run of L4-IMP-090 has none either); the fix chore, the repair chore, red and
green.

## Decisions

### D1. Which tests of a test chore are browser tests

`browser = [t for t in task_browser_tests(wb, base, None) if t[0] in review.kept]`, computed after `review_test_chore`
and only when `e2e_configured(wb.cfg)`. `base` is the chore's step base (`wb.head()` at `:3580`) and `None` the work
tree, as for the already-satisfied finish of L4-IMP-101. The restriction to `review.kept` is a guard against a
difference between the two readings: a file the review put back is at its base content and has no changed test, so
the two sets are the same in practice. A browser test in a file of `own_tests` that the step appended to counts (it is
kept). A browser test in a file that `tdd.test_globs` does not match never gets here: the review already failed the
attempt as a non-test change (D8 says so in the prompt). `task_browser_tests` and its git-error note
(`e2e.task_tests_unread`) are not changed.

### D2. When and where the e2e run happens

In `run_single`, for `adds_tests`, right after `green_failures` and before `added` is computed, as the fix chore's e2e
duty sits (L4-IMP-090):

    if adds_tests and not reason and gate.report is not None and browser:
        browser = _runnable_browser_tests(wb, task, "single", tuple(browser), gate.report.tests)
        if browser:
            chore_e2e = _chore_browser_tests(wb, task, base, browser)
            reason, excerpt = chore_e2e.reason, chore_e2e.excerpt
            stuck = stuck or restore_replay(wb, "e2e run")

So an attempt whose test gate shows a new failure pays no e2e run. The skip decision reads the step's own unit-gate
report (`gate.report.tests`), the one L4-IMP-101 reads after a green step's test gate. The static gates run after the
e2e run, as for the fix chore: the "no tests added" decision needs the e2e count, and the order is the one the fix
chore already has.

### D3. How the run is judged, and what counts

`_chore_browser_tests(wb, task, base, tests) -> ChoreE2e(reason, excerpt, passed: dict[str, TestCase], unseen:
tuple[str, ...], note: str)` takes `_tree_state`, runs the e2e part and, in a `finally`, `_drop_gate_output(wb, task,
base, before, (), freeze_phase=None)` (D4). The e2e part is `_task_e2e_run` with the gate name `e2e-test-chore` and the
phase `single`, changed to return a `TaskE2e(reason, excerpt, passed, unseen, report)` instead of a pair;
`_task_e2e_reason` keeps its `(reason, excerpt)` return for green and the already-satisfied finish, so L4-IMP-101 is
unchanged.

The refusals are those of L4-IMP-101 D4, in its order: a failed build, a server that is not ready (its log tail as the
excerpt), a timed-out gate, no readable report, a collection error of a module that maps to a file of the step, a
browser test of the step with an id that failed or errored (`the task's browser tests do not pass: <ids>` and the
excerpt). A test chore's new tests must pass (the unit-gate rule is "no new failure", `green_failures`), so a failing
browser test of the step refusing the attempt is the same rule for the other gate.

What counts is the other direction from green: a browser test of the step is an added test when the report shows one of
its ids `passed` and none failed or errored (the ids `match_task_tests` maps to it, every browser parametrisation such
as `[chromium]` counted). A test the report does not show, or shows only skipped, is not counted: it is `unseen`, the
ledger note `e2e.task_tests_unseen{task, phase: "single", tests, ambiguous}` and a log line, as in green, and it does
not refuse the attempt by itself. Counting it would let a chore pass with a test that no gate ran; refusing on it would
halt a chore on a test no step can make appear. So an unseen test neither counts nor blocks; when nothing else counts,
the attempt fails with `no tests added` and names it (D5).

The other tests of the e2e report and the gate's exit code are not judged, as in green: a chore has no e2e baseline, and
verification step 3 judges the whole gate.

### D4. The tree after the run

`freeze_phase=None`: the step's own new test files are the chore's work, and the freeze of a fix chore
(`freeze_test_paths(..., phase="single")`) would put them back. The review has already put back what the chore may not
change. Everything else of `_drop_gate_output` stays: a link a gate planted is removed and recorded (it stops the unit
through `stop_on_unsafe`), a path new since `before` goes back to the base, a path the step had edited and a gate changed
gets the step's content back. A production file that a browser test's code changed is new since `before` (the step did
not change it: the review would have failed the attempt) and goes back to the base. The tree that is committed is the
tree the unit gate tested, so `keep_tested(mark, gate.report, sha)` stays right.

### D5. The text of `no tests added`

`_no_tests_text(wb, kept, e2e)` gives `no tests added: ` and one clause per gate, joined by `; `:

- the test gate, always: `the test gate (<gates.test.command, one line, cut at 120>) reports no new passing test`;
- the e2e gate, one of:
  - `gates.e2e` not configured and a kept file lies under the default e2e directory (`e2e/`): `the e2e gate is not
    configured, so a browser test does not count`; not configured otherwise: nothing;
  - configured and the step kept no browser test: `this step kept no browser test under <dir>/, so the e2e gate did not
    run`;
  - configured and the run skipped: `the e2e gate did not run: <the skip reason of _e2e_skip_reason>`;
  - configured and run: `the e2e gate (<command>) reports none of this step's browser tests as passed: <path::name of
    each unseen test, _list>`;
- and, when `review.kept` is empty: `this step kept no new test file and appended no test` first.

The reason starts with `no tests added` as before. No code compares the whole text (the halt line of `max_task_attempts`
embeds it); the readers that do are tests (`tests/unit/implementer/test_single_phase.py`), which the implementer
updates. The red step's own `no tests added`
(`tdd.py:560`) is not changed. The reason is the next attempt's previous failure, so the clauses are what the next prompt
shows; no excerpt is added, since no test failed.

### D6. Two lists, one record

`added_unit` (the unit-gate ids, as today) and `added_e2e` (the passed browser ids, sorted) are kept apart, and `added =
added_unit + added_e2e` is what the `no tests added`, `_already_done` (a retake) and `decision_calling_code_wrong`
checks read. The cap (L4-VER-052) reads each id from its own report:
`over_cap_text({**{i: gate.report.tests[i] for i in added_unit}, **chore_e2e.passed}, ...)`. `task.tests_added` keeps
`tests: added` and gains `e2e_tests: added_e2e` when not empty, so a reader can tell which ids are of the e2e report;
`files` is `review.kept` as before, so `check_test_paths` (`verifier/integrity.py:607`) allows the browser test file of
the commit as it allows any kept file.

### D7. The discrimination runs (L4-IMP-110)

The runs of `discriminate_extra` use the unit gate (the zero-value run and the base run), so an id of the e2e report is
never in their reports and would be inconclusive. Only `added_unit` goes to `_discriminating_tests`. When the task cites
a criterion and `added_unit` is empty while `added_e2e` is not, no run is made and the chore is held as an inconclusive
check is today (L4-IMP-063): `HeldCheck(task.key, "green", "tests", (), tuple(added_e2e), BROWSER_ONLY, ())` with
`BROWSER_ONLY = "the discrimination runs use the unit gate, which does not run browser tests: these browser tests passed
in the e2e gate, and the harness cannot check that they fail when the code is wrong"`. Its question says that no run was
made (`Runs:` names none). An accept replays the step as for any held check, and the held tests are recorded
`discriminating` as an accepted hold's are today. When `added_unit` is not empty, the unit ids are judged as today and
the browser ids go along with the outcome: accepted when one unit id is accepted (today a chore passes when one of its
tests is accepted), held on the unit ids when every one of them is inconclusive, and failed when they are rejected.

Considered: let a browser-only chore pass with no hold, since a test chore cannot change production code and the judge
reviews the item. Rejected for this change: it would accept, with no person, tests whose look at the answer nothing
checked, which is what the hold of L4-IMP-063 exists to prevent. The question now says why it was raised.

### D8. The prompts and the question note (L4-IMP-111)

Built in `prompt.py`, not in `single_tests.md`, so no template version moves:

- `PromptContext.e2e_dir` and `e2e_frozen` are already filled for every role (`tdd.py` `_prompt`). For role `single`
  with `adds_tests` and `e2e_dir`, `render_prompt` adds after the phase text: `# Browser tests` and "A browser test you
  add as a Python test under `<dir>/` (for example `<dir>/test_<name>.py`) counts as an added test: after your step the
  harness builds the app, serves it and runs the e2e gate, and a browser test of this step must pass there. You cannot
  run it in this sandbox." and, when not `e2e_frozen`, "This project's test globs do not cover `<dir>/`, so a file there
  is not a test file for this task: changing one fails the attempt."
- `PromptContext.retake_tests: bool`, set for role `single` when `adds_tests` and `retake`: `# This item was taken
  before` and "A verifier judged that an earlier take of this feedback item did not do what it asks. The test files that
  take added are existing test files now: an edit of one is put back. Add what the item still asks for as new tests, with
  new names, in a new test file, and say in notes_for_verifier which earlier tests they complete."
- `chore_question_note(unit, kind="fix")`: for `kind == "tests"` the note keeps its first sentence (`Harness note: this
  is a fix task.`, which the delegate's fallback reads) and then says "It adds tests: a new test file, and new tests
  appended to a test file a red step of this unit wrote, are kept; an edit of any other existing test file, or of a
  test-support file, is put back whatever the answer says. A missing check can go into a new test file. Otherwise a
  person must commit the change on the unit branch themselves, then answer this question (`<answer command>`)." The
  fix chore's note is unchanged. `_with_note` gains `chore_kind: str = "fix"`, and `_raise_blocked` passes
  `chore_kind(wb.ref.path, task.title) or "fix"`.

### D9. Considered and not proposed: a retake may edit its earlier take's test files

The consumer's case would have been met at once if the fix unit's test chore could edit the browser test file that the
earlier take added. That file carries no red proof: it was written by a test chore, recorded in that chore's
`task.tests_added.files`, and the judge has just found it short of the item. A rule could let a test chore that retakes a
`tests` item change, add and remove tests in the files that an earlier take of the same item added, when each file's blob
at the fix unit's base is the one that take committed (no person changed it since), and record them in its own
`task.tests_added.files`, which `check_test_paths` reads.

Not proposed in this change, because it loosens the tamper guard for a test that may since carry a criterion's proof (a
`verify.extra_proof` tied to the file's content) and that a person may have relied on; and because the case is already
unblocked without it: with D3 a new browser test file with the missing check counts, and D8 tells the agent so. The
cost is a duplicate test. It is an open question for the owner's delegate.

### D10. Fail-safe and upgrade

- Nothing here lets a wrong unit pass: a test chore still cannot change production code; a browser test counts only when
  a gate ran it and it passed; a failing one refuses the attempt; the discrimination hold stays for tests the runs cannot
  reach. No agent gets a person-only action, and no answer can unfreeze more than before (the note only describes the
  existing rule).
- A test chore that kept no browser test, or a project without `gates.e2e`, runs as before; only the text after `no
  tests added` is new.
- Upgrade: a unit in flight with a test chore on 0.4.59 runs its next attempt with the new rules. A held test chore of
  0.4.59 (its held tests are unit ids) replays on 0.4.60: the unit ids go to the discrimination runs as before and the
  accepted override still matches them. A ledger written by 0.4.59 folds as before: the only new keys are
  `task.tests_added.e2e_tests` and the `phase: "single"` value of two existing notes.

### D11. Cost

Per test-chore attempt that kept a browser test and passed its test gate: one `gates.build` run and one e2e suite run,
each bounded by `gates.timeout`. A step of phase `single` keeps its deadline cap of one gate (L4-IMP-067), which may now
be low for such a step; a step that runs over is stopped at the soft deadline as any step is.

## Risks / Trade-offs

- The e2e suite runs whole for each such attempt (the project's command, as every e2e run of the harness).
- A browser test that pytest-playwright reports under an id the matcher cannot map is unseen and not counted; the
  attempt then fails with `no tests added` naming it, which is the right direction (no unrun test is counted).
- A browser-only test chore of a cited criterion still costs a person (or an allowed delegate) one answer.
- The phase-`single` deadline cap does not grow for the e2e run (D11).
