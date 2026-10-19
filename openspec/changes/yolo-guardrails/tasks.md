Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, key and signature is in `design.md` (D1 to D11
  and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree, with its own `.venv`. Never change git configuration. Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `yolo-guardrails A<n>: …` or
  `yolo-guardrails B<n>: …`, with no trailer and no local path.
- Never wait on a process with `while pgrep …` (it matches itself), and never write a loop that waits on a process
  name. Run commands in the foreground with a timeout. A test that starts a background process kills it in a
  `finally` (it writes its pid to a file under `tmp_path`).
- Name a consumer repository only as "a consumer repository". Put no local path in docs or fixtures.
- Two implementers work in sequence: group A (sections 1 to 3), then group B (sections 4 to 9), on top of A's commits.

Test worlds: `tests/unit/yolo/yolo_cmd_world.py` (`world`, `A` = `openspec:add-greeting`, `B` = `openspec:add-b`,
batch `b1`, `plan_doc`, `ev`, `world.push`, `world.push_plan`, `world.pull`, `world.reviewed`, `world.seed`,
`world.l4`, `world.clone`); `tests/unit/yolo/test_yolo_review_worktree.py` (`ready_world`, `judge`, `answer`,
`commit_edit`, `edit_spec`, `SPEC_FILE`, `FOLDER_A`); `tests/unit/yolo/yolo_cycle_world.py` (`CycleWorld`,
`push_main`, `commit`, `unit_branch`, `activate`, `step`).

## 1. Group A: the OpenCode major gate joins 0.4.18 (design D7; L4-OCG-001..004)

- [x] 1.1 Cherry-pick. The commit that added this change already holds `openspec/changes/opencode-major-gate/` at its
  spec commit. Run `git cherry-pick b91df9ac b4a05956`. A trial on this base applied both without conflict. If one
  conflicts anyway, resolve it toward the cherry-picked side and keep every hunk of this branch. Then, in one more
  commit (`yolo-guardrails A1: the OpenCode major gate joins 0.4.18`):
  - Move every line of `CHANGELOG.md`'s `## 0.4.20 (unreleased)` into `## 0.4.18 (unreleased)`: its `### Changed` lines
    to the end of that section's `### Changed`, its `### Fixed` lines to the end of `### Fixed`. Delete the heading
    `## 0.4.20 (unreleased)` and its empty subsections. Leave no blank line between list items.
  - In `openspec/changes/opencode-major-gate/proposal.md` (the CHANGELOG line) and `tasks.md` (task 2.4's CHANGELOG
    bullet), replace `0.4.20` with `0.4.18`. Change nothing else in that change.
  Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/test_versions_major.py tests/unit/availability
  tests/unit/agents/test_opencode.py tests/unit/agents/test_opencode_key.py tests/unit/agents/test_opencode_provider.py
  tests/unit/agents/test_login_lock_coverage.py tests/unit/doctor tests/unit/provision tests/unit/runner
  tests/unit/test_recorded_versions.py tests/unit/docs`, `scripts/check_spec.py docs/SPEC.md` and
  `openspec validate opencode-major-gate --strict`.
  Done when all pass and `git log --oneline -3` shows the two cherry-picks and this commit.

- [x] 1.2 The two review fixes (D7). Tests first, `tests/unit/provision/test_install.py`:
  - `test_the_link_guard_runs_on_python_3_11`: monkeypatch `pathlib.Path.exists` with a function that takes only
    `self` and calls the real one (the 3.11 signature). Write a regular file `keep` under `paths.local_bin`. Assert that
    `_link(target, keep, replace_files=False)` raises `InstallFailed` matching `keep` (it raises `TypeError` today),
    that the file is unchanged, and that `_link(target, other_link)` with `replace_files` left at its default still
    replaces a regular file.
  - Replace `test_a_regular_file_at_the_node_link_is_still_replaced` with
    `test_a_regular_file_at_the_node_link_is_replaced_by_the_node_install`. Build it like
    `test_a_too_old_system_node_is_left_alone_and_extraction_is_atomic`: write a regular file at
    `paths.local_bin / "node"`, run `install(...)` with the fakes, and assert the Node action is `applied` and the path is
    a symlink that resolves to `paths.l4_home / "node" / "bin" / "node"`. It passes before the fix: it is the scoped
    guard's regression test through the real call.
  Code: `src/l4/provision/install.py` `_link`: `if not replace_files and not link.is_symlink() and link.exists():`.
  Run: `tests/unit/provision`. Commit `yolo-guardrails A2: …`.

## 2. Group A: probes never hang (design D8; L4-AVL-012)

- [x] 2.1 `run_process`, bounded. Tests first, in a new file `tests/unit/test_run_process.py`. Each test uses small
  Python child scripts run by `sys.executable` and a pid file:
  - `test_a_helper_in_its_own_session_holding_stdout_does_not_hang` (SCN-AVL-21): the child prints `1.18.34`, starts a
    grandchild with `start_new_session=True` that inherits stdout and sleeps 60 s, and exits 0. `run_process(...,
    timeout=10)` returns within 4 s with `(0, "1.18.34\n")`. The test kills the grandchild in `finally`. Today it waits
    the full 10 s and then hangs; guard the test itself with `pytest.mark.timeout` if the plugin is there, else run
    the call in a thread joined with 20 s and fail if it is still alive.
  - `test_a_timeout_with_an_escaped_helper_still_returns`: the same grandchild, but the child sleeps 60 s. With
    `timeout=1` it returns `CmdResult(124, "", "timed out")` within 1 + 2 + 1 s.
  - `test_a_helper_in_the_group_holding_the_pipe_is_killed_after_the_grace`: the grandchild is in the same group. The
    call returns within the grace, and the grandchild is gone (`os.kill(pid, 0)` raises `ProcessLookupError` within
    1 s after the return).
  - `test_a_normal_exit_leaves_a_background_process_with_closed_output_alone`: the grandchild redirects its stdio to
    `/dev/null` and sleeps 5 s. The call returns at the child's exit, and the grandchild is still alive (killed by the
    test).
  - `test_output_past_the_cap_is_dropped`: with `MAX_STREAM_BYTES` monkeypatched to 1000, a child that prints 5000
    bytes gives 1000 characters and exit 0.
  The existing `tests/unit/agents/test_proc.py::test_run_process_timeout_kills_the_whole_group` and the
  `run_process` tests of `tests/unit/specs/test_openspec_cli.py` must still pass.
  Code: `src/l4/proc.py` (D8: `EOF_GRACE_S`, `MAX_STREAM_BYTES`, the selectors loop, the group kill on (b) and (c),
  the bounded wait, closing the read ends). Run: `tests/unit/test_run_process.py tests/unit/agents/test_proc.py
  tests/unit/specs/test_openspec_cli.py tests/unit/provision`.

- [x] 2.2 The step timeout and the named reason. Tests first:
  - `tests/unit/config/test_schema.py`: `test_probe_step_timeout_defaults_to_20s` (`L4Config().availability.
    probe_step_timeout == "20s"`, and `"probe_step_timeout"` is in `fallback`'s `timing` set: a change of it does not
    change a probe cache identity).
  - New `tests/unit/availability/test_probe_step_timeout.py`:
    `test_every_non_hello_step_gets_the_step_timeout` (SCN-AVL-25): a fake runner records the `timeout` argument. For
    each of the claude, codex (with a fake `rpc` that records its timeout), opencode and kiro-cli probes, `binary`,
    `auth` and `quota` get 5 with `ProbeCtx(timeout_s=60, step_timeout_s=5)`, the hello gets 60, and with
    `step_timeout_s=90` every call gets at most 60.
    `test_a_step_that_times_out_is_named` (SCN-AVL-22 with a fake runner): an opencode `auth list` that returns
    `CmdResult(124, "", "timed out")` gives, through `ProbeLadder.run`, an `auth` step with `ok False`,
    `failure_class == "transient"` and the reason `opencode did not answer within 5 s (auth step); an OpenCode v2 daemon
    or a login prompt can cause this: run l4 doctor`. The `hello` never runs.
    `test_a_binary_step_that_times_out_is_named`: claude `--version` returns 124; the reason is the claude text with
    `(binary step)`, not `did not report a version`.
    `test_a_codex_rpc_that_answers_nothing_in_time_is_named`: a fake `rpc` that sleeps past a 0.2 s step timeout and
    returns `{}`; the `auth` step's reason starts `codex did not answer within`.
    `test_a_hello_that_times_out_is_named` (SCN-AVL-23): claude, codex, opencode, kiro-cli and the `command` adapter.
    `test_the_real_runner_names_a_hanging_cli` (SCN-AVL-22, end to end): an executable `opencode` script in `tmp_path`
    on PATH answers `--version` with `1.18.34`, and `auth list` with a same-group child and a 60 s sleep. With
    `run=run_process` and `step_timeout_s=2`, the ladder's `auth` step fails with the reason within 6 s, and the child
    pid is gone.
  - Update to the new hello text: `tests/unit/availability/test_probes_opencode.py` (the `slow.reason == "timeout"`
    assertion) and `tests/unit/availability/test_probes_command.py` (the same).
  - `tests/unit/provision/test_readiness.py`: `test_a_binary_step_that_times_out_is_missing_with_the_reason` and
    `test_an_auth_step_that_times_out_is_not_authenticated_with_the_reason`.
  Code: `src/l4/config/schema.py` (`AvailabilityCfg.probe_step_timeout`), `src/l4/agents/base.py`
  (`ProbeCtx.step_timeout_s`), `src/l4/agents/factory.py` (sets it), `src/l4/availability/fallback.py` (`timing`),
  `src/l4/availability/probes.py` (`StepTimedOut`, `step_seconds`, `timeout_reason`, `step_run`, `_binary`, the claude
  `auth status`, `_codex_auth`, `_hello_verdict(timeout_text=…)`, `ProbeLadder.run`), `src/l4/availability/quota.py`
  (claude and kiro `/usage`, codex quota's rpc timeout and empty answer, openrouter's client timeout),
  `src/l4/agents/opencode.py` (`auth list`, the hello text), `src/l4/agents/kiro_cli.py` (`whoami`, the hello text),
  `src/l4/agents/command.py` (the hello text), `src/l4/provision/readiness.py`. Look for every `ctx.timeout_s` in
  `src/l4/availability` and `src/l4/agents`: each non-hello use moves to `step_seconds(ctx)`. Run:
  `tests/unit/availability tests/unit/agents tests/unit/provision tests/unit/config tests/unit/doctor`.

- [x] 2.3 `ProcRunner`, bounded. Tests first, `tests/unit/agents/test_proc.py`:
  `test_an_escaped_helper_holding_stdout_does_not_hang_the_run` (SCN-AVL-24): the agent starts a grandchild with
  `start_new_session=True` that holds stdout and sleeps 60 s, then exits. `ProcRunner().run(...)` returns within
  5 + 5 + 2 s with the agent's return code and logs the D8 warning (caplog). The test kills the grandchild. The existing
  `test_a_grandchild_holding_stdout_open_cannot_leave_the_file_unfinished` must still pass. Code: `src/l4/agents/proc.py`
  (`JOIN_AFTER_KILL_S`, the bounded joins, the warning). Run: `tests/unit/agents/test_proc.py tests/unit/agents`.

## 3. Group A: docs (L4-AVL-012)

- [x] 3.1 Tests first, new `tests/unit/docs/test_yolo_guardrails_docs.py`, part A, on the model of
  `tests/unit/docs/test_plan_run_lessons_docs.py`:
  `test_the_spec_has_the_probe_requirement_and_its_scenarios` (`**L4-AVL-012 ` after `**L4-AVL-011 `;
  `#### SCN-AVL-21 ` to `#### SCN-AVL-25 ` in order after `#### SCN-AVL-20 `; `probe_step_timeout` in the §3.2
  configuration sample);
  `test_the_changelog_has_the_gate_and_the_probe_fix_under_0_4_18` (in `## 0.4.18 (unreleased)`:
  `probe_step_timeout`, `did not answer within`, `OpenCode v2`, `unsupported_version`; no `## 0.4.20 (unreleased)`
  heading);
  `test_the_runbook_names_the_probe_timeout` (runbook 7.4 holds `did not answer within` and `l4 doctor`).
  Code: `docs/SPEC.md` (L4-AVL-012 with the requirement text of `specs/probe-bounds/spec.md`, SCN-AVL-21..25 in the
  Part II form `#### SCN-AVL-NN (+|−) Title · L4-AVL-012` with **Given**/**When**/**Then**, the §3.2 key
  `probe_step_timeout: 20s` with a comment, the §8.4 `binary`/`auth`/`quota` rows), `docs/runbook.md` 7.4,
  `CHANGELOG.md` (Added: `availability.probe_step_timeout`; Fixed: a probe no longer hangs on a helper that holds its
  output, a step that times out names the CLI, the seconds, the cause and `l4 doctor`, an agent run ends when an
  escaped helper holds its output). Run: that file, `tests/unit/docs`, `scripts/check_spec.py docs/SPEC.md`.
  Then the whole of group A once: `tests/unit/availability tests/unit/agents tests/unit/provision tests/unit/doctor
  tests/unit/config tests/unit/runner tests/unit/docs tests/unit/test_run_process.py tests/unit/test_versions_major.py`.
  Commit.

## 4. Group B: judge roles at load (design D6; L4-CFG-006)

- [ ] 4.1 Tests first:
  - New `tests/unit/config/test_judge_roles.py`:
    `test_a_kiro_cli_judge_fails_at_load_by_name` (SCN-CFG-05: `load_config_text` raises `ConfigSchemaError` whose text
    equals the D6 message for `kiro`/`judges` plus ` at $`);
    `test_every_judge_role_is_checked` (SCN-CFG-06: `verifier_agent` with a `command` profile, `clarifier` and
    `s1_judge` with `kiro-cli`, and `judges` with `mystery-cli`: that message holds `(not one the harness knows)` and
    not `mystery-cli`);
    `test_backend_profiles_allowed_adapters_and_undefined_names_load` (SCN-CFG-07);
    `test_the_constants_are_one` (`l4.llm.agent_judge.JUDGE_ADAPTERS is l4.config.roles.JUDGE_ADAPTERS`,
    `set(HARNESS_ADAPTERS) == set(l4.agents.factory.ADAPTERS)`, and `l4.config.roles` imports nothing from `l4`,
    checked with `ast`).
  - `tests/unit/doctor/test_doctor_load_errors.py` (new, or the file that already tests a schema error in `l4 doctor`
    if there is one): `test_doctor_exits_2_with_the_judge_role_text` (SCN-CFG-05, through `l4.cli.main(["doctor",
    "--repo", …])` on a repo whose config has the kiro judge: exit 2, the text on stderr).
  - Update, since that configuration now fails at load:
    `tests/unit/llm/test_agent_judge_roles.py::test_a_profile_that_cannot_serve_a_toolless_call_is_unavailable_not_a_usage_error`
    keeps only the `api` parameter. Add `test_a_kiro_cli_s1_judge_is_a_load_error` beside it.
    `tests/unit/clarifier/test_hook.py::test_a_clarifier_profile_that_cannot_run_tool_less_goes_to_a_human_before_any_call`
    uses `{"backend": "openai-chat", "model": "x"}` for `kirox` instead of `kiro-cli`, so the runtime path stays
    covered: it is still `tool-less`.
  Code: new `src/l4/config/roles.py`, `src/l4/llm/agent_judge.py` (`from l4.config.roles import JUDGE_ADAPTERS`; delete
  its tuple), `src/l4/config/schema.py` (`_judge_roles_can_judge`). Then run the whole suite once
  (`.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit -x`): any other test or fixture that puts a non-judge
  adapter in a judge role fails now. Fix the fixture (use an allowed adapter or a backend) unless the test is about that
  case; list each one in the commit message. Run: the files above, `tests/unit/config tests/unit/llm
  tests/unit/clarifier tests/unit/verifier tests/unit/doctor`. Commit `yolo-guardrails B1: …`.

## 5. Group B: what a review read, and the staleness module (design D1, D2; L4-YOLO-068)

- [x] 5.1 Tests first, new `tests/unit/yolo/test_yolo_staleness.py`, on a scratch git repository (`tmp_path`, `git
  init`, a bare `origin`, commits with fixed author env):
  - `file_digests`: a folder with `tasks.md`, `spec.md`, `verification.md`, `.l4/x`: the keys leave out the harness
    files, and a check-mark change gives the same value for `tasks.md`; `unit_digest` of every existing digest test
    still gives the same value (`tests/unit/yolo/test_yolo_digest*.py` unchanged and passing).
  - `changed_files`: added, removed and changed files, sorted and relative to the repository; a tick-only change gives
    `[]`; an unknown `old_rev` gives None.
  - `divergence` and the texts: ahead 2 (with paths and with none), behind 1, diverged 1/1, equal (None), and the exact
    `divergence_text`, `divergence_verb` and `divergence_fix` of D1, the plurals and the `and <k> more` cut included.
  - `unit_change` and `plan_change`: each `label`, `<where>` on the target and on a unit branch, `MISSING`, with and
    without files.
  - `stale_reasons`: the five causes of D1 in order, and [] for a current review.
  - `unit_revs` and `frozen_rev`.
  Code: `src/l4/yolo/digest.py` (`_entries`, `file_digests`; `unit_digest` uses `_entries`), new
  `src/l4/yolo/staleness.py`. Run: that file and `tests/unit/yolo/test_yolo_digest*.py`.

- [ ] 5.2 Every review records what it read (SCN-YOLO-183). Tests first:
  `tests/unit/yolo/test_yolo_staleness_messages.py` (new; it uses the `world` of `yolo_cmd_world.py`):
  `test_a_local_review_records_target_rev_and_unit_revs`; `tests/unit/yolo/test_yolo_review_worktree.py`:
  `test_record_writes_target_rev_and_unit_revs` (after the push of 7.1's helper; write it in 7.1 if that helper is not
  there yet); `tests/unit/yolo/test_yolo_cycle_review.py`: `test_the_ci_review_records_target_rev_and_unit_revs` (the
  sha of `origin/main` and, for a unit with a branch, the branch's sha). Code: `commands.run_review` (`--local`),
  `review_worktree.run_review_worktree`, `cycle._review` (two keys on the event). Run: the three files.

## 6. Group B: the messages (design D1: M1 to M5, M11 to M13)

- [ ] 6.1 Activate, status and the CI review (M1 to M4). Tests first, `tests/unit/yolo/test_yolo_staleness_messages.py`:
  `test_a_stale_activation_names_the_spec_its_digests_and_files` (SCN-YOLO-177), `…_the_plan_file` (SCN-YOLO-178),
  `…_an_unpushed_commit_and_the_push` (SCN-YOLO-179), `test_status_shows_the_same_causes` (SCN-YOLO-180, text and
  JSON, and no `review.stale` key for a current review), `test_a_prompt_change_names_both_versions` (SCN-YOLO-181),
  `test_an_older_review_without_revisions_names_no_file` (SCN-YOLO-183, second half),
  `test_review_names_the_stale_causes_before_it_asks_ci` (M4). `world.push` commits in a second clone and leaves
  `world.clone` behind `origin/main`: build the commits of SCN-YOLO-179 in `world.clone` after `world.pull()`, and push
  the first one with `world.clone.run("push", "-q", "origin", "HEAD:main")`. Update the old texts:
  `tests/unit/yolo/test_yolo_commands_activate.py` lines asserting `review is for other inputs` (two) and
  `tests/unit/yolo/test_yolo_review7_prompt.py` (`older review prompt: run l4 yolo review p1`) now assert the M1 header
  and the prompt line. `tests/unit/yolo/test_yolo_commands_manage.py`'s `review: stale (the review prompt changed)`
  stays true. Code: `commands.run_activate` (only the body of `if view.kind == "stale":`), `_describe` (`review.stale`),
  `_render` (the lines under `review:`), `run_review`'s CI path. Each calls `staleness.stale_reasons` when
  `view.kind == "stale"`. Do not change `_review_view` or `ReviewView`. Run: the three files and
  `tests/unit/yolo/test_yolo_status_activity.py`.

- [ ] 6.2 The plan file that is not on origin (M5, SCN-YOLO-182). Tests first, same new file:
  `test_a_plan_file_only_in_head_says_push`, `test_a_plan_file_only_in_the_working_tree_says_commit_and_push`,
  `test_no_plan_file_anywhere_keeps_the_old_text` (only ` (<sha7>)` is added). Code: `commands._file`. Run: that file,
  `tests/unit/yolo/test_yolo_commands_activate.py`, `tests/unit/yolo/test_yolo_check_worktree.py`.

- [ ] 6.3 The stop details (M11 to M13, SCN-YOLO-184). Tests first, `tests/unit/yolo/test_yolo_cycle_active.py` (or a
  new `tests/unit/yolo/test_yolo_cycle_stop_details.py` with `CycleWorld`):
  `test_a_spec_change_after_the_activation_is_named_in_the_stop_detail` (a review event seeded with `unit_revs`, the
  activation, a pushed change of `spec.md`: the detail is the M12 text with `changed:`),
  `test_a_plan_file_change_after_the_activation_names_both_digests` (M11),
  `test_a_fixed_rejected_spec_names_the_digests` (M13), `test_without_unit_revs_the_detail_names_no_file`.
  `tests/unit/yolo/test_yolo_review_y1.py`'s `"changed after the activation" in …` must still pass (prefix). Code:
  `cycle._live`, `cycle._file_changed`, `cycle._rejected_fixed`. Run: those files and
  `tests/unit/yolo/test_yolo_cycle*.py`. Commit `yolo-guardrails B<n>: …` after 6.3.

## 7. Group B: --record reviews what origin holds; the CI review warns (design D3, D4; L4-YOLO-069, -070)

- [ ] 7.1 Tests first, new `tests/unit/yolo/test_yolo_record_origin.py` (the worlds and helpers of
  `test_yolo_review_worktree.py`; add a helper `push_edit(world)` = `commit_edit(world)` then
  `world.clone.run("push", "-q", "origin", "HEAD:main")`):
  `test_a_record_with_head_ahead_is_refused_before_any_judge_call` (SCN-YOLO-185: `judge(monkeypatch)` with no answer,
  exact lines, no event), `test_a_record_with_head_behind_names_the_pull` and `test_a_diverged_record_names_both`
  (SCN-YOLO-186), `test_a_record_refuses_a_unit_whose_branch_holds_another_spec` and
  `test_a_branch_that_differs_only_in_check_marks_is_not_refused` (SCN-YOLO-187),
  `test_a_record_at_origin_names_the_next_step` (SCN-YOLO-188, both `Next:` lines),
  `test_the_dry_run_is_not_refused_before_the_push` (SCN-YOLO-189, with the M9 line).
  Update `tests/unit/yolo/test_yolo_review_worktree.py`: every `--record` test that commits an edit and expects exit
  0, or a refusal other than the uncommitted one, pushes first (`push_edit`). `test_record_writes_the_events_ci_would`
  now asserts the M8 line (`Next: a person runs l4 yolo activate p1 --reason TEXT`). The uncommitted-path test asserts
  the M10 line. `test_scn_yolo_58_a_recorded_review_of_the_commit_spares_the_ci_review` pushes `edit a`
  (`world.push_main()`) before `--record`, then steps CI: no judge call and no new review, as before.
  Code: `review_worktree.run_review_worktree` (D3 checks 1 and 2 after the uncommitted check and before
  `worktree.snapshot`; M8, M9, M10). Run: the two files and `tests/unit/yolo/test_yolo_contract.py`.

- [ ] 7.2 The CI review warns (SCN-YOLO-190, -191). Tests first, `tests/unit/yolo/test_yolo_record_origin.py`:
  `test_the_ci_review_warns_about_an_unpushed_plan_commit`, `test_local_warns_too` (with `fake_judge` or the `judge`
  helper), `test_an_unrelated_unpushed_commit_gives_no_warning`, `test_head_behind_gives_no_warning` (exit codes
  unchanged). Code: `commands.run_review` (D4, before any other line). Run: that file and
  `tests/unit/yolo/test_yolo_commands_activate.py`. Commit.

## 8. Group B: `scripts/yolo_preflight.py` (design D10; L4-SKL-005)

- [ ] 8.1 Tests first, new `tests/unit/yolo/test_yolo_preflight_script.py`, on the model of
  `tests/unit/yolo/test_yolo_validate_plan.py`. It runs the script as `[sys.executable, "-I", SCRIPT, "p1", "--repo",
  …]` with a controlled `env`: `PATH` = a `tmp_path` bin folder plus the system git's folder, `HOME`, and the fixed git
  identity variables.
  - World: a bare `origin`, a clone with `.l4/config.yaml` (block style: `forge.base_branch: main`, profiles, roles),
    `.l4/plans/p1.json` and `openspec/changes/add-greeting/{proposal.md,tasks.md}`, pushed.
  - A fake `l4` in the bin folder (a Python script with a `#!` line) answers `--version`, `yolo check p1` (exit from a
    file), `yolo status p1 --json` and `yolo findings p1 --json` (documents from files the test writes). A fake
    `opencode` prints a version from a file. A fake `claude` exists or not.
  - Tests:
    `test_the_script_needs_only_the_standard_library` (ast, as validate_plan's test);
    `test_the_constants_equal_the_harness` (`JUDGE_ADAPTERS`, `JUDGE_ROLES`, `AGENT_MARKERS`, `OPENCODE_PIN`,
    `OPENCODE_MAJOR` against `l4.config.roles`, `l4.actor`, `l4.provision.catalog`);
    `test_a_pushed_admitted_plan_with_no_review_gets_the_review_command` (SCN-SKL-11, both review forms);
    `test_a_dirty_tree_fails_with_its_fix`, `test_an_unpushed_commit_fails_with_the_push` (SCN-SKL-12; the fake `l4`
    records its calls, and none is made);
    `test_a_kiro_cli_judge_fails_with_the_harness_text` (SCN-SKL-13: the detail equals the message that
    `l4.config.loader.load_config_text` raises for the same config, without ` at $`);
    `test_an_opencode_v2_fails` and `test_an_opencode_v1_passes_both_version_forms` (SCN-SKL-13);
    `test_an_agent_with_a_ready_review_hands_activation_to_a_person` and `test_a_person_is_told_to_activate`
    (SCN-SKL-14; `CLAUDECODE=1` in env; a person needs a terminal: run the person case in-process, loading the module
    with `importlib` and monkeypatching its `stdin_is_tty`);
    `test_a_subject_past_two_rounds_is_accepted_by_whoever_may` (SCN-SKL-15, both callers);
    `test_a_persistent_blocking_finding_goes_to_a_person`;
    `test_an_active_plan_prints_the_status_next_line`;
    `test_json_output` (schema, checks, next, exit; exit 1 on a FAIL);
    `test_a_hanging_opencode_is_bounded` (a fake `opencode` that sleeps 60 s: the check fails within 25 s);
    `test_a_bad_plan_id_is_a_usage_error` (exit 2).
  Code: `plugins/l4/skills/l4/scripts/yolo_preflight.py` (D10; the block-style reader copied from `validate_plan.py`,
  the bounded runner, the checks, the `Next:` rules, `--json`). `tests/unit/skills/test_skills_install.py`'s bundled
  tree test must still pass (the wheel carries the new file through `force-include`). Run: that file and
  `tests/unit/skills`. Commit.

## 9. Group B: the skill, the docs, SPEC and CHANGELOG (design D9, D11)

- [ ] 9.1 The skill. Tests first, `tests/unit/docs/test_yolo_guardrails_docs.py`, part B:
  `test_operate_starts_with_origin_then_the_runbook_and_the_table` (SCN-SKL-09: the section `## Delivering a plan: the
  runbook` is the first `## ` of `operate.md`; it holds `Origin is what counts`, `yolo_preflight.py`, the numbered
  steps `1.` to `10.`, `at most two rounds`, `A person activates`, and the table rows of D9);
  `test_every_command_of_the_runbook_exists` (resolve every `` `l4 …` `` span of that section with `_resolve` of
  `test_control_loop_agent_docs.py`, flags included. One tolerance: a span with `--force` on `yolo accept` while the
  CLI has no `--force` (force-accept not merged yet) is skipped, and the check counts how many it skipped; when
  `--force` exists, nothing is skipped);
  `test_the_skill_hands_a_persons_steps_to_a_person` (SCN-SKL-10: the new `SKILL.md` rule, its `Next:` and `stop`
  words, and the operate bullet that starts with `delivering a plan`).
  The existing skill tests must still pass: `test_review_resolution_docs.py`, `test_escalate_and_note_docs.py`,
  `test_unfreeze_and_answer_docs.py`, `test_plan_run_lessons_docs.py`, `test_run_liveness_docs.py`,
  `test_control_loop_agent_docs.py`, `test_adoption_docs.py`.
  Code: `plugins/l4/skills/l4/references/operate.md` (the new first section of D9, in the order given there; nothing
  else in the file changes), `plugins/l4/skills/l4/SKILL.md` (the rule after `**Check before acting.**`, and the start of
  the operate bullet), `plugins/l4/skills/l4/references/plan.md` (step 5 of "Check and fix the review" only).
  Run: `tests/unit/docs tests/unit/skills`.

- [ ] 9.2 Docs, SPEC, CHANGELOG. Tests first, the same docs file, part B:
  `test_the_spec_has_the_requirements_and_scenarios_in_order` (`**L4-YOLO-068 ` to `**L4-YOLO-070 ` after
  `**L4-YOLO-056 `; `#### SCN-YOLO-177 ` to `#### SCN-YOLO-191 ` in increasing order after `#### SCN-YOLO-149 ` and
  before `### 23.21`; `**L4-CFG-006 ` after `**L4-CFG-005 `; `#### SCN-CFG-05 ` to `07` after `#### SCN-CFG-04 `;
  `**L4-SKL-004 ` and `**L4-SKL-005 ` after `**L4-SKL-003 `; `#### SCN-SKL-09 ` to `15` after `#### SCN-SKL-08 `;
  `| 54 | \`yolo-guardrails\` |`; the `l4 yolo review` CLI row names `origin/<base>` for `--record`;
  SCN-YOLO-58's **Given** says the commit is pushed; `target_rev` and `unit_revs` are named);
  `test_the_yolo_doc_and_the_runbook_say_push_before_record` (`docs/yolo-mode.md` "The review" and runbook 12.2a:
  commit, push, then `--record`; the runbook 12.2 refusal list holds `is stale against origin/<base>`);
  `test_the_changelog_names_the_guardrails` (in `## 0.4.18 (unreleased)`: `yolo_preflight.py`, `target_rev`,
  `--record`, `cannot judge`, `warning:`).
  Code: `docs/SPEC.md` (D11; requirement texts from this change's `specs/*/spec.md`; scenarios in the Part II form;
  the new text of L4-YOLO-026's `--record` sentence and of SCN-YOLO-58), `docs/yolo-mode.md`, `docs/runbook.md` (12.2,
  12.2a steps 4–5 and its branch paragraph, the kiro-cli judge note), `CHANGELOG.md` (D11's Added, Changed and Fixed
  lines, without blank lines between items). Run: `tests/unit/docs`, `scripts/check_spec.py docs/SPEC.md`,
  `openspec validate yolo-guardrails --strict` and `openspec validate opencode-major-gate --strict`.

- [ ] 9.3 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit`, `.venv/bin/ruff check
  src tests plugins`, `.venv/bin/ruff format --check src tests plugins`, `.venv/bin/mypy src`. Commit.
  Done when all pass, `git status` is clean, and `git grep -nE "exists\(follow_symlinks|is for other inputs" src/`
  finds nothing (`os.stat(..., follow_symlinks=False)` is valid on 3.11 and stays).

## CHANGELOG lines (`## 0.4.18 (unreleased)`)

Write them under the existing subsections, with no blank line between items. Group A writes the lines marked (A) in
task 3.1, and group B the rest in task 9.2. The gate's own lines arrive by task 1.1.

### Added
- (B) `scripts/yolo_preflight.py` in the `l4` skill, beside `validate_plan.py`, standard library only. It checks a
  clean tree, HEAD equal to `origin/<base>`, the plan file and the unit folders on origin, the judge roles, the
  installed OpenCode major, `yolo.review.accept_by_agents` and the caller. It asks the harness for the admission and
  the review state, and prints exactly one `Next:` command (`--json` too) (L4-SKL-005).
- (B) The skill's `references/operate.md` starts with "origin is what counts", a numbered runbook from the draft to an
  active plan, and an error table (message, cause, fix). The runbook allows at most two rounds of spec fixes per
  subject, then accepting what this stack cannot fix, and a person activates (L4-SKL-004).
- (B) `plan.reviewed` records `target_rev` and `unit_revs`, the revisions the review read. A stale review's messages
  name the changed files from them (L4-YOLO-068).
- (A) `availability.probe_step_timeout` (default `20s`): the timeout of the `binary`, `auth` and `quota` probe steps.
  The hello keeps `availability.probe_timeout` (L4-AVL-012).

### Changed
- (B) `l4 yolo review PLAN --worktree --record` fetches and records only when HEAD is `origin/<base>`: commit, push,
  then `--record`. HEAD ahead, behind or diverged is refused before any judge call, with both short shas, the counts,
  the paths and the command (`git push origin HEAD:<base>` or the pull). A unit whose branch on origin holds another
  spec is refused too. The last line names `l4 yolo findings` or the person's `l4 yolo activate` (L4-YOLO-069).
- (B) A stale review names what differs: `activate: the review of <plan> is stale against origin/<base> (<sha>):`, one
  line per cause and a `Fix:` line. The causes are the review prompt, the plan file's digests, each changed unit's
  digests (where it is read, and its changed files), a subject not judged, and unpushed commits. `l4 yolo status`
  shows the same lines (`--json`: `review.stale`), and `l4 yolo review` prints them before it asks CI. A plan file that
  is only in HEAD is named with the push. The `inputs_changed` stop details name the frozen and the current digests
  (L4-YOLO-068).
- (B) `l4 yolo review PLAN` and `--local` print a `warning:` when HEAD is ahead of `origin/<base>` and the unpushed
  commits change the plan file or a unit folder: CI reviews origin, not your commits (L4-YOLO-070).
- (B) **Breaking:** an adapter profile that cannot judge in `roles.judges`, `roles.verifier_agent`, `roles.clarifier`
  or `roles.s1_judge` is a configuration error at load. An adapter that can judge is `claude-code`, `codex`, `opencode`
  or `fake`; one that cannot is, for example, `kiro-cli`. The error names the profile, the role and the allowlist.
  Before, such a profile was skipped at selection. Remove it from the role: kiro-cli becomes a judge in 0.4.19. Backend
  profiles are not affected (L4-CFG-006).

### Fixed
- (A) An availability probe no longer hangs when a CLI leaves a helper (an OpenCode v2 daemon) holding its output. The
  output is read until the CLI exits plus 2 s, and the whole process group is killed at the timeout (L4-AVL-012).
- (A) A probe step that does not answer names the CLI, the seconds, the likely cause and `run l4 doctor`. Before, it
  said `did not report a version` or `timeout` (L4-AVL-012).
- (A) An agent run ends when a helper outside its process group holds its output (L4-AVL-012).
