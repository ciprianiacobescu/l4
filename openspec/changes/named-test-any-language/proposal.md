# Red may change a named test of any language in place

## Why

A consumer's later unit must change an earlier unit's merged TypeScript test (`src/api/error-codes.test.ts` asserts
"exactly 16 codes"; the task adds six). The reviewed task line names the file. In L4 that never works [V, 2026-10-29]:

- red may change an existing test in place only through L4-IMP-082's `path.py::name` ids (`named_tests._NODE`), so a
  TypeScript red that edits the test fails with `red broke existing tests`;
- green may not open a pre-existing test file at all (unfreeze-and-answer design D3: "tests are red's to write"), and
  only an answer that names the path opens it, which costs a question round and a run.

Green should stay closed: an edit to a frozen test is guarded only by the AST rules of L4-IMP-016 (old statements
stay, no name bound again, nothing patches the unit's modules), which read Python only. Red is the right step: a test
red changes must fail at red against the current code, which proves the new assertion checks something, and green
must then make it pass, while step 1 still runs every other test of the file at its base version.

## What changes

- A backticked `` `path::name` `` in the reviewed task text, where `path` is a tracked regular non-`.py` file that
  matches `tdd.test_globs` and no support or ignore glob, names an existing test of any language. The name is resolved
  against the base report: exactly one id whose file is `path` (`test_locate.file_of_id`) and whose test name matches;
  zero or several matches are kept with a reason (the task falls back to the question route).
- Red may change such a test in place: `classify_red` excuses the named id while it is still in the red report and its
  source window changed between base and red; the changed test must fail at red (a changed named test that passes at
  red fails the attempt, as an AST guard cannot check it); deleting or renaming it still fails.
- `tests.superseded{task, tests: [report ids], criteria: [], reason: "named_by_task", source, language}` is recorded,
  and the judge's prompt lists the changed named tests.
- Not changed: green opens no pre-existing test file in any language; L4-IMP-014's kept reasons; L4-IMP-016's AST
  rules; the Python id forms; the answer route; fix and follow-up units name nothing.

## Impact

- Code: `l4.implementer.named_tests`, `l4.implementer.tdd` (`run_red`, `classify_red`), `l4.implementer.test_locate`,
  `l4.verifier.judge` (a listing block).
- Spec: L4-IMP-089 added, L4-VER-068 added (the judge listing); L4-IMP-082, L4-IMP-048 and L4-IMP-014 amended;
  SCN-IMP-439 to SCN-IMP-444, SCN-VER-253; change-table row 97.
