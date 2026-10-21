## Purpose

The evidence of a red project CI job is the failing step's own output, on GitHub and on GitLab, within today's budgets,
and the finding names that step and leads with the failure. In CI the gates see the CI's identity variables,
so a test that only the repository's CI fails also fails in the unit's own gates, and the implementer is told why. A CI job that fails again on a hand-off after no commit changed a project file escalates with its evidence instead of being handed off again.

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
that today's detail quotes, the detail SHALL add `Failed: <those lines, joined with " | ">` after that part, the lines that name a failing test first (pytest `FAILED` and `ERROR`, jest and vitest `FAIL`, go `--- FAIL`), then the counts, then pytest's `E` lines, then annotations, at most 240 characters, and quote a shorter end (at least 80 characters) so that both fit the first 600 characters (the window being the one shown after the `again:` sentence of L4-OPS-023, when there is one); when there
is none, the detail SHALL be today's, byte for byte. The `Failed:` part SHALL open only when a line that names a failing test, or a count line, is not in the first window; its lines SHALL be chosen against the smallest window that part can leave (`max(80, min(300, 600 - len(where) - 250 - 19))` or the like), so that no failing test falls out of both parts, and a detail whose only missing lines are `E` lines or annotations SHALL have no `Failed:` part. Step 0 SHALL record a GitHub job's `ci.step` as `skipped`, with
`step` its `failed_step` and the reason `a GitHub Actions step is named, not re-run: no command is derived from a
workflow file`; it MUST NOT read `.gitlab-ci.yml` for it or take a `$ ` line of its output as a step.

#### Scenario: SCN-VER-227 (−) The incident's blocker names the step and the failing test in its first 600 characters
- **GIVEN** a `ci.failed` for `ci.yml / tests`, with a run URL, whose excerpt is the one of SCN-VER-217 with 25 lines of a coverage report between the count line and `Error: Process completed with exit code 1.`
- **WHEN** step 0 builds the blocker
- **THEN** its detail starts ``job `ci.yml / tests` failed in step `tests` on the hand-off commit``, and its first 600
  characters hold `Failed: FAILED tests/test_cli.py::test_help - AssertionError | 1 failed, 2277 passed` (the failing test, then the count, then the `E` lines that still fit), `Log ends:` and `Error: Process completed with exit code 1.`; with six `E` lines before the `FAILED` line in the log, `Failed:` still starts with the `FAILED` line; for the excerpt of SCN-VER-217 itself, whose failing test is already in the end of the log, the detail has no `Failed:` part and `Log ends:` holds the `FAILED` line

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

### Requirement: L4-SEC-040 Gates see the CI's identity variables
When the harness runs in CI (`CI`, `GITHUB_ACTIONS` or `GITLAB_CI` is `true` in its environment), every gate process
(setup, build, lint, typecheck, test, e2e, coverage check, a `repository-ci:<job>` step) SHALL also receive those of
`CI`, `GITHUB_ACTIONS` and `GITLAB_CI` that the harness's environment sets, with that value, when the value fully
matches a short word (1 to 16 letters, digits, `_`, `-`); a gate's own setting wins. A value that is not a short word
MUST NOT be passed, and `l4 run` SHALL log once per such name the WARNING `the gates do not get <NAME>: its value is not
a short word (at most 16 letters, digits, '_', '-')`, never the value. No colour variable (`FORCE_COLOR`, `NO_COLOR`,
`PY_COLORS`, `CLICOLOR`, `CLICOLOR_FORCE`, `TTY_COMPATIBLE`) is passed, in CI or out of it: with them pytest writes ANSI
codes into its logs and JUnit XML, which the harness's own readers of gate output do not expect. Agent processes MUST
NOT receive the three variables. No other variable of the CI is passed (not `GITHUB_OUTPUT`, `GITHUB_ENV`,
`GITHUB_PATH`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `RUNNER_TEMP`, `CI_JOB_TOKEN` or any `CI_*`). Outside CI the gate
environment SHALL be unchanged; `CI=true l4 run` opts in on a person's machine, and `l4 run` then logs one INFO line
`the gates run with <NAME=value, ...> from this environment, not from a CI job: tools behave as in the repository's CI`
(when neither `GITHUB_ACTIONS` nor `GITLAB_CI` is `true`). `run.started` SHALL record `gate_env_ci`, the sorted names
the gates get, when there is one. The runner probe's shell twin (`m0_gate_env`) SHALL build the same environment, with
`LC_ALL=C` for its character class.

#### Scenario: SCN-SEC-100 (−) In a GitHub job the gates get the CI's flags and the agents do not
- **GIVEN** a harness environment with `CI=true`, `GITHUB_ACTIONS=true`, `FORCE_COLOR=1`, `PY_COLORS=1`,
  `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `RUNNER_TEMP` and `CI_JOB_TOKEN`
- **WHEN** a gate and an agent step are started
- **THEN** the gate's environment has `CI=true` and `GITHUB_ACTIONS=true` and none of the other seven; the agent's has
  neither flag; `run.started` has `gate_env_ci: ["CI", "GITHUB_ACTIONS"]`

#### Scenario: SCN-SEC-101 (−) A test that only CI fails now fails in the unit's gate
- **GIVEN** a unit whose test of a command's help text fails when `GITHUB_ACTIONS` is set and passes otherwise
- **WHEN** its test gate runs in a GitHub job, and again on a person's machine with no CI variable
- **THEN** the gate fails in the job, as the repository's CI does, and passes on the machine as before

#### Scenario: SCN-SEC-102 (−) A value that is not a short word is not passed and is named
- **GIVEN** a job with `CI=true`, `GITLAB_CI` set to a 40-character token, `GITHUB_ACTIONS=/tmp/x` and a third case with
  `GITHUB_ACTIONS=true\n` (a trailing newline)
- **WHEN** `l4 run` starts and a gate runs
- **THEN** the gate's environment has `CI=true` and none of the refused names, and the run's log has the WARNING once
  for each refused name, without any value

#### Scenario: SCN-SEC-103 (+) Outside CI nothing changes, CI=true opts in, and no colour variable is ever passed
- **GIVEN** a person's shell with `CLICOLOR=1` and `FORCE_COLOR=1`, and no `CI`, `GITHUB_ACTIONS` or `GITLAB_CI`
- **WHEN** a gate runs, and again with `CI=true` set in that shell
- **THEN** the first gate's environment is the 0.4.20 environment, with no `gate_env_ci`; the second has `CI=true` and
  neither `CLICOLOR` nor `FORCE_COLOR`, `run.started` has `gate_env_ci: ["CI"]`, and the run logs the INFO line once

### Requirement: L4-IMP-080 The implementer is told what the gates see in CI
When the gates of the step receive variables of L4-SEC-040, the gate section of the red, green and single prompts SHALL
name them (`` `CI=true`, `GITHUB_ACTIONS=true` ``), say that the step's own shell does not have them, tell how to
reproduce a failure that only the CI shows (run the gate command as `CI=true GITHUB_ACTIONS=true <gate command>`), say
that tools such as typer and rich may colour their output under them, and that a test of a command's help or output must
not depend on colour (strip the ANSI codes before comparing, or turn the command's colour off in the test). When there
is none, the prompt SHALL be byte-identical to today's. No template file or template version changes.

#### Scenario: SCN-IMP-396 (+) In a GitHub job the gate section names the variables
- **GIVEN** a red step in a GitHub job (`CI=true`, `GITHUB_ACTIONS=true`), and the same step on a person's machine
- **WHEN** the prompt is rendered
- **THEN** the first prompt's gate section names `` `CI=true`, `GITHUB_ACTIONS=true` ``, the command `CI=true
  GITHUB_ACTIONS=true <gate command>` and the colour rule; the second prompt and its sha256 are those without the rule,
  and the template versions are unchanged

### Requirement: L4-IMP-081 A CI fix task is told what the gates may not show, and asks no one to unfreeze a file
When a `[chore]` of a fix unit answers a `repository CI failed: <job>` finding of the last `repository_ci_failed` edge,
the prompt of its step SHALL carry one more line (built in code; no template file or version changes): the task answers
that CI job, the gates here may not show its failure, and when they do not the agent is to say so in
`notes_for_verifier` and name the file and the change a person must make, instead of guessing a change the gates cannot
check. A chore that changes nothing is committed as before. A fix step's change to a test file or a test-support file
(`conftest.py`, fixtures, also a new one) is put back (`guard.test_tamper` for a test path, `guard.violation` for a
support file); the note for the next attempt and the harness note on a technical question that the step raises SHALL say that a
person must commit that change on the unit branch and that an answer cannot unfreeze a file in a fix task, and MUST NOT
offer an unfreeze. `l4 questions show` and `accept` with `--unit <fix unit>` SHALL find the fix unit's questions, which
live on its parent unit's branch under the fix unit's own folder; `--unit <parent>` shows the parent's own questions.

#### Scenario: SCN-IMP-397 (+) A CI chore's prompt carries one line, and a chore that changes nothing is committed
- **GIVEN** a fix unit whose chore answers `repository CI failed: ci.yml / tests` (the finding of the last edge), a
  chore that answers a judge finding, and an agent step of the first that changes no project file
- **WHEN** both single prompts are rendered and the first step ends
- **THEN** the first prompt holds the line that names `ci.yml / tests`, the gates and `notes_for_verifier`; the second
  prompt and its sha256 are those without it and the template versions are unchanged; the first step is committed as a
  chore that changes nothing is today

#### Scenario: SCN-IMP-398 (−) A put-back test or support file is not offered for unfreezing
- **GIVEN** a fix chore whose step changed `tests/test_cli.py` and added `tests/conftest.py` (both put back, as
  `guard.test_tamper` and `guard.violation` with `phase: single`) and then reported blocked with one technical question
- **WHEN** the next attempt's prompt and the question are written
- **THEN** the guard note names both paths, says that a fix chore may not change test files or test-support files and that a person must commit that change, and does not tell the agent to ask a question that names the path; the question's context ends with the harness note that a fix task cannot unfreeze a test or test-support file and that a person must commit the change on the unit branch themselves, then answer the question with `l4 questions answer Q-NNN --unit F --text "..."` (F the fix unit, which names the question's own unit: `l4 retry --unit F` is refused for a fix unit); it holds no `unfreeze_note` text

#### Scenario: SCN-IMP-399 (−) A fix unit's questions are shown and accepted by its own name
- **GIVEN** unit `openspec:a` with the fix unit `openspec:a-fix-1`, whose open question Q-001 is in the fix unit's
  folder on the branch of `a`, and a `discover` that also lists the fix unit as a unit of its own
- **WHEN** `l4 questions show Q-001 --unit openspec:a-fix-1`, `l4 questions accept Q-001 --unit openspec:a-fix-1` and
  `l4 questions show Q-001 --unit openspec:a` run
- **THEN** the first two read the question from the branch of `a` and the accept is taken; the third reports no Q-001 in
  the unit's own folder; none says `has no branch on origin`

### Requirement: L4-OPS-023 A CI failure that no fix touched is not handed off again
A project file is a path outside the units' and fix units' folders, `openspec/changes/**`, `.kiro/specs/**`,
`**/.l4/**`, `**/.l4-out/**` and `verifier.evidence.scope_exempt` (`l4.evidence.scope.file_kind`). A job of the last
`repository_ci_failed` edge E (head H) is unfixed when the unit has an earlier edge that lists the same job (head H0)
and no commit of `git log --first-parent --no-merges H0..H` changed a project file (a merge of the base is not a fix);
when H0 is not an ancestor of H, the rule does not apply. The detail of a blocker whose job failed on an earlier edge
SHALL start ``again: job `<job>` also failed on the hand-off commit <H0-10>; project files changed since: <N>.``
(without the count when H0 is no ancestor of H), counted in the first 600 characters with L4-VER-064's parts; after the
blank line it SHALL name the test and support files that fix steps put back between the two edges (`guard.test_tamper` and `guard.violation` with `phase: single` whose rule is one a fix task's note names: a frozen test, a test path freeze, a test support file, or none; not `gate configuration` or `link outside worktree`) and the fix step's notes. A FAIL round with an unfixed job SHALL escalate
with the reason code `ci_not_fixed` and no new fix unit, whatever fix rounds are left, unless it takes up an unfinished
fix unit or has a person's feedback item to take. The reason SHALL read ``the repository CI job `<job>` failed in step `<failed_step>`: <the failing lines>. It failed again on the hand-off commit <H10>, as on <H0-10>, and no commit between changed a project file: the gates here do not reproduce this CI failure, so handing off again would fail the same way`` (the failing step and the failing lines come first so that no cut loses them, each only when recorded; with neither, ``the repository CI job `<job>` failed again on …``), and every place that records or reads it SHALL keep 600 characters of it (the reason of every other escalation is cut at 300). `l4 status --unit` and `--json`, the refusal of `l4 run --unit`, `l4 yolo
status` and the sticky note SHALL show that reason and name the way on: ``the gates do not reproduce this CI failure;
fix it in a commit of your own on the unit branch (test-support files such as conftest.py are a person's change: a fix
step puts them back), or give the change as feedback (l4 feedback add --unit U --kind behaviour --when ... --then ...
--text ..., then the git lines it prints), then l4 retry --unit U --reason TEXT; l4 retry alone hands the unit off as it
is, for a failure that does not come from the change (a flaky job)``. The decision SHALL be read from the ledger and
git, so a resumed round decides the same way.

#### Scenario: SCN-OPS-40 (−) The incident: the fix changed no project file, the job fails again, the unit escalates
- **GIVEN** a unit whose CI job `ci.yml / tests` failed on H1, a round that failed on its blocker and made fix unit 1,
  whose chore commit changed only its `tasks.md` and the ledger (its step added `tests/conftest.py`, which the guard
  removed: `guard.violation`), a round 5 that passed and handed the unit off at H2 with no project file changed, and
  `ci.yml / tests` red on H2
- **WHEN** round 6 verifies the unit
- **THEN** step 0 raises the blocker with a detail that starts ``again: job `ci.yml / tests` also failed on the hand-off
  commit <H1>; project files changed since: 0.`` and names `tests/conftest.py` as put back; the round fails, no fix unit
  2 is made although fix rounds are left, the unit is `escalated` with `ci_not_fixed` and a reason that holds `failed
  again on the hand-off commit <H2>, as on <H1>`, the step `tests` and `FAILED tests/test_cli.py::test_help -
  AssertionError`, and the unit is not handed off

#### Scenario: SCN-OPS-41 (−) A hand-off as it was that fails again escalates at once
- **GIVEN** the unit of SCN-OPS-40 after a person's `l4 retry`, handed off as it was at H3, and `ci.yml / tests` red on
  H3
- **WHEN** the next round verifies it
- **THEN** the unit is `escalated` with `ci_not_fixed` and the reason `failed again on the hand-off commit <H3>, as on
  <H2>`, and no fix unit is made

#### Scenario: SCN-OPS-42 (+) A project change or a person's commit makes a fix unit, not an escalation
- **GIVEN** in turn the unit of SCN-OPS-40 whose fix chore changed `src/app/cli.py`, and whose branch has a person's
  commit between the two hand-offs that changes `tests/test_cli.py`, with `ci.yml / tests` red again on H2
- **WHEN** the next round verifies it
- **THEN** the blocker's detail starts ``again: job `ci.yml / tests` also failed on the hand-off commit <H1>; project
  files changed since: 1.``, the round makes a fix unit, and the unit is not `escalated` with `ci_not_fixed`

#### Scenario: SCN-OPS-43 (+) The status, the run refusal and the sticky note show the excerpt and the way on
- **GIVEN** a unit `escalated` with `ci_not_fixed`
- **WHEN** `l4 status --unit U`, `l4 status --json`, `l4 run --unit U` and `l4 yolo status` run, and the sticky note is
  written
- **THEN** each shows the reason with the failing step and its failing lines and names a commit of a person's own on the
  unit branch (test-support files such as `conftest.py` are a person's change), `l4 feedback add --unit U --kind
  behaviour`, `l4 retry --unit U --reason TEXT`, and that `l4 retry` alone hands the unit off as it is

#### Scenario: SCN-OPS-44 (−) A base merge is not a fix, and a rewritten history is not judged
- **GIVEN** in turn the unit of SCN-OPS-40 whose only commit between H1 and H2 besides the fix unit's is a merge of the
  base that changes `src/app/other.py`; and a unit whose H1 is no longer an ancestor of H2
- **WHEN** the next round verifies it
- **THEN** the first escalates with `ci_not_fixed`; the second's blocker starts ``again: job `ci.yml / tests` also
  failed on the hand-off commit <H1>.`` with no count, and the round makes a fix unit
