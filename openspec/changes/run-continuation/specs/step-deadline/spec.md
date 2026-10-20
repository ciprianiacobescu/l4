## Purpose

When the CI job's budget is known, a run is never killed by the CI timeout. A step that cannot finish before the soft
deadline is not started, or is stopped and handed back without counting as an attempt. Exactly one continuation
follows, and a step that never fits in one job halts the unit by name.

## ADDED Requirements

### Requirement: L4-IMP-066 The soft deadline counts from the job's start
The soft deadline SHALL count from the start of the CI job. That start is `L4_JOB_STARTED_AT` when set, else GitLab's
`CI_JOB_STARTED_AT`, else the start of the run, and a value that does not parse is skipped. Both GitHub workflow
templates SHALL have, as their first step, a step named `job start` that writes `L4_JOB_STARTED_AT` (UTC, ISO 8601) to
`$GITHUB_ENV`. When a budget is known and the job's start is not, `l4 run` MUST say once, at INFO, that it counts from
the run's start and that `l4 upgrade` adds the step. `run.started` SHALL record `job_timeout_s` (the budget before the
margin) and `job_started_at` when they are known.

#### Scenario: SCN-IMP-332 (+) The job's start comes from L4_JOB_STARTED_AT
- **GIVEN** `L4_JOB_TIMEOUT_MINUTES=180`, the default 20-minute margin, and `L4_JOB_STARTED_AT` 12 minutes before
  `l4 run` starts
- **WHEN** `l4 run` computes the time left at its start
- **THEN** it is 148 minutes, not 160

#### Scenario: SCN-IMP-333 (−) Without the job's start the run's start is used and said once
- **GIVEN** `L4_JOB_TIMEOUT_MINUTES=180` and neither `L4_JOB_STARTED_AT` nor `CI_JOB_STARTED_AT`
- **WHEN** `l4 run` runs two units
- **THEN** the deadline counts from the run's start, and one INFO line says `the job's start is unknown (no
  L4_JOB_STARTED_AT)` and names `l4 upgrade`

#### Scenario: SCN-IMP-334 (+) The templates record the job's start and run.started records the budget
- **GIVEN** a configuration rendered with `l4 ci render` for GitHub, in both forms (`l4.github.yml` and the action form)
- **WHEN** the workflow is rendered and a run starts in a job with `L4_JOB_TIMEOUT_MINUTES=180` and `L4_JOB_STARTED_AT`
- **THEN** the first step is `job start` and writes `L4_JOB_STARTED_AT` to `$GITHUB_ENV`, and `run.started` has
  `job_timeout_s: 10800` and that `job_started_at`

### Requirement: L4-IMP-067 A step that does not fit is not started
Before each implementer step (red, green, a single-phase chore, also of a fix unit) and before each verification
round, `l4 run` SHALL compare the time left to the soft deadline with the step's estimate, when the deadline is known.
The estimate SHALL be the longest step of the same phase measured in this run or among the unit's last 10 recorded
`step.timed` of that phase, or, with no measure of that phase, the longest of any phase. It SHALL be at least 10
minutes and at most the agent's time limit plus `gates.timeout`. A step whose estimate exceeds the time left MUST NOT
start, and the step is handed back (L4-IMP-069). The first step of a run MUST start whenever any time is left. Every
step that starts SHALL record `step.timed{phase, task, attempt, seconds}` (a round: `round` in place of `task` and
`attempt`). With no known budget, no step is checked.

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

### Requirement: L4-IMP-068 A step still running at the soft deadline is stopped
When the soft deadline is reached, the harness SHALL send SIGINT (never SIGTERM) to the process group of every agent,
CLI judge and gate that the unit's run has running, and SIGKILL to the group 5 seconds later if it has not exited. A
process started after the deadline MUST be stopped at once. The stopped step MUST be handed back (L4-IMP-069) after
the cleanup it already does (protected paths, gate and runner configuration and the ledger put back, scratch dropped,
`agent.finished` and the reported cost recorded). The agent's `step.finished` SHALL record `status: deadline`. A stop
inside the verifier MUST NOT become a failed verification step.

#### Scenario: SCN-IMP-339 (+) An agent running at the deadline is stopped and its changes are not kept
- **GIVEN** a green agent step that has written `half.txt` and is running when the deadline fires
- **WHEN** the deadline fires
- **THEN** the agent's group gets SIGINT, then SIGKILL after 5 s when still alive; `step.finished{status: deadline}`
  and `deadline.reached{when: during, during: agent}` are recorded, no `task.attempt_failed` is recorded, and
  `half.txt` is not in any commit

#### Scenario: SCN-IMP-340 (+) A gate running at the deadline is stopped
- **GIVEN** the red step's test gate is running when the deadline fires
- **WHEN** the deadline fires
- **THEN** the gate's group is stopped, `gate.finished` is recorded, then `deadline.reached{when: during, during: gate,
  gate: test}`, and the red is not committed and not counted as a failed attempt

#### Scenario: SCN-IMP-341 (+) A CLI judge of a verification round is stopped without failing the round's step
- **GIVEN** a verification round whose CLI judge is running when the deadline fires
- **WHEN** the deadline fires
- **THEN** `deadline.reached{when: during, during: judge, phase: verify}` is recorded, no `verify.step{status:
  failed}` is recorded for the stopped step, and the unit stays `verifying`

### Requirement: L4-IMP-069 A step handed back at the soft deadline is resumed by the next run
A step handed back (not started under L4-IMP-067, or stopped under L4-IMP-068) MUST NOT count as an attempt and MUST
NOT change the unit's phase. The run SHALL record `deadline.reached`, end the unit with exit 10 and the exit reason
`soft deadline: …`, commit only its ledger file, push the unit branch, and record `run.finished{exit_code: 10, reason}`.
No unit after it in the same run SHALL start; each is listed as `not started: soft deadline (…)`. The next run MUST
continue from the last pushed step: a red that was committed is not done again.

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

### Requirement: L4-IMP-070 Exactly one continuation follows the soft deadline
A run in CI with `ci.continuation: dispatch` SHALL dispatch exactly one continuation on the base (`dispatch_continuation`)
when a unit was handed back or left at the soft deadline and the run's exit code is a designed stop (10, 11, 12 or 13).
When it was dispatched or one is already queued, the plan's next-run start (L4-YOLO-012) of the same run MUST NOT be
sent. When no step started in the run, no continuation SHALL be dispatched, and a warning MUST name the job timeout to
raise. The continuation's check for a waiting run MUST NOT count the dispatching run itself.

#### Scenario: SCN-IMP-345 (+) One dispatch for a plan unit handed back
- **GIVEN** an active plan whose current unit is handed back, in GitHub Actions
- **WHEN** the run ends
- **THEN** the forge receives exactly one `workflow_dispatch` of `l4.yml` on the base, `outcome.json` has
  `continuation: dispatched`, and `plan: next run on …` is not logged

#### Scenario: SCN-IMP-346 (+) A more severe code of another unit does not stop the continuation
- **GIVEN** two units in one run: the first parks in `awaiting_human` (11), and the second is handed back
- **WHEN** the run ends
- **THEN** one continuation is dispatched and the run exits 11

#### Scenario: SCN-IMP-347 (−) No step started, no continuation
- **GIVEN** a run whose time was used up before its first step
- **WHEN** the first step is checked
- **THEN** it is handed back, no continuation is dispatched, and a WARNING says `continuation: not requested: no step
  fitted before the soft deadline` and names `timeout-minutes`

### Requirement: L4-IMP-071 A step stopped at the deadline twice in a row halts the unit
When the same task and phase (or verification round) is stopped at the soft deadline (L4-IMP-068) twice as the first
step of its run, with no `task.red_committed`, `task.green_committed` or `task.done` of that task between the two
stops, the unit SHALL halt with `breaker.tripped{reason: deadline_repeated, task, phase, stops: 2}`. The halt reason
MUST say that the step does not fit in one job, and MUST name the job timeout to raise, splitting the task, and
`l4 retry --unit <U> --reason TEXT`. No continuation is dispatched for a halted unit. A stop of a step that was not the
first of its run, and a step that was not started, MUST NOT count. `deadline.reached` of a stop SHALL record `ran_s`
(the seconds the step ran) and `first`, and the estimate (L4-IMP-067) SHALL read `ran_s` as a measure of that phase.

#### Scenario: SCN-IMP-348 (−) A green stopped in two runs in a row halts the unit
- **GIVEN** a unit whose green of task 1.1 was stopped at the deadline in the last run, as that run's first step
- **WHEN** this run starts the same green as its first step and stops it at the deadline again
- **THEN** the unit is `halted` with reason `deadline_repeated`, the reason names `timeout-minutes` and `l4 retry`, and
  no continuation is dispatched

#### Scenario: SCN-IMP-349 (+) A late stop or a checkpoint between two stops does not halt
- **GIVEN** a red of task 1.1 stopped as the first step of a run, then a run that committed that red, then a run whose
  green is stopped; and, in a second case, a green stopped when it was not the first step of its run, then stopped
  again as the first step of the next run
- **WHEN** the last green is stopped
- **THEN** the unit is handed back (exit 10) and does not halt, and the second case's `deadline.reached` has `first:
  true` and the first one's `first: false`
