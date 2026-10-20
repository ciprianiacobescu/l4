Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, key, field, signature and constant is in
  `design.md` (D1 to D10 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree (`ci-evidence`), with its own `.venv` (`uv sync --inexact`). Never change git
  configuration. Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `ci-evidence <n.m>: …`, with no
  trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- Name a consumer repository only as "a consumer". Put no local path in docs or fixtures, and no test name, job name or
  path taken from a consumer's repository: the fixtures use generic names (`tests/test_cli.py::test_help`, `ci.yml /
  tests`).
- No test reads the network or sleeps. GitHub is `tests/unit/forge/_github_helpers.FakeGitHub`, GitLab is
  `tests/unit/forge/test_gitlab_pipelines.FakeGitLab` (`gitlab`, `make_forge_client`).
- One implementer does the tasks in order, on top of the previous commits.

Test worlds: `tests/unit/forge/_github_helpers.py` (`FakeGitHub`, `add_check_run`, `logs`, `redirect_to`, `REPO`,
`API`, `TOKEN`); `tests/unit/forge/test_github_checks.py` (`github`, `forge`); `tests/unit/forge/test_gitlab_pipelines.py`
(`RUNNER_TRACE`, `_runner_line`); `tests/unit/ci/test_sweeper.py` (the `ci.failed` tests at `:463`, `:532`, `:598`);
`tests/unit/verifier/test_preconditions.py` (`_ci_edge`, `edge_at`, `person_commit`, `STEP`, `CI_FILE`, `STEP_TAIL`);
`tests/unit/verifier/test_fixunit.py` (`ci_detail` at `:253`); `tests/unit/sandbox/test_env.py` (`HOST`, `make_spec`);
`tests/unit/runner/test_probe_m15_parity.py` (`run_bash`, `world`); `tests/unit/orchestrator/conftest.py` (`run_l4`,
`Run.events`, `tdd_repo`, `fake_clock`); `tests/unit/orchestrator/test_step_deadline.py:78-100` (the `run.started`
tests); `tests/unit/implementer/test_prompt.py` (`ctx`).

## 1. The excerpt module (design D1, D2, D4; L4-VER-061, L4-VER-063)

- [x] 1.1 Fixtures first, new directory `tests/fixtures/ci_logs/`:
  `github-pytest-failure.log` (synthetic, the incident's shape: a byte-order mark; every line prefixed
  `2026-10-20T10:00:00.0000000Z ` with rising times; the set-up lines; `##[group]Run actions/checkout@v4` … its
  output; `##[group]Run uv run pytest -q` with its script, `shell:` and an `env:` block that holds `UV_FROZEN: 1` and
  `GITHUB_TOKEN: ***`, `##[endgroup]`; 300 lines of dots and a failures section with `E       AssertionError: assert
  'run' in '\x1b[1m Usage: \x1b[0m'` written as the literal `repr` text; `=== short test summary info ===`, `FAILED
  tests/test_cli.py::test_help - AssertionError: assert 'run' in …`, `1 failed, 2277 passed in 312.40s (0:05:12)`,
  `##[error]Process completed with exit code 1.`; then two `Post job cleanup.` blocks of 20 lines each, `Cleaning up
  orphan processes` and `##[warning]Node.js 20 is deprecated. The following actions target Node.js 20 …`);
  `github-two-failed-steps.log` (a copy of `docs/live/feedback/runs/38329266005-job-115075028141.log`, the harness's
  own dummy, with the GitHub account in its URLs and paths replaced by `owner`). Tests first, new `tests/unit/forge/test_logexcerpt.py`:
  `test_the_incident_gives_the_failing_step` (SCN-VER-217: `actions_excerpt` of the first fixture with the steps
  `[Set up job: success, Run actions/checkout@v4: success, tests: failure, Post Run actions/checkout@v4: success]`
  gives a text whose first line is `Run uv run pytest -q`, which holds the `FAILED` line, the count and the first `E`
  line, ends with `Error: Process completed with exit code 1.`, and holds no `Post job cleanup.`, no `Node.js 20`, no
  `UV_FROZEN`, no `2026-10-20T` and no `﻿`; `failed_step` is `tests`);
  `test_the_first_failed_step_is_the_anchor` (SCN-VER-218: the second fixture holds `fatal: could not read Username`
  and `Error: Process completed with exit code 128.`, and not `exit code 127`; its first line is `Run git fetch …`);
  `test_an_annotation_does_not_cut_the_step` (SCN-VER-219); `test_a_continue_on_error_step_is_not_the_anchor`
  (SCN-VER-220: with and without the steps); `test_no_error_line_gives_todays_tail` (SCN-VER-221: the last 40 lines,
  equal to `clip_log` of the lines without timestamps; `failed_step` still the API's name when given);
  `test_without_steps_the_name_is_the_header` (SCN-VER-221, the second case);
  `test_a_failure_before_any_step` and `test_a_composite_step_is_its_own_section` (SCN-VER-222);
  `test_markers_read_as_on_the_page` (`##[error]`, `##[warning]`, `##[notice]` become `Error: `, `Warning: `, `Notice:
  `; `##[group]` inside the body loses its marker, `##[endgroup]` lines go);
  `test_summary_lines_patterns` (each of the six patterns of D4 matches its example and `0 failed`, `Process completed
  with exit code 1`, `PASSED t::x` do not; at most six `E` lines; log order; no repeats);
  `test_ranked_summary_lines` (D5: with six `E` lines before a `FAILED` line and a count, the order is the `FAILED` line, the count, then the `E` lines; log order within a class; no repeats); `test_section_excerpt_budgets` (SCN-VER-225: five `FAILED`, 30 `E` lines and 200 more lines: the five, the first six
  `E`, `...`, the last 40; a 2,000-character line is cut to 500 plus `...`; 3,000 characters at most; over budget the
  tail's first lines go down to five, then the summary's last lines; a body of 10 lines has no `...`);
  `test_the_module_imports_only_the_forge_base` (with `ast`: no `l4.` import but `l4.forge.base`).
  Code: new `src/l4/forge/logexcerpt.py` (Contracts). Run: `tests/unit/forge/test_logexcerpt.py`.
  Result: done; 18 tests in test_logexcerpt.py pass; the tests were seen to fail on the missing module first; fixtures in tests/fixtures/ci_logs (synthetic incident log, scrubbed copy of the harness's own dummy log).

## 2. The GitHub forge (design D2, D6; L4-VER-061)

- [x] 2.1 Tests first. `tests/unit/forge/_github_helpers.py`: `add_check_run(..., steps=None)` stores a job's steps,
  and `GET /repos/{REPO}/actions/jobs/<id>` answers `{"id": …, "steps": […]}` (404 for an unknown id, and a settable
  status such as `jobs_status = 403`). New `tests/unit/forge/test_github_job_log.py`:
  `test_job_log_is_the_failing_steps_excerpt_and_names_it` (the first fixture of 1.1 as the log, its steps: `tail` is
  the excerpt of 1.1, `step` is None, `failed_step` is `tests`; `job_log_tail` is the same tail);
  `test_the_steps_are_read_with_the_token_and_the_log_without_it` (the hosts of the existing redirect test, plus one
  `actions/jobs/<id>` read on the API host);
  `test_a_refused_steps_read_keeps_the_log` (SCN-VER-221: `jobs_status = 403` and a 500: the excerpt of the first
  error's section, `failed_step` its header);
  `test_no_log_reads_no_steps` (SCN-VER-221: an unknown job gives `JobLog()` and no `actions/jobs/<id>` request); `test_steps_listed_with_the_run_jobs_are_not_read_again` (a `_run_jobs` listing whose job objects hold `steps`: `job_log` of that job makes no `actions/jobs/<id>` request and the excerpt is the same; a listing without `steps` falls back to the read).
  The existing `tests/unit/forge/test_github_checks.py::test_log_redirect_is_followed_without_the_token` must pass
  unchanged (a log with no `##[error]` and no timestamps: today's tail). Code: `src/l4/forge/base.py`
  (`JobLog.failed_step`; the `job_log` docstring of the protocol), `src/l4/forge/github.py` (`_job_steps` reads the map that `_run_jobs` fills with each listed job's `steps`, else the request; `job_log` composes, `job_log_tail` returns its tail). Run: `tests/unit/forge`.
  Result: done; tests/unit/forge 465 pass (new test_github_job_log.py: 5 tests incl. the steps reused from the run's job listing). 2.2 (live validation of the step conclusions) stays open for a person.

- [ ] 2.2 Live validation (not done by the implementer; a person ticks it with a log of a real run): on a GitHub repository, a job with a `continue-on-error: true` step that fails and a later step that fails the job, and a job with a step stopped by `timeout-minutes`. Read `GET actions/jobs/<id>` for both and record the `conclusion` of each step. The code is safe for either answer (D2); this task only replaces the two [U] marks of D2 with [V]. Do not build a fixture on a guess before it is done.

## 3. The GitLab forge (design D3; L4-VER-062)

- [x] 3.1 Tests first, in `tests/unit/forge/test_gitlab_pipelines.py`:
  `test_an_after_script_after_the_failure_is_not_in_the_tail` (SCN-VER-223: the shape of
  `docs/runner/live-m0-2026-10-04-job-5420.txt:80-106` with an `after_script` of 60 lines: the tail ends with `l4 exit 1
  (internal_error): …` and `ERROR: Job failed: exit status 1`, no `after_script` line, `step` unchanged);
  `test_the_cache_sections_are_runner_sections` (a trace without a script section whose `archive_cache_on_failure`
  section has lines: they are not in the tail); `test_a_trace_without_a_script_section_keeps_todays_tail`
  (SCN-VER-224); `test_a_long_script_keeps_its_failures` (SCN-VER-225 on GitLab: `FAILED` lines before the last 40).
  The existing `test_job_log_tail_is_capped_and_ansi_stripped`, `test_job_log_tail_drops_the_runner_framing_…`,
  `test_a_trace_without_runner_timestamps_is_cleaned_too`, `test_failing_step_is_the_last_echo_in_step_script`,
  `test_an_after_script_echo_is_not_the_failing_step` and `test_a_trace_without_sections_has_no_step` must pass
  unchanged. Code: `src/l4/forge/gitlab.py` (`_RUNNER_SECTIONS`, `_read_trace` returns `TraceParts`, `job_log`
  composes with `section_excerpt`). Run: `tests/unit/forge`.
  Result: done; tests/unit/forge 469 pass (4 new in test_gitlab_pipelines.py; the 6 existing job-log tests unchanged).

## 4. The sweep and step 0 (design D5, D6; L4-VER-063, L4-VER-064)

- [x] 4.1 The sweep records `failed_step`. Tests first: `src/l4/forge/local.py` gets the scripted `failed_steps`
  beside `steps` (state key `failed_steps`, read back by `LocalForge` like `steps`), and `tests/unit/forge/
  test_local_forge.py` checks it. In `tests/unit/ci/test_sweeper.py`: `test_ci_failed_records_the_failing_step`
  (a GitHub-shaped job with `failed_steps`: the entry has `failed_step`; a GitLab job's entry has no such key, so the
  equality at `:598` holds); `test_the_failing_step_and_the_tail_are_redacted` (SCN-VER-226: a configured secret's
  value and a `ghp_` token of 36 characters in the tail and in the step's name: `[REDACTED:…]` in both, the name at
  most 300 characters after redaction). Code: `src/l4/ci/sweeper.py` (`_log`, the entry). Run: `tests/unit/ci
  tests/unit/forge/test_local_forge.py`.
  Result: done; test_sweeper.py 78 pass, test_local_forge.py pass; the sweep records failed_step only when the forge names one.

- [x] 4.2 The blocker's detail and the GitHub `ci.step`. Tests first, in `tests/unit/verifier/test_preconditions.py`:
  `test_the_blocker_names_the_github_step_and_leads_with_the_failure` (SCN-VER-227: an edge whose job is `ci.yml / tests` with `workflow: ci.yml`, `failed_step: tests`, a run URL and a tail like the one of 1.1 with 25 coverage lines between the count and the closing `Error:` line (without them the failing test is in `Log ends:` already and there is no `Failed:` part, which the test also checks): the detail starts ``job `ci.yml /
  tests` failed in step `tests` on the hand-off commit``, and its first 600 characters hold `Failed: FAILED tests/test_cli.py::test_help - AssertionError | 1 failed, 2277 passed`, `Log ends:` and `Error: Process completed with exit code 1.`; a variant whose tail has six `E` lines before the `FAILED` line still starts `Failed:` with the `FAILED` line, then the count, then the `E` lines that fit; and a variant with an `again:` sentence in front: the window and the candidates are chosen after it, so the 600 characters still hold the `FAILED` line and `Log ends:`); `test_a_detail_whose_failures_are_in_the_end_is_todays` (SCN-VER-228: `ci_detail` of
  `STEP_TAIL` and of the tail of `test_job_log_tail_drops_the_runner_framing_…` equals the 0.4.20 text, pasted into the
  test as a literal); `test_an_older_edge_leads_with_its_failures` (SCN-VER-229: no `failed_step`, a `FAILED` line 40
  lines before the end); `test_a_github_step_is_named_never_derived` (SCN-VER-230: `workflow: ci.yml`, a `$ make
  deploy` line in the tail and a `.gitlab-ci.yml` at H that lists it: `ci.step` `skipped`, `step` the `failed_step`,
  the reason of the Contracts, source `ci.yml@<H10>`, and `show_blob` is not called for `.gitlab-ci.yml`: today
  `derive_ci_steps` reads it once before its job loop, `preconditions.py:139`; the read becomes lazy, at the first job
  that is not a GitHub job).
  In `tests/unit/verifier/test_fixunit.py`: `test_the_fix_spec_carries_the_excerpt` (SCN-VER-231: OpenSpec proposal
  and Kiro requirements of a fix unit built from the blocker above hold `tests`, the `FAILED` line and `Error: Process
  completed with exit code 1.`, and no `##(`). The existing `test_ci_blocker_names_the_failing_step_and_records_ci_step`
  and the `ci_detail` use at `test_fixunit.py:253` must pass unchanged. Code: `src/l4/verifier/preconditions.py`
  (`ci_detail`, `ci_blockers`, `derive_ci_steps`, `GITHUB_STEP_REASON`; the module docstring). Run:
  `tests/unit/verifier/test_preconditions.py tests/unit/verifier/test_fixunit.py tests/unit/ci`.
  Result: done; test_preconditions/test_fixunit/specs fix-unit tests pass; the new tests were seen to fail without the code. Deviation: SCN-VER-227 is run with a coverage report after the failing test (the incident's own excerpt ends with its failing test, so there is no Failed: part; spec, SPEC.md, design and tasks say so); ci_detail has a prefix argument for D12.

## 5. The gate environment (design D7; L4-SEC-040)

- [x] 5.1 Tests first, in `tests/unit/sandbox/test_env.py`: `test_in_ci_the_gate_gets_the_ci_flags_and_the_agent_does_not`
  (SCN-SEC-100: `HOST` plus `CI=true`, `GITHUB_ACTIONS=true`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `RUNNER_TEMP`: the
  gate has the two flags and none of the others; the agent has neither; the existing first test still holds for
  `HOST`); `test_gitlab_ci_and_no_colour_variable_is_passed` (`GITLAB_CI=true` with `FORCE_COLOR=1`, `NO_COLOR=1`, `PY_COLORS=1`, `CLICOLOR=0`, `CLICOLOR_FORCE=1`, `TTY_COMPATIBLE=1`: the gate has `GITLAB_CI` and none of the six, in CI and with `CI=true` alone); `test_a_value_that_is_not_a_short_word_is_refused` (SCN-SEC-102: for `GITLAB_CI` and `GITHUB_ACTIONS`: a 40-character value, `/tmp/x`, `true\n` (a trailing newline: `fullmatch`, not `match`), `1.0` and an empty value: not passed; `refused_ci_env` names the non-empty ones);
  `test_outside_ci_nothing_changes_and_ci_true_opts_in` (SCN-SEC-103); `test_a_gates_own_setting_wins` (`extra`
  `FORCE_COLOR=0` over the host's `1`). In `tests/unit/runner/test_probe_m15_parity.py`: the gate parity test also with a CI host (`CI=true`, `GITHUB_ACTIONS=true`, `GITLAB_CI=/tmp/x`, `FORCE_COLOR=1`, and `GITHUB_ACTIONS=true\n` in a second case). New
  `tests/unit/orchestrator/test_gate_ci_env.py` (the `run_l4` world): `test_run_started_records_the_gate_names`
  (SCN-SEC-100: with `CI=true`, `GITHUB_ACTIONS=true` and `FORCE_COLOR=1` in the run's environment, `run.started` has `gate_env_ci: ["CI", "GITHUB_ACTIONS"]`; without, no key); `test_a_refused_value_is_named_once` (SCN-SEC-102: one WARNING per name, with the D7 text, and the value nowhere in `caplog.text`); `test_a_local_opt_in_logs_one_info_line` (SCN-SEC-103: `CI=true` alone: one INFO line with the D7 text and `gate_env_ci: ["CI"]`; in a `GITHUB_ACTIONS=true` job: no INFO line); `test_a_test_that_only_ci_fails_fails_in_the_gate`
  (SCN-SEC-101: a unit whose test reads `os.environ.get("GITHUB_ACTIONS")` and fails when it is set: in a run with
  `GITHUB_ACTIONS=true` the green step's gate fails on it; without, it passes as before). The existing
  `test_step_deadline.py:78-100` must pass unchanged. Code: `src/l4/sandbox/env.py`, `scripts/runner/ci-probe-m15.sh`
  (`m0_gate_env`: the same `in_ci` test and the same short-word check, `LC_ALL=C` for the character class and the whole value matched, so `GITLAB_CI=/tmp/x` is refused there too;
  the CI names printed in `GATE_CI_PASSTHROUGH` order after `m0_env`'s lines and before `printf '%s\n' "$@"`, the
  cache variables, which is where `build_gate_env` puts them; `gate_ci_env` returns them in that order, only the
  ledger's `gate_env_ci` is sorted), `src/l4/orchestrator.py` (`_job_facts`, the WARNING in `run_command` after the
  budget checks).
  Run: `tests/unit/sandbox tests/unit/runner tests/unit/gates tests/unit/orchestrator/test_gate_ci_env.py
  tests/unit/orchestrator/test_step_deadline.py`.
  Result: done; tests/unit/sandbox, runner, gates 474 pass (13 skipped: no bwrap); test_gate_ci_env.py + test_step_deadline.py 52 pass; the three CI names only, fullmatch short words, no colour variable, INFO line on a local opt-in; shell twin m0_ci_env with LC_ALL=C, parity-tested with 5 CI hosts.

## 6. The implementer's prompt (design D8; L4-IMP-080)

- [x] 6.1 Tests first, in `tests/unit/implementer/test_prompt.py`: `test_in_ci_the_gate_section_names_the_variables`
  (SCN-IMP-396: `ctx` with `gate_env_ci=("CI=true", "GITHUB_ACTIONS=true")` for red, green and single: the gate section holds the D8 text with `` `CI=true`, `GITHUB_ACTIONS=true` `` and the command `CI=true GITHUB_ACTIONS=true <gate command>`); `test_without_them_the_prompt_is_todays`
  (the rendered text and sha256 with the default context equal those before the change: every pinned prompt hash in
  `tests/unit/implementer` passes unchanged, and `templates.lock.json` is not touched). In
  `tests/unit/implementer/test_prompt_context_run.py` (or the nearest `tdd.py` prompt-context test):
  `test_the_context_takes_the_gate_ci_env` (a workbench whose `host_env` has `CI=true`, `GITHUB_ACTIONS=true`: the
  context's `gate_env_ci` is the sorted pairs; a host without them gives `()`). Code: `src/l4/implementer/prompt.py`
  (`PromptContext.gate_env_ci`, the gate section), `src/l4/implementer/tdd.py` (`:715`). Run:
  `tests/unit/implementer/test_prompt.py tests/unit/implementer/test_prompt_context_run.py tests/unit/doctor
  tests/unit/sim`.
  Result: done (the implementer/doctor/sim run is in the final full run); test_prompt.py/test_single_phase.py/test_prompt_context_run.py pass; the prompt is byte-identical without the variables (pinned sha256 of the default red/green/single prompts); the reproduce command names the configured gate command; the CI chore line (D11, PromptContext.ci_job) is in 6.1's commit because it shares the prompt code; 8.1 below only covers what is left.

## 7. The CI module of D12 (design D12; L4-OPS-023)

- [x] 7.1 Tests first, new `tests/unit/ci/test_unfixed.py` (a real git repository from `tdd_repo`/`raw`, ledger events built in the test): `test_project_changes_leave_out_spec_harness_and_merges` (commits after H that change the parent's folder, a fix unit's folder under `openspec/changes/`, `.l4/ledger/r.jsonl`, `.l4-out/x` and a merge of the base that changes `src/app/other.py`: `()`; one more commit that changes `src/app/cli.py`: `("src/app/cli.py",)`; an H that is no ancestor: None); `test_the_same_job_again_on_an_unchanged_head_is_unfixed` (SCN-OPS-40, SCN-OPS-41: edge 1 at H1, a fix unit commit that changes only its `tasks.md`, edge 2 at H2 with the same job: `again_head` H1, `again_changed` 0, `unfixed`; a verdict or a `unit.retried` between the edges changes nothing); `test_again_with_changes` (SCN-OPS-42: a commit that changes `src/app/cli.py`, or a person's commit that changes `tests/test_cli.py`, between the edges: `again_changed` 1, not `unfixed`); `test_a_job_that_failed_before_only_in_another_job_is_not_again` (edge 1 lists job A, edge 2 lists job B: B has no `again_head`); `test_put_back_and_notes` (`guard.test_tamper{phase: single, path: tests/test_cli.py}` and `guard.violation{phase: single, path: tests/conftest.py, rule: test support file}` between the edges, and the chore's `task.done{notes}`, become `put_back` (both paths, sorted) and `notes`; an event of `phase: green` or one before edge 1 is not counted); `test_a_base_merge_is_not_a_fix` and `test_a_rewritten_history_is_not_judged` (SCN-OPS-44: H1 not an ancestor of H2: `again_changed` None, not `unfixed`). Code: new `src/l4/ci/unfixed.py` (Contracts). Run: `tests/unit/ci/test_unfixed.py`.
  Result: done; tests/unit/ci/test_unfixed.py 10 pass; CiHistory also carries failed_step and failing (E's step and failing lines for the escalation text) and ci_history takes no head (E's is in the ledger).

## 8. The fix chore's line, the put-back note, the questions of a fix unit (design D11, D13; L4-IMP-081)

- [x] 8.1 The line in the chore's prompt. Tests first, in `tests/unit/implementer/test_prompt.py`: `test_a_ci_chore_prompt_carries_the_line` (SCN-IMP-397: `ctx` with `ci_job="ci.yml / tests"` and role `single`: the prompt holds the D11 line with the job; `ci_job=None`: the prompt and its sha256 are those before the change, and the template versions and `templates.lock.json` are unchanged); in `tests/unit/implementer/test_single_phase.py` (the world of `test_a_reproduced_ci_step_must_pass_after_the_chore`, an edge of a GitHub job with `workflow`): `test_the_prompt_of_a_ci_chore_names_the_job` (the chore's findings hold `finding_id("repository CI failed: ci.yml / tests")` of the last edge: the prompt has the line; a chore of a judge finding: not) and `test_a_ci_chore_that_changes_nothing_is_committed_as_before` (SCN-IMP-397: the step changes nothing: `ok`, as `test_a_chore_without_a_ci_finding_runs_no_extra_gate` and the existing single-phase tests expect). Code: `src/l4/implementer/prompt.py` (`PromptContext.ci_job`, `CI_JOB_LINE`), `src/l4/implementer/tdd.py` (`_prompt` fills `ci_job` for the single role from the edge, as `failing_step.py:229-238` does). Run: `tests/unit/implementer`.
  Result: done in the commit of 6.1 (same prompt code): test_prompt.py (line, byte-identical default, job name cannot open a data block) and test_single_phase.py (the line reaches the chore's prompt only for its own finding; a chore that changes nothing is committed); the trigger is chore_ci_job(events, findings) in l4/ci/failing_step.py, as chore_ci_steps matches the finding id.

- [x] 8.2 The put-back note and the question of a blocked chore. Tests first, in `tests/unit/implementer/test_guardnotes.py` (or the nearest guard-note test): `test_a_single_phase_put_back_is_a_persons_commit` (SCN-IMP-398: `guard.test_tamper{phase: single, rule: test path freeze}` for `tests/test_cli.py` and `guard.violation{phase: single, rule: test support file}` and one without a rule (from `restore_frozen`) for `tests/conftest.py`: the lines name both paths and say `a fix task may not change test or test-support files`, `a person must commit that change`; the advice ends `do not ask for the file to be unfrozen`; none holds `ask a question that names its path`; the same events with `phase: green` keep today's text byte for byte); in `tests/unit/implementer/test_loop*.py` (the test that covers `_raise_blocked`): `test_a_chore_question_cannot_unfreeze_a_file` (SCN-IMP-398: a blocked chore whose attempt put `tests/conftest.py` back: the question's context ends with the D11 harness note that names `tests/conftest.py`, and holds no `Harness note: the red tests and test-support files of this task are frozen`; a blocked green question keeps `unfreeze_note`). Code: `src/l4/implementer/guardnotes.py` (`GuardNote.phase`, `note_of`, `guard_note_text`), `src/l4/implementer/loop.py` (`_questions` and `_raise_blocked` add the chore note when `red` is None and the step is a chore). Run: `tests/unit/implementer`.
  Result: done; test_guard_notes.py, test_test_path_freeze.py and test_loop.py pass (the existing 'a fix chore may not change test files' assertion still holds as a substring). Deviation: the question note names no path (a blocked step is discarded before the put-backs run); it is for technical questions only; spec/design/SPEC.md say so.

- [x] 8.3 `l4 questions` finds a fix unit's questions. Tests first, in the questions CLI tests (`tests/unit/specs/test_questions_cli*.py` or where `load_folders` is tested): `test_show_and_accept_find_a_fix_units_question` (SCN-IMP-399: a repository with unit `a` and `a-fix-1` whose `questions.md` holds Q-001 on a's branch only, with `discover` listing the fix unit too: `show Q-001 --unit openspec:a-fix-1` prints it, `accept Q-001 --unit openspec:a-fix-1` takes it and commits on a's branch; `show Q-001 --unit openspec:a` says no Q-001; none says `has no branch on origin`); `test_a_fix_unit_without_a_folder_is_no_unit` (`no unit <name>`). Code: `src/l4/specs/questions_cli.py` (`load_folders`: the `_FIX_NAME` match is tried before `unit in by_id` when the parent is a unit and the name is not the parent's). Run: the questions CLI tests and `tests/unit/specs`.
  Result: done; test_questions_cli.py and test_questions_agents.py 91 pass (3 new: show and accept of a fix unit that discover lists as a unit of its own fail with 'has no branch on origin' before the change). A unit with a branch of its own keeps it; a fix name resolves to the parent only when the fix unit has no branch.

## 9. The round escalates (design D12; L4-OPS-023)

- [x] 9.1 Step 0 and the fix loop. Tests first, in `tests/unit/verifier/test_preconditions.py`: `test_a_repeated_ci_job_gets_the_again_prefix` (SCN-OPS-40: edge 1, a fix commit of `tasks.md` only, the put-back events (`guard.test_tamper` for `tests/test_cli.py` and `guard.violation` for a new `tests/conftest.py`) and the chore's notes of 300 characters, edge 2 with a GitHub run URL: the blocker's detail starts ``again: job `ci.yml / tests` also failed on the hand-off commit <H1-10>; project files changed since: 0.``, its first 600 characters hold `Failed:` and `Log ends:`, and after the blank line it names both paths and has `The fix step said:`); `test_again_prefix_with_changes` (SCN-OPS-42: `project files changed since: 1.`; a rewritten history: no count, SCN-OPS-44). In `tests/unit/verifier/test_fixloop_escalation.py`: `test_an_unfixed_ci_job_escalates_with_ci_not_fixed` (SCN-OPS-40: fix rounds left, the reason of D12 with the step and the failing lines, no fix unit, `same_failure` not reached); `test_a_hand_off_as_it_was_that_fails_again_escalates` (SCN-OPS-41); `test_a_project_change_makes_a_fix_unit` (SCN-OPS-42: no escalation); `test_a_base_merge_is_not_a_fix` (SCN-OPS-44); `test_an_unfinished_fix_unit_or_a_feedback_item_goes_first` (an unfinished fix unit is taken up; a round with a person's feedback item makes its fix unit); `test_a_resumed_round_decides_the_same` (the decision with step 0 not re-run: from the ledger and git). The existing `tests/unit/verifier/test_fixloop*.py` and `test_ladder_fix_resume.py` must pass unchanged. Code: `src/l4/verifier/preconditions.py` (`ci_blockers` with the history; `check_preconditions` passes it), `src/l4/verifier/fixloop.py` (`CI_NOT_FIXED`, `decide_fix`). Run: `tests/unit/verifier tests/unit/ci`.
  Result: done; test_preconditions (3 new), test_fixloop_ci.py (9 new: decide_fix on a real repository and ledger) and test_fixloop_escalation pass. The decision lives in fixloop.unfixed_ci_jobs/ci_not_fixed_detail and runs only for a round whose findings hold the job's blocker; a round with a feedback item to take makes its fix unit; an unfinished fix unit is taken up first. Deviation: no end-to-end run_l4 test (the world cannot seed two hand-offs); decide_fix is called directly.

- [x] 9.2 The way on. Tests first, in `tests/unit/state/test_next_step.py`: `test_ci_not_fixed_names_the_way_on` (SCN-OPS-43: `way_out(U, "ci_not_fixed")` is the D12 text); in `tests/unit/state/test_status_reason.py`: `Cause:` (the reason with the excerpt), `Next:` and `next` of a unit `escalated` with `ci_not_fixed`; in `tests/unit/ci/test_resume_label.py`: the sticky section of such a unit shows the reason and the way on and the label; the refusal of `l4 run --unit` (the test that covers `no_convertible_finding` there) names it too. The existing SCN-OPS-38/39 tests pass unchanged. Code: `src/l4/state/next_step.py` (`CI_NOT_FIXED`, `ci_not_fixed_way_out`, `way_out`), `src/l4/ci/resume_label.py` (the `escalated` section for `ci_not_fixed`). Run: `tests/unit/state tests/unit/ci tests/unit/orchestrator/test_run_command.py`.
  Result: done; tests/unit/state (next_step, status_reason, spec_edited refusal), test_resume_label, test_yolo_commands_manage: 141 pass. The sticky note and the run refusal keep up to 600 characters of the reason for ci_not_fixed (the excerpt), 300 and 150 for the other causes as before.

## 10. Docs, SPEC, CHANGELOG (design D10)

- [x] 10.1 Tests first, new `tests/unit/docs/test_ci_evidence_docs.py`:
  `test_the_spec_has_the_requirements_and_scenarios` (`**L4-VER-061 ` to `**L4-VER-064 ` in order before `**L4-VER-015
  `; `**L4-SEC-040 ` after `**L4-SEC-039 `; `**L4-IMP-080 ` after `**L4-IMP-079 `; `#### SCN-VER-217 ` to `#### SCN-VER-231
  ` in order after `#### SCN-VER-169 `; `#### SCN-SEC-100 ` to `#### SCN-SEC-103 `; `#### SCN-IMP-396 ` to `#### SCN-IMP-399 ` before
  `### 23.8`; `**L4-IMP-081 ` after `**L4-IMP-080 `; `**L4-OPS-023 ` after `**L4-OPS-022 `; `#### SCN-OPS-40 ` to
  `#### SCN-OPS-44 ` after `#### SCN-OPS-39 `; `| 62 | \`ci-evidence\` |`; §12.1 names `failed_step` and `gate_env_ci`; L4-SEC-001 names L4-SEC-040);
  `test_the_runbook_says_what_the_fix_unit_gets` (§7.5's "Your own CI is red" paragraph names `failed_step` or "the
  failing step", `GITHUB_ACTIONS`, and that no colour variable is passed); `test_the_skill_says_it`
  (`plugins/l4/skills/l4/references/operate.md` has a `repository CI failed: <job>` row that names the failing step
  and the gates' CI flags);
  `test_the_changelog_names_the_change` (in `## 0.4.21 (unreleased)`, above `## 0.4.20 (`: `failed_step`, `GITHUB_ACTIONS`, `gate_env_ci`, `after_script`, `Process completed`, `ci_not_fixed`, `changed a project file`);
  `test_the_runbook_names_ci_not_fixed` (the runbook's list of escalation reasons has `ci_not_fixed` with its way on, and so do `plugins/l4/skills/l4/references/operate.md` (the escalated bullet near `no_convertible_finding`) and `control-loop.md` (the `escalated` row)). Code: `CHANGELOG.md` (the lines below, under
  `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)`; a parallel change may add the same heading: whoever merges
  second keeps one heading and merges the lists under the same subheadings), `docs/runbook.md` (the list of `escalated` causes at `:224` and the
  cause table of §7.3 at `:1033-1041` get `ci_not_fixed`, with the D12 reason and way on; §7.5, after the
  paragraph "Your own CI is red on the hand-off commit": the fix unit gets the failing step's name and the end of its output with the failing tests first; in CI the gates run with `CI`, `GITHUB_ACTIONS` or `GITLAB_CI` as the job has them, agents do not, and no colour variable is passed (a test must not depend on colour); `CI=true l4 run` does the same on a person's machine), `plugins/l4/skills/l4/references/operate.md`
  (a row of the error table: `repository CI failed: <job>`; cause: the repository's own CI is red on the hand-off commit, and the finding names the failing step and its failing tests; fix: the fix unit takes it; in CI the gates run with the CI's flags; when the same job fails again with no project change, the unit escalates with `ci_not_fixed`: fix it in a commit of your own or give feedback, then `l4 retry`). The SPEC text is already in this branch; change it only to match the
  code, with the orchestrator. Run: `tests/unit/docs tests/unit/skills`, `scripts/check_spec.py docs/SPEC.md`,
  `openspec validate ci-evidence --strict`.
  Result: done; tests/unit/docs + tests/unit/skills 112 pass; SPEC.md check_spec clean; openspec validate ci-evidence --strict valid. test_yolo_guardrails_docs.py counts the rows of operate.md's error table: 34 -> 35 for the new row (the spec asks for it; earlier changes bumped the count the same way). The skill reference stays within its 900 words.

- [ ] 10.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract`; then
  `CI=true GITHUB_ACTIONS=true .venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/sandbox tests/unit/gates
  tests/unit/implementer tests/unit/verifier tests/unit/orchestrator` (the harness's own CI sets both: no test may
  depend on their absence); `.venv/bin/ruff check src tests scripts plugins`, `.venv/bin/ruff format --check` on every
  changed file, `.venv/bin/mypy` on the changed src files, and `bash -n scripts/runner/ci-probe-m15.sh`. Done when all
  pass, `git status` is clean, and `git grep -n "no failing step in the log" -- src` finds only the GitLab path.

## CHANGELOG lines (`## 0.4.21 (unreleased)`; task 10.1 writes them as they stand)

### Changed
- In CI, the gates run with the CI's identity variables (L4-SEC-040). When `CI`, `GITHUB_ACTIONS` or `GITLAB_CI` is
  `true`, every gate (setup, build, lint, typecheck, test, e2e, a `repository-ci:` step) also gets `CI`,
  `GITHUB_ACTIONS` and `GITLAB_CI` as the job has them, when the whole value is a short word. Agents do not, and no
  colour variable is passed. Tools now behave in the gates as in your CI: typer and rich colour their output, pytest
  stops truncating assertions, jest and vitest write no new snapshot, pnpm installs with a frozen lock file. A test
  that only your CI failed now fails before the hand-off. `run.started` records `gate_env_ci`. Outside CI nothing
  changes; `CI=true l4 run` opts in and logs one INFO line.
- When the gates get those variables, the implementer's prompt names them, gives the command to reproduce a CI-only
  failure, and says that a test of a command's help or output must not depend on colour (L4-IMP-080).
- A CI job that fails again on a later hand-off, with no commit since its earlier failure that changed a project file,
  no longer gets another fix unit (L4-OPS-023). Before, a fix unit whose only task changed nothing (the gates could
  not show the failure, and a fix task may not change the unit's tests) passed its round and was handed off with the
  same failure, until `max_fix_rounds`. Now the round escalates with the new reason `ci_not_fixed`: `l4 status` and the
  sticky note show the CI excerpt and the way on (your own commit, or `l4 feedback add`, then `l4 retry`; `l4 retry`
  alone hands the unit off as it is). A CI blocker of a job that failed before starts with `again:`.
- A fix task that answers a red CI job is told that the gates may not show the failure and to say so in
  `notes_for_verifier` (L4-IMP-081). A test or test-support file that a fix step changed is put back as before, and the
  note and the step's question now say that a person must commit that change, instead of asking to unfreeze it.

### Fixed
- The evidence of a red project job is the failing step's output (L4-VER-061, L4-VER-062, L4-VER-063). On GitHub it
  was the last 40 lines of the job log, which end with the post steps (`Post job cleanup.`, cache and checkout
  cleanup, the runner's Node.js warnings), so a fix unit could be given none of the failure. Now the forge reads the
  job's steps, takes the section of the first `##[error]` line (its `Run …` header, its last 40 lines, its `FAILED`
  lines, assertion lines and counts before them), drops the runner's timestamps, and records the step's name as
  `ci.failed.jobs[].failed_step`. On GitLab the excerpt ends with the job's script and the `ERROR: Job failed` line:
  `after_script` and the cache upload no longer push the error out.
- The `repository CI failed` blocker names the failing step (``job `ci.yml / tests` failed in step `tests` …``) and
  puts the failing tests in its first 600 characters (`Failed: …`, the failing tests first, then the counts) before
  `Log ends: …` (L4-VER-064). `##[error]` reads `Error:` (the excerpt ends with `Error: Process completed with exit code 1.`), so a fix spec no longer shows `##(error)`. A GitHub job's
  `ci.step` says that its step is named, not re-run, instead of `no failing step in the log`.
- `l4 questions show` and `accept` with `--unit <fix unit>` find the fix unit's questions on its parent's branch
  instead of failing with `has no branch on origin`.
