## Purpose

A test is followed to its file whatever the language, a held question shows each named test's own lines, and the check
of tests people or a test chore wrote rejects a test only when a run that could reach it was made.

## ADDED Requirements

### Requirement: L4-VER-050 A test the runs cannot reach is inconclusive
When tests that people or a test chore wrote are checked (`discriminate_extra`, L4-VER-009), a test that no run
accepted SHALL be inconclusive, and SHALL NOT be rejected, when its file is found among the repository's files and is a
source file of another language (an extension in `OTHER_LANGUAGES`: `.ts`, `.js`, `.go`, `.java`, `.swift`, …), and
neither run reached it by an error (it did not fail on the base, or in the zero-value run, by an error). Its reason is
`the zero-value run and the base run vary Python files only, and <file> is not a Python file`; a reason that a run
already gave for the test is kept. A file of another kind (for example a Markdown file with a pytest doctest) is decided
by the runs. When no run was made, every test not accepted SHALL be inconclusive: with `neither run could be made: …`
when nothing could be varied, and with `no run could be made: no file of the zero-value scope could be varied, and the
unit changed no Python production file` when the zero-value scope had files none of which could be varied. The check
SHALL record the names of the runs it made, and the hold of a test chore SHALL name those runs only. When a test
chore's added tests are partly rejected and partly inconclusive, the chore SHALL fail with a reason that names only the
runs made, lists only the rejected tests as passing them, and lists each inconclusive test apart with its reason.

#### Scenario: SCN-VER-243 (−) a TypeScript test in a unit that changed a Python file is held, not failed
- **WHEN** a fix unit's test chore that cites a criterion adds `src/pricing/total.test.ts` in a project whose unit
  changed the Python production file `deploy/seed.py`, and both runs are made and the test passes both
- **THEN** the test is inconclusive with `… and src/pricing/total.test.ts is not a Python file`, the task is held with a
  harness question whose `Runs:` line names the runs made, and no attempt is used

#### Scenario: SCN-VER-244 (−) no run made, no rejection
- **WHEN** the zero-value scope of a test chore has a Python file in which no function can be varied, and the unit
  changed no Python production file
- **THEN** no gate runs, the added tests are inconclusive with `no run could be made: …`, and the task is held with a
  question whose `Runs:` line is `none`

#### Scenario: SCN-VER-245 (−) a chore of one rejected and one inconclusive test fails and says which is which
- **WHEN** a test chore adds `tests/test_total.py::test_total`, which passes both runs, and `src/pricing/total.test.ts`,
  which no run can reach
- **THEN** the attempt fails; its reason lists `tests.test_total::test_total` as passing both runs and the TypeScript
  test apart as inconclusive with its reason

#### Scenario: SCN-VER-246 (+) a Python test a run makes fail is accepted as before
- **WHEN** a test chore in a project with Python and TypeScript adds a Python test that fails by assertion in the
  zero-value run
- **THEN** it is accepted with the proof `zero_value`, as before this change

### Requirement: L4-IMP-065 A held question shows the source of a test in any language
A held question's Context SHALL show, for each named test, the test's own lines when its file is found, whatever the
language. The test's file SHALL be found among the work tree's files (tracked and untracked; the files that the
harness's excludes leave out are not listed) from the id's head, in this order: (1) the head as a path; (2) the one
file whose path with dots for slashes is the head; (3) the dotted Python module; (4) the one file whose path with dots
for slashes ends with `.` and the head. When several files match at step 2 or 4, the one that the step changed SHALL be used if
exactly one of them is; otherwise no file is found. In a file that is not Python, the file SHALL be redacted whole first, and the lines SHALL run from the test
call that names the test to the line that closes it, at most 40 lines. When no file or no such line is found, the
Context SHALL say `(the source of this test was not found)`.

#### Scenario: SCN-IMP-413 (+) the question shows a TypeScript test found from a dotted id
- **WHEN** a test chore is held whose test id is `src.pricing.total.test.ts::C-0a1b2c3d total of two prices`, the step
  added `src/pricing/total.test.ts`, and the test's assertions are after the file's first 40 lines
- **THEN** the question shows that test from its `test("C-0a1b2c3d total of two prices", …)` line to its closing line,
  with its assertions, and not the next test of the file

#### Scenario: SCN-IMP-414 (−) a name in a describe block, two matching files, a missing name
- **WHEN** the test is an `it("adds", …)` inside `describe("total", …)` reported as `… ::total > adds`; or the id's
  head matches two files of which the step changed one; or the file has no line that names the test
- **THEN** the question shows the `it("adds", …)` block; the changed file is used; the question says `(the source of
  this test was not found)`
