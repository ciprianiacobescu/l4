## Purpose

A test chore that writes a browser test runs it with the app served and counts it as an added test, says what each
gate found when it added none, judges each new test against the report that holds it, and tells its agent and the
person who answers its questions what a test chore may change.

## ADDED Requirements

### Requirement: L4-IMP-108 A test chore counts the browser tests it writes
When `gates.e2e` is configured (`e2e_configured`), a test chore (a `[chore]` task of kind `tests`) SHALL compute the
browser tests of its step: the tests of `task_browser_tests(wb, base, None)` (L4-IMP-101: the tests pytest would
collect from the Python files under `e2e_test_dir(gates.e2e)` that the step added or whose own definition it changed,
between the step base and the work tree) whose file `review_test_chore` kept. When there is one, the attempt's test gate
passed with no new failure and the run is not skipped (`_e2e_skip_reason`, read with the ids of the step's unit-gate
report; a skip is `e2e.task_run_skipped{phase: "single"}`), the chore SHALL run `gates.build` (when it is configured)
and then the e2e gate (`run_e2e`, name `e2e-test-chore`), before it counts its added tests. The attempt SHALL fail, as
in green (L4-IMP-101), on a failed build, a server that is not ready (with the end of its log), a timed-out gate, no
readable report, a collection error of a module that maps to a file of the step, or a browser test of the step with an
id that failed or errored (`the task's browser tests do not pass: <ids>`, with their failure text as the excerpt). A
browser test of the step SHALL count as an added test when the e2e report shows one of its ids `passed` and none failed
or errored; one the report does not show, or shows only skipped, SHALL NOT count and SHALL be recorded as
`e2e.task_tests_unseen{task, phase: "single", tests, ambiguous}`. The tests the chore adds SHALL be the unit gate's new
passing tests and these browser tests together, and the "at least one new test must pass" rule of L4-VER-006 SHALL read
them together. The retake rule (`_already_done`: a chore whose feedback items are all retakes is ticked with nothing
committed) SHALL apply only when the step kept no test file; a retake that kept a test file of which no gate counted a
test SHALL fail with the reason of L4-IMP-109, so a test file no gate counted is never discarded with the task ticked.
What the build and the e2e run write SHALL NOT be committed, a link a gate planted is removed and recorded (L4-SEC-020),
and the step's own new and appended test files SHALL stay (the run's clean-up makes no test-path freeze).
`task.tests_added` SHALL keep `files`, SHALL keep `tests` for the ids of the unit gate's report, and SHALL hold the ids
of the e2e report in `e2e_tests` when there are any. A test chore with no browser test, and a project without
`gates.e2e`, SHALL run as before.

#### Scenario: SCN-IMP-586 (+) A new browser test of a test chore counts
- **Given** a test chore whose step adds `e2e/test_layout.py` with `test_regions`, a unit gate that does not collect
  `e2e/`, and an e2e gate whose report shows `test_layout::test_regions[chromium]` passed
- **When** the chore's attempt runs
- **Then** the e2e gate ran once as `e2e-test-chore` after the test gate, the task is done, its commit holds
  `e2e/test_layout.py`, and `task.tests_added` lists that file, the id under `e2e_tests` and an empty `tests`

#### Scenario: SCN-IMP-587 (−) A failing browser test of a test chore fails the attempt with its text
- **Given** the chore of SCN-IMP-586, and an e2e report that shows `test_layout::test_regions[chromium]` failed with
  `assert 88 < 40`
- **When** the attempt runs
- **Then** it fails with a reason that starts `the task's browser tests do not pass:` and names the id, its excerpt
  holds `assert 88 < 40`, nothing is committed, and the next attempt's prompt holds the excerpt

#### Scenario: SCN-IMP-588 (−) A browser test the report does not show is not counted
- **Given** the chore of SCN-IMP-586, and an e2e report that holds no id of `test_regions`, or holds it only skipped
- **When** the attempt runs
- **Then** the ledger has `e2e.task_tests_unseen` with `phase: "single"` naming `e2e/test_layout.py::test_regions`, and
  the attempt fails with a reason that starts `no tests added:` and names that test

#### Scenario: SCN-IMP-589 (+) A test chore with no browser test runs no e2e gate
- **Given** a test chore whose step adds only `tests/test_discount.py` with a passing test, once with `gates.e2e`
  configured and once without
- **When** the attempt runs
- **Then** neither `gates.build` nor the e2e gate runs, and the task is done as before

#### Scenario: SCN-IMP-590 (−) A server that never gets ready fails the test chore's attempt
- **Given** the chore of SCN-IMP-586, and an e2e server whose log ends with `Error: listen EADDRINUSE`
- **When** the attempt runs
- **Then** it fails with a reason that starts `the e2e server was not ready (see`, its excerpt holds `EADDRINUSE`, and it
  counts as a failed attempt

#### Scenario: SCN-IMP-591 (+) What the e2e run writes is not committed, and the chore's test files stay
- **Given** the chore of SCN-IMP-586, a build that writes `.l4-out/built`, and an e2e run that writes
  `test-results/trace.zip` and rewrites a production file the step did not change
- **When** the attempt passes
- **Then** the commit holds `e2e/test_layout.py` and neither the build output, nor `test-results/trace.zip`, nor the
  rewritten production file

#### Scenario: SCN-IMP-592 (+) A retake that keeps no test file is already done
- **Given** a test chore that retakes a `tests` feedback item, whose step changes no file
- **When** the attempt runs
- **Then** the task is ticked as already done (`L4-TDD: already-done`), as today

#### Scenario: SCN-IMP-600 (−) A retake whose new browser test no gate counted fails, and is not ticked
- **Given** a test chore that retakes a `tests` feedback item, whose step adds `e2e/test_layout.py` with
  `test_regions`, and an e2e report that does not show that test
- **When** the attempt runs
- **Then** it fails with a reason that starts `no tests added:` and names `e2e/test_layout.py::test_regions`, the task
  is not ticked and no `task.done{tdd: "already-done"}` is recorded

### Requirement: L4-IMP-109 A test chore that adds no test says what each gate found
A test chore's attempt that adds no test SHALL fail with a reason that starts `no tests added: ` and names each gate and
what it found, joined by `; `: `this step kept no new test file and appended no test` first when the review kept no
file; then `the test gate (<gates.test.command>) reports no new passing test`; then, for the e2e gate, `the e2e gate is
not configured, so a browser test does not count` when `gates.e2e` is not configured and a kept file lies under `e2e/`,
`this step kept no browser test under <dir>/, so the e2e gate did not run` when it is configured and the step kept none,
`the e2e gate did not run: <skip reason>` when the run was skipped, and `the e2e gate (<command>) reports none of this
step's browser tests as passed: <path::name, ...>` when it ran. A command SHALL be shown on one line and cut at 120
characters, and a list SHALL be cut as every list of a reason is. The red step's own `no tests added` SHALL NOT change.

#### Scenario: SCN-IMP-593 (−) The reason names each gate and what it found
- **Given** a test chore whose step adds only `e2e/test_layout.py::test_regions`, in four projects: one without
  `gates.e2e`; one with `gates.e2e` whose step kept `tests/test_a.py` with no new test instead; one whose e2e command is
  `pytest e2e -m browser`; and one whose e2e report does not show the test
- **When** the attempt runs and adds no test
- **Then** each reason starts `no tests added: the test gate (` and goes on, in order, with `the e2e gate is not
  configured, so a browser test does not count`; `this step kept no browser test under e2e/, so the e2e gate did not
  run`; `the e2e gate did not run: the e2e command selects tests with`; and `the e2e gate (` followed by `reports none
  of this step's browser tests as passed: e2e/test_layout.py::test_regions`

### Requirement: L4-IMP-110 A test chore's new tests are checked against the report that holds them
The per-test cap of a test chore (L4-VER-052) SHALL read each added test from the report that holds it: a unit-gate id
from the unit gate's report and a browser id from the e2e report. The discrimination runs of a test chore whose task
cites a criterion (`discriminate_extra`, L4-VER-009) SHALL get the added unit-gate tests only. When the task cites a
criterion and every added test is a browser test, no discrimination run SHALL be made and the chore SHALL be held with a
harness question (L4-IMP-063, check `tests`) whose reason says that the discrimination runs use the unit gate, which does
not run browser tests, that these browser tests passed in the e2e gate, and that the harness cannot check that they fail
when the code is wrong; the question names the tests and no run. An accepted answer SHALL let the replayed step through
and record the held tests as `discriminating`, as for any held test chore. When there are added unit-gate tests, they
SHALL be judged as today and the browser tests SHALL go along with that outcome.

#### Scenario: SCN-IMP-594 (+) The discrimination runs get the unit tests only
- **Given** a test chore whose task cites `C-1a2b3c4d`, whose step adds `tests/test_discount.py::test_code` (it fails by
  assertion in the zero-value run) and the browser test of SCN-IMP-586
- **When** the attempt runs
- **Then** `discriminate_extra` is asked about `tests/test_discount.py::test_code` only, the task is done, and
  `task.tests_added.discriminating` holds that id

#### Scenario: SCN-IMP-595 (−) A test chore of a cited criterion with only browser tests is held, and says why
- **Given** a test chore whose task cites `C-1a2b3c4d` and whose only added test is the passing browser test of
  SCN-IMP-586
- **When** the attempt runs
- **Then** no zero-value or base run is made, the task is held with a harness question of check `tests` that names
  `test_layout::test_regions[chromium]`, says `the discrimination runs use the unit gate, which does not run browser
  tests` and names no run, and after an accept the replayed step is done with that id under `discriminating`

#### Scenario: SCN-IMP-596 (−) The cap counts a browser test's criteria
- **Given** `verifier.max_criteria_per_test: 2` and a test chore whose only added test is a browser test whose id names
  three criterion ids of the unit
- **When** the attempt runs
- **Then** it fails with the cap's text (L4-VER-052) naming that browser test

### Requirement: L4-IMP-111 A test chore's prompt and questions say what it may change
When `gates.e2e` is configured, the prompt of a test chore SHALL say, under `# Browser tests`, that a browser test it
adds as a Python test under the e2e test directory counts as an added test, that the harness builds and serves the app
and runs the e2e gate after the step, that a browser test of the step must pass there and that the step cannot run it;
and, when `tdd.test_globs` does not cover that directory, that a file there is not a test file for the task and that
changing one fails the attempt. The prompt of a test chore that retakes a feedback item (`retakes` in `.l4/fix.json`)
SHALL say, under `# This item was taken before`, that a verifier judged the earlier take short of the item, that the
test files that take added are existing test files whose edit is put back, and that what the item still asks for goes
into new tests, with new names, in a new test file. A technical question of a test chore SHALL get a harness note that
keeps the fix chore's first sentence (`Harness note: this is a fix task.`) and then says that a new test file and new
tests appended to a test file a red step of the unit wrote are kept, that an edit of any other existing test file or of
a test-support file is put back whatever the answer says, that a missing check can go into a new test file, and that
otherwise a person commits the change and then answers. The fix chore's note SHALL NOT change. The blocks SHALL be built
by the prompt code, so no template version changes.

#### Scenario: SCN-IMP-597 (+) The test chore's question says what a test chore may keep
- **Given** a test chore that reports status blocked with one technical question
- **When** the harness writes the question
- **Then** its Context ends with a note that starts `Harness note: this is a fix task. It adds tests:` and says `a
  missing check can go into a new test file`, its `question.raised` has `chore: true`, and a fix chore's question keeps
  the note `It cannot unfreeze a test or test-support file`

#### Scenario: SCN-IMP-598 (+) A retake's prompt says the earlier tests stay and new tests go in a new file
- **Given** a test chore whose finding is listed under `retakes`, and another that is not
- **When** their prompts are rendered
- **Then** only the first holds `# This item was taken before` and `in a new test file`, and the template version of
  both is the one of 0.4.59

#### Scenario: SCN-IMP-599 (+) A test chore's prompt names the e2e gate when the project has one
- **Given** a test chore in a project with `gates.e2e` whose e2e directory is `e2e`, once with `tdd.test_globs`
  covering `e2e/` and once without
- **When** the prompt is rendered
- **Then** both hold `# Browser tests` and `counts as an added test`, only the second holds `a file there is not a test
  file for this task`, and a project without `gates.e2e` gets no such block
