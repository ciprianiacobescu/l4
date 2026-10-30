## Context (verified on fix-0445 = v0.4.44, read-only analysis of 2026-10-30)

- `run_single` (src/l4/implementer/tdd.py ~2310): `base = wb.head()`; `baseline(...)` runs the unit test gate; for kind
  `fix` the else branch puts edits back (~2368-2371: `restore_frozen` + `freeze_test_paths`, the local `put_back`);
  the only gate after is `gates.test` (~2376); `green_failures(base_report, [], gate)` (~2378) has an empty must-pass
  list; then the static, CI-step and outside-link checks, `set_marker DONE` (~2430), commit, `task.tdd_exempt`. No
  "nothing changed" rule for kind `fix` (refactor ~2363-2367, tests ~2385-2389 have one). `chore_ci_job(...)` is the CI
  job of a D11/D12 chore; D11 (openspec/changes/ci-evidence/design.md ~284) keeps committing a put-back chore and D12's
  `ci_not_fixed` reads `put_back` from `phase: single` guard events.
- The e2e runner: `run_e2e(wb, worktree=None, *, name, must_contain, extra_env)` (src/l4/gates/e2e.py ~127); the
  verifier runs setup, build, lint, typecheck (src/l4/verifier/gates.py ~95-103) and then `run_e2e_gate` (~174-180).
  `run_single` runs only `run_setup` (`gates.setup`, tdd.py ~541-556); no implementer code runs `gates.build`.
  `ServerNotReady` raises `L4Exit(INTERNAL_ERROR)` (e2e.py ~191-192). The server and seeding come from the gate's own
  launcher.
- Findings: "e2e gate failed" = `_judged` (verifier/gates.py ~136-139, failing names cut at 5) + `_blocker` (~84-87, the
  e2e log, no criterion); "new tests failed" = `check_tests_ran` (src/l4/evidence/testsran.py ~115, names cut at 5, no
  log), called from collect.py ~321 via `_collect_step` (ladder.py ~816-841) on `_merged(...)` (ladder.py ~692). Ids are
  `finding_id(title, criterion)` (types.py ~79-81), stable across rounds.
- `tests()` (ladder.py ~676-697) holds `out.report` and `browser.report` (`TestReport`, `TestCase.failure_kind`,
  `.message`, `.status`, junit.py ~38-49). `verdict_json` (verifier/report.py ~358-384). Do not change the `tests` values
  (`failure_set` fixloop.py ~557 and `restore_round` evidence.py ~183 read them as strings) and do not add keys inside
  `tests_ran.summary` (`TestsSummary(**...)`). `read_verdict` (verifier/evidence.py ~97); the fix unit's parent round is
  in the ledger (`fix.spawned.verify_round`).
- Candidates of a fix unit: `fixunit._candidates`, `key = criterion or f.id` (fixunit.py ~214).

## 1. The failures map (L4-VER-069)

- [x] 1.1 Write the tests first (the verifier report/verdict tests: find them with `grep -rln "verdict_json\|read_verdict"
  tests/unit`): SCN-VER-254, and that `read_verdict` of an old verdict without `failures` still works. Then build the map
  in `tests()` from both reports (gate `test` for the unit report, `e2e` for the browser report; status failed or
  errored), pass it to `verdict_json` as a new top-level key `failures: {id: {gate, kind, message}}` (first line,
  `wb.redactor.redact_text`, 200 characters), and expose it from `read_verdict`.

  Result: Added `failure_records(unit, browser, redact)` and `MAX_FAILURE_CHARS = 200` to `l4.verifier.gates`: for each
  failed or errored test of the unit report (gate `test`) and the browser report (gate `e2e`, which wins for an id both
  hold) it gives `{gate, kind, message}`, the message being the redacted first line cut to 200 characters. `kind` is the
  JUnit reader's `failure_kind`; where the reader gives none (an error of no known shape, a failure with no message
  shape) the record says `error` for status error and `other` for status failed, so the key is never empty. `tests()` in
  `l4.verifier.ladder` sets the new `VerifyResult.failures` (`l4.verifier.types`) from both reports and `verdict_json`
  writes it as the top-level `failures`; the `tests` map is unchanged. `read_verdict` already returns the whole stored
  object, so `failures` is exposed with no change to it; the new test shows an old verdict without the key is still read
  (a reader uses `.get("failures")`). Beyond the task text: `restore_round` (`l4.verifier.evidence`) copies `failures` too, so a reused NEEDS_HUMAN round keeps them. Tests: new `tests/unit/verifier/test_failures_map.py` (8) and one end-to-end test
  in `tests/unit/verifier/test_ui_flow.py` (a real e2e gate failing by assertion; the verdict holds gate `e2e`, kind
  `assertion`). Before: the new module failed at import (no `failure_records`), the ui-flow test failed (no `failures`
  key; run with the source changes stashed); after: 8 passed (with `test_resume_independence.py` 11), and `test_ui_flow.py` + `test_report.py` 25 passed.

## 2. The fix chore (L4-IMP-090, L4-IMP-017)

- [x] 2.1 Write the tests first (the fix-chore tests: `grep -rln "run_single\|kind=\"fix\"" tests/unit/implementer`):
  SCN-IMP-449 (a put-back-only attempt fails `nothing changed: …`; the same with a CI-job chore still commits; a retake
  keeps `_already_done`). Then add the rule in `run_single` for kind `fix` with `ci_job is None`: `put_back` non-empty and
  nothing else changed (`changed_files()` minus the ledger, tasks.md and the put-back paths is empty).

  Result: In `run_single` (`l4.implementer.tdd`), the `else` branch (kind `fix`) now fails the attempt with `nothing
  changed: the guard put back every edit (<paths>)` when `put_back` is not empty, no other path changed
  (`changed_files()` minus the put-back paths and `_reusable_change`: the ledger, `tasks.md`, held files) and the chore
  is not a CI job's (`ci_job is None`); it discards the tree first. A retake (`retake=True`) takes `_already_done`
  instead, as the refactor and tests branches do. A step that edited nothing at all (no put-back) keeps today's rule.
  Deviation: two existing tests wrote the unit's own `IMPL` again next to a put-back test edit, which is no change
  (green had written it already), so they now meet the new rule; `test_a_fix_chore_is_unchanged`
  (`test_single_phase.py`) and `test_a_fix_chore_loses_a_new_test_file_and_a_test_chore_keeps_it`
  (`test_test_path_freeze.py`) write a real product change (`IMPL` plus a comment) now. Tests (new, in
  `test_single_phase.py`): put-back-only fails and is not ticked (HEAD unchanged, `[ ] 1.2`); put-back plus a product
  change is done; an empty step is unchanged; a retaken put-back-only chore is `already-done`; a CI-job chore with the
  same put-back is committed. Before: the put-back-only test and the retake test failed (the task was ticked `exempt`);
  the other three passed as they pin unchanged behaviour. After: `test_single_phase.py` + `test_test_path_freeze.py`
  39 passed; `test_refactor_chore.py`, `test_outside_links.py`, `test_config_opened.py`, `test_baseline_reuse.py` 48 passed.
- [x] 2.2 Write the tests first: SCN-IMP-446, -447, -448 (stub `run_e2e` and the build runner the way the verifier's e2e
  tests do). Then, in `run_single` for kind `fix`: find the e2e ids of the task's findings from the parent round's
  verdict (`fix.spawned.verify_round` → `read_verdict` → `failures` with gate `e2e`, limited to the ids of this task's
  findings; a finding titled "e2e gate failed" takes all e2e failures of the round); when there are any, after the test
  gate run `gates.build` when configured (reuse the verifier's build runner) and `run_e2e(wb, name="e2e-chore",
  must_contain=ids)`; fail the attempt naming the ids that are missing or not passed; catch `ServerNotReady` (and the
  `L4Exit` it raises) as a failed attempt `the e2e server was not ready`. Record the e2e run like the other gates of the
  step (find how `run_single` records `gate.finished`).

  Result: New leaf module `l4.verifier.failures` (plain data, no harness imports, so `tdd` and `fixunit` can both use
  it): `failing_ids(verdict, gate)`, `named_test_ids(detail)` and `e2e_ids_of(verdict, finding_ids)` (a finding titled
  `e2e gate failed` takes all ids the round recorded under the e2e gate; `new tests failed` / `new tests errored` take
  those of them that its detail names). `l4.verifier.gates` got `run_build_only(wb)` (`gates.build` alone, sharing the new
  `_run_stage` with `run_build_gates`, whose behaviour is unchanged). In `run_single` (`l4.implementer.tdd`) for kind
  `fix`: `_e2e_chore_ids` reads the last `fix.spawned` of this fix unit in the parent's ledger, `verify_round`, and
  `read_verdict` of the parent unit (a lazy import: `evidence` -> `report` -> `judge` -> `tdd` is a cycle); when the e2e
  gate is configured and the ids are not empty, `_e2e_chore_reason` runs, after the test gate and only if it passed,
  `gates.build` and `run_e2e(wb, name="e2e-chore", must_contain=ids)`, and the attempt fails naming the ids that are
  missing from the report or not passed (with the failure excerpt of those that ran), `gates.build failed before the e2e
  gate: ...` for a failed build, `the e2e server was not ready` for `ServerNotReady`; the replay guard is restored after
  it. `gate.finished` is emitted by the workbench for the build and e2e runs like for the other gates. Deviations:
  only `ServerNotReady` is caught (the other `L4Exit` of `run_e2e` is a refused configuration, USAGE_ERROR, which stays
  an error of the run); the other e2e tests that fail in that run are not judged, only the finding's ids (the spec asks
  for the ids as must-pass); a verdict that has no `failures` (an older harness) or no recorded `fix.spawned` gives no
  e2e ids, so the chore runs as before. A `new tests ...` finding whose detail is cut (`and N more`) names only the
  ids shown. Tests: new `tests/unit/implementer/test_fix_chore_e2e.py` (13: SCN-IMP-446 twice, -447, -448, missing
  report entry, build before e2e and failed build, other finding, no e2e failure recorded, no spawning round, no e2e
  gate configured, `new tests failed` limits the ids, `e2e_ids_of`). `run_e2e` is stubbed. Before (the code of 2.1):
  the first stubbed test failed on the missing `run_e2e` in `l4.implementer.tdd`; after: 13 passed.

## 3. One failure, one task

- [ ] 3.1 Write the tests first (`tests/unit/specs/test_fix_unit.py` or the fixunit tests; find them): SCN-VER-255, -256.
  Then in `fixunit._candidates` make a `new tests failed` / `new tests errored` finding whose ids (from the round's
  `failures`, not the cut text) are all among the failing ids of a failed gate finding of the same round join that
  candidate. Verdicts, finding ids and `same_failure` sets stay as they are.

## 4. Checks

- [ ] 4.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the test files that import a module you changed (`grep -rl` under tests/unit), in as few
  sequential runs as the time limit allows; not whole directories. Run ruff check and ruff format on the changed files.
  Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md.
