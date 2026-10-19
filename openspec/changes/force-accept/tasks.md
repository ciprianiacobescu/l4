Every task follows these rules:
- Read `design.md` of this change first. Every event key, function signature and quoted text is in it (section
  "Contracts" and D1 to D9); do not change one without the orchestrator.
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`, then
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. At the end of section 5, run `.venv/bin/python -m pytest -q -p no:cacheprovider
  tests/unit/yolo tests/unit/mcp tests/unit/docs tests/unit/archive tests/unit/implementer tests/unit/orchestrator
  tests/unit/test_accepted_reader.py tests/unit/cli` once.
- Never wait on a process with `while pgrep -f …` (it matches itself). Stage explicit paths only. Name a consumer
  repository "a consumer repository"; no local paths in docs.
- Worlds: `tests/unit/yolo/yolo_cmd_world.py` (`world`, `A` = `openspec:add-greeting`, `B` = `openspec:add-b`, batch
  `b1`, `ev`, `plan_doc`, `world.reviewed`, `world.seed`, `world.l4`), `yolo_review_events.py` (`review`, `entry`,
  `two_rounds`, `TESTABILITY`, `FAILURES`, `BLOCKING`), the `person` fixture and `agent()` helper of
  `test_yolo_commands_accept.py` (move both to a new `tests/unit/yolo/yolo_actor.py` and import them from there in both
  test files; `person` must also record the prompt's keyword arguments, as `asked_kwargs`), and `judge(monkeypatch, …)`,
  `answer()`, `ready_world`, `cache_lines` of `test_yolo_review_worktree.py`.
- "No model": a test that must not reach a judge sets
  `monkeypatch.setattr("l4.yolo.readiness.Factory", Boom)` and `monkeypatch.setattr("l4.yolo.commands.review_plan_costed",
  boom)` where `Boom`/`boom` raise `AssertionError("no model")`.

## 1. The force acceptance: state and rules (L4-YOLO-057, L4-YOLO-060)

- [x] 1.1 Fold. Tests first, `tests/unit/yolo/test_yolo_state_fold.py`: `test_force_accepted_is_kept_with_its_time`
  (`plan.force_accepted` sets `state.force_accepted` to its data plus `at`, in `new`, `reviewed` and stopped
  `inputs_changed`); `test_a_later_force_acceptance_replaces_the_earlier` (SCN-YOLO-162 at fold level);
  `test_a_withdrawal_clears_the_force_acceptance`; `test_a_final_plan_ignores_a_force_acceptance` (after
  `plan.cancelled`); `test_an_old_ledger_has_no_force_acceptance`. Code: `PlanState.force_accepted: dict[str, Any] |
  None = None` (`src/l4/yolo/model.py`); the two branches in `fold_plan` (`src/l4/yolo/state.py`) and one docstring
  line. Run: that test file.

- [x] 1.2 Rules. Tests first, `tests/unit/yolo/test_yolo_accept_rules.py` (events with `ev`, plans with
  `l4.yolo.model.Plan.model_validate(plan_doc())`):
  `test_status_refusal_is_the_first_rule_of_check` (every status of `check`'s first rule, same text);
  `test_force_subjects_skips_no_review`, `…_stale_review` (each of: other plan digest, other prompt version, the unit's
  digest, one unit of the batch), `…_blocked`, `…_blocking_material_and_rounds_in_order`, `…_not_ready`,
  `…_ready_skips_nothing`; `test_force_subjects_records_digest_digests_review_at_verdict_material` (a unit gets
  `digest`, `batch:b1` gets `digests` of A and B, `review_at` is the latest `plan.reviewed`'s `at`);
  `test_force_holds_per_subject` (SCN-YOLO-160 at function level: A changed → A and `batch:b1` False, B True; plan digest
  changed → all False; `MISSING` recorded or current → False; `None` force → `{}`);
  `test_force_line_holds_and_void` (both texts of D6). Code: `src/l4/yolo/accept.py`: `status_refusal`, `force_subjects`,
  `force_holds`, `force_line`, the `SKIPPED_WORDS` mapping of D6, `check` calls `status_refusal`. Run: that test file.

## 2. The command (L4-YOLO-057, -058, -059, -060, -063)

- [x] 2.1 CLI and usage. Tests first: `tests/unit/cli/test_dispatch.py`:
  `test_yolo_accept_takes_all_and_force_without_a_subject` (monkeypatch `l4.yolo.commands.run_accept` to record its
  keyword arguments; `main(["yolo", "accept", "p1", "--all", "--force", "--reason", "go", "--repo", …])` reaches it
  with `all_subjects=True, force=True, subject=None`; the existing `ARGV` row stays); new file
  `tests/unit/yolo/test_yolo_commands_force_accept.py`: `test_the_flags_are_checked_before_anything_is_read`
  (SCN-YOLO-153: the four usage errors of D1, exit 2, `world.store().read().head` unchanged, `_sync` not called:
  monkeypatch `l4.yolo.commands._sync` to raise). Code: `src/l4/cli.py` (`subject` `required=False`, `--all` dest
  `all_subjects`, `--force` dest `force`, the `--yes` help of D8); `run_accept(..., all_subjects=False, force=False)` in
  `src/l4/yolo/commands.py` checks D1's usage rules first and routes `--all --force` to a new `_run_force_accept`.
  Run: both files.

- [x] 2.2 Who. Tests first (same new file): `test_an_agent_is_refused_even_when_agents_may_accept` (SCN-YOLO-154:
  push `.l4/config.yaml` with `accept_by_agents: true`, `agent(world, monkeypatch)`, `--yes`; exit 2; the D2 text with
  `CLAUDECODE is set` and the command; ref unchanged); `test_an_mcp_caller_is_refused` (SCN-YOLO-155: `agent(world,
  monkeypatch, "AI_AGENT")` with value `l4-mcp`; `AI_AGENT is set`); `test_no_terminal_is_refused_and_nothing_prompts`
  (SCN-YOLO-156: `_stdin_tty` False, no marker, `--yes`; `stdin is not a terminal`); in
  `tests/unit/mcp/test_tools.py`: `test_no_tool_runs_yolo_accept` (no tool's command words start with
  `("yolo", "accept")`, checked on `TOOLS`). Code: the actor check of D2 at the top of `_run_force_accept`, before
  `_sync`. Run: both files.

- [x] 2.3 What stays refused. Tests first (same new file): `test_a_unit_with_no_folder_is_refused_by_admission`
  (SCN-YOLO-157: `plan_doc({A: [], "openspec:ghost": []})`, `unknown_unit` line, no prompt, nothing recorded);
  `test_a_missing_digest_is_refused_as_unit_missing` (monkeypatch `l4.yolo.commands._now_digest` to return `MISSING`
  for B; the D3 text); `test_a_cycle_is_refused` (SCN-YOLO-158: `plan_doc({A: [B], B: [A]})`); `test_an_active_plan_is_refused`
  (SCN-YOLO-159, seeded `plan.activated`); `test_a_file_that_is_not_a_plan_is_refused`. Code: `_admitted(...)` extracted
  from `run_activate` (which now calls it), then the status, admission and `unit_missing` checks of D3 in
  `_run_force_accept`. Run: the new file and `tests/unit/yolo/test_yolo_commands_activate.py`.

- [x] 2.4 Record. Tests first (same new file): `test_a_person_force_accepts_a_blocked_review_and_no_model_is_called`
  (SCN-YOLO-150: `world.reviewed({A: "BLOCKED"}, findings={A: [{"criterion": "schema", "severity": "blocking", "text":
  "schema_invalid: ok"}]})` seeded, the "No model" patches, `person` types `p1`; the D6 summary lines; the event's
  keys and values of D4 including `confirmed: "typed"`, `actor: "person"`, `marker: None`, `subjects[A].skipped ==
  ["blocked"]`, `subjects[B].skipped == []`, `subjects["batch:b1"].digests`; no new `plan.reviewed`);
  `test_a_plan_never_reviewed_is_admitted_and_force_accepted` (SCN-YOLO-151: kinds are `["plan.admitted",
  "plan.force_accepted"]`, every `skipped == ["no_review"]`, then `l4 yolo status p1` shows `admitted`);
  `test_an_admitted_plan_gets_no_second_admission` (state already admitted at this digest and order → only
  `plan.force_accepted`); `test_any_other_answer_records_nothing` (SCN-YOLO-152); `test_the_reason_rules_apply`
  (empty, 1001 characters); `test_a_lost_lease_says_the_plan_moved`. Code: the rest of `_run_force_accept` (D4, D6
  summary, `_confirm` of task 4.1 may come later: use `click.prompt(..., err=True)` here and switch to `_confirm` in
  4.1). Run: the new file.

- [x] 2.5 Withdraw. Tests first (same new file): `test_a_withdrawal_by_an_agent_removes_it` (SCN-YOLO-161);
  `test_nothing_to_withdraw`; `test_a_withdrawal_after_activation_is_refused`;
  `test_a_second_force_acceptance_replaces_the_first` (SCN-YOLO-162: after a push to A's spec, force-accept again;
  every subject holds). Code: the withdrawal branch of D7. Run: the new file.

## 3. Activation and visibility (L4-YOLO-061, L4-YOLO-062)

- [x] 3.1 Activation. Tests first, `tests/unit/yolo/test_yolo_commands_activate.py`:
  `test_a_force_accepted_plan_never_reviewed_activates` (SCN-YOLO-163: event `review == "force_accepted"`,
  `accepted` items of A, B and `batch:b1` exactly `{"findings": [], "reason": R, "by": "alex@example.com", "actor":
  "person", "force": True}`; the printed force lines); `test_a_later_blocked_review_does_not_undo_it` (SCN-YOLO-164:
  force-accept with no review, then seed `world.reviewed({A: "BLOCKED"}, …)` at the same digests; exit 0);
  `test_a_voided_force_acceptance_is_named_in_the_refusal` (SCN-YOLO-165: push a change of A's spec; exit 2; the D5 line
  names `openspec:add-greeting, batch:b1`); `test_a_ready_subject_of_a_force_acceptance_is_not_cleared_later`
  (force-accept when B is READY at the current review, then A's spec changes and a current review says B
  NEEDS_REVISION at B's same digest: B is still a problem); the regression guard
  `test_activation_without_force_has_no_review_key` (passes today and must keep passing: the event of
  `test_activation_without_acceptances_records_an_empty_accepted` has no `review` key). Code:
  `ReviewView.force`, `.covered`, `.forced`, `.ready` and the force step of `_review_view` (D5); `run_activate` (D5).
  Run: that file and `tests/unit/yolo/test_yolo_commands_findings.py`.

- [x] 3.2 Status and findings. Tests first: `tests/unit/yolo/test_yolo_commands_activate.py`:
  `test_status_names_the_force_acceptance_and_says_activate` (SCN-YOLO-166, status part: text lines of D6, the
  `review:` suffix, `Next: l4 yolo activate p1 --reason TEXT`; `--json` `review.force_accepted` with `covered`, each
  subject's `holds`, `skipped`, `review_at`, `verdict`; a voided subject's line; after activation the
  `activated_force` list and its lines); `tests/unit/yolo/test_yolo_commands_findings.py`:
  `test_findings_name_the_force_acceptance_even_without_a_review` (the line follows `no review yet`; `--json` has
  `force_accepted`, also in the empty document). Code: `run_status`/`_describe`/`_render`/`_next_line` and
  `run_findings` in `src/l4/yolo/commands.py`. Run: both files and `tests/unit/yolo/test_yolo_status_activity.py`.

- [x] 3.3 Carrier, implementer, report, PR body. Tests first:
  `tests/unit/yolo/test_yolo_cycle_active.py`: `test_a_dispatch_carries_a_force_item_with_force_true` (an activation with
  a force item for A: `step.accepted[A]` has the item with `"force": True` and `findings == []`; an ordinary item has no
  `force` key); `tests/unit/test_accepted_reader.py`: `test_a_force_item_keeps_force_and_an_ordinary_item_has_no_key`;
  `tests/unit/implementer/test_prompt.py`: `test_a_force_item_renders_the_force_rule_and_the_reason` and
  `test_without_a_force_item_the_block_is_unchanged` (byte equality with today's block for an ordinary item);
  `tests/unit/yolo/test_yolo_cycle_auto.py`: `test_the_report_names_a_force_accepted_unit` and
  `test_a_force_accepted_unit_has_no_accepted_finding_open` (with `merge: auto` the guard merges as for a unit with no
  item); `tests/unit/archive/test_render.py`: `test_the_body_names_a_force_acceptance` (D6 line after the
  `Verification` line, the reason on one line) and `test_a_body_without_the_force_line_is_still_the_harness_body`
  (`harness_body(old_body, fresh_with_line, fresh_without_line)` is True). Code: `cycle._accepted`, `accepted._item`,
  `tdd.FORCE_RULE` and `accepted_block`, `report._accepted_lines`, `archive.render_pr_body`, `_pr_body` and the
  hand-off's `harness_body` call (pass the body rendered without the line as one more candidate). Run: the six files.

## 4. Confirmation (L4-YOLO-063, L4-YOLO-064)

- [x] 4.1 A person's `--yes`, the recorded confirmation and the stderr prompt. Tests first:
  `tests/unit/yolo/test_yolo_commands_accept.py`: replace `test_a_person_with_yes_is_still_asked_for_the_plan_id` by
  `test_a_person_with_yes_is_not_asked_and_the_event_says_so` (SCN-YOLO-168: `person == []`, the findings printed,
  `confirmed == "--yes"`); `test_a_person_who_types_is_recorded_as_typed` (`confirmed == "typed"`, `judged_at` is the
  review's `at`); `test_an_agent_with_yes_records_confirmed_yes` (SCN-YOLO-170, extend
  `test_an_agent_cannot_accept_unless_the_target_allows_it`); `test_the_prompt_is_written_to_stderr` (SCN-YOLO-172:
  `asked_kwargs[0]["err"] is True`); `tests/unit/yolo/test_yolo_commands_waive.py`:
  `test_a_person_waives_with_yes_without_a_prompt` and `test_the_waive_prompt_is_written_to_stderr`; the force file:
  `test_a_person_force_accepts_with_yes` (SCN-YOLO-169) and `test_the_force_prompt_is_written_to_stderr`. Code:
  `_confirm` of D8 used by `_show_and_confirm`, `run_waive` and `_run_force_accept`; `run_accept` and `run_waive` skip it
  for a person with `--yes`; `confirmed` and `judged_at` on the events. Run: the three files.

- [x] 4.2 Nothing prompts without a terminal. Regression guards that already pass at c1994292 (no terminal makes the
  caller an agent, which never reaches a prompt): `tests/unit/yolo/test_yolo_commands_accept.py` and
  `tests/unit/yolo/test_yolo_commands_waive.py`: `test_without_a_terminal_nothing_prompts` (SCN-YOLO-171: `_stdin_tty`
  False, no marker, `accept_by_agents: true` pushed, `click.prompt` raises `AssertionError`; exit 2 naming `--yes`).
  Failing first: `test_confirm_refuses_without_a_terminal` in `test_yolo_commands_accept.py` (call `commands._confirm`
  directly with `_stdin_tty` False: exit 2 `accept: no terminal to ask the plan id on: pass --yes`, `click.prompt`
  never called). Code: the terminal check inside `_confirm`. Run: both files.

## 5. The acceptance binding (L4-YOLO-065, L4-YOLO-066)

- [x] 5.1 Reproduce hypothesis (i) and keep the accepted judgement. Tests first:
  `tests/unit/yolo/test_yolo_findings_history.py`: `test_prior_entries_prefers_the_judgement_an_acceptance_is_bound_to`
  (two `plan.reviewed` of material `m1` for A, findings `[T]` at t1 and `[F]` at t2; `accepted={A: {"material": "m1",
  "findings_sha": findings_sha([T])}}` → the t1 entry; without `accepted` → the t2 entry (today's rule); an acceptance
  of other material changes nothing). `tests/unit/yolo/test_yolo_review_worktree.py`:
  `test_a_reuse_keeps_the_accepted_judgement_of_the_same_material` (SCN-YOLO-173, end to end: `ready_world`, one dry run
  with `judge(monkeypatch, answer("NEEDS_REVISION", [GAP]), answer(), answer())` to learn A's material key from
  `cache_lines`; seed `plan.reviewed` at t1 (A: that key, `[GAP]`; B and `b1` READY with their keys from the cache),
  `plan.accepted` of A bound to that key and `findings_sha([GAP])`, then a second `plan.reviewed` at t2 with A on the
  same key and `[OTHER]`; push a plan file whose `limits` differ and pull; run `l4 yolo review p1 --worktree --record`
  with `judge(monkeypatch)` (no call allowed); the recorded A entry has findings `[GAP]` and `reused_from` t1, and
  `l4 yolo activate p1 --reason go` exits 0 and prints the acceptance). Run them and see both fail (the t2 entry is
  reused). Code: `findings.prior_entries(..., accepted=None)` (D9.1) and the three callers (`cycle._review`,
  `commands.run_review` `--local`, `review_worktree.run_review_worktree`) pass `state.accepted`. Run: both files and
  `tests/unit/yolo/test_yolo_cycle_review.py`.

- [x] 5.2 Hypothesis (ii) and the why-line. Tests first: `tests/unit/yolo/test_yolo_accept_rules.py`:
  `test_why_not_holds_other_material_own_spec`, `…_other_material_prerequisite`, `…_other_findings_same_material`
  (with and without `judged_at`, `reused` and `new`), `…_no_entry` (texts of D9.2);
  `tests/unit/yolo/test_yolo_review_worktree.py`: `test_a_fresh_dry_run_names_other_findings_and_record_keeps_the_ledger`
  (SCN-YOLO-174: accepted on the ledger as in 5.1 (one judgement only); a dry run `--fresh openspec:add-greeting` whose
  judge returns `[OTHER]` prints `no longer holds: it was for other findings of the same material` and not `the
  material changed`; then `--record` with `judge(monkeypatch)` (no call) records A reused from the ledger with `[GAP]`,
  and the acceptance holds: the guard part passes today, the text part fails today). Update:
  `test_yolo_commands_activate.py::test_a_change_of_the_material_voids_the_acceptance` (now asserts the prefix
  `(the acceptance by alex@example.com was for other material: accepted on material m2 with findings `; its seeded
  acceptance has no `digests`, so no cause clause),
  `test_yolo_findings_render.py` line 146 (now `(no longer holds: it was for other material: …`). Code:
  `accept.why_not_holds`; `_review_view` keeps the latest `plan.reviewed` event (for `review_at`) and uses it;
  `findings.render`/`render_json` take `why`; `run_findings`, `_show_and_confirm` and `review_worktree._show` pass it.
  Run: the four files.

- [x] 5.3 An accepted subject is shown as accepted. Tests first: `tests/unit/yolo/test_yolo_findings_render.py`:
  `test_a_holding_acceptance_is_on_the_subject_line` and `test_a_reused_entry_says_when_it_was_judged`;
  `tests/unit/yolo/test_yolo_review_worktree.py`: `test_the_worktree_line_names_the_acceptance_and_the_judgement_time`
  (`(reused), judged <t>; accepted by <by>: it does not stop the activation`; the `(reused)` counts of the existing
  tests stay right); `tests/unit/yolo/test_yolo_commands_activate.py`:
  `test_review_local_names_a_holding_acceptance_and_says_activate` (SCN-YOLO-175, `--local` part: extend that file's
  `fake_judge(monkeypatch, verdicts, materials=None, findings=None, batches=None)` so a verdict carries the material
  and findings of the seeded acceptance and `b1` is READY; defaults keep today's behaviour);
  `tests/unit/yolo/test_yolo_cycle_review.py`: `test_the_review_log_counts_the_accepted` (`(1 accepted)`; the line of
  the existing test at its line 188 stays as it is). Code: D9.3 and D9.4 in `findings.py`, `review_worktree._show`,
  `commands.run_review` (`--local`), `cycle._review`'s log line. Run: the four files. Then the whole run of the rules.

## 6. Documentation and SPEC (L4-YOLO-067)

- [x] 6.1 Tests first, new `tests/unit/docs/test_force_accept_docs.py` on the model of
  `test_plan_run_lessons_docs.py`: `test_the_spec_has_the_eleven_requirements_and_their_scenarios_in_order`
  (`**L4-YOLO-057 ` to `**L4-YOLO-067 ` after `**L4-YOLO-056 `; `#### SCN-YOLO-150 ` to `#### SCN-YOLO-176 ` after
  `#### SCN-YOLO-149 ` and before `### 23.21`; `| 53 | \`force-accept\` |`; the `yolo accept` CLI row has
  `--all --force`); `test_the_yolo_doc_has_the_section_with_the_risk_and_the_alternative` ("When the reviewer is
  unavailable", `l4 yolo accept <plan> --all --force`, `l4 yolo review <plan>`, `no model reviewed`);
  `test_the_runbook_has_the_procedure` (12.2a: `--all --force`, `--yes`, `plan.force_accepted`);
  `test_the_skill_keeps_agents_off_the_force_path` (`plan.md` and `operate.md` say never to run `--force` and give the
  command); `test_the_changelog_names_the_three_fixes` (in `## 0.4.18 (unreleased)`: `plan.force_accepted`, `--yes`,
  `stderr`, `reused`). Code: the edits of D10 in `docs/yolo-mode.md`, `docs/runbook.md`,
  `plugins/l4/skills/l4/references/plan.md` and `operate.md`, `CHANGELOG.md` (lists without blank lines between
  items), `docs/SPEC.md` (the requirements, scenarios, row 53, CLI rows and the three sentences of D10; each scenario
  `#### SCN-YOLO-NN (+|−) Title · L4-YOLO-0NN` with **Given**/**When**/**Then**). Run: that file,
  `tests/unit/docs`, `.venv/bin/python scripts/check_spec.py docs/SPEC.md` (clean) and
  `openspec validate force-accept --strict`.
