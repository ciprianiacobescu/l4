Every task follows these rules:
- Read `design.md` of this change first. Every stop code, step status, signature and quoted text is in it (section
  "Contracts" and D1 to D12); do not change one without the orchestrator.
- Prerequisite (the orchestrator, before task 1.1): this branch is rebased on force-accept and yolo-guardrails as
  merged. Check that `l4 yolo accept PLAN --all --force`, `commands._confirm`, `ReviewView.covered`,
  `tests/unit/yolo/yolo_actor.py` (`person`, `agent`) and `plugins/l4/skills/l4/scripts/yolo_preflight.py` exist. If
  one is missing, stop and tell the orchestrator; do not write a stand-in.
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`, then
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`.
- Never wait on a process with `while pgrep -f …` (it matches itself and never ends); run tests in the foreground.
  Stage explicit paths only (`git add <file> …`, never `git add -A` or a directory). Name a consumer repository "a
  consumer repository"; no local paths in docs or tests.
- Worlds and helpers: `tests/unit/yolo/yolo_cmd_world.py` (`world`, `A` = `openspec:add-greeting`,
  `B` = `openspec:add-b`, batch `b1`, `ev`, `plan_doc`, `world.push_plan`, `world.reviewed`, `world.seed`,
  `world.l4("go", …)` runs `l4 yolo go …`, `world.clone` is the checkout under test), `yolo_review_events.py`
  (`review`, `entry`, `two_rounds`, `TESTABILITY`, `FAILURES`, `BLOCKING`), `yolo_actor.py` (`person` fixture, `agent()`).
  A local commit that is not pushed: write the file in `world.app.repo` and commit it with `world.clone.run(...)`.
- "No model": `monkeypatch.setattr("l4.yolo.readiness.Factory", Boom)` and
  `monkeypatch.setattr("l4.yolo.commands.review_plan_costed", boom)`, raising `AssertionError("no model")`.
- "Fake forge": `monkeypatch.setattr("l4.yolo.go.start_run_result", fake)` where `fake(app, cfg)` appends to a list and
  returns `(answer, line)`. "Fake CI": `monkeypatch.setattr("l4.yolo.go._sleep", ci)` where `ci(seconds)` counts its
  calls and, on the n-th, seeds `world.reviewed()` (or a `plan.refused`) with `world.seed`; a fake `_clock` adds the
  slept seconds, so a wait ends without real time passing.
- Two implementers: **I1** owns `src/l4/yolo/go.py` and tasks 1, 3 to 7; **I2** owns `src/l4/yolo/preflight.py`, the
  refactors of task 2.2, MCP and docs (tasks 2, 8, 9). Waves: (1.1, 1.2 | 2.1, 2.2), (1.3, 3 | 8), (4, 5 | 9), (6, 7),
  10. One implementer does them in number order.

## 1. Walking skeleton (M1): a person's go on a reviewed READY plan

- [x] 1.1 (I1) The pure core. Tests first, new `tests/unit/yolo/test_yolo_go_core.py`:
  `test_the_stop_codes_are_twenty_to_twenty_nine_and_not_exit_codes` (`GoStop` values of D9; no `ExitCode` member has a
  value 20..29; `SEVERITY_ORDER` unchanged); `test_step_reached_is_the_last_step_reached`;
  `test_as_json_has_the_keys_and_the_seven_steps_in_order` (D10 keys exactly, `schema == "l4/yolo-go@1"`, `exit` is an
  int); `test_command_line_quotes_the_reason_and_repeats_the_flags` (`'a b'`; the flag order of D9; `drop` and `add`);
  `test_a_persons_command_has_no_yes_json_or_no_push`. Code: `src/l4/yolo/go.py`: `GoStop`, `STEPS`, `STATUSES`,
  `Step`, `GoResult`, `Flags`, `command_line`. Run: that file.

- [x] 1.2 (I1) The decision. Tests first, new `tests/unit/yolo/test_yolo_go_decide.py`, with a `facts(**over)` builder of
  `Facts` defaults (a person, a new plan, admitted, review `current`, no problem): one test per rule of D5 to D8, in
  that order: `test_active_and_waiting_are_active_before_admission`; `test_completed_is_active_with_the_report`;
  `test_cancelled_and_other_stops_are_plan_state` (`limit_runs`, `unit_halted`; not `inputs_changed`);
  `test_a_rejected_unit_with_an_unchanged_spec_is_plan_state`; `test_no_file_an_invalid_file_and_findings_are_not_admitted`;
  `test_covered_skips_the_review`; `test_force_without_a_current_review_force_accepts`; `test_local_reviews_here`;
  `test_ci_is_asked_then_pending_after_the_wait`; `test_a_refusal_after_the_ask_is_not_admitted`;
  `test_problems_without_a_flag_stop_at_findings` (next with `--accept-findings` when every `refusals` value is None,
  with `--accept-findings --yes` for an agent, else `l4 yolo findings p1`; the `--force` hint only for a person and a
  BLOCKED subject); `test_accept_findings_is_all_or_nothing` (person-only refusals → 27, a rule refusal → 26, an agent
  without `--yes` → 29, none → `Do("accept", subjects in plan order)`); `test_an_agent_at_the_activation_is_a_person_step_or_refused`;
  `test_a_person_at_the_activation_activates`. Code: `Facts`, `Stop`, `Active`, `Do`, `decide` in `go.py` (pure: the
  test imports nothing from git or the world). Run: that file.

- [x] 1.3 (I1) The command end to end on the simplest path. Tests first: `tests/unit/cli/test_dispatch.py`: add `"go"`
  to `YOLO_WORDS` and `"yolo go": ["yolo", "go", "p1", "--reason", "go"]` to `ARGV` (the registry tests fail until the
  handler exists), and `test_yolo_go_reaches_run_go_with_its_options` (monkeypatch `l4.yolo.go.run_go` to record its
  keyword arguments; every option of D1 reaches it with its dest; `wait` defaults to `"30m"`); new
  `tests/unit/yolo/test_yolo_go_activate.py`: `test_a_person_activates_a_reviewed_ready_plan` (`world.push_plan()`,
  `world.pull()`, `world.seed("p1", world.reviewed())`, the `person` fixture with a prompt that fails the test; exit 0;
  one `plan.activated` with `reason == "ship it"`; the step lines `preflight: ok` … `activate: done`; exactly one line
  starts with `Next:` and it is `Next: l4 yolo status p1`); `tests/unit/yolo/test_yolo_go_core.py::
  test_the_flags_are_checked_before_anything_is_read` (SCN-YOLO-201: monkeypatch `l4.yolo.commands._sync` to raise;
  each usage error exits 2; the plan ref head unchanged). Code: `cli.py` (`_SPECS["yolo go"]`, `_CANCELLABLE`),
  `commands.py` (`HANDLERS`, `OWNING_CHANGE`), `yolo/commands.py` (`_admission_at`, which `run_check` now calls: run
  `tests/unit/yolo/test_yolo_commands_check.py` unchanged), `go.py` (`run_go`, the usage rules of D1, `_gather`, the
  loop of D2, `_relay`, the steps check → activate for a person; preflight and push may be `ok` stubs that the later
  tasks replace; a `Do("review_ci")` stops with 24 until task 4.3). Run: the three files and
  `tests/unit/yolo/test_yolo_commands_check.py`.

## 2. Preflight and the shared refactors (L4-YOLO-081)

- [x] 2.1 (I2) The checks and the parity with the skill script. First read `scripts/yolo_preflight.py` at this base: when
  its checks differ from design D3, make D3 and the function follow the script (same codes, same order) in this
  task's commit and say so in its message. Tests first, new `tests/unit/yolo/test_yolo_go_preflight.py` (each fixture a
  fresh `world`): `test_a_clean_tree_has_no_problem`; `test_a_tracked_change_is_dirty` (staged and unstaged);
  `test_a_plan_on_neither_side_is_missing`; `test_an_untracked_plan_file_is_uncommitted`;
  `test_an_untracked_file_in_a_unit_folder_is_a_problem_and_one_elsewhere_is_not` (SCN-YOLO-203, function level);
  `test_the_harness_and_the_skill_script_agree` (SCN-YOLO-204: run the script with `subprocess.run([sys.executable,
  "-I", <script>, …], cwd=<repo>)` as its usage says, in each fixture; both pass or both fail; the same codes when the
  script prints them). Code: `src/l4/yolo/preflight.py` (`Problem`, `problems`). The script is not edited. Run: that
  file.

- [x] 2.2 (I2) The refactors `go` calls. Tests first: `tests/unit/yolo/test_yolo_commands_activate.py`:
  `test_the_activation_blocker_names_another_active_plan_and_a_missing_target` (calls
  `commands._activation_blocker` directly; the texts are today's refusals without `activate: `); every existing test of
  that file still passes. `tests/unit/state/test_retry.py`: `test_start_run_result_gives_the_answer_and_the_line`
  (each forge answer, and `unavailable` for `ForgeUnavailable`; `start_run_line` returns the same lines as before).
  Code: `_activation_blocker` (called by `run_activate`), `l4.state.retry.start_run_result` (called by
  `start_run_line`). Run: both files.

- [x] 2.3 (I1, after 2.1) Preflight in `go`. Tests first, `tests/unit/yolo/test_yolo_go_preflight.py`:
  `test_a_dirty_tree_stops_at_preflight_before_any_fetch` (SCN-YOLO-202: `_sync` monkeypatched to raise; exit 20;
  `Next: git status`; the ref unchanged); `test_an_untracked_unit_file_stops_go` (SCN-YOLO-203, command level);
  `test_no_origin_is_a_preflight_stop`. Code: the preflight step of `run_go`. Run: that file.

## 3. Push (L4-YOLO-082)

- [x] 3.1 (I1) Tests first, new `tests/unit/yolo/test_yolo_go_push.py` (the "No model" patches and a reviewed READY plan
  so the run reaches the end): `test_nothing_ahead_pushes_nothing` (`push: ok`); `test_commits_ahead_are_pushed_as_a_fast_forward`
  (SCN-YOLO-205: two local commits; `origin/main` equals HEAD after; spy `l4.yolo.go._push` and assert its argv has no
  `--force` or `--force-with-lease`; the fake forge is not called); `test_no_push_stops_with_the_push_command`
  (SCN-YOLO-206, both halves); `test_a_diverged_base_is_never_forced` (SCN-YOLO-207: `world.push(...)` after the local
  commit); `test_only_the_base_branch_is_pushed` (SCN-YOLO-208: `git switch -c feature`);
  `test_the_worktree_admission_runs_before_the_push` (SCN-YOLO-209: a local commit adds a spec folder no plan lists;
  exit 22; `origin/main` unchanged); `test_a_push_that_would_stop_the_active_plan_is_not_made` (SCN-YOLO-212: seed
  `plan.activated`; a local commit changes B's `spec.md`; exit 21); `test_a_stopped_inputs_changed_plan_is_pushed`
  (the guard does not apply); `test_a_refused_push_names_gits_reason` (a pre-receive hook on the bare origin that exits
  1; exit 21; the hook's text in the detail). Code: the push step of D4 (`_push` runs the git push). Run: that file.

- [x] 3.2 (I1) The agent's hand-off scope. Tests first (same file): `test_an_agents_push_outside_the_hand_off_is_a_persons`
  (SCN-YOLO-210: `agent(world, monkeypatch)`; a local commit changes `.l4/config.yaml`; exit 27; the push step
  `person`; `Next: a person runs: git push origin main`); `test_an_agent_pushes_the_plan_file_and_its_unit_folders`
  (SCN-YOLO-211); `test_an_agents_push_of_another_plans_file_is_a_persons`. Code: the scope rule of D12 in the push
  step. Run: that file.

## 4. Check and review (L4-YOLO-083, L4-YOLO-084)

- [x] 4.1 (I1) Check and the plan's state. Tests first, new `tests/unit/yolo/test_yolo_go_check.py`:
  `test_a_plan_not_admitted_stops_at_check` (SCN-YOLO-213: `plan_doc({A: [B], B: [A]})`);
  `test_an_active_plan_is_reported_as_active` (SCN-YOLO-214: two runs; the ref head unchanged; statuses of D5.1;
  completed → `Next: l4 yolo report p1`); `test_cancelled_and_limit_stops_stop_at_check` (SCN-YOLO-215);
  `test_a_rejected_unit_with_an_unchanged_spec_stops_at_check`. Code: D5 in `_gather` and `decide`'s callers. Run:
  that file.

- [x] 4.2 (I1) Review: reuse and `--local`. Tests first, new `tests/unit/yolo/test_yolo_go_review.py`:
  `test_a_current_review_is_reused` (SCN-YOLO-216: "No model" and a fake forge that fails the test);
  `test_local_reviews_here` (SCN-YOLO-220 positive: the judge fake of `test_yolo_commands_activate.py`'s
  `fake_judge` answering READY; `plan.reviewed{source: local}`; exit 0);
  `test_local_with_a_judge_that_cannot_run_stops_with_25` (raises `RoleUnavailable`; `Next: l4 yolo go p1 --reason R`;
  nothing recorded); `test_a_covering_force_acceptance_skips_the_review` (seed `plan.force_accepted` as force-accept's
  tests do). Code: D6.1 to D6.4. Run: that file.

- [ ] 4.3 (I1) Review in CI with a bounded wait. Tests first (same file), with the fake forge and the fake CI:
  `test_ci_is_asked_and_awaited` (SCN-YOLO-217: the forge answers `started`, called once; the review seeded at the
  second `_sleep`; review `done`); `test_after_its_own_push_go_does_not_ask_the_forge` (a local commit is pushed; the
  fake forge's list stays empty); `test_a_skip_ci_head_asks_the_forge` (the pushed head's message has `[skip ci]`);
  `test_the_wait_is_bounded` (SCN-YOLO-218: `--wait 1m`, nothing seeded; exit 24; at most five reads of the plan ref;
  `review: pending`; next `l4 yolo go p1 --reason R --wait 1m`); `test_wait_zero_asks_and_returns` (`_sleep` never
  called); `test_no_run_can_be_asked` (SCN-YOLO-219: `unsupported`; exit 24 at once; next is `how_to_start`'s
  command); `test_a_ci_refusal_during_the_wait_is_not_admitted` (SCN-YOLO-221); `test_each_poll_checks_for_a_cancel`
  (`l4.cancel.request()` inside the fake CI; the run ends with exit 16 and records nothing). Code: D6.5 (`_sleep`,
  `_clock`, `POLL_S`, the progress lines). Run: that file.

## 5. Findings and acceptance (L4-YOLO-085)

- [ ] 5.1 (I1) Findings and `--accept-findings`. Tests first, new `tests/unit/yolo/test_yolo_go_accept.py`:
  `test_a_subject_not_ready_stops_at_findings` (SCN-YOLO-222: `two_rounds` for B; exit 26; B's line; next
  `--accept-findings`; the BLOCKED variant's next `l4 yolo findings p1` and the `--force` hint);
  `test_accept_findings_accepts_each_subject_and_activates` (SCN-YOLO-223: A and B each on two rounds; the `person`
  fixture records prompts; capture stdout writes and prompt calls in one ordered list and assert each subject's
  findings come before its prompt; two `plan.accepted{confirmed: "typed"}`; `plan.activated{accepted}` has both;
  the `--yes` variant: no prompt, `confirmed: "--yes"`); `test_one_subject_that_cannot_be_accepted_means_none_is`
  (SCN-YOLO-224); `test_a_wrong_answer_stops_with_29` (the person types `yes` at the second prompt; A's acceptance stays
  recorded; exit 29). Code: D7.1, D7.2, D7.4. Run: that file and `tests/unit/yolo/test_yolo_commands_accept.py`.

- [ ] 5.2 (I1) `--force`. Tests first (same file): `test_force_accepts_without_a_review_and_activates` (SCN-YOLO-225:
  "No model" patches and a fake forge whose list may hold only the activation's run; `plan.admitted`,
  `plan.force_accepted`, `plan.activated{review: "force_accepted"}`; review `skipped`);
  `test_force_from_an_agent_stops_before_anything` (SCN-YOLO-226: `_sync` monkeypatched to raise; exit 27; accept
  `person`; the person's command with `--force`); `test_force_on_a_ready_review_forces_nothing` (accept `skipped`, no
  `plan.force_accepted`, activated). Code: D7.3 and the `--force` agent rule of D1. Run: that file.

## 6. Activation and agents (L4-YOLO-086, L4-YOLO-090)

- [ ] 6.1 (I1) Tests first, `tests/unit/yolo/test_yolo_go_activate.py`:
  `test_an_agent_stops_at_the_activation_with_the_persons_command` (SCN-YOLO-227: `agent(world, monkeypatch)`; exit 27;
  activate `person`; `Next: a person runs: l4 yolo go p1 --reason 'ship it'`; no `plan.activated`);
  `test_an_agent_is_told_the_activation_would_be_refused` (SCN-YOLO-228: a second plan `p2` with its own units seeded
  `plan.activated`; exit 28); `test_a_persons_run_activates_with_the_reason_and_no_prompt` (SCN-YOLO-229: a holding
  acceptance of B seeded as `test_yolo_commands_activate.py` does; accept `ok`); `test_an_agent_goes_as_far_as_it_may`
  (SCN-YOLO-236: push `.l4/config.yaml` with `yolo: {review: {accept_by_agents: true}}`; the three runs of the
  scenario; `click.prompt` fails the test if called). Code: D8 (with `_activation_blocker`), D12's agent rules. Run:
  that file.

## 7. Output contract and re-run safety (L4-YOLO-087, -088, -089)

- [ ] 7.1 (I1) Tests first, new `tests/unit/yolo/test_yolo_go_output.py`: `test_each_stop_has_its_own_code_and_one_next_line`
  (SCN-YOLO-230: one parametrised world per row of D9, reusing the set-ups of tasks 2 to 6; reason `"a b"`);
  `test_the_json_document_is_the_only_thing_on_stdout` (SCN-YOLO-231: `json.loads(capsys.readouterr().out)` succeeds and
  the keys are exactly D10's; the stderr holds B's findings and the prompt text);
  `test_a_refusals_fix_line_is_the_next_command` (an `L4Exit` with `…\nFix: l4 yolo review p1` from a monkeypatched
  `run_activate` → exit 28 and `Next: l4 yolo review p1`; without a `Fix:` line → the go command);
  `test_relayed_output_drops_next_lines_and_keeps_the_rest`. Code: D9 and D10 rendering. Run: that file.

- [ ] 7.2 (I1) Tests first, new `tests/unit/yolo/test_yolo_go_rerun.py`: `test_a_second_run_with_nothing_changed_does_nothing`
  (SCN-YOLO-232: the ref head, `origin/main`, the fake forge's list and the "No model" patches checked after the second
  run); `test_an_interrupted_accept_goes_on` (SCN-YOLO-233 first part: monkeypatch `l4.yolo.commands.run_accept` to
  raise `RunCancelled` on its second call, then restore and run again); `test_an_interrupted_wait_goes_on`
  (SCN-YOLO-233 second part: the fake CI raises `RunCancelled` on its first call; seed the review; run again);
  `test_a_lost_lease_reads_again_and_records_nothing_twice` (SCN-YOLO-234: `PlanStore.append` patched so that its first
  call seeds B's acceptance through `world.seed` and then raises `PlanMoved`, later calls append);
  `test_a_lease_lost_again_and_again_stops_with_28` (SCN-YOLO-235: every append raises `PlanMoved`; exactly four
  activation attempts; nothing recorded); `test_no_progress_stops_with_28` (a `run_review` patched to record nothing:
  the guard of D2). Code: D11 (`MAX_MOVED`, the re-read on `commands._MOVED`), the guard of D2. Run: that file and
  every `tests/unit/yolo/test_yolo_go_*.py`.

## 8. MCP (L4-YOLO-090)

- [ ] 8.1 (I2) Tests first, `tests/unit/mcp/test_tools.py`: `test_plan_go_runs_go_read_mostly` (SCN-YOLO-237: the argv of
  D12 exactly; the schema's properties are `repo`, `plan`, `reason`, `wait`; the description says it never pushes,
  accepts or activates and that it may cost judge tokens); update `test_the_full_tool_list_and_no_activation` (adds
  `l4_plan_go`; no tool's words start with `("yolo", "activate")` or `("yolo", "accept")`) and
  `test_write_tools_say_what_they_write_and_the_review_says_it_costs`. Code: `l4_plan_go` in `src/l4/mcp/tools.py`.
  Run: `tests/unit/mcp`.

## 9. Docs, SPEC, CHANGELOG (L4-YOLO-091)

- [ ] 9.1 (I2) Tests first, new `tests/unit/docs/test_yolo_go_docs.py` on the model of `test_plan_run_lessons_docs.py`:
  `test_the_spec_has_the_twelve_requirements_and_their_scenarios_in_order` (`**L4-YOLO-080 ` to `**L4-YOLO-091 ` after
  the last earlier L4-YOLO requirement; `#### SCN-YOLO-200 ` to `#### SCN-YOLO-238 ` in 23.20 before `### 23.21`;
  `| 55 | \`yolo-go\` |`); `test_the_spec_names_the_cli_row_the_exit_codes_and_the_mcp_tool` (the CLI row
  `` `l4 yolo go PLAN --reason TEXT `` ; L4-CLI-001 names `20 to 29` and `l4 yolo go`; L4-MCP-003 names `l4_plan_go`);
  `test_the_yolo_doc_has_the_section` (SCN-YOLO-238: the heading, each code 20..29, `l4/yolo-go@1`, `l4 yolo status`
  as the read-only view); `test_the_runbook_starts_12_2_with_or_simply`; `test_the_skill_teaches_go_to_persons_and_agents`
  (`operate.md`: `or simply: l4 yolo go`, `--wait`, `next_command`, never `--force`; `plan.md`: `l4 yolo go`);
  `test_the_changelog_names_go_in_0_4_19` (the section `## 0.4.19 (unreleased)` exists above `## 0.4.18` and names
  `l4 yolo go` and `l4_plan_go`; its lists have no blank line between items). Code: the edits of D13 in
  `docs/yolo-mode.md`, `docs/runbook.md`, `plugins/l4/skills/l4/references/operate.md` and `plan.md`, `CHANGELOG.md`,
  `docs/SPEC.md` (each scenario `#### SCN-YOLO-NNN (+|−) Title · L4-YOLO-0NN` with **Given**/**When**/**Then**; the
  texts of the requirements are the `### Requirement:` texts of this change's specs). Run: that file, `tests/unit/docs`,
  `.venv/bin/python scripts/check_spec.py docs/SPEC.md` (clean) and `openspec validate yolo-go --strict`.

## 10. Close

- [ ] 10.1 (orchestrator) Run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/yolo tests/unit/mcp
  tests/unit/docs tests/unit/cli tests/unit/state`, then `ruff check`, `ruff format --check` and `mypy` on every changed
  file, and `openspec validate yolo-go --strict`. A live check on the GitHub test repository: a person's
  `l4 yolo go <plan> --reason "…"` from a committed, unpushed plan to `active` (the CI review awaited), then the same
  command again (exit 0, nothing recorded), with the output kept under `docs/live/yolo-go/`.
