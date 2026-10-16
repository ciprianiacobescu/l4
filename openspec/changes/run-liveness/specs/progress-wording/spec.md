## Purpose

The CI log says what a red step's failing test gate means, and a GitHub run's summary page lists the tasks that ended
in it, so a person does not take the intended failure of red for a problem.

## ADDED Requirements

### Requirement: L4-OBS-004 A red test gate that fails only on new tests says that this is intended
For the test gate that `run_red` runs after the agent, `gate.finished` SHALL record `red_new_failing: <n>` when all of
these hold, and SHALL not have the key otherwise:
- the gate status is `fail`, and its report is readable;
- at least one test fails or errors;
- every failing or erroring test is new: its id is not in the base report that `run_red` took before the agent ran;
- each of them failed by assertion or with `NotImplementedError` (the failure kinds that the red check accepts), and
  none carries the hang marker;
- the report has no collection error that the base report does not have.
The progress log SHALL print an event with `red_new_failing` at INFO as `red: <n> new tests fail, as intended` (`red: 1
new test fails, as intended` for one), and SHALL print the gate line of today for it at DEBUG. Every other gate SHALL
print as today. The key MUST NOT change the verdict of the red step: the red check decides as before.

#### Scenario: SCN-OBS-03 (+) A red gate that fails only on new tests prints the red line
- **GIVEN** a red step whose base report has 5 passing tests, and whose gate report after the agent has the same 5 passing and 7 new tests that fail by assertion or with `NotImplementedError`
- **WHEN** the gate ends and the progress log prints it
- **THEN** `gate.finished` has `red_new_failing: 7`, the INFO line is `red: 7 new tests fail, as intended`, and `gate test fail (exit 1, 12 tests: 5 passed, 7 failed)` is at DEBUG
- **AND** with one new failing test the INFO line is `red: 1 new test fails, as intended`

#### Scenario: SCN-OBS-04 (−) Every other failing gate prints as today
- **GIVEN** in turn: a red gate where a new test fails with `TypeError`; a red gate where an old test fails too; a red gate with a new collection error; a green gate that fails; a red gate with no readable report
- **WHEN** each gate ends
- **THEN** no `gate.finished` has `red_new_failing`, each prints the gate line of today at INFO, and the red verdicts are the ones of today

### Requirement: L4-OBS-005 In GitHub Actions each task that ends adds a line to the job summary
When `GITHUB_ACTIONS` is `true` and `GITHUB_STEP_SUMMARY` names a file, `l4 run` SHALL append one Markdown list line
to that file for each task that ends in the run:
- `task.done`: `- <unit> task <k>: done (<n> attempts, <profile>, <took>)`, where `<n>` is the number of agent steps
  of the task in this run, `<profile>` the profile of the last one, and `<took>` the time since `task.started` in the
  format of L4-IMP-023;
- `task.red_ok` with `tdd: already-satisfied`: `- <unit> task <k>: already satisfied (no green step)`;
- `task.done` with `tdd: already-done`: `- <unit> task <k>: done (closed with no open required task)`;
- `breaker.tripped`: `- <unit> task <k>: halted (<reason code>)`.
A task of a fix unit SHALL have `[<fix unit>]` after the unit. The line MUST NOT hold text of an agent or of a person
(no notes, no failure reasons): only ids, codes, numbers and the profile name. A failed write SHALL be logged once at
WARNING and MUST NOT stop the run. Outside GitHub Actions nothing SHALL be written.

#### Scenario: SCN-OBS-05 (+) The job summary lists the tasks that ended
- **GIVEN** `GITHUB_ACTIONS=true`, `GITHUB_STEP_SUMMARY` naming a file, and a run of `openspec:add-x` where task 2.1 is done after two agent steps on `deepseek` in 11 minutes, task 2.2 is already satisfied, task 2.3 halts on `max_task_attempts`, and task 1.1 of the fix unit `add-x-fix-1` is done
- **WHEN** the run ends
- **THEN** the file ends with `- openspec:add-x task 2.1: done (2 attempts, deepseek, 11m)`, `- openspec:add-x task 2.2: already satisfied (no green step)`, `- openspec:add-x task 2.3: halted (max_task_attempts)` and `- openspec:add-x [add-x-fix-1] task 1.1: done (…)`

#### Scenario: SCN-OBS-06 (−) No summary outside GitHub, no agent text, and a failed write does not stop the run
- **GIVEN** in turn: no `GITHUB_ACTIONS`; `GITLAB_CI=true`; a `task.done` whose `notes` hold a sentence of the agent; a `GITHUB_STEP_SUMMARY` that names a path that cannot be written
- **WHEN** the run ends
- **THEN** the first two write no file, the third's line holds no word of the notes, and the fourth logs one WARNING and the run ends with the exit code it would have without the summary
