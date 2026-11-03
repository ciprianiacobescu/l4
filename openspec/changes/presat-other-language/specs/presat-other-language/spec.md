## ADDED Requirements

### Requirement: L4-IMP-092 The pre-satisfied run does not refute a test it cannot reach
In the pre-satisfied confirmation (L4-IMP-002), a test of the confirmation (a step's new test, or an existing one the
already-satisfied path checks) whose file `file_of_id` finds among the work tree's files with an extension in
`OTHER_LANGUAGES`, and that the zero-value run did not reach (its report does not hold the test as `failed`, `error` or
`skipped`; no run reaches it when none was made), SHALL be inconclusive with `the zero-value run varies Python files
only, and <file> is not a Python file`. A criterion SHALL then be decided by L4-IMP-060: confirmed when any of its tests
is a proof, inconclusive when none is and any is inconclusive, and not discriminating only when every one of its tests
ran and none is a proof. This SHALL hold at the exit where the zero-value scope is empty, which makes no run, at the
exit where the run wrote no readable report (`zero is None`), which makes none either, and for a criterion the
zero-value run refuted. A test whose file is not found, and a Python test, SHALL keep the rules they have. An
inconclusive criterion SHALL go to the base run, and when the base run does not confirm it the task SHALL be held with a
`pre_satisfied` harness question (L4-IMP-063), unless another criterion of the step is refuted, which fails the attempt
as before; it SHALL NOT be passed without an `accept`. A test the zero-value run holds as `failed`, `error` or `skipped`
was reached. The hold's `Runs:` line names only the runs that were made, and its reason ends with the base run's outcome
for that criterion.

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

#### Scenario: SCN-IMP-489 (+) the hold shows what the base run saw
- **WHEN** a TypeScript criterion is held after a confirmation that made no zero-value run, and its new test passes
  against the unit base code too
- **THEN** the `Runs:` line names only `test-base-run`, and the reason ends with `the base run: every new test passes
  against the unit base code too`
