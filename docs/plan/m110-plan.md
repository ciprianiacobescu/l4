# M1.10 — the M1.8 and M1.9 live findings (planned 2026-10-06)

## Goal

The M1.8 and M1.9 live checks passed, with ten findings left open (`docs/live/README.md`, sections "M1.8 easy
adoption" F1–F4 and "M1.9 re-verify after the hand-off" F2–F7 and the land note). M1.10 closes them as C1–C10:

* **C1 (M1.9 F2, important).** A fix round for `repository CI failed: <job>` is checked only by the judge. In B9 a
  wrong fix (a line still 105 > 92) passed every L4 gate. M1.10 re-runs the project job's **failing step** in the gate
  sandbox, as the extra gate `repository-ci:<job>`, in the chore and in the rounds after it. When the step cannot be run
  safely, it is skipped with a recorded reason and the judge alone checks the fix, as today.
* **C2 (M1.9 F5).** A human-accepted answer that names a frozen red test unfreezes exactly that file for that task's
  next green attempt.
* **C3 (M1.9 F4).** On re-verification the judge no longer reviews the harness's `verification.md`, and it is told
  which changes are the owner's.
* **C4–C10.** The sweep's CI warning line (F6), the question title in the trace (F7), the marker's quote style (F3),
  the runner tags in `setup gitlab` (M1.8 F1), a token refresh for `--watch` (M1.8 F2), path narrowing in the lint
  advice (M1.8 F3), and init's console reminders and closing line (M1.8 F4, M1.9 land note).

**26 build lines**, test first. Each new test is seen failing before the code is written.

## Coverage: finding → build lines

| Finding | Lines | Finding | Lines |
|---|---|---|---|
| C1 a CI fix is checked only by the judge (M1.9 F2) | 1–9 | C6 marker quote style (M1.9 F3) | 19 |
| C2 an accepted answer cannot unfreeze a red test (M1.9 F5) | 10–14 | C7 runner tags not named (M1.8 F1) | 20 |
| C3 judge noise on re-verification (M1.9 F4) | 15, 16 | C8 `--watch` dies at the token's TTL (M1.8 F2) | 21, 22 |
| C4 the sweep's CI warning never prints (M1.9 F6) | 17 | C9 lint advice narrows rules, not paths (M1.8 F3) | 23, 24 |
| C5 `question … raised (verdict): None` (M1.9 F7) | 18 | C10 init reminders and closing line (M1.8 F4, M1.9 land note) | 25 |

Not built: the third F4 bullet (the judge flagged an audit test committed after its diff was taken), M1.8 F5
(`186/192 passed` without naming the 6 skips), M1.8 F6 (watcher line order) and M1.8 F7 (the sample-consumer job's schedule guard,
which is the maintainer's to fix).

## Facts this plan rests on

Labels: [V] read in code or files at `8e1c562`; [I] inferred; [U] not checked.

* **The chore's checks** [V `implementer/tdd.py` `run_single`]:
  * a `[chore]` task runs one `single` step;
  * its checks are `check_green(base_report, [], gate)` plus `worse_static_gates`, which are only the configured
    `gates.*`;
  * a fix unit's events go to the parent's run ledger (`wb.ledger_rel`, `resume_red`'s comment);
  * which findings a task carries comes from the harness-written `.l4/fix.json` (`chore_findings`), never from the
    task's text.
* **Finding ids** are `F-` plus 8 hex digits of `sha256(title \0 criterion)` [V `verifier/types.py:45`]. A blocker
  titled `repository CI failed: <job>` with no criterion therefore has the same id in every round.
* **Step 0's CI blockers** [V `verifier/preconditions.py` `ci_blockers`]:
  * they come from the last `phase.changed{trigger: repository_ci_failed}` that no `verify.verdict` follows, so they
    fire only in the first round after the edge;
  * the detail is `ci_detail(job, stage, head, url, tail)`;
  * a fix task keeps the first 600 characters of the detail.
* **What the verifier can see** [V]:
  * it reads only the worktree ledger (`ladder._events` = `read_ledger(wb.ref.path)`);
  * `pr.ready` is appended *after* H is committed and pushed (`archive.handoff_hook:304`), so it lands in the
    pending ledger on the lock ref, not on the branch;
  * `verify.verdict{verdict}` is emitted by the verifier and committed with the round (`ladder.py:1054`).
* **The recorded tail** [V]:
  * it is `clip_log(job_log_text(trace), 40)`, at most 40 lines and 3,000 characters (`forge/gitlab.py:285`,
    `sweeper._tail`, `MAX_TAILS = 3`);
  * GitLab echoes each script line as `$ <command>` [V job 5604: lines 35, 52, 54 of `m19/b5-h1-test-job-5604.txt`];
  * the script runs in the section `step_script` [V fixture in `tests/unit/forge/test_gitlab_pipelines.py`];
  * a multi-line entry is echoed as `$ <first line> # collapsed multi-line command` [I GitLab runner];
  * `after_script` runs in its own section after the failure [I GitLab docs], so its `$` lines come after the failing
    step;
  * a failing pytest step prints more than 40 lines [I], so its `$` line is usually not in the tail.
* **The CI file reader** [V `ci/gitlab_jobs.py`]:
  * it reads names, stages and tags, resolves `extends`, and follows local includes one level deep;
  * it does not read `script` or `before_script`;
  * its `_Loader` reads `!reference` as plain data (a list), which would look like commands if read as a script.
* **Gate runner** [V `gates/runner.py:3, 97`]:
  * commands are split with `shlex` and never run through a shell;
  * `Workbench._next_gate_log` uses the gate name raw in the log file name (`workbench.py:264`).
* **The M0 gates** use `.venv/bin/…`, not `uv run` [V `init/ecosystem.py:14`]. Inside the agent sandbox `uv run` fails
  [V SPEC 1287]. With the network off in the gate sandbox [U].
* **The freeze** [V `implementer/guards.py`, `tdd.run_green`]:
  * `restore_frozen` puts every manifest file back to the red commit;
  * `green.md` (v1) says "do not edit tests … report status blocked with one question of kind technical";
  * SPEC L4-IMP-002 says the same, and says nothing about what follows the answer [V `grep`];
  * `check_freeze` makes every frozen file changed between red and green a blocker (`integrity.py:252`).
* **Answers** [V `clarifier/clarifier.py:169`, `specs/questions.py:513–532`]:
  * `question.answered{id, by, answer_sha256}` is recorded at re-entry;
  * `effective_answer` is the human's text for `answered` and the clarifier suggestion for `accepted`;
  * `answered_by` is `human` for both;
  * `Question.blocking_tasks` holds the task keys.
* **Live F5** [V `m19/b3-…-questions-at-cf6c2f7.md`]: Q-002 was `accepted`, and its suggestion names
  `tests/test_notices.py:8`. Green asked again (Q-003).
* **Zero-value runs** vary functions only, not module constants (`stubs.zero_value_variant`) [V], so `zeroed_run`
  cannot decide a corrected test of a constant such as F5's `RETURN_POLICY`.
* **The judge's input** [V `ladder._git_diff`, `judge.py`]:
  * the diff `base...head` excludes `**/.l4/**` but not the unit's `verification.md`;
  * `PROMPT_VERSION = 4`;
  * step 1 already knows which files only people changed (`run.scope.files[].human`, sha10, from
    `evidence/collect._human_commit`).
* **Sweep trace** [V `ci/sweeper.py:126`]: `_UnitRun` opens its `LedgerWriter` with no observer. Only the orchestrator
  passes `observers=[trace]` (`orchestrator.py:943`).
* **`question.raised` without `title`** [V]: the verdict questions (`verdicts.py:549`) and both intake emitters
  (`orchestrator.py:344, 354`). `progress._raised` prints `_clip(None)`, which is `None`.
* **Marker quote** [V `init/pytest_marker.py:149`]:
  * `_quote`'s regular expression excludes both quote characters inside a string;
  * in the last-element split, `_edit_pyproject` reads a `#` inside a string as a comment, so the re-parse check
    refuses that edit (no corruption) [V by reading].
* **Runners** [V `setup/gitlab.py:174`]:
  * the runner rows read `projects/:id/runners`;
  * instance runner rows print the type and the warning text, and no tags;
  * `GET runners/12` returns `tag_list` [V `m18/s2-runner-12.txt`]; the list endpoint omits it [I GitLab docs].
* **Watch** [V `ci/watch.py:68–73`]: `watch_pipeline` re-raises every `AdminError` that is not a 5xx error.
  * The Mintkey wrapper fetches one brokered JWT, which lives about 600 s [V m18 F2].
  * `connect_gitlab` is shared by `setup gitlab` and `ci watch` [V].
* **Lint advice** [V `gates/dryrun.py:41`, `gates/suggest.py:52`]:
  * `narrow_ruff` adds `--select F,E9` and keeps the paths;
  * when that fails, the advice is "set gates.lint to []".
* **Init** [V `init/init.py:288–334`, `init/ecosystem.py:49`]:
  * `proposal.todos` are written only as `# TODO:` lines in the config;
  * the closing line is the fixed text "commit .l4/, .gitignore and the CI file", even when the marker edited
    `pyproject.toml`, `pytest.ini` or `conftest.py`.

## Decisions

1. **C1: where the failing step comes from.** This deviates from the task's literal rule, for two reasons (Facts): the
   `$` line of a long step falls out of the 40-line tail, and an `after_script` echo is the last `$` line.
   * The sweep records it when it reads the log: `ci.failed.jobs[].step` is the last `$ ` line inside the
     `step_script` (or legacy `build_script`) section of the raw trace, without `$ `. It is at most 300 characters and
     redacted.
   * The task's rule (the last `$ ` line of the recorded tail) stays as the fallback, for ledgers written before
     M1.10 and for traces without section markers.
   * The port gains `job_log(job_id, max_lines) -> JobLog(tail, step)`. `job_log_tail` stays as `job_log(...).tail`,
     so one trace fetch serves both.
   * GitHub returns `step=None`: an Actions log has no `$` echo, so its jobs are skipped with a reason.
2. **C1: re-derived, never trusted.** The recorded step is data from a log that agent-written code printed into, so
   it only *selects* a command. The command that runs is the matching entry of the project's CI file at H, which is
   member-written like the specs. At step 0 the verifier derives `CiStep(job, command | None, reason)`, pure. It refuses
   (a skip with that reason) when:
   * no step was recorded and the tail has no `$` line;
   * the job name is not a key of `.gitlab-ci.yml` or its local includes at H (a `parallel: matrix` name, or a job
     defined in a remote, project, template or component include);
   * the job's `script` or `before_script` (own, through `extends`, or `default:`) uses `!reference` or another
     custom tag. The script reader keeps custom tags as a `Tagged` value, which refuses; it does not flatten them as
     CI-002's reader does;
   * the step is not exactly one entry of `before_script + script` after stripping (**the log and the file
     disagree**), or that entry has a newline, or the echo ends with `# collapsed multi-line command`;
   * the command is not runnable without a shell:
     * a `$`, a backtick, `|`, `&`, `;`, `<`, `>`, `(`, `)`, `*`, `?`, `[`, `{`, `~`, or a `\` outside quotes;
     * `shlex.split` fails;
   * a token is in the denylist:
     * the words `docker`, `docker-compose`, `podman`, `kubectl`, `helm`, `ssh`, `scp`, `rsync`, `curl`, `wget`,
       `sudo`, `apt`, `apt-get`, `apk`, `yum`, `dnf`, `brew`, `twine`, `terraform`, `aws`, `gcloud`, `az`;
     * the pairs `git push|fetch|clone|pull`, `pip install`, `uv sync|pip|publish`, `npm install|ci|publish`,
       `poetry install|publish`, `cargo publish`;
     * any token containing `deploy`, `release`, `publish` or `upload`;
   * the CI files read at H differ from the base's and a harness commit (`vcs.authorship.is_harness`) in `base..H`
     touched one of them. Such a change would be an agent's. A person's change on the unit branch is member-written
     and allowed.
3. **C1: `ci.step` records the decision.**
   * Event: `ci.step{job, head, step, command, status: derived|skipped|reproduced, reason, source:
     ".gitlab-ci.yml@<H10>"}`. The last event per `(head, job)` wins.
   * Step 0 writes `derived` or `skipped` once per `(head, job)`.
   * The blocker's detail names the step first ("failing step: `<command>` (job `<job>` at <H10>)"), so the fix task's
     600 characters carry it (F2's other candidate: "let the fix step see the CI command").
4. **C1: reproduce first, in the chore.** A chore whose findings include the id of `repository CI failed: <job>`, with
   a `derived` or `reproduced` step, runs the gate `repository-ci:<job>` at its clean base, after `gates.setup`:
   * It counts as **reproduced** when the exit code is not 0 and the local log holds at least one line of the CI log
     after the step line. Lines are compared normalised (whitespace collapsed, at least 10 characters, timing lines
     such as `in 0.04s` dropped). The chore then writes `ci.step{status: reproduced}` and the gate is a must-pass of
     this chore.
   * It is **skipped** (`ci.step{status: skipped}`) with the reason `exit 126/127: not runnable in the gate sandbox`,
     `passes at the fix's base: does not reproduce` or `fails differently in the gate sandbox (no line of the CI
     error)`. The chore then behaves as today.
   * This rule also covers what the parse cannot see: job `variables:`, the job's `image:`, and `uv run` with the
     network off [U].
   * After the agent step, a failing must-pass gate fails the attempt. The reason is `repository-ci:<job> still fails
     (<reason>)` plus the last 15 lines of its log, so the retry prompt shows the error.
5. **C1: the rounds that follow.** Step 2 runs, after `typecheck`, one gate per `ci.step{status: reproduced}` of the
   active window, and a failure is the blocker `repository CI failed: <job>` (same id, so the next chore finds its step).
   * The window starts at the last review edge, when its trigger is `repository_ci_failed`.
   * It ends at the first `verify.verdict{verdict: PASS}` after that edge. `pr.ready` cannot be the marker, because the
     branch never holds it (Facts).
   * A later review edge with another trigger (`commit_after_handoff`, `spec_edit_after_handoff`) also ends it.
   * Only `reproduced` steps run: a `derived` step that no chore checked could fail for environmental reasons.
6. **C2: what unfreezes.** A frozen path is unfrozen for task T's green when **all** of these hold:
   * a question in `questions.md` has Status `answered` or `accepted` (`answered_by == "human"`). `answered-by-clarifier`
     never unfreezes;
   * a `question.answered{by: human}` was recorded for it, with the `answer_sha256` of the file's current effective
     answer;
   * its kind is not `verdict`, and its `blocking_tasks` meet `task_scope(T)`;
   * its effective answer names the path as a token: a repository-relative path, optionally followed by `:<line>` or
     sentence punctuation;
   * the path is a `test`-kind entry of T's freeze manifest.

   A named support file (`conftest.py`, a fixture) or ignore file stays frozen, and the trace says so. At most 3 paths
   per question. The record is `task.unfrozen{task, paths, question, answer_sha256, red_sha}`, written before the
   attempt.
7. **C2: still TDD.**
   * The red ids stay must-pass in the corrected file (`check_green`), so a renamed test fails green.
   * Before the green commit, the red ids in each unfrozen file must still **fail at the red commit's production code**:
     the production files green changed are swapped in place to their red-commit content, the test gate runs, and they
     are put back with a sha256 check (the pattern of `zeroed_run`, D7).
   * A corrected test that passes there fails the attempt: "the corrected test no longer discriminates".
   * "Re-frozen after green": the unfreeze covers only T's green attempts while that answer is current. Every later
     step freezes the path again (`proved_test_files` reads `task.red_ok.frozen`, and `manifest_at_head` takes the
     green version).
   * `check_freeze` exempts exactly the unfrozen paths of T between T's red and green commits, and lists them in
     `verification.md` as "unfrozen by Q-002 (human): tests/test_notices.py".
8. **C2: the prompt.** `green.md` gains one sentence: "If the prompt lists a test file as unfrozen by a human answer,
   you may change that file as the answer says; every other test stays frozen." Its version goes 1 → 2, and the lock
   is regenerated. The unfrozen paths are listed in a harness-written block of the green prompt, with the question id.
9. **C3: the judge's diff and context.**
   * `_git_diff` adds one `:(literal,exclude)<dir>/verification.md` per family unit dir (`_unit_dirs`). A
     `verification.md` elsewhere is project content and stays.
   * The prompt gains a block `## Owner changes (changed by people on the unit branch, not the unit's work)` from
     `run.scope.files` with `human` set (`path (commit <sha10>)`, at most 40 lines). The block is absent when there are
     none or when step 1's scope did not run.
   * Rubric line: "Files under Owner changes were changed by the project's people, not by the implementer: judge the
     criteria on the committed code as it is, owner changes included, but raise no finding about an owner change
     itself."
   * `PROMPT_VERSION` 4 → 5, and the lock is regenerated.
10. **C4.** `_UnitRun`'s writer gets a `ProgressTrace` observer filtered to `ci.failed` and `ci.preexisting`. An
    unfiltered trace would print a `run.started` line per unit per sweep.
11. **C5.** The three emitters add `title` (the question's own title, redacted like the file). For a ledger without a
    title, `progress._raised` falls back to `target` (verdict questions) or prints no `: …` part.
12. **C6.** One TOML string scanner (`_strings(text, start, end)`: basic, literal and both multi-line forms, and
    comments) serves `_close_of`, `_quote` (the opener of the last string) and the last-line comment split.
13. **C7.** For each usable runner (at most 5, then `and n more`), `GET runners/:id` gives `tag_list` and
    `run_untagged`. Every runner row then ends with `tags: agentic, ai, opencode`. A 403 or 404 says `tags: not
    readable (<status>)` and changes no verdict.
14. **C8.** `AdminApi(refresh=…)`:
    * on a 401, call `refresh()` once for that request, `add_secret` the new value, and send the request again;
    * a second 401 raises as today. A request that got a 401 did not land, so a POST is retried too;
    * the CLI option `--token-command` (env `L4_TOKEN_COMMAND`) is on both `setup gitlab` and `ci watch`;
    * the command is `shlex`-split and run without a shell, with a 30 s timeout and stdout captured;
    * its one non-empty stdout line is the credential, which `app.redactor` adopts as `setup:credential-<n>`. A
      failure or an empty output re-raises the 401 with `token command failed (exit n)`, and never shows the output;
    * the wrapper gains `--print-jwt`: it fetches one JWT and prints it only when stdout is not a terminal. It passes
      `--token-command "<its absolute path> --print-jwt"`.
15. **C9.**
    * `project_dirs(repo, pyproject)` lists the source and test dirs that exist, at most 4, in order:
      * pyproject `tool.ruff.src`;
      * `tool.pytest.ini_options.testpaths`;
      * hatch `packages`, setuptools `packages.find.where` and `package-dir`;
      * then `src`, a top-level package named after the project, `tests` and `test`.
    * `narrow_ruff_paths(command, dirs)` replaces the positional paths of the narrowed `ruff check`, reading a known
      set of value options (`--select`, `--extend-select`, `--ignore`, `--extend-ignore`, `--exclude`,
      `--extend-exclude`, `--config`, `--line-length`, `--target-version`, `--output-format`, `--per-file-ignores`,
      `--cache-dir`). It returns None for anything it cannot read.
    * The dry run runs it as a third gate `lint-narrow-paths` only when the rule-narrowed run fails.
16. **C10.**
    * Init prints each `# TODO:` it wrote as `todo: <text>` on stderr, before the closing line.
    * The closing line is computed from the plan:
      * `.l4/` for everything under it;
      * `.gitignore` when extended;
      * the CI file when created or edited;
      * the marker file when the marker edit writes;
      * the Serena seed files.
    * It is printed as `next: … then commit .l4/, .gitignore, .gitlab-ci.yml and pyproject.toml`.

## Build lines

Line format: `n. ids — what · test (write it first, see it fail) · code · verify`.

**Stage A — the repository CI step (C1)**

1. forge-and-ci 1.1, L4-ARC-002 (d) — `JobLog(tail, step)` and `job_log(job_id, max_lines)` on the port.
   * GitLab: `step` = the last `$ ` line inside `step_script`/`build_script` of the raw trace, read before
     `job_log_text` strips the markers; `job_log_tail` = `job_log(...).tail`.
   * FakeGitLab and LocalForge serve a scripted step; GitHub returns `step=None`.

   Tests in `tests/unit/forge/test_gitlab_pipelines.py`:
   * `::test_failing_step_is_the_last_echo_in_step_script` (the job-5604 fixture gives `uv run ruff check --select
     E501 --line-length 92 src`);
   * `::test_an_after_script_echo_is_not_the_failing_step`;
   * `::test_a_trace_without_sections_has_no_step`.

   Code: `src/l4/forge/base.py`, `src/l4/forge/gitlab.py`, `src/l4/forge/github.py`, `src/l4/forge/local.py`,
   `tests/unit/forge/conftest.py`. Verify: `uv run pytest tests/unit/forge -q`.
2. L4-ARC-002 (d), L4-OBS-002 — the sweep records `ci.failed.jobs[].step` (redacted, ≤ 300 characters) next to
   `tail` · `tests/unit/ci/test_sweeper.py::test_ci_failed_records_the_failing_step_redacted` (a token-shaped string in
   the step never reaches the ledger) · `src/l4/ci/sweeper.py` · `uv run pytest tests/unit/ci -q`
3. forge-and-ci 2.19 — `job_script(text, load, name) -> JobScript(before, script) | ScriptRefusal(reason)` in
   `ci/gitlab_jobs.py`:
   * `extends` resolved for `script` and `before_script`, and `default: before_script` applied;
   * one level of nested lists flattened;
   * custom tags kept as `Tagged`, which refuses;
   * CI-002's reader unchanged.

   Tests in `tests/unit/ci/test_gitlab_jobs.py`:
   * `::test_script_and_before_script_through_extends_and_default`;
   * `::test_a_reference_tag_refuses`;
   * `::test_a_job_from_a_remote_include_refuses`;
   * the existing tests unchanged.

   Code: `src/l4/ci/gitlab_jobs.py`. Verify: `uv run pytest tests/unit/ci/test_gitlab_jobs.py -q`.
4. L4-ARC-002 (d), L4-SEC-004 — `l4/ci/failing_step.py`, pure:
   * `echoed_step(tail)` (the fallback);
   * `unrunnable(command) -> reason | None` (metacharacters, `shlex`, the denylist);
   * `derive_step(job, step, tail, script) -> CiStep(job, command, reason)` (decision 2);
   * `shared_error_line(ci_tail, step, local_log) -> bool` (decision 4).

   Tests in `tests/unit/ci/test_failing_step.py`:
   * `::test_the_live_e501_step_is_derived`;
   * `::test_log_and_file_disagree_refuses` (an agent-printed `$ rm -rf x` that is no script entry);
   * `::test_ci_variables_docker_and_deploy_refuse`;
   * `::test_multi_line_and_collapsed_echo_refuse`;
   * `::test_shell_operators_refuse`;
   * `::test_the_tail_fallback_takes_the_last_echo`;
   * `::test_a_shared_error_line_reproduces_and_a_different_failure_does_not`.

   Code: `src/l4/ci/failing_step.py`. Verify: `uv run pytest tests/unit/ci/test_failing_step.py -q`.
5. L4-VER-002 step 0, SCN-ARC-14 — step 0 derives the step for each CI blocker:
   * the CI files are read at H (`show_blob`), with the base comparison and the harness-commit refusal of decision 2;
   * it emits `ci.step{derived|skipped}` once per `(head, job)`;
   * the blocker's detail starts with the failing step.

   Tests in `tests/unit/verifier/test_preconditions.py`:
   * `::test_ci_blocker_names_the_failing_step_and_records_ci_step`;
   * `::test_a_ci_file_a_harness_commit_changed_is_refused`;
   * `::test_a_ci_file_a_person_changed_on_the_branch_is_read_at_h`;
   * `::test_ci_step_is_recorded_once_per_head_and_job`.

   Code: `src/l4/verifier/preconditions.py`, `src/l4/verifier/ladder.py` (the step 0 closure emits). Verify:
   `uv run pytest tests/unit/verifier/test_preconditions.py tests/unit/verifier/test_fixunit.py -q`.
6. L4-GAT-001 — `_next_gate_log` makes the gate name a safe file name (`[^A-Za-z0-9._-]` → `_`, at most 60
   characters). Job names carry `/`, spaces, `:` and `..` · `tests/unit/implementer/test_workbench.py::test_a_gate_name_with_slashes_logs_inside_the_run_folder`
   · `src/l4/implementer/workbench.py` · `uv run pytest tests/unit/implementer/test_workbench.py -q`
7. L4-VER-006, L4-IMP-003 (D8), L4-IMP-002 (green checks) — the chore reproduces, then requires, `repository-ci:<job>`
   (decision 4). Tests in `tests/unit/implementer/test_single_phase.py`:
   * `::test_a_reproduced_ci_step_must_pass_after_the_chore` (attempt 1 leaves the long line: failed, and the retry
     reason holds the tool's error; attempt 2 fixes it: done);
   * `::test_a_step_that_passes_at_the_base_is_skipped_and_the_chore_runs_as_today`;
   * `::test_exit_127_is_skipped_with_its_reason`;
   * `::test_a_chore_without_a_ci_finding_runs_no_extra_gate`.

   Code: `src/l4/implementer/tdd.py` (`run_single`), `src/l4/ci/failing_step.py`. Verify:
   `uv run pytest tests/unit/implementer -q`.
8. L4-VER-002 step 2, L4-ARC-002 — `active_ci_steps(events)` (decision 5) and `run_build_gates(wb, ci_steps)`. A
   failure is the blocker `repository CI failed: <job>` with the same id, and a `GateLine` named `repository-ci:<job>`.
   Tests in `tests/unit/verifier/test_repository_ci_gate.py`:
   * `::test_the_round_after_the_chore_runs_the_reproduced_step`;
   * `::test_a_failing_step_is_the_same_finding_id`;
   * `::test_the_window_ends_at_a_pass_or_another_review_edge`;
   * `::test_derived_or_skipped_steps_do_not_run`.

   Code: `src/l4/verifier/gates.py`, `src/l4/verifier/ladder.py`, `src/l4/ci/failing_step.py`. Verify:
   `uv run pytest tests/unit/verifier/test_repository_ci_gate.py tests/unit/verifier/test_gates.py -q`.
9. SCN-ARC-14 end to end — `tests/unit/orchestrator/test_review_reentry.py::test_a_wrong_ci_fix_is_caught_by_the_repository_ci_gate`:
   * a FakeGitLab red pipeline whose trace fails on `python scripts/check_len.py src`, a script of the fixture repo
     named in its `.gitlab-ci.yml`;
   * the scripted chore first leaves the long line, then fixes it;
   * the trace and ledger show `ci.step` `derived` → `reproduced`, `gate repository-ci:test fail` then `pass`, then
     round n+1 runs it, PASS and H2.

   The existing `::test_ci_failure_on_h_runs_a_round_that_fails_at_step_0_and_spawns_a_fix_unit` is unchanged in
   meaning: its step is skipped with a reason. Code: whatever lines 1–8 missed. Verify:
   `uv run pytest tests/unit/orchestrator/test_review_reentry.py tests/unit/ci -q`.

**Stage B — an accepted answer unfreezes a red test (C2)**

10. L4-IMP-002, L4-QMD-005, L4-QMD-006 — `l4/implementer/unfreeze.py`: `unfrozen(questions, events, scope, manifest)
    -> Unfreeze(paths, question, answer_sha256, kept: [(path, why)])` (decision 6), pure. Tests in
    `tests/unit/implementer/test_unfreeze.py`:
    * `::test_the_live_q002_accepted_suggestion_unfreezes_its_test` (F5's text);
    * `::test_answered_by_clarifier_never_unfreezes`;
    * `::test_an_answer_edited_after_it_was_recorded_does_not_count`;
    * `::test_a_named_support_file_stays_frozen`;
    * `::test_a_question_of_another_task_or_a_verdict_does_not_count`;
    * `::test_path_tokens_with_line_and_punctuation`.

    Code: `src/l4/implementer/unfreeze.py`. Verify: `uv run pytest tests/unit/implementer/test_unfreeze.py -q`.
11. L4-IMP-002, L4-IMP-004, HB-11 — the green wiring:
    * `run_green` drops the unfrozen paths from the manifest for the attempt and emits `task.unfrozen`;
    * the prompt lists the paths;
    * `green.md` gets decision 8's sentence, `version: 2`, then `uv run python -m l4.templatelock --write`.

    Tests:
    * `tests/unit/implementer/test_tdd_green.py::test_an_unfrozen_test_edit_is_kept_and_recorded` (no
      `guard.test_tamper` for that path, which stays a test of the task);
    * `::test_other_frozen_tests_are_still_restored`;
    * `tests/unit/implementer/test_prompt.py::test_green_prompt_lists_the_unfrozen_paths`;
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/implementer/tdd.py`, `src/l4/implementer/prompt.py`, `src/l4/implementer/templates/green.md`,
    `src/l4/templates.lock.json`. Verify: `uv run pytest tests/unit/implementer tests/unit/test_template_lock.py -q`.
12. L4-IMP-002, L4-VER-009 — `fails_at_red(wb, red_sha, ids) -> list[str]` (decision 7):
    * production files are swapped in place to their red content and put back with a sha256 check;
    * green fails when a red id of an unfrozen file passes there.

    Tests in `tests/unit/implementer/test_tdd_green.py`:
    * `::test_a_corrected_test_that_passes_at_red_is_rejected` (`assert True`);
    * `::test_a_corrected_test_that_fails_at_red_is_accepted`;
    * `::test_the_swap_is_restored_when_the_gate_raises`.

    Code: `src/l4/implementer/discrimination.py`, `src/l4/implementer/tdd.py`. Verify: as line 11.
13. L4-VER-002 step 1, L4-VER-005 — `check_freeze` exempts T's unfrozen paths between T's red and green, and lists
    them (`IntegrityReport.unfrozen`, a `verification.md` line, the step-1 note `(+n unfrozen by human answers)`).
    Tests:
    * `tests/unit/verifier/test_integrity.py::test_a_test_unfrozen_by_a_human_answer_is_listed_not_a_blocker`;
    * `::test_an_unfrozen_path_of_another_task_is_still_a_blocker`;
    * `tests/unit/verifier/test_report.py::test_unfrozen_tests_are_listed`.

    Code: `src/l4/verifier/integrity.py`, `src/l4/verifier/types.py`, `src/l4/verifier/report.py`. Verify:
    `uv run pytest tests/unit/verifier/test_integrity.py tests/unit/verifier/test_report.py -q`.
14. F5 end to end — `tests/unit/orchestrator/test_reentry.py::test_an_accepted_answer_to_change_a_frozen_test_lets_green_finish`:
    * green raises Q-002 naming the test;
    * the human sets `accepted`;
    * the next run resumes at green, the scripted agent corrects the test and the code, the task is done and no Q-003
      is raised;
    * the round's integrity is ok with the path listed.

    Code: whatever lines 10–13 missed. Verify: `uv run pytest tests/unit/orchestrator/test_reentry.py -q`.

**Stage C — the judge on re-verification (C3)**

15. L4-VER-001, L4-VER-005 — `_git_diff` excludes `<dir>/verification.md` of every family unit dir (decision 9).
    Tests:
    * `tests/unit/verifier/test_judge_step.py::test_the_judge_diff_has_no_verification_md_of_the_family`;
    * `::test_a_project_verification_md_elsewhere_stays_in_the_diff`.

    Code: `src/l4/verifier/ladder.py`. Verify: `uv run pytest tests/unit/verifier/test_judge_step.py -q`.
16. L4-VER-001, L4-SEC-004 — the `Owner changes` block and its rubric line, `PROMPT_VERSION = 5`, then
    `uv run python -m l4.templatelock --write`. Tests:
    * `tests/unit/verifier/test_prompt.py::test_owner_changes_block_and_rubric_line` (the block is absent when empty,
      the line always present);
    * `tests/unit/verifier/test_judge_step.py::test_files_only_people_changed_reach_the_judge_as_owner_changes`;
    * `tests/unit/test_template_lock.py`.

    Code: `src/l4/verifier/judge.py`, `src/l4/verifier/ladder.py`, `src/l4/templates.lock.json`. Verify:
    `uv run pytest tests/unit/verifier/test_prompt.py tests/unit/verifier/test_judge_step.py tests/unit/test_template_lock.py -q`.

**Stage D — trace (C4, C5)**

17. L4-OBS-001 — the sweep's writer gets the filtered trace (decision 10) ·
    `tests/unit/ci/test_sweeper.py::test_ci_failed_prints_the_warning_line_once` (caplog holds `repository CI failed on
    <H10>: test (pipeline <id>); l4 run re-verifies` and no `run … started` line) · `src/l4/ci/sweeper.py`,
    `src/l4/progress.py` (the filter) · `uv run pytest tests/unit/ci tests/unit/obs -q`
18. L4-OBS-001, L4-VER-013 — `title` on the three `question.raised` emitters, and the fallback (decision 11). Tests:
    * `tests/unit/obs/test_progress.py::test_question_raised_prints_the_title_or_the_target` (never `None`);
    * `tests/unit/verifier/test_verdicts.py::test_a_verdict_question_event_carries_its_title`;
    * `tests/unit/orchestrator/test_scenario_lint.py::test_the_lint_question_event_carries_its_title`.

    Code: `src/l4/verifier/verdicts.py`, `src/l4/orchestrator.py`, `src/l4/progress.py`. Verify:
    `uv run pytest tests/unit/obs tests/unit/verifier/test_verdicts.py tests/unit/orchestrator/test_scenario_lint.py -q`.

**Stage E — adoption (C6–C10)**

19. L4-INS-002 — one TOML string scanner for `_close_of`, `_quote` and the comment split (decision 12). Tests in
    `tests/unit/init/test_pytest_marker.py`:
    * `::test_a_double_quoted_entry_holding_single_quotes_keeps_double` (F3's `"… -m 'not ui'"`);
    * `::test_a_hash_inside_the_last_string_is_not_a_comment`;
    * the existing tests unchanged.

    Code: `src/l4/init/pytest_marker.py`. Verify: `uv run pytest tests/unit/init/test_pytest_marker.py -q`.
20. L4-INS-006 — the runner rows name their tags (decision 13). Tests in `tests/unit/setup/test_gitlab_setup.py`:
    * `::test_an_instance_runner_row_names_its_tags` (runner 12's live answer);
    * `::test_unreadable_runner_details_say_so_and_change_nothing`.

    Code: `src/l4/setup/gitlab.py`. Verify: `uv run pytest tests/unit/setup -q`.
21. L4-INS-006 — `AdminApi(refresh=…)`: one refresh and one retry per request on a 401 (decision 14). Tests:
    * `tests/unit/forge/test_gitlab_admin.py::test_a_401_refreshes_once_and_retries`;
    * `::test_a_second_401_raises`;
    * `::test_the_new_credential_is_scrubbed_from_errors`;
    * `tests/unit/ci/test_watch.py::test_watch_outlives_a_token_expiry_with_a_refresh` (401 after the token's 600 s
      on a fake clock; the watch ends `success`).

    Code: `src/l4/forge/gitlab_admin.py`, `src/l4/ci/watch.py` (none expected). Verify:
    `uv run pytest tests/unit/forge/test_gitlab_admin.py tests/unit/ci/test_watch.py -q`.
22. L4-INS-006 — `--token-command` and `L4_TOKEN_COMMAND` on `setup gitlab` and `ci watch`, and the wrapper's
    `--print-jwt`. Tests:
    * `tests/unit/setup/test_gitlab_setup_flow.py::test_token_command_refreshes_and_its_value_is_never_printed`;
    * `::test_a_failing_token_command_reraises_the_401_without_its_output`;
    * `tests/unit/forge/test_mk_scripts.py::test_print_jwt_prints_to_a_pipe_and_refuses_a_terminal` (fake `curl` on
      `PATH`);
    * `::test_the_wrapper_passes_its_own_token_command`.

    Code: `src/l4/setup/gitlab.py`, `src/l4/cli.py`, `src/l4/commands.py`, `scripts/forge/mk-l4-setup-gitlab.sh`.
    Verify: `uv run pytest tests/unit/setup tests/unit/forge/test_mk_scripts.py -q` and
    `bash -n scripts/forge/mk-l4-setup-gitlab.sh`.
23. L4-DOC-001 (GATE-001), L4-GAT-003 — `project_dirs(repo, pyproject)` and `narrow_ruff_paths(command, dirs)`
    (decision 15). Tests in `tests/unit/gates/test_dryrun.py`:
    * `::test_project_dirs_from_pyproject_then_conventional_dirs`;
    * `::test_narrow_ruff_paths_replaces_the_dot_and_keeps_options`;
    * `::test_an_unknown_option_shape_gives_none`.

    Code: `src/l4/gates/pyproject.py`, `src/l4/gates/dryrun.py`. Verify: `uv run pytest tests/unit/gates -q`.
24. L4-DOC-001 (GATE-001) — the dry run's third lint run `lint-narrow-paths`, `GateRun.narrowed_paths` and
    `narrowed_paths_ok`, and the advice "… fails even narrowed to F,E9; on the source and test directories (`<cmd>`)
    it passes: use that in gates.lint". The old text stays when that run also fails. Tests:
    * `tests/unit/gates/test_suggest.py::test_lint_advice_narrows_paths_before_dropping_lint`;
    * `tests/unit/gates/test_dryrun.py::test_a_path_narrowed_run_follows_a_failing_rule_narrowed_one`.

    Code: `src/l4/gates/dryrun.py`, `src/l4/gates/suggest.py`. Verify: `uv run pytest tests/unit/gates tests/unit/doctor -q`.
25. L4-GAT-003, L4-OBS-001 — init prints `todo:` lines and a closing line computed from the plan (decision 16).
    Tests in `tests/unit/init/test_init_cli.py`:
    * `::test_init_prints_the_uv_lock_and_ruff_reminders`;
    * `::test_the_closing_line_names_every_file_to_commit` (with the marker in `pyproject.toml`, then in `conftest.py`).

    Code: `src/l4/init/init.py`. Verify: `uv run pytest tests/unit/init -q`.

**Stage F — close-out**

26. Close-out:
    * `uv run pytest -q` in the tool's background mode (never piped into `tail`), then `uv run ruff check .` and
      `uv run ruff format --check .`;
    * `uv run python -m l4.templatelock --write` leaves no diff (judge v5, implementer/green v2);
    * SPEC edits, small and local:
      * L4-ARC-002: the failing step of a `repository CI failed` job is re-run as `repository-ci:<job>` when it can be
        derived safely and reproduces, else judge-only with a recorded reason;
      * L4-IMP-002: a human answer that names a frozen test file unfreezes exactly that file for the task's next green,
        and the corrected test must still fail at the red commit;
      * L4-VER-002 step 1: unfrozen paths are listed;
      * L4-INS-006: "with their type **and tags**", `--token-command`;
      * the GATE-001 row: path narrowing;
      * 12.1: the events `ci.step`, `task.unfrozen`, `question.raised{title}` and `ci.failed.jobs[].step`;
    * openspec: no new ticks are expected (C1–C10 refine built tasks). Pointers in forge-and-ci 2.44 gain
      `src/l4/ci/failing_step.py`;
    * write `docs/plan/m110-progress.md`.

## Live protocol

Run on `example-group/dummy-agentic` (118) with runner `l4-runner`, then on the laptop copy of sample-consumer.
Save every job log (ANSI and section markers stripped) under `docs/live/m110/`, and token-scan them as in M1.9. The
92-character step already exists on the dummy's `main` (M1.9 "left behind").

| Step | Action | Expected |
|---|---|---|
| 0 | `uv run pytest -q` at the M1.10 head | suite green |
| 1 | push `l4 upgrade` to M1.10, the seed `add-pickup-notice` (one constant-free function returning a 100-character text, one scenario) and a throwaway seed with two scenarios of the same WHEN | the upgrade job is green. The throwaway seed's intake prints `question Q-001 raised (ambiguous): Scenarios "…" and "…" conflict` (C5); remove it in the next push. The pickup unit goes red → green → PASS, H red on E501 |
| 2 | the `*/30` schedule (or a web pipeline on `main`) | sweep: WARNING `repository CI failed on <H10>: test (pipeline <id>); l4 run re-verifies` (C4); `ci.failed.jobs[0].step` = `uv run ruff check --select E501 --line-length 92 src`. Run: step 0 FAIL, `ci.step{derived}`; the fix task's detail starts with the failing step; the chore's `gate repository-ci:test` at its base → `ci.step{reproduced}` [U: `uv run` in the gate sandbox; if it does not reproduce, `ci.step{skipped, reason}` is recorded and the run goes on judge-only, which is itself the C1 fallback to check] |
| 3 | none (same job) | a wrong fix fails `repository-ci:test` and is retried with the E501 line in the prompt. Round n+1 runs `repository-ci:test` (pass), PASS, H2; H2's `test` job green |
| 4 | `scripts/forge/mk-l4-setup-gitlab.sh --project 118 --dry-run` | runner row `runner #12 (instance_type, online)` … `tags: agentic, ai, opencode` (C7). The wrapper passes `--token-command`, which a run without a 401 never calls |
| 5 (C2, opportunistic) | if a green step raises a question asking to change a frozen test (live F5 was n = 1), set it `accepted` | the next run prints `task … unfrozen by Q-…: <path>`, green finishes, no second question, and `verification.md` lists the path. If no such question comes up, C2 rests on line 14 |
| 6 (C9, C10, laptop) | on a local copy of sample-consumer at `fed8f84`: `init --ci gitlab --vendor`, then `doctor --adoption` | init prints the `todo:` lines and a closing line naming `.l4/`, `.gitignore`, `.gitlab-ci.yml` and the marker file. GATE-001's lint advice names a `--select F,E9 <src> <tests>` command that passes. Re-measure the command count (M1.8: 6 commands and 1 edit; target 5 and 0) |
| cleanup | leave the pickup MR for the maintainer; delete the throwaway seed | `nothing to do` |

C8 is not run live: no check pipeline outlives the 600 s token. It rests on lines 21–22, and the [U] stays in the risks.
Spend: Codex 3–4 agent steps (red, green, 1–2 chore attempts); Claude 2 judge calls, about $0.20 [I, M1.9 rates].

## Risks

* **`uv run` in the gate sandbox** [U]. If it cannot run offline, every `uv run …` step is skipped as "fails
  differently", and C1 falls back to today's behaviour. This is recorded per job, not silent. A later fix would map
  `uv run X` to `.venv/bin/X`; that is not done here, because rewriting a member's command is a decision.
* **The reproduce rule can miss.** A tool that prints absolute paths (`/builds/…` in CI, the worktree locally) shares
  no line, and the step is skipped (judge-only). It can never make a wrong fix pass; it can only fall back.
* **An agent can steer the step choice** by printing a `$ ` line in its test output. The step then selects another
  member-written entry of the same job, or none. The denylist and the reproduce rule bound what runs. The failure mode
  is "skipped", not "ran something unvetted".
* **Cost.** One more gate per chore attempt and per round in the window, bounded by `gates.timeout`.
* **C2 widens what green may touch.** It is bounded to `test`-kind paths named in a human-recorded answer to a question
  that blocks the task, and the corrected test must still fail at the red commit. A human's answer that asks to delete
  or rename a test makes green fail ("red tests still failing"). The human then answers again.
* **C3 could hide a real problem in an owner change.** The criteria are still judged on the committed code, and
  integrity, tests and scope stay attributed (M1.9 G3). Only findings *about* owner changes are dropped.
* **C8 runs a local command** given by the operator (`--token-command`), with the same trust as the shell that
  starts `l4`. The wrapper prints a JWT only to a pipe.
* **C9's directory guess** can be wrong. The narrowed run then fails and the old advice stands: never worse than today.

## Overlap

No other milestone is in flight [V: every other worktree branch (`fu`, `hb`, `m12`–`m19`, `m1x-seams`,
`sec-guidance`) is an ancestor of `main` at `8e1c562`]. Shared files change at small seams:
* `ladder.py`: step 0's emit, step 2's extra gates, `_git_diff`, and one judge keyword;
* `tdd.py`: `run_single` and `run_green`;
* `sweeper.py`: `step` and the observer;
* `gitlab.py`, `gitlab_jobs.py`, `integrity.py`, `judge.py`, `progress.py`, `verdicts.py`;
* `orchestrator.py`: two emitters;
* `pytest_marker.py`, `setup/gitlab.py`, `gitlab_admin.py`, `cli.py`, `dryrun.py`, `suggest.py`, `init.py`.

The logic lives in the new modules `ci/failing_step.py` and `implementer/unfreeze.py`.
