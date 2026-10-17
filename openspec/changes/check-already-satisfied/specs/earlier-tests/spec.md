## Purpose

A red step whose task an earlier task already did reuses the tests that already prove its criteria instead of writing
copies, and the confirmation by an earlier red holds for tests that live in a class.

## ADDED Requirements

### Requirement: L4-IMP-003 An already-satisfied task reuses the tests that already prove its criteria
The confirmation by an earlier red SHALL find a test's file from its id by dropping dotted parts from the end of the
part before `::` until `<parts joined by />.py` exists in the red commit, so that the class of
`pkg.tests.test_x.TestY::test_z` does not hide `pkg/tests/test_x.py`. A path id (`tests/test_x.py::test_z`) SHALL be
used as it is.

A red step that adds no new test and changes no file SHALL be accepted as already satisfied when the result reports
`criteria_ids` and a `tdd_exemption.reason` that starts with `already_satisfied`, and every cited criterion belongs to
the unit and is confirmed. The candidates of a cited criterion SHALL be the tests of the head report that trace it and
pass. They SHALL be confirmed in the order of new tests: the earlier red, then the zero-value run, then the base run.
On success the harness SHALL tick the task, record `criterion.pre_satisfied` per criterion and `task.red_ok` and
`task.done` with `tdd: already-satisfied`, and commit `test(<unit>): <task> already satisfied` with
`L4-TDD: already-satisfied`. The commit SHALL hold no test change. The proofs SHALL be `pre_satisfied` with
`tests: []` and the confirmed tests as `discriminating`. No green step SHALL run.

A cited criterion that no passing test traces SHALL fail the step with `no test traces <ids> yet: write a new test for
each`. A cited criterion that nothing confirms SHALL fail it with the confirmation's own message. A cited id that is not
the unit's SHALL fail it as today. A step that adds no test without that reason, or without `criteria_ids`, SHALL fail
as today (`no tests added`, or `NO_NEW_TEST` when it touched a test file). A red step that adds new tests SHALL be
judged as before, and a reason SHALL stay optional there.

#### Scenario: SCN-IMP-206 (+) A test in a class is evidence of the earlier red that saw it fail
- **GIVEN** an earlier red of the unit whose discriminating test is `tests.test_old.TestTotal::test_old_total` in
  `tests/test_old.py`, unchanged and passing at head
- **WHEN** a later red step's new tests for the same criterion pass
- **THEN** the criterion is confirmed `via: earlier_red` with that test as `discriminating`, and no zero-value run
  covers it

#### Scenario: SCN-IMP-207 (+) An already-satisfied task adds no test and reuses the earlier ones
- **GIVEN** task 1.1's red wrote a test tracing criterion C that failed by assertion, and green made it pass
- **WHEN** task 2.1's red step adds no test, changes no file, and reports `criteria_ids: [C]` and
  `tdd_exemption.reason: "already_satisfied by 1.1"`
- **THEN** C is confirmed `via: earlier_red` by 1.1's test, the task is committed as `already satisfied` with no test
  file in the commit, its proof is `{tests: [], proof: pre_satisfied, discriminating: [1.1's test], via: earlier_red}`,
  and no green step runs

#### Scenario: SCN-IMP-208 (−) A cited criterion no test traces yet needs a new test
- **GIVEN** a red step that adds no test, reports `already_satisfied by 1.1` and cites a criterion no test of the head
  report traces
- **WHEN** the red step is checked
- **THEN** it fails with `no test traces <id> yet: write a new test for each`, and nothing is committed

#### Scenario: SCN-IMP-209 (−) No test and no reason is still no new test
- **GIVEN** a red step that adds no test and reports no `tdd_exemption`
- **WHEN** the red step is checked
- **THEN** it fails as before: `no tests added` when it changed nothing, the `NO_NEW_TEST` message when it touched
  a test file

#### Scenario: SCN-IMP-210 (−) Existing tests that nothing confirms are no proof
- **GIVEN** a red step that adds no test, reports `already_satisfied by 1.1`, and cites a criterion whose passing
  tests no earlier red saw fail, no zero-value run fails and no base run fails
- **WHEN** the red step is checked
- **THEN** it fails with the confirmation's `not discriminating` message, and nothing is committed
