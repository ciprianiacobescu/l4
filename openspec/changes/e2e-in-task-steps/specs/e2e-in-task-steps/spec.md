## Purpose

A browser test that a task's red step wrote runs, with the app served, in the step that completes that task, so a wrong
browser test is met where the task can still be unfrozen and fixed, not first at verification.

## ADDED Requirements

### Requirement: L4-IMP-101 The step that completes a task runs that task's own browser tests
A task's *browser tests* SHALL be the test functions (`tamper.facts_of`) of the Python files under the e2e test
directory (`e2e_test_dir(gates.e2e, worktree)`), other than `conftest.py`, `__init__.py` and files of
`tdd.test_support_globs`, that the task's red step added or whose definition or what they use in their file changed,
read from git between the red commit's parent and the red commit (between the step base and the work tree for a red
step that finishes the task as already satisfied). A support file alone and a file of another language add none.

When `gates.e2e` is configured (`command`, `serve.command` and `serve.ready_url`) and the task has browser tests, its
green step SHALL run `gates.build` (when it is configured) and then the e2e gate (`run_e2e`, name `e2e-task`) after the
test gate, the static gates, the test-at-red run and any held check passed, and before its commit. The attempt SHALL
fail unless each browser test of the task has an id in the report (the module and the function, a parametrised id
included) and each of its ids passed or was skipped with at least one passed. The reason SHALL name the tests (`the
task's browser tests do not pass: <ids>`, or `are not in the e2e report: <path::name>`), and the failure text of the
failing ones SHALL be the excerpt the next attempt's prompt carries. A timed-out gate, a run with no readable report and
a collection error of one of the task's files SHALL fail the attempt. The other tests of the e2e report SHALL NOT be
judged at the step. A build that fails SHALL fail the attempt before the e2e run. A server that is not ready SHALL fail
the attempt with `the e2e server was not ready (see <log name>)` and the end of its log, redacted, as the excerpt, and
SHALL NOT be an error of the run. Such a failure is no near pass (L4-IMP-100). What the runs write into the tree is put
away as for a fix chore (L4-IMP-090), so the commit holds the step's work only.

A red step that finishes a task as already satisfied (L4-IMP-003) SHALL run the task's browser tests the same way
before its commit, and a failure SHALL fail the red attempt. A red step that commits a red SHALL NOT run the e2e gate.
When `gates.e2e` is not configured, or the task has no browser tests, no step of the task SHALL run it. The green
prompt SHALL name the task's browser tests and say that the harness runs them after the step; the red prompt SHALL say
that the green step runs them with the app served and that they are frozen after red.

#### Scenario: SCN-IMP-548 (−) A wrong browser test is met in green
- **Given** a task whose red commit added `e2e/test_layout.py::test_width`, and a green step after which the e2e run
  reports `e2e.test_layout::test_width[chromium]` failed with `assert 1508 == 1500`
- **When** the green attempt is judged
- **Then** it fails with a reason that names the test, the next attempt's prompt holds `assert 1508 == 1500`, the task
  is not ticked, and `gate.finished` holds a run named `e2e-task`

#### Scenario: SCN-IMP-549 (+) Passing browser tests let the task be green
- **Given** the task of SCN-IMP-548 and a green step after which the test passes, with `gates.build` configured
- **When** the attempt is judged
- **Then** the build runs once, then the e2e gate once, the task is done, and what the runs wrote into the tree is not
  in the green commit

#### Scenario: SCN-IMP-550 (+) A task that touched no browser test runs no e2e gate
- **Given** a task whose red commit changed only unit tests and `e2e/conftest.py`, and another unit whose `gates.e2e`
  has a command but no `serve.command`
- **When** their green steps run
- **Then** neither runs the build or the e2e gate, and both are judged as before this change

#### Scenario: SCN-IMP-551 (−) A server that never gets ready is a failed attempt
- **Given** a task with browser tests whose e2e server never becomes ready
- **When** its green attempt runs the e2e gate
- **Then** the attempt fails with `the e2e server was not ready (see <log name>)`, the end of the log is the excerpt, it
  counts as a failed attempt, and the run does not stop with an internal error

#### Scenario: SCN-IMP-552 (−) A browser test that did not run does not pass
- **Given** a task with browser tests `test_a` and `test_b`, and an e2e report that holds no id of `test_b`, or holds
  `test_b` only as skipped
- **When** the green attempt is judged
- **Then** it fails naming `test_b`, and a failing e2e test that is not the task's changes nothing

#### Scenario: SCN-IMP-553 (+) The e2e run comes last
- **Given** a task with browser tests, a green attempt whose test gate fails, and another whose tests pass and whose
  lint gate fails
- **When** they are judged
- **Then** neither runs the e2e gate, and the second is a near pass as before (L4-IMP-100)

#### Scenario: SCN-IMP-554 (−) An already-satisfied task's browser test must pass before its commit
- **Given** a red step that adds a browser test for a criterion the harness confirms as already satisfied, and an e2e
  run in which that test fails
- **When** red would finish the task as already satisfied
- **Then** the red attempt fails naming the test, nothing is committed, and the next red attempt may change the test

#### Scenario: SCN-IMP-555 (+) A resumed red still has its browser tests
- **Given** a task whose red commit added a browser test, and a later run that resumes the task at its green step
- **When** the green step runs
- **Then** it runs the e2e gate for that test, as the run that made the red commit would have

### Requirement: L4-IMP-067 (amendment, the cap of a green step that runs the e2e gate)
When `gates.e2e` is configured, the cap of a green step's estimate SHALL be the agent's time limit plus three times
`gates.timeout` (the test gate, the build and the e2e gate, L4-IMP-101); every other cap SHALL stay as it is.

#### Scenario: SCN-IMP-556 (+) The deadline counts a green step's e2e gate
- **Given** a known deadline, `gates.timeout: 10m`, the agent's 30-minute limit, a configured `gates.e2e`, and a
  recorded green step of 55 minutes
- **When** the next green step is checked
- **Then** its estimate is 55 minutes (the cap is 60), where without `gates.e2e` it would be 40
