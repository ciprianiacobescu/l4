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

- [ ] 1.1 Write the tests first (the verifier report/verdict tests: find them with `grep -rln "verdict_json\|read_verdict"
  tests/unit`): SCN-VER-254, and that `read_verdict` of an old verdict without `failures` still works. Then build the map
  in `tests()` from both reports (gate `test` for the unit report, `e2e` for the browser report; status failed or
  errored), pass it to `verdict_json` as a new top-level key `failures: {id: {gate, kind, message}}` (first line,
  `wb.redactor.redact_text`, 200 characters), and expose it from `read_verdict`.

## 2. The fix chore (L4-IMP-090, L4-IMP-017)

- [ ] 2.1 Write the tests first (the fix-chore tests: `grep -rln "run_single\|kind=\"fix\"" tests/unit/implementer`):
  SCN-IMP-449 (a put-back-only attempt fails `nothing changed: …`; the same with a CI-job chore still commits; a retake
  keeps `_already_done`). Then add the rule in `run_single` for kind `fix` with `ci_job is None`: `put_back` non-empty and
  nothing else changed (`changed_files()` minus the ledger, tasks.md and the put-back paths is empty).
- [ ] 2.2 Write the tests first: SCN-IMP-446, -447, -448 (stub `run_e2e` and the build runner the way the verifier's e2e
  tests do). Then, in `run_single` for kind `fix`: find the e2e ids of the task's findings from the parent round's
  verdict (`fix.spawned.verify_round` → `read_verdict` → `failures` with gate `e2e`, limited to the ids of this task's
  findings; a finding titled "e2e gate failed" takes all e2e failures of the round); when there are any, after the test
  gate run `gates.build` when configured (reuse the verifier's build runner) and `run_e2e(wb, name="e2e-chore",
  must_contain=ids)`; fail the attempt naming the ids that are missing or not passed; catch `ServerNotReady` (and the
  `L4Exit` it raises) as a failed attempt `the e2e server was not ready`. Record the e2e run like the other gates of the
  step (find how `run_single` records `gate.finished`).

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
