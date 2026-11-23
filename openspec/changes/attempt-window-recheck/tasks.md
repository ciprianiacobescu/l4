Read `design.md` first (D1-D5). Requirements: L4-IMP-104, L4-IMP-105, L4-VER-082 and the L4-IMP-075 amendment
(`docs/SPEC.md`), scenarios SCN-IMP-566..576 and SCN-VER-322..323. Run single test files only (`uv run --frozen pytest
<file> -q`), never a whole directory, never two runs at once, and never a wait loop on `pgrep`. Use the bench of
`tests/unit/implementer/test_loop.py` (`make_bench`, `test_seed_attempts_reads_the_window`,
`test_seeded_failures_reach_max_task_attempts`) for the attempt window, and the delegate grants of
`tests/unit/implementer/test_unfreeze_delegate.py` for an answer that unfreezes. Stub gate runs as
`tests/unit/implementer/test_tdd_green.py` and `test_tdd_red.py` do; a re-run is the second call of `wb.run_gate` with
the name `test-recheck`.

## 1. An answer renews the green window (L4-IMP-104, D1)

- [x] 1.1 Write the tests first in a new `tests/unit/implementer/test_attempt_renewal.py`:
  - SCN-IMP-566: two `task.attempt_failed{phase: green}`, a question raised by green attempt 3, a delegate accept that
    unfreezes `e2e/test_layout.py` (`delegate.unfreeze: true`): `run_task` records `task.attempts_renewed{task, phase:
    green, questions: [Q-001], failed: 2}` before the first green step, the step's attempt is 3, and three more failed
    attempts are needed for `breaker.tripped`;
  - the same with a person's answer (`by: human`) and with an agent's (`by: agent`);
  - SCN-IMP-567: a second run with the same answer records no second renewal (`seed_attempts` clears at the first
    event, so the failures after it count); an answer that an earlier `task.unfrozen{reason: human_answer, question:
    "Q-001, Q-002"}` of the task names (split on `", "`) is credited and renews nothing;
  - SCN-IMP-568: an answer that names no frozen file, a delegate accept with `delegate.unfreeze: false`, and a
    `named_by_task` grant renew nothing;
  - SCN-IMP-569: two renewals with `failed > 0` after the newest `unit.resumed` and a third new question: no event, a
    warning, the breaker trips as before; one more `unit.resumed`: the cap count starts again;
  - a renewal with `failed: 0` is recorded and does not count toward the cap;
  - `seed_attempts` keeps `attempts["green"]` across a renewal (the step key is used once), and clears
    `escalated_from["green"]`; `deadline.stops` and `deadline.last_is_stop` of the same ledger are unchanged;
  - SCN-IMP-570: a ledger with no `task.attempts_renewed` seeds exactly as before; an unused 0.4.59 answer renews,
    one a 0.4.59 green used (its `task.unfrozen` is in the ledger) does not;
  - with two profiles in `roles.implementer` and `escalate_after: 2`, a renewal clears both profiles' counts and the
    move, and the phase starts on the run's selected profile.
  Run the file and see the new tests fail.
- [x] 1.2 Then add `MAX_RENEWALS = 2` and `_renew_on_answers` to `src/l4/implementer/loop.py`, call it in `_run_task`
  after `resume_red` when `start == "green"` (before `origin` and `_escalate_while_due`) and after a red commit of the
  run, and add the clearing rule to `seed_attempts`. Do not change `src/l4/deadline.py`. Run the new file, then
  `tests/unit/implementer/test_loop.py`, `tests/unit/implementer/test_escalate_spent_profiles.py` and
  `tests/unit/implementer/test_unfreeze_delegate.py`, one at a time.

## 2. The re-run of regressed pre-existing tests (L4-IMP-105, D2, D3)

- [x] 2.1 Write the tests first:
  - in a new `tests/unit/implementer/test_recheck.py` (pure): `recheck_candidates` for 1 and 5 ids (yes), 6 ids, a
    missing id, a time-out marker, a test in a changed file (no); `gate_repeat.untouched` with a TypeScript id among
    `.ts` files only, as `pre_existing` does; `tests/unit/verifier/test_gate_repeat.py` passes unchanged;
  - in a new `tests/unit/implementer/test_step_recheck.py`: SCN-IMP-571 (green: the re-run passes the test, the task is
    committed, `task.tests_rechecked{stopped: passed}`, `keep_tested` got the merged report); SCN-IMP-572 (it fails
    again: the reason ends with `; failed again on a re-run (L4-IMP-105): <id>`); SCN-IMP-573 (no `test-recheck` call
    for each case); SCN-IMP-574 (`stopped: budget` with an armed deadline, `stopped: tree` when `tree_reset` gives
    None); SCN-IMP-575 (red with `tampered` checked after the re-run, and a fix chore through `run_single`);
    SCN-IMP-576 (`new_failures`); a `new failing tests added in green` found on the merged report still fails the
    attempt; a `_run_repair` step makes no re-run.
  Run both files and see the new tests fail.
- [x] 2.2 Then: `untouched` and a public `short_of_time` in `src/l4/verifier/gate_repeat.py` (`pre_existing` and
  `settle` use them, same behaviour); the new `src/l4/implementer/recheck.py` (`recheck_candidates`, the re-run, the
  merged report, the event); `RedVerdict.regressed` and the branch marker of `green_failures` in
  `src/l4/implementer/tdd.py`; the calls in `run_red` (after `classify_red`), `run_green` and `run_single` (after
  `green_failures`), each taking `tree_reset` before run 1 and running its guard after the re-run. Run the files of
  2.1, then `tests/unit/implementer/test_tdd_green.py`, `tests/unit/implementer/test_tdd_red.py`,
  `tests/unit/implementer/test_single_phase.py` and `tests/unit/implementer/test_red_preexisting_tests.py`, one at a
  time.

## 3. Verification lists them (L4-VER-082, D4)

- [x] 3.1 Write the tests first in a new `tests/unit/verifier/test_report_step_flakes.py`: SCN-VER-322 (a ledger with
  `task.tests_rechecked{stopped: passed, flaky: [...]}`, one of a fix unit: `VerifyResult.step_flakes`, the section of
  `verification.md`, `verdict.json`'s `step_flakes`, and `restore_round` keeps it); the 20-line cap; SCN-VER-323 (no
  section, and the verdict and findings are equal to those of the same round without the events). Run it and see the
  new tests fail.
- [x] 3.2 Then add `VerifyResult.step_flakes` (`src/l4/verifier/types.py`), its builder next to `_guards`
  (`src/l4/verifier/ladder.py`), the section and the `verdict.json` key (`src/l4/verifier/report.py`) and the restore
  (`src/l4/verifier/evidence.py`). Run the new file, then `tests/unit/verifier/test_report.py`, one at a time.

## 4. Checks

- [x] 4.1 `docs/SPEC.md` holds L4-IMP-104, L4-IMP-105, L4-VER-082, the L4-IMP-075 amendment, SCN-IMP-566..576,
  SCN-VER-322..323 and change-table row 140. Check them against the code and tell the orchestrator where they differ;
  do not edit `docs/SPEC.md`, `CHANGELOG.md` or `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py
  docs/SPEC.md`.
- [x] 4.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.

## 5. Review fixes

- [x] 5.1 A test that failed in run 1 and is skipped in the re-run is not flaky: the attempt fails (SCN-IMP-572,
  `test_step_recheck.py`). Nothing in the code changed.
