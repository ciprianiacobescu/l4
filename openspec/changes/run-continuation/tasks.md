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
  adapter's `on_start` lever, or a thread that waits for a marker file a real gate writes) and moves time with the
  `FakeClock` of `fake_clock`. Only the `ProcRunner` tests of 2.1 wait for the real 5 s grace.
- Name a consumer repository only as "a consumer repository". Put no local path in docs or fixtures.
- Two implementers work in sequence: group A (sections 1 to 5), then group B (sections 6 to 8), on top of A's commits.

Test worlds: `tests/unit/orchestrator/conftest.py` (`run_l4(script, *flags, **config)`, `Run.events`, `Run.ledger`,
`Run.branch_ledger`, `Run.local_events`, `Run.subjects`, `Run.outcome`, `fake_clock`, `install_hooks`, `BRANCH`,
`UNIT`); `tests/unit/implementer/conftest.py` (`red_step`, `green_step`, `make_bench`, `Bench`);
`tests/unit/orchestrator/test_soft_deadline.py` (`_cfg`, `_units`, `clock`, `_run`);
`tests/unit/orchestrator/test_continuation.py` (`FakeForge`, `forge`, `_go`, `CI`);
`tests/unit/forge/_github_helpers.py`
(`FakeGitHub`); `tests/unit/ci/test_pin_guard.py` (`make_repo`, `app_for`, `guarded`, `PINNED`);
`tests/unit/yolo/test_yolo_status_activity.py` (`_describe`, `_units`, `_at`, `NOW`, `LINK`, `UNIT`, `RUN`);
`tests/unit/verifier/test_ladder.py` (the real ladder); `tests/unit/implementer/test_held_accept.py` (a held step, its
question, a person's accept and the replay).
For an `l4 run` test with a known budget, the environ of `tdd_repo` gets `L4_JOB_TIMEOUT_MINUTES=180` and
`L4_JOB_STARTED_AT` set to the `FakeClock`'s start, plus `GITHUB_ACTIONS=true` only where the continuation is under
test (with `make_forge` monkeypatched to a `FakeForge`).

## 1. Group A: the run deadline and the job's start (design D1, D2; L4-IMP-066)

- [x] 1.1 The module and the test isolation. Tests first, new `tests/unit/test_deadline.py`:
  `test_the_module_imports_nothing_from_l4` (with `ast`);
  `test_remaining_and_fire` (a `FakeClock`, `at` 600 s ahead: `remaining_s() == 600`, `fired()` false, then after
  `fire()` true);
  `test_arm_starts_a_timer_and_disarm_cancels_it` (a `timer` factory passed to `arm` records the seconds it is given
  and is cancelled by `disarm`; `current()` is None after `disarm`);
  `test_the_estimate_has_a_floor_a_cap_and_a_fallback` (SCN-IMP-337: recorded greens `[300, 5000]` give 3600; `[120]`
  gives 600; no green measure and a red of 1410 measured gives 1410);
  `test_the_cap_is_per_phase` (SCN-IMP-361: `cap_s("verify", 1800) == 7200`, `cap_s("green", 1800) == 3600`; a recorded
  round of 7000 s gives 7000);
  `test_the_first_step_always_starts` (SCN-IMP-336: `started == 0`, 400 s left, recorded red 1800: no raise, then
  `started == 1` and `step.first` true);
  `test_a_step_that_does_not_fit_raises` (SCN-IMP-335: `DeadlineReached` with `when == "before"`, `exc.mark.phase ==
  "green"`, `exc.mark.left_at_start_s == 300`, `exc.mark.estimate_s == 1410`; `step` stays None and `started` does not
  move);
  `test_a_step_stopped_last_time_starts_only_first` (SCN-IMP-368: `stopped_last=True` raises with the D3 reason when
  `started >= 1`, and starts when `started == 0`);
  `test_check_before_is_idempotent_for_the_same_step` (two calls with the same phase, task and attempt: one start);
  `test_a_different_current_mark_is_replaced_unrecorded` (a green mark is current and `check_before` is called for the
  red of the same task: no `step.timed` for the green, `started` unchanged overall, the red mark keeps `first`);
  `test_the_mark_holds_the_step_and_end_step_clears_it` (`StepMark` fields; `end_step()` returns the seconds, updates
  `steps`, clears `step`);
  `test_no_deadline_no_check` (SCN-IMP-338: `current()` None, `check_before` returns);
  `test_deadline_reached_is_not_an_exception` (a `BaseException`, not an `Exception`);
  `test_no_l4_job_variable_reaches_a_test` (`os.environ` holds no `L4_JOB_*` inside a test).
  Code: new `src/l4/deadline.py` (D2, D3, Contracts); `tests/conftest.py` (`_AMBIENT_CI` also matches `L4_JOB_.*`, and
  an autouse fixture that calls `deadline.disarm()` after each test). Run: that file and `tests/unit/ci tests/unit/cli`
  (they read the CI environment: nothing
  else may change).

- [x] 1.2 The job's start and the arming. Tests first, `tests/unit/orchestrator/test_soft_deadline.py`:
  `test_l4_job_started_at_sets_the_start` (SCN-IMP-332);
  `test_l4_job_started_at_wins_over_ci_job_started_at`;
  `test_an_unparsable_start_is_skipped`;
  `test_an_unknown_start_is_said_once_as_a_warning` (SCN-IMP-333, `caplog` at WARNING, one line with `no
  L4_JOB_STARTED_AT` and `l4 upgrade` over two units);
  `test_job_budget_s` (the total before the margin: `time_budget` set, `CI_JOB_TIMEOUT`, `L4_JOB_TIMEOUT_MINUTES`,
  none);
  `test_run_units_arms_the_deadline_and_disarms_it` (with a budget, `deadline.current()` is set while a unit runs and
  None after `run_units` returns, also when the unit raises; without a budget it is never set);
  `test_run_units_carries_the_steps_started` (`CommandResult.steps_started` equals the deadline's `started` at the end).
  The existing tests of that file must pass unchanged. Code: `src/l4/orchestrator.py` (`job_budget_s`,
  `job_remaining_s`, `run_units`: arm after the first computation, `finally: disarm()`, the WARNING,
  `steps_started`), `src/l4/outcome.py` (`steps_started`). Run: that file and
  `tests/unit/orchestrator/test_wait_in_run.py`.

- [x] 1.3 The templates and `run.started`. Tests first:
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

- [x] 2.1 `ProcRunner`. Tests first, `tests/unit/agents/test_proc.py`:
  `test_the_deadline_stops_a_running_process_with_sigint_then_sigkill` (a child that ignores SIGINT and sleeps 60 s:
  after `deadline.current().fire()` from a timer thread at 0.5 s, `run` returns within 0.5 + 5 + 2 s with
  `interrupted` and `deadline` true, and the child's pid is gone);
  `test_a_child_that_exits_on_sigint_ends_before_the_grace` (it returns within 2 s);
  `test_a_process_started_after_the_deadline_is_stopped_at_once`;
  `test_the_deadline_wins_over_the_idle_rule_and_the_time_limit` (SCN-IMP-362: a silent child with
  `stall_timeout_s=0.2`, the deadline fired at 0.3 s inside the idle grace; and a child with `timeout_s=1` and the
  deadline fired at 1 s: each outcome has `deadline` true, `stalled` and `timed_out` false, and the `watch`'s
  `stopped_idle_s` is None);
  `test_without_a_deadline_nothing_changes` (`deadline` false, `interrupted` false).
  The existing tests of that file must pass. Code: `src/l4/agents/proc.py` (`ProcOutcome.deadline`; `_wait` checks
  `deadline.fired()` first in each poll). Run: `tests/unit/agents/test_proc.py tests/unit/agents`.

- [x] 2.2 Gates. Tests first:
  new `tests/unit/gates/test_runner_deadline.py`: `test_a_gate_stopped_by_the_deadline_says_so` (a real command, a
  Python script that writes a marker file and sleeps 60 s; a thread that waits for the marker, at most 10 s, fires the
  deadline; `GateResult.deadline` true, `status == "fail"`, the script's pid gone);
  new `tests/unit/implementer/test_step_deadline.py` (`make_bench`):
  `test_run_gate_spec_raises_after_its_restores` (the same marker gate also writes a protected file: the file is put
  back, `gate.finished` is recorded, then `DeadlineReached` with `during == "gate"` and `gate` the gate's name);
  `test_a_gate_that_ends_before_the_deadline_returns_its_result`.
  Code: `src/l4/gates/runner.py` (`GateResult.deadline`), `src/l4/implementer/workbench.py` (`run_gate_spec`, after
  `gate.finished`). Run: those files and `tests/unit/gates tests/unit/implementer/test_setup.py`.

- [x] 2.3 The agent step and the CLI judge. Tests first:
  `tests/unit/implementer/test_step_deadline.py`:
  `test_a_stopped_agent_records_its_end_and_raises` (a fake step whose `on_start` fires the deadline and that writes
  `half.txt`; `agent.finished` and `budget.cost` are recorded, `step.finished{status: deadline}`, no `agent.idle`,
  `half.txt` is not in the worktree's index, protected paths are put back, then `DeadlineReached` with `during ==
  "agent"`);
  `test_a_cancelled_run_without_the_deadline_is_still_a_failed_step` (today's text `ended with status cancelled`).
  New `tests/unit/llm/test_agent_judge_deadline.py`: `test_a_stopped_cli_judge_raises` and
  `test_a_cancelled_judge_without_the_deadline_is_an_error_result`.
  `tests/unit/agents/test_fake.py`: `test_on_start_runs_first` and
  `test_the_fake_honours_the_interrupt_and_the_deadline`
  (status `cancelled`).
  Code: `src/l4/agents/fake.py` (`Step.on_start`, the interrupt), `src/l4/implementer/tdd.py` (`agent_step`: the raise
  after the cost events; `box.status = "deadline"`), `src/l4/llm/agent_judge.py` (`_run`). Run: those files,
  `tests/unit/implementer/test_liveness_step.py`, `tests/unit/llm`. Commit `run-continuation A2: …`.

## 3. Group A: before each step, the hand-back and the replay (design D3, D5; L4-IMP-067, L4-IMP-069)

- [x] 3.1 The checks before each step. Tests first, `tests/unit/orchestrator/test_step_deadline.py`:
  `test_a_green_that_does_not_fit_is_not_started` (SCN-IMP-335: `red_step(on_start=…)` moves `fake_clock` 1410 s, the
  job started 155·60 − 1410 s before the red began; the green is never requested from the adapter;
  `deadline.reached{when: before, phase: green, left_s: 300, estimate_s: 1410}`; the outcome's `exit_reason` is the
  D5 text);
  `test_the_first_step_of_a_run_always_starts` (SCN-IMP-336);
  `test_the_estimate_reads_the_units_recorded_steps` (SCN-IMP-337 end to end: earlier `step.timed` seeded in the
  unit's ledger on its branch);
  `test_no_budget_no_check` (SCN-IMP-338);
  `test_every_started_step_records_step_timed` (red and green, with their seconds on the `FakeClock`);
  `test_a_resumed_green_is_checked_before_its_baseline` (SCN-IMP-360, first part: a branch holding task 1.1's red
  commit and `task.red_ok`, 300 s left, not the first step (a first unit ran before it in `_run` style, or
  `deadline.current().started` set to 1); no `gate.finished{name: baseline}`, no `task.red_resumed`, and
  `deadline.reached{when: before, phase: green}`);
  `test_a_step_after_a_fall_back_is_checked` (SCN-IMP-360, second part: a green that hits a usage limit, the next
  profile, 300 s left: the new `run_task` is deferred before any gate);
  `test_a_resumed_red_without_red_ok_runs_red_under_one_mark` (the branch holds the red commit but no `task.red_ok`:
  the top check marks green, `resume_red` returns None, the loop's red check replaces the mark; one `step.timed`, for
  red);
  `test_a_verification_round_that_does_not_fit_is_not_started` (SCN-IMP-361 end to end: `install_hooks` with a verify
  hook that fails the test if called; a recorded `step.timed{phase: verify, seconds: 7000}` and 6800 s left).
  Code: `src/l4/implementer/loop.py` (`run_task`: `check_before` at the top before `resume_red`, with the phase from
  `_last_checkpoint`, and before `run_single`, `run_red`, `run_green`; `end_step` and `step.timed` after each, except
  when `DeadlineReached` passes), `src/l4/orchestrator.py` (`_verify`: the check before `verify(self._ctx)` and the
  round's `step.timed`). Run: that file, `tests/unit/implementer/test_loop.py`,
  `tests/unit/orchestrator/test_run_unit.py`, `tests/unit/orchestrator/test_fallback.py`.

- [x] 3.2 The hand-back. Tests first, same file:
  `test_the_hand_back_is_pushed_and_exits_10` (SCN-IMP-342: the unit stays `implementing`; `Run.branch_ledger()` holds
  `deadline.reached`, `lock.released` and `run.finished{exit_code: 10, reason}` with the reason starting `soft
  deadline:`; no `task.attempt_failed`; `run.code == 10`);
  `test_the_next_run_continues_at_green` (SCN-IMP-343: a second `run_l4` without the budget; one `test(` commit and one
  `feat(` commit in `Run.subjects()`);
  `test_an_agent_stopped_at_the_deadline_is_handed_back` (SCN-IMP-339 end to end: `green_step(on_start=fire,
  writes={"half.txt": "x"})`; `half.txt` is in no commit of origin's branch; `step.finished{status: deadline}`;
  `deadline.reached` has `phase: green`, `task: "1.1"`, `attempt: 1`, `ran_s`, `left_at_start_s`, `estimate_s` and
  `first` from the mark: the agent raise site);
  `test_a_gate_stopped_at_the_deadline_is_handed_back` (SCN-IMP-340 end to end: the red's test gate command is the
  marker script of 2.2; no red commit, no failed attempt; the event's fields from the mark: the gate raise site);
  `test_a_stopped_clarifier_records_the_units_phase` (SCN-IMP-363: a CLI clarifier stopped with no mark: `phase:
  clarifying`, `first: false`, no task, exit 10: the judge raise site with no step).
  New `tests/unit/verifier/test_ladder_deadline.py` (the real ladder of `test_ladder.py`):
  `test_a_stopped_judge_writes_the_calibration_and_fails_no_step` (SCN-IMP-341: the round's CLI judge is stopped; the
  `_calibrate` rows are written, no `verify.step{status: failed}` for the judge step, no `verify.verdict`, and
  `DeadlineReached` reaches `run_unit`, which records `deadline.reached{during: judge, phase: verify, round}`; the unit
  stays `verifying`, exit 10).
  `tests/unit/orchestrator/test_soft_deadline.py`: `test_no_unit_starts_after_a_hand_back` (SCN-IMP-344, with `_run`
  and a first unit whose result has `deferred=True`).
  `tests/unit/orchestrator/test_step_deadline.py`: `test_a_stop_during_the_idle_grace_is_a_hand_back` (SCN-IMP-362 end
  to end: a fake step with `idle_s` and `on_start` that fires the deadline: no `agent.idle`, no attempt).
  Code: `src/l4/orchestrator.py` (`run_unit`: `except DeadlineReached`; `_defer` with the mark;
  `UnitRunResult.deferred`;
  `run_units`; `CommandResult.deferred` through `run_command`), `src/l4/state/ledger.py` (`finish(exit_code,
  reason=None)`), `src/l4/outcome.py` (`deferred`). Run: those files, `tests/unit/orchestrator`,
  `tests/unit/verifier/test_ladder.py`.

- [x] 3.3 A stopped replay is replayed again (review M4). Tests first, new
  `tests/unit/implementer/test_held_replay_deadline.py` (the held world of `test_held_accept.py`):
  `test_a_replay_stopped_in_its_gate_is_replayed_again` (SCN-IMP-364: a person's accept, the replay's test gate stopped
  after `held.replayed`; the next run makes no agent request, records a second `held.replayed` and commits the step
  with the accept applied);
  `test_a_replay_followed_by_a_commit_is_spent` (a `held.replayed` followed by `task.green_committed`, then a stop of a
  later step: not void);
  `test_replay_voided_reads_the_task_and_phase` (unit test of `replay_voided`: another task's stop, or another phase's,
  leaves the replay spent);
  `test_the_used_up_notice_ignores_a_void_replay` (the accepted-tests block of `held_patch.py:869` does not print the
  used-up notice for a void replay).
  Code: `src/l4/implementer/held_patch.py` (`replay_voided`; its use at the three readers of `held.replayed`). Run:
  those files and `tests/unit/implementer/test_held_*.py`. Commit `run-continuation A3: …`.

## 4. Group A: one continuation, and a step that never fits (design D6, D7; L4-IMP-070, L4-IMP-071)

- [x] 4.1 The continuation. Tests first, `tests/unit/orchestrator/test_continuation.py`:
  `test_a_hand_back_dispatches_once` (SCN-IMP-345 at function level: `result.deferred == ["openspec:a"]`, code 10);
  `test_a_more_severe_designed_stop_still_dispatches` (SCN-IMP-346: code 11 and a hand-back; also 12 and 13);
  `test_a_failure_code_does_not_dispatch` (parametrized 1, 2, 3, 14, 16);
  `test_no_step_started_no_continuation` (SCN-IMP-347 at function level: `steps_started == 0`; the WARNING text);
  `test_the_plan_next_run_is_skipped_after_a_continuation` (`run_command` level, `make_forge` monkeypatched to a fake
  that records `dispatch_continuation` and `start_run`; a plan step with `start_next_run=True`; exactly one call, to
  `dispatch_continuation`; with `already_queued`, still no `start_run`).
  `tests/unit/forge/test_dispatch_continuation.py`: `test_the_dispatching_runs_own_progress_does_not_block`
  (SCN-IMP-365: the listing holds this run `in_progress`: the dispatch is sent; a `queued` run: nothing).
  `tests/unit/orchestrator/test_step_deadline.py`: `test_one_dispatch_for_a_plan_unit_handed_back` (SCN-IMP-345 end to
  end, `GITHUB_ACTIONS=true`, a `FakeForge`; `outcome.json` `continuation: dispatched`; `plan: next run on` is not
  logged); `test_no_step_started_sends_nothing_at_all` (SCN-IMP-347 end to end: an active plan, the job's start more
  than the usable budget ago; the `FakeForge` records neither `dispatch_continuation` nor `start_run`; the WARNING).
  The existing tests of `test_continuation.py` must pass. Code: `src/l4/orchestrator.py` (`continue_left_units`,
  `run_command`: clear `step.start_next_run` after a continuation and when no step started). Run: those files and
  `tests/unit/yolo/test_yolo_cycle*.py`.

- [x] 4.2 GitLab. Tests first, new `tests/unit/forge/test_gitlab_continuation.py` (the HTTP fakes of
  `test_gitlab_pipelines.py`):
  `test_no_waiting_pipeline_starts_one` (SCN-IMP-366: `POST /pipeline {ref}`, `dispatched`);
  `test_a_waiting_pipeline_starts_nothing` (parametrized `created`, `waiting_for_resource`, `preparing`, `pending`,
  `scheduled`: `already_queued`);
  `test_a_running_pipeline_and_the_own_pipeline_do_not_count` (`running`, and the pipeline whose id is
  `CI_PIPELINE_ID`);
  `test_a_refused_start_is_unsupported_with_a_warning` (403 and 404).
  `tests/unit/orchestrator/test_continuation.py`: `test_a_gitlab_hand_back_dispatches` (`GITLAB_CI=true`).
  Code: `src/l4/forge/gitlab.py` (`dispatch_continuation`). Run: `tests/unit/forge
  tests/unit/orchestrator/test_continuation.py`.

- [x] 4.3 The halt. Tests first, `tests/unit/orchestrator/test_step_deadline.py`:
  `test_a_green_stopped_twice_halts` (SCN-IMP-348: two runs whose green is the first step and is stopped by
  `on_start=fire`; after the second, `breaker.tripped{reason: deadline_repeated, task: "1.1", phase: green, stops: 2}`,
  phase `halted`, the reason holds `timeout-minutes` and `l4 retry --unit`, and no continuation is sent with a
  `FakeForge`);
  `test_a_checkpoint_between_two_stops_resets_the_count` (SCN-IMP-349);
  `test_a_retry_a_resume_or_a_restart_resets_the_count` (SCN-IMP-367, first part, parametrized over `unit.retried`,
  `unit.resumed` and `unit.restarted` seeded between the stops);
  `test_a_round_counts_from_its_verdict` (SCN-IMP-367, second part);
  `test_a_stopped_step_starts_only_as_the_first_step` (SCN-IMP-368: another unit runs first in the run; the stopped
  green is deferred with the D3 reason; in the next run, where it is first, it starts);
  `test_an_attempt_that_ran_to_its_end_clears_stopped_last` (a stop, then a `step.timed` of the same task and phase:
  `stopped_last` is false);
  `test_the_halt_text_shows_both_stops` (the two `left_at_start_s` and `estimate_s` in the reason);
  `test_a_late_stop_on_a_small_estimate_still_counts_when_it_had_its_estimate` (`left_at_start_s >= estimate_s`,
  not first: counted);
  `test_a_step_not_started_never_counts` and `test_a_stop_with_no_mark_never_counts`;
  `test_the_stopped_time_feeds_the_estimate` (`ran_s` of a stop is read as a measure of its phase);
  `test_a_halt_of_a_round_has_no_task` (a verification round stopped twice as the first step: the halt has `task:
  null`; `l4 status` prints its cause and `l4 retry --unit` brings it back; `note_binding` and the sticky section take
  a halt without a task, as for `baseline_failed`).
  Code: `src/l4/orchestrator.py` (`_defer`, D7; the `stopped_last` argument handed to `check_before` by `run_task` and
  `_verify`), `src/l4/deadline.py` (`ran_s` in the estimate). Run: that file,
  `tests/unit/orchestrator/test_halt_codes.py`,
  `tests/unit/orchestrator/test_park_retry.py`, `tests/unit/state`.

- [x] 4.4 Failed attempts count across runs (design D7b; L4-IMP-075). Tests first:
  `tests/unit/implementer/test_loop.py`: `test_seed_attempts_reads_the_window` (`task.attempt_failed` before the last
  `task.red_committed`, before a `unit.retried`, `unit.resumed` or `unit.restarted`, of another task, or of another
  fix unit are not counted; the rest give `failures[phase][profile]`, `reasons[phase]` and the highest attempt, a
  `deadline.reached{when: during}` included);
  `test_seeded_failures_reach_max_task_attempts` (two seeded green failures and `max_task_attempts: 3`: one more
  failure halts the task);
  `test_seeded_failures_escalate_before_the_first_attempt` (SCN-IMP-379 at loop level).
  `tests/unit/orchestrator/test_step_deadline.py`:
  `test_a_stop_then_a_failure_then_a_timely_attempt` (SCN-IMP-377: run 1 stops the green; run 2 fails attempt 1 as
  the first step, then starts attempt 2 because its `step.timed` cleared `stopped_last`, and that attempt is handed
  back; run 3 starts at attempt 3 with 2 failures counted);
  `test_failures_of_earlier_runs_halt_the_unit` (SCN-IMP-378: run 1 fails attempts 1 and 2 (each `on_start` moves the
  `FakeClock` 3600 s) and defers attempt 3; run 2 fails attempt 3 as its first step: `halted`, `max_task_attempts`, no
  continuation);
  `test_escalate_after_holds_across_runs` (SCN-IMP-379 end to end, two profiles as in `test_fallback.py`).
  Code: `src/l4/implementer/loop.py` (`seed_attempts`; `run_task` seeds before the D3 check and escalates when the
  seeded count says so). Run: those files, `tests/unit/orchestrator/test_escalation.py`,
  `tests/unit/implementer/test_escalation.py`. Commit `run-continuation A4: …`.

## 5. Group A: docs (L4-IMP-066 to L4-IMP-071)

- [x] 5.1 Tests first, new `tests/unit/docs/test_run_continuation_docs.py`, part A, on the model of
  `tests/unit/docs/test_yolo_guardrails_docs.py`:
  `test_the_spec_has_the_deadline_requirements_and_scenarios_in_order` (`**L4-IMP-066 ` to `**L4-IMP-071 ` after
  `**L4-IMP-065 ` and before `## 8.`, and `**L4-IMP-075 ` after the place of `**L4-IMP-074 `; `#### SCN-IMP-332 ` to
  `#### SCN-IMP-349 `, `#### SCN-IMP-360 ` to `#### SCN-IMP-368 ` and `#### SCN-IMP-377 ` to `#### SCN-IMP-379 ` in
  increasing order after `#### SCN-IMP-331 ` and before `### 23.8`);
  `test_the_spec_amendments_are_made` (L4-IMP-012 no longer lists "the SIGINT of a running agent", "the estimate per
  phase" or "the continuation dispatch" as still to do, and still names the WIP push; SCN-IMP-19's **Then** says the
  ledger and the unit branch are pushed and the WIP snapshot stays local until M2; L4-CI-004 names `10, 11, 12 or 13`
  and the GitLab pipeline and no longer says GitLab answers `unsupported`; the §3.2 comment of
  `soft_deadline_margin` names the longest call that cannot be stopped);
  `test_the_changelog_has_the_deadline_lines_under_0_4_19` (in `## 0.4.19 (unreleased)`: `L4_JOB_STARTED_AT`,
  `deadline.reached`, `deadline_repeated`, `soft deadline:`, `limit_runs`, `count across runs`).
  Code: `docs/SPEC.md` (the requirement texts of `specs/step-deadline/spec.md`, L4-IMP-075 included; the scenarios in
  the Part II form
  `#### SCN-IMP-NNN (+|−) Title · L4-IMP-0NN` with `- **Given**`/`- **When**`/`- **Then**`; the amendments of design
  D10: L4-IMP-012, SCN-IMP-19, L4-CI-004, the §3.2 comment), `CHANGELOG.md` (the lines marked (A) below, under a new
  `## 0.4.19 (unreleased)` above `## 0.4.18 (2026-10-20)` if it is not there). Run: that file, `tests/unit/docs`,
  `scripts/check_spec.py docs/SPEC.md`, `openspec validate run-continuation --strict`.
  Then the whole of group A once: `tests/unit/orchestrator tests/unit/implementer tests/unit/agents tests/unit/gates
  tests/unit/llm tests/unit/ci tests/unit/verifier tests/unit/yolo tests/unit/forge tests/unit/state tests/unit/docs
  tests/unit/test_deadline.py`. Commit `run-continuation A5: …`.

## 6. Group B: the relay before the configuration (design D8; L4-IMP-072, L4-IMP-074)

- [x] 6.1 The forge. Tests first, new `tests/unit/forge/test_relay_run.py` (`FakeGitHub`):
  `test_no_other_active_run_dispatches_the_base`;
  `test_an_active_run_sends_nothing` (parametrized `queued`, `pending`, `waiting`, `requested`, `in_progress`);
  `test_the_own_run_is_left_out` (the only `in_progress` run has `id == exclude_run_id`);
  `test_completed_runs_do_not_count`;
  `test_403_is_refused_and_404_is_unsupported`;
  `test_base_runs_counts_the_waiting_and_running_runs` (GitHub, and GitLab's pipelines `created` to `running`; None on
  an error);
  `test_gitlab_and_local_relay_answers_unsupported`.
  `tests/unit/forge/test_dispatch_continuation.py` must pass unchanged apart from 4.1's test. Code:
  `src/l4/forge/base.py` (the protocol methods), `src/l4/forge/github.py`, `src/l4/forge/gitlab.py`,
  `src/l4/forge/local.py` (`relay_run`, `base_runs`; the local forge records its calls like `dispatch_continuation`).
  Run: `tests/unit/forge`.

- [x] 6.2 The early stop and `relay_to_base`. Tests first, new `tests/unit/ci/test_relay.py` (the `make_repo`,
  `app_for` and `guarded` of `test_pin_guard.py`; `make_forge`, or the forge class the relay builds, monkeypatched to a
  fake whose `relay_run` answer the test sets; `RUNNER_TEMP` set to a `tmp_path` folder):
  `test_the_lenient_settings_ignore_unknown_keys` (a config with an unknown key: the eight keys are read; a file that
  is not YAML gives `{}`);
  `test_the_lenient_read_keeps_yaml_1_2_values_and_finds_the_delivery` (SCN-IMP-384: `base_branch: on` stays `"on"`; a
  mapping or a list at a listed key is ignored; no `harness.delivery` and a setup-action pin in the workflow give
  `action`; a symlinked file and one over 1 MB give `{}`; `forge.platform` is not read, `forge.type` is);
  `test_the_relay_forge_is_built_from_forge_keys_only` (a `ci.platform: gitlab` in the file does not change the
  forge: GitHub, from `GITHUB_ACTIONS`);
  `test_a_scheduled_run_on_the_default_branch_relays` (SCN-IMP-350: `l4 doctor --ci` through `l4.cli.main`; the two
  lines on stderr in order, one `relay_run` call with the base and `GITHUB_RUN_ID`; then `l4 run`: exit 0, no work,
  `outcome.json` `relay: dispatched`);
  `test_an_active_run_on_the_base_is_not_doubled` (SCN-IMP-351);
  `test_a_mismatch_on_the_base_does_not_relay` (SCN-IMP-352: the configuration loads first; `relay: on_base`);
  `test_on_the_base_a_schema_error_stays_exit_2` (SCN-IMP-381);
  `test_no_work_is_not_relayed` (SCN-IMP-353, a real repository with no plan ref, no unit branch, no unit folder);
  `test_an_active_plan_and_a_waiting_plan_are_work` (plan refs seeded with `plan.activated`, and `plan.waiting`);
  `test_an_unreadable_plan_ref_is_work` (SCN-IMP-354);
  `test_a_unit_branch_or_a_unit_folder_is_work` (SCN-IMP-371, the archive folder alone is not);
  `test_a_refused_token_names_the_command` (SCN-IMP-355: `refused`, and no token at all);
  `test_outside_github_nothing_is_relayed` (SCN-IMP-356: `GITLAB_CI=true`, no `relay` key);
  `test_a_config_key_the_harness_does_not_know_does_not_defeat_the_relay` (SCN-IMP-369: `doctor --ci`, `plan --sweep`,
  `run` and `status` in order through `l4.cli.main`; doctor relays and exits 0 with no check row; the other three exit
  0 before the load; one dispatch);
  `test_the_status_step_of_a_stopped_job_is_not_red` (SCN-IMP-382: `l4 status` prints the warning, no forge call,
  exit 0);
  `test_one_relay_per_job` (SCN-IMP-370: the marker; the later commands print `relayed earlier in this job` and make no
  forge call; without `RUNNER_TEMP` the marker is `.l4-out/relay.json`);
  `test_a_marker_of_another_run_attempt_or_job_is_ignored` (SCN-IMP-370, last clause: each of `run_id`,
  `run_attempt`, `job` differing makes the command relay).
  The existing tests of `test_pin_guard.py` and `tests/unit/doctor/test_doctor_load_errors.py` must pass (a schema
  error outside a stale pin still exits 2), and the doctor tests of CFG-008 on a mismatch off the base now expect the
  early stop (no rows). Code: new `src/l4/ci/relay.py`; `src/l4/doctor/run.py`, `src/l4/planner.py`,
  `src/l4/orchestrator.py`, `src/l4/state/status.py` (or the `l4 status` handler: `early_pin_stop` first, before
  `load_app_config`), `src/l4/outcome.py` (`relay`). Run: `tests/unit/ci/test_relay.py tests/unit/ci/test_pin_guard.py
  tests/unit/doctor
  tests/unit/orchestrator/test_run_command.py tests/unit/cli`.

- [x] 6.3 The base's warning (L4-IMP-074). Tests first, new `tests/unit/ci/test_default_copy_warning.py` (a bare
  `origin` with a `main` and a `staging`, an event payload file under `tmp_path` as `GITHUB_EVENT_PATH`):
  `test_an_older_default_copy_is_named` (SCN-IMP-375: the one `::warning::` with `main`, both short shas, `v0.4.18`,
  `cannot relay` and the copy step);
  `test_a_newer_release_says_they_relay` and `test_an_unknown_release_uses_the_conditional_wording` (SCN-IMP-383: no
  comment, the copy form, and a `# main` comment);
  `test_releases_compare_as_numbers` (`parse_release("# v0.4.9") < (0, 4, 19)`; `# main` gives None);
  `test_a_default_branch_without_the_workflow_is_named` (SCN-IMP-383, last case);
  `test_no_warning_for_the_same_pin_an_unknown_default_or_another_delivery` (SCN-IMP-376);
  `test_run_prints_it_once_on_the_base` (through `run_command`, `GITHUB_REF_NAME=staging`).
  Code: `src/l4/ci/relay.py` (`default_copy_warning`), `src/l4/orchestrator.py` (`run_command`, on the base). Run:
  that file and `tests/unit/ci`.

- [x] 6.4 The upgrade reminder. Tests first, `tests/unit/init/test_upgrade.py`:
  `test_the_default_branch_reminder_names_the_relay` (a known default branch that is not the base: today's text plus
  `; from 0.4.19 on, that copy's scheduled runs relay to <base>`);
  `test_an_unset_origin_head_still_reminds` (`origin/HEAD` unset: the D8 text with `if the default branch is not
  <base>`).
  Code: `src/l4/init/upgrade.py` (`_default_branch_reminder`). Run: `tests/unit/init`. Commit `run-continuation B1: …`.

## 7. Group B: `l4 yolo status` (design D9; L4-IMP-073)

- [x] 7.1 The forge's view of a CI run. Tests first, new `tests/unit/forge/test_ci_run_state.py`:
  `test_a_github_run_url_is_read` (`GET /repos/{r}/actions/runs/{id}`; `completed` with the conclusion `cancelled`;
  `in_progress` is `running`);
  `test_a_re_run_reads_its_attempt` (`…/runs/77/attempts/2` → `GET /repos/{r}/actions/runs/77/attempts/2`);
  `test_a_gitlab_job_url_is_read`;
  `test_the_get_has_a_short_timeout` (the request is made with a timeout of at most 10 s);
  `test_an_unknown_url_or_an_error_is_unknown`;
  `test_local_is_unknown`.
  Code: `src/l4/forge/base.py`, `github.py`, `gitlab.py`, `local.py` (`ci_run_state`). Run: `tests/unit/forge`.

- [x] 7.2 Status. Tests first, new `tests/unit/yolo/test_yolo_status_open_run.py` (the helpers of
  `test_yolo_status_activity.py`, with `OpenRun(..., job_timeout_s=…)`, `ctx` given `app` and `cfg`, and the forge
  monkeypatched):
  `test_an_open_run_older_than_its_timeout_ended_without_a_record` (SCN-IMP-357: the text line, the `Next:` line with
  `gh workflow run l4.yml --ref main`, the JSON keys, the same `next`);
  `test_an_older_run_started_without_the_timeout_assumes_180_minutes` (SCN-IMP-357, last clause);
  `test_the_ci_says_completed` (SCN-IMP-358);
  `test_a_young_run_without_an_answer_is_unchanged` (SCN-IMP-359);
  `test_the_forge_is_asked_only_when_the_age_does_not_decide` (SCN-IMP-372: an old open run with a forge that fails
  when called; a re-run URL; an open run with no `ci_url` and no age rule);
  `test_a_stopped_plan_keeps_its_next` (SCN-IMP-373) and `test_a_waiting_plan_keeps_its_next`;
  `test_an_active_plan_idle_for_two_periods_names_the_command` (SCN-IMP-374: newest event 70 minutes old, `*/30`,
  `base_runs == 0`, the idle time in the line; with 1, today's line; with None, today's line);
  `test_between_two_ticks_the_schedule_is_trusted` (SCN-IMP-380: 20 minutes idle: today's line);
  `test_no_schedule_names_the_command` (SCN-IMP-380: `ci.schedule: null`; and an `origin/HEAD` default branch whose
  copy pins another harness: the reason names it);
  `test_cron_period_s` (`*/30 * * * *` 1800; `15 * * * *` 3600; `0 6 * * *` 86400; `0 6 * * 1` 3600; None for null);
  `test_gitlab_names_the_new_pipeline_page`.
  `tests/unit/state/test_status_activity.py`: `test_open_run_reads_job_timeout_s`.
  Update `tests/unit/yolo/test_yolo_status_activity.py::test_active_plan_shows_unit_activity_and_open_run`: the
  `open_run` dict also has `ended_without_record: False`. Code: `src/l4/state/status.py` (`OpenRun.job_timeout_s`,
  `_activity`), `src/l4/yolo/commands.py` (`_activity_of`, `_describe`, `_next_line`, `_render`). Run: those files,
  `tests/unit/yolo/test_yolo_commands_manage.py`, `tests/unit/state`, `tests/unit/mcp`. Commit
  `run-continuation B2: …`.

## 8. Group B: docs, SPEC and CHANGELOG (design D10)

- [x] 8.1 Tests first, `tests/unit/docs/test_run_continuation_docs.py`, part B:
  `test_the_spec_has_the_relay_and_status_requirements` (`**L4-IMP-072 ` to `**L4-IMP-074 ` after `**L4-IMP-071 ` and
  before `**L4-IMP-075 `; `#### SCN-IMP-350 ` to `#### SCN-IMP-359 `, `#### SCN-IMP-369 ` to `#### SCN-IMP-376 ` and
  `#### SCN-IMP-380 ` to `#### SCN-IMP-384 ` in increasing order, before `### 23.8`; L4-ADO-005 names `L4-IMP-072` and
  `L4-IMP-074`; L4-YOLO-030 names `ended without a record` and `nothing is
  running or queued`; `| 56 | \`run-continuation\` |`);
  `test_the_runbook_and_the_yolo_doc_say_what_needs_the_copy` (`docs/runbook.md` has `ended without a record`,
  `gh workflow run l4.yml --ref` and `copy .github/workflows/l4.yml to the default branch once (or promote the base)`;
  `docs/yolo-mode.md` names the relay and the copy);
  `test_the_skill_error_table_has_the_three_rows` (`plugins/l4/skills/l4/references/operate.md`: `ended without a
  record`, `nothing is running or queued`, `deadline_repeated`);
  `test_the_changelog_names_the_relay_the_copy_and_the_status` (in `## 0.4.19 (unreleased)`: `relay`, `before the
  configuration`, `copy .github/workflows/l4.yml to the default branch once`, `ended without a record`).
  The existing docs tests must pass: `test_yolo_guardrails_docs.py`, `test_force_accept_docs.py`,
  `test_control_loop_agent_docs.py` (every `l4 …` span of the skill resolves). Code: `docs/SPEC.md` (requirements 072
  to 074, their scenarios, the L4-ADO-005 sentences, the L4-YOLO-030 text, row 56), `docs/runbook.md`,
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
  and the run warns once (L4-IMP-066).
- (A) Before each implementer step and each verification round, a run with a known budget compares the time left
  with the step's estimate. The estimate is the longest step of that kind in this run or among the unit's recorded
  steps, at least 10 minutes and at most one agent time limit plus `gates.timeout` (four gate timeouts for a round). A
  step that does not fit is not started; a resumed green is checked before its baseline. The first step of a run
  always starts. Every step records `step.timed` (L4-IMP-067).
- (A) At the soft deadline, every agent, CLI judge and gate that the unit's run has running gets SIGINT, then SIGKILL
  after 5 s. The step is handed back: `deadline.reached` is recorded, no attempt is counted, the phase does not change,
  the ledger and the unit branch are pushed, `run.finished` has `reason: soft deadline: …`, and the run exits 10. The
  next run continues from the last pushed step, and a stopped replay of a held step is replayed again (L4-IMP-068,
  L4-IMP-069).
- (A) A step stopped at the soft deadline starts again only as the first step of a run, and a second stop halts the
  unit with `deadline_repeated`. The reason names the job timeout to raise and `l4 retry` (L4-IMP-071).
- (B) A GitHub run that the pin guard stops off the base (a scheduled run on a default branch that is not the base,
  or a push to an old unit branch) relays to the base before it reads the configuration, so a configuration key that
  its older harness does not know cannot stop it. `l4 doctor --ci`, `l4 plan --sweep`, `l4 run` and `l4 status` stop
  there and exit 0; the first of the first three dispatches `l4.yml` on the base once per job, when the base may have
  work and no other run of `l4.yml` is queued or running there, and prints what it did (`outcome.json` `relay`). On
  the base itself a configuration error stays exit 2. It works once the default branch's copy pins 0.4.19 or later: copy
  .github/workflows/l4.yml to the default branch once (or promote the base); the base's own run warns while that copy
  is behind, or missing (L4-IMP-072, L4-IMP-074).
- (B) `l4 yolo status` calls an open run "ended without a record" when it is older than its job timeout (recorded on
  `run.started` as `job_timeout_s`) or when the forge says its CI run completed. For an active plan whose open run
  ended without a record, or with nothing running or queued on the base and either idle for two schedule periods or
  with no schedule that can advance it, `Next:` gives the command that starts a run on the base (`gh workflow run
  l4.yml --ref <base>`). `--json` has `open_run.ended_without_record` and `open_run.why`
  (L4-IMP-073).

### Changed
- (A) A continuation is dispatched for a unit handed back or left at the soft deadline even when another unit of the
  run exits 11, 12 or 13. When it is dispatched, the plan's own next-run start of the same run is not sent: one dispatch
  per run. A run in which no step started dispatches nothing and says so. On GitLab the continuation is now a pipeline
  on the base, and none is started while one waits. Each continuation is one more run of a delivery plan, so a plan's
  `limits.max_runs` is reached sooner (`limit_runs`; `l4 yolo resume --extend-runs N`) (L4-IMP-070).
- (A) Failed attempts of a task count across runs: `implementer.max_task_attempts` and `implementer.escalate_after`
  read the task's `task.attempt_failed` since its last commit, retry, resume or restart, so a run that hands back and
  continues does not give a task fresh attempts (L4-IMP-075).
- (B) In GitHub Actions, on a copy of the workflow that is not the base's, `l4 doctor --ci` stops before the
  configuration and its checks, prints the pin warning and exits 0 (before, it could exit 2 on a configuration key its
  older harness does not know) (L4-IMP-072).

### Fixed
- (A) A run with a known job timeout is no longer killed by the CI timeout in the middle of an agent step, which left
  an open run with no end and no continuation (L4-IMP-012, L4-IMP-068).
- (B) `l4 yolo status` no longer says `nothing: CI advances the plan at each run` for an active plan that nothing will
  advance (L4-IMP-073).
