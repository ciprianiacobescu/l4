## Purpose

The failure text of a test that verification saw fail travels with the fix task made for it: into the fix unit's
files, the fix chore's prompt and the questions the task raises, bounded and redacted, so nobody has to reproduce a
failure that the round already recorded.

## ADDED Requirements

### Requirement: L4-VER-078 Step 3 records a bounded failure excerpt of each failing test
For each of the first 20 failed or errored tests of each gate (`test`, `e2e`) in sorted id order, the round's
`failures` record (L4-VER-069) SHALL hold an `excerpt`: the lines the retry prompt shows for that test (its `E` lines,
the deepest repository frame and its location; the message's first lines when the report holds no body), paths
relative to the worktree and the gate's tmp root shown as `<tmp>`, the body redacted whole before a line is dropped and
the result redacted again, at most 8 lines and 600 characters. A module that a report could not collect, among those
20 by its id, SHALL get the `E` lines of its collection error the same way. A record with nothing to show has no
`excerpt`. `message` and the other keys SHALL stay as they are, a reused round SHALL keep the excerpts, and readers that
do not know the key SHALL keep working.

#### Scenario: SCN-VER-308 (+) The excerpt of a failing browser test is recorded
- **Given** a round whose e2e gate fails `e2e.test_layout::test_width[chromium]` with the body lines `>       assert
  width == 1500` and `E       assert 1508 == 1500` under an absolute worktree path
- **When** step 3 writes the verdict
- **Then** its `failures` record holds `message` as before and an `excerpt` that holds both lines, the file path
  relative to the worktree, at most 8 lines and 600 characters

#### Scenario: SCN-VER-309 (−) A secret in a failure is not recorded
- **Given** a failing test whose body holds a token-shaped value (`glpat-` followed by 20 letters and digits), and a
  private-key block whose end marker lies past the eighth line
- **When** step 3 writes the verdict
- **Then** neither the token nor any line of the key block is in the `excerpt` or in `verdict.json`

#### Scenario: SCN-VER-310 (+) The excerpts are bounded per gate
- **Given** a round with 30 failing unit tests and 2 failing browser tests
- **When** step 3 writes the verdict
- **Then** the first 20 unit-test records by id and both browser records hold an `excerpt`, and the other 10 hold their
  `message` only

### Requirement: L4-IMP-102 A fix task, its prompt and its questions carry the failure text of its tests
A fix task whose findings name failing tests (`test gate failed` and `e2e gate failed`: every record of that gate;
`new tests failed` and `new tests errored`: the recorded ids its detail names) SHALL carry a failure block: each test
as `<id> (<kind>, <gate>):` with the lines of its `excerpt`, or its `message` when it has none, at most 8 tests and
6,000 characters, the rest counted. The block SHALL be written into the fix unit's `proposal.md` (OpenSpec) or
`design.md` (Kiro), indented under the finding it belongs to, and never into `tasks.md`; the fix unit SHALL still
validate. The prompt of a fix chore (kind `fix`) SHALL hold the block, read from the round that spawned the fix unit,
in a data block the context budget does not cut. Every question raised by a fix chore SHALL hold the block in its
Context as a harness note, and every question raised by an attempt that follows a failed attempt of the same task and
phase in the run SHALL hold that attempt's reason (300 characters at most) and its ledger excerpt (L4-IMP-064). These
notes SHALL come after the agent's own text and before the harness note on unfreezing or on the fix task, which stays
last. All of
it SHALL pass the redactor. With no stored round, or a round without `failures`, nothing SHALL be added.

#### Scenario: SCN-IMP-557 (+) The fix proposal shows why the test failed
- **Given** a round with `e2e gate failed` whose record of `e2e.test_layout::test_width[chromium]` has kind
  `assertion` and an excerpt that holds `assert 1508 == 1500`
- **When** the fix unit is written
- **Then** its `proposal.md` holds, under that finding, `e2e.test_layout::test_width[chromium] (assertion, e2e):` and
  `assert 1508 == 1500` on indented lines, its `tasks.md` is as before, and `openspec validate --strict` passes

#### Scenario: SCN-IMP-558 (+) The fix chore's first prompt holds the failure
- **Given** the fix unit of SCN-IMP-557 and a context budget so small that `proposal.md` is cut from the prompt
- **When** its fix chore's first step is prompted
- **Then** the prompt holds a `Failures of this task's tests` block with `assert 1508 == 1500`

#### Scenario: SCN-IMP-559 (+) The fix chore's question shows the failure to the person
- **Given** the fix chore of SCN-IMP-558, whose agent reports blocked with a technical question that holds no failure
  text
- **When** the question is raised
- **Then** its Context holds the agent's text, then the harness note with `assert 1508 == 1500`, and ends with the fix
  chore's note as before

#### Scenario: SCN-IMP-560 (+) A question after a failed attempt says why that attempt failed
- **Given** a green attempt that failed with `red tests still failing: tests.test_a::test_x` and the excerpt
  `E   assert 2 == 3`, and a next green attempt that reports blocked with a question
- **When** the question is raised
- **Then** its Context holds, after the agent's text, `Harness note: the previous attempt of this task was rejected:
  red tests still failing: tests.test_a::test_x` and a line holding `assert 2 == 3`; a question of a first attempt has
  no such note

#### Scenario: SCN-IMP-561 (−) Nothing is added without a recorded failure
- **Given** a fix unit whose spawning round is not on record, and another whose round's verdict has no `failures`
- **When** their fix chores are prompted and raise questions
- **Then** no failure block is in the prompt or the Context, and the rest of both is as before this change
