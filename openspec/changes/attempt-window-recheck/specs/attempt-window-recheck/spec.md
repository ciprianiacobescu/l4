## Purpose

An answer that unfreezes a frozen file for a task's green step gives that green a full window of attempts, once per
answer and within a stated bound. A step that would fail an attempt only because a few pre-existing tests failed runs
its test gate once more, and a test that passes there does not fail the attempt. Verification lists every such test.

## ADDED Requirements

### Requirement: L4-IMP-104 An answer that unfreezes a file for a task's green renews its green attempts once
When a task's green step is about to start in a run (a red commit resumed at the task's start, or a red commit made in
the run), and before the escalation that precedes its first attempt, the harness SHALL take the grants that open a
frozen file for that green under L4-IMP-015 and L4-DLG-014 (`reason` `human_answer` or `delegate_answer`, at least one
path). A grant SHALL renew the window when its question is credited nowhere yet: no earlier `task.attempts_renewed`
of the task names it, and no earlier `task.unfrozen` of the task with `reason` `human_answer` or `delegate_answer` (or
none, an old event) names it in `question` (the same fix unit, over the whole ledger). Then the harness records `task.attempts_renewed{task, phase: green, questions,
failed}`, where `failed` is the count of failed green attempts it clears, and clears the green phase's failed attempts,
their reasons and its newest move (L4-IMP-094). Attempt numbers SHALL go on. A renewal SHALL NOT be made when `failed`
is above 0 and the task already has 2 renewals with `failed` above 0 since the newest `unit.retried`, `unit.resumed` or
`unit.restarted`. The harness then logs a warning and records nothing. When a later run seeds the task's attempts
(L4-IMP-075), a `task.attempts_renewed` in the window SHALL clear the green counts seeded before it. The task's own
text (`named_by_task`) SHALL renew nothing. The deadline's stop count (L4-IMP-071) SHALL NOT change. Between two `l4
retry`, `l4 resume` or `l4 restart` a task's green phase SHALL have at most three windows, each bounded as L4-IMP-075
and L4-IMP-094 bound one: with one profile in `roles.implementer`, at most three times
`implementer.max_task_attempts` failed green attempts.

#### Scenario: SCN-IMP-566 (+) An answer that unfreezes the test gives green a full window
- **Given** green attempts 1 and 2 of task 1.2 that failed, a green attempt 3 that raised a question, and the
  delegate's accept of the suggestion `Edit e2e/test_layout.py`, which unfreezes that file (`delegate.unfreeze: true`)
- **When** the next run resumes the task at green with one profile and `implementer.max_task_attempts: 3`
- **Then** `task.attempts_renewed{task: 1.2, phase: green, questions: [Q-001], failed: 2}` is recorded before the first
  attempt, the attempt is numbered 3, and the task may fail 3 green attempts in this window before the breaker trips

#### Scenario: SCN-IMP-567 (−) The same answer renews once
- **Given** the unit of SCN-IMP-566 after attempts 3 and 4 failed with the same answer in place
- **When** a later run resumes the task at green
- **Then** no second `task.attempts_renewed` is recorded, and the task has one attempt left

#### Scenario: SCN-IMP-568 (−) An answer that opens nothing, and the task's text, renew nothing
- **Given** an answered question whose answer names no frozen file, a delegate's accept while `delegate.unfreeze` is
  false, and a support file that the task's reviewed text opens (`named_by_task`)
- **When** green is about to start
- **Then** no `task.attempts_renewed` is recorded, and the failed attempts count as before

#### Scenario: SCN-IMP-569 (−) Renewals are bounded between two retries
- **Given** a task with 2 renewals with `failed` above 0 since its last `unit.resumed`, and a third answered question
  that unfreezes another file
- **When** green is about to start
- **Then** nothing is recorded, a warning names the cap, and the task halts on `max_task_attempts` as before; after
  `l4 resume` the window is new anyway

#### Scenario: SCN-IMP-570 (+) A unit in flight from 0.4.59 renews on its next run
- **Given** a ledger written by 0.4.59 with two failed green attempts and an accepted answer that unfreezes the test,
  not yet used by a green attempt; and another whose 0.4.59 green attempt already recorded `task.unfrozen` for its
  answer
- **When** the next run on 0.4.60 resumes each task at green
- **Then** the first window is renewed once, the second is not, and a ledger without the event folds as before

### Requirement: L4-IMP-105 A step runs its test gate once more before it fails on pre-existing tests
When a red step would fail its attempt with `red broke existing tests`, or a green step or a fix, tests or refactor
chore with `green broke existing tests`, and that is the only reason, the step SHALL run its test gate once more, its
whole command, as `test-recheck`, with the same environment, when all of these hold: one to five tests regressed; each
failed or errored in run 1 and holds no time-out marker; and each one's file is found and is not a file the unit's
branch or this step changed. Before run 1 the step SHALL record the worktree's untracked paths, and before the re-run
it SHALL remove what is new since, as L4-VER-076 does. There SHALL be no re-run when that cannot be done, or when the
armed soft deadline leaves less than run 1's duration plus the larger of 60 seconds and a tenth of it. The step's
guards after a gate run SHALL run after the re-run. When the re-run is usable and every regressed test passes in it,
and no test that passed in run 1 fails or is missing in it, the regressed tests SHALL be flaky. The step SHALL then go
on with run 1's report, each flaky test's case taken from the re-run, and judge it again with the same checks. That
report is also the one any later reader of the step's report, and the next task's baseline, reads (L4-IMP-088). In
every other case the attempt SHALL fail with run 1's reason. A re-run that ran and failed adds `; failed again on a
re-run (L4-IMP-105): <ids>`. An unusable one adds `; its re-run was not usable`. Each case with candidates SHALL be
recorded as `task.tests_rechecked{task, phase, attempt, tests, flaky, failing, new_failures, stopped}` (`stopped`:
`passed`, `failed`, `unusable`, `tree` or `budget`). An attempt SHALL get at most one re-run. A repair chore, a new
test, a test the unit's branch or the step changed, a hung test and a test missing from run 1 SHALL get none.

#### Scenario: SCN-IMP-571 (+) A pre-existing test that fails once in green and passes on the re-run does not fail the attempt
- **Given** a green step whose test gate passes the red tests and fails only `tests.test_stack::test_ready`, which
  passed in the step's base report and lies in a file the unit did not change, and a re-run in which it passes
- **When** the step judges its gate
- **Then** `test-recheck` ran once, `task.tests_rechecked{stopped: passed, flaky: [tests.test_stack::test_ready]}` is
  recorded, the task is committed green, and `keep_tested` holds the test as passed

#### Scenario: SCN-IMP-572 (−) A test the step broke fails twice and fails the attempt
- **Given** the step of SCN-IMP-571 whose re-run fails `tests.test_stack::test_ready` again
- **When** the step judges its gate
- **Then** the attempt fails with `green broke existing tests: tests.test_stack::test_ready; failed again on a re-run
  (L4-IMP-105): tests.test_stack::test_ready` and `task.tests_rechecked{stopped: failed}`

#### Scenario: SCN-IMP-573 (−) No re-run for six tests, a changed file, a hang, a gone test or another reason
- **Given** green attempts that regress six pre-existing tests; one in a file the unit changed; one whose message holds
  the time-out marker; one missing from the report; and one whose gate also leaves a red test failing
- **When** each step judges its gate
- **Then** no `test-recheck` runs, no `task.tests_rechecked` is recorded, and each attempt fails with the reason of
  0.4.59

#### Scenario: SCN-IMP-574 (−) No re-run without time or a clean tree
- **Given** a step with candidates whose armed soft deadline leaves less than run 1's duration plus 60 seconds, and
  another whose tree cannot be put back
- **When** each step judges its gate
- **Then** no `test-recheck` runs, `task.tests_rechecked` has `stopped: budget` and `stopped: tree`, and each attempt
  fails with run 1's reason

#### Scenario: SCN-IMP-575 (+) Red and a fix chore get the re-run too
- **Given** a red step whose only failure reason is `red broke existing tests: tests.test_dns::test_no_lookup`, and a
  fix chore whose only one is `green broke existing tests` on the same test, each passing it on the re-run
- **When** each step judges its gate
- **Then** red commits its red tests and the chore commits its fix, each with `task.tests_rechecked{stopped: passed}`,
  and the red step's tamper check ran after the re-run

#### Scenario: SCN-IMP-576 (−) A re-run that fails a test run 1 passed fails the attempt
- **Given** a re-run in which the regressed test passes and another pre-existing test, which passed in run 1, fails
- **When** the step judges its gate
- **Then** the attempt fails with run 1's reason and `; failed again on a re-run (L4-IMP-105): <that test>`, and
  `new_failures` names it

### Requirement: L4-VER-082 Verification lists the tests that passed only on a task step's re-run
`verification.md` SHALL list under `## Pre-existing tests that passed on a task step's re-run (L4-IMP-105)` every test
that a `task.tests_rechecked{stopped: passed}` of the unit's ledger (its fix units' included) names as flaky, as `<id>
(task <k> <phase> attempt <n>)`, with `, fix unit <f>` for a fix unit's, at most 20 lines and then `(+<n> more)`.
`verdict.json` SHALL store the lines as `step_flakes`, and a reused round SHALL keep them. The listing SHALL NOT be a
finding and SHALL NOT change the verdict. A ledger with no such event SHALL list nothing.

#### Scenario: SCN-VER-322 (+) The flaky test of a task step is listed
- **Given** the unit of SCN-IMP-571
- **When** the unit is verified
- **Then** `verification.md` holds the section with `tests.test_stack::test_ready (task 1.2 green attempt 1)`, and
  `verdict.json` holds it in `step_flakes`

#### Scenario: SCN-VER-323 (−) Nothing is listed without a passed re-run
- **Given** a unit whose ledger holds only `task.tests_rechecked{stopped: failed}`, and a 0.4.59 unit with none
- **When** each unit is verified
- **Then** neither `verification.md` has the section, and the verdict is what it is without this change
