Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Verifier (L4-VER-017)

- [ ] 1.1 Tests: `tests/unit/verifier/test_judge_accepted.py` (SCN-VER-68), `test_judge_run.py` (SCN-VER-69,
  SCN-VER-70, SCN-VER-71).
- [ ] 1.2 `JudgePrompt.accepted_ids` and `feedback_ids`, the second call in `run_judge`, the carried rows in
  `_resume`.

## 2. Delivery plans (L4-YOLO-031)

- [ ] 2.1 Tests: `tests/unit/yolo/test_yolo_cycle_auto.py` (SCN-YOLO-73, the report line),
  `test_yolo_commands_waive.py` (SCN-YOLO-74), the status `Next:` line (SCN-YOLO-75), the plan fold.
- [ ] 2.2 `plan.finding_waived` and `plan.waiver_withdrawn` in the fold (`PlanState.waived`), `_accepted_open`,
  `_accepted_lines`, `_next_line`, `run_waive` and the `yolo waive` command.

## 3. Docs

- [ ] 3.1 `docs/SPEC.md` (L4-VER-017, L4-YOLO-031, the scenarios, the command table, the change row),
  `docs/runbook.md` (the `accepted_finding_open` row), `docs/yolo-mode.md`, the skill's `plan.md`, `CHANGELOG.md`
  (`## 0.4.7 (unreleased)`).
- [ ] 3.2 `openspec validate answer-accepted-findings --strict`.
