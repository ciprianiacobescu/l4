## 1. The rule (L4-SEC-004)

- [x] 1.1 Write the tests first (tests/unit/security/test_protected.py), then add `**/.gitattributes` to
  `CONTRACT_PROTECTED_GLOBS` and the root file to the anchored roots. Cases: SCN-SEC-120, SCN-SEC-121.
  Result: `CONTRACT_PROTECTED_GLOBS` has 28 globs; `ANCHORED_ROOT_FILES` = the root guidance files plus `.gitattributes`
  feeds `anchored_roots`; 6 new cases failed before the change and pass after; tests/unit/security passes (146).

## 2. Checks

- [x] 2.1 SPEC.md (L4-SEC-004, SCN-SEC-120, SCN-SEC-121, row 109), CHANGELOG; ruff; the docs tests.
