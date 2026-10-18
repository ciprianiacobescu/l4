## Purpose

A delivery plan pays for the runs that do work: a run in which the dispatched unit did nothing is not charged and
starts no other run, and a run in which the delegate answered starts the run that reads the answer.

## MODIFIED Requirements

### Requirement: L4-YOLO-012 One plan step per run, and the next run is started
A CI run SHALL make at most one plan step (design D10): one review, or one unit dispatch, or one merge with its checks,
or one batch check, or the completion. After a step that wrote a record and left work, the run MUST start the next run
on the target (`start_run`), except after an idle run of the unit the step let run (L4-YOLO-014): then the run MUST
NOT start the next run, and the next trigger (a person's command, the delegate's start, a push or the schedule) is the
next run. A run in which the delegate wrote an answer for a unit of the plan (L4-DLG-007) MUST start the next run once,
also when the step waited. The step, the holds and the merge-policy listing MUST read the plan files from
`origin/<forge.base_branch>` when that ref exists and the checkout is not that commit (or has a changed plan file), so
a local checkout never stops or releases a plan of the target. A named run of the current unit (`l4 run --unit`) MUST
be charged to the plan like the run of the step.

#### Scenario: SCN-DLG-48 (−) An idle run chains nothing
- **GIVEN** an active plan whose step dispatches unit A in `implementing`, and A's run finds no task it can run, makes no
  agent call and runs no gate, and parks A in `awaiting_human`
- **WHEN** the run ends
- **THEN** it records `plan.run_idle{unit: A, attempt: 1, run}` and does not start the next run

#### Scenario: SCN-DLG-49 (+) A delegate answer chains one run although the plan waited
- **GIVEN** an active plan waiting with `unit_awaiting_human` on unit A, and a run that takes the planner action
  `delegate` for A in which the delegate answers Q-004
- **WHEN** the run ends
- **THEN** it starts exactly one next run on the base

### Requirement: L4-YOLO-014 Plan limits are never reset, and idle runs are not charged
Usage (cost, runs, attempts) SHALL be charged into the plan ledger per attempt of a unit (R1): a restart starts a new
unit ledger, so the usage of the current attempt is charged as `plan.charged{unit, attempt, cost_usd, runs}`, the fold
keeps the maximum per (unit, attempt) and sums them, and the cost of the earlier attempts is kept. The attempt number
of a unit is 1 + the number of its attempt refs on `origin`. The cost of the review is charged as the key `plan:review`.
A run is *idle* for the unit the step let run when that unit's ledger of the run holds no `agent.finished` (of any
role), no `gate.finished`, and no `phase.changed` other than into `awaiting_human` or `clarifying`. After an idle run
the harness SHALL record `plan.run_idle{unit, attempt, run}` on the plan ledger with the lease, once per run, and the
fold SHALL subtract the idle runs of each (unit, attempt) from its charged runs, so that an idle run does not count
against `max_runs`. A step that dispatches nothing (no unit is eligible, or the current unit waits) MUST charge no run.
The charge of a run that did not start the unit (`unit.not_started`, L4-YOLO-013) and of a run that parked the unit in
`waiting_capacity` MUST stay. The limits MUST be evaluated by one implementation, with the extended deadline, for the
step and for `l4 yolo resume` (R3), and checked before every dispatch and merge. A unit restart and a plan resume MUST
NOT reset the usage. More allowance MUST be an explicit `l4 yolo resume --extend-…`, recorded (in `plan.resumed` from a
stop or a wait, in `plan.extended` on an active plan, by a person: L4-YOLO-050, L4-YOLO-051). A plan file with
`max_unit_attempts` below 1, `max_cost_usd` below 0, `max_runs` below 1 or a `deadline` without a time zone MUST be
refused (R12). `l4 yolo status` SHALL show the idle runs next to the runs used.

#### Scenario: SCN-DLG-50 (+) Idle runs do not reach the run limit
- **GIVEN** a plan with `max_runs: 10` whose unit A has been dispatched 12 times, of which 9 runs were idle
- **WHEN** the plan step evaluates the limits
- **THEN** the runs used are 3, no `limit_runs` stop is recorded, and `l4 yolo status` shows `runs: 3 of 10 (9 idle,
  not counted)`

#### Scenario: SCN-DLG-51 (−) A run that did work is charged
- **GIVEN** a dispatched run of unit A that makes one implementer call and then parks A in `awaiting_human`
- **WHEN** the run ends
- **THEN** no `plan.run_idle` is recorded and the run counts

#### Scenario: SCN-DLG-52 (−) Runs that did not start the unit and capacity parks stay charged
- **GIVEN** a dispatched run of A that ended before it started the unit, and another that parked A in
  `waiting_capacity` after its probes
- **WHEN** both runs end
- **THEN** neither is recorded `plan.run_idle`, and both count against `max_runs`

#### Scenario: SCN-DLG-53 (−) A step that waits charges nothing
- **GIVEN** an active plan whose current unit A waits in `awaiting_human` with no answer and no `delegate` action
- **WHEN** a scheduled run's plan step runs
- **THEN** it records at most `plan.waiting`, no `plan.charged` with more runs, and starts no next run
