Read `design.md` first (D1-D5). Requirements: L4-VER-079, L4-VER-080, L4-VER-081 (`docs/SPEC.md`), scenarios
SCN-VER-312..321. Run single test files only (`uv run --frozen pytest <file> -q`), never a whole directory, never two
runs at once, and never a wait loop on `pgrep`. Build the git histories as `test_support_files_changed_by_infra_or_people_are_kept_at_head`
and `test_the_run_keeps_them_at_head_and_lists_them` in `tests/unit/verifier/test_base_tests.py` do (harness commits
with `L4-Unit`, `L4-Task` and `L4-TDD` trailers, ledger events in the `IntegrityContext`). Secrets in tests: use a token
shape the redactor knows (`"glpat-" + "A1b2C3d4E5f6G7h8I9j0"`). Requirement L4-VER-079 is slippable: keep its code in
`_named_red_change` and its tests in their own module, so that it can be cut alone.

## 1. A named support file stays at head (L4-VER-079, D1)

- [x] 1.1 Write the tests first in a new `tests/unit/verifier/test_base_tests_named_support.py`:
  - SCN-VER-312: `kept_files` keeps `test/arch/modules.ts` (at the base and at head, changed by the `L4-TDD: red`
    commit of task 1.1, `task.unfrozen{reason: named_by_task, red_sha: <that sha>, source: plan:p@d, paths: [], kept:
    [{path, why: "a red test of this task"}]}`) with the reason `task 1.1: changed by its red step, named by its
    reviewed text (plan:p@d)`; `check_base_tests` (gate stubbed as in `test_the_run_keeps_them_at_head_and_lists_them`)
    lists it in `allowed_tests` and not in `reverted`;
  - the same with the path in `paths` instead of `kept`;
  - SCN-VER-313: a second red commit of task 1.2 with no event naming it, a green commit of task 1.1, or a fix unit's
    commit: reverted;
  - SCN-VER-314: an ignore file, a file red added, `test/arch/repo.test.ts` (a test module by `is_support_file`), an
    event whose `red_sha` is another commit, an event with no `source`, a named file whose `--numstat` counts 60
    lines and a binary one (reverted), and a fourth named file (the first three in path order are kept, the note
    counts one more);
  - SCN-VER-315: a Python file matching `**/tests/**` and `**/tests/helpers/**`, named and changed by red with a
    pre-existing test changed in it: `integrity.check_tests` still blocks it (`_allowance` is unchanged);
  - SCN-VER-316: the events of a 0.4.59 ledger (no new key) give the same kept reason.
  Run the file and see the new tests fail.
- [x] 1.2 Then add `MAX_NAMED_SUPPORT = 3`, `MAX_NAMED_SUPPORT_LINES = 40` and `_named_red_change(ctx, who, path, by_sha)` to
  `src/l4/verifier/base_tests.py` and call it from `kept_files` after `_allowance`, with a per-task count for the cap
  and the note of D1. Update the `kept_files` docstring (what reads a harness change to a support file now). Do not
  change `integrity._allowance`, `_unfrozen_source` or `split_allowed`. Run the new file, then
  `tests/unit/verifier/test_base_tests.py` and `tests/unit/verifier/test_integrity.py`, one at a time.

## 2. The blocker's text and its records (L4-VER-080, D2)

- [x] 2.1 Write the tests first:
  - in `test_base_tests_named_support.py`: SCN-VER-317 (the lead text of both blocker titles, at most 5 support files,
    `(a person)` for a file only people changed, the tasks of the harness commits; no lead with no reverted support
    file, and the detail is then byte for byte as before); `verify.base_tests` carries `support_reverted` (at most 20);
    the blocked failing ids have `failures` records with `gate: base-tests`, `kind`, `message` and an `excerpt`
    (`Outcome.failures`); SCN-VER-319's token is in no record;
  - in `tests/unit/verifier/test_failures_block.py`: `shown_failure_ids(failures, BASE_FAILS_TITLE, detail)` gives
    every `base-tests` record; `failing_ids(failures, "test")` and `finding_test_ids` ignore them;
  - in `tests/unit/verifier/test_failures_map.py`: `failure_records(..., unit_gate="base-tests")` writes that gate and
    keeps the 200-record cap; without the keyword the records are exactly as before;
  - SCN-VER-318 in `tests/unit/implementer/test_fix_failure_excerpt.py` (its bench and `seed_round`): a stored round
    whose finding is `a pre-existing test fails on the unit's code` and whose record has `gate: base-tests` and an
    excerpt: the fix chore's first prompt holds the block with the excerpt line.
  Run each file and see the new tests fail.
- [x] 2.2 Then: `BASE_FAILS_TITLE` and the branch in `shown_failure_ids` (`src/l4/verifier/failures.py`;
  `base_tests.FAILS_TITLE` imports it); `unit_gate` in `failure_records` (`src/l4/verifier/gates.py`);
  `Outcome.failures` (`src/l4/verifier/integrity.py`); in `check_base_tests` the `support_reverted` list, the lead text,
  the records (with `case_excerpt` as `ladder.tests()` builds it) and `_emit(..., support_reverted=...)`; in
  `ladder.integrity()` copy `ran.failures` into `result.failures`. Run the files of 2.1, then
  `tests/unit/verifier/test_ui_flow.py`, `tests/unit/verifier/test_fixunit.py` and
  `tests/unit/verifier/test_repair_integrity.py`, one at a time.

## 3. The escalation (L4-VER-081, D3)

- [x] 3.1 Write the tests first in `tests/unit/verifier/test_fixloop_escalation.py` (or a new
  `test_fixloop_base_tests.py` next to it, with the round fixtures `repeated_failure` tests use): SCN-VER-320 (two
  stored FAIL rounds with the same `finding <id>` of `a pre-existing test fails on the unit's code`, a
  `verify.base_tests{round: 2, support_reverted: [{path: test/arch/modules.ts, tasks: [1.1, 1.2], people: false}]}`:
  the escalation's reason starts with the way-out text and holds the `same_failure` detail, cut at 300 characters for
  the way-out part, code `same_failure`); SCN-VER-321 (a `test gate failed` repeat, and a `verify.base_tests` without
  `support_reverted`: the reason is as before); the reason with a unit id of 40 characters, put through the exit
  reason's form (`escalated: <detail>. Next: l4 retry --unit <u> --reason TEXT`, cut at 300), still holds `then l4
  retry:`. Run it and see the new tests fail.
- [x] 3.2 Then add `base_tests_way_out(events, round_no)` to `src/l4/verifier/fixloop.py` and use it in the
  `same_failure` branch (703-704) when the round's blocking findings hold `FAILS_TITLE` or `GONE_TITLE`. Run the file,
  then `tests/unit/verifier/test_fixloop.py` and `tests/unit/verifier/test_fixloop_escalate.py`, one at a time.

## 4. Checks

- [x] 4.1 `docs/SPEC.md` holds L4-VER-079..081, SCN-VER-312..321 and change-table row 136. Check them against the code
  and tell the orchestrator where they differ; do not edit `docs/SPEC.md`, `CHANGELOG.md`, `docs/runbook.md` or the
  skill. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [x] 4.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
