Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check`,
  `ruff format --check` and `mypy src`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Verifier (L4-VER-016)

- [ ] 1.1 Tests: `tests/unit/verifier/test_verdicts.py` (SCN-VER-64, SCN-VER-65), `test_fixunit_feedback.py`
  (SCN-VER-66, plan level), `test_hold_verdicts.py` (SCN-VER-67).
- [ ] 1.2 `effective_verdicts` (read time, D1) and `plan_fix_unit` / `_candidates` (write time, D2).

## 2. Operator commands (L4-OPS-022)

- [ ] 2.1 Tests: `tests/unit/state` next-step tests (SCN-OPS-38, SCN-OPS-39), the refusal of `l4 run --unit`, and
  the sticky note.
- [ ] 2.2 `UnitFacts.halt_reason`, `next_step`, `_refuse_stopped`, `halted_section`.

## 3. Questions (L4-QMD-010)

- [ ] 3.1 Tests: `tests/unit/specs/test_questions_cli.py` (SCN-QMD-26, SCN-QMD-27), `test_verdicts.py` (SCN-QMD-28).
- [ ] 3.2 `--replace` in `cli.py`, `questions_cli.py`, `QuestionsFile.replace_answer`.

## 4. Docs

- [ ] 4.1 `docs/SPEC.md` (L4-VER-016, L4-OPS-022, L4-QMD-010, the scenarios, the change row), `docs/runbook.md`, the
  skill reference, `CHANGELOG.md` (`## 0.4.6 (unreleased)`).
- [ ] 4.2 `openspec validate settle-human-rejects --strict`.
