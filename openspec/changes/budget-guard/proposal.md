## Why

A consumer repository adopted L4 on 2026-10-15 with `ci.time_budget: 21m` and `ci.soft_deadline_margin: 20m` in
`.l4/config.yaml`. Its GitHub workflow has `timeout-minutes: 180` and `L4_JOB_TIMEOUT_MINUTES: "180"`.

- Before 0.4.19 the soft deadline was checked only between units. 21m − 20m left one usable minute, which meant "one
  unit per run" (the first unit of a run always starts) and did no harm.
- Release 0.4.19 (run-continuation, L4-IMP-066 to L4-IMP-071) checks the soft deadline before and during every
  implementer step and verification round. An explicit `ci.time_budget` wins over `L4_JOB_TIMEOUT_MINUTES`
  (`job_budget_s`, `src/l4/orchestrator.py:1819-1827`). So every run's first step started with about 20 seconds left
  (the first step of a run always starts), was stopped at the deadline, and after two such stops the unit halted with
  `deadline_repeated` and the plan stopped (`unit_halted`).
- The halt text (`orchestrator.py:460-464`) said "raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES or split the task".
  That is the wrong fix here: the budget came from `ci.time_budget`. The "no step fitted" warning
  (`orchestrator.py:1798-1803`) names both sources at once.
- Nothing warned at configuration load, in `l4 doctor`, or in `l4 upgrade` to 0.4.19.

## What Changes

- **A budget that leaves less than one step is a configuration error** (L4-IMP-076). When `ci.time_budget` is a
  duration and `ci.time_budget − ci.soft_deadline_margin` is below the 10-minute step floor (`l4.deadline.FLOOR_S`),
  a new doctor check `CFG-012` fails as an error with the cause and the fix: `ci.time_budget 21m minus
  soft_deadline_margin 20m leaves 1 min, less than one step (10 min): set ci.time_budget: auto (the job timeout) or
  raise it`. `l4 run` refuses with the same text and exits 2 before the follow-ups, the plan step and any unit, so no
  unit halts. The configuration still loads, so `l4 status` and `l4 upgrade` keep working on it.
- **A budget that shortens the job is named** (L4-IMP-077). When a set `ci.time_budget` is shorter than the job's own
  timeout by more than the margin, `CFG-012` warns and `l4 run` logs one WARNING. The job's timeout comes from
  `CI_JOB_TIMEOUT`, else `L4_JOB_TIMEOUT_MINUTES`, else the `timeout-minutes` of the checked-out
  `.github/workflows/l4.yml`.
- **The deadline texts name the budget's real source** (L4-IMP-078). The `deadline_repeated` halt and the "no step
  fitted" warning say `raise ci.time_budget (or set it to auto)` when the budget is `ci.time_budget`, `raise the job's
  timeout (CI_JOB_TIMEOUT)` on GitLab's job timeout, and keep `raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES` for
  GitHub's. `run.started` records `job_budget_source`.
- **`l4 upgrade` names the problem** (L4-IMP-079). After the files, it prints `error: …` for L4-IMP-076 and `warning:
  …` for L4-IMP-077, with the job timeout of the workflow it writes. It changes no file for them and still exits 0.
- **Docs**: SPEC (L4-IMP-076 to L4-IMP-079, SCN-IMP-385 to SCN-IMP-395, L4-IMP-066/070/071 name the source, doctor
  `CFG-012`, §3.2 comment, §12.1, change-table row 58), the runbook's soft deadline section, the skill's error table,
  and CHANGELOG `## 0.4.20 (unreleased)`.

## Impact

- Code: `src/l4/ci/budget.py` (new: the budget, its source, the job's timeout, the two texts, the fix of a source),
  `src/l4/orchestrator.py` (`job_budget_s` delegates; `_job_facts` adds `job_budget_source`; `run_command` refuses or
  warns after `preflight_run_config`; `_repeated_stop` and `continue_left_units` take the fix from the source),
  `src/l4/doctor/checks_config.py` (`CFG-012`), `src/l4/init/upgrade.py` (the budget lines in `UpgradePlan.notes`).
- Ledger: new optional key `run.started{job_budget_source}`. Older ledgers and readers are unaffected.
- Behaviour change: a configuration whose budget leaves less than 10 minutes after the margin now fails `l4 doctor`
  (exit 3) and `l4 run` (exit 2). In the generated workflows `l4 doctor --ci` runs before `l4 run`, so such a job now
  fails at the doctor step and no unit is touched. That is the intended outcome: a red job that names the key, instead
  of a halted unit and a stopped plan. The no-step-fitted warning no longer says `or ci.time_budget` when the budget
  is the job's timeout.
- Tests that change: `tests/unit/orchestrator/test_continuation.py` (the warning's text),
  `tests/unit/doctor/test_doctor_cli.py` (the registered ids), `tests/unit/docs/test_yolo_guardrails_docs.py:25` (the
  0.4.20 heading, the same edit as `pin-clis`).
- Spec: L4-IMP-076 to L4-IMP-079, SCN-IMP-385 to SCN-IMP-395, change-table row 58 (row 57 is `pin-clis`, on its own
  branch).
- No configuration key, no runtime dependency, no prompt version change, no template change.
