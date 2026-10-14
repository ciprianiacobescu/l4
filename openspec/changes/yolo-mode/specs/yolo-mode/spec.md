## Purpose

A person selects a batch of spec units, the order between them and the limits, reviews it, and activates it once. L4
then runs the units in dependency order. With `merge: human` people merge and L4 only orders. With `merge: auto` L4
merges each verified unit into the integration branch under a guard the git server enforces, checks it, and goes on,
until the plan is complete or something stops it. Promotion of the integration branch is never automatic.

## ADDED Requirements

### Requirement: L4-YOLO-001 The delivery plan file
A plan SHALL be the file `.l4/plans/<plan-id>.json` on the base branch, with schema `l4/delivery-plan@1` as design D1
says. The file name MUST equal `<plan-id>.json`. Unknown fields MUST be refused. `external_dependencies` that is not
empty MUST be refused with `external dependencies are not supported in this version`.

#### Scenario: SCN-YOLO-01 (−) An unknown field refuses the plan
- **GIVEN** `.l4/plans/p1.json` with a field `parallel: 3`
- **WHEN** `l4 yolo check p1` runs
- **THEN** it exits 2 and prints `p1: unknown field parallel`, and records nothing

#### Scenario: SCN-YOLO-02 (−) External dependencies are refused
- **GIVEN** a plan with one entry in `external_dependencies`
- **WHEN** `l4 yolo check` runs
- **THEN** it exits 2 with `external dependencies are not supported in this version`

### Requirement: L4-YOLO-002 Admission is deterministic
Admission SHALL check, at the target head: unique unit and batch ids; every unit known to a spec provider; every
dependency resolvable; no cycle in the graph of units and batches (design D2); known acceptance profiles;
`target == forge.base_branch`; `merge: auto` only with `forge.merge_policy: auto`; no unit with open questions; every
unit passing the existing intake checks; no unit already merged. Each failure MUST be a finding with its code. The
order MUST be topological, with ties broken by batch position, then unit position.

#### Scenario: SCN-YOLO-03 (−) A cycle through a batch prerequisite is found
- **GIVEN** batch `b2` depends on batch `b1`, and unit `a` of `b1` depends on unit `c` of `b2`
- **WHEN** `l4 yolo check` runs
- **THEN** it exits 2 with a `cycle` finding that names `a -> c -> b1 -> a`

#### Scenario: SCN-YOLO-04 (+) A valid plan prints its order
- **GIVEN** units `a`, `b` (needs `a`) in batch `b1`, and `c` (needs `b`) in batch `b2` that depends on `b1`
- **WHEN** `l4 yolo check` runs
- **THEN** it exits 0 and prints the order `a, b, c`

#### Scenario: SCN-YOLO-05 (−) A target that is not the base branch is refused
- **GIVEN** `forge.base_branch: l4/main` and a plan with `target: main`
- **WHEN** `l4 yolo check` runs
- **THEN** it exits 2 with `target_mismatch: the plan targets main, the base branch is l4/main`

### Requirement: L4-YOLO-003 Input digests ignore the harness's own writes
The digest of a unit SHALL hash the unit folder as design D3 says: `.l4/**`, `verification.md`, `questions.md` and
`feedback.md` excluded, task checkbox markers normalised. A harness tick, a verification report or a ledger line MUST
NOT change the digest; a change of a spec, requirement, design or task text MUST.

#### Scenario: SCN-YOLO-06 (+) A harness tick keeps the digest
- **GIVEN** a unit digest taken before implementation
- **WHEN** the harness ticks task 1.1 to `[x]` and writes `verification.md`
- **THEN** the digest is the same

#### Scenario: SCN-YOLO-07 (−) A changed requirement changes the digest
- **GIVEN** a frozen unit digest
- **WHEN** a person changes one sentence of `requirements.md`
- **THEN** the digest differs

### Requirement: L4-YOLO-004 Readiness review in CI
A CI run SHALL review a plan whose latest `plan.reviewed` is not for its current plan digest and unit digests: the judge
role reviews each unit and each batch with more than one unit, with the prompt and output schema of design D5, and the
result is recorded as `plan.reviewed`. An empty, unparsable or schema-invalid answer MUST be BLOCKED. A blocking finding
MUST make the verdict at least NEEDS_REVISION. One plan is reviewed per run.

#### Scenario: SCN-YOLO-08 (−) An unparsable review is BLOCKED
- **GIVEN** a plan with one unit and a judge that answers `ok`
- **WHEN** the CI step reviews it
- **THEN** `plan.reviewed` records the unit as BLOCKED with `schema_invalid`

#### Scenario: SCN-YOLO-09 (−) A blocking finding overrides READY
- **GIVEN** a judge answer `{"verdict": "READY", "findings": [{"criterion": "contradiction", "severity": "blocking", "text": "…"}]}`
- **WHEN** the review is recorded
- **THEN** the unit's verdict is NEEDS_REVISION

### Requirement: L4-YOLO-005 Activation is one person's decision
`l4 yolo activate PLAN --reason TEXT` SHALL record `plan.activated` with the frozen unit digests, the plan digest and the
limits, and then start a run on the target. It MUST be refused, with exit 2 and the cause, unless: the plan is admitted;
the latest review is for the current digests; every unit and batch is READY; `merge` and `forge.merge_policy` agree;
the target exists on `origin`; no other plan is active on the target. Nothing MUST run from a plan before activation.

#### Scenario: SCN-YOLO-10 (−) A plan reviewed for older inputs is refused
- **GIVEN** a plan reviewed READY, after which a person changed `spec.md` of one unit
- **WHEN** `l4 yolo activate` runs
- **THEN** it exits 2 with `review is for other inputs: run l4 yolo review <plan>`, and records nothing

#### Scenario: SCN-YOLO-11 (+) Activation freezes the inputs
- **GIVEN** a plan reviewed READY for the current digests
- **WHEN** `l4 yolo activate p1 --reason "go"` runs
- **THEN** `plan.activated{digests, limits, by, reason}` is on `refs/l4/plans/p1` and a run of the harness is started on the target

### Requirement: L4-YOLO-006 The plan ledger is a leased ref
Plan state SHALL be the ledger in `refs/l4/plans/<plan-id>` (design D4). Every write MUST be one commit pushed with
`--atomic` and a lease on the ref's previous value. A lost lease MUST make the writer read again and decide again; it
MUST NOT overwrite. The state MUST be a fold of the ledger alone.

#### Scenario: SCN-YOLO-12 (−) Two writers do not both win
- **GIVEN** two processes that read the plan ref at the same commit
- **WHEN** both append an event
- **THEN** one push succeeds, the other raises `PlanMoved`, and the ref holds exactly one of the two events

### Requirement: L4-YOLO-007 Bound to the target; a merged PR counts only on the base
Every plan step SHALL use `forge.base_branch` as the target and refuse a plan whose `target` differs. A missing target
MUST refuse activation and stop an active plan with `target_missing`; there is no fallback branch. For every unit, with
or without a plan, a merged PR MUST count as the unit's merge only when its destination is `forge.base_branch`; else the
unit stays `in_review` and its cause says `merged into <x>, not the base <base>`.

#### Scenario: SCN-YOLO-13 (−) A PR merged into another branch is not the unit's merge
- **GIVEN** a unit `in_review` whose PR was retargeted to `release` and merged there
- **WHEN** the sweep runs
- **THEN** the unit stays `in_review`, no archive PR is opened, and `l4 status --unit` says `merged into release, not the base l4/main`

### Requirement: L4-YOLO-008 The guarded merge
With `merge: auto`, the plan step SHALL merge a unit only when all the preconditions of design D8 hold (in review, PASS,
no open question, no person's commit after the hand-off, the PR open with the target as base, the target tip an
ancestor of the unit head), by pushing the unit head to the target without force. A refused push for
`non-fast-forward` MUST send the unit to `verifying` once per attempt (`stale`); a second one, or any other refusal,
MUST stop the plan with `merge_refused` and the forge's reason. The harness MUST NOT merge any unit that is not the
current unit of an active `merge: auto` plan.

#### Scenario: SCN-YOLO-14 (+) A verified unit is merged by a fast-forward push
- **GIVEN** an active `merge: auto` plan whose current unit is `in_review` with a PASS, and the target tip in its head
- **WHEN** the CI step runs
- **THEN** the target's tip is the unit head, `unit.merge_requested` and `unit.merged{head, pr}` are recorded, and the PR is merged on the forge

#### Scenario: SCN-YOLO-15 (−) A target that moved is not merged
- **GIVEN** the same unit, and a person's commit on the target after the verification
- **WHEN** the CI step runs
- **THEN** nothing is pushed to the target, the unit goes to `verifying` with `retry_requested`, and the plan stays active

#### Scenario: SCN-YOLO-16 (−) A protected target stops the plan
- **GIVEN** a target whose protection refuses direct pushes
- **WHEN** the merge push is refused
- **THEN** `plan.stopped{merge_refused}` records the forge's message, and no later unit is dispatched

#### Scenario: SCN-YOLO-17 (−) No merge without a plan
- **GIVEN** `forge.merge_policy: auto`, no active plan, and a unit `in_review` with a PASS
- **WHEN** `l4 run` and the sweep run
- **THEN** the target is not changed, and `l4 doctor` warns that `merge_policy: auto` has no effect without an active plan

### Requirement: L4-YOLO-009 Post-merge acceptance and integration
After a unit's merge into the target (by the harness or, with `merge: human`, by a person), the plan step SHALL run the
unit's acceptance profile on the merged target revision (design D9) and record `unit.integrated` only when it passes. A
profile with no gate to run MUST be an error, never a pass. A failure MUST stop the plan with `postcheck_failed`. With
`merge: auto`, the OpenSpec archive PR of a plan unit MUST be merged by the harness with the same guard. For every
unit, the rule "one archive PR at a time" (L4-ARC-007) MUST count only open archive PRs whose base is
`forge.base_branch`.

#### Scenario: SCN-YOLO-18 (−) A failing post-merge check stops the plan
- **GIVEN** a unit merged into the target whose `all` profile fails on the merged revision
- **WHEN** the CI step runs the profile
- **THEN** `unit.postcheck{status: fail}` and `plan.stopped{postcheck_failed}` are recorded, and the successor is not dispatched

#### Scenario: SCN-YOLO-19 (+) The archive PR of a plan unit is merged by the harness
- **GIVEN** an OpenSpec plan unit merged by the plan step, and its archive PR opened by the sweep
- **WHEN** the sweep runs again
- **THEN** the archive branch is pushed to the target as a fast-forward and the unit is archived

### Requirement: L4-YOLO-010 Dependency order
A plan unit SHALL be dispatched only when every unit it depends on, directly or through a batch prerequisite, is
integrated, and every prerequisite batch is accepted. A unit's branch MUST NOT exist before that. `l4 run --unit U` MUST
obey the same rule: a plan unit that is not eligible, or a unit outside an active plan, exits 13 before the lease, with
the reason, and writes nothing. A unit listed in a plan file on the target MUST be dispatched only by that plan's step,
while the plan is active; in every other plan status it waits with `held by plan <id> (<status>)`. While a plan is
active, units outside every plan MUST get no new agent work. The sweep MUST still observe every unit.

#### Scenario: SCN-YOLO-30 (−) Specs pushed with their plan do not start on their own
- **GIVEN** one commit on the target that adds the unit folders of `a` and `b` and a plan that lists them, not yet activated
- **WHEN** the CI run for that push happens
- **THEN** the plan is admitted and reviewed, no branch of `a` or `b` is created, and `l4 plan` shows both as `held by plan p1 (reviewed)`

#### Scenario: SCN-YOLO-20 (+) B starts only after A is integrated
- **GIVEN** an active plan with `b` depending on `a`, and `a` merged but its post-merge check not yet run
- **WHEN** a CI run happens
- **THEN** the run checks `a`, and the branch of `b` does not exist until a later run after `unit.integrated{a}`

#### Scenario: SCN-YOLO-21 (−) A direct run cannot jump the order
- **GIVEN** an active plan where `b` waits for `a`
- **WHEN** `l4 run --unit openspec:b` runs
- **THEN** it exits 13 with `run: openspec:b waits for openspec:a (not integrated) (plan p1)`, and nothing is pushed

#### Scenario: SCN-YOLO-22 (+) A human-merge plan orders without merging
- **GIVEN** an active `merge: human` plan with `b` depending on `a`, and a person merges the PR of `a` into the target
- **WHEN** the next CI runs happen
- **THEN** `a` is integrated after its profile passes, `b` is dispatched, and the harness pushes nothing to the target

### Requirement: L4-YOLO-011 Batches
When every unit of a batch is integrated, the plan step SHALL run the batch's acceptance profile on the target tip and
record `batch.accepted` or `batch.failed`. A failed batch MUST stop the plan. A batch that depends on it MUST NOT start.

#### Scenario: SCN-YOLO-23 (−) A failed batch check holds the next batch
- **GIVEN** batch `b1` with all units integrated and a profile that fails on the target tip
- **WHEN** the CI step runs
- **THEN** `batch.failed{b1}` and `plan.stopped{batch_failed}` are recorded, and no unit of `b2` is dispatched

### Requirement: L4-YOLO-012 One plan step per run, and the next run is started
A CI run SHALL make at most one plan step (design D10): one review, or one unit dispatch, or one merge with its checks,
or one batch check, or the completion. After a step that wrote a record and left work, the run MUST start the next run
on the target (`start_run`).

#### Scenario: SCN-YOLO-24 (+) The run after a merge is started by the harness
- **GIVEN** a CI run that merged and integrated unit `a`, with `b` waiting for it
- **WHEN** the run ends
- **THEN** it has called `start_run` on the target once, and the next run dispatches `b`

### Requirement: L4-YOLO-013 Stops, waits, cancel and resume
The plan SHALL stop, with the reason, when its current unit is `halted`, `escalated`, `abandoned` or `rejected`, when a
frozen digest changes (`inputs_changed`), when a limit is reached, and as D8, D9 and L4-YOLO-011 say. It SHALL wait,
with the reason, while its current unit is `awaiting_human`, `clarifying` or `waiting_capacity`. A stopped plan MUST
dispatch and merge nothing, later independent units included. `l4 yolo cancel` MUST stop new dispatch and merges for
good. `l4 yolo resume` MUST be refused while the cause is still there (design D10's table), and `inputs_changed` MUST
need a new review and activation.

#### Scenario: SCN-YOLO-25 (−) A spec push to a plan unit stops the plan
- **GIVEN** an active plan, and a person's push that changes `spec.md` of the current unit on its branch
- **WHEN** the next CI run happens
- **THEN** `plan.stopped{inputs_changed, unit}` is recorded, and the unit is neither merged nor dispatched again by the plan

#### Scenario: SCN-YOLO-26 (−) Resume is refused while the unit is still escalated
- **GIVEN** a plan stopped with `unit_escalated` and the unit still escalated
- **WHEN** `l4 yolo resume p1 --reason "x"` runs
- **THEN** it exits 2 with `resume: openspec:b is still escalated: run l4 retry --unit openspec:b first`

### Requirement: L4-YOLO-014 Plan limits are never reset
Usage (cost, runs, attempts) SHALL be charged into the plan ledger and checked before every dispatch and merge. A unit
restart and a plan resume MUST NOT reset it. More allowance MUST be an explicit `l4 yolo resume --extend-…`, recorded.

#### Scenario: SCN-YOLO-27 (−) A restart does not reset the plan's attempts
- **GIVEN** a plan with `max_unit_attempts: 2` and a unit restarted once
- **WHEN** the unit is restarted again
- **THEN** the plan stops with `limit_attempts` at its next step

### Requirement: L4-YOLO-015 Status, report, receipts, no promotion
`l4 yolo status` SHALL show the plan status, each unit's phase and what it waits for, batch results, usage against
limits, the stop reason and `Next:`. `l4 status` and `l4 plan` SHALL show the active plan and the wait reasons. On
completion and on every stop, `report.md` MUST be written to the plan ref and `.l4-out/yolo/`; it MUST state `Promotion
to <target_branch> was not performed`. Each integrated unit MUST get one receipt (design D12). The harness MUST NOT push,
open a PR or merge to the promotion target.

#### Scenario: SCN-YOLO-28 (+) The completed plan hands off
- **GIVEN** an active plan whose last unit is integrated and whose batches are accepted
- **WHEN** the CI step runs
- **THEN** `plan.completed{revision}` is recorded, `report.md` names the target revision, the units, PRs and merge commits, and says `Promotion to amaster was not performed`, and `amaster` is unchanged

### Requirement: L4-YOLO-016 Documentation
The runbook SHALL have a section on delivery plans (states, commands, every stop and how to clear it) in the style of
the existing runbook. `docs/yolo-mode.md` SHALL describe the plan file, the two merge modes and their safety rules. The
skill's operate reference SHALL list the `l4 yolo` commands.

#### Scenario: SCN-YOLO-29 (+) Every stop reason is in the runbook
- **GIVEN** the stop reasons of design D10
- **WHEN** the docs check runs
- **THEN** each reason code appears in `docs/runbook.md` with the command that clears it
