## 1. Red (L4-IMP-089)

- [x] 1.1 Write the tests first (tests/unit/implementer/test_test_locate.py, test_tdd_red.py, test_prompt.py, and the
  `named_other_changed` tests wherever `named_other` is tested today). Then implement design D1 to D4 and D6. Cases:
  SCN-IMP-450 to SCN-IMP-452; the reproduction of the consumer's file (a module-level `EXPECTED_CODES` object above the
  `test(...)` call, 16 entries at the base, 22 at red); a describe-scoped constant; a red step that appends a test with a
  blank line before it and an import (named test passing: nothing excused, no failure); a red step that changes another
  existing test of the file (its window is removed, so the named test is not excused when only that test changed);
  SCN-IMP-439 to SCN-IMP-444 still pass.
  Result: `test_locate.outside_tests` (D1, built on a new `_span` that `window` shares); `named_other_changed(wb, base,
  named, base_report, report)` also returns a named test whose lines are the same when it fails (`failed` or `error`)
  and the file's lines outside the tests of the base report's names (at the base) and of the red report's names (in the
  work tree) differ (D2; the base tree's paths are read once, only when needed); `classify_red(named_unchanged=...)`
  appends the hint to `red broke existing tests` (D3, the order of the checks is unchanged) and `run_red` passes the
  named tests that fail and were not returned; `named_tests.found{task, tests, source}` is emitted before the agent
  step when a test is named (D4); the red prompt's named section carries the sentence of D6 before `Do not delete or
  rename one` (the existing prompt test pins `the criteria need:` followed by the data block). Tests: the consumer's
  module-level `EXPECTED_CODES` (reproduced first: `red broke existing tests`), a describe-scoped constant, a test and an
  import appended with the named test passing (nothing excused), another test of the file changed (hint), a file red did
  not touch (hint), `named_tests.found` with a TypeScript and a Python test, and `named_other_changed` called directly.

## 2. The judge (L4-VER-068)

- [ ] 2.1 Write the test first (tests/unit/verifier/test_judge_step.py and test_prompt.py, grep `Named tests changed`).
  Then implement design D5. Case: SCN-VER-261; SCN-VER-253 still passes.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-IMP-089, L4-VER-068, the scenarios, row 107, the `named_tests.found` event), runbook.md (the named
  test NOTE), CHANGELOG; the unit suite, ruff, mypy, `openspec validate named-test-shared-lines --strict`.
