## 1. The rule (D1, D2, D4)

- [ ] 1.1 Write the tests first (tests/unit/implementer/test_presatisfied_other_language.py): SCN-IMP-485 at the
  `confirm_pre_satisfied` level for the empty-scope exit and through `_decide_pre_satisfied` (a held `pre_satisfied`
  outcome), SCN-IMP-486, SCN-IMP-487, SCN-IMP-488 (a Python test and a test whose file is not found), a TypeScript test
  that the zero-value run refuted with a non-empty scope (a mixed project), and a criterion the run confirmed that
  stays confirmed. Then add `PRE_NOT_PYTHON` and the per-test reclassification in `confirm_pre_satisfied`.

## 2. Checks

- [ ] 2.1 SPEC.md (L4-IMP-092, the sentence in "Confirmation by a base run", SCN-IMP-485..488, row 117), CHANGELOG, the
  implementer and verifier suites, the docs tests, ruff, `openspec validate presat-other-language --strict`.
