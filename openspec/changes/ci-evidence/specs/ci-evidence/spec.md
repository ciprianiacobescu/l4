## Purpose

The evidence of a red project CI job is the failing step's own output, on GitHub and on GitLab, within today's budgets,
and the finding names that step and leads with the failure. In CI the gates see the CI's identity and colour variables,
so a test that only the repository's CI fails also fails in the unit's own gates, and the implementer is told why. A fix
that leaves the project's files as they were on the failing hand-off commit is not handed off again.

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

#### Scenario: SCN-VER-217 (−) The incident's job gives the failing step, not the post steps
- **GIVEN** a red job whose log has a step `Run uv run pytest -q` with 300 lines of output, `FAILED
  tests/test_cli.py::test_help - AssertionError`, `1 failed, 2277 passed in 312.40s` and `##[error]Process completed
  with exit code 1.`, then `Post job cleanup.` with 40 lines of checkout and cache cleanup, `Cleaning up orphan
  processes` and a `##[warning]Node.js 20 is deprecated` line, and whose API steps name `tests` as `failure`
- **WHEN** the sweep records `ci.failed`
- **THEN** the job's `tail` starts with `Run uv run pytest -q`, holds the `FAILED` line and the count, ends with `Error:
  Process completed with exit code 1.`, holds no `Post job cleanup.`, no `Node.js 20` and no timestamp, and
  `failed_step` is `tests`

#### Scenario: SCN-VER-218 (−) The first failed step is the anchor, not an always() step after it
- **GIVEN** a log in which `Run git fetch …` ends with `##[error]Process completed with exit code 128.`, then an `if:
  always()` step `Run l4 status` ends with `exit code 127.`, then an upload step warns
- **WHEN** the excerpt is built
- **THEN** it holds `fatal: could not read Username` and `Error: Process completed with exit code 128.` and not `exit
  code 127`

#### Scenario: SCN-VER-219 (−) An annotation in the middle of a step does not cut the step
- **GIVEN** a failing step whose output has `##[error]tests/test_a.py:3: assert 1 == 2` (a tool's `::error::`), 20
  more lines, `1 failed, 4 passed` and `##[error]Process completed with exit code 1.`
- **WHEN** the excerpt is built
- **THEN** it ends with `Error: Process completed with exit code 1.` and holds the count line

#### Scenario: SCN-VER-220 (−) An error of a step that did not fail the job is not the anchor
- **GIVEN** a step with `continue-on-error` that printed `##[error]Process completed with exit code 2.` at 10:00:05, and
  the API's failing step `tests`, started at 10:01:00, whose section ends with `exit code 1.`
- **WHEN** the excerpt is built
- **THEN** it is the section of `tests` and does not hold `exit code 2`; without the API's steps it is the first
  error's section

#### Scenario: SCN-VER-221 (+) No error line, no steps, no log: the excerpt degrades to today's
- **GIVEN** in turn a log with no `##[error]` line; a log whose steps read answers 403; and a job whose log answers 404
- **WHEN** the excerpt is built
- **THEN** the first is the log's last 40 lines without timestamps; the second is the first error's section and
  `failed_step` is its header `Run …`; the third is empty with no `failed_step`, and its steps are not read

#### Scenario: SCN-VER-222 (+) A failure before any step and a step of a composite action
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

#### Scenario: SCN-VER-223 (−) An after_script after the failure is not in the excerpt
- **GIVEN** a trace whose `step_script` ends with a traceback and `l4 exit 1 (internal_error)`, whose `after_script`
  prints 60 lines, and whose last line is `ERROR: Job failed: exit status 1`
- **WHEN** the sweep records `ci.failed`
- **THEN** the tail ends with `l4 exit 1 (internal_error)` and `ERROR: Job failed: exit status 1`, holds none of the
  `after_script` lines, and `step` is the script's last `$ ` command

#### Scenario: SCN-VER-224 (+) A trace without a script section keeps today's tail
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

#### Scenario: SCN-VER-225 (−) A long output keeps its failures before the tail
- **GIVEN** a failing pytest step whose output has five `FAILED` lines, 30 `E` lines and then 200 more lines before
  `5 failed, 900 passed`
- **WHEN** the excerpt is built
- **THEN** it holds the five `FAILED` lines and the first six `E` lines, then `...`, then the last 40 lines, at most
  3,000 characters, and a 2,000-character line in it is cut to 500

#### Scenario: SCN-VER-226 (−) A secret in the failing step is redacted
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

#### Scenario: SCN-VER-227 (−) The incident's blocker names the step and the failing test in its first 600 characters
- **GIVEN** the `ci.failed` of SCN-VER-217 for `ci.yml / tests`, with a run URL
- **WHEN** step 0 builds the blocker
- **THEN** its detail starts ``job `ci.yml / tests` failed in step `tests` on the hand-off commit``, and its first 600
  characters hold `Failed: FAILED tests/test_cli.py::test_help - AssertionError`, the count, `Log ends:` and `Error:
  Process completed with exit code 1.`

#### Scenario: SCN-VER-228 (+) A detail whose failures are already in the end is today's
- **GIVEN** a GitLab job whose tail ends with `E501 Line too long (108 > 92)`, its code lines and `Found 1 error.`
- **WHEN** step 0 builds the blocker
- **THEN** the detail is byte-identical to the 0.4.20 detail of the same tail

#### Scenario: SCN-VER-229 (+) An older ledger without failed_step gives today's text with the failures first
- **GIVEN** a `repository_ci_failed` edge recorded by 0.4.20 (no `failed_step`) whose tail holds a `FAILED` line 40
  lines before its end
- **WHEN** step 0 builds the blocker
- **THEN** the detail starts ``job `<job>` failed on the hand-off commit`` and its first 600 characters hold the `FAILED`
  line

#### Scenario: SCN-VER-230 (−) A GitHub step is named, never derived
- **GIVEN** a GitHub job entry (`workflow: ci.yml`) whose tail has a line `$ make deploy`, in a repository that also has
  a `.gitlab-ci.yml` with that command
- **WHEN** step 0 derives the failing steps
- **THEN** its `ci.step` is `skipped` with the reason `a GitHub Actions step is named, not re-run: no command is derived
  from a workflow file`, `step` its `failed_step`, no command, and `.gitlab-ci.yml` is not read for it

#### Scenario: SCN-VER-231 (+) The fix unit's spec carries the excerpt
- **GIVEN** the blocker of SCN-VER-227
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

### Requirement: L4-IMP-081 A fix chore that answers a CI failure and changes nothing is told once
When a `[chore]` of a fix unit answers a `repository CI failed: <job>` finding of the last `repository_ci_failed` edge
(head H1), its own step left no project file (L4-OPS-023) changed after the put-backs of the test paths, and no commit
after H1 changed a project file, its first attempt SHALL fail with the reason ``this task answers `repository CI failed: <job>`, and after it no project file
differs from the hand-off commit <H1>, on which the repository's CI failed: the next hand-off would fail the same way.
The gates here do not show that failure: <gates>. From the CI's log: failing step `<failed_step>`: <summary lines>.``,
then what to do: change the project's code so that this step passes in the CI; say why in `notes_for_verifier` when no
change of this task can fix it; report status blocked with one technical question when only a change to a test can.
`<gates>` SHALL say whether the gates ran with the CI's variables (L4-SEC-040) and name them, or that they ran without
`CI` and the forge's flag. When the attempt put test files back, the reason SHALL name them and say that a fix task may
not change the unit's tests. A later attempt, or a retake, that changes nothing SHALL be committed as before. A chore
whose own step changed a project file, a chore with no such finding, and a test or refactor chore are not affected,
even in a fix unit whose other tasks changed code.

#### Scenario: SCN-IMP-397 (−) A CI chore that changes nothing is told once
- **GIVEN** a fix unit whose chore answers `repository CI failed: ci.yml / tests`, an edge with the excerpt of
  SCN-VER-217, a run outside CI, and an agent step that changes no project file
- **WHEN** the chore's first attempt ends
- **THEN** the attempt fails with the reason that names `ci.yml / tests`, the hand-off commit, `they run without the
  CI's `CI` and `GITHUB_ACTIONS` variables`, the step `tests` and the `FAILED` line; nothing is committed; the second
  attempt's prompt carries the reason

#### Scenario: SCN-IMP-398 (−) A CI chore whose test edit was put back is told so
- **GIVEN** the chore of SCN-IMP-397, in a GitHub job, whose step changed only `tests/test_cli.py`, which the guard puts
  back
- **WHEN** the first attempt ends
- **THEN** the reason holds `they run with `CI=true`, `GITHUB_ACTIONS=true`, as the CI does, and still pass` and
  `Your changes to tests/test_cli.py were put back: a fix task may not change the unit's tests.`

#### Scenario: SCN-IMP-399 (+) A second attempt, a real change and other chores are not affected
- **GIVEN** in turn the second attempt of SCN-IMP-397 that again changes nothing, with notes; the first attempt changing
  `src/app/cli.py`; a chore that answers a judge finding and changes nothing; and the CI chore of SCN-IMP-397 after a
  person's commit on the branch that changed `src/app/cli.py`
- **WHEN** each attempt ends
- **THEN** the first is committed with its notes, and the second, the third and the fourth are committed as before

### Requirement: L4-OPS-023 A CI failure that no fix touched is not handed off again
A project file is a path outside the units' and fix units' folders, `openspec/changes/**`, `.kiro/specs/**`,
`**/.l4/**`, `**/.l4-out/**` and `verifier.evidence.scope_exempt`. A head changed nothing since H when no commit of
`git log --first-parent --no-merges H..head` changed a project file (merges of the base are not a fix); when H is not
an ancestor of the head, the rule does not apply. A job of the last `repository_ci_failed` edge E (head H) is unfixed
when (a) a verdict followed E, no `unit.retried`, `unit.resumed` or other review edge came after that verdict, and the
head changed nothing since H; or (b) E is open and the job also failed on an earlier edge of the unit, which a verdict
followed, at a head H0 such that H changed nothing since H0. In case (a) step 0 SHALL raise E's blockers again. An
unfixed blocker's detail SHALL start ``not fixed: job `<job>` failed on the hand-off commit <H10>, and no commit since
changed a project file.`` (within the first 600 characters, with `Log ends:`), and name after its first part the test
files the fix units put back after E and the fix step's notes; a blocker whose job failed on an earlier edge at H0
with project changes since SHALL start ``again: job `<job>` also failed on the hand-off commit <H0>; project files
changed since: <N>.``. A FAIL round with an unfixed job SHALL escalate with the
reason code `ci_not_fixed` and no new fix unit, whatever fix rounds are left, unless it takes up an unfinished fix unit
or has a person's feedback item to take; the reason SHALL read ``the repository CI job `<job>` failed on the hand-off
commit <H10>, and nothing since changed a project file: the gates here do not show the failure, so handing off again
would fail the same way`` (case b: ``failed again on the hand-off commit <H10>, as on <H0>, and nothing between changed
a project file``). `l4 status --unit` and `--json`, the refusal of `l4 run --unit` and the sticky note SHALL name the
way on: a person's commit that fixes it, or the change as feedback (`l4 feedback add --unit U --kind behaviour …`),
then `l4 retry --unit U --reason TEXT`; `l4 retry` alone hands the unit off as it is. The decision SHALL be read from
the ledger and git, so a resumed round decides the same way.

#### Scenario: SCN-OPS-40 (−) The incident: a fix that changed nothing escalates instead of handing off
- **GIVEN** a unit whose CI job `ci.yml / tests` failed on H1, round 4 that failed on its blocker and made fix unit 2,
  and fix unit 2's chore commit that changed only its `tasks.md` and the ledger
- **WHEN** round 5 verifies the unit and its gates pass
- **THEN** step 0 raises `repository CI failed: ci.yml / tests` again with a detail that starts `not fixed:`, the round
  fails, no fix unit 3 is made although fix rounds are left, the unit is `escalated` with `ci_not_fixed` and the reason
  of L4-OPS-023, and the unit is not handed off

#### Scenario: SCN-OPS-41 (−) The same job failing again after a hand-off as it was escalates at once
- **GIVEN** the unit of SCN-OPS-40 after a person's `l4 retry`, handed off as it was at H2, and `ci.yml / tests` red on
  H2
- **WHEN** the next round verifies it
- **THEN** the blocker's detail starts `not fixed:`, the unit is `escalated` with `ci_not_fixed` and the reason `failed
  again on the hand-off commit <H2>, as on <H1>, and nothing between changed a project file`, and no fix unit is made

#### Scenario: SCN-OPS-42 (+) A project change, a person's commit or a retry closes the window
- **GIVEN** in turn the unit of SCN-OPS-40 whose fix chore changed `src/app/cli.py`; whose branch has a person's commit
  that changes `tests/test_cli.py`; and on which a person ran `l4 retry` after round 5
- **WHEN** the next round verifies it with passing gates
- **THEN** each round passes and hands off; a later failure of `ci.yml / tests` on that head starts its detail `again:
  job `ci.yml / tests` also failed on the hand-off commit <H1>; project files changed since: 1.` in the first two
  cases and makes a fix unit

#### Scenario: SCN-OPS-43 (+) The status, the run refusal and the sticky note name the way on
- **GIVEN** a unit `escalated` with `ci_not_fixed`
- **WHEN** `l4 status --unit U`, `l4 status --json` and `l4 run --unit U` run, and the sticky note is written
- **THEN** each names a commit of a person's own, `l4 feedback add --unit U --kind behaviour`, `l4 retry --unit U
  --reason TEXT`, and that `l4 retry` alone hands the unit off as it is

#### Scenario: SCN-OPS-44 (−) A base merge is not a fix, and a rewritten history is not judged
- **GIVEN** in turn the unit of SCN-OPS-40 whose only commit after H1 besides the fix unit's is a merge of the base that
  changes `src/app/other.py`; and a unit whose H1 is no longer an ancestor of its head
- **WHEN** the next round verifies it
- **THEN** the first escalates with `ci_not_fixed`; the second raises no `not fixed` blocker
