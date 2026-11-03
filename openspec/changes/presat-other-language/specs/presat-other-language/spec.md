## ADDED Requirements

### Requirement: L4-IMP-092 The pre-satisfied run does not refute a test it cannot reach
In the pre-satisfied confirmation (L4-IMP-002), a new test whose file `file_of_id` finds among the work tree's files
with an extension in `OTHER_LANGUAGES`, and that the zero-value run did not reach (its report does not hold the test as
`failed` or `error`; no run reaches it when none was made), SHALL be inconclusive with `the zero-value run varies Python
files only, and <file> is not a Python file`. A criterion SHALL then be decided by L4-IMP-060: confirmed when any of its
tests is a proof, inconclusive when none is and any is inconclusive, and not discriminating only when every one of its
tests ran and none is a proof. This SHALL hold at the exit where the zero-value scope is empty, which makes no run, and
for a criterion the zero-value run refuted. A test whose file is not found, and a Python test, SHALL keep the rules
they have. An inconclusive criterion SHALL go to the base run, and when the base run does not confirm it the task SHALL
be held with a `pre_satisfied` harness question (L4-IMP-063); it SHALL NOT be passed without an `accept`.

#### Scenario: SCN-IMP-485 (+) a TypeScript test that an earlier task satisfied is held, not refuted
- **WHEN** a red step's new test `src.durable.queue.test.ts::C-1 launch again` passes at head, the project has no Python
  module for the zero-value run to vary, and the base run errors at the unit base
- **THEN** the criterion is inconclusive with `the zero-value run varies Python files only, and
  src/durable/queue.test.ts is not a Python file`, and the task is held with a `pre_satisfied` question, not failed

#### Scenario: SCN-IMP-486 (+) a mixed criterion is inconclusive
- **WHEN** a criterion has a Python test that passed in the zero-value run and a TypeScript test that the run did not
  reach
- **THEN** the criterion is inconclusive with the TypeScript test's reason, not refuted

#### Scenario: SCN-IMP-487 (−) a test the zero-value run reached is still refuted
- **WHEN** a criterion's only test is a TypeScript test that failed by an error in the zero-value run
- **THEN** the criterion is refuted as before

#### Scenario: SCN-IMP-488 (−) Python tests and tests with no file found keep today's rules
- **WHEN** the zero-value scope is empty and a criterion's tests are Python tests, or tests whose file is not found
- **THEN** the criterion is refuted with `no project source module is imported by those tests`
