## 1. The rule (D1, D2, D4)

- [x] 1.1 Write the tests first (tests/unit/implementer/test_presatisfied_other_language.py): SCN-IMP-485 at the
  `confirm_pre_satisfied` level for the empty-scope exit and through `_decide_pre_satisfied` (a held `pre_satisfied`
  outcome), SCN-IMP-486, SCN-IMP-487, SCN-IMP-488 (a Python test and a test whose file is not found), a TypeScript test
  that the zero-value run refuted with a non-empty scope (a mixed project), and a criterion the run confirmed that
  stays confirmed. Then add `PRE_NOT_PYTHON` and the per-test reclassification in `confirm_pre_satisfied`.
  Result: `PRE_NOT_PYTHON` and `_out_of_reach` in `l4.implementer.discrimination`, applied at the empty-scope exit and
  after `variant.judge`; test_presatisfied_other_language.py, 11 passed (the file failed to import before the constant
  existed).

## 2. Checks

- [x] 2.1 SPEC.md (L4-IMP-092, the sentence in "Confirmation by a base run", SCN-IMP-485..488, row 117), CHANGELOG, the
  implementer and verifier suites, the docs tests, ruff, `openspec validate presat-other-language --strict`.
  Result: L4-IMP-092, the sentence in "Confirmation by a base run", SCN-IMP-485..488, row 117 and CHANGELOG;
  tests/unit/implementer: test_presatisfied 4, test_presatisfied_inconclusive 4, test_base_run 15, test_earlier_red 21,
  test_dependency_only 15 passed; tests/unit/verifier/test_extra_inconclusive.py 38, tests/unit/docs 120, release notes
  9 passed; `scripts/check_spec.py docs/SPEC.md` clean, ruff clean, `openspec validate presat-other-language --strict`
  valid.
