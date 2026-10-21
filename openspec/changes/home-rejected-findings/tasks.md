## 1. Verifier (L4-VER-006)

- [x] 1.1 Tests: `tests/unit/verifier/test_fixunit_finding_home.py` (SCN-VER-76); SCN-VER-77 is
  `test_a_scenario_without_a_criterion_uses_the_parents_only_requirement` in `tests/unit/verifier/test_fixunit.py`.
- [x] 1.2 `fixunit._requirement_for`: a person-rejected finding with no criterion gets `<finding title> — finding <id>`
  in the parent's first capability by name.

## 2. Docs

- [x] 2.1 `docs/SPEC.md` (L4-VER-006, SCN-VER-76, SCN-VER-77, change row 31), `CHANGELOG.md`.
