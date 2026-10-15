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
A unit that the plan itself merged or integrated (its own ledger) is done: when the plan is admitted again (the step's
review, `l4 yolo check`, `review` and `activate` all pass the ledger state), it MUST NOT get `finished`, `unknown_unit`,
open question or intake findings, even when its change was archived or its folder is gone. It stays a unit of the graph,
so the units that depend on it resolve and treat it as integrated. A plan with no ledger state, or with nothing merged,
MUST still be refused for a merged or unknown unit. The judge MUST NOT be asked about a done unit. An excluded id that
names a change archived at the target (`<root>/changes/archive/<date>-<name>`, the rule of `scripts/validate_plan.py`)
is known.

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
`feedback.md` excluded at any depth, task checkbox markers normalised with the patterns of the Kiro and OpenSpec
providers themselves (R4). A harness tick, a verification report or a ledger line MUST NOT change the digest; a change
of a spec, requirement, design or task text MUST. The digest of a unit MUST be taken on `refs/remotes/origin/<unit branch>`
when it exists, else on the target; a revision or a folder that does not exist MUST raise, and MUST NOT give the digest
of an empty set (R3).

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
MUST make the verdict at least NEEDS_REVISION. Material that the size limits cut MUST make the verdict at least
NEEDS_REVISION, with a finding that names what was left out. A batch with no acceptance profile only groups units and
states no outcome, so a `batch_acceptance` finding on it MUST be dropped from the verdict and kept as an assumption, and
its NEEDS_REVISION MUST become READY when no blocking or major finding remains. The judge's material for a batch shows
every prerequisite of its units that is not a unit of the batch, the way the material of a unit shows its prerequisites,
and both state that a prerequisite unit of the plan is delivered and merged into the target before any unit that depends
on it starts. File names, unit ids and batch ids MUST reach the prompt only inside `<l4:data>` blocks. A judge that
times out or fails MUST record no review: the next run tries again (R9). One plan is reviewed per run.

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
Activation freezes the plan digest (`activated_digest`) with the unit digests. From then on, `plan.admitted`,
`plan.refused` and `plan.reviewed` change only the review fields, never `activated_digest`, the order or the status, and
a plan file whose digest differs from `activated_digest` MUST stop the plan with `inputs_changed` (R2).

#### Scenario: SCN-YOLO-10 (−) A plan reviewed for older inputs is refused
- **GIVEN** a plan reviewed READY, after which a person changed `spec.md` of one unit
- **WHEN** `l4 yolo activate` runs
- **THEN** it exits 2 with `review is for other inputs: run l4 yolo review <plan>`, and records nothing

#### Scenario: SCN-YOLO-11 (+) Activation freezes the inputs
- **GIVEN** a plan reviewed READY for the current digests
- **WHEN** `l4 yolo activate p1 --reason "go"` runs
- **THEN** `plan.activated{digests, limits, by, reason}` is on `refs/l4/plans/p1` and a run of the harness is started on the target

#### Scenario: SCN-YOLO-32 (−) An edited plan file stops an active plan
- **GIVEN** an active plan, and a person's push that changes its file `.l4/plans/p1.json` on the target (a unit is added)
- **WHEN** the next CI run happens
- **THEN** `plan.stopped{inputs_changed, subject: plan}` is recorded, `activated_digest` and the order do not change, and nothing is dispatched or merged

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
ancestor of the unit head, and the head to push equals the tip of the unit branch on `origin` and the head of the PR),
by pushing the unit head to the target without force. The step MUST record `unit.merge_requested` with the lease before
the push, after it has read the plan again: a cancelled or stopped plan MUST NOT merge (R5). A refused push for
`non-fast-forward` MUST send the unit to `verifying` once per attempt (`stale`); a second one, or any other refusal,
MUST stop the plan with `merge_refused` and the forge's reason. The harness MUST NOT merge any unit that is not the
current unit of an active `merge: auto` plan. When the head of the PR differs from the tip of the unit branch, the step
MUST read the PR again, up to three times, five seconds apart (a forge may show a push late), before it calls the merge
not ready, in the run that records that wait for the first time and not in a preview (`l4 run --unit`) or in a later run
while the wait for that head stands. A merge that stays not ready MUST be a wait (L4-YOLO-013).

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

#### Scenario: SCN-YOLO-33 (−) A PR whose head moved after the check is not merged
- **GIVEN** an active `merge: auto` plan whose current unit is `in_review` with a PASS, and a commit pushed to the unit branch after the PR head was read
- **WHEN** the plan step is ready to push the unit head to the target
- **THEN** the head to push is not the tip of the unit branch on `origin` and the head of the PR, nothing is pushed to the target, and the unit is not merged

#### Scenario: SCN-YOLO-17 (−) No merge without a plan
- **GIVEN** `forge.merge_policy: auto`, no active plan, and a unit `in_review` with a PASS
- **WHEN** `l4 run` and the sweep run
- **THEN** the target is not changed, and `l4 doctor` warns that `merge_policy: auto` has no effect without an active plan

### Requirement: L4-YOLO-009 Post-merge acceptance and integration
After a unit's merge into the target (by the harness or, with `merge: human`, by a person), the plan step SHALL run the
unit's acceptance profile on the merged target revision (design D9) and record `unit.integrated` only when it passes.
Every merged unit of the plan that is not integrated MUST be checked, not only the current one (R10). The profile `all`
MUST leave out the e2e gates that need an app server (`gates.e2e.serve`) and say so in the detail; a profile that names
`e2e` while `serve` is set MUST be refused at admission (`unsupported_profile`). A profile MUST pass only when at least
one required gate other than `setup` ran and passed; with no such gate it is an error, never a pass (R7). A failure MUST
stop the plan with `postcheck_failed`. With `merge: auto`, the OpenSpec archive PR of a plan unit MUST be merged by the
harness with the same guard, and only when every commit on the archive branch after the target tip is a strict harness
commit, the archive PR is open with the target as its base, and the target is `forge.base_branch` (R6). For every
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
while the plan is active; in every other plan status it waits with `held by plan <id> (<status>)`. A unit listed in a
plan file on the target MUST stay held while the file is there, whatever the status of the plan, a cancelled plan
included; only the removal of the unit from the file, or of the file, releases it. A plan file that is invalid MUST still
hold the unit ids that can be read from its JSON (`batches[].units[].id`); a file that is not JSON holds nothing, and
`l4 plan` and `l4 yolo status` MUST report it. A unit listed in two plan files MUST be a finding (`held_by_other_plan`)
for the second (R8). While a plan is active, units outside every plan MUST get no new agent work. The sweep MUST still
observe every unit.

#### Scenario: SCN-YOLO-30 (−) Specs pushed with their plan do not start on their own
- **GIVEN** one commit on the target that adds the unit folders of `a` and `b` and a plan that lists them, not yet activated
- **WHEN** the CI run for that push happens
- **THEN** the plan is admitted and reviewed, no branch of `a` or `b` is created, and `l4 plan` shows both as `held by plan p1 (reviewed)`

#### Scenario: SCN-YOLO-34 (−) A cancelled plan still holds its units
- **GIVEN** a plan that was cancelled, with its file still on the target, and a unit `a` that it lists
- **WHEN** a CI run happens and `l4 plan` runs
- **THEN** no branch of `a` is created, `l4 plan` shows `held by plan p1 (cancelled)`, and the unit is released only when it is removed from the file or the file is removed

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
on the target (`start_run`). The step, the holds and the merge-policy listing MUST read the plan files from
`origin/<forge.base_branch>` when that ref exists and the checkout is not that commit (or has a changed plan file), so
a local checkout never stops or releases a plan of the target. A named run of the current unit (`l4 run --unit`) MUST be
charged to the plan like the run of the step.

#### Scenario: SCN-YOLO-24 (+) The run after a merge is started by the harness
- **GIVEN** a CI run that merged and integrated unit `a`, with `b` waiting for it
- **WHEN** the run ends
- **THEN** it has called `start_run` on the target once, and the next run dispatches `b`

### Requirement: L4-YOLO-013 Stops, waits, cancel and resume
The plan SHALL stop, with the reason, when its current unit is `halted`, `escalated`, `abandoned` or `rejected`, when a
frozen digest changes or the plan file is edited after the activation (`inputs_changed`), when a limit is reached, when
the current unit is no longer among the units of the target (`unit_missing`, cleared when the unit is back), and as D8,
D9 and L4-YOLO-011 say. It SHALL wait, with the reason, while its current unit is `awaiting_human`, `clarifying` or
`waiting_capacity`; a waiting plan goes on by itself when the cause is gone, and `l4 yolo resume` also wakes it. A `merge: auto`
plan SHALL also wait, with the reason `merge_not_ready`, the unit and the detail (once, not again while the detail holds),
while the merge of its current unit is not ready (no open PR, a PR aimed at another branch, a PR head that is not the
branch tip); it goes on by itself when the merge is ready. A plan stopped with `unit_rejected` MUST need the cause fixed (the unit's spec, which then needs a new review, or the
configuration) and a new activation, and the step MUST NOT ask `l4 retry` to move a rejected unit; after the activation
the next run of the unit reads the corrected spec or configuration, and a unit that its run rejects again stops the plan
again. A unit that its own run rejects (exit 14, for example an empty
`gates.test.command`) has no phase to show it, so the run MUST record `unit.rejected{unit, run, detail}` on the plan
ledger when the plan dispatched the unit, and the next plan step MUST stop the plan with `unit_rejected` for that unit,
recording its spec digest, and not dispatch it again. A run of the plan's current unit that ends before the unit
started (no `run.started`: a usage error, a lease or worktree failure, a missing CLI) MUST be recorded the same way as
`unit.not_started{unit, run, exit, detail}`; the next plan step then MUST wait with the reason `unit_not_started`, the
unit and the detail, and MUST NOT start a next run, so that one trigger runs the unit once; a run that starts the unit
clears it. Outside CI the plan step MUST fetch the target branch before it
reads the plan files; when the fetch fails it MUST log one line, write nothing to the plan ledger and let no unit run while the last fetched ledger of
a plan says it is open, else hold the units the plan files list and let the units that no plan lists run. A stopped plan MUST
dispatch and merge nothing, later independent units included. `l4 yolo cancel` MUST stop new dispatch and merges for
good. `l4 yolo resume` MUST be refused while the cause is still there (design D10's table), and `inputs_changed` MUST
need a new review and activation.
At the re-activation the plan MUST keep its current unit only when the new order holds it and every prerequisite of it
under the new plan is integrated (its dependencies, the units of its prerequisite batches, those batches accepted);
else the current unit is cleared, and `plan.activated` records `current`. That unit stays a held plan unit: it goes on
when its prerequisites are integrated, by the usual rules (adopted when it is in review with a PASS, and the guarded
merge refuses a head that lacks the new target tip). The step MUST NOT choose, adopt or merge a unit whose
prerequisites are not integrated. The attempts of a unit that is no longer in the plan MUST NOT reach a limit.

#### Scenario: SCN-YOLO-25 (−) A spec push to a plan unit stops the plan
- **GIVEN** an active plan, and a person's push that changes `spec.md` of the current unit on its branch
- **WHEN** the next CI run happens
- **THEN** `plan.stopped{inputs_changed, unit}` is recorded, and the unit is neither merged nor dispatched again by the plan

#### Scenario: SCN-YOLO-26 (−) Resume is refused while the unit is still escalated
- **GIVEN** a plan stopped with `unit_escalated` and the unit still escalated
- **WHEN** `l4 yolo resume p1 --reason "x"` runs
- **THEN** it exits 2 with `resume: openspec:b is still escalated: run l4 retry --unit openspec:b first`

### Requirement: L4-YOLO-014 Plan limits are never reset
Usage (cost, runs, attempts) SHALL be charged into the plan ledger per attempt of a unit (R1): a restart starts a new
unit ledger, so the usage of the current attempt is charged as `plan.charged{unit, attempt, cost_usd, runs}`, the fold
keeps the maximum per (unit, attempt) and sums them, and the cost of the earlier attempts is kept. The attempt number
of a unit in the plan is 1 + the number of its attempt refs on `origin` less the number it had when the plan was activated
(`plan.activated{attempt_base}`), so restarts before the plan do not count; every stop writes the live charge of the
current attempt before `plan.stopped`. The cost of the review is charged as the key `plan:review`.
The limits MUST be evaluated by one implementation, with the extended deadline, for the step and for `l4 yolo resume`
(R3), and checked before every dispatch and merge. A unit restart and a plan resume MUST NOT reset the usage. More
allowance MUST be an explicit `l4 yolo resume --extend-…`, recorded. A plan file with `max_unit_attempts` below 1,
`max_cost_usd` below 0, `max_runs` below 1 or a `deadline` without a time zone MUST be refused (R12).

#### Scenario: SCN-YOLO-27 (−) A restart does not reset the plan's attempts
- **GIVEN** a plan with `max_unit_attempts: 2` and a unit restarted once
- **WHEN** the unit is restarted again
- **THEN** the plan stops with `limit_attempts` at its next step

#### Scenario: SCN-YOLO-31 (−) A restart does not reset the plan's cost or attempts
- **GIVEN** a plan with `max_unit_attempts: 2`, and a unit that used $2 in its first attempt and was restarted
- **WHEN** the unit used $1 more in its second attempt and the plan step runs
- **THEN** the plan has used $3 and 2 attempts of the unit, the cost of the first attempt is not lost, and a third attempt stops the plan with `limit_attempts`

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

### Requirement: L4-YOLO-017 Exclusions in the plan file
A plan file MAY list `exclude: [{"id": <unit id>, "reason": <text>}]`: units that this plan deliberately does not
deliver (design D15). The reason MUST be non-empty text of at most 200 characters, and unknown fields MUST be
refused. Admission MUST refuse a plan that lists the same unit in `exclude` and in a batch (`excluded_and_planned`), the
same unit twice in `exclude` (`duplicate_id`), or an excluded id that no spec provider knows and that is not a change
archived at the target (`unknown_unit`). An excluded unit MUST NOT be held by the plan: while no plan is active on the
target (for example while the plan waits for its review or its activation, or after it completes) it runs as it would
without a plan. While a plan is active it gets no new agent work, like every unit outside the active plan (L4-YOLO-010),
and `l4 yolo status` lists it under `excluded` with the reason. The exclusions are part of the plan
file, so an edit of them after the activation stops the plan (`inputs_changed`) like any other edit.

#### Scenario: SCN-YOLO-35 (+) An excluded unit is not held by the plan
- **GIVEN** a plan p1 whose file lists `kiro:pick-priority` in `exclude` with the reason `in review before the plan`
- **WHEN** a CI run looks for work while p1 is reviewed and not yet active, or after p1 completes
- **THEN** `kiro:pick-priority` runs as it would without a plan
- **WHEN** a CI run looks for work while p1 is active
- **THEN** `kiro:pick-priority` gets no new agent work (`is not in the active plan p1`), like every unit outside the active plan
- **AND** `l4 yolo status p1` lists it under `excluded` with the reason

#### Scenario: SCN-YOLO-36 (−) A unit that is both planned and excluded is refused
- **GIVEN** a plan file that lists `openspec:a` in a batch and in `exclude`
- **WHEN** `l4 yolo check p1` runs
- **THEN** it exits 2 with the finding `excluded_and_planned` for `openspec:a`, and nothing is written

### Requirement: L4-YOLO-018 `l4 yolo draft` scaffolds and updates a plan file
`l4 yolo draft <plan-id> [--target BRANCH] [--merge human|auto] [--update]` SHALL write `.l4/plans/<plan-id>.json` in
the working tree and nothing else: no commit, no push, no plan ref, no model call. Before it reads the phases of the
units it MUST fetch the base branch and the unit refs from `origin`, as the other `l4 yolo` commands do, so that a fresh
clone does not take a unit in review or merged for new work. With no `origin`, or when the fetch fails, it MUST go on
with the refs the checkout has and print one line saying that the phases may be old. Without `--update` it MUST refuse an
existing file (exit 2). It lists every unit the spec providers find in the working tree that no plan file lists
(planned or excluded) and that is not a derived unit whose parent a plan file lists. It puts each unit that is not
finished into one batch `unplanned` with no dependencies, and each finished unit (`merged`, `archived`) into `exclude`
with the reason `already <phase>`. `--target` defaults to `forge.base_branch` and `--merge` to `human`. With `--update`
the file MUST exist and be a valid plan. Units found as above are added to the batch `unplanned` (created last when
missing) or to `exclude`. A listed unit that the providers no longer find is reported as `gone: <id>` and kept.
Nothing else in the file changes. The command MUST NOT invent a dependency. It prints what it added and the next steps
(edit the dependencies and batches, run the validator, `l4 yolo check`). When the plan's local ref says it is active or
waiting, `--update` warns that the edit stops the plan.

#### Scenario: SCN-YOLO-37 (+) A draft lists every unplanned unit without dependencies
- **GIVEN** three OpenSpec changes and two Kiro specs in the working tree, one Kiro spec already merged, and no plan file
- **WHEN** `l4 yolo draft p1` runs
- **THEN** `.l4/plans/p1.json` is a valid plan with the four other units in batch `unplanned`, each with `depends_on: []`, the merged spec in `exclude` with the reason `already merged`, `target` equal to `forge.base_branch` and `merge: human`; nothing is committed

#### Scenario: SCN-YOLO-38 (+) An update adds a new spec and keeps the person's edits
- **GIVEN** a plan file p1 edited by a person (batches and dependencies), and a new OpenSpec change `openspec:z` that no plan lists
- **WHEN** `l4 yolo draft p1 --update` runs
- **THEN** `openspec:z` is appended to batch `unplanned` with no dependencies, every other batch, unit, dependency and exclusion is unchanged, and the output says `added: openspec:z`

### Requirement: L4-YOLO-019 A standalone plan validator
The harness SHALL ship `validate_plan.py`, a script that needs only the Python standard library. It is in two places,
`scripts/validate_plan.py` and `plugins/l4/skills/l4/scripts/validate_plan.py`, and the two copies MUST be byte-equal.
It reads every `.l4/plans/*.json` of a working tree and finds the units with the providers' discovery rules (design
D15). It MUST report, with the codes of admission where they are the same check:
- a plan file that is not a valid plan (schema, file name, limits);
- `duplicate_id`, `self_dependency`, `unknown_dependency`, `cycle` (on admission's graph of units and batches),
  `unknown_unit`, `excluded_and_planned`, `external_dependencies` and `empty_plan`;
- across all plan files: `uncovered`, a unit that no plan lists (planned or excluded), except a derived unit whose
  parent is listed;
- `covered_twice`, a unit listed in two plan files.

A planned unit whose OpenSpec change is archived MUST NOT fail the script, because it has no plan state and cannot tell a
unit that this plan already merged or integrated (which `l4 yolo check` accepts) from an archived unit in a fresh plan
(which `l4 yolo check` refuses as `unknown_unit`). It MUST print `finished: <id> (archived: l4 yolo check refuses it as
unknown_unit unless this plan already merged or integrated it)` and keep exit 0 when nothing else is wrong. Its reading of the configuration MUST accept a
quoted `"spec":` key and a leading byte order mark, and its verdict on a deadline MUST be that of `l4 yolo check`,
including a deadline written as a Unix time.

It exits 0 when everything is valid, 1 with one line per problem, and 2 on a usage or read error. On success it MUST
print, for each plan, its dispatch order (the same order as `l4 yolo check`) and its waves (design D15). `--json` MUST
print the same as one JSON object. The script MUST NOT write anything, use the network or run git.

#### Scenario: SCN-YOLO-39 (−) A cycle through a batch is found
- **GIVEN** a plan where batch b2 depends on batch b1, and a unit of b1 depends on a unit of b2
- **WHEN** `python3 scripts/validate_plan.py` runs
- **THEN** it exits 1 with `<plan>: cycle: …` naming the path, as `l4 yolo check` does

#### Scenario: SCN-YOLO-40 (−) A spec that no plan covers is found
- **GIVEN** two plan files, and a Kiro spec `kiro:new-report` listed in neither
- **WHEN** the validator runs
- **THEN** it exits 1 with `uncovered: kiro:new-report (add it to a plan or to a plan's exclude with a reason)`

#### Scenario: SCN-YOLO-41 (+) A valid plan prints its order and waves
- **GIVEN** a plan where D and E depend on A, B and C, F depends on D, G on E, H on F, and I and J depend on nothing
- **WHEN** the validator runs
- **THEN** it exits 0 and prints wave 1 `A, B, C, I, J`, wave 2 `D, E`, wave 3 `F, G` and wave 4 `H`, and the dispatch order of `l4 yolo check`

### Requirement: L4-YOLO-020 The skill teaches plan creation and update
The skill SHALL have the reference `plugins/l4/skills/l4/references/plan.md`, linked from `SKILL.md`, that teaches an
agent to create and update a plan from OpenSpec changes and Kiro specs (design D15). It MUST say that the agent never
activates, resumes or cancels a plan for a person, never writes `refs/l4/plans/*`, and sets `merge: auto` only when the
person asks and `forge.merge_policy` is `auto`. It MUST tell the agent to check the
state of every spec first and to exclude, with a reason a person can check, a unit that is started or in review (or to
plan it knowingly and say so), to leave `promotion` out unless the person names a branch that exists on the remote, to
put finished and deliberately left-out specs in `exclude` and not only in the hand-off message, and to keep an
integrated unit in the file after an update.

#### Scenario: SCN-YOLO-42 (+) An agent with the skill writes a valid plan
- **GIVEN** ten specs with dependencies that their proposals state, and the skill
- **WHEN** an agent is asked to plan their delivery
- **THEN** the plan file passes the validator, every dependency it lists is stated in the specs, and the agent did not activate the plan
- **AND** the agent started from `l4 yolo draft`, gave one line of evidence per dependency in the commit message, used batches for acceptance checks, excluded specs only with a reason, ran the validator and `l4 yolo check`, and committed and pushed only the plan file
- **AND** an edit of an active plan is described as stopping it until a new review and activation
