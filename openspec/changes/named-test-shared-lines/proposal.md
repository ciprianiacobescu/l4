# A named test is also changed through its file's shared lines

## Why

A consumer's later unit had to make an earlier unit's merged TypeScript registry test expect 22 codes instead of 16.
The reviewed task line named the test as `` `src/api/error-codes.test.ts::C-… The registry holds exactly the 16 codes …` ``
and told red to extend `EXPECTED_CODES`, the module-level constant the test compares with. Red did exactly that on two
models and five attempts, and every attempt failed with `red broke existing tests: <the named id>`, so the unit halted
on `max_task_attempts` [V, 0.4.45, 2026-10-31].

Cause [V, reproduced with the 0.4.46 code]: the name resolved (one test of the file in the base report, the file in
`tdd.test_globs` and in no support or ignore glob), but `tdd.named_other_changed` counts a named test of another
language as changed only when its own lines (`test_locate.window`, the `test(...)` call to its closing line) differ
between the base and red. The constant sits above the call, so the window was byte-identical, the id was not excused,
and its assertion failure was a regression. L4-IMP-089 lists this as a limit; the red prompt does not say it, and the
natural way to write such a test (the expected value in a constant of the file) is the one that fails.

## What changes

- A named test of another language whose own lines are unchanged also counts as changed in place when it fails at red
  and the file's lines outside every test (a constant, a fixture or a helper of that file; blank lines dropped) differ
  between the base and red. Such a test is excused like one whose own lines changed (it must fail by an assertion or
  `NotImplementedError`, and green must make it pass). One that still passes is unchanged: nothing is excused, recorded
  or failed, so a red step that only adds tests or imports to the file is not affected.
- A named test that fails at red although red changed neither its lines nor its file's shared lines is still `red broke
  existing tests`, and the reason now says why and what to do.
- `named_tests.found{task, tests, source}` records which existing tests the task's text named, before red runs.
- The judge's block of changed named tests gives the file's diff for a test changed through its shared lines, instead
  of two identical copies of its own lines.
- The red prompt says which changes count.
- Not changed: a Python named test (the AST closure of L4-IMP-046 already reaches the module's definitions); green opens
  no pre-existing test file; a test whose expected value is in another file; step 1 (it already runs the base version of
  the file and excuses only the recorded ids).

## Impact

- Code: `l4.implementer.test_locate` (`outside_tests`), `l4.implementer.tdd` (`named_other_changed`, `run_red`,
  `classify_red`), `l4.implementer.prompt` (`_named_section`), `l4.verifier.ladder` (`_named_changes`),
  `l4.verifier.judge` (`NamedChange`, `_named_lines`).
- Spec: L4-IMP-089 and L4-VER-068 amended; SCN-IMP-450 to SCN-IMP-452, SCN-VER-261; change-table row 107; runbook.
