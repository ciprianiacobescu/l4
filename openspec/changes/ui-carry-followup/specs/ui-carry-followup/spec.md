## Purpose

A follow-up unit is verified with its family's criteria: its own delta and the delta of the merged parent it follows. Step 5
carries a UI criterion that the unit did not change from the base (L4-VER-086) instead of holding it. Two things kept a
follow-up's UI criteria out of that carry for no good reason: the parent's criteria were read at the wording of the parent's
archived delta, not at the wording the base now holds, and a test file that the unit only added tests to counted as a file
the unit changed. A parent criterion is read at the base's wording (L4-VER-096); a test file the unit only added whole tests to
does not keep a criterion a gap (L4-VER-097 for JavaScript and TypeScript, L4-VER-098 for Python).

## ADDED Requirements

### Requirement: L4-VER-096 A follow-up reads its merged parent's criteria at the wording the base holds
`FamilyProvider.merged_parent_criteria` (the criteria of the merged unit that an OpenSpec follow-up follows,
L4-FBK-010) SHALL give each criterion of the parent's delta the text of the base's capability spec when ALL of these hold:
(a) the base holds exactly one criterion with the same id, and its framework, capability, requirement name and scenario name
are the parent criterion's (an OpenSpec id hashes those four and never the body: `criteria.criterion_id`, so the same id
means the same four, and only the body can differ); (b) its text is not empty and differs from the parent's after
`normalise`. The criterion SHALL then keep its id, alias, capability, requirement, scenario, `source_path` and `source_line`,
and its `text` SHALL be the base's. The base SHALL be the archived specs at the unit's base commit read from git
(`criteria.base_criteria_at`, the baseline of L4-VER-009 that step 4 and the red step read), and the unit's base commit SHALL
be the merge base of `refs/remotes/origin/<forge.base_branch>` and `HEAD`, read as `preconditions` reads it; for this
reading the family SHALL use the origin ref only (`unit_base_commit(..., local_fallback=False)`): with no
`refs/remotes/origin/<forge.base_branch>` no base commit is known and the parent's text stays (a local base branch that was
moved onto the unit's own head would otherwise make the unit's edit of the spec the "base"); `discrimination.unit_base`
and every other caller keep their fallback to the local base branch. A criterion SHALL keep the parent's text, word for word as before, when: the base has no criterion with that id (the
requirement or the scenario was renamed or removed on the base) or has two; the base's text equals the parent's, or is empty;
no base commit is known (also: there is no origin ref, whatever the local base branch holds) or git cannot read the specs; or the follow-up is a Kiro follow-up (a Kiro id hashes the text, so no
criterion has the same id and another text, and its baseline is the parent's own criteria). A criterion of the follow-up's own
delta SHALL never be rewritten and SHALL still win over a parent criterion with the same id (`FamilyProvider.criteria`). The
family's ids, their number and their order SHALL NOT change; the rewritten criterion is the one reading that the verifier's
steps, the judge, the test writers, the verdict questions and the red step's pass-to-pass rule all get. Step 4's pass-to-pass
rule (L4-VER-009) SHALL therefore see such a criterion as unchanged on the base, and a test that traces it and passed at the
base and at the head SHALL have the proof `pass_to_pass`. What this can lose: a follow-up that means to keep the promise the
parent wrote, which a later change on the base superseded, no longer verifies the old promise; the follow-up says it again by
a scenario of its own delta with the same requirement and scenario name, which wins. A person's accept bound to the old text
of such a criterion (`text_sha256`) is void once and asked again. [V, a consumer, three follow-up units: two parent scenarios
that a later change had reworded were `uncovered`, each raised a UI hold and a criterion verdict question, though the base held
their tests]

#### Scenario: SCN-VER-412 (+) A parent scenario that a later change reworded is read at the base's wording and carried
- **Given** a follow-up whose merged parent's archived delta holds a scenario S with the text `the journey opens /flows`,
  a base spec of the same capability whose scenario with the same requirement and scenario name reads `the journey opens
  /no-such-page-deep-link, a path no feature owns`, a web file changed by the unit, and tests that trace S, passed at the
  base and pass at the head, in files the unit did not change
- **When** the family's criteria are read and step 5 runs
- **Then** S has the id and alias it had, its `text` is the base's, `unchanged_ids` holds S, the tracing tests have the proof
  `pass_to_pass`, S is carried by L4-VER-086 (`verify.generated{status: carried}`), and no UI hold and no criterion verdict
  question is raised for it; a second case, a parent scenario that says `the plan's eight` where the base says `the nine
  calls ... the frozen calls.test.ts`, is carried the same way

#### Scenario: SCN-VER-413 (−) Nothing is rewritten when the base holds no single scenario with that id, or no readable base
- **Given** four parent scenarios: one whose requirement a later change renamed (no base scenario has its id), one whose
  base spec holds two scenarios of that name under that requirement, one whose base text equals the parent's, and one
  that is checked in a repository where git cannot read `openspec/specs` at the base commit; and a Kiro follow-up
- **When** the family's criteria are read
- **Then** every one of them has the parent's text exactly as in 0.4.61, none is carried by reason of this requirement,
  and the Kiro follow-up's criteria and baseline are unchanged

#### Scenario: SCN-VER-414 (−) The follow-up's own scenario wins and a changed one is still not carried
- **Given** a follow-up whose own delta restates scenario S of its parent under the same requirement and scenario name with
  a changed sentence (the follow-up's feedback), and a base spec that holds S at the parent's older or at a third wording
- **When** the family's criteria are read
- **Then** the criterion has the follow-up's own text, `unchanged_ids` does not hold it, and L4-VER-086 does not carry it:
  the writer is asked and an outcome that is not accepted raises its UI hold as before

#### Scenario: SCN-VER-415 (+/−) The reading is one for every reader, and an accept bound to the old text is void once
- **Given** the criterion of SCN-VER-412 and a person's accept of its criterion verdict from before the upgrade, bound to the
  parent's old text
- **When** the judge prompt, the test writer prompt, the red step's `unchanged_on_base` and the next round's verdicts read
  the family
- **Then** all of them read the base's text, the old accept is not in force (its `text_sha256` is not the text's) and the
  criterion is decided again by the round, and no other criterion's accept is touched

#### Scenario: SCN-VER-430 (−) A local base branch that moved onto the unit is no base
- **Given** a follow-up whose merged parent's scenario S the base reworded, a repository with no `refs/remotes/origin/<base>`
  and a local `<base>` branch moved onto the unit's own head, where the unit edited the base spec's wording of S
- **When** the family's criteria are read
- **Then** no base commit is known to the family, S keeps the parent's text (the unit's own edit is never read as the base's
  wording), and the red step and every other caller of `unit_base_commit` keep their fallback to the local branch

### Requirement: L4-VER-097 A test file the unit only added tests to does not keep a UI criterion a gap (JavaScript and TypeScript)
Condition 3 of L4-VER-086 (the file of every tracing test, listed or ignored, is not among the files the unit changed since
its merge base) SHALL also be met by a file F of a JavaScript or TypeScript test (its extension is one of `ts`, `tsx`, `js`,
`jsx`, `mjs`, `cjs`, `mts`, `cts`) that the unit changed, when ALL of these hold; any doubt keeps the criterion a gap: (a) `git
diff --name-status --no-renames <base> <head>` gives F as `M` (not added, deleted or renamed), `git diff --numstat` gives it
0 deleted lines (a binary file, a mode change and a line removed or changed anywhere in F fail), and both blobs are read from
git, are at most `MAX_SOURCE_BYTES` and decode as UTF-8; (b) step 1 of this round ran F at its base version on the unit's
code, which is the record of that run (`reverted`, `failing`, `not_run`, `flaky`: the fields of its `verify.base_tests` event)
listing F in `reverted`, every tracing test of F (listed or ignored, any criterion's) among the ids that PASSED in that
run (`passed`, read from the run's own report, R1, not from the event: a test the run never saw is in none of the other
lists) and none of them among its `failing`, `not_run` or `flaky` ids; a record without the list of the passed ids fails
closed; (c) with `name` the part of a test id after its first `::`, the
*block* of an OLD test in a text is what `test_locate.window` gives it, and counts only when the first line of the block is a
call line of `test`, `it`, `describe`, `suite` or `bench` whose string names the test (not the fallback of `window`, the
first line that holds the name), `window` finds it exactly once (a name carried by two calls that the enclosing
`describe` strings do not tell apart is not found), and the block is *closed* (its `(`, `{` and `[` balance, with strings,
template literals and comments skipped, and no count is negative); the *block* of a NEW test is exactly one plain test
statement (a scanner that reads the file once, `carry_appended._plain_calls`): one expression statement that starts its line,
outside every string, template literal and comment, directly in the file or in a `{` block, after a `;`, a `{`, a `}` or a `)`
that does not close the head of an `if`, `for`, `while`, `switch`, `with` or `catch`, of the form `it(` or `test(` (never
`describe`, `suite`, `bench`, a hook, `.each`, `.only`, `.skip` or `.todo`, which are all refused), whose first argument
is one string literal (quotes, or a backtick template with no `${`) and whose second is a function literal (`() => {`,
`async () => {`, `function (`, `async function (`, `name => {`) with at most one parameter, a name or a destructuring pattern
with an optional type and no default value, an optional third argument that is a number (the timeout) and an optional trailing
comma, and whose closing `)` ends its last line, followed only by an optional `;`, whitespace and a `//` comment (with no `;`,
the next code character does not continue the statement: not one of `(`, `[`, a backtick, `.`, `,` or an operator); the block is
the lines from that statement's first to its last, and the title of a describe, whatever it says, never starts a block; (d) let
H be the names of the tests of F in the
step-3 reports at the head (the unit gate's and the end-to-end gate's, `test_locate.test_names_of`, which moved there from `tdd`), OLD the names of H that have
a block at the base and NEW the names of H that are not in OLD and have a block at the head, found once (one plain statement
carries the longest string that names the name, and it is not a line of an OLD block): every tracing test of F is in
OLD (its title is still at the base); every name of OLD has a block at the head that is the very text of its block at the
base, so no line was added inside any old test, the traced ones included; and the lines of the base outside the blocks of
OLD equal the lines of the head outside the blocks of OLD and NEW, blank lines dropped, so that
what the unit added to F is whole new tests (a hook, an import, a constant, a `describe` wrapper, a `vi.mock`, a statement on the same line as
a test, a test whose arguments run code when the file is collected or any other line outside a test is not a new test and fails
the rule). Both texts are read once, whatever the number of tests (the names are looked up in an index of the file, so a file
of some thousands of tests is decided in seconds). A criterion SHALL be carried by L4-VER-086 when each file of each
of its tracing tests is either not changed by the unit or meets this requirement (or L4-VER-098), and its other conditions
(the criterion unchanged on the base, every tracing test passed with the proof `pass_to_pass`, nobody rejected it) hold as
before; a file that is changed and neither is a gap. A language other than JavaScript, TypeScript and Python SHALL keep the
file-level rule. The carried criterion's row of the generated UI tests table SHALL name each such file (`the unit only added
tests to <file>`), `verify.generated{status: carried}` SHALL carry the optional list `appended` of those files, and nothing else
of 0.4.60's carry changes: a carry passes nothing, a reused round keeps the stored outcome, and a rejected criterion is never
carried. What this can lose is in `design.md` D3; the run of the base's file on the unit's code (b) and the run of the head's
file at step 3 are the evidence that neither the traced tests nor the new ones broke the other. [V for the file's evidence, a consumer: a unit changed one test file by adding one new test (the file's
trace holds fifteen old tests with the proof `pass_to_pass` and that one new test with a plain string title and a red proof),
and the two UI criteria that its old tests traced stayed holds because the file was a changed file; the step-1 record listed
the file in `reverted` with empty `failing` and `not_run`. [V, the diff of that unit: one whole new top-level `test(...)` block of 11 added lines between two existing top-level statements, with no import, no hook and no other change, which this rule accepts]

#### Scenario: SCN-VER-416 (+) One test appended to a changed test file carries the criteria the file traces
- **Given** a follow-up with two unchanged UI criteria C1, C2, each traced only by passing `pass_to_pass` tests of one TypeScript
  file F that the unit changed by adding one 11-line `it(...)` block with a plain string title, at the end of F or between two
  old tests, and nothing else (+11/-0), F listed in `reverted` by step 1 of the round with an empty `failing` and `not_run`,
  and the other conditions of L4-VER-086
- **When** step 5 runs
- **Then** C1 and C2 are carried (`status: carried`, `appended: [F]`), their rows say `the unit only added tests to F`, no writer
  call and no hold is raised for them, and when F's new test also has its own criterion that is a gap, only that one goes to
  the writer

#### Scenario: SCN-VER-417 (−) A line deleted or changed anywhere in the file keeps the hold
- **Given** SCN-VER-416 where the unit also changed one assertion of an old test that C1 does not trace, or deleted a blank
  line, a comment or an import line (-1 line, whatever it is)
- **When** step 5 runs
- **Then** neither C1 nor C2 is carried and each follows 0.4.61 (the writer, then a hold)

#### Scenario: SCN-VER-418 (−) A line added inside an old test, a traced one or not, keeps the hold
- **Given** SCN-VER-416 where the unit added one line inside the body of the traced test (+1/-0), or inside another old
  test of F, or a new `it(...)` block nested inside an old test
- **When** step 5 runs
- **Then** the block of that old test differs between the base and the head, the rule fails, and the criteria F traces are gaps

#### Scenario: SCN-VER-419 (−) An added line that is not a whole new test keeps the hold
- **Given** SCN-VER-416 with, instead of the new test, one of: a `beforeEach` or `afterAll` hook, a new import, a new
  constant or helper, a `vi.mock(...)` call, a new `describe` block that holds the new test, a new test whose title is
  a template literal with `${...}` or an `.each` table that the report names differently from its source text
- **When** step 5 runs
- **Then** the lines outside the blocks differ between the base and the head (or a new test has no block), the rule fails,
  and the criteria F traces are gaps

#### Scenario: SCN-VER-420 (−) A traced test whose block cannot be found once on each side keeps the hold
- **Given** SCN-VER-416 where one of: the new test has the same title as the traced one (two calls carry the name), the
  traced test is declared by `it.each` or with a template-literal title, the file does not close its brackets (an unbalanced
  string, JSX text with an apostrophe), or the traced test's first line is not a call line (`window`'s fallback)
- **When** step 5 runs
- **Then** the traced test is not in OLD, the rule fails closed, and the criteria F traces are gaps

#### Scenario: SCN-VER-421 (−) The base's file was not run on the unit's code, or its traced test did not pass there
- **Given** SCN-VER-416 where F is not in the `reverted` list of step 1's run of the round (it was kept at head because
  a person's commit changed it last, step 1 did not run, or F is outside `tdd.test_globs`), or a tracing test of F is in the
  event's `failing`, `not_run` or `flaky` or not among the ids that passed in that run (SCN-VER-429)
- **When** step 5 runs
- **Then** the rule fails and the criteria F traces are gaps, whatever the text of F says

#### Scenario: SCN-VER-422 (−) A file that is added, renamed, deleted, binary, oversized or of another language keeps the file-level rule
- **Given** the tests of SCN-VER-416 in a file that the unit renamed (so the path at the head is an addition), or whose blob
  is over `MAX_SOURCE_BYTES`, or a Go, Java or C# test file that the unit changed by adding one test
- **When** step 5 runs
- **Then** the criteria are gaps as in 0.4.61

#### Scenario: SCN-VER-423 (+/−) The other conditions of L4-VER-086 still decide, file by file
- **Given** SCN-VER-416 where C1 is also traced by a test in a second changed file that fails the rule, C2 has a tracing
  test whose proof is red, C3 is rejected by a person, and C4's scenario text differs from the base's
- **When** step 5 runs
- **Then** none of C1, C2, C3 and C4 is carried, and each one's outcome is what 0.4.61 gives it

#### Scenario: SCN-VER-427 (−) A new block that is more than one plain `it(` or `test(` statement keeps the hold
- **Given** SCN-VER-416 where the new test is written as one of: `it("t", () => {}); beforeEach(() => { counter = 5; });` on one
  line (or `vi.mock(...)`, or an assignment, after the call on its line, or a statement before it), a multi-line test whose
  closing line goes on with a hook that closes later, a `describe` whose title is the new test's and that holds a hook and the
  test, a test whose arguments run code when the file is collected (`it("t", (counter = 7, () => {}))`, an immediately
  called function as the second argument, a parameter with a default value), `it.only`, `it.skip`, `test.todo`, an
  `.each` table, a title that is not one string literal, a body that is not a function block, a second argument that is not a
  function literal, an options object, a statement that the next line goes on with (`(`, `.`), a test that is the argument or
  the body of another statement, or one inside a template literal or a comment
- **When** step 5 runs
- **Then** the block is not a plain test statement, its lines are outside every block and differ from the base's (or the
  rule refuses it), and the criteria F traces are gaps; and a plain `it(` or `test(` statement (an async arrow, a `function`,
  one destructured or named parameter, a timeout number, backtick title without `${`, a trailing `;` or `//` comment, a title on
  its own line) is a new block wherever it lies at statement level, also at the end of a `describe`

#### Scenario: SCN-VER-429 (−) A traced test that step 1's run did not pass keeps the hold
- **Given** SCN-VER-416 where the traced test of F is absent from the ids that passed in step 1's run of the base's file on
  the unit's code, though it is in none of `failing`, `not_run` and `flaky` (the run never saw it), or step 1's record has
  no list of passed ids
- **When** step 5 runs
- **Then** the rule fails and the criteria F traces are gaps

#### Scenario: SCN-VER-431 (+) A test file of some thousands of tests is decided in seconds
- **Given** a generated TypeScript file of 3000 tests and one new test appended, and a generated Python file of 3000 tests and
  300 new ones
- **When** the rule decides each file
- **Then** each decision takes under ten seconds, and a new block that is not a plain statement is refused in as little time

### Requirement: L4-VER-098 The same rule for a Python test file
A Python test file F (`.py`, found by `carry_file` with the dotted-module walk in agreement, L4-VER-086) that the unit changed
SHALL meet condition 3 of L4-VER-086 under the conditions (a) and (b) of L4-VER-097 and these: both blobs parse as Python; the
*collected tests* of a text are the module's functions and the methods of its module-level classes whose name starts with
`test` (`scan._qualified`), with the span of a test from its first decorator, or its `def`, to its `end_lineno`; every tracing
test of F is a collected test at the base and at the head (its qualified name read from its id as `tamper.names_test_id`
reads it: a parametrised `test_x[a-b]` names `test_x`); NEW is the set of collected tests of the head whose qualified name is
not a collected test of the base, and each has no decorator, has no default value (positional or keyword-only) and no type
parameter, has only annotations that are names, attributes, subscripts of those (tuples and lists inside a subscript
included) and constants, the return annotation too (a call, a lambda, an assignment expression or an operator in an
annotation runs at collection: refused; plain fixture parameters such as `db` or `db: Session` pass), is bound by exactly one statement of its scope at the head and
by none at the base (no second `def`, assignment, class or import of that name: a later definition of an old name would
replace the old test); and the head's text with the spans of NEW removed equals the base's text, a line that is blank or
only a comment (read with `tokenize`) dropped on both sides, except a shebang on line 1 and a coding declaration (PEP 263,
`^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)`) on line 1 or 2, which are code here: any difference in them keeps the criterion a gap. A file that does not parse, a test nested in a function or a
class that is not module-level, a changed or deleted line, a decorator on a new test, a new test with an old test's name and
anything else that is unclear SHALL keep the criterion a gap. [I, the same facts as L4-VER-097; no Python consumer data]

#### Scenario: SCN-VER-424 (+) A new test function and a new method of an old class carry the criteria the file traces
- **Given** a unit that changed a Python test file F by adding `def test_new(...)` at module level and `def test_other(self)` to
  an existing `class TestA`, deleting nothing, F listed in `reverted` of step 1's run of the round with the traced test
  passing there, and a UI criterion traced by `pass_to_pass` tests of F
- **When** step 5 runs
- **Then** the criterion is carried with `appended: [F]`

#### Scenario: SCN-VER-425 (−) A redefinition, a decorator, a nested def, a changed line or a file that does not parse keeps the hold
- **Given** SCN-VER-424 where the added test has the name of an old test (the old one is replaced by the later `def`), or
  carries `@pytest.mark.slow`, or is a `def test_x` inside an old test's body, or the unit also changed one line of an old
  test or a module-level statement, or the head does not parse
- **When** step 5 runs
- **Then** the rule fails and the criterion is a gap as in 0.4.61

#### Scenario: SCN-VER-426 (+) A reused round keeps the carry and the row says what was appended
- **Given** the round of SCN-VER-416 or SCN-VER-424, reused by the next round
- **When** the next round runs
- **Then** the stored outcome stands and nothing is decided again, and the generated UI tests table row of each carried
  criterion reads `carried from the base: <ids> (...); the unit only added tests to <F>; a note, not a hold (L4-VER-086)`

#### Scenario: SCN-VER-428 (−) A coding declaration or a shebang, a default value or a computed annotation of a new Python test keeps the hold
- **Given** SCN-VER-424 where the unit also added a coding declaration (`# -*- coding: latin-1 -*-`) on line 1 or 2 or a
  shebang on line 1, or changed or removed one (the same declaration on both sides is no difference), or the new test is
  `def test_new(x=compute())`, `def test_new(*, x=1)`, `def test_new(a: compute())`, `def test_new(a: (lambda: 1)())` or
  `def test_new() -> compute()`
- **When** step 5 runs
- **Then** the rule fails and the criterion is a gap as in 0.4.61; plain fixture parameters (`db`, `db: Session`,
  `-> None`) and an ordinary comment on line 1 do not fail it
