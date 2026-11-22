Read `design.md` first (D1-D7). Requirement: L4-VER-086 (`docs/SPEC.md`), scenarios SCN-VER-343..349 and SCN-VER-351.
This change is SLIPPABLE: it and `ui-hold-evidence` need nothing of each other (both touch `types.py`, `report.py`,
`generate.py` and `fixunit.py`, in different functions), and it can be left out at integration. Then also remove all of
its text, and nothing else:
- `docs/SPEC.md`: the requirement L4-VER-086 with its `[V, …]` note; its sentence in L4-VER-067 (`, except a criterion
  carried from the base, which raises none (L4-VER-086)`); its sentence in the step-5 row of 10.2 (`A UI criterion
  unchanged on the base whose only tracing tests are passing `pass_to_pass` tests … is **carried from the base** …
  (L4-VER-086).`); the `status: carried` clause of `verify.generated` in 12.1; row 141 of the change table; the
  scenarios SCN-VER-343 to SCN-VER-349 and SCN-VER-351;
- `CHANGELOG.md`: the bullet under Changed that starts `A UI criterion that a unit did not change is carried from the
  base`;
- `docs/runbook.md`: the paragraph that starts `From 0.4.60 a UI criterion that the unit did not change`;
- `openspec/changes/ui-carry-unchanged/` (the folder);
- the code and tests of the change are its own commits (`git log --format=%h\ %s 62188257..HEAD | grep ui-carry`
  and the commits that name L4-VER-086 or the carry): revert them, not the commits of `ui-hold-evidence`.
Run single test files only (`uv run --frozen pytest <file> -x -q`), never a whole directory, never two runs at once, and
never a wait loop on `pgrep`.

## 1. The rule (D1)

- [x] 1.1 Write the tests first in `tests/unit/verifier/test_ui_step.py`: `carried_from_base` carries the criterion of
  SCN-VER-343 and none of the variants of SCN-VER-344..347 (a criterion not in `unchanged`; a tracing test with a red,
  audit, human, chore, repair or generated proof; a `pass_to_pass` test that failed, is skipped, has a `note` or is
  over the cap; an ignored test that is not a passing over-cap candidate; a test whose file `file_of` does not find; a
  file in `changed`; a criterion in `rejected`); `rejected_ui_criteria` finds a reject of the criterion, of a UI hold
  named by `question.raised{criterion}`, of the stable hold id with no such event, and a consumed one; an accept is not
  a reject. Run and see them fail.
- [x] 1.2 Then add `carried_from_base`, `carry_file` and `rejected_ui_criteria(events, criteria)` to
  `src/l4/verifier/ui_step.py` (pure, no git). Run
  `tests/unit/verifier/test_ui_step.py`.

## 2. Step 5 and what it records (D2, D3)

- [x] 2.1 Write the tests first:
  - in `tests/unit/verifier/test_ui_flow.py` (follow its stubs of the e2e gate and the writer): SCN-VER-343 (no writer
    request for C, the `verify.generated` event, no hold, the finding's detail, no base checkout when C is the only
    gap, and with another gap the writer is asked for that one only and no UI hold comes back for C after the judge
    step); SCN-VER-345 and SCN-VER-347 through the ladder;
    SCN-VER-348 (a judge reply that calls `test_c` inadequate: C is `needs_human` and its criterion question is raised);
    the carry happens with `roles.verifier_agent` empty too;
  - in `tests/unit/verifier/test_report_m15.py`: the row of a `carried` outcome (and not the `covered by step 4` text);
  - in `tests/unit/verifier/test_resume.py`: SCN-VER-349 (a reused round restores `carried`, asks no writer, raises no
    hold);
  - in `tests/unit/verifier/test_fixunit.py`: a PASS round with `fix_minor_findings` makes no task for a carried gap.
  Run each file and see the new tests fail.
- [x] 2.2 Then add `carried` to `GenStatus` (`src/l4/verifier/types.py`); keep `_Run.unchanged` in `traceability`,
  split the test-to-file mapping out of `_test_blobs`, and carry in `_generate_step` before `gap_findings`
  (`src/l4/verifier/ladder.py`); `carried=` in `ui_gap_finding` (`src/l4/verifier/generate.py`) and `gap_findings`;
  the closed set of `unclosed_holds` (`src/l4/verifier/ui_step.py`; leave `lost_notes` as it is, design D3) and of
  `_candidates` (`src/l4/verifier/fixunit.py`); the row in `_generated_rows` (`src/l4/verifier/report.py`). Run the
  files of 2.1, then `tests/unit/verifier/test_generate.py`, `tests/unit/verifier/test_hold_binding.py` and
  `tests/unit/verifier/test_ladder_hold_fix.py`, one at a time.

## 3. Checks

- [x] 3.1 `docs/SPEC.md` holds L4-VER-086, SCN-VER-343..349, change-table row 141 and the amendments named above. Check
  them against the code and tell the orchestrator where they differ; do not edit `docs/SPEC.md`, `CHANGELOG.md` or
  `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [x] 3.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
