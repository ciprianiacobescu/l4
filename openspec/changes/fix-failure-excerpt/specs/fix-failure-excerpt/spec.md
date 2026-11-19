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
20 by its id, SHALL get the `E` lines of its collection error the same way, cut as a test's excerpt is (8 lines, then
at a line end before 600 characters). A report keeps only the last 4,000 characters of a body and the first 500 of a
message, so a private-key block can reach the excerpt with one marker only: an END marker without its BEGIN SHALL take
everything before it, and a BEGIN without its END everything after it (the shared redactor is unchanged). A record with
nothing to show has no `excerpt`. `message` and the other keys SHALL stay as they are, a reused round SHALL keep the excerpts, and readers that
do not know the key SHALL keep working. A `verdict.json` grows by at most 24,000 characters of excerpt (2 x 20 x 600;
the keys, ids and JSON around them are not counted).

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

#### Scenario: SCN-VER-311 (−) A key block with one marker is not recorded, and a collection excerpt is bounded
- **Given** a failing test whose kept body starts inside a private-key block (its END marker, no BEGIN), another whose
  message ends inside one (its BEGIN marker, no END), and a module that did not collect with 20 `E` lines in its error
- **When** step 3 writes the verdict
- **Then** no line of either key block is in the `excerpt` or in `verdict.json`, and the collection record's excerpt
  holds its first 8 lines

### Requirement: L4-IMP-102 A fix task, its prompt and its questions carry the failure text of its tests
A fix task whose findings name failing tests (`test gate failed` and `e2e gate failed`: every record of that gate;
`new tests failed` and `new tests errored`: the recorded ids its detail names) SHALL carry a failure block: each test
as `<id> (<kind>, <gate>):` with the lines of its `excerpt`, or its `message` when it has none, at most 8 tests and
6,000 characters, the rest counted. The block SHALL be written into the fix unit's `proposal.md` (OpenSpec) or
`design.md` (Kiro), after the line `Failing tests as the verifier recorded them:`, every line indented by six spaces
(OpenSpec: the finding is a list item whose content starts at column 2, so six spaces are an indented code block inside
it, where four would let a line that begins `#`, a fence or `-` be structure; Kiro: a top-level block of four spaces),
and never into `tasks.md`; the fix unit SHALL still validate. The prompt of a fix chore (kind `fix`) SHALL hold the block, read from the round that spawned the fix unit,
in a data block the context budget does not cut. Every question raised by a fix chore SHALL hold the block as a harness note, and every
question raised by an attempt that follows a failed attempt of the same task and phase in the run SHALL hold that
attempt's reason (300 characters at most, redacted before the cut and after) and its ledger excerpt (L4-IMP-064). The
notes SHALL be in their own `### Harness notes` subsection of the question, between `### Options` and the answer, and
never in its Context: what an accepted suggestion may unfreeze is judged against the question's title, Context and
Options (L4-IMP-015), and text that came from a test's output must not widen it. The Context keeps the agent's own text
and the harness note on unfreezing or on the fix task, which stays last. The clarifier and the delegate read the notes
with the Context. All of it SHALL pass the redactor. With no stored round, or a round without `failures`, nothing SHALL be added.

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
- **Then** its `### Harness notes` subsection holds the harness note with `assert 1508 == 1500`, and its Context is the
  agent's text and ends with the fix chore's note as before

#### Scenario: SCN-IMP-560 (+) A question after a failed attempt says why that attempt failed
- **Given** a green attempt that failed with `red tests still failing: tests.test_a::test_x` and the excerpt
  `E   assert 2 == 3`, and a next green attempt that reports blocked with a question
- **When** the question is raised
- **Then** its `### Harness notes` subsection holds `Harness note: the previous attempt of this task was rejected: red
  tests still failing: tests.test_a::test_x` and a line holding `assert 2 == 3`, and its Context does not; a question of
  a first attempt has no such note, and a reason with a token that straddles the 300-character cut leaves no part of it

#### Scenario: SCN-IMP-561 (−) Nothing is added without a recorded failure
- **Given** a fix unit whose spawning round is not on record, and another whose round's verdict has no `failures`
- **When** their fix chores are prompted and raise questions
- **Then** no failure block is in the prompt or the Context, and the rest of both is as before this change

#### Scenario: SCN-IMP-565 (−) A harness note never widens what an accepted suggestion unfreezes
- **Given** a question whose only mention of `tests/test_discount.py` is in the harness note about the previous
  attempt, and a suggestion `Edit tests/test_discount.py`
- **When** `l4 questions accept` lists its effects, and the green step reads the accepted question
- **Then** the effect is `unfreezes: false` (`the question does not name it`) and the file stays frozen, as when the
  note does not exist; a `###` line inside the note is escaped and cannot close its subsection
