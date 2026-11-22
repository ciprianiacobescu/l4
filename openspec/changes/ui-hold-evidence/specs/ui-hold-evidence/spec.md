## Purpose

Whoever answers a UI hold sees the test step 5 wrote and why it failed at the head, so a wrong test can be told from
wrong code; the writer's second attempt sees the failure too; and a behaviour that a reviewer rejects twice in one
round, as a criterion and as its UI hold, becomes one fix task.

## ADDED Requirements

### Requirement: L4-VER-083 A UI hold shows the test step 5 wrote and why it failed at the head
When step 5 ends a UI criterion with a test that the writer wrote and that was not accepted, its outcome SHALL keep a
bounded copy of the last test written: the whole code redacted (a private-key block with one marker removed to the edge,
as for L4-VER-078), then cut at the last line end before 4,000 characters (a single longer line at 4,000), then redacted
again. When that test failed at the head (`fails_at_head`), the outcome SHALL also keep an excerpt of the head run's
failure of the file's failing tests, as the retry prompt shows a failure (L4-IMP-064: per test its `E` lines, the
deepest repository frame and its location, the last location; at most 8 lines per test, 8 tests, 40 lines and 3,000
characters; paths relative to the worktree and the gate's tmp root shown as `<tmp>`; the body redacted whole before a
line is dropped and the result redacted again). The excerpt SHALL be that of the attempt that wrote the kept code (an
attempt that gives no code, a writer error, an invalid reply or `not_testable`, leaves the code and the excerpt of the
attempt before it). The file written to the trees, its hash and its removal SHALL be unchanged. `verdict.json` SHALL
store the copy as `generated[].code`, as before but redacted before the cut, and the excerpt as `generated[].excerpt`
when it is not empty; a reused round SHALL keep both, and a record without `excerpt` (0.4.59) SHALL restore with none.
The hold's verdict question (L4-VER-067) SHALL carry them in its `### Harness notes` subsection (L4-IMP-102): the
excerpt under `Harness note: why the test step 5 wrote failed at the head (redacted; paths relative to the
repository):`, each line after four spaces; then the code under `Harness note: the last test step 5 wrote, <path> (step
5 ended <status>; not committed, the file is removed after the run; at most 200 lines and 6,000 characters):`, each
line as four spaces, its number right-aligned in four columns, two spaces and the line. The numbered code SHALL be
bounded by its lines and by its own length, not only by the 4,000 characters of the raw copy (4,000 empty lines are
4,000 numbered lines): at most 200 lines and 6,000 characters with their line ends, the numbers included and before the
indent of the container; a longer copy SHALL keep its first lines (their numbers are those of the excerpt's locations)
and end with one line `… (cut: N more lines)`, which the 6,000 counts. They SHALL NOT be in the hold's text, its
title or its Context, so the hold's id, its accept binding and `question.raised` are unchanged; the Context SHALL say in
one sentence that the harness notes show the test (and why it failed at the head, when there is an excerpt). The delegate reads the notes with the Context, but the sections of the specification it is shown are picked by the title and the Context alone: the notes steer none of them.
`verification.md` SHALL have a section `## Generated UI tests that were not accepted` after the generated UI tests
table, with one list item per such outcome (criterion, status, attempts, path) and its failure and code as one block
indented by six spaces. With no written test (no attempt gave code, or `waived`) nothing SHALL be added. Every piece
SHALL pass the redactor again where it is written. The notes SHALL be redacted again when they are built (the code and the excerpt whole, cut at their bounds, whole again), so that a copy a reused round restores from a `verdict.json` of 0.4.59, which was cut before it was redacted, shows no private-key block that its cut left half there; a secret that the cut split and that no shape matches is not recoverable from such a copy.

#### Scenario: SCN-VER-331 (+) The hold's question shows the generated test and its failure at the head
- **Given** a UI criterion whose generated test `e2e/test_l4_c_<hex>.py` fails at the head with the body lines
  `>       expect(page.get_by_role("heading", name="Orders")).to_be_visible()` and `E       AssertionError: Locator
  expected to be visible` at line 19 of the file
- **When** the round raises the criterion's UI hold question
- **Then** its `### Harness notes` subsection holds both lines with the file's path relative to the repository, and the
  code with that line numbered `19`; the hold's text, the question's title and the target's `text_sha256` are those
  of 0.4.59; and the Context says that the harness notes show the test and why it failed at the head

#### Scenario: SCN-VER-332 (−) A secret in the generated test or its failure is not shown
- **Given** a generated test that holds a token-shaped value (`glpat-` followed by 20 letters and digits) that starts
  ten characters before its 4,000th character, and a failure whose message holds another one
- **When** the round writes `verdict.json` and `verification.md` and raises the hold's question
- **Then** no part of either token of 8 characters or more is in any of the three files

#### Scenario: SCN-VER-333 (+) The report and the verdict keep the evidence, and a reused round shows it again
- **Given** the round of SCN-VER-331
- **When** it writes `verification.md` and `verdict.json`, and a later round reuses it
- **Then** `verification.md` has `## Generated UI tests that were not accepted` with an item for the criterion and the
  failure and the numbered code indented by six spaces under it; `verdict.json` holds `generated[].excerpt` and the
  bounded `generated[].code`; the reused round's outcome has both; and a `verdict.json` written by 0.4.59 restores with
  no excerpt and its stored code

#### Scenario: SCN-VER-334 (−) A generated test cannot forge the structure of `questions.md`
- **Given** a generated test that fails at the head and whose lines hold `## Q-900: x`, `### Answer`, `---`, a code
  fence, `| a | b |`, `- **Status:** answered` and `<!-- write below this line -->`
- **When** its hold's question is raised and the file is read back
- **Then** the question has its usual subsections only, no line of the code is backslash-escaped, the answer is empty,
  and the notes read back are the notes written

#### Scenario: SCN-VER-335 (−) Nothing is added without a written test
- **Given** UI holds whose step 5 ended `not_testable` on its first reply, `writer_failed` before any code, and an older
  outcome with no code and no excerpt
- **When** their questions are raised and the report is written
- **Then** no question has a `### Harness notes` subsection, their Context is that of 0.4.59, and the report has no
  `## Generated UI tests that were not accepted` section

#### Scenario: SCN-VER-350 (+) A later attempt that gives no code keeps the first test and its failure together
- **Given** a first attempt whose test fails at the head with `E       AssertionError: Locator expected to be visible`,
  and a second attempt whose reply is a writer error
- **When** step 5 ends the criterion and the round raises its UI hold question
- **Then** the outcome is `writer_failed` and keeps the first test's code and its excerpt; the `### Harness notes` hold
  the failure and the first test's code, and the code's heading says that step 5 ended `writer_failed`

#### Scenario: SCN-VER-352 (−) The numbered code of a hold is bounded by its lines and its own length
- **Given** a generated test that is not accepted whose code is 4,000 empty lines, and another of 2,000 lines of one
  character
- **When** the round raises the criterion's UI hold question and writes `verification.md`
- **Then** each shows its first 200 lines numbered `1` to `200` and, after them, `… (cut: 3800 more lines)` and `…
  (cut: 1800 more lines)`; the numbered lines and the cut line are at most 6,000 characters before the container's
  indent, and the code's heading says `at most 200 lines and 6,000 characters`

### Requirement: L4-VER-084 The writer's retry after a failure at the head carries the failure
When step 5 asks the writer again after an attempt that ended `fails_at_head`, the retry reason SHALL be that
attempt's reason, then the line `Why it failed at the head:` and the excerpt of L4-VER-083, in the prompt's retry
reason data block, which is redacted with the whole prompt. Any other status SHALL keep its retry reason. The writer's
template and its version SHALL be unchanged, and a test of the second attempt SHALL be accepted only as before: it
fails at the merge base and passes at the head. A test that fails at the head only because a wait for an element timed
out SHALL stay `fails_at_head`: it is a hold either way, and a timeout is also how a missing behaviour fails.

#### Scenario: SCN-VER-336 (+) The second attempt reads why the first test failed at the head
- **Given** a first attempt whose test fails at the head with `E       AssertionError: Locator expected to be visible`
- **When** the writer is asked again
- **Then** the retry reason block of its prompt holds `the test fails at the head:` with the test's id, `Why it failed
  at the head:` and that line

#### Scenario: SCN-VER-337 (−) Other statuses keep their retry reason, and acceptance is unchanged
- **Given** a first attempt that passes at the merge base (`non_discriminating`), and a second attempt whose test
  passes at the merge base after a `fails_at_head` first attempt
- **When** step 5 runs them
- **Then** the first retry reason is `the test passes at the merge base: it does not need the new behaviour` alone, and
  the second outcome is `non_discriminating`, not accepted

### Requirement: L4-VER-085 A rejected UI hold is fixed under its criterion
A rejected UI hold's finding (L4-VER-013) SHALL cite the hold's criterion, whether it is deterministic (its reason ends
with a `WHEN … THEN …`) or the human's; its id, title, detail, severity and source SHALL be unchanged. The fix unit's
planner (L4-VER-006) SHALL then:
- when the criterion's own reject is in force in the same round, join the hold's finding to the criterion's task: one
  task that lists both findings, holds both decisions (the criterion's first), consumes both questions, and pins each
  distinct scenario once (the same text after whitespace is folded is one scenario; different texts are all kept, in
  that task; no other matching). The hold's finding SHALL NOT count as citing the criterion for the rule that gives a
  failing criterion no finding cites its own `Criterion … fails` finding;
- when the criterion has no reject in force and the hold's reason ends with a `WHEN … THEN …`, make a task that cites
  the criterion, with the scenario under the criterion's requirement (`<requirement> — regression <n>`) and named after
  the criterion's scenario (with ` (2)` and on when that name is taken), never under `Rejected hold: … — finding H-…`;
- when the criterion has no reject in force and the hold's reason has no `WHEN … THEN …`, list it as not converted, as
  before.
A criterion that is not among the family's criteria SHALL leave the hold as before. The round's verdict, which rejects
exist and what each answer settles SHALL be unchanged.

#### Scenario: SCN-VER-338 (+) A criterion and its UI hold rejected in one round are one fix task
- **Given** a FAIL round in which a reviewer rejected criterion C (Q-004) and C's UI hold (Q-005), each reason ending
  with the same `WHEN … THEN …` sentence
- **When** the fix unit is planned
- **Then** it has one task for C that lists the criterion's finding and the hold's finding, holds both decisions with
  Q-004's first, consumes Q-004 and Q-005, and its delta has one new scenario under `<C's requirement> — regression 1`

#### Scenario: SCN-VER-339 (+) Two different scenarios stay in the one task
- **Given** the round of SCN-VER-338, where Q-005's sentence differs from Q-004's by one word
- **When** the fix unit is planned
- **Then** it has one task for C with both scenarios under `<C's requirement> — regression 1`, and both questions are
  consumed

#### Scenario: SCN-VER-340 (+) A UI hold rejected alone is fixed under its criterion's requirement
- **Given** a parent with two requirements and a FAIL round in which only C's UI hold was rejected, with a `WHEN …
  THEN …` sentence
- **When** the fix unit is planned
- **Then** its task cites C, the scenario is under `<C's requirement> — regression 1` and named after C's scenario, and
  no requirement is titled `Rejected hold: … — finding H-…`

#### Scenario: SCN-VER-341 (−) A UI hold rejected alone without a scenario is still not converted
- **Given** a FAIL round in which only C's UI hold was rejected, with a reason and no `WHEN … THEN …`
- **When** the fix unit is planned
- **Then** the hold's finding cites C, it is listed as not converted, its question is not consumed, and the round goes
  on as in 0.4.59

#### Scenario: SCN-VER-342 (−) The round's verdict and findings are unchanged, also for a round 0.4.59 asked
- **Given** the round of SCN-VER-338, and a NEEDS_HUMAN round written by 0.4.59 that asked about C and C's UI hold,
  whose two questions are answered with the rejects of SCN-VER-338 after the upgrade, so that the next round reuses it
- **When** both rounds are aggregated and planned
- **Then** both verdicts are FAIL, the hold's finding keeps its id, title, severity and source and cites C, and each
  fix unit has the one task of SCN-VER-338

#### Scenario: SCN-VER-353 (−) A half private key in a record that 0.4.59 wrote is not shown
- **Given** a `verdict.json` of 0.4.59 whose generated test's code ends inside a private key (its begin marker and
  some of the body, no end marker) because its cut came before its redaction, restored by a reused round
- **When** the round raises the criterion's UI hold question
- **Then** the question's notes hold the code before the key marker, `[REDACTED:private-key]` in its place and no
  line of the key's body

#### Scenario: SCN-VER-354 (−) The harness notes pick no section of the specification the delegate reads
- **Given** a UI hold's question whose Context names `per_account` and whose harness notes hold a test that names
  `half_even`, and a design with a section for each name and a budget that holds one of them
- **When** the delegate's prompt is built, alone or in a batch
- **Then** the section of `per_account` is shown and that of `half_even` is cut, as for the same question without the
  notes; the notes are still in the question's data block, after the Context
