## 1. Red (L4-IMP-089)

- [ ] 1.1 Write the tests first (tests/unit/implementer/test_test_locate.py, test_tdd_red.py, test_prompt.py, and the
  `named_other_changed` tests wherever `named_other` is tested today). Then implement design D1 to D4 and D6. Cases:
  SCN-IMP-450 to SCN-IMP-452; the reproduction of the consumer's file (a module-level `EXPECTED_CODES` object above the
  `test(...)` call, 16 entries at the base, 22 at red); a describe-scoped constant; a red step that appends a test with a
  blank line before it and an import (named test passing: nothing excused, no failure); a red step that changes another
  existing test of the file (its window is removed, so the named test is not excused when only that test changed);
  SCN-IMP-439 to SCN-IMP-444 still pass.

## 2. The judge (L4-VER-068)

- [ ] 2.1 Write the test first (tests/unit/verifier/test_judge_step.py and test_prompt.py, grep `Named tests changed`).
  Then implement design D5. Case: SCN-VER-261; SCN-VER-253 still passes.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-IMP-089, L4-VER-068, the scenarios, row 107, the `named_tests.found` event), runbook.md (the named
  test NOTE), CHANGELOG; the unit suite, ruff, mypy, `openspec validate named-test-shared-lines --strict`.
