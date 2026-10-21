Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Implementer (L4-IMP-025)

- [x] 1.1 Tests: `tests/unit/implementer/test_import_roots.py` (SCN-IMP-211..215, and a head stub in a member for
  run (b)).
- [x] 1.2 `discrimination.import_roots`; `_resolve` returns every match under the roots; `imported_modules` uses them.

## 2. Docs

- [x] 2.1 `docs/SPEC.md` (L4-IMP-025 next to the pre-satisfied paragraph of L4-IMP-002, the scenarios, the change
  row), `CHANGELOG.md`.
