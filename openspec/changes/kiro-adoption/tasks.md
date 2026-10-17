Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Kiro provider (L4-KSP-006)

- [ ] 1.1 Tests: SCN-ODD-10 .. SCN-ODD-15 in `tests/unit/specs/`.
- [ ] 1.2 `specs/kiro.py`: done leaves warn; a non-JSON graph block warns; whole-requirement references resolve; both
  heading levels; references only as standalone numbers.

## 2. Docs

- [ ] 2.1 `docs/SPEC.md` (L4-KSP-003 text, L4-KSP-006 after L4-KSP-005, SCN-ODD-10..15 after SCN-ODD-09, a change row
  after the last), `CHANGELOG.md` under `## 0.4.13 (unreleased)` (create it if missing).
