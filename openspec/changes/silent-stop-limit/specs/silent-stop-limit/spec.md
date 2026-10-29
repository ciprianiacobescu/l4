## ADDED Requirements

### Requirement: L4-IMP-087 A silent implementer step is a limit of its profile
An implementer step that the idle watchdog stops (L4-IMP-024) before its stream reader saw any tool call SHALL be a
silent stop when `roles.implementer` lists more than one profile. A silent stop SHALL be handled as a limit of kind
`silent` (L4-AVL-006): the profile cools for `availability.default_cooldown`, its cached hello is cleared, the task
goes on on the next usable profile, and the run's selected profile moves when the silent one was the run's. It MUST NOT
count as a failed attempt. An idle stop after a tool call, a step that reaches its time limit, and an idle stop with a
single implementer profile SHALL count as before.

## MODIFIED Requirements

### Requirement: L4-IMP-024 (amendment)
An idle stop with no tool call and more than one implementer profile is a silent stop (L4-IMP-087), not a failed
attempt; `agent.idle` carries `silent`.

### Requirement: L4-IMP-017 (amendment)
A silent stop (L4-IMP-087) MUST NOT count and MUST NOT start an escalation, like a limit.

### Requirement: L4-AVL-003, L4-AVL-005, L4-AVL-006 (amendment)
`silent` is a limit kind: it cools the profile for `availability.default_cooldown` and clears its cached hello.

#### Scenario: SCN-IMP-426 (+) a silent step moves the task and the run without counting
- **WHEN** `roles.implementer: [free, glm]` and the step on `free` is stopped idle with no tool call
- **THEN** `availability.cooldown{profile: free, kind: silent}` and `availability.fallback{reason: silent}` are
  recorded, no `task.attempt_failed`, the step runs again on `glm`, and the next task starts on `glm`

#### Scenario: SCN-IMP-427 (−) an idle stop after a tool call counts as before
- **WHEN** the step made one tool call and then went idle
- **THEN** `task.attempt_failed` is recorded and no cool-down

#### Scenario: SCN-IMP-428 (−) a step that reaches its time limit counts as before
- **WHEN** the step reaches the wall-clock time limit with no tool call
- **THEN** it is a failed attempt as before

#### Scenario: SCN-IMP-429 (−) a single profile counts its silent stops
- **WHEN** `roles.implementer: [free]` and the step is stopped idle with no tool call
- **THEN** it is a failed attempt and the profile is not cooled

#### Scenario: SCN-IMP-430 (+) a silent escalated profile cools and the task moves on
- **WHEN** a task escalated to `glm` and the step on `glm` is stopped idle with no tool call, with `[free, glm, sonnet]`
- **THEN** `glm` cools and the task goes on on `sonnet` without counting

#### Scenario: SCN-IMP-431 (+) the cooled profile's hello is asked again
- **WHEN** a selection after the silent stop needs `free` again once its cool-down ended
- **THEN** the hello runs again (the cached pass was cleared)
