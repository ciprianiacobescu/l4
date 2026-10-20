Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, key, event and signature is in `design.md` (D1
  to D10 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree, with its own `.venv`. Never change git configuration. Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `run-continuation A<n>: …` or
  `run-continuation B<n>: …`, with no trailer and no local path.
- Never wait on a process with `while pgrep …` (it matches itself), and never write a loop that waits on a process
  name. Run commands in the foreground with a timeout. A test that starts a child process kills its group in a
  `finally` (it writes the pid to a file under `tmp_path`).
- No test sleeps for the real soft deadline. A test fires the deadline with `RunDeadline.fire()` (or the fake
  adapter's `on_start` lever) and moves time with the `FakeClock` of `fake_clock`. Only the `ProcRunner` tests of 2.1
  wait for the real 5 s grace.
- Name a consumer repository only as "a consumer repository". Put no local path in docs or fixtures.
- Two implementers work in sequence: group A (sections 1 to 5), then group B (sections 6 to 8), on top of A's commits.

Test worlds: `tests/unit/orchestrator/conftest.py` (`run_l4(script, *flags, **config)`, `Run.events`, `Run.ledger`,
`Run.branch_ledger`, `Run.local_events`, `Run.subjects`, `Run.outcome`, `fake_clock`, `install_hooks`, `BRANCH`,
`UNIT`); `tests/unit/implementer/conftest.py` (`red_step`, `green_step`, `make_bench`, `Bench`);
`tests/unit/orchestrator/test_soft_deadline.py` (`_cfg`, `_units`, `clock`, `_run`);
`tests/unit/orchestrator/test_continuation.py` (`FakeForge`, `forge`, `_go`, `CI`); `tests/unit/forge/_github_helpers.py`
(`FakeGitHub`); `tests/unit/ci/test_pin_guard.py` (`make_repo`, `app_for`, `guarded`, `PINNED`);
`tests/unit/yolo/test_yolo_status_activity.py` (`_describe`, `_units`, `_at`, `NOW`, `LINK`, `UNIT`, `RUN`).
For an `l4 run` test with a known budget, the environ of `tdd_repo` gets `L4_JOB_TIMEOUT_MINUTES=180` and
`L4_JOB_STARTED_AT` set to the `FakeClock`'s start, plus `GITHUB_ACTIONS=true` only where the continuation is under
test (with `make_forge` monkeypatched to a `FakeForge`).

## 1. Group A: the run deadline and the job's start (design D1, D2; L4-IMP-066)

- [ ] 1.1 The module. Tests first, new `tests/unit/test_deadline.py`:
  `test_the_module_imports_nothing_from_l4` (with `ast`);
  `test_remaining_and_fire` (a `FakeClock`, `at` 600 s ahead: `remaining_s() == 600`, `fired()` false, then after
  `fire()` true);
  `test_arm_starts_a_timer_and_disarm_cancels_it` (a timer factory passed to `arm` records the seconds it is given and
  is cancelled by `disarm`; `current()` is None after `disarm`);
  `test_the_estimate_has_a_floor_a_cap_and_a_fallback` (SCN-IMP-337: recorded greens `[300, 5000]` give 3600 with the
  default cap; `[120]` gives 600; no green measure and a red of 1410 measured gives 1410);
  `test_the_first_step_always_starts` (SCN-IMP-336: `started == 0`, 400 s left, recorded red 1800: no raise, then
  `started == 1`);
  `test_a_step_that_does_not_fit_raises_with_the_figures` (SCN-IMP-335: `DeadlineReached` with `when == "before"`,
  `left_s == 300`, `estimate_s == 1410`, `phase == "green"`);
  `test_no_deadline_no_check` (SCN-IMP-338: `current()` None, `check_before` returns);
  `test_deadline_reached_is_not_an_exception` (`issubclass(DeadlineReached, BaseException)` and not of `Exception`).
  Code: new `src/l4/deadline.py` (D2, Contracts). Run: that file.

- [ ] 1.2 The job's start and the arming. Tests first, `tests/unit/orchestrator/test_soft_deadline.py`:
  `test_l4_job_started_at_sets_the_start` (SCN-IMP-332);
  `test_l4_job_started_at_wins_over_ci_job_started_at`;
  `test_an_unparsable_start_is_skipped`;
  `test_an_unknown_start_is_said_once` (SCN-IMP-333, `caplog`, one INFO line with `no L4_JOB_STARTED_AT` and
  `l4 upgrade` over two units);
  `test_job_budget_s` (the total before the margin: `time_budget` set, `CI_JOB_TIMEOUT`, `L4_JOB_TIMEOUT_MINUTES`,
  none);
  `test_run_units_arms_the_deadline_and_disarms_it` (with a budget, `deadline.current()` is set while a unit runs and
  None after `run_units` returns, also when the unit raises; without a budget it is never set).
  The existing tests of that file must pass unchanged. Code: `src/l4/orchestrator.py` (`job_budget_s`,
  `job_remaining_s`, `run_units`: arm after the first computation, `finally: disarm()`, the INFO line). Run: that file
  and `tests/unit/orchestrator/test_wait_in_run.py`.

- [ ] 1.3 The templates and `run.started`. Tests first:
  `tests/unit/ci/test_render_github.py` and `tests/unit/ci/test_render_github_action.py`:
  `test_the_first_step_records_the_job_start` (the first step is named `job start`, its `run` is the D1 line, it has
  no `with`, no `env` and no `if`) (SCN-IMP-334). Update the step-order test of the action form
  (`test_steps_checkout_base_checkout_action_doctor_save_plan_run_status_upload`: `job start` comes first) and the
  rendered fixtures `tests/fixtures/ci/l4.github*.yml` (render them again, do not edit them by hand).
  `tests/unit/ci/test_lint.py`: `test_the_job_start_step_passes_the_lint`.
  New `tests/unit/orchestrator/test_step_deadline.py`: `test_run_started_records_the_job_budget_and_start` (SCN-IMP-334:
  `run_l4([red_step(), green_step()])` with the budget environ; `run.started` has `job_timeout_s == 10800` and the
  `job_started_at`; without the budget neither key).
  Code: `src/l4/ci/templates/l4.github.yml`, `src/l4/ci/templates/l4.github-action.yml`, `src/l4/orchestrator.py`
  (the two keys passed to `LedgerWriter.open` in `run_unit_in_worktree`). Run: `tests/unit/ci`,
  `tests/unit/orchestrator/test_step_deadline.py`, `tests/unit/orchestrator/test_ci_url_roundtrip.py`. Commit
  `run-continuation A1: …`.

## 2. Group A: the stop (design D4; L4-IMP-068)

- [ ] 2.1 `ProcRunner`. Tests first, `tests/unit/agents/test_proc.py`:
  `test_the_deadline_stops_a_running_process_with_sigint_then_sigkill` (a child that ignores SIGINT and sleeps 60 s:
  after `deadline.current().fire()` from a timer thread at 0.5 s, `run` returns within 0.5 + 5 + 2 s with
  `interrupted` and `deadline` true, and the child's pid is gone);
  `test_a_child_that_exits_on_sigint_ends_before_the_grace` (it returns within 2 s);
  `test_a_process_started_after_the_deadline_is_stopped_at_once`;
  `test_without_a_deadline_nothing_changes` (`deadline` false, `interrupted` false).
  The existing tests of that file must pass. Code: `src/l4/agents/proc.py` (`ProcOutcome.deadline`, `_wait` reads
  `deadline.fired()` as it reads `interrupt`). Run: `tests/unit/agents/test_proc.py tests/unit/agents`.

- [ ] 2.2 Gates. Tests first:
  new `tests/unit/gates/test_runner_deadline.py`: `test_a_gate_stopped_by_the_deadline_says_so` (`GateResult.deadline`
  true, `status == "fail"`);
  new `tests/unit/implementer/test_step_deadline.py` (`make_bench`):
  `test_run_gate_spec_raises_after_its_restores` (a gate command that writes a protected file and is stopped: the file
  is put back, `gate.finished` is recorded, then `DeadlineReached` with `during == "gate"` and `gate` the gate's
  name);
  `test_a_gate_that_ends_before_the_deadline_returns_its_result`.
  Code: `src/l4/gates/runner.py` (`GateResult.deadline`), `src/l4/implementer/workbench.py` (`run_gate_spec`, after
  `gate.finished`). Run: those files and `tests/unit/gates tests/unit/implementer/test_setup.py`.

- [ ] 2.3 The agent step and the CLI judge. Tests first:
  `tests/unit/implementer/test_step_deadline.py`:
  `test_a_stopped_agent_records_its_end_and_raises` (SCN-IMP-339 at bench level: a fake step whose `on_start` fires
  the deadline and that writes `half.txt`; `agent.finished` and `budget.cost` are recorded, `step.finished{status:
  deadline}`, `half.txt` is not in the worktree's index, protected paths are put back, then `DeadlineReached` with
  `during == "agent"`);
  `test_a_cancelled_run_without_the_deadline_is_still_a_failed_step` (today's text `ended with status cancelled`).
  New `tests/unit/llm/test_agent_judge_deadline.py`: `test_a_stopped_cli_judge_raises` and
  `test_a_cancelled_judge_without_the_deadline_is_an_error_result`.
  `tests/unit/agents/test_fake.py`: `test_on_start_runs_first` and
  `test_the_fake_honours_the_interrupt_and_the_deadline` (status `cancelled`).
  Code: `src/l4/agents/fake.py` (`Step.on_start`, the interrupt), `src/l4/implementer/tdd.py` (`agent_step`: the raise
  after the cost events; `box.status = "deadline"`), `src/l4/llm/agent_judge.py` (`_run`). Run: those files,
  `tests/unit/implementer/test_liveness_step.py`, `tests/unit/llm`. Commit `run-continuation A2: …`.

## 3. Group A: before each step, and the hand-back (design D3, D5; L4-IMP-067, L4-IMP-069)

- [ ] 3.1 The check before each step. Tests first, `tests/unit/orchestrator/test_step_deadline.py`:
  `test_a_green_that_does_not_fit_is_not_started` (SCN-IMP-335: `red_step(on_start=…)` moves `fake_clock` 1410 s, the
  job started 155·60 − 1410 s before the red began; the green is never requested from the adapter;
  `deadline.reached{when: before, phase: green, left_s: 300, estimate_s: 1410}`; the outcome's `exit_reason` is the
  Contracts text);
  `test_the_first_step_of_a_run_always_starts` (SCN-IMP-336);
  `test_the_estimate_reads_the_units_recorded_steps` (SCN-IMP-337 end to end: earlier `step.timed` seeded in the
  unit's ledger on its branch);
  `test_no_budget_no_check` (SCN-IMP-338);
  `test_every_started_step_records_step_timed` (red and green, with their seconds on the `FakeClock`);
  `test_a_verification_round_that_does_not_fit_is_not_started` (`install_hooks` with a verify hook that fails the test
  if called; a recorded `step.timed{phase: verify}` larger than the time left).
  Code: `src/l4/implementer/loop.py` (`run_task`: `check_before` before `run_single`, `run_red`, `run_green`;
  `step.timed` after each, except when `DeadlineReached` passes), `src/l4/orchestrator.py` (`_verify`: the check before
  `verify(self._ctx)` and the round's `step.timed`). Run: that file, `tests/unit/implementer/test_loop.py`,
  `tests/unit/orchestrator/test_run_unit.py`.

- [ ] 3.2 The hand-back. Tests first, same file:
  `test_the_hand_back_is_pushed_and_exits_10` (SCN-IMP-342: the unit stays `implementing`; `Run.branch_ledger()` holds
  `deadline.reached`, `lock.released` and `run.finished{exit_code: 10, reason}` with the reason starting `soft deadline:`;
  no `task.attempt_failed`; `run.code == 10`);
  `test_the_next_run_continues_at_green` (SCN-IMP-343: a second `run_l4` without the budget; one `test(` commit and one
  `feat(` commit in `Run.subjects()`);
  `test_an_agent_stopped_at_the_deadline_is_handed_back` (SCN-IMP-339 end to end: `green_step(on_start=fire,
  writes={"half.txt": "x"})`; `half.txt` is in no commit of origin's branch; `step.finished{status: deadline}`);
  `test_a_gate_stopped_at_the_deadline_is_handed_back` (SCN-IMP-340: the red's test gate is stopped; no red commit, no
  failed attempt);
  `test_a_stopped_cli_judge_does_not_fail_the_round` (SCN-IMP-341: a verify hook whose judge raises
  `DeadlineReached(when="during", during="judge", phase="verify")`; no `verify.step{status: failed}` for it; the unit
  stays `verifying`; exit 10).
  `tests/unit/orchestrator/test_soft_deadline.py`: `test_no_unit_starts_after_a_hand_back` (SCN-IMP-344, with `_run`
  and a first unit whose result has `deferred=True`).
  Code: `src/l4/orchestrator.py` (`run_unit`: `except DeadlineReached`; `_defer`; `UnitRunResult.deferred`;
  `run_units`; `CommandResult.deferred` through `run_command`), `src/l4/state/ledger.py` (`finish(exit_code,
  reason=None)`), `src/l4/outcome.py` (`deferred`). Run: those files and `tests/unit/orchestrator`. Commit
  `run-continuation A3: …`.

## 4. Group A: one continuation, and a step that never fits (design D6, D7; L4-IMP-070, L4-IMP-071)

- [ ] 4.1 The continuation. Tests first, `tests/unit/orchestrator/test_continuation.py`:
  `test_a_hand_back_dispatches_once` (SCN-IMP-345 at function level: `result.deferred == ["openspec:a"]`, code 10);
  `test_a_more_severe_designed_stop_still_dispatches` (SCN-IMP-346: code 11 and a hand-back; also 12 and 13);
  `test_a_failure_code_does_not_dispatch` (parametrized 1, 2, 3, 14, 16);
  `test_no_step_started_no_continuation` (SCN-IMP-347: an armed deadline with `started == 0`; the WARNING text);
  `test_the_plan_next_run_is_skipped_after_a_continuation` (`run_command` level, `make_forge` monkeypatched to a fake
  that records `dispatch_continuation` and `start_run`; a plan step with `start_next_run=True`; exactly one call, to
  `dispatch_continuation`; with `already_queued`, still no `start_run`).
  `tests/unit/orchestrator/test_step_deadline.py`: `test_one_dispatch_for_a_plan_unit_handed_back` (SCN-IMP-345 end to
  end, `GITHUB_ACTIONS=true`, a `FakeForge`; `outcome.json` `continuation: dispatched`; `plan: next run on` is not
  logged).
  The existing tests of `test_continuation.py` must pass. Code: `src/l4/orchestrator.py` (`continue_left_units`,
  `run_command`). Run: those files and `tests/unit/yolo/test_yolo_cycle*.py`.

- [ ] 4.2 The halt. Tests first, `tests/unit/orchestrator/test_step_deadline.py`:
  `test_a_green_stopped_twice_in_a_row_halts` (SCN-IMP-348: two runs whose green is stopped by `on_start=fire`; after
  the second, `breaker.tripped{reason: deadline_repeated, task: "1.1", phase: green, stops: 2}`, phase `halted`, the
  reason holds `timeout-minutes` and `l4 retry --unit`, and no continuation is sent with a `FakeForge`);
  `test_a_checkpoint_between_two_stops_resets_the_count` (SCN-IMP-349, first case);
  `test_a_stop_that_was_not_the_first_step_does_not_count` (SCN-IMP-349, second case: `first` false then true; no
  halt);
  `test_a_step_not_started_never_counts` (two runs whose green is not started: no halt);
  `test_the_stopped_time_feeds_the_estimate` (`ran_s` of a stop is read as a measure of its phase);
  `test_a_halt_of_a_round_has_no_task` (a verification round stopped twice as the first step: the halt has `task:
  null`, and `l4 status` and `l4 retry --unit` read it; confirm `note_binding` and the sticky section take a halt
  without a task, as for `baseline_failed`).
  Code: `src/l4/orchestrator.py` (`_defer`, D7), `src/l4/deadline.py` (`ran_s` in the estimate). Run: that file, `tests/unit/orchestrator/test_halt_codes.py`,
  `tests/unit/orchestrator/test_park_retry.py`. Commit `run-continuation A4: …`.

## 5. Group A: docs (L4-IMP-066 to L4-IMP-071)

- [ ] 5.1 Tests first, new `tests/unit/docs/test_run_continuation_docs.py`, part A, on the model of
  `tests/unit/docs/test_yolo_guardrails_docs.py`:
  `test_the_spec_has_the_deadline_requirements_and_scenarios_in_order` (`**L4-IMP-066 ` to `**L4-IMP-071 ` after
  `**L4-IMP-065 ` and before `## 8.`; `#### SCN-IMP-332 ` to `#### SCN-IMP-349 ` in increasing order after
  `#### SCN-IMP-331 ` and before `### 23.8`; L4-IMP-012 no longer lists "the SIGINT of a running agent" or "the
  continuation dispatch" as still to do, and still names the WIP push; L4-CI-004 names `10, 11, 12 or 13`);
  `test_the_changelog_has_the_deadline_lines_under_0_4_19` (in `## 0.4.19 (unreleased)`: `L4_JOB_STARTED_AT`,
  `deadline.reached`, `deadline_repeated`, `soft deadline:`).
  Code: `docs/SPEC.md` (the requirement texts of `specs/step-deadline/spec.md`; the scenarios in the Part II form
  `#### SCN-IMP-NNN (+|−) Title · L4-IMP-0NN` with `- **Given**`/`- **When**`/`- **Then**`; L4-IMP-012's paragraph;
  SCN-IMP-19; L4-CI-004; the §3.2 comment of `soft_deadline_margin`), `CHANGELOG.md` (the lines marked (A) below,
  under a new `## 0.4.19 (unreleased)` above `## 0.4.18 (2026-10-20)` if it is not there). Run: that file,
  `tests/unit/docs`, `scripts/check_spec.py docs/SPEC.md`, `openspec validate run-continuation --strict`.
  Then the whole of group A once: `tests/unit/orchestrator tests/unit/implementer tests/unit/agents tests/unit/gates
  tests/unit/llm tests/unit/ci tests/unit/verifier tests/unit/yolo tests/unit/docs tests/unit/test_deadline.py`.
  Commit `run-continuation A5: …`.

## 6. Group B: the relay (design D8; L4-IMP-072)

- [ ] 6.1 The forge. Tests first, new `tests/unit/forge/test_relay_run.py` (`FakeGitHub`):
  `test_no_other_active_run_dispatches_the_base`;
  `test_an_active_run_sends_nothing` (parametrized `queued`, `pending`, `waiting`, `requested`, `in_progress`);
  `test_the_own_run_is_left_out` (the only `in_progress` run has `id == exclude_run_id`);
  `test_completed_runs_do_not_count`;
  `test_403_is_refused_and_404_is_unsupported`;
  `test_gitlab_and_local_answer_unsupported`.
  `tests/unit/forge/test_dispatch_continuation.py` must pass unchanged (the continuation keeps its `queued` check).
  Code: `src/l4/forge/base.py` (the protocol method), `src/l4/forge/github.py`, `src/l4/forge/gitlab.py`,
  `src/l4/forge/local.py` (`relay_run`, which records its calls like `dispatch_continuation`). Run: `tests/unit/forge`.

- [ ] 6.2 `relay_to_base`. Tests first, new `tests/unit/ci/test_relay.py` (the `make_repo`, `app_for` and `guarded` of
  `test_pin_guard.py`; `make_forge` monkeypatched to a fake whose `relay_run` answer the test sets; the check for work
  monkeypatched where a test does not build ledgers):
  `test_a_scheduled_run_on_the_default_branch_relays` (SCN-IMP-350: the two lines on stderr in order, one `relay_run`
  call with the base and `GITHUB_RUN_ID`, `outcome.json` `relay: dispatched`, exit 0);
  `test_an_active_run_on_the_base_is_not_doubled` (SCN-IMP-351);
  `test_a_mismatch_on_the_base_does_not_relay` (SCN-IMP-352);
  `test_no_work_is_not_relayed` (SCN-IMP-353, with a real empty repository: no plan ref, no unit);
  `test_an_active_plan_is_work` and `test_a_waiting_plan_is_work` (a plan ref seeded with `plan.activated`, and with
  `plan.waiting`);
  `test_an_unreadable_state_is_work` (SCN-IMP-354: the check raises; an unknown phase);
  `test_a_refused_token_names_the_command` (SCN-IMP-355: `refused`, and `ForgeUnavailable`);
  `test_outside_github_nothing_is_relayed` (SCN-IMP-356: `GITLAB_CI=true`, no `relay` key);
  `test_plan_sweep_never_relays` (`l4 plan --sweep` with the stop: no `relay_run` call).
  The existing tests of `test_pin_guard.py` must pass. Code: new `src/l4/ci/relay.py`, `src/l4/orchestrator.py`
  (`run_command`'s stop), `src/l4/outcome.py` (`relay`). Run: `tests/unit/ci/test_relay.py
  tests/unit/ci/test_pin_guard.py tests/unit/orchestrator/test_run_command.py`.

- [ ] 6.3 The upgrade text. Tests first, `tests/unit/init/test_upgrade_stale_branches.py`:
  `test_the_note_names_the_relay` (the D8 sentence after `the schedule do that`). Code: `src/l4/init/upgrade.py`
  (`stale_branches_note`). Run: `tests/unit/init`. Commit `run-continuation B1: …`.

## 7. Group B: `l4 yolo status` (design D9; L4-IMP-073)

- [ ] 7.1 The forge's view of a CI run. Tests first, new `tests/unit/forge/test_ci_run_state.py`:
  `test_a_github_run_url_is_read` (with and without `/attempts/2`; `GET /repos/{r}/actions/runs/{id}`; `completed` with
  the conclusion `cancelled`; `in_progress` is `running`);
  `test_a_gitlab_job_url_is_read`;
  `test_an_unknown_url_or_an_error_is_unknown`;
  `test_local_is_unknown`.
  Code: `src/l4/forge/base.py`, `github.py`, `gitlab.py`, `local.py` (`ci_run_state`). Run: `tests/unit/forge`.

- [ ] 7.2 Status. Tests first, new `tests/unit/yolo/test_yolo_status_open_run.py` (the helpers of
  `test_yolo_status_activity.py`, with `OpenRun(..., job_timeout_s=…)`, `ctx` given `app` and `cfg`, and `make_forge`
  monkeypatched):
  `test_an_open_run_older_than_its_timeout_ended_without_a_record` (SCN-IMP-357: the text line, the `Next:` line with
  `gh workflow run l4.yml --ref main`, the JSON keys, the same `next`);
  `test_an_older_run_started_without_the_timeout_assumes_180_minutes` (SCN-IMP-357, last clause);
  `test_the_ci_says_completed` (SCN-IMP-358);
  `test_a_young_run_without_an_answer_is_unchanged` (SCN-IMP-359);
  `test_a_waiting_plan_keeps_its_next` (an ended open run on a `waiting` plan: the line has the suffix, `Next:` is the
  wait's);
  `test_gitlab_names_the_new_pipeline_page`.
  `tests/unit/state/test_status_activity.py`: `test_open_run_reads_job_timeout_s`.
  Update `tests/unit/yolo/test_yolo_status_activity.py::test_active_plan_shows_unit_activity_and_open_run`: the
  `open_run` dict also has `ended_without_record: False`. Code: `src/l4/state/status.py` (`OpenRun.job_timeout_s`,
  `_activity`), `src/l4/yolo/commands.py` (`_activity_of`, `_describe`, `_next_line`, `_render`). Run: those files,
  `tests/unit/yolo/test_yolo_commands_manage.py`, `tests/unit/state`, `tests/unit/mcp`. Commit
  `run-continuation B2: …`.

## 8. Group B: docs, SPEC and CHANGELOG (design D10)

- [ ] 8.1 Tests first, `tests/unit/docs/test_run_continuation_docs.py`, part B:
  `test_the_spec_has_the_relay_and_status_requirements` (`**L4-IMP-072 ` and `**L4-IMP-073 ` after `**L4-IMP-071 `;
  `#### SCN-IMP-350 ` to `#### SCN-IMP-359 ` after `#### SCN-IMP-349 ` and before `### 23.8`; L4-ADO-005 names
  `L4-IMP-072`; L4-YOLO-030 names `ended without a record`; `| 56 | \`run-continuation\` |`);
  `test_the_runbook_and_the_yolo_doc_name_the_relay_and_the_command` (`docs/runbook.md` has `ended without a record`
  and `gh workflow run l4.yml --ref`; `docs/yolo-mode.md` names the relay);
  `test_the_skill_error_table_has_the_two_rows` (`plugins/l4/skills/l4/references/operate.md`: `ended without a
  record`, `deadline_repeated`);
  `test_the_changelog_names_the_relay_and_the_status` (in `## 0.4.19 (unreleased)`: `relay`, `ended without a
  record`).
  The existing docs tests must pass: `test_yolo_guardrails_docs.py`, `test_force_accept_docs.py`,
  `test_control_loop_agent_docs.py` (every `l4 …` span of the skill resolves). Code: `docs/SPEC.md` (requirements
  072 and 073, their scenarios, the L4-ADO-005 sentence, the L4-YOLO-030 text, row 56), `docs/runbook.md`,
  `docs/yolo-mode.md`, `plugins/l4/skills/l4/references/operate.md`, `CHANGELOG.md` (the lines marked (B)). Run:
  `tests/unit/docs tests/unit/skills`, `scripts/check_spec.py docs/SPEC.md`, `openspec validate run-continuation
  --strict`.

- [ ] 8.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit`, `.venv/bin/ruff check
  src tests plugins`, `.venv/bin/ruff format --check` on every changed file, and `.venv/bin/mypy` on the changed src
  files. Commit. Done when all pass, `git status` is clean, and `git grep -n "interrupt=None" src/l4/gates` finds
  nothing.

## CHANGELOG lines (`## 0.4.19 (unreleased)`)

Write them under the subsections, with no blank line between items. Group A writes the lines marked (A) in task 5.1,
and group B the rest in task 8.1.

### Added
- (A) The GitHub workflow templates record the job's start (`L4_JOB_STARTED_AT`, a first step `job start`), and the
  soft deadline counts from it. Run `l4 upgrade` to get the step; until then the deadline counts from the run's start,
  and the run says so once (L4-IMP-066).
- (A) Before each implementer step and each verification round, a run with a known budget compares the time left
  with the step's estimate. The estimate is the longest step of that kind in this run or among the unit's recorded
  steps, at least 10 minutes and at most one agent time limit plus `gates.timeout`. A step that does not fit is not
  started. The first step of a run always starts. Every step records `step.timed` (L4-IMP-067).
- (A) At the soft deadline, every agent, CLI judge and gate that the unit's run has running gets SIGINT, then SIGKILL
  after 5 s. The step is handed back: `deadline.reached` is recorded, no attempt is counted, the phase does not change,
  the ledger and the unit branch are pushed, `run.finished` has `reason: soft deadline: …`, and the run exits 10. The
  next run continues from the last pushed step (L4-IMP-068, L4-IMP-069).
- (A) A step stopped at the soft deadline as the first step of two runs in a row halts the unit with
  `deadline_repeated`. The reason names the job timeout to raise and `l4 retry` (L4-IMP-071).
- (B) A GitHub run that the pin guard stops (a scheduled run on a default branch that is not the base, or a push to an
  old unit branch) relays to the base. It dispatches `l4.yml` on the base once, when the base may have work and no
  other run of `l4.yml` is queued or running there, and it prints what it did (`outcome.json` `relay`). This works once
  the default branch's copy pins 0.4.19 or later (L4-IMP-072).
- (B) `l4 yolo status` calls an open run "ended without a record" when it is older than its job timeout (recorded on
  `run.started` as `job_timeout_s`) or when the forge says its CI run completed. For an active plan, `Next:` then gives
  the command that starts a run on the base (`gh workflow run l4.yml --ref <base>`). `--json` has
  `open_run.ended_without_record` and `open_run.why` (L4-IMP-073).

### Changed
- (A) A continuation is dispatched for a unit handed back or left at the soft deadline even when another unit of the
  run exits 11, 12 or 13. When it is dispatched, the plan's own next-run start of the same run is not sent: one dispatch
  per run. A run in which no step started dispatches nothing and says so (L4-IMP-070).

### Fixed
- (A) A run with a known job timeout is no longer killed by the CI timeout in the middle of an agent step, which left
  an open run with no end and no continuation (L4-IMP-012, L4-IMP-068).
- (B) `l4 yolo status` no longer says `nothing: CI advances the plan at each run` for an active plan whose last run
  died without a record (L4-IMP-073).
