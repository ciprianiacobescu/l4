Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, key, event and signature is in `design.md` (D1
  to D7 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree (`budget-guard`), with its own `.venv`. Never change git configuration. Never
  push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `budget-guard <n.m>: …`, with no
  trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- No test sleeps. A test of the deadline texts uses the levers of `tests/unit/orchestrator/test_step_deadline.py`
  (`budget`, `stop_green`, `red_committed`, the `fake_clock`).
- Name a consumer repository only as "a consumer repository". Put no local path in docs or fixtures.
- One implementer does the tasks in order, on top of the previous commits.

Test worlds: `tests/unit/orchestrator/conftest.py` (`run_l4(script, *flags, **config)`, `Run.events`, `Run.outcome`,
`fake_clock`, `tdd_repo`, `UNIT`); `tests/unit/orchestrator/test_step_deadline.py` (`budget`, `no_budget`,
`stop_green`, `red_committed`, `BUDGET`, `MARGIN_S`); `tests/unit/orchestrator/test_continuation.py` (`FakeForge`,
`forge`, `_go`, `CI`, `HANDED`); `tests/unit/orchestrator/test_soft_deadline.py` (`_cfg`, `_run`, `clock`);
`tests/unit/doctor/conftest.py` (`make_ctx`); `tests/unit/init/test_upgrade.py` (`adopt`, `run`, `action_adoption`,
`upgrade_to_new`), `tests/unit/init/test_init_fetched.py` (a fetched adoption).

## 1. The budget module (design D1, D3, D5; L4-IMP-076 to L4-IMP-078)

- [ ] 1.1 `l4.ci.budget`. Tests first, new `tests/unit/ci/test_budget.py`:
  `test_job_budget_reads_the_set_budget_then_gitlab_then_github` (`3h` with `L4_JOB_TIMEOUT_MINUTES=180` gives
  `Budget(10800, "ci.time_budget")`; `auto` with both variables gives `CI_JOB_TIMEOUT`; `auto` with
  `L4_JOB_TIMEOUT_MINUTES=180` gives `Budget(10800, "L4_JOB_TIMEOUT_MINUTES")`; `auto` with `180h` or nothing gives
  None); `test_too_short_says_what_is_left_and_the_fix` (SCN-IMP-385: `21m`/`20m` gives exactly `ci.time_budget 21m
  minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): set ci.time_budget: auto (the job
  timeout) or raise it`; SCN-IMP-387: `30m`/`20m` and `auto` give None, `15m`/`20m` says `leaves no time`;
  `1h`/`50m` gives None); `test_shortens_job_names_the_job_timeout_and_its_source` (SCN-IMP-388: `60m`/`20m` with
  `(10800, "L4_JOB_TIMEOUT_MINUTES")` gives the D3 text word for word with `minute 40, not at minute 160`;
  SCN-IMP-390: `21m` gives `minute 1, not at minute 160`; SCN-IMP-389: `60m` with `(3600, "CI_JOB_TIMEOUT")`, `170m`
  with 180 minutes, `auto`, and a None timeout give None); `test_job_timeout_reads_the_job_then_the_workflow`
  (SCN-IMP-389: `CI_JOB_TIMEOUT=3600` gives `(3600, "CI_JOB_TIMEOUT")`; `L4_JOB_TIMEOUT_MINUTES=180` gives `(10800,
  "L4_JOB_TIMEOUT_MINUTES")`; no variable and a workflow text with `    timeout-minutes: 180` gives `(10800,
  ".github/workflows/l4.yml timeout-minutes")`; a non-digit variable is skipped; nothing gives None);
  `test_workflow_timeout_reads_the_first_integer` (`timeout-minutes: ${{ inputs.t }}` gives None; two jobs give the
  first); `test_read_workflow_refuses_a_link_and_a_big_file` (a symlinked `.github/workflows/l4.yml`, one over 1
  MiB, and no file give None); `test_raise_fix_per_source` (the three texts of D5; None gives the
  `L4_JOB_TIMEOUT_MINUTES` text); `test_upgrade_notes` (the `error: …; until it is fixed, l4 run exits 2 and doctor
  CFG-012 fails` and `warning: …` lines for `21m` with a 180-minute workflow text, in that order; none for `auto`;
  only the error line with no workflow text); `test_the_module_does_not_import_the_orchestrator` (with `ast`: no
  `l4.orchestrator`, `l4.doctor` or `l4.init` import). The existing
  `tests/unit/orchestrator/test_soft_deadline.py::test_job_budget_s` must pass unchanged. Code: new
  `src/l4/ci/budget.py` (Contracts); `src/l4/orchestrator.py` (`job_budget_s` returns `job_budget(...).seconds`).
  Run: `tests/unit/ci/test_budget.py tests/unit/orchestrator/test_soft_deadline.py`.

## 2. Doctor `CFG-012` (design D4; L4-IMP-076, L4-IMP-077)

- [ ] 2.1 Tests first, new `tests/unit/doctor/test_checks_cfg_012.py` (with `make_ctx`, a real `L4Config`):
  `test_a_budget_below_one_step_is_an_error` (SCN-IMP-385: `fail`, severity `error` from `REGISTRY`, the text, the D4
  fix hint);
  `test_a_budget_at_the_floor_and_auto_pass` (SCN-IMP-387: `30m`/`20m` passes with `leaves 10 min after
  soft_deadline_margin 20m`; `auto` passes with `the job's timeout is the budget`; `15m`/`20m` fails with `leaves no
  time`);
  `test_a_budget_that_shortens_the_job_warns` (SCN-IMP-388: `ctx.env` with `L4_JOB_TIMEOUT_MINUTES=180`, `60m`: `fail`
  with `result.severity == "warn"`; the whole doctor run's exit stays 0);
  `test_the_job_timeout_comes_from_the_workflow_file` (SCN-IMP-389: no variable, `.github/workflows/l4.yml` under
  `ctx.repo` with `timeout-minutes: 180`: warns with `.github/workflows/l4.yml timeout-minutes`; no file: passes;
  `CI_JOB_TIMEOUT=3600`: passes; `170m`: passes);
  `test_both_texts_make_one_error` (SCN-IMP-390: `21m` with `L4_JOB_TIMEOUT_MINUTES=180`: one `fail`, severity
  `error`, the message is the error text, `; `, the warning text);
  `test_cfg_012_runs_in_every_config_scope` (registered with `CONFIG_SCOPES`, so `--adoption --no-gates` runs it).
  Update `tests/unit/doctor/test_doctor_cli.py` (the list of registered ids gets `CFG-012`; the default `auto` passes,
  so it is not in `skipped`). Code: `src/l4/doctor/checks_config.py` (`_cfg_012`, `CFG_012`; the module docstring
  names it). Run: `tests/unit/doctor`.

## 3. `l4 run` (design D2, D3, D5; L4-IMP-076 to L4-IMP-078)

- [ ] 3.1 The refusal and the warning. Tests first, new `tests/unit/orchestrator/test_budget_guard.py` (the `run_l4`
  world, configuration through `run_l4(..., ci={...})`):
  `test_run_refuses_a_budget_below_one_step_before_any_unit` (SCN-IMP-386: `ci: {time_budget: 21m,
  soft_deadline_margin: 20m}` and `L4_JOB_TIMEOUT_MINUTES=180`: exit 2, the SCN-IMP-385 text in the error output, no
  ledger event, no worktree, no unit-branch commit, and the fake agent never called);
  `test_the_refusal_comes_before_the_follow_ups_and_the_plan_step` (monkeypatch `orchestrator.perform_follow_ups`,
  `orchestrator.yolo_step` and `orchestrator.make_forge` to record calls: none is called);
  `test_a_budget_that_shortens_the_job_warns_once_and_runs` (SCN-IMP-388: `ci: {time_budget: 60m}` with
  `L4_JOB_TIMEOUT_MINUTES=180`: one WARNING record with the D3 text in `caplog`, and the unit runs its red);
  `test_the_incident_prints_only_the_refusal` (`21m` with `L4_JOB_TIMEOUT_MINUTES=180`: exit 2 and no WARNING with
  `is shorter than the job's timeout`);
  `test_status_and_the_dry_run_are_not_refused` (SCN-IMP-387: `l4 status` exits 0 and `l4 run --dry-run` is not
  refused on the `21m` configuration).
  The existing `tests/unit/orchestrator/test_soft_deadline.py` (it calls `run_units` with `10m`, `30m`, `40m`) must pass
  unchanged. Code: `src/l4/orchestrator.py` (`run_command`: after `preflight_run_config`, `too_short` raises
  `L4Exit(ExitCode.USAGE_ERROR, text)`, else `shortens_job(cfg, job_timeout(app.environ, read_workflow(app.repo)))`
  is logged once). Run: that file, `tests/unit/orchestrator/test_soft_deadline.py`,
  `tests/unit/orchestrator/test_run_command.py` and `tests/unit/sim`.

- [ ] 3.2 The texts by source and `run.started`. Tests first:
  `tests/unit/orchestrator/test_step_deadline.py`: `test_the_halt_text_names_ci_time_budget` (SCN-IMP-391: the levers
  of `test_the_halt_text_shows_both_stops` with `ci: {time_budget: 3h}` as well: the detail starts `task 1.1 green does
  not fit in one job: raise ci.time_budget (or set it to auto) or split the task, then l4 retry --unit`);
  `test_the_halt_text_names_the_gitlab_job_timeout` (`CI_JOB_TIMEOUT=10800` in place of `L4_JOB_TIMEOUT_MINUTES`: it
  names `raise the job's timeout (CI_JOB_TIMEOUT)`); `test_run_started_records_the_budget_source` (SCN-IMP-393: `3h`,
  `L4_JOB_TIMEOUT_MINUTES=180`, `CI_JOB_TIMEOUT=10800`, and no budget: `job_budget_source` and `job_timeout_s` as the
  scenario says, absent in the fourth). The existing `test_the_halt_text_shows_both_stops` must pass unchanged (the
  `L4_JOB_TIMEOUT_MINUTES` text is byte-identical).
  `tests/unit/orchestrator/test_continuation.py`: change `test_no_step_started_no_continuation` (`:163`) to assert
  `raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES, or split the task` and that `or ci.time_budget` is not in
  `caplog.text`; new `test_the_no_step_fitted_warning_names_ci_time_budget` (SCN-IMP-392: `_go` with a configuration
  whose `ci.time_budget` is `40m`: the warning ends `raise ci.time_budget (or set it to auto), or split the task`).
  Code: `src/l4/orchestrator.py` (`_repeated_stop`, `continue_left_units`, `_job_facts`). Run: those two files and
  `tests/unit/orchestrator/test_soft_deadline.py`.

## 4. `l4 upgrade` (design D6; L4-IMP-079)

- [ ] 4.1 Tests first, new `tests/unit/init/test_upgrade_budget.py`:
  `test_the_upgrade_names_a_budget_below_one_step_and_a_shortened_job` (SCN-IMP-394: `action_adoption`, then
  `ci.time_budget: 21m` and `soft_deadline_margin: 20m` written into `.l4/config.yaml`, then `upgrade_to_new`: the
  output has the `error:` line and the `warning:` line with `(180 min, .github/workflows/l4.yml timeout-minutes)`,
  exit 0, `.l4/config.yaml` still holds `time_budget: 21m`; the same with `--dry-run`);
  `test_the_lines_do_not_depend_on_a_changed_file` (a second upgrade that changes no file prints both lines again);
  `test_a_sound_budget_prints_no_line` (SCN-IMP-395: an action adoption with `auto`; a fetched adoption with `3h`
  and its GitHub workflow; a vendored adoption (`adopt`) with `60m` and no GitHub workflow; each with
  `L4_JOB_TIMEOUT_MINUTES=600` in the environment: no `error:` or `warning:` budget line).
  The existing `tests/unit/init/test_upgrade.py` must pass unchanged. Code: `src/l4/init/upgrade.py` (`plan_upgrade`:
  the planned workflow's bytes, else `read_workflow(repo)`, then `upgrade_notes(loaded, text)` appended to `notes`).
  Run: `tests/unit/init`.

## 5. Docs, SPEC, CHANGELOG (design D7)

- [ ] 5.1 Tests first, new `tests/unit/docs/test_budget_guard_docs.py`:
  `test_the_spec_has_the_requirements_and_scenarios` (`**L4-IMP-076 ` to `**L4-IMP-079 ` in order after
  `**L4-IMP-075 `; `#### SCN-IMP-385 ` to `#### SCN-IMP-395 ` in order before `### 23.8`; the doctor table has `|
  CFG-012 | error |`; `| 58 | \`budget-guard\` |`; L4-IMP-070 and L4-IMP-071 say `the fix for the budget's source`);
  `test_the_runbook_names_the_budget_check` (the soft deadline section names `CFG-012`, `ci.time_budget: auto`,
  `less than one step` and `raise ci.time_budget (or set it to auto)`, and no longer says `(or ci.time_budget)`);
  `test_the_skill_has_the_budget_rows` (`operate.md`'s error table has `less than one step (10 min)` and `is shorter
  than the job's timeout`, and its `deadline_repeated` row names `ci.time_budget`);
  `test_the_changelog_names_the_budget_guard` (in `## 0.4.20 (unreleased)`: `CFG-012`, `ci.time_budget: auto`,
  `exits 2`, `job_budget_source`, `raise ci.time_budget`). Change `tests/unit/docs/test_yolo_guardrails_docs.py:25`
  from `assert "## 0.4.20 (unreleased)" not in changelog` to `assert changelog.index("## 0.4.20 (unreleased)") <
  changelog.index("## 0.4.19 (")`: the same edit as `pin-clis` makes on its branch, so the two hunks are identical.
  `test_run_continuation_docs.py` and `test_yolo_go_docs.py` read the 0.4.19 head, which stays; the runbook line
  that starts ``- The soft deadline is `ci.time_budget` `` stays word for word (`test_run_continuation_docs.py:69`
  splits on it). Code: `CHANGELOG.md` (the lines below, under `## 0.4.20 (unreleased)` above `## 0.4.19
  (2026-10-20)`; `pin-clis` adds the same heading with `### Added` and `### Changed`: whoever merges second keeps
  one heading and merges the lists under the same subheadings), `docs/runbook.md` (section 6, "Start a run", the
  soft deadline bullets: the two `raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES (or ci.time_budget)` texts name
  the fix by source, and one new bullet after the soft deadline bullet: `l4 doctor` `CFG-012` and `l4 run` refuse a
  set `ci.time_budget` that leaves less than 10 minutes after the margin, the fix is `ci.time_budget: auto`, and a
  set budget shorter than the job's timeout by more than the margin is a warning),
  `plugins/l4/skills/l4/references/operate.md` (the error table: the `deadline_repeated` row's fix becomes `Raise
  ci.time_budget (or set it to auto) when the reason names it, else timeout-minutes and L4_JOB_TIMEOUT_MINUTES, or
  split the task, then …`; new rows `ci.time_budget … leaves N min, less than one step (10 min)` (cause: the set
  budget minus the margin leaves less than one step; fix: `ci.time_budget: auto`, commit, push) and `ci.time_budget
  … is shorter than the job's timeout` (cause: the set budget moves the soft deadline early; fix: `auto` unless the
  job must stop early)). The SPEC text is already in this branch; change it only to match the code, with the
  orchestrator. Run: `tests/unit/docs tests/unit/skills`, `scripts/check_spec.py docs/SPEC.md`, `openspec validate
  budget-guard --strict`.

- [ ] 5.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract`,
  `.venv/bin/ruff check src tests scripts plugins`, `.venv/bin/ruff format --check` on every changed file, and
  `.venv/bin/mypy` on the changed src files. Done when all pass, `git status` is clean, and `git grep -n "or
  ci.time_budget, or split" -- src` finds nothing.

## CHANGELOG lines (`## 0.4.20 (unreleased)`; task 5.1 writes them as they stand)

### Added
- Doctor `CFG-012` checks the soft deadline against the step floor (L4-IMP-076, L4-IMP-077). It is an error when a set
  `ci.time_budget` minus `ci.soft_deadline_margin` leaves less than 10 minutes, the smallest estimate of a step:
  `ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): set ci.time_budget:
  auto (the job timeout) or raise it`. It is a warning when a set `ci.time_budget` is shorter than the job's timeout
  (`CI_JOB_TIMEOUT`, `L4_JOB_TIMEOUT_MINUTES`, else the `timeout-minutes` of `.github/workflows/l4.yml`) by more than
  the margin.
- `run.started` records `job_budget_source`: `ci.time_budget`, `CI_JOB_TIMEOUT` or `L4_JOB_TIMEOUT_MINUTES`
  (L4-IMP-078).

### Changed
- `l4 run` refuses a set `ci.time_budget` that leaves less than 10 minutes after the margin: it prints the text above
  and exits 2 before the plan step and any unit (L4-IMP-076). Since 0.4.19 checks the deadline inside a unit, such a
  budget started each run's first step with seconds left and halted the unit with `deadline_repeated` after two runs.
  In the generated workflows `l4 doctor --ci` fails first, so the job is red at the doctor step. Fix: `ci.time_budget:
  auto`, the job's own timeout. The configuration still loads, so `l4 status` and `l4 upgrade` work on it.
- `l4 run` logs one warning when a set `ci.time_budget` shortens the job by more than the margin (L4-IMP-077).
- `l4 upgrade` prints `error: …` and `warning: …` lines for these two cases after the files it changes, and still exits
  0 (L4-IMP-079).

### Fixed
- The `deadline_repeated` halt reason and the "no step fitted" warning name the fix of the budget's real source: `raise
  ci.time_budget (or set it to auto)` when the budget is `ci.time_budget`, `raise the job's timeout (CI_JOB_TIMEOUT)`
  on GitLab, and `raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES` on GitHub. Before, the halt always named
  `timeout-minutes`, and the warning named both (L4-IMP-078).
