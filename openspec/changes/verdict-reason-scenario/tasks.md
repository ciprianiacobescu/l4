## 1. The bounded reason (L4-VER-059)

- [ ] 1.1 Write the tests first (tests/unit/verifier, grep `record_human_verdicts` and `when_then`). Then implement design D1.
  Cases: design D3, SCN-VER-262, SCN-VER-263.

## 2. Tag-safe brackets (L4-IMP-006 (7))

- [ ] 2.1 Write the tests first (tests/unit/specs, grep `_plain`, `_line` and the existing bracket tests). Then implement
  design D2. Cases: design D3, SCN-VER-264; the existing tests that a `[tag]` in a finding's text becomes `(tag)` still pass.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-VER-059, L4-IMP-006 (7), the scenarios, row 108), CHANGELOG; the unit suite, ruff, mypy,
  `openspec validate verdict-reason-scenario --strict`.
