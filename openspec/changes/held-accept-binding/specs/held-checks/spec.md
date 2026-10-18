## Purpose

An `accept` of a held check binds to the step the person looked at, not to whatever a later agent writes.

## ADDED Requirements

### Requirement: L4-IMP-065 A held step is kept and an accept replays it
When a step is held with a harness question, the harness SHALL save the step's changes before discarding them as a
patch at `<unit folder>/.l4/held/<task>-<check>.patch`, commit it with the questions commit, and record
`patch_sha256` and the test ids in `question.raised`; the question's Context SHALL show the redacted source of each
named test, at most 40 lines each. When the next run reaches the step and an `accept` of that question is recorded, the
harness SHALL NOT start an agent: it SHALL verify the digest, apply the patch, run the guards, gates and checks of an
agent step on it, and record `held.replayed{question, task, check, patch_sha256}`. A missing patch, a digest that
differs or a patch that does not apply SHALL give no override and a new harness question that says why.

#### Scenario: SCN-IMP-320 (+) An accept replays the held step without an agent
- **GIVEN** a red step held with a harness question, and a second agent step that would write the test under another
  name
- **WHEN** the question is answered `accept: …` and the next run reaches the step
- **THEN** no agent runs, `held.replayed` is recorded, the override covers the tests of the patch, the task proceeds and
  the patch is deleted in the step's commit

#### Scenario: SCN-IMP-321 (−) A patch that cannot be replayed raises a new question
- **GIVEN** an accepted question whose patch is missing, whose digest differs or that does not apply
- **WHEN** the next run reaches the step
- **THEN** no override applies, no agent runs, and a new harness question names the reason

#### Scenario: SCN-IMP-322 (+) A retry drops the patch and the agent runs with the note
- **GIVEN** a held step answered `retry: …`
- **WHEN** the next run reaches the step
- **THEN** the patch is deleted in a commit and the agent step runs with the note in its prompt

#### Scenario: SCN-IMP-323 (−) The replayed changes meet the guards
- **GIVEN** a patch that writes a protected path or holds a secret
- **WHEN** it is replayed
- **THEN** the protected path is put back with `guard.violation` and the secret fails the step, as for an agent

#### Scenario: SCN-IMP-324 (−) An agent cannot write the held path
- **GIVEN** an agent step that writes `<unit folder>/.l4/held/1.1-pre_satisfied.patch`
- **WHEN** the step ends
- **THEN** the file is put back with `guard.violation`

#### Scenario: SCN-IMP-325 (+) The question shows what is accepted
- **GIVEN** a held step with a test whose source holds a token shape
- **WHEN** the question is raised
- **THEN** its Context holds the test function redacted and, when longer than 40 lines, cut with a note

#### Scenario: SCN-IMP-326 (+) A later agent step is told which tests are accepted
- **GIVEN** a task with an accepted override
- **WHEN** an agent step runs for it
- **THEN** its prompt holds a data block `accepted tests` with the ids, their source and the rule to keep them
  unchanged
