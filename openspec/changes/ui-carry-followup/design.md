## Context

Read at the branch head 4c8f127d. Labels: [V] read in code or in stored data, [I] inferred from code, not run, [U] not verified.

- `FamilyProvider.criteria` (`src/l4/verifier/fixloop.py:175-187`): the family's criteria, each id once, a member's own reading
  first; for the parent unit it then adds `merged_parent_criteria()` with `setdefault`, so a follow-up's own criterion wins
  over a parent criterion with the same id [V]. `merged_parent_criteria` (`:194-205`) reads `openspec_criteria(folder)`,
  `folder` being the parent's own folder in the follow-up's tree (`parent_folder`, `src/l4/specs/followup.py:118-136`: a
  sibling change, else the newest `archive/<date>-<name>/`), and is empty for any other unit [V].
- The baseline of the pass-to-pass rule: `spec_baseline` (`src/l4/specs/criteria.py:332-341`) is `base_criteria_at(git, rev)`
  for OpenSpec (the archived specs at the unit's base commit, from git, `:311-329`) and `merged_parent_criteria()` for Kiro;
  step 4 reads it at `ladder.py:861-862` and the red step at `src/l4/implementer/tdd.py:428-435` [V]. `unchanged_ids`
  (`criteria.py:344-350`) holds a criterion when the baseline has the same id with the same text after `normalise` [V].
- The carry: `carried_from_base` (`ui_step.py:228-263`); C3 is `any(f is None or f in changed for f in files)` (`:260`), with
  `files` from `ladder._carry_files` (`:1353-1360`, `carry_file` over the work tree) and `changed` from `unit_changed_files`
  (`playwright.py:36-39`: `git diff --name-only --no-renames base head`) [V]. `_generate_step` calls it at
  `ladder.py:1413-1418` [V].
- Step 1 (`src/l4/verifier/base_tests.py:552-700`) runs the test gate once at the head with every test and support file the
  unit added, changed or deleted at its base version (`unit_test_plan`, `support_base.py:73-94`, `support_at_base`, `:199`),
  except the files `_kept` leaves at head (a person's commit changed it, a `[test-infra]` task, a task's named support file,
  an unfrozen one), and emits `verify.base_tests` with `reverted`, `failing`, `not_run` and `flaky` (`base_tests.py:657-665`) [V].
  When the unit changed no test file, or setup failed, or no base reference exists, it emits nothing or skips [V].
- The harness already locates a test's own lines in another language: `test_locate.window` and `outside_tests`
  (`src/l4/implementer/test_locate.py:151-173`), used by the red step for a named test that red may have changed in place
  (`tdd.named_other_changed`, `tdd.py:1495-1531`, L4-IMP-089). That rule is looser on purpose ("a test that still passes is
  unchanged whatever else the file got"): it only decides whether red changed a test. A carry replaces a hold that a
  person would answer, so D2 is stricter [V].

## Goals / Non-Goals

Goals: a follow-up's UI criterion whose scenario is unchanged on the base is carried although a later change reworded the
parent's archived text (R1) or the unit appended a test to the file that traces it (R2), with no new way for a changed
behaviour to be carried.

Non-goals: see the proposal (`not_testable` notes, proving an implementer-written e2e test by running it at the base and the
head, fuzzy text matching, other languages).

## Decisions

### D1. The matching key for R1 is the criterion id, for OpenSpec only (L4-VER-096)

The stored data decides it. `criterion_id` (`criteria.py:36-38`) is `sha256` of `framework|container|requirement|leaf`,
each `normalise`d; for OpenSpec the container is the capability folder name and the leaf is the SCENARIO NAME, never its body
(`openspec_criteria`, `:98`; `_base_scenarios`, `:274-286`, builds the base's the same way). So two criteria share an id exactly
when they share capability, requirement name and scenario name (up to an 8-hex-digit collision, which the key's extra field
checks below defend against), and only the body can differ. Re-reading the stored parent deltas and the base specs of the
consumer's three units, both stale cases printed `in base, text differs` under the same id [V]. So for OpenSpec the id is not
a text hash, no second key is needed, and "requirement + scenario name" is the id itself. For Kiro `kiro_criteria` hashes the criterion's body
(`criteria.py:229`): a reworded Kiro criterion has another id, there is no same-id criterion to match, and the Kiro baseline
is the parent's own criteria (`spec_baseline`, `:339-340`), so its text agrees by construction [V]. R1 is OpenSpec only.

The rule: for each parent criterion `p`, `b` the base's criteria with `p.id`; if there is exactly one, with the same
framework, capability, requirement and scenario as `p`, and `normalise(b.text)` is not empty and differs from
`normalise(p.text)`, the result is `p` with `text=b.text`. Keeping `id`, `alias`, `source_path` and `source_line` matters:
the ids are what the ledger, the tests (`C-xxxxxxxx` in their names), the verdict questions and `reusable` key on, and
`carryover.carry_over` reads `source_path`'s blob (`carryover.py:229`); only the body is the stale part. Not rewritten: a
criterion with no base counterpart (the requirement or scenario was renamed or removed after the parent merged: the id
differs or is absent, and the parent's text stays, which is today's behaviour: it is a criterion the base no longer holds
and `unchanged_ids` does not hold it); an id held twice by the base (two scenarios of one name under one requirement; the
last would win in `unchanged_ids`'s dict, R1 keeps the parent's text); an empty base text.

Alternatives. Fuzzy text matching: rejected, L4-VER-086 says "not done" and a reworded scenario that is really a new
promise must stay a new criterion. Requirement name only: rejected, it would pick among scenarios. Doing it in
`unchanged_ids` (call a criterion unchanged when the base's id exists, whatever the text): rejected, it would carry
criteria whose text the unit's own delta changed, which is what C1 exists to stop. Rewriting only the pass-to-pass input and
not the text: rejected, the judge and the writers would read a text that step 4 does not.

Where. In `FamilyProvider.merged_parent_criteria` (`fixloop.py:194`), so that every reader gets the one text: the verifier's
steps through `wb.provider.criteria` (`ladder.py:751`, `:1588`; `wb.provider` is the family, `ladder.py:2263`), the judge and
writer prompts, the verdict questions, and the red step's `unchanged_on_base` when its provider is the family [U: whether a
task's workbench provider is `family_of`'s or the plain provider is not read; task 1.3 checks and, if it is the plain one,
passes the same resolver there, so that the red step and the verifier agree, L4-IMP-093]. `cap_universe`
(`implementer/result.py:225-236`) reads ids only [V].

The base commit. `family.criteria(...)` is computed in `verify_hook` right after `bring_in_base` (`ladder.py:2226-2228`), so at
that point `HEAD` contains the base branch head and the merge base is the head of `refs/remotes/origin/<base_branch>`,
which is what `check_preconditions` computes (`preconditions.py:288`) and what `unit_base` computes for the red step
(`discrimination.py:736-746`, which also tries the local base branch) [V for `verify_hook`; the other callers of `family_of` (`delegate/run.py:233`, `verifier/legacy.py:52`, `fixloop.py:346` and
`:489`) were not read, and there the merge base may be older than the head of the base branch [U]: task 1.3 reads them]. `family_of` (`fixloop.py:240-259`) passes the
provider a `base_rev` read once, lazily (the git call is made only for a follow-up), by one shared helper that `unit_base`
and `preconditions` also call, so that the three never disagree. The family reads the ORIGIN ref only (`unit_base_commit(...,
local_fallback=False)`, as `preconditions` does; group 5, F6): with `refs/remotes/origin/<base>` missing and a local base
branch that was moved onto the unit's head, the fallback would have read the unit's own edit of the spec as "the base". The
red step (`discrimination.unit_base`) keeps its fallback to the local branch. `FamilyProvider.git` may be `None` and
`merge-base` may fail: then `base_rev` is `None` and nothing is rewritten (today's behaviour). `spec_baseline` and the rewrite read the same commit.

What step 4 does with it: the criterion is now `unchanged` (same id, same text as `base_criteria_at(rev)` by construction),
so a test that traces it and passed at the base and passes at the head has the proof `pass_to_pass`, and L4-VER-086 can
carry it. A criterion step 4 does not find covered stays a gap, as before.

### D2. The R2 rule: whole new tests and nothing else (L4-VER-097, L4-VER-098)

What the carry needs from C3 is that the test the person or the judge would look at is the base's. A file the unit changed
only by adding new tests keeps every old test as it was; the rule proves that from the text, with two legs that cover each
other's blind spot: the text leg cannot see an effect that a new test has at run time through shared state, the run leg
(step 1's run of the base's file on the unit's code, and step 3's run of the head's file) can: a traced test that passes both
with the new tests (step 3, it has the proof `pass_to_pass` at the head) and without them (step 1) is not made to pass or to
fail by them, except through an order dependence that both runs pass. The text leg, in turn, fixes what step 1 and step 3
do not say: that the head's old tests are the base's. The rule is defined on block text, not on diff hunks: git may slide a
hunk across a shared closing line, so "an added line outside the traced block" would depend on the alignment git picked;
equal block text does not.

Common to both languages (a): `git diff --name-status --no-renames base head` says `M` for F, `--numstat` says 0 deleted
lines and F is not binary, both blobs are read through git (`evidence.collect.show_blob`, at most `MAX_SOURCE_BYTES`, so not
the work tree) and decode as UTF-8. A rename is `D` plus `A` under `--no-renames`, so a moved file is never "appended". "Removes or modifies no line" is
the 0-deleted test: a changed line is a deleted line and an added one. (b): step 1's run of
this round lists F in `reverted` and none of the tracing tests of F is in its `failing`, `not_run` or `flaky`. `verify_unit`
reads `events` once, at `ladder.py:750`, before step 1 emits `verify.base_tests`, and `_generate_step` gets that list [V], so
this round's event is not in it: `check_base_tests` hands the four fields to the round (`Outcome`, then `_Run`) and step 5
reads them there; the ledger is not read. A fifth field, `passed`, is the ids that PASSED in step 1's run (R1, the report of
the base's file on the unit's code): the four lists say what failed, was absent from the base or flaky, and a test that the
run never saw is in none of them, so the rule requires every tracing test of F to be in `passed` as well, and a record with no
`passed` (None) fails closed (group 5, F5).
`_kept` can leave F at head (a person's commit changed it last), `check_base_tests` can return early (setup failed, no base
reference) or not run at all (no test or support file changed), and F can lie outside `tdd.test_globs`; in each case no event
lists F and the rule fails closed. This costs some real cases and is the price of the argument above [I]. In the consumer's
data the file of the two blocked criteria was in `reverted` in both rounds with empty `failing` and `not_run` [V].

JavaScript and TypeScript (extensions `ts tsx js jsx mjs cjs mts cts`, `gate_repeat.JS_EXTENSIONS`, `gate_repeat.py:42`). The
block of a test is `test_locate.window(text, name)` (`name` is the id's part after its first `::`: the consumer's Vitest ids
look like `web.src.x.test.ts::C-... title`, with no `describe` prefix in the data [V]; a
reporter that joins `describe` and test titles by ` > ` or a space is read by `window` through `_names` and the enclosing
strings [I]). A block counts only when:
- its first line is a call line (`_CALL`/`_OPENED`: `test`, `it`, `describe`, `suite`, `bench`, with the modifiers) whose string
  names the test: `_start`'s last resort, "the first line that holds the name", is no block, because any comment or string
  would do;
- `window` finds it once: it returns `None` when two calls carry the name and the `describe` strings of the name cannot tell
  them apart. This is what catches a new test with the title of an old one, and a `window` that spans the wrong lines;
- it is closed: the block's `(`, `{`, `[` balance with string, template-literal and comment text skipped (a small scanner in
  the new module; `_span` ends a block by indentation, which is right for formatted code and wrong for code that is not, and
  a block cut short would let an added line look "outside" it). A single-quoted string that does not end on its line, JSX
  text with an apostrophe that leaves a quote open, a negative count or a non-zero count at the end of the block: not closed.

The block of an OLD test is the one above. The block of a NEW test is stricter (group 5, F1): `window` ends a block at the next
dedented line, so a line such as `it("t", () => {}); beforeEach(() => { counter = 5; });`, a closing line that goes on with a
hook, or a `describe` titled like the test would have been read as "one test" and accepted. A NEW test is exactly one plain
test statement, found by one scan of the head (`carry_appended._plain_calls`: the same string, template and comment aware
scanner as `is_closed`, lenient about a quote that does not end, since a whole file has JSX text; `_tokens`):
- it starts its line, is outside every string, template literal and comment, and is a statement: directly in the file or in a
  `{` block, after a `;`, a `{`, a `}` or a `)` that does not close the head of an `if`, `for`, `while`, `switch`, `with` or
  `catch` (so `if (x)\nit(...)` and `foo(\nit(...)\n)` are no statements);
- it is `it(` or `test(`: not `describe`, `suite`, `bench`, a hook, and not `.each`, `.only`, `.skip`, `.todo` or any modifier
  (chosen for simplicity: a modifier changes whether the test runs, which the run leg would have to see; they stay refused);
- its first argument is one string literal (quotes, or a backtick template with no `${`), its second a function literal
  (`() => {`, `async () => {`, `function (`, `async function (`, `name => {`) with at most one parameter that is a name or a
  destructuring pattern with an optional type and no `=` (no default value; no call, string or comma at the top level in the
  parameter list), an optional third argument that is a number (the timeout) and an optional trailing comma; no comment
  between the arguments;
- its closing `)` (found with the bracket scan) ends its last line, followed only by an optional `;`, whitespace and a `//`
  comment; with no `;`, the next code character must not be one of `( [` a backtick `+ - * / . , ? : = & | < > % ^ ~ !`
  (an `it(...)` before a line that starts so would be continued by it).
The title of a `describe` never starts a block, whatever the strings say (the scan has no `describe`). What the old scan
accepted and this refuses: a statement on the same line, arguments that run code at collection (`it("t", (counter = 7, () =>
{}))`, an immediately called function), `it.only` and the like, a block whose closing line goes on. What it keeps: a new test
at the end of a `describe` (a `{` block), with or without semicolons (after a `)`), a timeout, a title on its own line (prettier),
a trailing `//` comment. Cost: a new test that wants a comment between its arguments, a typed parameter list that holds a
function type, a modifier or an `it` after a non-`)`-ending semicolon-free line is refused (lost cases, fail closed).

Then, with H the names of F's tests in the head's step-3 reports (the unit gate's and the e2e gate's; `_test_names_of`,
`tdd.py:1482-1492`, which moves to `test_locate` so the verifier and the red step share it): OLD = names of H with a block at
the base; NEW = names of H not in OLD with one plain statement at the head that carries the longest string that names the
name (`describe` strings of a reported name are tolerated as for OLD) and is no line of an OLD block at the head (several
statements with that string: not found). The rule holds when every tracing test of F (listed and ignored) is in OLD, every
name of OLD has a block at the head equal to its block at the base, and the base's lines outside the OLD blocks equal the
head's outside the OLD and NEW blocks (blank lines dropped, as a test appended to a file brings the blank line before it).
Read together: the head is the base plus whole test blocks. A line added inside a traced test, inside another old test, or
as a new test nested inside one fails the block equality. A hook, an import, a constant, a `describe` wrapper, a `vi.mock`,
a comment outside a test: outside lines differ. A new test that is not found by its reported name (a template-literal
title with `${...}`, an `.each` table: the expanded names do not match the literal) leaves its lines outside any block, and
they differ. All of those fail closed, which also keeps `vi.mock`, which a runner may hoist to the top of the file wherever it
is written, out of the text leg's reach for added lines outside tests (a `vi.mock` inside a new test's body is another
case: see D3). Some real cases are lost: a new test that needs a new import, or that opens a new
`describe`.

Cost (group 5, F4): the old reading ran `_span`, `_start` and `_literal` over every line for every name (800 tests of 46 KB
took 3.6 s, and `MAX_SOURCE_BYTES` is 500 000). A file is now read once: `test_locate.CallIndex` holds the string of every
call line and the lines that carry each string, and a name is looked up through the suffixes of the name (the strings it can
carry, `_names`), and the new blocks come from the one scan. The same result as the line-by-line reading is tested for the
index; a generated 3000-test file is decided in well under 10 s.

Python (`.py`): the blocks are the AST's. A collected test is a module function or a method of a module-level class whose
name starts with `test` (`scan._qualified`, `scan.py:214-222`), spanning its decorators to `end_lineno`. A tracing test of F is
read from its id as `tamper.names_test_id` reads it (`tamper.py:521-528`) and must be collected at both sides. NEW is the
collected tests of the head whose qualified name is not collected at the base. Each must have no decorator (a mark, a
`parametrize` or a fixture alias could reach a fixture, a skip or a reorder; the cost is a test that carries a mark),
be bound once in its scope at the head and not at the base: Python lets a later `def` of an old name REPLACE the old test while
the old lines stay in the file, which a text rule alone would read as "old test unchanged". Remove the spans of NEW from the
head and compare with the base with blank and comment-only lines (read by `tokenize`) dropped on both sides: equal text is
the whole rule. Two additions (group 5): a shebang on line 1 and a PEP 263 coding declaration (`^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)`
on line 1 or 2) are NOT droppable, they change how the file is read, so any difference in them refuses (the blobs are decoded
as UTF-8 before the rule, and an added `# coding: latin-1` would make the interpreter read the same bytes differently); and a
new test's `def` line runs when the module is collected, so it must have no default value (positional or keyword-only), no
type parameter, and only annotations that are names, attributes, subscripts of those (a tuple or list inside a subscript is
kept as structure) and constants, the return annotation too: a call, a lambda, an assignment expression or any operator
(`int | None` included) refuses; plain fixture parameters (`db`, `db: Session`, `-> None`) pass. The bindings of a scope are
counted once per scope, not once per new test. A test nested in a function or in a non-module-level class is not collected, so its lines stay in the
head's text and differ: fail closed. A file that does not parse: fail closed.

Other languages: the file-level rule stays (a Go, Java or C# test file that the unit changed keeps its criteria gaps). The
harness has block readers for them in `window` (Go's `func Test...(`), but the closed-block check of D2 and the run leg were
only reasoned for the two languages whose consumers exist.

Recorded: `verify.generated{status: carried, covered_by, attempts: 0}` gets the optional `appended: [<file>, ...]`, only
when a file was accepted by this rule; the carried row says `the unit only added tests to <files>`. Nothing in the ledger
needs the key. A reused round keeps the stored outcome (L4-VER-086 already says so).

### D3. What could slip

R1 (L4-VER-096):
- A follow-up meant to keep the parent's original promise, which a later change on the base superseded. After R1 the family
  verifies the base's wording, the current promise. This is the intended reading (a merged unit's promise is what the base now
  says; the follow-up refactors or fixes ON the base), and a follow-up that really means the older sentence restates the
  scenario in its own delta, under the same names, where its own text wins and is a changed criterion (not carried, SCN-VER-414).
- Silent dependence on the base spec: a later change that WEAKENED the scenario weakens the follow-up's check with it. The
  tests that trace it still ran and passed, the judge still reads the unit's diff; the carry still passes nothing (L4-VER-086).
- A later change that renamed or removed the requirement or scenario leaves the parent's text, which is today's behaviour: R1
  does not cover that case, and its hold stays.
- A person's accept of the criterion verdict bound to the old text (`text_sha256`, `verdicts.py:72`, `:518`) is void once for a
  rewritten criterion, and a UI hold's binding (`ui_step.ui_hold_binding`, `:290-301`) hashes the text too: the hold is
  asked again with a new binding if the criterion is not carried. Criteria whose text is not rewritten keep their accepts.
- A unit whose round was already NEEDS_HUMAN under the old harness is reused while its subject and the criteria ids are
  unchanged (`evidence.reusable`, `:108-116`: ids only), so it keeps the old holds until a new commit or `l4 retry` makes a
  fresh round; no text is compared there [I].
- The base commit is read in three places (`family_of`, `preconditions`, `unit_base`); a divergence would make C1 compare
  against another spec than the one the rewrite read. D1 puts them behind one helper; the test of 1.3 pins it.

R2 (L4-VER-097, L4-VER-098):
- A new test that changes shared state (a module variable, a global, an environment variable, timers, a mock set at module
  scope) and so changes what an old test does, in a way that makes it pass with the new tests and with the base's file alike.
  It would have to pass in two runs, with and without the new tests (step 3, step 1), and the old tests' text is the base's:
  what slips is a test that is order dependent in a way both orders pass. Named, accepted.
- A `vi.mock(...)` (or `jest.mock`) written inside the BODY of a new test passes the text leg, because the new test is a whole
  new block, and a runner may hoist it to the top of the file, where it changes the old tests. Only the run leg covers it: the
  base's file ran on the unit's code at step 1 and the traced test passed there. Named, accepted.
- A new test written as `it.only(...)` or inside a `describe.only`: `it.only` is refused by the text leg (a NEW block is a
  plain `it(` or `test(` statement, no modifier); a `describe.only` wrapper is outside lines and refused too; either way the
  old tests would be `skipped` at the head and C2 needs `passed` [I].
- "Statement level" for a NEW block is any `{` block or the file: a helper, a hook, a loop or an `if` body that already exists
  at the base counts, not only the file and `describe` callbacks. It is a new test only when the head's report holds its
  name and the lines outside the blocks equal the base's, so the risk is a new test registered inside an existing block
  that the base's code runs. Named, accepted. The head of an `if`, `for`, `for await`, `while`, `switch`, `with` or `catch` is
  read from the 24 characters before its `(`: a comment between the keyword and the paren is not seen, so a braceless body
  with such a comment can take a test inserted in front of it. Residual, named.
- A NEW block is one plain statement, so nothing else rides on its lines; an OLD block is still `window`'s, an indentation
  reader, checked closed, and its text must equal the base's. `window` is an indentation reader and the closed-block check is a scanner, not a parser. Unusual code (a regex literal that
  holds a quote, JSX text that balances by accident) can mislead the scanner into a block that looks closed and is not.
  The block-equality and the outside-lines equality are then taken over the wrong lines, and what protects the carry is step
  1's and step 3's runs and the fail-closed cases. Residual risk, named.
- Python: a new test with the name of a non-test binding of the base is refused; a new test method inside a class that the
  unit created is not a NEW test of an old class and is refused (the class's lines are new outside lines).
- Lost cases (fail closed): a new test that needs a new import, a new `describe` or a hook; a file left at head by step 1; a
  test that carries a mark (Python); a file outside the languages of D2. The hold stays, as in 0.4.60.
- The rule never carries a criterion on its own: C1, C2 and C4 are L4-VER-086's, the judge's pass is still needed, and a
  reject is never carried.

### D4. Tests

Test-first, in the style of `tests/unit/verifier/test_ui_step.py` (pure functions) and `test_ui_flow.py` (the ladder):

- R1, `tests/unit/specs/test_parent_text.py` (new, the pure `read_at_base`): the table of SCN-VER-412..414: a reworded
  scenario takes the base's text and keeps id, alias, source; a renamed requirement, a duplicate, an equal text, an empty base
  text keep the parent's; a Kiro criterion is untouched; the own delta wins (tested on `FamilyProvider.criteria`).
  `tests/unit/verifier/test_family_parent_text.py` (new, a temporary git repo as `test_fixloop_kiro.py` builds one): the family
  of an OpenSpec follow-up with an archived parent whose scenario the base reworded; `base_rev` None (no `origin` ref, git
  failing) leaves the text; the three readers of the base commit agree on a repository where the local base branch is ahead
  of `origin/<base>`; a Kiro follow-up is unchanged.
- R2, `tests/unit/verifier/test_carry_appended.py` (new, pure over two texts and a name list): one case per row of SCN-VER-416..425:
  an `it` between two tests (the real shape, +11/-0), at the end of a `describe` and at the end of the file; a deleted
  blank line; one line added inside the traced test, inside another test, a new test nested in an old one; a hook, an import,
  a constant, a `vi.mock`, a `describe` wrapper, a template-literal title, an `.each` table; a duplicate title; an unclosed
  string and JSX text with an apostrophe; a traced test whose first line is not a call line; Python: a function, a method of an
  old class, a redefinition of an old name, a decorator, a nested def, a changed line, a syntax error, comment and blank lines.
- `tests/unit/verifier/test_ui_step.py` (`carried_from_base` with the new `appended` argument: a file in `changed` that the
  predicate accepts carries; one that it refuses does not; the other conditions still decide per file, SCN-VER-423) and
  `test_ui_flow.py` (the ladder: step 1's record with and without F in `reverted`, in `failing`, in
  `flaky`; `verify.generated{appended}`; the row; a reused round, SCN-VER-421, 426).
- A table-driven check of the real shape against `test_locate.window`: ids of the form `<dotted path>::C-... title`.
- Not verifiable here: an end-to-end run against a consumer's repository. The two real cases are stored as fixtures
  reduced to their shape (wording and a +11/-0 diff), without the consumer's names.

### D5. Upgrade and risks

No configuration key. A unit in `needs_human` under 0.4.60 keeps its round until a new subject (D3). A person who accepted a
hold or a verdict for a rewritten criterion answers it again once. The optional `appended` key is ignored by an older
reader. R1 and R2 are separable: either can be left out of a release, and each loosens L4-VER-086's C1 or C3 only in the
cases named, so `docs/SPEC.md` marks them slippable like the carry itself.
