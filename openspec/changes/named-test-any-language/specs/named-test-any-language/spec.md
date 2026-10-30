## ADDED Requirements

### Requirement: L4-IMP-089 Red may change a named test of any language in place
A backticked `path::name` in a task's reviewed text, whose path is a tracked non-Python test file of `tdd.test_globs`
and whose name matches exactly one test of that file in the base report, SHALL let red change that test in place. The
changed test SHALL fail at red like a new red test (an assertion or `NotImplementedError`, no hang) and does not count
as a new test; one that passes at red, that fails otherwise, or that red deleted or renamed, SHALL fail the attempt, and
a task with such a change SHALL NOT end as already satisfied. A name the text used that opened nothing SHALL be recorded
as `named_tests.kept{task, token, reason}` and listed in the red prompt. The
change SHALL be recorded as `tests.superseded{reason: "named_by_task", language}`. Green SHALL NOT open the file.

### Requirement: L4-VER-068 The judge is told which named tests red changed
The judge's prompt SHALL list the named tests that red changed in place (L4-IMP-089, L4-IMP-082) with their source and,
for a test of another language, its lines at the base and at head.

#### Scenario: SCN-IMP-439 (+) a named TypeScript test is changed at red and fails
- **WHEN** the task names `` `src/api/codes.test.ts::the registry holds exactly the codes` `` and red changes its 16 to 22
- **THEN** red passes (the test fails against the code), `tests.superseded{reason: named_by_task, language: typescript}`
  names its report id, and green must make it pass

#### Scenario: SCN-IMP-440 (−) a changed named test that passes at red fails the attempt
- **WHEN** red changes the named test so that it passes against the current code
- **THEN** the attempt fails naming the test

#### Scenario: SCN-IMP-441 (−) a named test red deleted or renamed fails the attempt
- **WHEN** red removes the named test or changes its name
- **THEN** the attempt fails with `red broke existing tests`

#### Scenario: SCN-IMP-442 (−) an ambiguous or missing name is kept
- **WHEN** the name matches no test, or more than one, of that file in the base report
- **THEN** nothing is excused, the kept reason says which (a `named_tests.kept` event and the red prompt)

#### Scenario: SCN-IMP-443 (−) green does not open the file
- **WHEN** the task names the file without a test (`` `src/api/codes.test.ts` ``)
- **THEN** green may not change it, as before

#### Scenario: SCN-IMP-444 (+) step 1 still runs the rest of the file at its base version
- **WHEN** red changed the named test and another test of the same file was weakened
- **THEN** step 1 excuses only the named id and reports the other, also when the names share the text before a `[`

#### Scenario: SCN-VER-253 (+) the judge's prompt lists the changed named tests
- **WHEN** the unit has such a `tests.superseded{reason: named_by_task}`
- **THEN** the judge's prompt names the test and its source
