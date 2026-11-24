## Why

A red step adds failing tests. Its test gate nevertheless runs the whole suite, and the red verdict then re-measures
every test the step cannot have touched.

Evidence from one TypeScript consumer plan (seven units, 51 leaf tasks, 171 implementer calls, run on 0.4.59):

- 66 red-step runs of the whole test suite took about 4.9 minutes each, about 320 minutes, about 10% of the time spent
  in runs.
- 27 of 45 clean-tree baseline runs had failing tests: the suite is flaky.
- 8 red steps failed with `red broke existing tests`. All 8 name end-to-end stack or journey tests, so they are
  probably flakes and not real catches (inferred, not proven). 4 of the journey-test failures happened in red only.

What exists at 0.4.60 (re-checked in the source at 663cd6d5):

- `gates.test.targeted` is a string with `{files}` and `{grep}` placeholders (`src/l4/config/schema.py:216`,
  `docs/SPEC.md:800`). Nothing reads it (a search of `src/` finds only its declaration).
- `run_red` runs the whole test command once, as the gate `test` (`src/l4/implementer/tdd.py:1701`), after
  `enforce_red_scope` (1657) and before the verdict. `classify_red` (526) judges that report against the step's base
  report.
- Green judges its failures against `RedOutcome.base_report`, the measured baseline, not against any red report
  (`tdd.py:2289`, `green_failures` at 613). Verification reads `task.red_ok` (`tests`, `frozen`, `criteria`), never a
  red report.
- A red step in a TypeScript repository cannot keep a production file: `enforce_red_scope` puts back every changed
  path that is not a test, a support file or a runner configuration and is not Python (`stubs.py:893-899`).
- The gate runner splits the command with `shlex.split` and runs no shell (`gates/runner.py`), deletes the listed
  report files before the run and fails the run when one of them is missing afterwards.

## What Changes

- A new key `gates.test.red_check`, `full` (default: today's behaviour) or `targeted`. `targeted` needs
  `gates.test.targeted` to hold `{files}` as a word of its own: otherwise the configuration does not load (L4-CFG-007).
- With `targeted`, each red step decides its check from rules that hold per step: every path the step changed is a new
  test module, no stub, nothing restored by red scope, no named or stale test in the task, the unit has not been
  switched back (L4-IMP-117). An eligible step runs its test command with `{files}` replaced by the new files, as the
  gate `test-targeted` (L4-GAT-007).
- The targeted run is used only when it is complete: a report was read, no collection error, no test of the base
  report ran, every new file owns a test and every reported test belongs to a new file, and every new test fails.
  Otherwise the same step runs the whole suite, exactly as today, and records why (L4-GAT-009, L4-IMP-118).
- The red checks see the base report with the targeted results added (L4-GAT-008, L4-IMP-119). Green, the near-pass
  carry and verification see what they saw before (L4-IMP-119).
- The ledger names the check: `task.red_ok` gains `check` and `files`, and `task.red_check_full` says why a step of a
  `targeted` configuration ran the whole suite (L4-IMP-120).
- When green's full run in a unit that has a targeted red, after its own re-run, still has a base-passing test failing,
  or a red test of a targeted task is missing from green's report, the harness records `task.red_check_disabled`. The
  unit's later red steps then run the whole suite, and green's reason says, for a task whose own red was targeted, that
  the targeted red may be the cause and what a person does about it (L4-IMP-121, L4-IMP-122).

Non-goals: a targeted green check, a path that redoes a red commit, the `{grep}` placeholder, a doctor check, a
targeted check for a step that changes a stub (a Python red step that adds stubs runs the whole suite).

## Capabilities

### New Capabilities

- `red-check-targeted`: L4-CFG-007 (the key and its load rule), L4-GAT-007 (the targeted command), L4-GAT-008 (the
  report with the targeted results added), L4-GAT-009 (when a targeted run is usable, and the fallback), L4-IMP-117
  (the per-step choice), L4-IMP-118 (a targeted red step), L4-IMP-119 (what each reader of the red report sees),
  L4-IMP-120 (ledger records), L4-IMP-121 (a regression after a targeted red switches the unit back), L4-IMP-122
  (green's reason).

### Modified Capabilities

- L4-IMP-002 (red's checks 3 and 4): the run of check 3 may be the targeted run of L4-IMP-118, and check 4 is judged on
  the base status of the tests it did not run (L4-IMP-119). `docs/SPEC.md` says so in the check list of L4-IMP-002. Their
  order and their verdicts are unchanged.
- `gates.test.targeted`: now read (`full` configurations ignore it as before).

## Impact

- `src/l4/config/schema.py` (`UnitGate.red_check` and its validator), a new `src/l4/implementer/red_check.py`
  (eligibility, command, usable test, report with the results added, the unit's records),
  `src/l4/implementer/tdd.py` (`run_red`, `resume_red`, `run_green`, `RedOutcome.check`),
  `src/l4/verifier/support_base.py` (the test-module rule of `is_support_file`, taken for a work-tree file).
- `docs/SPEC.md` (L4-CFG-007, L4-GAT-007..009, L4-IMP-117..122, SCN-CFG-08..12, SCN-GAT-12..20, SCN-IMP-626..648,
  change-table row 144, the reference configuration, section 12.1), `docs/runbook.md`, `plugins/l4/skills/l4/`,
  `CHANGELOG.md`.
- Ledger: `task.red_ok` gains `check` and `files`; two new events, `task.red_check_full` and `task.red_check_disabled`;
  one new gate name, `test-targeted`. A harness that does not know them ignores them.
- Cost: with `full` nothing changes. With `targeted`, an eligible red step replaces one whole-suite run by one run of
  its new files. A step that falls back runs both, so a repository whose targeted command never works pays the
  shorter run on top of the longer one: the ledger shows it (`task.red_check_full`).
- Upgrade: 0.4.60 ledgers fold unchanged. The key does not load on 0.4.60 (`extra: forbid`), so move the pin before
  you set it, and remove it before you move the pin back.
