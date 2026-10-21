Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first; the decisions D1..D14 are referred to below.
- Work on the base that holds 0.4.18 (0.4.17 and the held-accept work merged). Where a name below differs on that base
  (`still_waits`, the kept patch of a held step, the sandbox's empty home, `plan.extended`), use the base's and say so in
  the commit message.
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>` (`uv sync` once if `.venv`
  is missing). Then `ruff check` and `ruff format --check` on the files that changed. Task 17.1 also runs
  `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...` (it matches itself and never ends). Stage explicit paths only.
- Name a consumer "a consumer repository". Fixture names stay neutral (`add-login`, `store`, `pytdd`).
- When a signature changes, update every caller and every test fake of it: `grep -rn "<name>" src tests`.
- Agents in tests are the scripted `fake` adapter (`src/l4/agents/fake.py`); no test calls a real model.
- A delegate test unit is built with the helpers of `tests/unit/clarifier/conftest.py` and
  `tests/unit/specs/questions_world.py` (a repository with a unit branch on a bare `origin`).

## 1. Configuration (L4-DLG-001, L4-DLG-009, L4-AVL-010; D1, D2, D10)

- [ ] 1.1 `delegate:` and `roles.delegate`.
  - Tests first, `tests/unit/config/test_delegate_config.py`:
    - `test_delegate_defaults`: `L4Config().delegate` has `enabled is False`, `scope == "yolo"`, `kinds ==
      ["technical", "product", "ambiguous", "harness", "verdict"]`, `independence == "model"`,
      `max_attempts_per_question == 2`, `max_answers_per_task == 3`, `max_questions_per_run == 5`,
      `max_cost_usd_per_answer == 3.0`, `max_cost_usd_per_unit == 15.0`, `plan_cost_share == 0.25`,
      `timeout == "15m"`, `unfreeze is False`; `L4Config().roles.delegate == []`.
    - `test_delegate_rejects_bad_values` (parametrized): `scope: x`, an unknown kind, `independence: vendor`,
      `plan_cost_share` 0 or 1.5, a negative cost, `timeout: 30s`, any `max_*` below 1: each a config error whose
      message names the key and not the value.
    - `test_delegate_is_an_optional_role`: `"delegate"` is a field of `RolesCfg` and not in `REQUIRED_ROLES`;
      `Factory.for_role("delegate", unit)` with an empty chain raises `RoleUnavailable` with `no profile is configured
      for it under roles`.
    - `test_delegate_settings_come_from_the_base`: `delegate_settings(git, base)` returns the `delegate` section and
      `roles.delegate` of `.l4/config.yaml` at `refs/remotes/origin/<base>` (through `target_full_config`); a value
      committed only on a unit branch is not seen; an absent or invalid file gives the defaults (`enabled False`)
      (SCN-DLG-02).
  - `src/l4/config/schema.py`: `DelegateCfg(_Strict)` with the fields and validators above (`timeout` a `Duration` of at
    least `1m`); `RolesCfg.delegate: list[str]`; `L4Config.delegate: DelegateCfg`.
  - New package `src/l4/delegate/` with `__init__.py` and `settings.py` (`delegate_settings`).
  - Run also `tests/unit/config/` and `tests/unit/agents/test_factory*.py`.

## 2. The real actor of every answer (L4-QMD-009, L4-CLR-006, L4-DLG-010; D11; the 0.4.16 bug)

- [ ] 2.1 One function decides who answered.
  - Tests first, `tests/unit/clarifier/test_answer_actor.py` (a unit repository with real commits made by
    `questions_cli.make_commit` and `commit_message`):
    - `test_clarifier_status_is_the_clarifier`.
    - `test_an_agent_commit_is_the_agent_for_every_kind` (parametrized over `technical`, `product`, `ambiguous`,
      `verdict`, `harness`): the commit of `answer Q-003` with `By: … (agent: CLAUDECODE)` gives `Actor("agent",
      marker="CLAUDECODE")`.
    - `test_a_person_commit_is_the_person`.
    - `test_a_hand_edit_after_the_agent_is_the_person` (SCN-DLG-42): a later plain commit changes Q-003's answer.
    - `test_another_question_commit_does_not_decide` (SCN-DLG-41): an agent's commit for Q-003, then a person's for
      Q-004 that also touched the file; Q-003 is the agent's, Q-004 the person's.
    - `test_the_delegate_needs_its_ledger_record` (SCN-DLG-43): a `By: delegate (…)` commit with no ledger record is
      `agent`; with `question.answered{id, by: delegate, profile, model, answer_sha256}` of the current digest it is
      `Actor("delegate", profile=…, model=…)`.
    - `test_history_is_bounded`: an `l4 questions` commit 201 commits back is not read (the actor is `human`).
  - New `src/l4/clarifier/actor.py`: `Actor(by, marker=None, profile=None, model=None)` and
    `answer_actor(git, unit_dir, question, events) -> Actor` (design D11 steps 1-4; at most 200 commits;
    `git show <sha>:<path>` parsed with `QuestionsFile.parse` to compare the digest). Remove `_written_by_agent` from
    `clarifier.py`.
- [ ] 2.2 Every writer of an actor uses it.
  - Tests first:
    - `tests/unit/clarifier/test_reenter.py`: `test_reenter_records_the_agent_for_a_technical_answer` and
      `test_reenter_records_the_marker`; the existing harness-only case keeps passing.
    - `tests/unit/verifier/test_verdict_actor.py`: `test_consume_verdicts_records_the_agent` (SCN-DLG-40:
      `human.verdict{by: agent, marker: CLAUDECODE}`), `test_consume_verdicts_records_the_delegate` (`by: delegate,
      profile, model`), `test_a_verdict_without_by_folds_as_human` (old ledgers).
    - `tests/unit/s1/test_labels_actor.py`: `test_only_a_persons_verdicts_become_labels` (SCN-DLG-31; an event with no
      `by` counts as a person's).
    - `tests/unit/clarifier/test_inject.py`: `test_answer_blocks_name_agent_and_delegate` (SCN-DLG-46).
  - `src/l4/clarifier/clarifier.py`: `Answered.by` is `Literal["human", "agent", "clarifier", "delegate"]`; `reenter`
    calls `answer_actor` for every answered question and records `marker` (agent) or `profile`, `model` (delegate).
  - `src/l4/verifier/verdicts.py`: `consume_verdicts(..., actor_of: Callable[[Question], Actor] | None = None)`
    records `by` (and `marker`, `profile`, `model`) from `actor_of` (default: a person, for the old callers); the
    ladder passes `answer_actor` bound to the unit. `src/l4/state/fold.py` `_human_verdict` keeps `by`.
  - `src/l4/s1/labels.py`: `labels_from_verdicts` skips a verdict whose `by` is set and is not `human`.
  - `src/l4/clarifier/inject.py`: the `by` attribute is the recorded actor.
  - Run also `tests/unit/clarifier/`, `tests/unit/verifier/test_verdicts*.py`, `tests/unit/s1/`.

## 3. The asker and the independence rule (L4-DLG-002; D3)

- [ ] 3.1 `question.raised` names who asked.
  - Tests first:
    - `tests/unit/implementer/test_question_asker.py`: `test_a_blocked_step_records_its_profile_and_model` (the
      event of `loop.py` has `profile` = the step's profile name and `model` = the served model, else the profile's
      `model`); `test_a_harness_question_records_its_profile_and_model`.
    - `tests/unit/verifier/test_verdict_question_judges.py`: `test_a_verdict_question_records_the_judges` (`judges:
      [{profile, model}]` of the round's judge replies, the panel's too).
  - `src/l4/implementer/loop.py` (both `question.raised` emits) and the verdict question writer of
    `src/l4/verifier/verdicts.py`.
- [ ] 3.2 The constraint for the factory.
  - Tests first, `tests/unit/delegate/test_independence.py`:
    - `test_model_mode_vetoes_the_name_and_the_model` (SCN-DLG-06: `delegate-opus` vetoed with `independence: model
      claude-opus-5-5 judged the question`, `delegate-sol` passes).
    - `test_profile_mode_vetoes_the_name_only`.
    - `test_another_adapter_does_not_serve_the_role` (SCN-DLG-08a: an `opencode` profile is skipped).
    - `test_an_old_raise_counts_every_implementer` (SCN-DLG-08) and, for a verdict, every judge profile of the unit's
      `verify.verdict` events.
    - `test_an_intake_question_has_no_asker` (SCN-DLG-08b: `source: intake_lint` and `intake_open_questions` veto no
      profile).
    - `test_no_profile_left_is_an_escalation` (SCN-DLG-07): `Factory.for_role("delegate", unit, constraints=[c])`
      raises `RoleUnavailable` whose reasons are all constraint vetoes; `independence_escalation(exc)` gives
      `no independent delegate`.
  - New `src/l4/delegate/independence.py`: `askers(events, question) -> tuple[Asker, ...]`,
    `delegate_constraint(askers, mode) -> Constraint` (the `Constraint` of `availability/fallback.py`).

## 4. The shared edit core and the field lines (L4-DLG-006, L4-QMD-001, L4-QMD-003; D4, D8)

- [ ] 4.1 `Answered by:` and `Escalated by:` are fields of a question.
  - Tests first, `tests/unit/specs/test_questions_delegate_fields.py`:
    - `test_the_two_lines_are_fields`: `_FIELD` matches `- **Answered by:** …` and `- **Escalated by:** …`;
      `Question.answered_by` and `Question.escalated_by` hold their text.
    - `test_set_field_inserts_after_status`: `QuestionsFile.set_field(qid, "Answered by", value)` puts the line after
      the Status line, replaces an existing one, and keeps every other byte, CRLF line endings and a BOM;
      `round_trip` of an edit plus the line passes.
    - `test_an_answer_with_the_line_is_structure` (SCN-DLG-39): `check_text("- **Answered by:** the delegate (x via
      y)")` refuses with `line 1 would be read as structure of the file`.
  - `src/l4/specs/questions.py`: `_FIELD` gains the two names; `set_field`; the two `Question` attributes.
- [ ] 4.2 The edit core works on the run's worktree.
  - Tests first, `tests/unit/specs/test_questions_edit_core.py`:
    - `test_a_folder_from_the_worktree`: `folder_from_worktree(git, worktree, unit, unit_rel, ledger_rel, branch,
      phase, fix)` reads `questions.md` of `HEAD` with `read_questions_at` and sets `head` to `HEAD`'s sha.
    - `test_the_delegate_edit_equals_the_cli_edit`: for one file, question and text, `build_edit` on that folder
      gives the bytes `l4 questions answer --no-push` shows.
    - `test_commit_message_names_the_delegate`: `commit_message(edit, name, "delegate", None, mark=DelegateMark(model,
      cli, profile))` holds `By: delegate (claude-opus-5-5 via claude-code; profile delegate-opus)`, `Via: l4
      delegate` and `[skip ci]`; the person and agent forms are byte for byte unchanged.
    - `test_a_draft_refuses_the_delegate` (SCN-DLG-38).
  - `src/l4/specs/questions_cli.py`: `folder_from_worktree`, `DelegateMark`, the `mark` argument of
    `commit_message`. The CLI's behaviour does not change: run also `tests/unit/specs/test_questions_cli.py`,
    `test_questions_agents.py` and `test_questions_harness.py`.

## 5. The read-only agent mode (L4-DLG-004; D5)

- [ ] 5.1 The argv of both adapters in `read_only` mode, pinned.
  - Tests first, `tests/unit/agents/test_read_only_mode.py`:
    - `test_claude_read_only_argv` (SCN-DLG-13): `-p --output-format stream-json --verbose --model
      claude-opus-5-5`, `--permission-mode plan`, `--safe-mode`, `--strict-mcp-config`, `--tools Read,Grep,Glob`,
      `--allowedTools Read,Grep,Glob`, `--json-schema`, `--max-turns`, `--max-budget-usd` when set; no `Edit`,
      `Write`, `Bash`, `--mcp-config` or `dontAsk`; `--bare` instead of `--safe-mode` for `auth: api_key`.
    - `test_codex_read_only_argv`: `exec --json -m gpt-6.1-sol -c model_reasoning_effort=high -s read-only
      --ignore-user-config --ignore-rules -c project_doc_max_bytes=0 --ephemeral --output-schema … -o
      <result dir>/result.json -`; no `--skip-git-repo-check` and no `mcp_servers.` override.
    - `test_read_only_runs_in_the_worktree`: both adapters start in `req.cwd`, not in `judge_workdir`.
    - `test_claude_read_only_reads_the_structured_result`: a stream-json `result` event with `structured_output`
      (from `tests/fixtures/recorded/`) parses to `RunResult.structured`.
  - `src/l4/agents/codex.py`: `--ephemeral` for `read_only` too (a delegate leaves no session). `claude_code.py` only
    if a test fails.
- [ ] 5.2 The sandbox mounts the worktree read-only for the delegate.
  - Tests first, `tests/unit/sandbox/test_bwrap_read_only_worktree.py`:
    - `test_ro_bind_when_the_spec_asks`: `SandboxSpec(..., worktree_read_only=True)` gives `--ro-bind <wt> <wt>`, the
      private directory still `--bind`, and the guidance masks after every bind.
    - `test_the_default_stays_writable`.
    - `test_a_write_fails_and_the_result_is_written` (SCN-DLG-14; marked to run only where bwrap works, as the other
      live sandbox tests).
  - `src/l4/sandbox/base.py` (`worktree_read_only: bool = False`), `bwrap.py`; `none.py` logs one warning that the
    worktree is writable without a sandbox (only where `sandbox.allow_none` lets it run at all).

## 6. The prompt and the result (L4-DLG-004, L4-DLG-005, L4-DLG-014; D5, D7, D15)

- [ ] 6.1 Schema `l4/delegate-result@1` and prompt `delegate@1`.
  - Tests first, `tests/unit/delegate/test_prompt.py`:
    - `test_the_schema_is_strict`: no extra properties; `decision` in the five words; `checked` items `{ref, quote,
      claim}`; `reason` required.
    - `test_material_by_kind`: a verdict question brings the target's text, the judge's reason from `verdict.json` and
      the target's section of `verification.md`; a harness question `check.inconclusive{reason, runs, kept}`, the
      gate `excerpt` and the held tests; every kind the unit's documents and answered questions.
    - `test_data_blocks_name_their_source` (SCN-DLG-15); `test_material_by_kind` covers SCN-DLG-15a.
    - `test_redaction_comes_before_the_cut`: a `glpat-` token that straddles a budget cut is redacted whole.
    - `test_the_version_and_the_digest`: `PROMPT_VERSION == 1`, `prompt.sha256` is the document's sha256.
  - New `src/l4/delegate/prompt.py` (system text, `build_prompt(question, material, budget, redact)`) and
    `src/l4/delegate/delegate-result.schema.json`; reuse `collect_sources` and `ContextBuilder` of the clarifier. Add
    the system text to `templatelock.current()` and regenerate the lock (`.venv/bin/python -m l4.templatelock
    --write`); run `tests/unit/test_template_lock.py`.
- [ ] 6.2 The reply checks.
  - Tests first, `tests/unit/delegate/test_reply.py`:
    - `test_the_decision_fits_the_kind` (parametrized table of D7; SCN-DLG-17).
    - `test_accept_needs_a_clarifier_suggestion`.
    - `test_checked_entries_resolve` (SCN-DLG-16): a `path:line` with the quote within three lines passes, four lines
      off fails, a symlink fails, a missing file fails; a `test:` id of the latest report passes, an unknown one fails;
      a `spec:` file of the unit folder holding the quote passes.
    - `test_escalate_needs_no_checked_entry`.
    - `test_a_reject_of_a_hold_needs_when_then` (SCN-DLG-18; scope and coverage holds exempt).
    - `test_a_frozen_path_discards` (SCN-DLG-19).
    - `test_unfreeze_false_escalates_an_unfreezing_answer` (SCN-DLG-54: an `accept` whose suggestion names a frozen
      `tests/conftest.py`, and an `answer` whose text names it, both escalate with the path and
      `delegate.unfreeze is false`) and `test_unfreeze_true_takes_the_suggestion_only` (SCN-DLG-55: the `accept` is
      kept under `suggestion_effects`' rules, an ignore file or a path the question does not name still escalates,
      and a free-text `answer` naming the file still escalates).
    - `tests/unit/implementer/test_unfreeze_delegate.py`: `test_a_delegate_accept_unfreezes_with_its_label` (the next
      green step may change the file; `task.unfrozen{reason: delegate_answer, question, answer_sha256, by: delegate,
      profile, model}`; `l4 status --unit` shows `delegate_override`).
    - `test_the_composed_answers` (`accept <text>`, `reject <text>`, `accept: <text>`, `retry: <text>`).
    - `test_the_text_checks_are_check_text`.
  - New `src/l4/delegate/reply.py`: `check_reply(reply, question, head_tree, report, frozen, hold_kind, unfreeze) ->
    Kept | Discarded` (L4-DLG-014, design D15); `src/l4/implementer/unfreeze.py` records `reason: delegate_answer`
    for an accepted question the ledger says the delegate answered.

## 7. Limits and cost (L4-DLG-009; D10)

- [ ] 7.1 Pure limit checks over the ledger and the plan.
  - Tests first, `tests/unit/delegate/test_limits.py`:
    - `test_attempts_per_question` (calls and deferrals of the current raise; a deferral with `reason: soft_deadline`
      is no attempt, SCN-DLG-105).
    - `test_answers_per_task_and_per_target` (SCN-DLG-27; fix units count for the parent's task; a verdict counts
      per target).
    - `test_the_unit_cap` (SCN-DLG-29), `test_the_plan_share` (SCN-DLG-28, with an extension of the cost limit),
      `test_no_share_without_a_plan_cost_limit`.
    - `test_an_unknown_cost_counts_at_the_cap`.
    - `test_the_delegate_cost_is_unit_cost` (SCN-DLG-29a: `budget.cost{role: delegate}` reaches `plan.charged`).
    - `test_what_is_left_must_cover_one_answer`.
  - New `src/l4/delegate/limits.py`: `limit_reached(question, events, plan_state, cfg) -> str | None` (the reason
    text of the escalation).

## 8. The delegate pass (L4-DLG-003, L4-DLG-005, L4-DLG-006, L4-DLG-008, L4-DLG-013; D6, D8, D9)

- [ ] 8.1 One pass per unit, one call per question.
  - Tests first, `tests/unit/delegate/test_pass.py` (the `fake` adapter scripted per question):
    - `test_one_call_per_question_oldest_first_capped` (`max_questions_per_run`; SCN-DLG-12a).
    - `test_each_question_has_its_own_constraint` (two questions with different askers get different profiles).
    - `test_a_kept_answer_is_written_committed_and_recorded` (SCN-DLG-20, SCN-DLG-21): the file's diff, the commit
      subject and body, `delegate.asked`, `budget.cost{role: delegate}`, `delegate.result{status: answered}`,
      `question.answered{by: delegate}`.
    - `test_an_escalation_writes_its_line` (SCN-DLG-25): `Escalated by:` line, `delegate.result{status: escalated}`,
      Status still `open`.
    - `test_a_discarded_reply_escalates`; `test_an_edit_refusal_escalates` (a draft).
    - `test_cooling_defers` (SCN-DLG-35), `test_a_fix_only_cause_escalates` (SCN-DLG-36),
      `test_an_empty_chain_escalates` (SCN-DLG-37).
    - `test_a_timeout_defers_then_escalates_at_the_limit` (SCN-DLG-36a).
    - `test_no_time_left_defers_and_asks_for_a_run` (SCN-DLG-12).
    - `test_no_consent_for_agents_is_needed` (SCN-DLG-22).
    - `test_a_decided_question_is_not_asked_again` (SCN-DLG-11).
    - `test_the_worktree_is_detached_read_only_and_removed`: the request's `cwd` is a `git worktree add --detach` of
      the pushed head, its sandbox spec has `worktree_read_only=True`, and the worktree is gone after the pass.
  - New `src/l4/delegate/run.py`: `delegate_hook(ctx: HookContext) -> DelegateOutcome(answered, escalated, deferred,
    start_run)`; it selects with `delegate_constraint`, builds the workbench as `clarify_hook` does (with a
    `PermissionPolicy("read_only")` request factory), and commits with `commit_questions`' shape and the message of
    task 4.2. `src/l4/services.py`: `HOOKS["delegate"]`, `Hooks.delegate`.

## 9. Wiring: the parking run and the action `delegate` (L4-DLG-001, L4-DLG-003, L4-CLR-002; D1, D6)

- [ ] 9.1 Scope.
  - Tests first, `tests/unit/delegate/test_scope.py`: `test_scope_yolo` (the current unit of an active or waiting
    plan, and its fix unit; SCN-DLG-03), `test_scope_all` (SCN-DLG-04), `test_an_active_plan_keeps_other_units_out`
    (SCN-DLG-05), `test_held_stopped_cancelled_and_finished_are_out`.
  - New `src/l4/delegate/scope.py`: `in_scope(unit, plans, cfg) -> bool`, from the plan files and ledgers the run read.
- [ ] 9.2 The parking run calls the pass.
  - Tests first, `tests/unit/orchestrator/test_delegate_hook.py`: `test_the_parking_run_calls_the_pass_after_the_clarifier`
    (SCN-DLG-09, SCN-DLG-44), `test_off_by_default` (SCN-DLG-01), `test_a_fix_units_questions_are_taken`,
    `test_the_exit_stays_11`.
  - `src/l4/orchestrator.py`: after the phase is `awaiting_human` (and in `fixing` with a waiting fix unit), before
    `close`, call `hooks.delegate` when the unit is in scope.
- [ ] 9.3 The planner action `delegate`.
  - Tests first:
    - `tests/unit/planner/test_delegate_action.py`: `test_an_undecided_question_is_the_delegate_action` (SCN-DLG-10),
      `test_no_action_after_a_final_record` (SCN-DLG-11), `test_no_action_before_retry_after`,
      `test_no_action_out_of_scope`.
    - `tests/unit/yolo/test_yolo_delegate_dispatch.py`: `test_the_plan_dispatches_the_delegate_action` (a waiting plan
      records `plan.resumed{by: harness}` and dispatches), `test_still_waits_is_false_while_the_action_is_due`.
  - `src/l4/planner.py` (`UnitFacts.delegate_due`, `next_action` returns `("delegate", "delegate: Q-003 to ask")`),
    `orchestrator.ACTIONABLE` and `yolo/cycle._ACTIONABLE` gain `delegate`; an `awaiting_human` unit run for this
    action does the reentry and the pass only, and exits 11.

## 10. The next run (L4-DLG-007, L4-YOLO-012; D4, D13)

- [ ] 10.1 An answer starts one run on the base.
  - Tests first:
    - `tests/unit/orchestrator/test_delegate_next_run.py`: `test_an_answer_outside_a_plan_starts_one_run` (the
      forge's `start_run(base)` called once for two answered units), `test_a_refused_start_is_a_log_line`,
      `test_no_answer_starts_nothing`.
    - `tests/unit/yolo/test_yolo_delegate_chain.py`: `test_an_answer_chains_once_while_the_plan_waited`
      (SCN-DLG-49), `test_the_next_step_resumes_and_dispatches` (SCN-DLG-23), `test_an_escalation_waits_without_a_run`.
  - `src/l4/orchestrator.py`: `UnitRunResult` and `CommandResult` gain `delegate_answered`; `run_command` starts the
    run (the plan's `_start_next_run`, or the forge's `start_run` outside a plan) once when it is not empty.

## 11. Idle runs (L4-YOLO-014, L4-YOLO-012; D12)

- [ ] 11.1 An idle run is recorded, not counted, and chains nothing.
  - Tests first, `tests/unit/yolo/test_yolo_idle_runs.py`:
    - `test_an_idle_run_is_recorded_and_not_counted` (SCN-DLG-48, SCN-DLG-50).
    - `test_a_run_that_worked_is_charged` (SCN-DLG-51).
    - `test_not_started_and_capacity_parks_stay_charged` (SCN-DLG-52).
    - `test_a_waiting_step_charges_nothing` (SCN-DLG-53).
    - `test_the_fold_subtracts_per_attempt_never_below_zero` and `test_one_record_per_run`.
    - `test_the_status_shows_idle_runs`.
  - `src/l4/orchestrator.py`: `CommandResult.idle` (units whose run ledger has no `agent.finished`, no
    `gate.finished` and no `phase.changed` but into `awaiting_human` or `clarifying`); `src/l4/yolo/cycle.py`
    `record_idle_runs` (with the lease, like `record_run_starts`) and no chained run after one; `src/l4/yolo/state.py`
    folds `plan.run_idle`; `src/l4/yolo/commands.py` status line.

## 12. Escalation on the forge and in the file (L4-DLG-008, L4-CLR-004)

- [ ] 12.1 Label, sticky note and wait detail.
  - Tests first:
    - `tests/unit/archive/test_needs_person_label.py`: `test_the_label_follows_escalated_questions` (SCN-DLG-45; a person's answer removes it, SCN-DLG-26).
    - `tests/unit/setup/test_github_labels.py`: `test_needs_person_is_in_the_label_set`.
    - `tests/unit/clarifier/test_notify_delegate.py`: `test_needs_a_person_section` and
      `test_answered_by_the_delegate_section`.
    - `tests/unit/yolo/test_yolo_wait_detail.py`: `test_the_wait_detail_names_escalated_questions` (SCN-DLG-25).
  - `src/l4/archive.py` (labels), `src/l4/setup/github.py`, `src/l4/clarifier/notify.py`, `src/l4/planner.py`
    (`awaiting_human` reason `(escalated to a person: Q-004)`).

## 13. Audit labels downstream (L4-DLG-010, L4-VER-051)

- [ ] 13.1 `delegate_override` and the delegate's verdicts are named everywhere.
  - Tests first:
    - `tests/unit/implementer/test_delegate_override.py`: `test_a_delegate_accept_is_delegate_override` (SCN-DLG-30;
      `check.accepted{by: delegate}`, `criterion.pre_satisfied{via: delegate_override}`).
    - `tests/unit/verifier/test_traceability_labels.py`: `test_the_delegate_label` (SCN-DLG-47).
    - `tests/unit/verifier/test_verification_md_actor.py`: `test_a_verdict_by_an_agent_or_the_delegate_is_named`.
    - `tests/unit/yolo/test_yolo_report_delegate.py`: `test_the_report_lists_the_delegate_decisions` (question,
      kind, decision, model, cost; escalations with their reason; SCN-DLG-31a).
  - `src/l4/implementer/tdd.py` (`VIA_DELEGATE_OVERRIDE`, `override_via`), `src/l4/implementer/held.py`,
    `earlier_red.py`, `src/l4/verifier/traceability.py` (`UNPROVEN_VIA`, `_unproven_note`), the `verification.md`
    writer, `src/l4/yolo/report.py`.

## 14. Status lines (L4-DLG-011, L4-YOLO-014)

- [ ] 14.1 `l4 status`, `l4 status --unit`, `l4 yolo status`.
  - Tests first:
    - `tests/unit/state/test_status_delegate.py`: `test_the_table_reason_of_an_escalation`, `test_the_delegate_lines`,
      `test_the_json_fields` (SCN-DLG-32).
    - `tests/unit/yolo/test_yolo_status_delegate.py`: `test_the_delegate_line_and_the_share`,
      `test_the_idle_runs_line`, `test_the_json_fields`.
  - `src/l4/state/status.py`, `src/l4/planner.py`, `src/l4/yolo/commands.py`.

## 15. Doctor (L4-DLG-012)

- [ ] 15.1 `DLG-001` and `DLG-002`.
  - Tests first, `tests/unit/doctor/test_checks_delegate.py`: `test_off_passes_silently` (SCN-DLG-34a), `test_an_empty_chain`,
    `test_an_opencode_profile_is_refused`, `test_an_unknown_profile`, `test_a_delegate_that_is_the_judges_model`
    (SCN-DLG-33), `test_a_usable_chain_passes` (SCN-DLG-34; DLG-002's only finding is the verdict-profiles warning), `test_no_usable_profile_warns_with_the_fix`,
    `test_live_hello_includes_the_delegate_chain` (LIVE-002).
  - New `src/l4/doctor/checks_delegate.py`, registered in the doctor registry.

## 16. Simulation (the lifecycle has no new edge)

- [ ] 16.1 The two delegate loops run in the simulator.
  - Tests first, `tests/unit/sim/test_delegate_sim.py`: `test_an_implementer_question_answered_by_the_delegate`
    (raise, delegate answer, next run `implementing`, PASS), `test_a_verdict_accepted_by_the_delegate_hands_off`
    (NEEDS_HUMAN, delegate `accept`, next round PASS, `in_review`, not merged; SCN-DLG-24),
    `test_no_new_lifecycle_edge` (the edges taken are a subset of SPEC 12.0's table).
  - The scenario files beside the existing simulator fixtures, and a scripted `fake` profile for `roles.delegate`.

## 17. Docs

- [ ] 17.1 SPEC, runbook, guides, skill, CHANGELOG.
  - `docs/SPEC.md`:
    - §3.2: the `delegate:` section with every key, its default and its requirement id; the profiles `delegate-opus`
      (`claude-opus-5-5`) and `delegate-sol` (`gpt-6.1-sol`, `reasoning_effort: high`); `roles.delegate` (optional).
    - §6: L4-QMD-001, L4-QMD-003 and L4-QMD-009 with this change's text; the grammar block shows the `Answered by:`
      line.
    - §8.4: L4-AVL-010. §9: L4-CLR-002, L4-CLR-004, L4-CLR-006; a new §9.1 "Delegate" with L4-DLG-001..014.
    - §10: L4-VER-051. §12.1: `delegate.asked`, `delegate.result`, `by`/`marker`/`profile`/`model` on
      `question.answered` and `human.verdict`, `profile`/`model`/`judges` on `question.raised`, and the plan
      ledger's `plan.run_idle`. §12.5: L4-YOLO-012, L4-YOLO-014.
    - §15: rows `DLG-001`, `DLG-002`; LIVE-002 names the delegate chain.
    - §21: row 63 `delegate-answers`, its outcome in one sentence (requirement ids,
      `openspec/changes/delegate-answers/`), and its live check (task 18).
    - §23: a subsection "Delegate (DLG)" with SCN-DLG-01..55 (and the lettered ones) from this change's spec files in the
      `#### SCN-DLG-NN (+|−) Title · L4-…` form with **Given**/**When**/**Then**; a scenario that names phase
      `awaiting_human` names exit 11.
  - `docs/runbook.md`: §7.1 a procedure "The delegate answered or escalated" (the `Delegate:` lines, the label
    `l4:needs-person`, how to answer an escalated question, how to turn the delegate off); §10.2 the label; §12.4 a
    waiting plan after a delegate answer and after an escalation; §12.6 the delegate pass and idle runs; §11 known limits
    (the read-only mode's [U] parts).
  - `docs/yolo-mode.md`: a section "The delegate" (scope, safety rules, limits, what it never does).
  - `docs/control-loop.md`, when the base has it: §5 the delegate pass at the end of a run and the action `delegate`;
    §6 and §7 where the delegate's commit lands and what starts the next run; the idle-run rule.
  - `plugins/l4/skills/l4/references/operate.md`: the delegate exists, how to read its lines and escalations, and that an
    agent never writes a `By: delegate` line; `plan.md`: enabling the delegate is a configuration change on the base
    that a person approves.
  - `CHANGELOG.md`: `## 0.4.22 (unreleased)` above `## 0.4.21 (2026-10-21)` (the 0.4.17 to 0.4.21 entries arrive by merge),
    with `### Added` (the delegate), `### Changed` (the label, the status lines) and `### Fixed` (the actor of every
    answer, idle runs, calibration labels).
  - Then `python scripts/check_spec.py docs/SPEC.md`, `npx --yes @fission-ai/openspec@1.14.1 validate delegate-answers
    --strict`, and the whole unit suite once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit`.

## 18. Live validation on a dummy repository (never a consumer repository)

- [ ] 18.1 A plan with the delegate on.
  - On a dummy repository, push to the base: `delegate: {enabled: true, scope: yolo}`, `roles.delegate:
    [delegate-opus, delegate-sol]`, and a plan of two units: unit A whose spec leaves a technical question that its
    `design.md` answers, and a product question that nothing in the repository settles; unit B with a criterion the
    judge will dispute (NEEDS_HUMAN).
  - Expect and record under `docs/live/delegate-answers/`: A's technical question answered (`By: delegate`, the
    `Answered by:` line, `question.answered{by: delegate}`), the chained run implementing it; the product question
    escalated with `l4:needs-person` and the plan waiting without runs; B's verdict question answered by the profile
    the independence rule leaves (not the judge's model), the next round's result; the delegate's cost within its caps;
    `l4 yolo status` showing the idle runs (if any) as not counted.
- [ ] 18.2 Scope `all` outside a plan.
  - With no plan active and `scope: all`, a unit outside every plan with an open technical question: the answer, the
    forge's `start_run`, the next run, a PASS hand-off to `in_review`, and no merge.
- [ ] 18.3 Both adapters in read-only mode.
  - Force one question to each profile (one `independence` veto each). From the published agent logs: the argv of
    each, no write to the worktree (a write attempt in the prompt's evidence fails), the result file read.
- [ ] 18.4 Record what was not verified (for example a Codex usage limit in the middle of a delegate call) in the
  evidence file and in §11 of the runbook.

## 0.4.22 amendment (groups 19 to 29)

These groups build the amendment (design "0.4.22 amendment", decisions A1 to A6, B1 to B3, C1 to C4, P1 to P4;
L4-DLG-015 to L4-DLG-027 and the new text of L4-DLG-002, L4-DLG-004, L4-DLG-012 and L4-DLG-014). The rules at the top
of this file apply, on the base that merged 0.4.21 into this change. No test calls a real opencode or kiro-cli: argv
and configuration are built and asserted, and runs are replayed from recorded or synthetic stream lines (synthetic
fixtures say so in their name). The delegate tests take a fake profile of each adapter from
`tests/unit/delegate/conftest.py`.

## 19. The read-only reply of the prompt-contract adapters (L4-DLG-015; A1)

- [x] 19.1 A read-only run replies in its last message, and its prompt says to read first.
  - Result: done. contract.py (last_top_level_object, attach_read_only_reply), agent_judge.py (READ_THEN_REPLY, reading flag, strip_suffix), opencode.py and kiro_cli.py (read_only parse; kiro keeps every tool name in tool_names); tests test_read_only_reply.py, test_agent_judge_read_suffix.py, and test_pass_adapters.py (SCN-DLG-56, 57, 101, 102, 103; the pass tests need DELEGATE_SERVES, set in 20.1). The refused-call-with-no-reply case is an adapter error (a deferral), not a bad reply.
  - Tests first:
    - `tests/unit/agents/test_read_only_reply.py`: `test_opencode_read_only_takes_the_object_after_the_last_tool`
      (SCN-DLG-56: a stream with a `read` tool use, then prose and the object; prose with a `{` before the tool call
      does not break the slice), `test_the_last_top_level_object_wins` (SCN-DLG-100: a `{` in prose after the last tool
      call that does not decode; two objects; a schema example followed by the answer; code fences ignored; an object
      nested in the last one does not count; `raw_decode` scanning, not first-`{`-to-last-`}`),
      `test_a_refused_call_then_a_valid_reply_is_kept` (SCN-DLG-101: an opencode stream with a denial, then `stop`) and
      `test_a_refused_call_with_no_valid_reply_gives_none` (SCN-DLG-102; a denial with no `stop` is
      `permission_blocked`), `test_kiro_read_only_takes_the_object_after_the_last_tool` (`last_message`, else
      `finalText`), `test_no_result_file_is_read_in_read_only` (a file at `result_path` is ignored),
      `test_a_tool_outside_the_read_set_is_no_reply` (SCN-DLG-57: kiro `shell`, opencode `bash` rejected: status
      `error` or `permission_blocked`, `structured` None).
    - `tests/unit/llm/test_agent_judge_read_suffix.py`: `test_a_read_only_request_gets_the_read_then_reply_suffix`
      (no `Do not call any tool`; it says to write nothing after the object), `test_the_published_prompt_and_the_digest_leave_the_suffix_out`,
      `test_a_judge_request_keeps_the_schema_instruction`.
    - `tests/unit/delegate/test_pass.py`: `test_a_tool_outside_the_read_set_defers_then_escalates` (SCN-DLG-57).
  - `src/l4/llm/agent_judge.py` (`READ_THEN_REPLY`; `schema_suffix(schema, reading=False)`; an `AgentJudge(...,
    reading=True)` constructor flag, which the delegate pass sets: `complete_structured` composes the prompt before
    `make_request` builds the request, so it cannot read the request's mode), `src/l4/agents/contract.py` (`attach_judge_reply` on the
    last message, then the whole text; the read-only parse takes the LAST top-level object by `raw_decode` scanning), `src/l4/agents/opencode.py` and `kiro_cli.py` (`read_only` parses like a
    judge, never `read_result_file`), `src/l4/delegate/run.py` (the published prompt strips the suffix it was sent).
  - Run also `tests/unit/agents/test_opencode*.py`, `test_kiro*.py`, `test_contract*.py`, `tests/unit/llm/`.

## 20. The opencode delegate (L4-DLG-016; A2)

- [x] 20.1 Deny by default, read in the worktree, the pinned major.
  - Result: done. opencode.config_content read_only is deny by default (BASH_SENTINEL for Zen, options.tools ignored, .env denials after the read allow), mask_instruction_files (INSTRUCTION_FILES) used by the pass on a separate masked detached worktree for opencode profiles only; DELEGATE_SERVES now holds opencode and kiro-cli (the rest of 22.1 follows). The two old read_only assertions of test_opencode.py changed with the map. SCN-DLG-60 holds through the existing major gate: no new code.
  - Tests first:
    - `tests/unit/agents/test_opencode_delegate.py`: `test_read_only_config_denies_by_default` (SCN-DLG-58: key order
      `"*"` first, then the four read tools; `edit`, `bash`, `webfetch`, `websearch`, `task`, `question` resolve to deny
      under last-match-wins; `external_directory` allows only the private directory), `test_a_zen_model_keeps_bash_refused`
      (SCN-DLG-59: `tools.bash` true, `permission.bash` `ask`), `test_the_argv_runs_in_the_worktree` (`--dir` is
      `req.cwd`, not `judge_workdir`), `test_the_implement_and_judge_configs_are_unchanged` (byte for byte),
      `test_options_tools_cannot_re_enable_a_tool` (SCN-DLG-97: a profile with `options.tools: [bash, edit]` gives a
      resolved agent with no `bash`, `edit` or `write`), `test_no_list_tool_in_the_set` (only `read`, `glob`, `grep`),
      `test_env_files_stay_unreadable` (SCN-DLG-99: the `read` rule keeps the `*.env` and `*.env.*` denials after its
      allow), `test_the_zen_bash_permission_is_deny_with_a_sentinel_ask` (SCN-DLG-59: `{"*": "deny", "<sentinel>":
      "ask"}`; a bash call is refused and the run goes on).
    - `tests/unit/delegate/test_worktree_mask.py`: `test_nested_instruction_files_are_removed_from_the_checkout`
      (SCN-DLG-98: `AGENTS.md`, `CONTEXT.md`, `CLAUDE.md` and the other names the adapter knows, at any depth below
      the root; the git tree (`HeadTree`) still holds them and a claim that resolves against it still resolves;
      the worktrees of the other adapters are untouched).
    - `tests/unit/delegate/test_pass_adapters.py`: `test_opencode_v2_escalates_and_does_not_defer` (SCN-DLG-60: a
      probe `unsupported_version` makes `RoleUnavailable` with no `retry_after`; `delegate.result{status: escalated}`).
  - `src/l4/agents/opencode.py` (`config_content` for `read_only`: no `list`, `options.tools` ignored, a `read` map with
    the `.env` denials, the Zen sentinel); `src/l4/delegate/run.py` (the mask, where the pass makes the detached
    worktree; the v2 test if it fails).

## 21. The kiro-cli delegate (L4-DLG-017; A3)

- [x] 21.1 A harness read agent, stdin, the served model.
  - Result: done. kiro_cli.py: DELEGATE_PREFIX, DELEGATE_TOOLS, delegate_agent_config, write_delegate_home, delegate_argv, the read_only branch of build_command, run and the tool check (stream_facts keeps tool_names: every tool of the run, from tool_call events and from updates that carry _meta.kiro.toolName); TRUST_TOOLS lost read_only; run.py escalates a model_mismatch as status discarded naming both ids. The old kiro read_only trust-list tests of test_kiro_cli.py changed with the mode; the credits and served model of the pass are in 23.1.
  - Tests first, `tests/unit/agents/test_kiro_delegate.py`:
    - `test_the_delegate_runs_its_own_read_only_agent` (SCN-DLG-61: argv, the agent file, `settings/cli.json`, cwd the
      worktree, no `--trust-tools=`, no `--require-mcp-startup`, no prompt argument, `KIRO_LOG_LEVEL` removed).
    - `test_a_prompt_over_the_argument_cap_goes_on_stdin` (200,000 bytes).
    - `test_another_engine_a_run_error_or_a_write_tool_is_no_reply` (parametrized: `runStarted{engine: v3}`, a
      `runError`, a `tool_call` of `write` or `shell`; a `tool_call` of `read`, `glob`, `grep` is fine).
    - `test_the_served_model_comes_from_the_session_file` (`model_resolved`) and `test_a_model_mismatch_escalates`
      (SCN-DLG-63, with `tests/unit/delegate/test_pass_adapters.py`: `delegate.result{status: discarded}` naming both
      ids, no deferral).
    - `test_credits_are_usage_credits` (the stream's `meteringUsage`, `cost_usd` None).
    - `test_a_turn_keeps_every_tool_name` and `test_a_call_to_a_tool_the_agent_lacks_voids_the_run` (SCN-DLG-103:
      `kiro_cli.py` kept only the first `tool_name` of a turn; a `read` then an unknown tool gives both names, no
      reply, a deferral).
  - `src/l4/agents/kiro_cli.py`: `DELEGATE_PREFIX = "l4-delegate-"`, `DELEGATE_TOOLS = ("read", "glob", "grep")`,
    `delegate_agent_config`, `write_delegate_home`, the `read_only` branch of `build_command` and `run`, the tool check
    of the read-only parse; `TRUST_TOOLS` loses `read_only`; the module docstring's "Open: a harness agent for the
    read-only mode" goes. `src/l4/delegate/run.py`: a `model_mismatch` detail is an escalation.

## 22. Who serves, one model identity, the kinds of a profile (L4-DLG-015, L4-DLG-018, L4-DLG-019, L4-DLG-002; A1, A4, A5)

- [x] 22.1 Four adapters serve, models compare after their prefix, `auto` vetoes.
  - Result: done. independence.py: DELEGATE_SERVES (set in 20.1), model_key and same_mind (after the last /, [..], @.., :.., (region.)anthropic., -v<n>(:<n>), date, dots; auto and none are None and veto under model), the constraint and _served_veto use them; l4.availability.vendor.same_model is unchanged. test_another_adapter_does_not_serve_the_role and the second half of test_an_unusable_chain_is_not_an_independence_escalation (it used an opencode profile as the unserved adapter) now use a command profile.
  - Tests first, `tests/unit/delegate/test_independence.py`:
    - change `test_another_adapter_does_not_serve_the_role` (SCN-DLG-08a): a `command` profile is skipped; an
      `opencode` and a `kiro-cli` profile are selected.
    - `test_a_provider_prefix_does_not_hide_the_model` (SCN-DLG-64), `test_a_slug_suffix_is_the_same_model`
      (SCN-DLG-65), `test_a_kiro_dotted_id_is_the_claude_id` (`claude-opus-5.5`), `test_auto_vetoes_under_model`
      (SCN-DLG-62, also `openrouter/auto`), `test_a_tag_a_date_or_a_bedrock_shape_is_the_same_model` (SCN-DLG-95:
      `:thinking`, `@20261001`, `us.anthropic.…-v1:0`, a `-v\d+(:\d+)?` suffix; `opencode-go/deepseek-v4.1-flash` equals
      `openrouter/deepseek/deepseek-v4.1-flash:free`), `test_a_free_tag_does_not_hide_the_model` (SCN-DLG-96, the
      `:free` Opus delegate against an Opus judge), `test_a_kiro_implementer_on_auto_vetoes_every_delegate`
      (SCN-DLG-112), `test_profile_mode_lets_auto_serve`, `test_the_served_model_is_compared_the_same_way`.
  - `src/l4/delegate/independence.py`: `DELEGATE_SERVES = ("claude-code", "codex", "opencode", "kiro-cli", "fake")`,
    `model_key(model) -> str | None` (after the last `/`, then `[…]`, `@…`, `:…`, the `(<region>.)?anthropic.` prefix
    (reusing the pattern shape of `MODEL_FAMILIES`, `l4/availability/vendor.py`) and `-v\d+(:\d+)?`, then
    `normalise_model`; None for `auto` or nothing; an asker on `auto` gives None, which vetoes),
    `same_mind(a, b)` (equal, or one is the other followed by `-`), used by `delegate_constraint` and `_served_veto`.
    `l4.availability.vendor.same_model` is not changed (the verifier keeps its rule).
- [x] 22.2 The kinds a profile may answer.
  - Result: done. New l4/delegate/kinds.py (is_free_tier, allowed_kinds, unknown_kinds, join_kinds, kinds_constraint(kind, cfg): cfg is a second argument because delegate.kinds is read from it). The factory step of the veto stays constraint; the kinds veto is told apart by its reason prefix kinds:, for which RoleUnavailable now carries reasons beside steps; independence_escalation(exc, kind) says no independent delegate or no delegate profile answers <kind> questions. A profile whose options.delegate_kinds holds an unknown entry is skipped by the pass (the entry grants nothing).
  - Tests first, `tests/unit/delegate/test_profile_kinds.py`: `test_a_free_model_never_answers_a_verdict`
    (SCN-DLG-66), `test_a_free_model_answers_a_technical_question` (SCN-DLG-67), `test_options_narrow_and_never_widen_a_free_model`,
    `test_an_unknown_kind_in_options_is_ignored_and_reported` (the pass skips the profile; DLG-001 names it),
    `test_no_profile_for_a_kind_escalates_with_its_reason` (`no delegate profile answers verdict questions`; a chain
    skipped for kinds and for independence together says `no independent delegate`).
  - New `src/l4/delegate/kinds.py`: `is_free_tier(model)`, `allowed_kinds(profile, cfg) -> frozenset[str]`,
    `kinds_constraint(kind) -> Constraint` (reason `kinds: <p> answers <kinds> questions`);
    `select_delegate` passes both constraints; `independence_escalation` tells the two vetoes apart by their reason.

## 23. Cost of every adapter (L4-DLG-020; A6)

- [x] 23.1 Known, zero, unknown, credits.
  - Result: done. run.py records budget.cost{credits, credits_source, profile, role, question} (never usd) for a call with credits, delegate.result carries credits and, for a call with no dollar cost, counted_usd (the cap it counts at); lines.py reads them (1.84 credits; counted at $3.00) and the status json carries credits and counted_usd; a reported 0 stays a known cost. limits.py needed no change.
  - Tests first:
    - `tests/unit/delegate/test_cost_adapters.py`: `test_a_zero_cost_is_known` (SCN-DLG-69),
      `test_kiro_credits_are_recorded_and_counted_at_the_cap` (SCN-DLG-70: `budget.cost{credits, credits_source,
      role: delegate, question}`, no `usd`; `delegate.result{credits}`; `delegate_cost` counts the call at the cap),
      `test_an_opencode_run_with_no_cost_counts_at_the_cap`.
    - `tests/unit/state/test_status_delegate.py`: `test_the_line_of_a_kiro_answer_names_its_credits`.
  - `src/l4/delegate/run.py` (`_record_cost` writes credits as `AgentJudge._record_cost` does; `_Reply.credits`),
    `src/l4/delegate/lines.py`, `src/l4/delegate/limits.py` only if a test fails.

## 24. Doctor (L4-DLG-012 new text, L4-DLG-019, L4-DLG-022; A5, B2)

- [x] 24.1 DLG-001 and DLG-002 for four adapters.
  - Result: done, with the 26.2 doctor off line (DLG-001: the delegate is off (delegate.enabled is false; docs/runbook.md 7.1 tells how to turn it on); DLG-002 keeps the short line). DLG-001: four serving adapters, routed (auto) profiles and askers fail under model, delegate.kinds with no profile that may answer, options.delegate_kinds unknown or wide for a free-tier model, the family-neighbour pair named. DLG-002 returns a warn-weight finding naming every profile that would answer verdict questions (opencode flagged); this changes the status assertion of four existing DLG-002 tests (test_a_usable_chain_passes, test_a_model_alias_is_warned_about, test_the_availability_check_spends_no_hello, test_the_second_profile_is_enough) because SCN-DLG-34 now has that finding; they use a usable() helper.
  - Tests first, `tests/unit/doctor/test_checks_delegate.py`:
    - replace `test_an_opencode_profile_is_refused` with `test_a_command_profile_is_refused` (`profile x is a command
      profile; only claude-code, codex, opencode and kiro-cli profiles serve the delegate`) and
      `test_opencode_and_kiro_profiles_serve`.
    - `test_a_kiro_auto_delegate_fails_under_model` (SCN-DLG-62), `test_a_kind_no_profile_may_answer_fails`
      (SCN-DLG-68), `test_a_free_model_whose_options_name_verdict_fails`, `test_a_prefix_or_suffix_pair_is_named` (the
      A4 neighbours, so a false veto shows at configuration time).
    - `test_off_passes_silently` keeps passing; `test_the_off_line_names_the_runbook` (SCN-DLG-76).
    - `test_dlg_002_names_the_profiles_that_answer_verdicts` (SCN-DLG-104: the warning names each profile of the chain
      that `delegate.kinds` and `options.delegate_kinds` leave `verdict` to, and flags an `opencode` profile such as
      `opencode-go/…` or a local custom provider among them; a free-tier profile is not named).
  - `src/l4/doctor/checks_delegate.py` (`ADAPTERS_THAT_SERVE`, `OFF`, the kinds and routed checks, the fix text).

## 25. The rules of 0.4.21 (L4-DLG-023 to L4-DLG-026, L4-DLG-014 new text; C1 to C4)

- [x] 25.1 Prompt `delegate@3`.
  - Result: done. SYSTEM is delegate@3 (read tools named for any CLI; the reject sentence states the behaviour the fix must give, last, never the judge's suggested fix; cap-only, split, judge-view and fix-task rules); PROMPT_VERSION 3; src/l4/templates.lock.json regenerated (only the delegate entry changed). The only pins of delegate@2 were in the prompt module, test_prompt.py and the CHANGELOG history (left to the orchestrator).
  - Tests first, `tests/unit/delegate/test_prompt.py`: `test_the_version_and_the_digest` (`PROMPT_VERSION == 3`),
    `test_the_system_text_asks_for_the_behaviour_the_fix_must_give` (SCN-DLG-80),
    `test_the_read_tools_are_named_for_any_cli` (no `Read`, `Grep` and `Glob` as the only names),
    `test_the_rules_of_a_chore_a_cap_only_criterion_and_the_judge_view_are_stated`.
  - `src/l4/delegate/prompt.py` (`SYSTEM`, `PROMPT_VERSION = 3`); regenerate the lock (`.venv/bin/python -m
    l4.templatelock --write`) and run `tests/unit/test_template_lock.py`.
- [x] 25.2 The reply checks of 0.4.21's questions.
  - Result: done. reply.py: check_reply takes chore, fix_task, cap_only, cap_only_file, judge_view_files, test_globs, support_globs (defaults are the config defaults); a reject of a finding that cites no criterion needs its WHEN ... THEN ... (questions_cli.cites_criterion and is_finding_question, shared with bare_gap_reject), a judge-view reject is discarded, a judge-view accept cites a file the hold names, a cap-only accept cites the lines of the candidate file, a chore answer naming a test or support path escalates, unfreeze: true never opens a support file nor anything in a fix task (test_reply.py::test_unfreeze_true_takes_the_suggestion_only now freezes tests/test_store.py). run.py hands them from verdict.json and the raise; a cap-only question with no file and a judge-view hold with no file escalate without a call (_without_a_call). The report carries no file field in this code base: cap_only_file takes the path before :: of the candidate id (review: the dead `file`-field branch is gone).
  - Tests first, `tests/unit/delegate/test_reply_0421.py`:
    - `test_a_reject_of_a_finding_with_no_criterion_needs_its_scenario` (SCN-DLG-77),
      `test_the_last_scenario_counts` (SCN-DLG-78, with the fix unit's parser `verdicts.WHEN_THEN`),
      `test_a_spec_gap_reject_with_a_reason_is_kept_when_it_cites_a_criterion` (SCN-DLG-79).
    - `test_a_cap_only_accept_cites_the_tests_lines` (SCN-DLG-81, SCN-DLG-82), `test_the_cap_only_file_comes_from_the_report`
      (SCN-DLG-108: the path before `::` of the candidate id, tested in test_prompt.py) and `test_a_cap_only_question_with_no_report_file_escalates`
      (SCN-DLG-109).
    - `test_a_judge_view_reject_is_discarded` (SCN-DLG-84), `test_a_judge_view_accept_cites_a_file_the_hold_names`,
      `test_a_judge_view_hold_that_names_no_file_escalates_without_a_call` (SCN-DLG-107: `LEGACY_LENGTH_HOLD`).
    - `test_a_chore_answer_naming_a_test_or_support_path_escalates` (SCN-DLG-86) and
      `test_a_chore_answer_about_production_code_is_kept` (SCN-DLG-87).
    - `test_unfreeze_true_never_opens_a_support_file` (SCN-DLG-88), `test_unfreeze_true_opens_nothing_in_a_fix_task` (SCN-DLG-106),
      `test_a_chore_answer_names_a_path_by_names_path` (SCN-DLG-110: "the conftest" alone names none; the rule is
      `names_path` of L4-IMP-015).
    - change `tests/unit/delegate/test_reply.py::test_unfreeze_true_takes_the_suggestion_only` (SCN-DLG-55 now freezes
      and unfreezes `tests/test_store.py`).
  - `src/l4/delegate/reply.py` (`target_kind`: criterion, finding with or without a criterion, hold kind; `cap_only_test`;
    `judge_view_files`; `chore`; the support globs); one function `cites_criterion(question)` shared with
    `questions_cli.bare_gap_reject`; `src/l4/delegate/run.py` passes them from `verdict.json` and the raise.
- [x] 25.3 The material of a split and a cap-only criterion.
  - Result: done with 25.1: prompt.py verdict_material reads judge_split and the criterion's reason; VerdictMaterial gains cap_only, candidate, candidate_file and files; cap_only_file(verdict, candidate) takes the path before :: of the candidate id (the report in this code base carries no file field; review dropped the dead branch).
  - Tests first, `tests/unit/delegate/test_prompt.py`: `test_a_split_criterion_names_the_files_not_shown`
    (SCN-DLG-83), `test_a_cap_only_question_brings_its_reason_and_candidate`.
  - `src/l4/delegate/prompt.py` (`verdict_material` reads `judge_split` and the criterion's reason).
- [x] 25.4 A chore's question is marked.
  - Result: done. loop.py _raise_blocked emits chore=True for a blocked fix chore's technical question; run.py is_chore reads it, or for an older raise the fix-task note of a fix unit's technical question.
  - Tests first: `tests/unit/implementer/test_question_asker.py`: `test_a_chore_question_records_chore_true` (and a
    red or green question records no `chore`); `tests/unit/delegate/test_pass.py`:
    `test_an_old_chore_raise_is_found_by_its_note`.
  - `src/l4/implementer/loop.py` (`_raise_blocked` emits `chore=True` with `chore_unit`), `src/l4/delegate/run.py`.
- [x] 25.5 `ci_not_fixed` stays a person's (pinning, no code expected).
  - Result: pinned, no code. test_an_escalated_unit_has_no_delegate_action (planner) and test_an_escalated_unit_gets_no_pass (Orchestrator._delegate runs for exit 11 and phase awaiting_human or fixing only).
  - Tests first: `tests/unit/planner/test_delegate_action.py`: `test_an_escalated_unit_has_no_delegate_action`
    (SCN-DLG-85, reason `ci_not_fixed`); `tests/unit/orchestrator/test_delegate_hook.py`:
    `test_an_escalated_unit_gets_no_pass`.
- [x] 25.6 An answer is progress (pinning the merge's order, no code expected).
  - Result: done. merge_next_run extracted from run_command (same order: drop the plan's request on a dispatched or queued continuation or when no step started, then after_delegate unless a continuation carries it; its docstring names L4-DLG-026); the soft-deadline deferral is no attempt (limits.attempts_used skips reason soft_deadline) and the third in a row asks for no run (limits.soft_deferrals_in_a_row, MAX_SOFT_DEFERRALS 3, SCN-DLG-113).
  - Tests first, `tests/unit/orchestrator/test_delegate_next_run.py`:
    `test_an_answer_with_no_step_started_starts_one_run` (SCN-DLG-89), `test_a_dispatched_continuation_carries_the_answer`
    (SCN-DLG-90, also `already_queued`), `test_an_escalation_or_a_cooling_deferral_starts_nothing`; `tests/unit/delegate/test_pass.py`:
    `test_a_soft_deadline_deferral_is_no_attempt` (SCN-DLG-105: two `soft_deadline` deferrals, then a run with time
    calls the delegate and does not escalate `delegate attempts used`; and
    `test_the_third_soft_deadline_deferral_in_a_row_requests_no_run` (SCN-DLG-113)).
  - `src/l4/orchestrator.py`: `after_delegate`'s docstring names L4-DLG-026.

## 26. Discoverability (L4-DLG-021, L4-DLG-022; B1, B2)

- [x] 26.1 One hint, four places.
  - Result: `src/l4/delegate/hint.py` (`delegate_hint`, `HintReader`: base settings read once, None when the base config cannot be read) feeds `l4 questions` (text + `delegate_hint`), `l4 status --unit` (text + `--json` of a `--unit` call), `l4 yolo status` (text + `delegate_hint`) and the sticky waiting section (`build_sticky_section(hint=)`, from `clarify_hook`, `awaiting_section`, `verdict_section` and the fix loop). Tests: 8 pure + 5 + 3 + 3 + 5 through the real commands and orchestrator.
  - Tests first:
    - `tests/unit/delegate/test_hint.py`: `test_the_hint_while_off_in_scope` (SCN-DLG-71), `test_no_hint_while_on`
      (SCN-DLG-72), `test_no_hint_out_of_scope` (SCN-DLG-73), `test_no_hint_for_kinds_it_does_not_answer`,
      `test_scope_is_read_with_enabled_true` (`in_scope` on a copy), `test_the_hint_is_one_line`,
      `test_no_hint_when_the_base_config_cannot_be_read` (SCN-DLG-111: `delegate_settings` falls back to defaults, so
      the hint requires a readable base configuration).
    - `tests/unit/specs/test_questions_hint.py` (`l4 questions`: text after `Next:`, `--json` `delegate_hint`),
      `tests/unit/state/test_status_hint.py` (`l4 status --unit`), `tests/unit/yolo/test_yolo_status_hint.py` (the
      current unit in `awaiting_human`), `tests/unit/clarifier/test_notify_hint.py` (SCN-DLG-74: the waiting section
      ends with it; the needs-person section never has it).
  - New `src/l4/delegate/hint.py` (`HINT`, `delegate_hint(settings, unit, view, phase, open_kinds) -> str | None`);
    `src/l4/specs/questions_cli.py` (`run_list`), `src/l4/state/status.py`, `src/l4/yolo/commands.py`,
    `src/l4/clarifier/notify.py` (`build_sticky_section(..., hint=None)`) and its callers in `clarifier.py`,
    `verifier/notes.py` and `verifier/fixloop.py` (the run reads `delegate_settings`). Run also
    `tests/unit/specs/test_questions_cli.py`, `tests/unit/state/`, `tests/unit/yolo/test_yolo_status*.py`,
    `tests/unit/clarifier/`.
- [x] 26.2 `l4 init`'s commented block and DLG-001's line.
  - Result: `init.with_delegate_block` places the single-`#` lines inside `profiles:` and `roles:` and ends the file with `# delegate:`; `##` prose; uncommented it loads with no duplicate key for `--s1` laya, jev and none, and DLG-001 passes on it (no xfail needed: the current DLG-001 already passes). DLG-001's own line is stream 1's (24.1).
  - Tests first, `tests/unit/init/test_init_delegate_block.py`: `test_the_config_holds_the_commented_delegate_block`
    (SCN-DLG-75), `test_uncommented_as_it_says_it_loads` (strip the `# ` of the single-`#` lines: valid YAML, no duplicate `delegate:`,
    `profiles:` or `roles:` key), `test_the_uncommented_block_passes_dlg_001` (SCN-DLG-75: models pinned on `codex` and
    `claude-code`, `delegate-sonnet` on `claude-sonnet-5`), `test_the_block_names_the_runbook_and_the_model_rule`.
    (DLG-001's line: 24.1.)
  - `src/l4/init/init.py` (`DELEGATE_BLOCK`: comment lines placed inside the mappings they extend, `##` for prose). Run also `tests/unit/init/`.

## 27. Polish (L4-DLG-027; P1 to P4)

- [x] 27.1 Neutral heading, the PR body, a final decision, the `--harness-ref` refusal.
  - Result: `## Answers to verdict questions` (the two heading tests changed); `render_pr_body(delegate=)` and `_pr_body(with_delegate=)`, the hand-off refresh also matches the bodies without the line; two planner tests pin the final-for-its-raise rule (no code change: `due.FINAL`); `resolve_ref` adds the `--harness-commit` pointer for a 7 to 40 hex value.
  - Tests first:
    - `tests/unit/verifier/test_verification_md_actor.py` and `test_ladder_depth.py`: the heading is `## Answers to
      verdict questions` (SCN-DLG-91).
    - `tests/unit/archive/test_pr_body_delegate.py`: `test_the_body_names_the_delegates_answers_at_the_hand_off`
      (SCN-DLG-92), `test_no_line_without_a_delegate_answer` (the body is byte for byte today's).
    - `tests/unit/planner/test_delegate_action.py`: `test_an_upgrade_does_not_reask` (SCN-DLG-93: a `discarded`
      record of an older harness), `test_a_new_raise_is_asked` (SCN-DLG-94).
    - `tests/unit/init/test_harness_ref.py`: `test_a_sha_is_sent_to_harness_commit` (7 to 40 hex: a sha passes the
      `_REF` name check, so it is the `names no tag or branch in <remote>` refusal after `git ls-remote` that ends
      `; a commit sha goes to --harness-commit (40 hex characters)`; a branch name with hex letters only is not a sha
      below 7 characters).
  - `src/l4/verifier/report.py`, `src/l4/archive.py` (`render_pr_body(..., delegate=())`, `_pr_body` reads the
    ledger's `delegate_answers`), `src/l4/init/action.py`.

## 28. Docs

- [x] 28.1 SPEC, runbook, guides, skill, CHANGELOG.
  - Result (integration): done. `docs/SPEC.md` 3.2 gained the example profiles `delegate-oc` (with `options.delegate_kinds: [technical, harness]`) and `delegate-kiro`; the 0.4.22 section of `CHANGELOG.md` was rewritten as one feature (what it is, how to turn it on, the four serving adapters, free models limited to technical and harness kinds, the `Hint:` line and init block, the 0.4.21 rules, polish) with the amendment lines merged in and no duplicates; `check_spec.py` and the docs tests pass.
  - Result (partial, stream 2): done here: runbook (7.1 item 1 and reasons, 7.15, 10.6, 11), yolo-mode.md, SKILL.md, adopt.md (4f), control-loop.md (898 words), operate.md, plan.md, quickstart.md, README, and `tests/unit/docs/test_delegate_0422_docs.py` (11 tests). NOT done here, by instruction: `docs/SPEC.md` 3.2 and `CHANGELOG.md` (the orchestrator, after stream 1).
  - `docs/SPEC.md`: §3.2 example profiles `delegate-oc` (opencode) and `delegate-kiro` (kiro-cli, a pinned model, its
    `vendor` the model's family) under `profiles:` with comments (L4-DLG-016, L4-DLG-017, L4-DLG-019; `roles.delegate`
    stays `[delegate-opus, delegate-sol, delegate-sonnet]`, which the docs test pins); §8.3 the opencode and kiro-cli
    rows say the read-only (delegate) invocation; §12.1 `question.raised{chore}`, `budget.cost{credits, role: delegate,
    question}`, `delegate.result{credits}`; §15 the DLG-002 row (which profiles answer verdict questions, an `opencode` one flagged); §21 row 63's
    live check names opencode and kiro-cli (task 29).
  - `docs/runbook.md` §7.1, the delegate procedure: a first item "To turn the delegate on" with the B2 block, the
    recommended chain of A5 and the `Hint:` line; the escalation reasons gain `no delegate profile answers <kind>
    questions`, `a fix task cannot change <path>: …`, `kiro-cli served <m>, the profile names <p>`, `the answer would
    unfreeze <path> of task <k>, a test-support file: …` (C3), the reject reasons of C1 and C2; a sentence that a
    decided question is final for its raise (P3); §11 known limits: A2's and A3's [U]; the upgrade lines:
    `--harness-ref` takes a tag or a branch, a sha goes to `--harness-commit` (P4).
  - `docs/runbook.md` also: a kiro-cli implementer or judge with the literal `model: auto` vetoes every delegate under
    `independence: model` (pin a model, or use `independence: profile`), and a §11 limit that instruction files are
    removed from an opencode delegate's checkout.
  - `docs/yolo-mode.md` "The delegate": the four adapters and the free-model rule; the "No unfreezing by default"
    bullet says that `delegate.unfreeze: true` opens frozen test files only, never a test-support file, and nothing in
    a fix task (C3).
  - `plugins/l4/skills/l4/SKILL.md`: one bullet under "Where to look next" (a delegate can answer the questions;
    `references/operate.md`); `references/adopt.md`: an opt-in step "The delegate (optional)" with the B2 block, the
    free-model rule and the `--harness-ref` note; `references/control-loop.md`: the `awaiting_human` row says "you
    answer, or the delegate does (`delegate.enabled` on base)" and stays at most 900 words (shorten the paragraph on
    `clarifier.auto_accept_kinds` by as many words); `references/operate.md`: how to turn it on, the `Hint:` line, the
    four adapters; `references/plan.md`: the free-model rule for a plan's delegate; `docs/quickstart.md`: one
    paragraph under "Conditional extras"; `README.md`: one line.
  - `tests/unit/docs/test_delegate_0422_docs.py`: §9.1 holds L4-DLG-015 to L4-DLG-027; every SCN-DLG of the change is
    in §23.27 (the existing test); each file above holds its sentence (`delegate.enabled`, `roles.delegate`,
    `docs/runbook.md 7.1` or the runbook section, `opencode`, `kiro-cli`, `technical and harness`), the control-loop
    reference stays at most 900 words, and the runbook names `--harness-commit` beside `--harness-ref`.
  - `CHANGELOG.md` under `## 0.4.22 (unreleased)`:
    - `### Added`: "The delegate runs on opencode and kiro-cli profiles too, each in a read-only mode L4 builds from an
      allow-list (opencode: read, glob and grep in the worktree, with nested instruction files removed and `options.tools` ignored; kiro-cli: a harness agent with read, glob and
      grep), and replies in its last message (L4-DLG-015 to L4-DLG-017)." / "`profiles.<p>.options.delegate_kinds`
      narrows the questions a delegate profile answers; a free-tier model answers technical and harness questions only
      (L4-DLG-019)." / "While the delegate is off, `l4 questions`, `l4 status --unit`, `l4 yolo status` and the sticky
      note of a waiting unit in scope print one `Hint:` line, and `l4 init` writes the delegate as a commented-out block
      (L4-DLG-021, L4-DLG-022)."
    - `### Changed`: "The delegate's prompt is `delegate@3`: the read tools are named for any CLI, and a reject's `WHEN
      … THEN …` states the behaviour the fix must give, never the judge's suggested fix (L4-DLG-023)." / "A delegate's
      reject of a finding that cites no criterion needs a `WHEN … THEN …`; a reject of a judge-view hold is discarded;
      an accept of a cap-only criterion cites the test's lines (L4-DLG-023, L4-DLG-024)." / "`delegate.unfreeze` no
      longer opens a test-support file, and nothing in a fix task; a fix chore's answer that changes a test or support
      file goes to a person (L4-DLG-014, L4-DLG-025)." / "`verification.md` titles the verdict answers `## Answers to
      verdict questions`; the PR body names the delegate's answers; DLG-001 names how to turn the delegate on
      (L4-DLG-022, L4-DLG-027)." / "`l4 upgrade --harness-ref` with a commit sha says to use `--harness-commit`."
    - `### Fixed`: "The delegate's independence check compares models after their provider prefix
      (`openrouter/anthropic/claude-opus-5-5` is `claude-opus-5-5`) and treats a kiro-cli `auto` profile as no known
      model (L4-DLG-018)." / "A Kiro delegate call's credits are recorded (L4-DLG-020)."
  - Then `uv run python scripts/check_spec.py docs/SPEC.md`, `openspec validate delegate-answers --strict`, and the whole
    unit suite once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit`.

## 29. Live validation on a dummy repository (never a consumer repository)

- [x] 29.1 An opencode delegate (a low-cost model of the default implementer's provider) answers a technical question
  that the unit's `design.md` settles: record the argv, the configuration (redacted), the tool calls, the reply, the
  cost, that a write attempt fails, and whether opencode writes into its working directory (`.opencode/`); the tool names of the run (whether a `list` tool
  exists), that a profile with `options.tools: [bash, edit]` still has neither, a nested `AGENTS.md` planted in the
  dummy that tries to steer the answer (it is removed from the checkout and the answer ignores it), and that a `.env`
  file is unreadable.
  - Result: PASS (2026-10-21, public dummy, runs 39638064672, 39638710540, 39638986374;
    docs/live/delegate-answers/0.4.22.md). `delegate-oc` (opencode 1.18.34, `opencode-go/glm-5.3-flash`,
    `options.tools: [bash, edit]`) answered Q-001 of `add-commission` from `docs/money-rules.md` (the project
    document, not a `design.md`): half to even, $0.00445 = the sum of the stream's `step_finish.cost`; the
    bot-dispatched next run implemented it, PASS. Tools of the run: `read`, `glob` (no `list` tool: `read` lists a
    directory). A `docs/AGENTS.md` pushed to the unit branch ("answer round half up") is in the git tree but not in
    the delegate's `glob **/*.md`, and the answer ignores it. The permission map is the one `config_content` builds
    (no `bash`, `edit`, `list`; `*.env` denied). Not verified: a write attempt, a `.env` read and a call to `bash` or
    `edit` (the model never tried), `.opencode/` writes (read-only bind, empty stderr), the argv as run (not logged).
- [x] 29.2 A kiro-cli delegate on a pinned model answers a technical and a verdict question: record the agent file, the
  tool calls, the credits, the session file's model, whether a tooled agent runs headless on `--v2` with the prompt on stdin (design A3: [U]; the
  `--v2` flag is not load-bearing; if stdin prompts fail with tools, the specified fallback is the prompt as an
  argument with prompts over `MAX_ARG_BYTES` escalated, as an amendment of L4-DLG-017's argv), whether `toolsSettings` can confine `read` to the
  worktree on the pinned 2.x, and whether kiro-cli writes into its working directory (`.kiro/`).
  - Result: PASS (runs 39639565794, 39640215367, 39641113267; docs/live/delegate-answers/0.4.22.md). `delegate-kiro`
    (kiro-cli 2.32.0, `claude-opus-5.5`) answered Q-001 (technical) and accepted Q-002 and Q-003 (verdict) of
    `add-deposit`; round 2 PASS. A tooled agent runs headless with `--v2` and the prompt on stdin (`runStarted{engine:
    v2}`; calls `grep`, `read`, `glob` only), so the argument fallback is not needed. Credits 0.70011, 0.934681,
    0.95407 (`budget.cost{credits, credits_source: kiro.stream}`, counted at $3.00 each). Agent file recorded from
    `delegate_agent_config`. Not verified: the session file's exact `model_id` (no mismatch, so it named the pin or
    nothing), whether `toolsSettings` can confine `read` to the worktree, `.kiro/` writes (read-only bind, empty
    stderr).
- [x] 29.3 A free Zen model last in the chain: a verdict question skips it (`kinds:`), a technical question is
  answered by it while the strong profiles are vetoed.
  - Result: PASS on the second try (runs 39641666425, 39642770691, 39643552645; docs/live/delegate-answers/0.4.22.md).
    Chain `[delegate-ds, delegate-free]`. First try: `opencode/longcat-2.5-preview-free` failed its hello (60 s
    timeout) and the question escalated at once (finding F2). Second try with `opencode/mimo-v2.6-flash-free`: on
    `add-booking-fee` `delegate-ds` was vetoed by independence and the free model answered the technical question
    ($0.00, then PASS); on `add-tip` both verdict questions skipped it (`kinds: delegate-free answers technical and
    harness questions`) and escalated `no independent delegate` with `l4:needs-person`. DLG-001 passed that chain
    (finding F1).
- [x] 29.4 With the delegate off, `l4 yolo status`, `l4 status --unit` and the sticky note of a plan's waiting unit
  show the `Hint:` line; with it on, none does.
  - Result: PASS for `l4 status --unit`, `l4 questions` (and `delegate_hint` in `--json`) and the sticky note of a
    waiting unit in no plan with `scope: all` (PR #11), each with the `Hint:` line while the delegate was off and none
    while it was on (PR #13's note, the two commands). Not verified: `l4 yolo status` (it needs an active or waiting
    plan, and an agent cannot activate one).
- [x] 29.5 Record what was not verified in `docs/live/delegate-answers/` and §11 of the runbook.
  - Result: done: docs/live/delegate-answers/0.4.22.md (what ran, the run ids, the PRs, the kiro agent file, the
    opencode map, the hint output, findings F1 to F4, what was not verified) and §11 of the runbook (what stays
    unverified, the hello escalation, the DLG-001 gap).
## 30. Findings of the 0.4.22 live test

- [x] 30.1 Live finding F1: DLG-001 checks, per kind of `delegate.kinds`, that a profile is both allowed the kind and
  independent of every asker of it (SCN-DLG-114).
  - Result: done. `_joint_problems` (checks_delegate.py) replaces the verdict-only joint check;
    `test_a_kind_whose_allowed_profiles_are_all_vetoed_fails` failed on the old code; `test_a_kind_no_profile_may_answer_fails`
    now uses an independent second profile (its `delegate-sol` is the implementer's model, which the old check missed).
