## Purpose

A human reject that no fix task could be derived from ends when a feedback-only fix unit takes the person's concrete
request, so the next round judges the fixed code instead of failing on the same reject.

## ADDED Requirements

### Requirement: L4-VER-016 A feedback-only fix unit consumes the rejects its round could not convert
`effective_verdicts` SHALL drop a `reject` verdict whose `human.verdict` event is before (in ledger order) a
`fix.spawned` event with `feedback_only: true`. A `reject` recorded after that event SHALL stay in force. A
`fix.spawned` without `feedback_only: true` SHALL keep the rule that only the questions of its `consumed` list are
consumed. An `accept` SHALL NOT be changed by this rule.

When the fix loop spawns a feedback-only fix unit, the `consumed` list of its `fix.spawned` event SHALL also hold the
questions of the rejects in force that the round listed as not converted.

A hold that is raised again in a later round and has no verdict in force SHALL be asked as a new hold question.

#### Scenario: SCN-VER-64 (+) A reject before a feedback-only spawn is consumed
- **GIVEN** a ledger with `human.verdict{question: Q-004, target: H-1234abcd, decision: reject}` then `fix.spawned{feedback_only: true, consumed: []}`
- **WHEN** `effective_verdicts` reads it
- **THEN** the reject is not in force

#### Scenario: SCN-VER-65 (−) A reject after the spawn, and a spawn that is not feedback-only, keep the reject
- **GIVEN** in turn: the reject recorded after a feedback-only `fix.spawned`; the reject before a `fix.spawned` with no `feedback_only` and `consumed: []`
- **WHEN** `effective_verdicts` reads each
- **THEN** the reject is in force in both

#### Scenario: SCN-VER-66 (+) The new spawn lists the rejects it could not convert
- **GIVEN** a FAIL round whose only blocking findings are a rejected hold with no scenario (question Q-004) and a feedback item
- **WHEN** the fix loop plans and spawns the fix unit
- **THEN** the plan is feedback-only and `fix.spawned.consumed` is `["Q-004"]`

#### Scenario: SCN-VER-67 (+) The hold is asked again after the fix
- **GIVEN** the ledger of SCN-VER-64, a later round that raises the same hold, and a `questions.md` whose Q-004 is answered
- **WHEN** the verdicts are resolved and `raise_verdict_questions` runs
- **THEN** the hold has no verdict in force, no human finding is added, and a new hold question is raised
