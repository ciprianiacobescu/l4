## Purpose

A fix chore is checked against the gate its finding came from, and a chore that changed nothing does not count as
done, so a broken browser test cannot be "fixed" by a no-op or by bending correct code past the browser tests.

## ADDED Requirements

### Requirement: L4-VER-069 Step 3 records why each test failed and in which gate
The verdict of a round SHALL hold a `failures` map: for each test id that failed or errored in step 3, the gate
(`test` or `e2e`), the failure kind the JUnit reader gives (`assertion`, `not_implemented`, `error`, `other`, …) and the
first line of its message, redacted and at most 200 characters. Readers of the verdict that do not know the key SHALL
keep working; the `tests` map keeps its form.

#### Scenario: SCN-VER-254 (+) The kind and gate of a failing browser test are recorded
- **GIVEN** a round whose e2e gate fails `e2e/test_a.py::test_x` with `Error: value must be a string or regular expression`
  and whose unit gate fails `tests/test_b.py::test_y` by assertion
- **WHEN** step 3 writes the verdict
- **THEN** `failures` holds `test_x` with gate `e2e`, its kind and that first line, and `test_y` with gate `test` and kind
  `assertion`; a token in a message is redacted

### Requirement: L4-IMP-090 A fix chore for a browser-test finding runs the browser tests
A fix chore (`[chore]` of a fix unit, kind `fix`) whose finding is an e2e finding (the finding of a failed e2e gate, or
failing ids that the parent round recorded under the e2e gate) SHALL, after the test gate, run `gates.build` when it is
configured and then the e2e gate with those ids as tests the report must hold and that must pass; it SHALL fail the
attempt otherwise, naming the ids. A server that is not ready SHALL fail the attempt with that reason. The test gate's
rules stay.

#### Scenario: SCN-IMP-446 (−) A no-op cannot pass a browser-test finding
- **GIVEN** a fix chore for the finding `e2e gate failed` (failing `e2e/test_a.py::test_x`)
- **WHEN** the agent's step leaves the e2e test failing
- **THEN** the attempt fails naming `test_x`, and the task is not ticked

#### Scenario: SCN-IMP-447 (+) A real fix passes
- **WHEN** the step changes the product code so that `test_x` passes in the e2e gate and the test gate has no regression
- **THEN** the task is done

#### Scenario: SCN-IMP-448 (−) The server never gets ready
- **WHEN** the e2e gate's server is not ready
- **THEN** the attempt fails with `the e2e server was not ready`, not an internal error of the run

### Requirement: L4-IMP-017 (amendment, a fix chore that changed nothing)
A fix chore attempt in which the guard put back every edit and no other file changed SHALL fail with `nothing changed:
the guard put back every edit (<paths>)`. A chore for a CI job (ci-evidence D11, D12) and a retake (`_already_done`)
SHALL keep their rules.

#### Scenario: SCN-IMP-449 (−) A put-back edit is not a done task
- **GIVEN** a fix chore whose only edit was to a frozen test file
- **WHEN** the guard puts it back
- **THEN** the attempt fails with `nothing changed: the guard put back every edit (<the test path>)`; a chore for a CI
  job with the same edit is committed as before

### Requirement: fix-unit tasks of one failure (amendment of the fix unit's candidates)
A "new tests failed" or "new tests errored" finding whose test ids are all among the failing ids of a failed gate finding
of the same round SHALL join that finding's task (one task naming both findings), not make a task of its own.

#### Scenario: SCN-VER-255 (+) One failure, one task
- **GIVEN** a round with `e2e gate failed` (failing `test_x`, `test_z`) and `new tests failed` (`test_x`, `test_z`)
- **WHEN** the fix unit is built
- **THEN** it has one chore task for both findings

#### Scenario: SCN-VER-256 (+) Different failures keep their tasks
- **WHEN** `new tests failed` names a test the gate finding does not
- **THEN** the two findings keep two tasks, as before
