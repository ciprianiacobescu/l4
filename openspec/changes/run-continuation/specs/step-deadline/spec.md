## Purpose

When the CI job's budget is known, a run is never killed by the CI timeout. A step that cannot finish before the soft
deadline is not started, or is stopped and handed back without counting as an attempt. Exactly one continuation
follows, and a step that never fits in one job halts the unit by name.

## ADDED Requirements

### Requirement: L4-IMP-066 The soft deadline counts from the job's start
The soft deadline SHALL count from the start of the CI job. That start is `L4_JOB_STARTED_AT` when set, else GitLab's
`CI_JOB_STARTED_AT`, else the start of the run, and a value that does not parse is skipped. Both GitHub workflow
templates SHALL have, as their first step, a step named `job start` that writes `L4_JOB_STARTED_AT` (UTC, ISO 8601) to
`$GITHUB_ENV`. When a budget is known and the job's start is not, `l4 run` MUST say once, as a WARNING, that it counts
from the run's start and that `l4 upgrade` adds the step. `run.started` SHALL record `job_timeout_s` (the budget before
the margin) and `job_started_at` when they are known.

#### Scenario: SCN-IMP-332 (+) The job's start comes from L4_JOB_STARTED_AT
- **GIVEN** `L4_JOB_TIMEOUT_MINUTES=180`, the default 20-minute margin, and `L4_JOB_STARTED_AT` 12 minutes before
  `l4 run` starts
- **WHEN** `l4 run` computes the time left at its start
- **THEN** it is 148 minutes, not 160

#### Scenario: SCN-IMP-333 (−) Without the job's start the run's start is used and said once
- **GIVEN** `L4_JOB_TIMEOUT_MINUTES=180` and neither `L4_JOB_STARTED_AT` nor `CI_JOB_STARTED_AT`
- **WHEN** `l4 run` runs two units
- **THEN** the deadline counts from the run's start, and one WARNING line says `the job's start is unknown (no
  L4_JOB_STARTED_AT)` and names `l4 upgrade`

#### Scenario: SCN-IMP-334 (+) The templates record the job's start and run.started records the budget
- **GIVEN** a configuration rendered with `l4 ci render` for GitHub, in both forms (`l4.github.yml` and the action form)
- **WHEN** the workflow is rendered and a run starts in a job with `L4_JOB_TIMEOUT_MINUTES=180` and `L4_JOB_STARTED_AT`
- **THEN** the first step is `job start` and writes `L4_JOB_STARTED_AT` to `$GITHUB_ENV`, and `run.started` has
  `job_timeout_s: 10800` and that `job_started_at`

### Requirement: L4-IMP-067 A step that does not fit is not started
When the deadline is known, `l4 run` SHALL compare the time left to the soft deadline with the step's estimate before
each implementer step (red, green, a single-phase chore, also of a fix unit) and before each verification round. For a
task, the first check SHALL be made when the task starts, before a committed red is resumed (its setup and baseline
belong to the green step), and again after a fall-back to another profile. The estimate SHALL be the longest step of the
same phase measured in this run or among the unit's last 10 recorded `step.timed` and stopped steps of that phase, or,
with no measure of that phase, the longest of any phase. It SHALL be at least 10 minutes, and at most a cap per phase:
the agent's time limit plus `gates.timeout` for red, green and single, and four times `gates.timeout` for a
verification round. A step whose estimate exceeds the time left MUST NOT start, and the step is handed back
(L4-IMP-069). The first step of a run MUST start whenever any time is left. A step that was stopped at the last
deadline (L4-IMP-071) starts only as the first step of a run. Every step that starts SHALL record `step.timed{phase,
task, attempt, seconds}` (a round: `round` in place of `task` and `attempt`). With no known budget, no step is checked.

#### Scenario: SCN-IMP-335 (+) A green that does not fit after a long red is not started
- **GIVEN** a 180-minute job, the 20-minute margin, the job's start known, and a unit whose red step took 23.5 minutes
  in this run and ended at minute 155
- **WHEN** the run is about to start the task's green step (300 s left, estimated 1410 s)
- **THEN** no agent runs, `deadline.reached{when: before, phase: green, left_s: 300, estimate_s: 1410}` is recorded, and
  the unit's exit reason is `soft deadline: task 1.1 green not started (300 s left, step estimated 1410 s); the next run
  continues it`

#### Scenario: SCN-IMP-336 (+) The first step of a run always starts
- **GIVEN** a run whose first step has 400 s left and whose unit has a recorded red of 1800 s
- **WHEN** the run reaches that first step
- **THEN** the step starts

#### Scenario: SCN-IMP-337 (+) The estimate reads the unit's recorded steps, with a floor and a cap
- **GIVEN** a fresh run whose unit has recorded greens of 300 s and 5000 s, and a red of 200 s measured in this run
- **WHEN** the run is about to start a green as its second step
- **THEN** the estimate is 3600 s (the cap: 1800 s plus `gates.timeout` 30m); with recorded greens of 120 s only, the
  estimate is 600 s (the floor)

#### Scenario: SCN-IMP-338 (+) No known budget, no check
- **GIVEN** `ci.time_budget: auto` with neither `L4_JOB_TIMEOUT_MINUTES` nor `CI_JOB_TIMEOUT`
- **WHEN** a unit runs its red and green
- **THEN** both start, and no `deadline.reached` is recorded

#### Scenario: SCN-IMP-360 (+) A resumed green is checked before its baseline, and so is a step after a fall-back
- **GIVEN** a unit whose branch holds the red commit of task 1.1, a run with 300 s left when the unit's tasks start (not
  its first step), and a recorded green of 1410 s
- **WHEN** the task starts
- **THEN** `deadline.reached{when: before, phase: green}` is recorded before `gates.setup` and the baseline gate run,
  and
  no `task.red_resumed` is recorded; and in a run where a green hits a usage limit and the task goes on with the next
  profile, the new `run_task` is checked before it runs anything

#### Scenario: SCN-IMP-361 (+) A verification round has its own cap
- **GIVEN** a unit with a recorded verification round of 7000 s and `gates.timeout` 30m
- **WHEN** the run is about to start a round with 6800 s left, not as its first step
- **THEN** the estimate is 7000 s (under the round's cap of 7200 s), and the round is not started

### Requirement: L4-IMP-068 A step still running at the soft deadline is stopped
When the soft deadline is reached, the harness SHALL send SIGINT (never SIGTERM) to the process group of every agent,
CLI judge and gate that the unit's run has running, and SIGKILL to the group 5 seconds later if it has not exited. A
process started after the deadline MUST be stopped at once. A process stopped by the deadline MUST be reported as
stopped by the deadline even when its idle limit or its time limit fired too, so that it never counts as a failed
attempt. The stopped step MUST be handed back (L4-IMP-069) after the cleanup it already does (protected paths, gate and
runner configuration and the ledger put back, scratch dropped, `agent.finished` and the reported cost recorded). The
agent's `step.finished` SHALL record `status: deadline`. A stop inside the verifier MUST NOT become a failed
verification step. A CLI judge or clarifier stopped this way MUST record the cost it metered (`budget.cost` with `usd` or `credits`) before the stop is handed back.

#### Scenario: SCN-IMP-339 (+) An agent running at the deadline is stopped and its changes are not kept
- **GIVEN** a green agent step that has written `half.txt` and is running when the deadline fires
- **WHEN** the deadline fires
- **THEN** the agent's group gets SIGINT, then SIGKILL after 5 s when still alive; `step.finished{status: deadline}`
  and `deadline.reached{when: during, during: agent}` are recorded, no `task.attempt_failed` is recorded, and
  `half.txt` is not in any commit

#### Scenario: SCN-IMP-340 (+) A gate running at the deadline is stopped
- **GIVEN** the red step's test gate is a real command that writes a marker file and then sleeps, and the deadline is
  fired as soon as the marker exists
- **WHEN** the deadline fires
- **THEN** the gate's group is stopped, `gate.finished` is recorded, then `deadline.reached{when: during, during: gate,
  gate: test}`, and the red is not committed and not counted as a failed attempt

#### Scenario: SCN-IMP-341 (+) A CLI judge of a verification round is stopped without failing the round's step
- **GIVEN** a verification round run by the real ladder, whose CLI judge is running when the deadline fires
- **WHEN** the deadline fires
- **THEN** the judge step's `finally` still writes the calibration rows, `deadline.reached{when: during, during: judge,
  phase: verify}` is recorded, no `verify.step{status: failed}` and no `verify.verdict` are recorded for the round, and
  the unit stays `verifying`

#### Scenario: SCN-IMP-362 (+) The deadline wins over an idle stop or a time limit
- **GIVEN** a green agent that has been silent past `implementer.idle_timeout`, or has reached its time limit, in the
  same poll in which the deadline fires (or while its idle grace runs)
- **WHEN** the process ends
- **THEN** its outcome has `deadline: true` and neither `stalled` nor `timed_out`, the step is handed back, and no
  `task.attempt_failed` or `agent.idle` is recorded

### Requirement: L4-IMP-069 A step handed back at the soft deadline is resumed by the next run
A step handed back (not started under L4-IMP-067, or stopped under L4-IMP-068) MUST NOT count as an attempt and MUST
NOT change the unit's phase. The run SHALL record `deadline.reached` filled from the step that was current when the
deadline stopped it (phase, task, attempt or round, `left_at_start_s`, `estimate_s`, `ran_s`, `first`). A stop with no
current step (a clarifier call, work before the unit's first check) SHALL record the unit's phase and `first: false`.
The run SHALL end the unit with exit 10 and the exit reason `soft deadline: …`, commit only its ledger file, push the
unit branch, and record `run.finished{exit_code: 10, reason}`. No unit after it in the same run SHALL start; each is
listed as `not started: soft deadline (…)`. The next run MUST continue from the last pushed step: a red that was
committed is not done again, and a replayed held step that was stopped is replayed again from its saved patch, with no
agent, because a `held.replayed` followed by a stop of the same task and phase, with no commit of that task between
them, MUST NOT count as a replay.

#### Scenario: SCN-IMP-342 (+) The hand-back is pushed and the run exits 10
- **GIVEN** the green of SCN-IMP-335 not started
- **WHEN** the unit's run ends
- **THEN** the unit stays `implementing`, origin's unit branch holds the run's ledger with `deadline.reached` and
  `run.finished{exit_code: 10, reason: "soft deadline: …"}`, `l4 yolo status` shows no open run for it, and `l4 run`
  exits 10

#### Scenario: SCN-IMP-343 (+) The next run continues at green
- **GIVEN** the hand-back of SCN-IMP-342, after a committed and pushed red
- **WHEN** the next run runs the unit
- **THEN** it runs only the green step (no second red commit), and the task is done

#### Scenario: SCN-IMP-344 (+) No unit starts after a hand-back
- **GIVEN** three chosen units and a hand-back in the first
- **WHEN** `l4 run` goes on
- **THEN** the second and third are not started (no lease, worktree or ledger write) and are listed as `not started:
  soft deadline (…)`

#### Scenario: SCN-IMP-363 (+) A stop with no current step is recorded with the unit's phase and never counts
- **GIVEN** a unit in `clarifying` whose CLI clarifier is running when the deadline fires, with no step checked in
  the unit
- **WHEN** the deadline fires
- **THEN** `deadline.reached{when: during, during: judge, phase: clarifying, first: false}` is recorded with no task,
  the run exits 10, and the stop is not counted toward `deadline_repeated`

#### Scenario: SCN-IMP-364 (+) A stopped replay is replayed again
- **GIVEN** a person accepted the harness question of task 1.1's held green, and the run replaying its saved patch is
  stopped at the deadline in the green's test gate, after `held.replayed`
- **WHEN** the next run reaches task 1.1
- **THEN** it replays the same saved patch again (a second `held.replayed`, no agent request), and the accept takes
  effect

### Requirement: L4-IMP-070 Exactly one continuation follows the soft deadline
A run in CI with `ci.continuation: dispatch` SHALL dispatch exactly one continuation on the base when a unit was handed
back or left at the soft deadline and the run's exit code is a designed stop (10, 11, 12 or 13). On GitHub it is a
`workflow_dispatch` of `l4.yml`, and none is sent when a run is already waiting (queued, pending, waiting or
requested); the check for a waiting run MUST NOT
count the dispatching run itself, which is in progress. On GitLab it is a pipeline on the base (`POST /pipeline`), and
none is started when a pipeline of the base is already created, waiting for a resource, preparing, pending or
scheduled. When the continuation was dispatched or one is already waiting, the plan's next-run start (L4-YOLO-012) of
the same run MUST NOT be sent. When no step started in the run, no continuation and no plan next-run start SHALL be
sent, and a warning MUST name the job timeout to raise.

#### Scenario: SCN-IMP-345 (+) One dispatch for a plan unit handed back
- **GIVEN** an active plan whose current unit is handed back, in GitHub Actions
- **WHEN** the run ends
- **THEN** the forge receives exactly one `workflow_dispatch` of `l4.yml` on the base, `outcome.json` has
  `continuation: dispatched`, and `plan: next run on …` is not logged

#### Scenario: SCN-IMP-346 (+) A more severe code of another unit does not stop the continuation
- **GIVEN** two units in one run: the first parks in `awaiting_human` (11), and the second is handed back
- **WHEN** the run ends
- **THEN** one continuation is dispatched and the run exits 11

#### Scenario: SCN-IMP-347 (−) No step started, no continuation and no plan next run
- **GIVEN** an active plan, and a run whose time was used up before its first step (the job's start more than the
  usable budget ago)
- **WHEN** `l4 run` reaches the plan unit's first step
- **THEN** it is handed back, the forge receives neither a continuation nor the plan's next-run start, and a WARNING
  says `continuation: not requested: no step fitted before the soft deadline` and names `timeout-minutes`

#### Scenario: SCN-IMP-365 (+) The dispatching run itself does not block the continuation
- **GIVEN** a GitHub run handed back whose own workflow run is `in_progress` on the base, and no other run of
  `l4.yml` there
- **WHEN** the continuation is requested
- **THEN** the dispatch is sent (`dispatched`); with another run `queued` on the base, nothing is sent
  (`already_queued`)

#### Scenario: SCN-IMP-366 (+) A GitLab hand-back starts one pipeline on the base
- **GIVEN** a GitLab job whose unit is handed back, and no other pipeline of the base waiting
- **WHEN** the run ends
- **THEN** one `POST /pipeline {ref: <base>}` is sent and `outcome.json` has `continuation: dispatched`; with a
  pipeline of the base `pending`, none is sent (`already_queued`); a token that may not start one gives
  `unsupported` and a warning

### Requirement: L4-IMP-071 A step stopped at the deadline twice halts the unit
A stop (L4-IMP-068) SHALL count toward `deadline_repeated` when the step was the first step of its run, or when it
started with at least its estimate left (`left_at_start_s >= estimate_s`). The count of a task and phase SHALL start
after the last `task.red_committed`, `task.green_committed` or `task.done` of that task, and the count of a
verification round after the last `verify.verdict`; a `unit.retried`, `unit.resumed` or `unit.restarted` starts both
again. After a stop, the same task and phase (or round) SHALL start only as the first step of a run while the newest
event of that task and phase in the window is that stop; a `step.timed` of a later attempt that ran ends it. When the
count reaches 2, the unit SHALL halt with `breaker.tripped{reason: deadline_repeated, task, phase, stops: 2}`. The halt
reason MUST say that the step does not fit in one job, MUST show for both stops the time left at its start against its
estimate, and MUST name the job timeout to raise, splitting the task, and `l4 retry --unit <U> --reason TEXT`. No
continuation is dispatched for a halted unit. A
step that was not started and a stop with no current step MUST NOT count. `deadline.reached` of a stop SHALL record
`ran_s` (the seconds the step ran), `left_at_start_s`, `estimate_s` and `first`.

#### Scenario: SCN-IMP-348 (−) A green stopped twice halts the unit
- **GIVEN** a unit whose green of task 1.1 was stopped at the deadline in the last run, as that run's first step
- **WHEN** this run starts the same green as its first step and stops it at the deadline again
- **THEN** the unit is `halted` with reason `deadline_repeated`, the reason shows both stops' `left_at_start_s` against
  their `estimate_s` and names `timeout-minutes` and `l4 retry`, and no continuation is dispatched

#### Scenario: SCN-IMP-349 (+) A checkpoint between two stops resets the count
- **GIVEN** a red of task 1.1 stopped as the first step of a run, then a run that committed that red, then a run whose
  green is stopped as its first step
- **WHEN** the green is stopped
- **THEN** the unit is handed back (exit 10) and does not halt

#### Scenario: SCN-IMP-367 (+) A retry, resume or restart starts the count again; a round counts from its verdict
- **GIVEN** a green of task 1.1 stopped once as the first step of a run, then a `unit.retried` (in other cases a
  `unit.resumed` or a `unit.restarted`), then the same green stopped again as the first step of a run; and a
  verification round stopped once, then a `verify.verdict`, then the next round stopped
- **WHEN** the second stop of each case is recorded
- **THEN** no case halts the unit

#### Scenario: SCN-IMP-368 (+) After a stop the same step starts only as the first step of a run
- **GIVEN** a green of task 1.1 stopped at the last deadline, and a run in which another unit runs first
- **WHEN** the run reaches task 1.1 with more time left than the green's estimate
- **THEN** the green is not started: `deadline.reached{when: before}` with the reason `stopped at the last deadline: it
  starts only as the first step of a run`, and the next run, where it is first, starts it

### Requirement: L4-IMP-075 Failed attempts of a task count across runs
When a task starts, the run SHALL count the task's `task.attempt_failed` events of each phase and profile (of the same
fix unit, or of none) in its window, as if they had failed in this run. The window starts after the last
`task.red_committed`, `task.green_committed` or `task.done` of that task, `unit.retried`, `unit.resumed` or
`unit.restarted`. So `implementer.max_task_attempts` and `implementer.escalate_after` MUST hold across runs. A run that
hands back and continues MUST NOT give a task fresh attempts. The next attempt number SHALL continue after the highest
attempt of that phase in the window (its failures and its stops). A profile that already reached `escalate_after` for
the task's phase in the window, with a later profile in `roles.implementer`, SHALL be escalated before the task's first
attempt in this run.

#### Scenario: SCN-IMP-377 (−) A stop, then failures, then a check on time: attempts add up
- **GIVEN** a unit whose green of task 1.1 had its attempt 1 stopped at the deadline in the last run, and
  `max_task_attempts: 3`
- **WHEN** this run starts that green as its first step, the next attempt fails its gate, the attempt after it starts
  with more time left than the green's estimate and fails too, and the one after that does not fit and is handed back
- **THEN** the attempts are numbered 2 and 3 (the numbering continues after the stop), attempt 3 is not deferred as
  "stopped at the last deadline" (the failed attempt's `step.timed` ended that), and the run after it starts at
  attempt 4 with 2 failures counted, so a third failure halts the unit

#### Scenario: SCN-IMP-378 (−) Failures of earlier runs reach the attempt limit
- **GIVEN** `max_task_attempts: 3`, a green that fails after about 60 minutes on each attempt, and about 160 minutes
  usable per job
- **WHEN** run 1 fails attempts 1 and 2 and hands back attempt 3, and run 2 starts attempt 3 as its first step and it
  fails
- **THEN** run 2 halts the unit with `max_task_attempts` and `breaker.tripped{attempts: 3}`, and dispatches no
  continuation

#### Scenario: SCN-IMP-379 (+) escalate_after holds across runs
- **GIVEN** `roles.implementer: [impl, impl-b]`, `escalate_after: 2`, `max_task_attempts: 3`, and a red of task 1.1 that
  failed twice on `impl` in earlier runs
- **WHEN** this run starts task 1.1
- **THEN** `implementer.escalated{from: impl, to: impl-b}` is recorded before the first attempt, and the attempt runs on
  `impl-b` with number 3
