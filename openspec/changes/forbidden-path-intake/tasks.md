## 1. Matching and finding (L4-YOLO-092)

- [x] 1.1 Write the tests first (`tests/unit/security/test_protected.py`; `tests/unit/delegate/test_reply_0421.py` for
  `named_paths`). Then add `forbidden_rule` (design D1), move `named_paths` to a neutral module with a re-export from
  `l4.delegate.reply`, and add the pure `forbidden_named` (design D2). Cases: SCN-YOLO-246, -248, -249, -250 at the
  function level (a missing migration → blocker with the message; existing file → warning; ticked task, negated line
  → nothing; directory token, design mention → warning; contract glob → no config fix); `named_paths` gives the same
  results after the move.

  Result: added `forbidden_rule` to `l4.security.protected` (the prefix walk, shared with `ProtectedSet.match` through
  `_first_glob`; `match` gives the same results), moved `names_path` and `named_paths` to the new `l4.specs.paths`
  (both, because `named_paths` needs `names_path` and `l4.specs` must not import `l4.implementer`; `l4.delegate.reply`
  and `l4.implementer.unfreeze` import them from there, so their callers and tests keep working), and added the module
  `l4.yolo.forbidden` with `PathFinding` and `forbidden_named(ref, tree_has, globs)`. Deviation from the signature in
  design D2: it takes the unit's `UnitRef` (framework and folder) instead of a bare `unit_dir`, because tasks are
  parsed per framework. A line that says not to touch the path gives nothing (not a warning). Failed before (import
  errors: no `forbidden_rule`, no `l4.specs.paths`, no `l4.yolo.forbidden`), pass now: 8 cases in
  `test_protected.py`, 1 in `test_reply_0421.py`, 20 in `test_yolo_forbidden_named.py`.

## 2. Where it runs (L4-YOLO-092)

- [x] 2.1 Write the tests first (`tests/unit/yolo/test_yolo_admit_admission.py`, `tests/unit/yolo/test_yolo_check_worktree.py`,
  `tests/unit/yolo/test_yolo_validate_plan.py`). Then pass the forbidden globs and a `tree_has` into `plans.intake` /
  `unit_infos` (design D3, plan side) and print warnings in `l4 yolo check` and `l4 yolo go`. Cases: SCN-YOLO-246 and
  -247 end to end through `l4 yolo check`; warnings printed with exit 0.

  Result: `plans.intake` and `plans.unit_infos` take `forbidden` (`odd.forbidden_paths`, with `extra_forbidden_paths`
  already applied by the config); the `tree_has` is the existence of the path in the checkout the units are read from
  (the working tree, or the temporary worktree of the revision checked), so no new parameter was needed for it. A
  blocker joins the other reasons in `UnitInfo.intake_detail` (so `admit` gives the `intake` finding with the
  `forbidden_path:` text), warnings go to the new `UnitInfo.warnings` and are printed as `warning: forbidden_path:
  <unit>: ...` after the order line by `l4 yolo check`, `check --worktree` and in the `check` step of `l4 yolo go`
  (exit unchanged). The CI review (`cycle.py`), `review`, `activate` and `go` get the rule through the same
  `unit_infos` call. Failed before: 6 of the 10 new cases in `test_yolo_admit_admission.py`, `test_yolo_check_worktree.py`
  and `test_yolo_commands_check.py` (the others pass by design: a narrowed list, a negated line); all pass now, with
  the `go` case and the validator-unchanged case (design D6) in `test_yolo_go_activate.py` and `test_yolo_validate_plan.py`
  added in the same task (these two were not run before the implementation). The 345 tests of the six touched yolo test
  files pass.
- [x] 2.2 Write the tests first (`tests/unit/orchestrator/test_openspec_intake_validation.py`,
  `tests/unit/orchestrator/test_kiro_unit.py`). Then run `forbidden_named` in `_lint_scenarios` for both frameworks in
  the intake phases (design D3, unit side). Cases: SCN-YOLO-251 (OpenSpec and Kiro; exit 14; no agent step); a unit
  in `implementing` is not rejected.

  Result: `Orchestrator._forbidden_reasons` runs `forbidden_named` on the unit's worktree (a path exists when it is in
  the worktree) with `cfg.odd.forbidden_paths`, only in `_OPENSPEC_INTAKE_PHASES`, and `_validate_openspec` and
  `_validate_kiro` add its blockers to their reasons, so one `unit.rejected` (exit 14, before any agent step) lists the
  validation errors and the forbidden path. It sits in those two validators rather than in `_lint_scenarios` itself,
  which only calls them, so the Kiro and OpenSpec paths share one rejection. A unit awaiting a person is not rejected.
  Failed before (without the orchestrator change): 3 of the 5 new cases (OpenSpec rejection, OpenSpec reasons together
  with a validation error, Kiro rejection); the other 2 (an `awaiting_human` unit, a "do not" line) pass by design.
  All 16 tests of the two files pass now.

## 3. The notes (L4-IMP-006, L4-IMP-015)

- [x] 3.1 Write the tests first (`tests/unit/implementer/test_guard_notes.py`, `tests/unit/implementer/test_unfreeze_note.py`).
  Then implement design D4 and D5. Cases: SCN-IMP-423; SCN-IMP-424 (after a removal in the attempt, and for a question
  that names a forbidden path without a removal); a question with no forbidden path keeps today's unfreeze note.

  Result: `note_of` takes the `odd.forbidden_paths` globs (`Workbench.emit` passes `protected.odd_forbidden`) and marks
  a violation under one of them (`GuardNote.forbidden`); `guard_note_text` gives it the D4 advice (named per path, at
  most 3) instead of the generic one. `forbidden_note` in `l4.implementer.unfreeze` is the D5 note, and `_with_note`
  uses it for a technical question when this attempt's guard notes hold a forbidden removal or the question names a
  path `forbidden_rule` matches (red, green and single steps; before the fix-chore note). Deviations from D5: the
  sentence "unfreezing a test does not help" is left out, because SCN-IMP-424 says the note does not mention
  unfreezing a test (the note says "no answer changes that"); for a contract path (CI files) the note does not offer the
  config fix, as at intake. Failed before: `test_unfreeze_note.py` did not import (no `forbidden_note`) and the new
  cases of `test_guard_notes.py` failed on the unknown `forbidden` argument; all 41 tests of the two files pass now.

## 4. Checks

- [x] 4.1 Run `tests/unit/security`, `tests/unit/delegate`, `tests/unit/yolo`, `tests/unit/implementer` and
  `tests/unit/orchestrator` once with pytest (never in a loop) and wait for them to finish. Run ruff check and ruff
  format on the changed files. Report the counts.

  Result: one run of the five directories (4138 tests, 3 h 9 min): 4137 passed, 1 failed
  (`test_yolo_status_activity.py::test_read_units_collects_activity_from_snapshots`: its stub config is `None`, and
  `_read_units` read `cfg.odd` even for `intake=False`). Fixed by reading the forbidden globs only when the intake
  checks run (`intake=True`); that test and `test_yolo_commands_check.py` pass again (22 passed). The other
  directories' tests were not rerun after the fix (the change is one line in `_read_units`). `ruff check` passes on the
  26 changed Python files; `ruff format --check` passes on 25, and `tests/unit/security/test_protected.py` was already
  unformatted before this change (three older blocks), so it was left as it was.

- [x] 4.2 Review fixes: a `./` before a negated path; the question note only when no frozen test is the subject; tracked
  existence instead of files on disk; the plan-side phase gate; tokens that are not repository paths; a task that says a
  person delivers the file.

  Result: (1) `_negated` accepts a `./` before the path. (2) D5 changed (design, `L4-IMP-015` amendment, SCN-IMP-425):
  the forbidden note replaces the unfreeze note after a forbidden removal in the attempt, or for a missing forbidden path
  the question names when its first option names no frozen file; a question that only mentions an existing forbidden
  file keeps the unfreeze note. (3) `TreeIndex`/`tracked_tree` in `l4.yolo.forbidden`: existence is read from the
  tracked files (`git ls-tree -r` of the revision on the plan side, `git ls-files` for `--worktree`, `HEAD` of the
  unit's worktree on the unit side), with the disk as fallback only when git cannot be read. (4) `unit_infos` applies
  the blocker only for the phases none, `intake` and `ready` (a warning otherwise); the unit-side test now covers every
  later phase, `implementing` included. (5) Host-like first segments are skipped; a name tracked one directory deeper is
  a warning (monorepo). (6) "a person commits", "committed by a person" and "a person adds" exempt the line, and the
  blocker names the rewording way out. Design D2, D3, D5, the spec (requirement text, SCN-YOLO-252 to 254, SCN-IMP-425)
  and the proposal's scenario list are amended. Failed before: 12 cases in `test_yolo_forbidden_named.py` and
  `test_yolo_plans_forbidden.py` (the `TreeIndex` import existed from the start, so those ran against the old rules),
  and 6 in the check, orchestrator and unfreeze-note files; 297 tests of the 13 focused files pass now.
