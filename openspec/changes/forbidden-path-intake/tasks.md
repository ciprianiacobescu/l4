## 1. Matching and finding (L4-YOLO-092)

- [ ] 1.1 Write the tests first (`tests/unit/security/test_protected.py`; `tests/unit/delegate/test_reply_0421.py` for
  `named_paths`). Then add `forbidden_rule` (design D1), move `named_paths` to a neutral module with a re-export from
  `l4.delegate.reply`, and add the pure `forbidden_named` (design D2). Cases: SCN-YOLO-246, -248, -249, -250 at the
  function level (a missing migration → blocker with the message; existing file → warning; ticked task, negated line
  → nothing; directory token, design mention → warning; contract glob → no config fix); `named_paths` gives the same
  results after the move.

## 2. Where it runs (L4-YOLO-092)

- [ ] 2.1 Write the tests first (`tests/unit/yolo/test_yolo_admit_admission.py`, `tests/unit/yolo/test_yolo_check_worktree.py`,
  `tests/unit/yolo/test_yolo_validate_plan.py`). Then pass the forbidden globs and a `tree_has` into `plans.intake` /
  `unit_infos` (design D3, plan side) and print warnings in `l4 yolo check` and `l4 yolo go`. Cases: SCN-YOLO-246 and
  -247 end to end through `l4 yolo check`; warnings printed with exit 0.
- [ ] 2.2 Write the tests first (`tests/unit/orchestrator/test_openspec_intake_validation.py`,
  `tests/unit/orchestrator/test_kiro_unit.py`). Then run `forbidden_named` in `_lint_scenarios` for both frameworks in
  the intake phases (design D3, unit side). Cases: SCN-YOLO-251 (OpenSpec and Kiro; exit 14; no agent step); a unit
  in `implementing` is not rejected.

## 3. The notes (L4-IMP-006, L4-IMP-015)

- [ ] 3.1 Write the tests first (`tests/unit/implementer/test_guard_notes.py`, `tests/unit/implementer/test_unfreeze_note.py`).
  Then implement design D4 and D5. Cases: SCN-IMP-423; SCN-IMP-424 (after a removal in the attempt, and for a question
  that names a forbidden path without a removal); a question with no forbidden path keeps today's unfreeze note.

## 4. Checks

- [ ] 4.1 Run `tests/unit/security`, `tests/unit/delegate`, `tests/unit/yolo`, `tests/unit/implementer` and
  `tests/unit/orchestrator` once with pytest (never in a loop) and wait for them to finish. Run ruff check and ruff
  format on the changed files. Report the counts.
