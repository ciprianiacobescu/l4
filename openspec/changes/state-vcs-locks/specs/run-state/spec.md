## Purpose

The durable record of a unit's life: per-run JSONL ledger files, the pure fold that derives `state.json`, the
lifecycle transition table, idempotent step reconciliation after a crash, and resume with budget extensions.

## ADDED Requirements

### Requirement: L4-STA-001 (part a) One ledger file per run
Each run SHALL append JSONL events only to `<unit>/.l4/ledger/<run-id>.jsonl`. Every event MUST carry `ts`, `run_id`, `unit`, `seq` and `type`. Two runs SHALL never write the same file, so merging branches cannot conflict on ledger files.

#### Scenario: SCN-STA-03 (+) One ledger file per run
- **GIVEN** two runs on the same unit, one of them on a branch later merged with the other
- **WHEN** the ledgers are merged by git
- **THEN** there is no conflict (separate files), every file starts with `run.started` and ends with `run.finished`, and `seq` is strictly increasing within each file.

### Requirement: L4-STA-001 (part b) Event type vocabulary
The ledger writer SHALL accept only the event types of L4-STA-001 (`run.started` through `run.finished`, plus `unit.resumed`, `budget.extended`, `push.rejected`, `lock.busy`, `guard.git_config`, `lessons.injected` and `lessons.curated`) and MUST reject any other `type` before writing a byte.

#### Scenario: SCN-STA-N4 (−) Unknown event type is refused
- **GIVEN** an open ledger writer
- **WHEN** a caller appends an event of type `task.finnished` (misspelled)
- **THEN** `UnknownEventType` is raised and the ledger file is byte-identical to before.

### Requirement: L4-STA-001 (part c) Run envelope and sequence
A ledger file SHALL begin with `run.started` (harness version, base and head SHA, iteration, runner id), SHALL assign `seq` as 1, 2, 3... without gaps, and SHALL end with `run.finished{exit_code}`. The writer MUST refuse appends after `run.finished`.

#### Scenario: SCN-STA-N5 (−) Append after run.finished is refused
- **GIVEN** a ledger writer that has written `run.finished`
- **WHEN** a caller appends `phase.changed`
- **THEN** `LedgerClosed` is raised and the file is unchanged.

#### Scenario: SCN-STA-N6 (+) A killed run leaves a readable ledger
- **GIVEN** a run killed by SIGKILL while writing its fifth event, leaving a torn final line
- **WHEN** the ledger is read and a new run starts
- **THEN** the torn line is skipped and reported, the four complete events are returned, and the new run writes its own new file.

### Requirement: L4-STA-002 (part a) State is a pure fold
`state.json` (`l4/state@1`) SHALL be a pure fold over all ledger files sorted by `(ts, run_id, seq)`, serialised canonically, so that `l4 status --rebuild` reproduces it byte for byte. The fold MUST NOT read the clock or any file other than ledger files.

#### Scenario: SCN-STA-01 (+) State is a pure fold
- **GIVEN** any simulation end state
- **WHEN** `l4 status --rebuild`
- **THEN** the rebuilt `state.json` equals the committed one byte for byte.

### Requirement: L4-STA-002 (part b) The ledger wins over state.json
When `state.json` differs from the fold of the ledger, the harness SHALL use the ledger-derived state, doctor STATE-001 SHALL warn, and `doctor --fix` SHALL rebuild `state.json` from the ledger.

#### Scenario: SCN-STA-02 (−) Hand-edited state loses to the ledger
- **GIVEN** `state.json` edited to `phase: verified`
- **WHEN** doctor runs
- **THEN** STATE-001 warns; `--fix` rebuilds; the run uses the ledger-derived phase.

### Requirement: L4-STA-003 (part a) Step idempotency key
The key of a step SHALL be the hex sha256 of the canonical JSON array of `(unit, step, task, base SHA, spec-files hash, prompt template version, profile)`, and the `step.started` and `step.finished` events MUST carry it.

#### Scenario: SCN-STA-N7 (+) Every key input changes the key
- **GIVEN** a reference step key
- **WHEN** exactly one of the seven inputs is changed, in turn
- **THEN** each change yields a different key, and repeating the reference inputs yields the same key.

### Requirement: L4-STA-003 (part b) Reconcile an unfinished step
A `step.started` without `step.finished` SHALL be reconciled at the next run in this order: a unit-branch commit whose `L4-Step` trailer matches the key means finished; else a WIP snapshot newer than the branch head is restored into the worktree and the step resumed; else the step is re-run.

#### Scenario: SCN-STA-N8 (+) Commit exists, step marked finished
- **GIVEN** `step.started` without `step.finished` and a branch commit with the matching `L4-Step` trailer
- **WHEN** the next run reconciles
- **THEN** the action is `MarkFinished`, a `step.finished` event is appended and the step is not re-run.

#### Scenario: SCN-STA-N9 (+) WIP newer than the head is restored
- **GIVEN** `step.started` without `step.finished`, no matching commit, and a WIP snapshot that is a descendant of the branch head
- **WHEN** the next run reconciles
- **THEN** the action is `RestoreWip` and the worktree content equals the snapshot afterwards.

#### Scenario: SCN-STA-N10 (−) Neither commit nor snapshot, step re-runs
- **GIVEN** `step.started` without `step.finished`, no matching commit and no newer WIP snapshot
- **WHEN** the next run reconciles
- **THEN** the action is `Rerun` and exactly one new `step.started` is written for that key.

#### Scenario: SCN-IMP-N21 (−) A finished step is not run twice
- **GIVEN** a ledger with `step.started` for green of task 2.1 and a green commit with `L4-Task: 2.1` already on the branch
- **WHEN** the orchestrator restarts
- **THEN** the step is marked finished without calling the agent and no second green commit exists

### Requirement: L4-STA-004 Pending ledger during review
Between hand-off commit H and the next unit-branch commit, ledger events SHALL be written to `ledger-pending/<run-id>.jsonl` in the tree of the lock-ref commits (which carry `[skip ci]`), never to the unit branch, and MUST be folded into the next unit-branch commit. The state fold SHALL read the unit branch plus the current lock ref's pending ledger.

#### Scenario: SCN-STA-N11 (+) Events after hand-off go to the lock commit
- **GIVEN** a unit in `in_review` that records phase changes and costs after H
- **WHEN** the harness writes those events
- **THEN** they appear under `ledger-pending/` in the lock commit tree, the unit branch head stays H, and the fold includes them.

#### Scenario: SCN-STA-N12 (−) Pending events are folded into the next branch commit
- **GIVEN** pending events in the lock commit and a human push that returns the unit to `implementing`
- **WHEN** the harness makes its next unit-branch commit
- **THEN** the pending file content is part of that commit and the pending file is removed from the next lock commit.

### Requirement: L4-STA-005 (part a) Lifecycle edges are a closed table
The transitions of SPEC section 12.0 SHALL be encoded as data, and `transition()` SHALL be the only code that appends `phase.changed`. A trigger that has no edge from the current phase MUST raise `IllegalTransition` and write nothing.

#### Scenario: SCN-STA-N13 (+) A legal edge writes one phase.changed
- **GIVEN** a unit in `verifying`
- **WHEN** the trigger `verify_pass` is applied
- **THEN** exactly one `phase.changed{from: verifying, to: verified}` event is appended.

#### Scenario: SCN-STA-N14 (−) An undeclared edge is refused
- **GIVEN** a unit in `intake`
- **WHEN** the trigger `verify_pass` is applied
- **THEN** `IllegalTransition` is raised and the ledger is unchanged.

### Requirement: L4-STA-005 (part b) Remembered previous phase
Entering `waiting_capacity`, `halted`, `escalated` or `abandoned` SHALL record the source phase in `previous_phase`; capacity returning, `l4 resume` and a reopened PR SHALL return the unit to that phase.

#### Scenario: SCN-STA-N15 (+) waiting_capacity returns to the previous phase
- **GIVEN** a unit that moved `fixing` to `waiting_capacity`
- **WHEN** the trigger `capacity_returned` is applied
- **THEN** the unit returns to `fixing` and `previous_phase` is cleared.

### Requirement: L4-STA-005 (part c) Run exit code per transition
Each edge SHALL carry the run exit code of the SPEC table (for example `awaiting_human` 11, `waiting_capacity` 12, `halted` and `escalated` 13, `rejected` 14, `in_review` 0), recorded in `phase.changed.exit_code` and returned to the caller.

#### Scenario: SCN-STA-N16 (+) Exit codes follow the table
- **GIVEN** edges into `awaiting_human`, `waiting_capacity`, `halted`, `rejected`
- **WHEN** each is applied
- **THEN** the returned exit codes are 11, 12, 13 and 14 respectively.

### Requirement: L4-IMP-013 (part a) Resume and budget extensions in the fold
`l4 resume` by a member SHALL append `unit.resumed{by, reason}` and optional `budget.extended{iterations, cost_usd, fix_rounds, by, reason}`, return the unit to its previous phase and reset breaker counters; the fold SHALL add extensions to the configured limits.

#### Scenario: SCN-RES-01 (+) A human resumes a breaker-halted unit
- **GIVEN** a unit `halted` by the no-progress breaker
- **WHEN** a member runs `l4 resume --unit … --reason "spec clarified"` (or sets the `l4:resume` label)
- **THEN** the unit returns to its previous phase, breaker counters reset, `unit.resumed` is in the ledger; the same label set by a non-member is ignored.

#### Scenario: SCN-RES-03 (+) Resume after the fix-round limit
- **GIVEN** a unit `escalated` after `max_fix_rounds` fix units
- **WHEN** a member runs `l4 resume --unit … --reason "one more try" --extend-fix-rounds 1`
- **THEN** the unit returns to `verifying`; one more fix unit may be created.

### Requirement: L4-IMP-013 (part b) Resume without the needed extension is refused
`l4 resume` on a unit halted for an exhausted budget, or escalated after `max_fix_rounds`, SHALL be refused with a message naming the exhausted budget unless the matching extension is given. Breaker halts need no extension.

#### Scenario: SCN-RES-02 (−) Resume without the needed extension is refused
- **GIVEN** a unit halted because `max_cost_usd_per_unit` was reached
- **WHEN** a member runs `l4 resume --unit … --reason "continue"` without `--extend-cost`
- **THEN** the command is refused naming the exhausted budget; with `--extend-cost 20` the unit resumes and the fold raises its cost limit by 20 USD.

#### Scenario: SCN-IMP-N17 (−) Resume without an extension is refused
- **GIVEN** a unit halted on `max_cost_usd_per_unit` and no `budget.extended` event
- **WHEN** a member runs `l4 resume --unit … --reason "retry"`
- **THEN** the command is refused with a message naming `max_cost_usd_per_unit` and the unit stays `halted`

### Requirement: L4-IMP-013 (part c) Budgets are ledger-counted
Budgets SHALL stay ledger-counted and MUST NOT be resettable by dispatch inputs; a run that starts with the iteration count at `max_iterations_per_unit` and no extension SHALL refuse, set `halted` and exit 13 without calling an agent.

#### Scenario: SCN-IMP-20 (−) Continuation over the iteration cap
- **GIVEN** a unit whose ledger iteration count equals `max_iterations_per_unit` (no extension recorded)
- **WHEN** a continuation (or a manual dispatch) starts `l4 run`
- **THEN** it refuses, phase `halted`, exit 13, no agent call
