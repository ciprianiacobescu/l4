## Purpose

A fix unit's task, and a single-phase task of any unit, that fails on the first implementer profile moves to the next
usable profile, as red and green phases do.

## MODIFIED Requirements

### Requirement: L4-IMP-017 A task phase that fails on one profile moves to the next usable profile of the chain
(Amendment) Every phase moves: red, green and single (a chore task). The tasks of a fix unit SHALL move like the tasks
of the unit's own loop: the move selects the next usable profile with the same checks, the task runs on it in a fresh
session with the previous-attempt block, and the next task of the fix unit starts on the run's selected profile again.
The run's selected profile, and the profile that the fix loop reads, MUST NOT change.
(Removed) "The tasks of a fix unit MUST NOT move."

#### Scenario: SCN-IMP-183 (+) a fix unit's chore moves to the next profile (amended; was "(−) The tasks of a fix unit do not move")
- **WHEN** `roles.implementer: [deepseek, glm]`, `escalate_after: 2`, `max_task_attempts: 3`, and a fix unit's chore
  task fails twice on deepseek
- **THEN** `implementer.escalated{phase: single, from: deepseek, to: glm, failures: 2, attempt: 3}` is recorded, the
  third attempt runs on glm, and the run's selected profile is still deepseek

#### Scenario: SCN-IMP-420 (+) a follow-up unit's chore moves, also from failures of an earlier run
- **WHEN** a follow-up unit's chore task failed twice on deepseek in an earlier run, and a new run starts it
- **THEN** the task moves to glm before its first attempt in this run

#### Scenario: SCN-IMP-421 (+) a limit after the move cools the moved profile only
- **WHEN** after the move of SCN-IMP-183, glm's step ends on a rate limit
- **THEN** glm is cooled, deepseek is not, the attempt does not count, and the next fix task starts on deepseek

#### Scenario: SCN-IMP-422 (−) a held check neither counts nor moves
- **WHEN** a fix unit's test chore is held as inconclusive with a `harness` question on deepseek
- **THEN** no failed attempt is counted and no `implementer.escalated` is recorded
