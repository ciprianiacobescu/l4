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
    - `test_attempts_per_question` (calls and deferrals of the current raise).
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
    (SCN-DLG-33), `test_a_usable_chain_passes` (SCN-DLG-34), `test_no_usable_profile_warns_with_the_fix`,
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
    - §21: row 49 `delegate-answers`, its outcome in one sentence (requirement ids,
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
  - `CHANGELOG.md`: `## 0.4.19 (unreleased)` above the newest entry (the 0.4.17 and 0.4.18 entries arrive by merge),
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
