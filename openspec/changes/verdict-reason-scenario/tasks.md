## 1. The bounded reason (L4-VER-059)

- [x] 1.1 Write the tests first (tests/unit/verifier, grep `record_human_verdicts` and `when_then`). Then implement design D1.
  Cases: design D3, SCN-VER-262, SCN-VER-263.
  Result: `verdicts.MAX_VERDICT_REASON_CHARS` (4000) and `verdicts.bounded_reason` (next to `WHEN_THEN`): a reason within
  the limit is unchanged; a longer one with a `WHEN ... THEN ...` sentence keeps it whole from its last `WHEN` (tail of
  at most 3,800 characters) behind the start of the text and ` … `, at most 4,000 characters in all; otherwise it is
  cut at 4,000. `consume_verdicts` (which records `human.verdict`) stores `bounded_reason(parsed[1])` instead of
  `parsed[1][:1000]`; `fixunit.when_then` is unchanged and reads the whole sentence. Tests in
  tests/unit/verifier/test_verdicts.py (five, SCN-VER-262 and SCN-VER-263); the record test fails with the old cut.

## 2. Tag-safe brackets (L4-IMP-006 (7))

- [ ] 2.1 Write the tests first (tests/unit/specs, grep `_plain`, `_line` and the existing bracket tests). Then implement
  design D2. Cases: design D3, SCN-VER-264; the existing tests that a `[tag]` in a finding's text becomes `(tag)` still pass.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-VER-059, L4-IMP-006 (7), the scenarios, row 108), CHANGELOG; the unit suite, ruff, mypy,
  `openspec validate verdict-reason-scenario --strict`.
