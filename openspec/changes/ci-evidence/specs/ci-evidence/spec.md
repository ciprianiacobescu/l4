## Purpose

The evidence of a red project CI job is the failing step's own output, on GitHub and on GitLab, within today's budgets,
and the finding names that step and leads with the failure. In CI the gates see the CI's identity and colour variables,
so a test that only the repository's CI fails also fails in the unit's own gates, and the implementer is told why.

## ADDED Requirements

### Requirement: L4-VER-061 The excerpt of a red GitHub job is the failing step's
When the sweep reads a red GitHub Actions job, the forge SHALL read the job's steps (`GET actions/jobs/:id`) besides
its log and SHALL build the excerpt from the failing step's section of the log. The log's lines SHALL lose the
byte-order mark and the runner's timestamp prefix. The failing step of the API is its first step with the conclusion
`failure`, else `timed_out` or `cancelled`. The anchor is the first line that starts with `##[error]`, counting only
lines not before that step's `started_at` when it is known and such a line exists. A section starts at a line that
starts with `##[group]Run `, at `Post job cleanup.` and at `Cleaning up orphan processes`; the excerpt SHALL be the
anchor's section to its end: its `Run …` header line, then (L4-VER-063) the last 40 lines of its output, not the
header's group (script, `shell:`, `env:`). `##[error]`, `##[warning]` and `##[notice]` SHALL read `Error: `, `Warning:
`, `Notice: `. `ci.failed.jobs[].failed_step` SHALL record the API's failing step's name, else the header, redacted
and at most 300 characters. A log with no `##[error]` line SHALL give the last 40 lines as before, without the
timestamps. No log SHALL give an empty excerpt as before, and the steps are then not read. A failed read of the steps
MUST NOT lose the log.

#### Scenario: SCN-VER-215 (−) The incident's job gives the failing step, not the post steps
- **GIVEN** a red job whose log has a step `Run uv run pytest -q` with 300 lines of output, `FAILED
  tests/test_cli.py::test_help - AssertionError`, `1 failed, 2277 passed in 312.40s` and `##[error]Process completed
  with exit code 1.`, then `Post job cleanup.` with 40 lines of checkout and cache cleanup, `Cleaning up orphan
  processes` and a `##[warning]Node.js 20 is deprecated` line, and whose API steps name `tests` as `failure`
- **WHEN** the sweep records `ci.failed`
- **THEN** the job's `tail` starts with `Run uv run pytest -q`, holds the `FAILED` line and the count, ends with `Error:
  Process completed with exit code 1.`, holds no `Post job cleanup.`, no `Node.js 20` and no timestamp, and
  `failed_step` is `tests`

#### Scenario: SCN-VER-216 (−) The first failed step is the anchor, not an always() step after it
- **GIVEN** a log in which `Run git fetch …` ends with `##[error]Process completed with exit code 128.`, then an `if:
  always()` step `Run l4 status` ends with `exit code 127.`, then an upload step warns
- **WHEN** the excerpt is built
- **THEN** it holds `fatal: could not read Username` and `Error: Process completed with exit code 128.` and not `exit
  code 127`

#### Scenario: SCN-VER-217 (−) An annotation in the middle of a step does not cut the step
- **GIVEN** a failing step whose output has `##[error]tests/test_a.py:3: assert 1 == 2` (a tool's `::error::`), 20
  more lines, `1 failed, 4 passed` and `##[error]Process completed with exit code 1.`
- **WHEN** the excerpt is built
- **THEN** it ends with `Error: Process completed with exit code 1.` and holds the count line

#### Scenario: SCN-VER-218 (−) An error of a step that did not fail the job is not the anchor
- **GIVEN** a step with `continue-on-error` that printed `##[error]Process completed with exit code 2.` at 10:00:05, and
  the API's failing step `tests`, started at 10:01:00, whose section ends with `exit code 1.`
- **WHEN** the excerpt is built
- **THEN** it is the section of `tests` and does not hold `exit code 2`; without the API's steps it is the first
  error's section

#### Scenario: SCN-VER-219 (+) No error line, no steps, no log: the excerpt degrades to today's
- **GIVEN** in turn a log with no `##[error]` line; a log whose steps read answers 403; and a job whose log answers 404
- **WHEN** the excerpt is built
- **THEN** the first is the log's last 40 lines without timestamps; the second is the first error's section and
  `failed_step` is its header `Run …`; the third is empty with no `failed_step`, and its steps are not read

#### Scenario: SCN-VER-220 (+) A failure before any step and a step of a composite action
- **GIVEN** in turn a log whose only error is `##[error]Unable to resolve action` before any `##[group]Run`, with the
  API's failing step `Set up job`; and a composite action whose inner step `Run make check` fails
- **WHEN** the excerpt is built
- **THEN** the first is the set-up lines up to that error with `failed_step` `Set up job`; the second starts with `Run
  make check`

### Requirement: L4-VER-062 The excerpt of a red GitLab job ends with the job's script
When the trace of a red GitLab job has a `step_script` (or `build_script`) section, the excerpt SHALL be that section's
lines (L4-VER-063) followed by the trace's closing line when it starts with `ERROR: Job failed`; `after_script`, the
cache upload and the artifact upload MUST NOT be in it. A trace without such a section SHALL give today's tail of the
cleaned trace, which also drops the sections `archive_cache` and `archive_cache_on_failure`. The recorded `step` (the
last `$ ` command of the script) is unchanged.

#### Scenario: SCN-VER-221 (−) An after_script after the failure is not in the excerpt
- **GIVEN** a trace whose `step_script` ends with a traceback and `l4 exit 1 (internal_error)`, whose `after_script`
  prints 60 lines, and whose last line is `ERROR: Job failed: exit status 1`
- **WHEN** the sweep records `ci.failed`
- **THEN** the tail ends with `l4 exit 1 (internal_error)` and `ERROR: Job failed: exit status 1`, holds none of the
  `after_script` lines, and `step` is the script's last `$ ` command

#### Scenario: SCN-VER-222 (+) A trace without a script section keeps today's tail
- **GIVEN** a trace with no section markers, and one that failed in `get_sources`
- **WHEN** the excerpt is built
- **THEN** each is the last 40 lines of the cleaned trace, as before

### Requirement: L4-VER-063 The excerpt keeps the failure's summary lines within the budgets
The excerpt of L4-VER-061 and L4-VER-062 SHALL be, in this order: the header line (GitHub), the summary lines of the
section that come before its last 40 lines, one `...` line when lines were left out, the last 40 lines, and the closing
line (GitLab). A summary line is one of: pytest's `FAILED` and `ERROR` lines, its first six `E` lines, a count of
failures or errors above zero (`1 failed`, `Found 2 errors`), a jest, vitest or go `FAIL` line, and a GitHub `Error:`
annotation other than `Process completed with exit code`; at most 12 lines and 1,200 characters, in log order, without
repeats. Every line SHALL be cut to 500 characters. The excerpt SHALL be at most 3,000 characters: the tail's first
lines go first, down to five, then the summary's last lines. Redaction SHALL stay in the sweep, after the forge: the
`tail`, the `step` and the `failed_step` are redacted with the run's redactor before they are recorded.

#### Scenario: SCN-VER-223 (−) A long output keeps its failures before the tail
- **GIVEN** a failing pytest step whose output has five `FAILED` lines, 30 `E` lines and then 200 more lines before
  `5 failed, 900 passed`
- **WHEN** the excerpt is built
- **THEN** it holds the five `FAILED` lines and the first six `E` lines, then `...`, then the last 40 lines, at most
  3,000 characters, and a 2,000-character line in it is cut to 500

#### Scenario: SCN-VER-224 (−) A secret in the failing step is redacted
- **GIVEN** a failing step that printed a configured secret's value and a `ghp_` token, and whose API name holds the
  secret's value
- **WHEN** the sweep records `ci.failed`
- **THEN** the `tail` and the `failed_step` hold `[REDACTED:…]` in their place and neither value

### Requirement: L4-VER-064 The blocker's detail names the failing step and leads with the failure
The detail of a `repository CI failed: <job>` blocker SHALL read ``job `<job>` (stage <stage>) failed in step
`<failed_step>` on the hand-off commit <H10> (<url>)`` when the job's `failed_step` is recorded and no command was
derived, and today's text otherwise. When summary lines (L4-VER-063) of the recorded tail are not in the end of the log
that today's detail quotes, the detail SHALL add `Failed: <those lines, joined with " | ">` after that part, at most
240 characters, and quote a shorter end (at least 80 characters) so that both fit the first 600 characters; when there
is none, the detail SHALL be today's, byte for byte. Step 0 SHALL record a GitHub job's `ci.step` as `skipped`, with
`step` its `failed_step` and the reason `a GitHub Actions step is named, not re-run: no command is derived from a
workflow file`; it MUST NOT read `.gitlab-ci.yml` for it or take a `$ ` line of its output as a step.

#### Scenario: SCN-VER-225 (−) The incident's blocker names the step and the failing test in its first 600 characters
- **GIVEN** the `ci.failed` of SCN-VER-215 for `ci.yml / tests`, with a run URL
- **WHEN** step 0 builds the blocker
- **THEN** its detail starts ``job `ci.yml / tests` failed in step `tests` on the hand-off commit``, and its first 600
  characters hold `Failed: FAILED tests/test_cli.py::test_help - AssertionError`, the count, `Log ends:` and `Error:
  Process completed with exit code 1.`

#### Scenario: SCN-VER-226 (+) A detail whose failures are already in the end is today's
- **GIVEN** a GitLab job whose tail ends with `E501 Line too long (108 > 92)`, its code lines and `Found 1 error.`
- **WHEN** step 0 builds the blocker
- **THEN** the detail is byte-identical to the 0.4.20 detail of the same tail

#### Scenario: SCN-VER-227 (+) An older ledger without failed_step gives today's text with the failures first
- **GIVEN** a `repository_ci_failed` edge recorded by 0.4.20 (no `failed_step`) whose tail holds a `FAILED` line 40
  lines before its end
- **WHEN** step 0 builds the blocker
- **THEN** the detail starts ``job `<job>` failed on the hand-off commit`` and its first 600 characters hold the `FAILED`
  line

#### Scenario: SCN-VER-228 (−) A GitHub step is named, never derived
- **GIVEN** a GitHub job entry (`workflow: ci.yml`) whose tail has a line `$ make deploy`, in a repository that also has
  a `.gitlab-ci.yml` with that command
- **WHEN** step 0 derives the failing steps
- **THEN** its `ci.step` is `skipped` with the reason `a GitHub Actions step is named, not re-run: no command is derived
  from a workflow file`, `step` its `failed_step`, no command, and `.gitlab-ci.yml` is not read for it

#### Scenario: SCN-VER-229 (+) The fix unit's spec carries the excerpt
- **GIVEN** the blocker of SCN-VER-225
- **WHEN** the fix unit is written (OpenSpec and Kiro)
- **THEN** its proposal (OpenSpec) or requirements (Kiro) hold the step's name, the `FAILED` line and `Error: Process
  completed with exit code 1.`, and no `##(error)` or `##(warning)`

### Requirement: L4-SEC-040 Gates see the CI's identity and colour variables
When the harness runs in CI (`CI`, `GITHUB_ACTIONS` or `GITLAB_CI` is `true` in its environment), every gate process
(setup, build, lint, typecheck, test, e2e, coverage check, a `repository-ci:<job>` step) SHALL also receive those of
`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `FORCE_COLOR`, `NO_COLOR`, `PY_COLORS`, `CLICOLOR`, `CLICOLOR_FORCE` and
`TTY_COMPATIBLE` that the harness's environment sets to a short word (1 to 16 letters, digits, `.`, `_`, `-`), with
that value; a gate's own setting wins. A value that is not a short word MUST NOT be passed, and `l4 run` SHALL log once
per such name the WARNING `the gates do not get <NAME>: its value is not a short word (at most 16 letters, digits, '.',
'_', '-')`, never the value. Agent processes MUST NOT receive them. No other variable of the CI is passed (not
`GITHUB_OUTPUT`, `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `RUNNER_TEMP`, `CI_JOB_TOKEN` or
any `CI_*`). Outside CI the gate environment SHALL be unchanged. `run.started` SHALL record `gate_env_ci`, the sorted
names the gates get, when there is one. The runner probe's shell twin (`m0_gate_env`) SHALL build the same
environment.

#### Scenario: SCN-SEC-100 (−) In a GitHub job the gates get the CI's flags and the agents do not
- **GIVEN** a harness environment with `CI=true`, `GITHUB_ACTIONS=true`, `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`,
  `GITHUB_TOKEN`, `RUNNER_TEMP` and `CI_JOB_TOKEN`
- **WHEN** a gate and an agent step are started
- **THEN** the gate's environment has `CI=true` and `GITHUB_ACTIONS=true` and none of the other five; the agent's has
  neither flag; `run.started` has `gate_env_ci: ["CI", "GITHUB_ACTIONS"]`

#### Scenario: SCN-SEC-101 (−) A test that only CI fails now fails in the unit's gate
- **GIVEN** a unit whose test of a command's help text fails when `GITHUB_ACTIONS` is set and passes otherwise
- **WHEN** its test gate runs in a GitHub job, and again on a person's machine with no CI variable
- **THEN** the gate fails in the job, as the repository's CI does, and passes on the machine as before

#### Scenario: SCN-SEC-102 (−) A value that is not a short word is not passed and is named
- **GIVEN** a GitHub job with `FORCE_COLOR` set to a 40-character token and `NO_COLOR=/tmp/x`
- **WHEN** `l4 run` starts and a gate runs
- **THEN** the gate's environment has neither, and the run's log has the WARNING once for `FORCE_COLOR` and once for
  `NO_COLOR`, without either value

#### Scenario: SCN-SEC-103 (+) Outside CI nothing changes, and CI=true opts in
- **GIVEN** a person's shell with `CLICOLOR=1` and `FORCE_COLOR=1`, and no `CI`, `GITHUB_ACTIONS` or `GITLAB_CI`
- **WHEN** a gate runs, and again with `CI=true` set in that shell
- **THEN** the first gate's environment is the 0.4.20 environment, with neither variable and no `gate_env_ci`; the
  second has `CI=true`, `CLICOLOR=1` and `FORCE_COLOR=1`

### Requirement: L4-IMP-080 The implementer is told what the gates see in CI
When the gates of the step receive variables of L4-SEC-040, the gate section of the red, green and single prompts SHALL
name them (`` `CI=true`, `GITHUB_ACTIONS=true` ``) and say that the step's own shell does not have them, that tools such
as typer and rich colour their output under them, and that a test of a command's help or output must not depend on
colour (strip the ANSI codes before comparing, or turn the command's colour off in the test). When there is none, the
prompt SHALL be byte-identical to today's. No template file or template version changes.

#### Scenario: SCN-IMP-396 (+) In a GitHub job the gate section names the variables
- **GIVEN** a red step in a GitHub job (`CI=true`, `GITHUB_ACTIONS=true`), and the same step on a person's machine
- **WHEN** the prompt is rendered
- **THEN** the first prompt's gate section names `` `CI=true`, `GITHUB_ACTIONS=true` `` and the colour rule; the
  second prompt and its sha256 are those of 0.4.20, and the template versions are unchanged
