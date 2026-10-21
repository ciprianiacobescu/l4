## Context

`proposal.md` describes the incident. This change makes the evidence of a red project CI job the failing step's own
output, names that step in the finding, and lets the gates see the CI's identity variables (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`), so a test that only CI fails fails in the unit's gates first. It is built for 0.4.21 on top of the released 0.4.20 (da3e7c28).

Labels: [V] verified in the code, the tests or a log of this repository at da3e7c28 (file:line); [I] inferred; [U]
unknown, not checked here. The incident's own facts (the job, the test, the counts, the fix task's text) come from the
report of 2026-10-20; this design does not re-read the consumer repository.

How the evidence is lost today [V]:
- The sweep reads at most `MAX_TAILS` = 3 red jobs (`src/l4/ci/sweeper.py:123,865`). `_log` (`:898-908`) calls
  `forge.job_log(job_id, 40)`, redacts the tail and the step with the run's redactor, keeps the last 3,000 characters
  of the tail and 300 of the step, and `ci.failed.jobs[]` records `{name, stage, url, tail, step}` (`:874-882`; GitHub
  adds `workflow`, `event`). Redaction happens here and only here.
- `GitHubForge.job_log` is `JobLog(job_log_tail(...), None)` (`src/l4/forge/github.py:598-600`); `job_log_tail`
  (`:729-747`) follows the log redirect without the token and returns `clip_log(text, 40)`.
- `clip_log` (`src/l4/forge/base.py:165-171`) removes ANSI codes and carriage returns, keeps the last 40 lines and the
  last 3,000 characters. It does not remove GitHub's per-line timestamp or the byte-order mark of line 1 (both are in
  every log under `docs/live/`, e.g. `docs/live/feedback/runs/38329266005-job-115075028141.log:1`).
- A GitHub job log is: the set-up lines; per step a `##[group]Run <first line>` header, the step's script, `shell:`,
  `env:` (secrets as `***`, other values in clear) and `##[endgroup]`, then the step's output and, for a failed `run:`
  step, `##[error]Process completed with exit code N.`; steps of `if: always()` after it; then one `Post job
  cleanup.` block per action with a post step; then `Cleaning up orphan processes` (the log above, lines 42-223). In
  that log the failing step (`exit code 128`, line 176) is outside the last 40 lines, which hold an `always()` step,
  the artifact upload and the checkout cleanup.
- `ci_detail` (`src/l4/verifier/preconditions.py:76-88`) writes `job … failed on the hand-off commit H (url). Log
  ends: …<the last max(80, min(300, …)) characters of the flattened tail>.`, then a blank line and the whole tail.
- What the implementer sees: an OpenSpec fix unit's task line is the finding's title only (`_tasks`,
  `src/l4/specs/openspec.py:470-476`); its proposal carries the flattened detail, up to 5,000 characters
  (`_plain(f.detail, MAX_DETAIL_CHARS + MAX_DECISION_CHARS + 400)`, `:460`). A Kiro fix unit's requirements carry
  `_line(finding.detail, MAX_ITEM_CHARS)` (`src/l4/specs/kiro.py:557,641,669`). Both replace `[`/`]` by `(`/`)`, which
  is where the incident's `##(warning)` came from. So the whole 40-line tail usually reaches the implementer; in the
  incident those 40 lines held no line of the failure. A person's decision placed in front of a detail
  (`fixunit.py:109`) can push the detail's end out; its first 600 characters (`CI_TASK_CHARS`) always stay.
- The failing step: `derive_ci_steps` (`preconditions.py:134-160`) reads `.gitlab-ci.yml` at H only. For a GitHub job
  the recorded step is None, `named_step` falls back to the last `$ ` line of the tail, and `derive_step` records
  `no failing step in the log (no recorded step, no `$` line in the tail)`, or `.gitlab-ci.yml cannot be read at H`
  when a test printed a line that starts with `$ ` (`src/l4/ci/failing_step.py:137-160`).
- GitLab: `_read_trace` (`src/l4/forge/gitlab.py:90-123`) drops the runner's timestamps, section markers and the
  sections `upload_artifacts_on_failure`, `upload_artifacts_on_success` and `cleanup_file_variables` (`:72-75`). It
  keeps `after_script`, which runs after a failed script: `docs/runner/live-m0-2026-10-04-job-5420.txt:88-106` has an
  `l4 status` table between the traceback and `ERROR: Job failed: exit status 1`. [I] The cache upload of a failed job
  (`archive_cache_on_failure`, a gitlab-runner stage name not seen in this repository's traces) comes after the script
  as well.

How the gates hide CI behaviour today [V]:
- `_base` (`src/l4/sandbox/env.py:19-29`) builds both environments: `PATH`, `HOME`, `USER`, `LANG`, `TMPDIR`,
  `PYTHONDONTWRITEBYTECODE`, then `ALLOWED_PASSTHROUGH` (`:10-13`: `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ`, `TERM` and the
  proxies). `build_agent_env` (`:32-41`) adds `L4_RESULT_PATH` and the adapter's variables; `build_gate_env`
  (`:59-79`) adds the cache variables and the caller's `extra`. `TERM` is already passed to both.
- Every gate goes through `Workbench.run_gate_spec` → `gates.runner.run_gate` → `build_gate_env(host_env, …)`
  (`src/l4/gates/runner.py:172`), with `host_env` the run's environment (`workbench.py:429`): setup, build, lint,
  typecheck, test, the coverage check, e2e and the `repository-ci:<job>` re-run (`implementer/tdd.py:510-587,1700`).
  Agents use `build_agent_env` (`implementer/tdd.py:786`, `llm/agent_judge.py:220`, `yolo/readiness.py:540`).
- Typer sets `FORCE_TERMINAL = True` when `GITHUB_ACTIONS`, `FORCE_COLOR` or `PY_COLORS` is set to any non-empty value,
  and `_TYPER_FORCE_DISABLE_TERMINAL` turns that off (`typer/rich_utils.py:77-84`, typer 0.26.8 and 0.27.1 in the uv
  cache of the development machine). Rich reads `NO_COLOR`, `FORCE_COLOR` and `TTY_COMPATIBLE` (`rich/console.py:734,
  961,970`).
- `l4.ci.detect.in_ci` (`src/l4/ci/detect.py:6-7`) is true when `GITLAB_CI`, `GITHUB_ACTIONS` or `CI` is `true`.
- `scripts/runner/ci-probe-m15.sh:350-357` (`m0_gate_env`) is a shell twin of `build_gate_env`, held equal by
  `tests/unit/runner/test_probe_m15_parity.py:105-111`.

How a fix that changed nothing is handed off again today [V]:
- `run_single` (`src/l4/implementer/tdd.py:2041-2164`) runs a `[chore]`: the CI steps of its findings are re-run at the
  base only when step 0 derived them (`reproduce_ci_steps`, `:1683-1715`; GitLab only, D5); after the agent's step the
  tests the family's red steps froze and every path of the test and support globs go back to the base (`:2098-2101`, `restore_frozen`, `freeze_test_paths`). A put-back of a test path is `guard.test_tamper{path, phase: single, action}` (`src/l4/implementer/guards.py:253,304`); of a support file, `guard.violation{path, phase: single}` (`restore_frozen`, `guards.py:234-266`, which also removes a new support file such as a `conftest.py`; a test chore's `review_test_chore` emits `guard.violation{rule: "test support file"}`, `tdd.py:1935-1938`). A person's `[test-infra]` tag never applies in a fix unit: its titles are
  the harness's (`has_human_tag`, `src/l4/verifier/scan.py:304-309`). So a fix chore cannot change any test.
- Its checks: nothing that passed at the base fails (`green_failures(base_report, [], gate)`, `:2106`), the static
  gates (`worse_static_gates`), and a reproduced step must pass (`ci_steps_reason`, `:2127`, `:1718-1726`). A refactor
  chore that changes nothing fails (`nothing changed`, `:2093-2097`); a plain fix chore does not, and `:2154` commits
  the tick and the ledger alone.
- Step 0 raises `repository CI failed: <job>` from the last `repository_ci_failed` edge that no `verify.verdict`
  follows (`ci_edge`, `src/l4/verifier/preconditions.py:91-99`; `ci_blockers`, `:106-120`): only the round right after
  the edge. The round after the fix unit has no CI blocker, its gates pass, and it hands off.
- `decide_fix` (`src/l4/verifier/fixloop.py:551-604`) escalates with `same_failure` when `repeated_failure`
  (`:499-529`) finds the FAIL round's failure set equal to the round before; a PASS round between two CI edges makes
  that check return None. `max_fix_rounds` is the only bound.
- In the incident [I: the report says the commit changed only `tasks.md` and the ledger; the ledger was not read here]: the fix of a help-text test the unit wrote is in that test or in the code's colour; if the agent edited the test, the harness put it back, and the fix unit's ledger has `guard.test_tamper{phase: single}` for it (or `guard.violation` for a support file).
- What the agent is told about a put-back [V]: `note_of` (`src/l4/implementer/guardnotes.py:99-115`) turns each guard event into a line of the next attempt's prompt, and for `test path freeze` says `Tests belong in the red step: if a test is wrong or missing, ask a question that names its path` (`_ADVICE`, `:63-65`); in a fix chore (`phase: single`) that sends the agent to a question that asks to unfreeze a file. An answer cannot do that there: `run_single` passes no `unfreeze` and no `keep` (`tdd.py:2098-2101`).
- Where a fix unit's questions live [V]: on its PARENT unit's branch, under the fix unit's own folder (`<parent folder>-fix-<n>/questions.md`, or `.kiro/specs/<fix unit>/questions.md`). `load_folders` (`src/l4/specs/questions_cli.py:150-197`) resolves a name such as `ns:parent-fix-1` to the parent when that name is not a unit of `discover` (`wanted_fix`), but takes `unit in by_id` first: a fix unit that `discover` lists as a unit of its own is looked up on a branch of its own, which does not exist, and `show` and `accept` fail with `has no branch on origin` (`:185`, `:445`).

## Goals / Non-goals

Goals: the evidence of a red project job is the failing step's output, on GitHub and GitLab, within today's budgets;
the finding names the step and leads with the failure; in CI the gates run with the CI's identity variables, so the unit's own gates and a fix unit's gates fail where the repository's CI fails; the implementer knows why; a CI failure that a fix did not touch escalates with the evidence instead of being handed off again.

Non-goals:
- Re-running a GitHub step in the gate sandbox (the `repository-ci:<job>` gate of L4-ARC-002). It needs a parser of
  GitHub workflows (`jobs.<id>.steps[].run`, `${{ }}` expressions, matrices, `defaults.run`, `working-directory`,
  composite actions) and the vetting of L4-SEC-004 against a file an agent can edit. Follow-up `github-ci-step`; here a
  GitHub step is named, and its `ci.step` says so (D5).
- The repository CI's own `env:` blocks (a `FORCE_COLOR: 1` in `ci.yml`) and every colour variable: the gates do not get them (D7). A test must not depend on colour (D8).
- A failing upload or cache section of a GitLab job that passed its script: dropped today, still out of the excerpt.
- `l4 ci watch` keeps its code and its text; it prints the last lines of the new excerpt (D2).

## D1. One pure module for the excerpt (`src/l4/forge/logexcerpt.py`)

The GitHub reader, the GitLab reader and step 0 need the same pieces: the summary lines, the composition of a section
within the budgets, and (for GitHub) the sections of an Actions log. A new module holds them and imports only
`l4.forge.base` (`clip_log`, `strip_ansi`, `MAX_TAIL_LINES`, `MAX_TAIL_CHARS`), so the forges and the verifier can
import it without a cycle [V: `src/l4/forge/__init__.py` is empty; `l4.forge.base` imports no `l4.ci`,
`l4.verifier` or `l4.forge.github`]. It reads no network and no file.

## D2. The GitHub excerpt (L4-VER-061)

Decision:
- `job_log(job_id, max_lines)` reads the log as today (the redirect without the token, `https` only). When there is a log, it takes the job's `steps[]` (`name`, `conclusion`, `started_at`) from the job list that `_run_jobs` (`github.py:508-518`) has already read for that job (`_run_jobs` keeps each listed job's `steps` in a per-forge map when the job object has a list), else it reads the job once more, `GET /repos/{repo}/actions/jobs/{id}` (`quick=True`: one try and the short timeout). A `ForgeError` (401, 403, 404, 5xx, a timeout) gives no steps; it never loses the log. Then `actions_excerpt(log, steps, max_lines=…)` gives the tail and the step's name:
  `JobLog(tail=…, step=None, failed_step=…)`. `job_log_tail` returns `job_log(...).tail`, as on GitLab
  (`gitlab.py:337-338`).
- Lines: the byte-order mark of line 1 and the prefix `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ` are removed, and
  the prefix's time, to the second (UTC), is kept for the anchor; ANSI codes and carriage returns go as in `clip_log`.
- The failing step of the API: the first step whose `conclusion` is `failure`, else the first that is `timed_out` or `cancelled` [U: what the API reports for a step stopped by `timeout-minutes`: the code takes `failure`, `timed_out` and `cancelled` in that order, so any of the three gives a name; live validation is task 2.2].
- The anchor: the first line that starts with `##[error]`, counting only lines whose time is not before the API's
  failing step's `started_at` (whole seconds) when that step and its start are known and such a line exists. The start filter is for a step with `continue-on-error`, which prints `##[error]` and does not fail the job. [U: whether the API reports such a step as `failure` (with `outcome` failure) or as `success`; the code is safe for both: a `failure` step that is not the job's failing one has an earlier start than the failing step, and a `success` one is not picked; live validation is a task, 2.2.] No `##[error]` line: no anchor.
- Sections: a section starts at a line that starts with `##[group]Run ` (a step's header, also a step inside a
  composite action), at `Post job cleanup.` and at `Cleaning up orphan processes`; the lines before the first header are
  the set-up section. The anchor's section runs from its start to the next start or the end of the log. Taking the
  section to its end, not the anchor line, keeps what a step prints after an annotation: `::error::` from a tool (a
  pytest annotation plugin, `ruff --output-format=github`) is a `##[error]` line in the middle of the step, and the
  step's summary and its `Process completed` line come after it.
- The header: the section's first line without `##[group]` (`Run uv run pytest -q`). Its group (the script, `shell:`,
  `env:`, `with:`) ends at the first `##[endgroup]` after it; those lines are not in the excerpt (they repeat the
  workflow file and hold environment values). The body is the rest of the section.
- Markers in the excerpt read as GitHub's page shows them: `##[error]` → `Error: `, `##[warning]` → `Warning: `,
  `##[notice]` → `Notice: `, a `##[group]` marker inside the body is removed and an `##[endgroup]` line dropped.
- The name (`failed_step`): the API's failing step's `name`, else the header (`Run uv run pytest -q`), else None.
- Composition: `section_excerpt(header, body, (), max_lines, max_chars)` (D4).
- No anchor (no `##[error]` line): today's tail, `clip_log` of the lines without the byte-order mark and the
  timestamps, with the markers converted; `failed_step` is still the API's name when known. No log (404, 410, an
  expired log, a check run of another app): `JobLog()` as today, and the steps are not read.

Why the first `##[error]`, not the job's last: a failed step stops the job; the steps after it are `if: always()`
steps and post steps, whose errors follow from the first (in the log above, `exit code 127` of `l4 status` follows
the failed checkout). Why sections and not the API's step numbers: a composite action is one step for the API and
several `##[group]Run` sections in the log (`docs/live/action/copy-check-38334353208.log:150,163`) [V], and the log
does not carry the API's custom step names. Why the steps: the step's name is what a person and an agent look for, and GitHub's page uses it. They cost no request when `_run_jobs` has listed the run's jobs (the case of a run whose check runs the sweep has told apart); else one request per red job, three per sweep at most.

`l4 ci watch --tail N` (`src/l4/ci/watch.py:206`) calls `job_log` and prints the last N lines: on GitHub those are
now the end of the failing step. Its code and text are unchanged.

## D3. The GitLab excerpt (L4-VER-062)

Decision:
- `_read_trace` also returns the lines of the `step_script` (or legacy `build_script`) section, as it already tracks
  that section for the step (`in_step`, `gitlab.py:98-122`), and the closing lines: the trace's last non-empty line
  when it starts with `ERROR: Job failed` (`ERROR: Job failed: exit code 1`, `…: execution took longer than …`).
- `job_log` composes `section_excerpt(None, script_lines, closing, max_lines, max_chars)`. `after_script`, the cache
  upload and anything else after the script are not in it.
- No `step_script` section (a trace without markers; a job that failed before its script, in `get_sources` or
  `restore_cache`): today's `clip_log(cleaned, max_lines)`.
- `archive_cache` and `archive_cache_on_failure` join `_RUNNER_SECTIONS` [I: names from gitlab-runner's build stages;
  a name that never occurs removes nothing], so the fallback drops them too.
- `step` (the last `$ ` echo of the script section) is unchanged; `job_log_text` and `job_log_step` keep their results.

The two existing tests keep passing [V: `tests/unit/forge/test_gitlab_pipelines.py:116-153`]: the script section of
`RUNNER_TRACE` ends with `Found 1 error.`, then the closing line, so `lines[-2:]` is the same; the trace without
timestamps gives the same three lines.

## D4. The summary lines and the budgets (L4-VER-063)

Decision:
- `SUMMARY_PATTERNS`, each matched with `re.search` against the whole line, after the markers of D2 are converted
  (pattern 6 also takes the raw marker, for a tail recorded before this change):
  1. `^(?:FAILED|ERROR) \S` (pytest's short test summary, `-rfE` by default; the `short test summary info` block is
     these lines);
  2. `^E\s{2,}\S` (pytest's assertion lines), the first `MAX_ASSERTION_LINES` = 6 only;
  3. `^\s*FAIL\s+\S` (jest and vitest);
  4. `^\s*--- FAIL: ` (go test, also a subtest);
  5. `\b[1-9]\d* (?:failed|errors?)\b` (a count: pytest `1 failed, 2277 passed`, ruff `Found 1 error.`, jest `Tests:
     1 failed`, vitest `Test Files  1 failed`);
  6. `^(?:##\[error\]|Error: )(?!Process completed with exit code)` (a GitHub annotation; the runner's own exit line is
     the last line of the tail anyway).
- `section_excerpt(header, body, closing, max_lines, max_chars)`:
  - every line is cut to `MAX_LINE_CHARS` = 500 characters (its start kept, `...` added);
  - `tail` = the last `max_lines` lines of the body; `summary` = the body's lines before the tail that match, in log
    order, without repeats, at most `MAX_SUMMARY_LINES` = 12 and `MAX_SUMMARY_CHARS` = 1,200 characters;
  - the text is the header (when there is one), the summary, one `...` line when body lines were left out, the tail,
    and the closing lines, joined by newlines;
  - over `max_chars`: the tail's first lines go, down to `MIN_TAIL_LINES` = 5; then the summary's last lines; then the
    text's start is cut as `clip_log` does.
- `summary_lines(lines)` is the same match, for step 0 (D5).
- The budgets are today's: 40 lines (`MAX_TAIL_LINES`), 3,000 characters (`MAX_TAIL_CHARS`, the forge's and the
  sweep's), 300 for a step (`MAX_STEP_CHARS`, now also for `failed_step`).

Why a fixed list: these are the lines that name what failed in the stacks L4 gates (Python, TypeScript, Go); anything
else is in the 40 lines of the tail. Why each line is cut: one line of minified output or a long `repr` would take the
whole budget. Why the summary is placed before the tail and not appended: the excerpt reads in log order, and the
end of the text stays the step's end, which the 3,000-character cut after redaction keeps (D6).

## D5. The blocker's detail and the GitHub `ci.step` (L4-VER-064)

Decision:
- `ci_detail(job, stage, head, url, tail, command=None, step_name=None)`. The `where` part: ``job `<job>` (stage
  <stage>)`` as today, then ``failed in step `<step_name>` `` when `step_name` is given and `command` is not, else
  `failed`, then ` on the hand-off commit <H10> (<url>)`. A derived `command` (GitLab) keeps today's `failing step:
  `<command>` (job …). ` prefix; the two never meet (a GitHub job is never derived, below).
- Today's `Log ends` window: `L0 = max(80, min(CI_SUMMARY_TAIL_CHARS, CI_TASK_CHARS - len(where) - 19))` characters of the flattened tail, where `where` is the FINAL text that precedes it: the `again:` sentence of D12 (when there is one) and the `where` part above. The window is therefore the one that is shown, after any prefix. The candidates: the summary lines of the tail that are not inside that window, in the order of priority below. None: the detail is byte-identical to today's.
- The priority: (1) lines that name a failing test: pytest `FAILED` and `ERROR` lines, jest and vitest `FAIL` lines, go `--- FAIL` lines (patterns 1, 3 and 4 of D4); (2) count lines (pattern 5); (3) pytest `E` lines (pattern 2); (4) annotations (pattern 6). Within a class, log order; no repeats. `ranked_summary_lines(lines)` returns them so; `summary_lines` stays in log order for the excerpt (D4).
- `Failed:` opens only when a line of class (1) or (2) is not inside that first window. Its candidates are chosen against the smallest window it can leave, `Lmin = max(80, min(CI_SUMMARY_TAIL_CHARS, CI_TASK_CHARS - len(where) - (F + 10) - 19))`, not against `L0` (review B1: choosing against `L0` left the `FAILED` line out of `Failed:` and, once `E` lines took its place, out of the shrunk window too). A tail whose only missing lines are `E` lines or annotations has no `Failed:` part.
- Otherwise: `Failed: <candidates flattened, joined with " | ">`, cut to `F = min(240, CI_TASK_CHARS - len(where) - 26
  - 80)` characters (`...` at a cut; left out when `F < 40`), placed after `where`; then `Log ends:` with `L =
  max(80, min(CI_SUMMARY_TAIL_CHARS, CI_TASK_CHARS - len(where) - len(failed part) - 19))` characters. The text after
  the blank line is the whole tail, as today.
- `ci_blockers` passes `job.get("failed_step")`. An older ledger has none: today's `where`.
- `derive_ci_steps`: a job entry with a `workflow` key is a GitHub job (the sweep adds it only on GitHub,
  `sweeper.py:880-881`) [V]. Its record is `skipped` with `step` = its `failed_step`, `command` None, reason `a GitHub
  Actions step is named, not re-run: no command is derived from a workflow file`, and source
  `<workflow>@<H10>`. `named_step`, `job_script` and the `.gitlab-ci.yml` read are not called for it, so a `$ ` line in
  its output can never select a command.

For the incident's own excerpt the failing test, the count and the closing `Error:` line are the last lines of the section, so they are inside the `Log ends` window and the detail has no `Failed:` part: the first 600 characters hold the step's name and, in `Log ends:`, the `FAILED` line, the count and `Error: Process completed with exit code 1.`. `Failed:` matters when something follows the failing test (a coverage report, a warnings summary after `-rA`, a later hook): then `L0` shows that tail and the `FAILED` line is not in it [I: `where` with a run URL is about 150 to 200 characters, so `F` is 240 and `L` about 130]. A log whose six `E` lines come before its `FAILED` line in log order still puts the `FAILED` line first.

## D6. Redaction stays in the sweep

The forges return raw excerpts; `Sweeper._log` (`sweeper.py:898-908`) redacts `tail`, `step` and now `failed_step`
with the run's redactor, then cuts (`tail[-MAX_TAIL_CHARS:]`, the step and `failed_step` to `MAX_STEP_CHARS`). The
entry records `failed_step` only when it is not None, as `workflow` and `event`. The excerpt is cut on whole lines
(D4), so its own cut does not split a token inside a line; the line cut at 500 characters and `clip_log`'s character
cut can, as today, and `KEY_FRAGMENT` and the token shapes need their full length [I] (residual, unchanged). The
header group with the step's `env:` lines is out of the excerpt (D2), which keeps the clear-text environment values of
the CI out of the ledger.

## D7. Gates see the CI's identity variables (L4-SEC-040)

Decision:
- `GATE_CI_PASSTHROUGH = ("CI", "GITHUB_ACTIONS", "GITLAB_CI")`; `CI_VALUE = re.compile(r"[A-Za-z0-9_-]{1,16}")`, matched with `fullmatch` (a value with a trailing newline, a `.` or a `/` does not match).
- `gate_ci_env(host_env)`: `{}` unless `in_ci(host_env)`; else every name of the list that `host_env` sets to a value that fully matches `CI_VALUE`, with that value. `refused_ci_env(host_env)`: the names of the list set to a value that does not match (empty outside CI).
- `build_gate_env` adds `gate_ci_env(host_env)` after `_base` and before the cache variables and `extra`, so a gate's own setting wins. `_base` and `build_agent_env` are unchanged: agents get none of them.
- No colour variable is passed, in CI or out of it: `FORCE_COLOR`, `NO_COLOR`, `PY_COLORS`, `CLICOLOR`, `CLICOLOR_FORCE` and `TTY_COMPATIBLE` stay out. With them pytest writes ANSI codes into its output and into the JUnit XML, and the harness reads that output as text: `gates/runner.py` (the log, ~186), `collection.py` (~10 and ~14), `lint_excerpt`, `hang.py`. The incident needs only `GITHUB_ACTIONS` (typer and rich colour under it) and `CI`.
- `TERM` stays in `ALLOWED_PASSTHROUGH` for both, as today.
- `l4 run` logs, once per refused name, the WARNING `the gates do not get <NAME>: its value is not a short word (at most 16 letters, digits, '_', '-')`, never the value. When the gates get the variables and neither `GITHUB_ACTIONS` nor `GITLAB_CI` is `true` in the environment (the opt-in `CI=true l4 run` on a person's machine), it logs one INFO line: `the gates run with <NAME=value, ...> from this environment, not from a CI job: tools behave as in the repository's CI`. `run.started` records `gate_env_ci`, the sorted names the gates get, when there is one.
- `m0_gate_env` (`scripts/runner/ci-probe-m15.sh:350`) prints the same names in the same place, so the parity test holds with a CI host too; its short-word test is `LC_ALL=C` with the same class (`[A-Za-z0-9_-]`, 1 to 16 characters, the whole value).

Why gates and not agents: the gates are where a unit is judged and where the repository's CI behaviour must show; an agent CLI (Claude Code, Codex, Kiro, OpenCode) may change its own behaviour under `CI=true` [U], and the adapters are tested without it. The implementer learns the values from its prompt (D8).

Why only in CI: the gates should behave as the repository's CI does, and the job the harness runs in is the nearest copy of it; on a person's machine today's hermetic environment is kept. `in_ci` counts `CI=true`, so `CI=true l4 run` is the opt-in on a machine, with no new key, and the INFO line says that it happened.

Why a short word: L4-SEC-001 says nothing passed may carry a credential. These names are no credential's, the values CI and tools use are `true`, `1`, `0`, `3`, and the token shapes the redactor knows need 19 characters or more (an OpenAI key; the JWT pattern is shorter in its regex, a real JWT is far longer) (`src/l4/redact.py:11-26`) [V]; a value outside the shape is refused by name. The `.` is not in the class: no version number or path is a CI flag.

What stays out by construction: every other variable of the job, in particular `GITHUB_OUTPUT`, `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_STEP_SUMMARY`, `GITHUB_STATE`, `GITHUB_TOKEN`, `RUNNER_TEMP`, `ACTIONS_*`, `CI_JOB_TOKEN` and every `CI_*` of GitLab. A gate's workflow commands (`::error::`, `::set-output`) go to its log file, not to the job's output (`gates/runner.py:173-186`) [V], so they make no annotation and set nothing.

Alternatives not taken:
- Always pass them, also outside CI: the gates would follow a person's terminal, not the CI.
- A configuration key (`gates.ci_env: auto | on | off`): `CI=true` already opts in; no new key (follow-up if asked).
- Synthesise the CI identity outside CI (`GITHUB_ACTIONS=true` on a person's machine for a GitHub forge): a fake that tools may act on, without the files they expect.
- Scratch files for `GITHUB_OUTPUT` and `GITHUB_STEP_SUMMARY` in the gate's temp directory, for a script that writes to them whenever `GITHUB_ACTIONS` is set: no such gate is known; reconsider on evidence (Risks).
- Pass the whole job environment minus a deny-list: a deny-list misses the next token variable; the allow-list of L4-SEC-001 stays an allow-list.

Rejected after review: the nine variables of the first draft (the six colour variables). They break the harness's own readers of gate output (above), and the incident does not need them.

## D8. The implementer's prompt says it (L4-IMP-080)

Decision:
- `PromptContext.gate_env_ci: tuple[str, ...] = ()` holds `NAME=value` pairs, sorted; `tdd.py:715` fills it from `gate_ci_env(wb.host_env)`.
- When it is not empty, the `# Gate command` section of the red, green and single prompts (`prompt.py:271-283`, built in code) gains: ``The gates run with `CI=true`, `GITHUB_ACTIONS=true` set, as the repository's CI does; your shell in this step does not have them. To reproduce a failure that only the CI shows, run the gate command as `CI=true GITHUB_ACTIONS=true <gate command>`. Under them tools may colour their output (typer and rich under `GITHUB_ACTIONS`), so a test of a command's help or output must not depend on colour: strip the ANSI codes before comparing (for example `click.unstyle`), or turn the command's colour off inside the test.`` (the pairs are the context's, in both places; `<gate command>` is the configured gate command, written out in the prompt).
- Empty (a person's machine, the dry run, the doctor's prompt check): the prompt is byte-identical to today's.

Why in code and not in a template: the gate section is built in `render_prompt`, and a template line would change a template version, `templates.lock.json` and the pinned prompt hashes of the tests, for a sentence that only applies in CI. The rendered prompt's sha256 is recorded as always (`prompt.rendered`).

## D9. No doctor check

`l4 doctor` says nothing new. There is nothing to fix: the passthrough is automatic, and a refused value is named by
`l4 run` (D7). The doctor's sandbox probe calls `build_gate_env(ctx.env, spec)` (`checks_sandbox.py:187`); in `--ci`
its gate environment now holds the variables, which the probe does not read [V: it reads canary files].

## D10. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`: L4-VER-061 to L4-VER-064 before L4-VER-015 (§10); L4-SEC-040 after L4-SEC-039; L4-IMP-080 and L4-IMP-081 after L4-IMP-079 (L4-IMP-081 also covers the put-back note and `l4 questions` for a fix unit); L4-OPS-023 after L4-OPS-022; SCN-VER-217 to SCN-VER-231 after SCN-VER-169; SCN-SEC-100
  to SCN-SEC-103 after SCN-SEC-99; SCN-IMP-396 to SCN-IMP-399 after SCN-IMP-395; SCN-OPS-40 to SCN-OPS-44 after
  SCN-OPS-39; L4-ARC-002 says a GitHub step is named and a fix that changes nothing escalates; L4-SEC-001 points at
  L4-SEC-040; L4-OPS-005 lists `ci_not_fixed`, L4-OPS-007 says it comes first, L4-YOLO-055 lists it with its way out; the skill's `operate.md` (the escalated bullet, ~189) and `control-loop.md` (~33) list it;
  §12.1 lists `failed_step` and `gate_env_ci`; change-table row 62. Written in this draft; tasks change them only to
  match the code.
- `docs/runbook.md` §7.5, "Your own CI is red on the hand-off commit": what the fix unit is given and what the gates
  see in CI, and that colour variables are not passed (a test must not depend on colour); the
  `escalated` causes (`:224`) and the cause table of §7.3 (`:1033-1041`) get `ci_not_fixed` with its way on.
- Skill `plugins/l4/skills/l4/references/operate.md`: a row of the error table for `repository CI failed: <job>`.
- `CHANGELOG.md`: `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)`, with `### Changed` and `### Fixed` (lines in
  `tasks.md`). Parallel drafts add the same heading; whoever merges second keeps one heading and merges the lists.

## D11. A CI fix chore is told what the gates may not show, and asks no one to unfreeze a file (L4-IMP-081)

Decision:
- One line in the single prompt of a chore that answers a CI blocker. The trigger is the one `failing_step.py:229-238` uses: the chore's findings hold `finding_id("repository CI failed: <job>")` for a job of the last `repository_ci_failed` edge. `PromptContext.ci_job: str | None = None` (the first such job's name), filled in `_prompt`; the line is built in code, after the task text, and no template file or version changes: ``This task answers the repository CI job `<job>`. The gates here may not show that failure. If they do not, do not guess a change they cannot check: say so in notes_for_verifier and name the file and the change a person must make.`` Empty (`ci_job` None): the prompt is byte-identical to today's. There is no forced failed attempt and no step-0 reopen window (D12): a chore that changes nothing is committed as today.
- A put-back is told in terms of what a fix step can do. For a guard event with `phase: single` (a test path put back: `guard.test_tamper`; a support file put back or removed, also a new `conftest.py`: `guard.violation`, from `restore_frozen` or `review_test_chore`), `note_of` gives the note the rule `fix task test file` and the detail `a fix chore may not change test files or test-support files: <path> was put back; a person must commit that change`, and `guard_note_text` ends with `What to do instead: A fix task may not change tests or test-support files (...): a person must commit that change on the unit branch. Do not repeat the change and do not ask for the file to be unfrozen (...); say in notes_for_verifier which file and which change a person must commit.` instead of the red-phase advice (`Tests belong in the red step: ... ask a question that names its path`). The same events with `phase: green` keep their text.
- A technical question raised by a blocked chore (`loop._raise_blocked` with `chore_unit`) gets a harness note on its context, as a blocked green question gets `unfreeze_note`: ``Harness note: this is a fix task. It cannot unfreeze a test or test-support file (a test, `conftest.py`, a fixture), whatever the answer says: a fix step's change to one is put back. A person must commit the change on the unit branch, then run `l4 retry --unit <unit id> --reason TEXT`.`` It names no path: a blocked step is discarded before the put-backs run, so the step that asks has put nothing back (the earlier attempt's put-back reached the agent through the guard note).
- `l4 questions show Q --unit <fix unit>` and `accept` find the question (D13).

Why not fail the first attempt: the agent cannot see the failure either (that is the point of the incident), so a forced second attempt tells it nothing it can use, and costs a step; the escalation of D12 carries the evidence to a person.

## D12. A CI failure that no fix touched is not handed off again (L4-OPS-023)

Decision:
- A project file is a path that `l4.evidence.scope.file_kind(path, <parent's folder>, cfg)` does not call `exempt`: not in a unit's or a fix unit's folder, `openspec/changes/**`, `.kiro/specs/**`, `**/.l4/**`, `**/.l4-out/**`, `.coverage`, `questions.md` or `verifier.evidence.scope_exempt` [V: `src/l4/evidence/scope.py:27-28,227-236`].
- `project_changes(git, since, head, unit_dir, cfg)`: the project files that the commits of `git log --first-parent --no-merges <since>..<head> --name-only` changed; None when `since` is not an ancestor of `head` (history rewritten: the rule does not apply). A base merge (`bring_in_base`) is a merge: what it brings is not the unit's fix.
- `ci_history(events, git, unit_dir, cfg)`, per job of the last `repository_ci_failed` edge E (head H):
  - `again_head`: the head H0 of the newest earlier `repository_ci_failed` edge of the unit that lists the job (a verdict, a retry or a resume between the two does not matter); None when there is none;
  - `again_changed`: `len(project_changes(H0, H))`, None when H0 is no ancestor of H;
  - `unfixed`: `again_head` is not None and `again_changed == 0`: the same job failed again on a hand-off and no commit since its earlier failure changed a project file;
  - `put_back`: the sorted, distinct paths of the `guard.test_tamper` and `guard.violation` events with `phase: single` between the earlier edge and E (a test path, or a support file such as a new `conftest.py`);
  - `notes`: the last `task.done.notes` of a chore that answered the job's finding between the two edges.
- Step 0 keeps its window (the first round after E). A blocker whose job has `again_head` starts ``again: job `<job>` also failed on the hand-off commit <H0-10>; project files changed since: <N>. `` (``again: job `<job>` also failed on the hand-off commit <H0-10>. `` when `again_changed` is None). The prefix is part of `where` (D5): the windows are computed after it. After the blank line, before the tail: ``The fix's changes to <paths> were put back (a fix task may not change tests or test-support files; a person must commit that change).`` when `put_back` is not empty, and ``The fix step said: <notes, at most 300 characters>`` when there are notes; they reach the fix spec and `verification.md` with the tail.
- `decide_fix`: a FAIL round with an unfixed job escalates before `same_failure`, the fix-round limit and the plan (an unfinished fix unit is taken up as today; a round that also has a person's feedback item to take makes its fix unit as today, since that item is the change the escalation would ask for): `FixDecision("escalate", used, [], listed, why, code=CI_NOT_FIXED)` with `CI_NOT_FIXED = "ci_not_fixed"` and `why` = ``the repository CI job `<job>` failed again on the hand-off commit <H10>, as on <H0-10>, and no commit between changed a project file: the gates here do not reproduce this CI failure, so handing off again would fail the same way. CI failed in step `<failed_step>`: <Failed lines, joined with " | ", at most 300 characters>`` (the sentence on the step is left out when the edge recorded neither a step nor summary lines). It reads the same `ci_history`, not step 0's result, so a resumed round decides the same way. The `why` is the unit's escalation detail, so `l4 status --unit` (`Cause:`), the sticky note and the run refusal show the excerpt.
- The way on (`l4.state.next_step.way_out` for `ci_not_fixed`, used by `l4 status --unit` and `--json`, the refusal of `l4 run --unit` and the sticky note, `src/l4/ci/resume_label.py:95-103`): ``the gates do not reproduce this CI failure; fix it in a commit of your own on the unit branch (test-support files such as conftest.py are a person's change: a fix step puts them back), or give the change as feedback (l4 feedback add --unit U --kind behaviour --when ... --then ... --text ..., then the git lines it prints), then l4 retry --unit U --reason TEXT; l4 retry alone hands the unit off as it is, for a failure that does not come from the change (a flaky job)``.
- A retry (or resume, or the `l4:retry` label) hands the unit off as it is. If the job fails again on that unchanged head, the same rule escalates again, with the `again` text: a person who retried for a flaky job sees at once that it was not.

Rejected after review (first draft of D11 and D12):
- A forced failed first attempt of the chore that changes nothing, and a step-0 "reopen" window (a verdict followed E, no retry came, the head changed nothing: raise E's blockers again in the round after the fix). The agent cannot see the failure, so the failed attempt told it nothing it could use; the window needed `reopened` state, the tracking of verdicts and retries, and a dedupe of `ci.step`. Replaced by the second failure of the same job. Cost: the loop takes one more hand-off and one more CI run before it escalates.
- Only the chore fails (every attempt) until a code change: the agent either guesses a change the gates cannot check or exhausts its attempts and halts with a reason that names a task, not the CI.
- Count the CI finding in `same_failure`'s set across a PASS round: it would end the loop one round later, with a `same_failure` text that names a finding id, not the job, the heads and the way on.

## D13. `l4 questions` finds a fix unit's questions (L4-IMP-081)

Decision: in `load_folders`, a `--unit` whose name matches `<parent>-fix-<n>` (`_FIX_NAME`) and whose parent is a unit of `discover` resolves to the parent's branch and the fix unit's folder (`wanted_fix`), whether or not `discover` also lists the fix unit as a unit of its own; `--unit <parent>` still shows the parent's own questions only (and its fix units' in the list form, as today). `show`, `accept`, `answer` and `list` use `load_folders`, so all of them find the question. A name that is neither a unit nor a fix unit of one stays `no unit <name>`; a fix unit that has no folder on the parent's branch stays `no unit <name>`.

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.forge.logexcerpt`:
  - `MAX_LINE_CHARS = 500`, `MAX_SUMMARY_LINES = 12`, `MAX_SUMMARY_CHARS = 1200`, `MAX_ASSERTION_LINES = 6`,
    `MIN_TAIL_LINES = 5`, `GAP = "..."`, `SUMMARY_PATTERNS` (D4, in that order).
  - `@dataclass(frozen=True) class ActionsStep: name: str; conclusion: str | None; started_at: datetime | None`.
  - `@dataclass(frozen=True) class Excerpt: text: str; failed_step: str | None = None`.
  - `summary_lines(lines: Sequence[str]) -> list[str]` (D4, with the `E` line limit, no repeats, log order); `ranked_summary_lines(lines: Sequence[str]) -> list[str]` (D5: the same lines, test-id lines, then counts, then `E` lines, then annotations; log order within a class).
  - `section_excerpt(header: str | None, body: Sequence[str], closing: Sequence[str] = (), *, max_lines: int,
    max_chars: int) -> str` (D4).
  - `actions_failed_step(steps: Sequence[ActionsStep]) -> ActionsStep | None` (D2).
  - `actions_excerpt(log: str, steps: Sequence[ActionsStep] | None, *, max_lines: int = MAX_TAIL_LINES, max_chars: int
    = MAX_TAIL_CHARS) -> Excerpt` (D2).
- `l4.forge.base.JobLog`: `tail: str = ""`, `step: str | None = None`, `failed_step: str | None = None`.
- `GitHubForge.job_log` / `job_log_tail` (D2); `GitHubForge._job_steps(job_id) -> list[ActionsStep] | None`.
- `l4.forge.gitlab`: `_read_trace(trace) -> TraceParts` with `text`, `step`, `script: tuple[str, ...] | None`,
  `closing: tuple[str, ...]`; `job_log_text` and `job_log_step` unchanged in result.
- `LocalForge`: a scripted `failed_steps` mapping beside `steps`, returned in `JobLog.failed_step`.
- Ledger: `ci.failed.jobs[].failed_step?: str` (redacted, at most 300 characters); `run.started.gate_env_ci?:
  list[str]`.
- `l4.verifier.preconditions`: `ci_detail(job, stage, head, url, tail, command=None, step_name=None, prefix="")` (`prefix` is the `again:` sentence of D12 with its trailing space; it counts in `where`);
  `GITHUB_STEP_REASON = "a GitHub Actions step is named, not re-run: no command is derived from a workflow file"`.
- `l4.sandbox.env`: `GATE_CI_PASSTHROUGH` (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`), `CI_VALUE` (matched with `fullmatch`), `gate_ci_env(host_env) -> dict[str, str]`, `refused_ci_env(host_env) -> tuple[str, ...]`; `build_gate_env` signature unchanged.
- `PromptContext.gate_env_ci: tuple[str, ...] = ()` and `PromptContext.ci_job: str | None = None`.
- `l4.implementer.guardnotes.FIX_TASK_TESTS` (the rule of a fix chore's put-back note) and `l4.implementer.loop.chore_question_note(unit)`.
- `l4.specs.questions_cli.load_folders` resolves a fix unit's name to its parent's branch (D13).
- `GitHubForge._run_jobs` keeps each listed job's `steps` in `self._job_steps_cache: dict[int, list[ActionsStep]]`; `_job_steps(job_id)` reads that map first.
- `l4.ci.unfixed` (new, pure but for `git`): `project_changes(git, since, head, unit_dir, cfg) -> tuple[str, ...] | None`; `@dataclass(frozen=True) class CiHistory: job: str; head: str; again_head: str | None; again_changed: int | None; unfixed: bool; put_back: tuple[str, ...]; notes: str | None; failed_step: str | None; failing: str`; `ci_history(events, git, unit_dir, cfg) -> dict[str, CiHistory]` (D12; the head is E's own, from the ledger; `failed_step` and `failing` (the ranked summary lines, at most 300 characters) are E's, for the escalation's text; `put_back` the paths of the `guard.test_tamper` and `guard.violation` events with `phase: single` between the earlier edge and E; `notes` the last chore `task.done.notes` for the job's finding).
- `l4.verifier.preconditions`: `ci_blockers(events, steps=None, history=None)`; the `again:` prefix of D12.
- `l4.verifier.fixloop`: `CI_NOT_FIXED = "ci_not_fixed"`; `decide_fix` checks it first (D12).
- `l4.state.next_step`: `CI_NOT_FIXED`, `ci_not_fixed_way_out(unit) -> str`, `way_out` returns it.
- `l4.implementer.prompt`: `CI_JOB_LINE` (the D11 line as a format string, one placeholder `{job}`).
- Texts: D5, D7 (the WARNING and the INFO line), D8, D11, D12, word for word.

## Collisions

- `verifier-cap`, `judge-parts`, `reject-reason` (parallel drafts on 0.4.20): ids do not overlap (they use L4-VER-052
  to L4-VER-060 and SCN-VER-170 to SCN-VER-216; `reject-reason` holds SCN-VER-205 to SCN-VER-216, so this change
  starts at SCN-VER-217) [V: `git show <branch>:docs/SPEC.md`]. All three wrote change-table
  row 59; this change takes 62. `judge-parts` edits the `budget.cost` line of §12.1, two lines below the `ci.failed`
  line this change edits: adjacent hunks, merged by hand. All add `## 0.4.21 (unreleased)` to CHANGELOG.
- No other local branch defines L4-VER-061 and up, SCN-VER-217 and up, L4-SEC-040, SCN-SEC-100, L4-IMP-080 or
  SCN-IMP-396 [V: every local branch's `docs/SPEC.md`].

## Risks

- In CI the gates now behave as the repository's CI does (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`), which is the point, and also changes what passed before: typer and rich colour under `GITHUB_ACTIONS`;
  pytest stops truncating assertion messages [I]; Hypothesis may load its CI profile [I]; jest and vitest do not write a
  new snapshot under `CI` [I], so a test whose snapshot file is not committed fails in the gate as it would in the
  repository's CI (the agent's own run, without the variables, writes it); pnpm and yarn install with a frozen lock file
  [I]. A unit that relied on any of these passed its gates and would have failed the repository's CI.
- A gate script that writes `>> "$GITHUB_OUTPUT"` or `$GITHUB_STEP_SUMMARY` whenever `GITHUB_ACTIONS` is set fails in
  the gate (the path variables are not passed). None is known; the scratch-file alternative of D7 is the answer if one
  appears.
- The GitHub log format (the `##[group]Run` headers, `Post job cleanup.`, the timestamp prefix) is GitHub's, not a
  contract. A changed format finds no anchor or no sections: the excerpt falls back to today's tail, never to nothing.
- A line a test prints that starts with `##[group]Run ` starts a section [I]: the excerpt then begins there and loses
  the step's own header line.
- The incident's own repository is not re-run here: the scenarios use a log of the same shape built from the harness's
  dummy logs.

- D12 escalates a unit whose CI failure the harness cannot fix by itself; before this change the same unit was handed off again until `max_fix_rounds`. A person now decides earlier, with the evidence; that is the purpose. The escalation comes after one wasted hand-off and CI run (the second failure), not before it.
- A base merge that fixes the failure on its own is not counted as a change (merges are left out): the unit escalates, and `l4 retry` hands it off. Counting merges would let any moving base hide a no-op fix.
- A flaky job that fails twice on one head's content escalates, and `l4 retry` hands it off again: acceptable, the text says so.

## Out of scope / follow-ups

- `github-ci-step`: derive and re-run a GitHub `run:` step in the gate sandbox (L4-ARC-002's `repository-ci:<job>`).
- The failing test ids of the excerpt (`FAILED <id>`) as must-pass ids of the `[chore]` fix: they are data from a log
  that agent-written code printed, so they could only select tests that exist at the fix's base.
- `gates.ci_env` (a key) or scratch `GITHUB_*` files, on evidence.
- `l4 ci watch` naming the failing step in its text.
- A fix chore that may change a test the unit's red step wrote, when a person's answer names it (L4-IMP-002's unfreeze in the single phase). Today a person commits the change (D11, D12's way on).
- Colour variables in the gates (D7): if a stack needs them, they come with a reader that strips ANSI from the JUnit XML and the logs first.

## Open questions (each with the recommended answer)

Every recommended answer below is taken (the owner's rule: the decision is in this design, the requirement and a
scenario).

1. Cut at the first `##[error]` or at the end of its step? Taken: the end of its step (D2, L4-VER-061, SCN-VER-219):
   an annotation can be the first `##[error]`.
2. Which variables, and when? Taken: `CI`, `GITHUB_ACTIONS` and `GITLAB_CI` (D7), only in CI, short words only, no colour variable (L4-SEC-040, SCN-SEC-100 to SCN-SEC-103).
3. Agents too? Taken: no; the prompt says it (D7, D8, L4-IMP-080, SCN-SEC-100, SCN-IMP-396).
4. A local opt-in key? Taken: no key; `CI=true` opts in (D7, SCN-SEC-103).
5. A doctor check? Taken: none (D9).
6. Re-run a GitHub step? Taken: no, named only, with its own `ci.step` reason (D5, L4-VER-064, SCN-VER-230); follow-up.
7. A prompt template line or code? Taken: code, only when the gates carry the variables (D8).
8. The chore fails, or the round escalates? Taken: the round escalates, when the same job fails again on a hand-off with no project change since its earlier failure (D12, L4-OPS-023, SCN-OPS-40, SCN-OPS-41); the chore is only told, in one prompt line (D11, L4-IMP-081, SCN-IMP-397).
9. What counts as a change? Taken: a project file changed by a commit after the earlier failing head on the first-parent line, merges left out (D12, SCN-OPS-42, SCN-OPS-44).
10. What does a person's retry mean? Taken: hand off as it is; a failure on that unchanged head escalates at once with `again` (D12, SCN-OPS-41).
11. May a fix step ask for a file to be unfrozen? Taken: no; its put-back note and its questions say that a person commits the change (D11, SCN-IMP-398).
12. Why does `l4 questions show --unit <fix unit>` fail? Taken: the fix unit is looked up as a unit of its own; it resolves to the parent's branch (D13, SCN-IMP-399).
