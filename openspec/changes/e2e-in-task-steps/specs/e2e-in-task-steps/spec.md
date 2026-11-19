## Purpose

A browser test that a task's red step wrote runs, with the app served, in the step that completes that task, so a wrong
browser test is met where the task can still be unfrozen and fixed, not first at verification. The check is fail-safe:
only a failure the e2e run shows refuses an attempt.

## ADDED Requirements

### Requirement: L4-IMP-101 The step that completes a task runs that task's own browser tests
A task's *browser tests* SHALL be the
test functions that pytest would collect, with its default settings, from the Python files under the e2e test directory
(`e2e_test_dir(gates.e2e, worktree)`) that match `python_files` (`test_*.py`, `*_test.py`; not `conftest.py`, and not a
file of `tdd.test_support_globs`): a module-level `def test*` or `async def test*` that is not decorated as a fixture,
and a `test*` method of a module-level class named `Test*` that has no `__init__` (its own or an in-file base's), the
names `tamper.facts_of` gives (`test_x`, `TestA.test_x`). A fixture or a helper that only happens to be named `test*`, a
method of a class that is not `Test*`, a helper module and a file of another language are no tests. A browser test is
the task's when the task's red step added it or changed its own definition, read from git between the red commit's parent
and the red commit, so a red that a later run resumes counts the same and nothing of the agent's own record is trusted
(between the step base and the work tree for a red step that finishes the task as already satisfied); a change to what a
test reads in its file (an autouse fixture, `pytestmark`, a constant) does not make it the task's, and a support file
alone (a helper in `e2e/conftest.py`) adds none. A git error while reading them gives none, a ledger note
(`e2e.task_tests_unread`) and a warning, and does not fail the step. When `gates.e2e` is configured (`command`,
`serve.command` and `serve.ready_url`; `e2e_configured`) and the task has browser tests, its green step SHALL run
`gates.build` (when it is configured) and then the e2e gate (`run_e2e`, name `e2e-task`, the project's whole e2e command
as every e2e run of the harness) last: after the test gate, the static gates (L4-IMP-096), the test-at-red run and any
held check passed, and before its commit.

The check is fail-safe: an attempt SHALL be refused only for a failure that the e2e run itself shows. In this order: a
timed-out gate gives its reason; no readable report gives `the e2e gate produced no readable report (<reason>)`; a
collection error of a module that is one of the task's files gives `browser tests not collected: <modules>`; a browser
test of the task that the report shows as failed or errored (any of its ids) gives `the task's browser tests do not
pass: <ids>`, and the failure text of those (the retry excerpt, L4-IMP-064) SHALL be the excerpt the next attempt's
prompt carries. A browser test of the task that the report does not show SHALL NOT block the step: not collected, a
module name that cannot be mapped, a test a person's answer removed, a class pytest skipped, or only skipped ids. The
step SHALL record `e2e.task_tests_unseen{task, phase, tests, ambiguous}` and log that they were not seen and that
verification step 3 runs them as before. A report id is matched to a task test by its module and its function:
`evidence.testsran.file_of_test` resolves the module (the exact path wins; else the one Python file of the tree whose
path ends with the classname's module path, since pytest writes the classname from its rootdir, `test_layout` under an
`e2e/pytest.ini` and `e2e.test_layout` otherwise), two files that fit give no answer (the id is left out and listed in
`ambiguous`, never guessed), the class between module and function must be the test's own class (`TestA::test_x` is not
`TestB.test_x`, and a module-level function has none), and a `[param]` suffix is ignored. `must_contain` is not used,
because those exact ids are not known before the run. The other tests of the e2e report and the gate's exit code SHALL
NOT be judged at the step: a task step has no e2e baseline, and step 3 judges the whole gate. A build that fails SHALL
fail the attempt with `gates.build failed before the e2e gate: ...` and no e2e run. A server that is not ready SHALL fail
the attempt with `the e2e server was not ready (see <log name>)` and the last 2,000 characters of its log, redacted, as
the excerpt; it counts as a failed attempt (the agent's code may be what keeps the server from starting) and SHALL NOT
be an error of the run; any other refusal of `run_e2e` (a format it does not read, no `reports`) stops the run with its
exit as for a fix chore (L4-IMP-090). Such a failure is no near pass (L4-IMP-100): a near pass stops at the static gates,
before the e2e run. What the runs write into the tree is put away as for a fix chore (L4-IMP-090: a new path goes back to
the base, a path the step had edited gets the step's content back, a link a gate planted is removed and recorded, the
test-path freeze runs again with the files the task may change kept), so the commit holds the tree the test gate tested
(L4-IMP-088).

The run SHALL be skipped, and no build or e2e run paid for, when the e2e gate cannot tell the task's browser tests from
the other tests of its directory: when the e2e command selects tests with `-m` or `-k` after its `pytest` word (its
report holds only part of the directory), or when the e2e directory also holds tests that the unit gate's report of the
step shows (`pytest tests -m browser` with `tests/` as the unit gate's directory, where every unit test would be a
browser test). The skip SHALL be decided before the step from the baseline and red reports (so the green prompt promises
no run), and again from the step's own unit report; it SHALL be recorded as `e2e.task_run_skipped{task, phase, reason,
tests}` and logged, and verification step 3 runs the browser tests as before. A red step that finishes a task as already
satisfied (L4-IMP-003) SHALL run the task's browser tests the same way before its commit (with no test-path freeze: the
test files are the step's own), and a failure SHALL fail the red attempt, whose next attempt may change the test. A red
step that commits a red SHALL NOT run the e2e gate: a browser test's honest red failure is often an error raised in the
browser library (a locator that waits for a button not built yet), so red could not ask for an assertion, and a test
whose page is its own fails before and after the code alike. When `gates.e2e` is not configured, or the task has no
browser tests, no step of the task SHALL run it (a gate with a command only is refused at step 3 as before). The green
prompt SHALL list the task's browser tests (`path::name`) in a block that says the harness builds and serves the app
after the step and runs them, that the task is not green while one of them fails, that one the report does not show is
run at verification, and that they are frozen like the other red tests (a wrong one: a technical question whose first
option is the edit, L4-IMP-015); the red prompt's browser-test paragraph SHALL say that the step that completes the task
runs them with the app served, and that they are frozen after red only when `tdd.test_globs` covers the e2e directory.
Cost: at most one build and one e2e gate run per green attempt of a task with browser tests that passed every other
check, none for any other task, each bounded by `gates.timeout`, and the run deadline's cap of a green step that runs
them counts them (L4-IMP-067).

#### Scenario: SCN-IMP-548 (−) A wrong browser test is met in green · L4-IMP-101
- **Given** a task whose red commit added `e2e/test_layout.py::test_width`, a configured `gates.e2e`, and a green step
  after which the e2e run reports `e2e.test_layout::test_width[chromium]` failed with `assert 1508 == 1500`
- **When** the green attempt is judged
- **Then** it fails with `the task's browser tests do not pass: e2e.test_layout::test_width[chromium]`, the next
  attempt's prompt holds `assert 1508 == 1500`, the task is not ticked, and `gate.finished` holds a run named `e2e-task`

#### Scenario: SCN-IMP-549 (+) Passing browser tests let the task be green · L4-IMP-101, L4-IMP-088
- **Given** the task of SCN-IMP-548 and a green step after which that test passes, with `gates.build` configured
- **When** the attempt is judged
- **Then** the build runs once and then the e2e gate once, the task is done, and what the runs wrote into the tree (a
  build output, `test-results/`) is not in the green commit

#### Scenario: SCN-IMP-550 (+) A task that touched no browser test runs no e2e gate · L4-IMP-101
- **Given** a task whose red commit changed only unit tests and `e2e/conftest.py`, and another unit whose `gates.e2e`
  has a command but no `serve.command`
- **When** their green steps run
- **Then** neither runs the build or the e2e gate, and both are judged as before

#### Scenario: SCN-IMP-551 (−) A server that never gets ready is a failed attempt · L4-IMP-101
- **Given** a task with browser tests whose e2e server never becomes ready
- **When** its green attempt runs the e2e gate
- **Then** the attempt fails with `the e2e server was not ready (see <log name>)`, the end of the log is the excerpt,
  the attempt is counted, and the run does not stop with an internal error

#### Scenario: SCN-IMP-552 (+) A browser test the report does not show does not block green · L4-IMP-101
- **Given** a task with browser tests `test_a` and `test_b`, and an e2e report that holds no id of `test_b`, or holds
  `test_b[chromium]` only as skipped, or holds only a module name that two files fit
- **When** the green attempt is judged
- **Then** it is not refused, `e2e.task_tests_unseen` names `e2e/test_layout.py::test_b` (and the ambiguous ids), the
  step log says they were not seen and that verification step 3 runs them; when `test_a` fails in the report the attempt
  is refused naming `test_a` only; an e2e test that is not the task's and fails changes nothing

#### Scenario: SCN-IMP-553 (+) The e2e run comes last · L4-IMP-101, L4-IMP-100
- **Given** a task with browser tests, a green attempt whose test gate fails, and another whose tests pass and whose
  lint gate fails
- **When** they are judged
- **Then** neither runs the e2e gate, and the second is a near pass as before

#### Scenario: SCN-IMP-554 (−) An already-satisfied task's browser test must pass before its commit · L4-IMP-101, L4-IMP-003
- **Given** a red step that adds a browser test for a criterion the harness confirms as already satisfied, and an e2e
  run in which that test fails
- **When** red would finish the task as already satisfied
- **Then** the red attempt fails naming the test, nothing is committed, and the next red attempt may change the test;
  when the test passes, the task is committed as already satisfied with the test

#### Scenario: SCN-IMP-555 (+) A resumed red still has its browser tests · L4-IMP-101
- **Given** a task whose red commit added a browser test, and a later run that resumes the task at its green step
- **When** the green step runs
- **Then** it runs the e2e gate for that test, as the run that made the red commit would have

#### Scenario: SCN-IMP-562 (+) Only the tests pytest would collect, and only those the red step wrote, are the task's · L4-IMP-101
- **Given** a red commit that adds `e2e/test_pages.py` with a fixture `test_user`, a method `Helper.test_helper`, a
  `TestA.test_x` and a module-level `test_real`, `e2e/helpers.py` with `testid`, and, in an existing e2e module, a new
  autouse fixture
- **When** the task's browser tests are read
- **Then** they are `TestA.test_x` and `test_real` of `e2e/test_pages.py` only: the fixture, the helper, the helper
  module and the tests of the existing module (whose own definitions did not change) are not the task's

#### Scenario: SCN-IMP-563 (+) A report id is matched by module suffix and by class · L4-IMP-101
- **Given** a task with `e2e/test_layout.py::TestA.test_x` and `TestB.test_x`, and reports whose classname is
  `e2e.test_layout` or, under an `e2e/pytest.ini`, `test_layout`
- **When** the green attempt is judged
- **Then** both id shapes name the tests; `TestA::test_x` passing does not stand for `TestB.test_x`; a report that
  holds `TestB::test_x` failing refuses the attempt naming it; a report without it leaves it unseen; with a second file
  `e2e/other/test_layout.py` the id `test_layout::test_x` is neither test's and is listed as ambiguous

#### Scenario: SCN-IMP-564 (+) A run that cannot tell the task's tests apart is skipped · L4-IMP-101, L4-IMP-067
- **Given** a task with browser tests and an e2e command `pytest e2e -m browser`, or an e2e command `pytest tests`
  whose directory the unit gate's report also holds tests of
- **When** its green step runs and its deadline is checked
- **Then** no build and no e2e run is paid for, `e2e.task_run_skipped` names the reason, the green prompt lists no
  browser tests, the cap of the green step is the plain one, and verification step 3 runs the browser tests as before

### Requirement: L4-IMP-067 (amendment, the cap of a green step that runs the e2e gate)
For a green step that will run the build and the e2e gate (L4-IMP-101: `gates.e2e` configured, browser tests in the
task's red commit, the run not skipped), the cap of the step's estimate SHALL be the agent's time limit plus three times
`gates.timeout` (the test gate, the build and the e2e gate); every other cap SHALL stay as it is. A skip that only the
step's own unit report shows leaves that cap a little high, which can only defer a step.

#### Scenario: SCN-IMP-556 (+) The deadline counts a green step's e2e gate · L4-IMP-067, L4-IMP-101
- **Given** a known deadline, `gates.timeout: 10m`, the agent's 30-minute limit, a recorded green step of 55 minutes,
  and a task whose red commit has browser tests that the green step will run (`gates.e2e` configured, no `-m`/`-k`)
- **When** the next green step is checked
- **Then** its estimate is 55 minutes (the cap is 60), where for a task without browser tests, or with `gates.e2e` not
  configured, or whose run is skipped, it would be 40
