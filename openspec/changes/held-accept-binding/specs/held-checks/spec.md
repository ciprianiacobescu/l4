## Purpose

An `accept` of a held check binds to the step the person looked at, not to whatever a later agent writes.

## ADDED Requirements

### Requirement: L4-IMP-065 A held step is kept and an accept replays it
When a step is held with a harness question, the harness SHALL save the step's changes before discarding them as a
patch at `<unit folder>/.l4/held/<task>-<check>.patch`, commit it with the questions commit, and record
`patch_sha256`, `result_sha256`, the test ids and `source_sha256` (a digest of each named test's source) in
`question.raised`. The question's Context SHALL list every path the patch changes, show the redacted source of each
named test and the redacted diff of every changed path, at most 40 lines each; a cut says that the cut lines are replayed
too and where the whole patch is. When the next run reaches the step
and an `accept` of that question is recorded, the harness SHALL NOT start an agent: it SHALL verify both digests, apply
the verified patch, run the guards, gates and checks of an agent step on it (the environment setup included), and record
`held.replayed{question, task, check, patch_sha256}`. The accept SHALL take effect only through that replay: once it is
used up (a failed gate, a refuted criterion), it covers nothing, and a later step that meets the same inconclusive check is
held again with a new question; a task reopened after the question drops it. A missing patch, a digest that differs or a patch that does not apply SHALL give no
override and a new harness question with `saved: false` that offers only `retry`. Every question records `saved`; only a
question without it keeps the old rule by test id. A step is always saved whole; the question stays within 200 KB. A replay
that leaves a path outside its patch SHALL fail as an attempt.

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

#### Scenario: SCN-IMP-327 (−) A used-up accept covers nothing
- **GIVEN** an accepted held step whose replay failed a gate, and a later agent attempt that writes a test of the same
  name with another body, or changes a helper, a conftest or a second definition
- **WHEN** the check is inconclusive again
- **THEN** the accept does not cover it and a new harness question saves and shows the new step

#### Scenario: SCN-IMP-328 (+) The question shows every change the replay applies
- **GIVEN** a held step that also wrote a support file or production code
- **WHEN** the question is raised
- **THEN** its Context lists every changed path and shows the redacted diff of every changed path
