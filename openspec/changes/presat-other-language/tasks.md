## 1. The rule (D1, D2, D4)

- [x] 1.1 Write the tests first (tests/unit/implementer/test_presatisfied_other_language.py): SCN-IMP-485 at the
  `confirm_pre_satisfied` level for the empty-scope exit and through `_decide_pre_satisfied` (a held `pre_satisfied`
  outcome), SCN-IMP-486, SCN-IMP-487, SCN-IMP-488 (a Python test and a test whose file is not found), a TypeScript test
  that the zero-value run refuted with a non-empty scope (a mixed project), and a criterion the run confirmed that
  stays confirmed. Then add `PRE_NOT_PYTHON` and the per-test reclassification in `confirm_pre_satisfied`.
  Result: `PRE_NOT_PYTHON` and `_out_of_reach` in `l4.implementer.discrimination`, applied at the empty-scope exit and
  after `variant.judge`; test_presatisfied_other_language.py, 11 passed (the file failed to import before the constant
  existed).
- [x] 1.2 The review: R1..R6. R1: `PreSatisfied.ran` (false at the dependency-only, empty-scope and `zero is None`
  exits) and `tdd._runs_of` lists `test-presatisfied` only when it is true; `BaseRunResult.seen` (`SEEN_PASSES`,
  `SEEN_ERROR`) filled by `confirmed_by_base_run` and ended onto an inconclusive reason by `combine`. R2: the
  `zero is None` exit applies `_out_of_reach`. R3: a test the zero-value run holds as `skipped` counts as reached. R4:
  tests. R5: design D5 and two risks. R6: wording of L4-IMP-092 in spec.md and SPEC.md, SCN-IMP-489, row 117,
  CHANGELOG.
  Result: test_presatisfied_other_language.py 22 passed (8 failed before the code: skipped, `zero is None`, `ran`,
  `_runs_of`, SCN-IMP-489, `seen`); test_base_run.py 18 passed (3 new, failed before); test_presatisfied 4,
  test_presatisfied_inconclusive 4, test_earlier_red 21, test_held_check 4, test_held_answers 8,
  test_zero_value_causes 19, test_dependency_only 15, tests/unit/orchestrator/test_held_exit.py 1,
  tests/unit/verifier/test_extra_inconclusive.py 38, tests/unit/docs 120, release notes 9 passed; no existing assertion
  changed; ruff clean, `scripts/check_spec.py docs/SPEC.md` clean, `openspec validate presat-other-language --strict`
  valid.

## 2. Checks

- [x] 2.1 SPEC.md (L4-IMP-092, the sentence in "Confirmation by a base run", SCN-IMP-485..488, row 117), CHANGELOG, the
  implementer and verifier suites, the docs tests, ruff, `openspec validate presat-other-language --strict`.
  Result: L4-IMP-092, the sentence in "Confirmation by a base run", SCN-IMP-485..488, row 117 and CHANGELOG;
  tests/unit/implementer: test_presatisfied 4, test_presatisfied_inconclusive 4, test_base_run 15, test_earlier_red 21,
  test_dependency_only 15 passed; tests/unit/verifier/test_extra_inconclusive.py 38, tests/unit/docs 120, release notes
  9 passed; `scripts/check_spec.py docs/SPEC.md` clean, ruff clean, `openspec validate presat-other-language --strict`
  valid.
