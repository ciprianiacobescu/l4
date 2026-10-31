## MODIFIED Requirements

### Requirement: L4-IMP-089 Red may change a named test of any language in place
A backticked `path::name` in a task's reviewed text, whose path is a tracked non-Python test file of `tdd.test_globs`
and whose name matches exactly one test of that file in the base report, SHALL let red change that test in place. A
named test SHALL count as changed when its own lines (`test_locate.window`) differ between the base and red, or when they
are the same, it fails at red, and its file's lines outside every test (`test_locate.outside_tests`, blank lines dropped)
differ. The changed test SHALL fail at red like a new red test (an assertion or `NotImplementedError`, no hang) and does
not count as a new test; one whose own lines changed and that passes at red, one that fails otherwise, and one that red
deleted or renamed, SHALL fail the attempt, and a task with such a change SHALL NOT end as already satisfied. A named
test that fails at red while neither its lines nor its file's shared lines changed SHALL fail the attempt as `red broke
existing tests` with a reason that says so. The named tests SHALL be recorded as `named_tests.found{task, tests, source}`
before the agent step, a name that opened nothing as `named_tests.kept{task, token, reason}`, and the change as
`tests.superseded{reason: "named_by_task", language}`. Green SHALL NOT open the file.

#### Scenario: SCN-IMP-450 (+) a shared constant of the named test's file is changed and the test fails
- **WHEN** the task names `` `src/api/codes.test.ts::the registry holds exactly the codes` ``, whose expected codes are a
  constant above the `test(...)` call, and red adds six entries to that constant only
- **THEN** red passes (the test fails by assertion against the code), `tests.superseded{reason: named_by_task, language:
  typescript}` names its report id, and green must make it pass

#### Scenario: SCN-IMP-451 (−) a red step that leaves the named test passing or its file untouched excuses nothing
- **WHEN** red only appends a new test and an import to the named test's file and the named test still passes, or red
  changes no line of the file and the named test fails
- **THEN** in the first case nothing is excused, recorded or failed for the named test; in the second the attempt fails
  with `red broke existing tests` and the reason names the test and says that red changed neither its lines nor its
  file's lines outside the tests

#### Scenario: SCN-IMP-452 (+) the tests the task names are recorded before red runs
- **WHEN** a task's reviewed text names a TypeScript test and a Python test
- **THEN** `named_tests.found{task, tests, source}` lists both, as the red prompt lists them, before the agent step

### Requirement: L4-VER-068 The judge is told which named tests red changed
The judge's prompt SHALL list the named tests that red changed in place (L4-IMP-089, L4-IMP-082) with their source and,
for a test of another language, its lines at the base and at head, or, when those are the same, its file's diff between
the base and head.

#### Scenario: SCN-VER-261 (+) the judge sees the file's diff of a named test changed through its shared lines
- **WHEN** the judge's prompt is built for a unit whose red changed a named TypeScript test only through a constant of its
  file
- **THEN** the block `Named tests changed in place` gives the file's diff between the base and head under the test, and not
  two equal copies of its lines
