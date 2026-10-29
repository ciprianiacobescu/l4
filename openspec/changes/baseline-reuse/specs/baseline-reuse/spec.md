## ADDED Requirements

### Requirement: L4-IMP-088 A baseline reuses the green gate run of the same tree
Within one job, a task's baseline SHALL reuse the report of the previous accepted green gate when the gate's
configuration is the same and the tree the green gate tested differs from the base's tree only in the unit's ledger,
its `tasks.md` and its held files, and SHALL record `gate.reused`. A green gate run with an extra environment (a fix
unit's coverage run), a guard restore or an environment rebuild SHALL NOT be reused, and an agent step, a discard or a
new job SHALL end the reuse.

## MODIFIED Requirements

### Requirement: L4-IMP-002 (amendment)
The base report of red check 4 and of green (b) MAY be a reused measurement (L4-IMP-088).

#### Scenario: SCN-IMP-432 (+) the second task reuses the first task's green run
- **WHEN** task 1.1 goes red then green and task 1.2 starts in the same job
- **THEN** one `baseline` gate ran in the job, and task 1.2's baseline is `gate.reused{from: test}`

#### Scenario: SCN-IMP-433 (+) a tasks.md-only commit between the tasks still reuses
- **WHEN** a commit that closes parent tasks lies between the green commit and task 1.2's base
- **THEN** the baseline is reused

#### Scenario: SCN-IMP-434 (−) a green gate that wrote a tracked file is not reused
- **WHEN** a test of the green gate writes a tracked file
- **THEN** task 1.2's baseline is measured

#### Scenario: SCN-IMP-435 (−) a fix unit's green gate is not reused
- **WHEN** the green gate ran with the fix unit's coverage environment
- **THEN** the next baseline is measured

#### Scenario: SCN-IMP-436 (−) a guard restore or a changed gate configuration is not reused
- **WHEN** a `guard.violation` was recorded during the green gate, or the gate's command changed between the tasks
- **THEN** the next baseline is measured

#### Scenario: SCN-IMP-437 (−) an agent step ends the reuse
- **WHEN** a failed green was discarded, or any agent step ran after the green gate
- **THEN** the next baseline is measured
