## Purpose

A time budget that leaves less than one step after the margin is a configuration error that a person sees before any
unit runs, not a unit that halts with `deadline_repeated`. A budget that shortens the job is named. Every deadline text
names the fix for the budget's real source, and `l4 upgrade` says when the configuration has one of these problems.

## ADDED Requirements

### Requirement: L4-IMP-076 A usable budget below one step is refused before any unit
When `ci.time_budget` is a duration (not `auto`) and `ci.time_budget` minus `ci.soft_deadline_margin` is less than the
smallest step estimate (`l4.deadline.FLOOR_S`, 600 s), the configuration SHALL be reported as an error with its cause
and its fix, in these words: `ci.time_budget <budget> minus soft_deadline_margin <margin> leaves <N> min, less than one
step (10 min): set ci.time_budget: auto (the job timeout) or raise it`, where `<budget>` and `<margin>` are the
configured values and `<N>` the whole minutes left, rounded down (`leaves no time` when nothing is left). Doctor
`CFG-012` (scopes `ci`, `local`, `config`) SHALL fail with this text as an error, so `l4 doctor` exits 3. `l4 run` SHALL
refuse with this text and exit 2 after the configuration and the run's preflight are read and before the follow-ups,
the plan step and any unit, so no lease, worktree, ledger write, plan record or forge call happens. The configuration
MUST still load: `l4 status`, `l4 upgrade` and every other command run on it. `l4 run --dry-run`, `l4 verify` and the
budget read between units are not changed. A budget equal to the floor after the margin is not an error.

#### Scenario: SCN-IMP-385 (−) Doctor fails a budget that leaves less than one step
- **GIVEN** `.l4/config.yaml` with `ci.time_budget: 21m` and `ci.soft_deadline_margin: 20m`
- **WHEN** `l4 doctor` runs (also `--ci`, also `--adoption --no-gates`)
- **THEN** `CFG-012` fails as an error with `ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than
  one step (10 min): set ci.time_budget: auto (the job timeout) or raise it`, and doctor exits 3

#### Scenario: SCN-IMP-386 (−) l4 run refuses before any unit
- **GIVEN** the configuration of SCN-IMP-385, a unit with a next step, an active plan, and `L4_JOB_TIMEOUT_MINUTES=180`
- **WHEN** `l4 run` runs
- **THEN** it prints the text of SCN-IMP-385 and exits 2; no lease, worktree or ledger event is written, no plan step
  runs, and the forge receives no call

#### Scenario: SCN-IMP-387 (+) The configuration still loads, and a budget at the floor passes
- **GIVEN** in turn `ci.time_budget: 21m` with the margin `20m`; `30m` with `20m`; `15m` with `20m`; and `auto`
- **WHEN** `l4 status` and `l4 doctor` run
- **THEN** `l4 status` runs on every one; `CFG-012` passes `30m` (10 min left, the floor) and `auto`, and fails `15m`
  with `leaves no time`

### Requirement: L4-IMP-077 A time budget that shortens the job is named
When `ci.time_budget` is a duration and the job's own timeout is known, and the job's timeout minus `ci.time_budget` is
more than `ci.soft_deadline_margin`, a warning SHALL say so: `ci.time_budget <budget> is shorter than the job's timeout
(<T> min, <source>) by more than soft_deadline_margin <margin>: the soft deadline comes at minute <D>, not at minute
<J>; set ci.time_budget: auto (the job timeout) unless the job must stop early`, where `<D>` is the budget minus the
margin and `<J>` the job's timeout minus the margin, in whole minutes. The job's timeout SHALL be read from GitLab's
`CI_JOB_TIMEOUT` (seconds), else `L4_JOB_TIMEOUT_MINUTES`, else the first `timeout-minutes: <integer>` of the
checked-out `.github/workflows/l4.yml` (a regular file of at most 1 MB, not a link; the source is then
`.github/workflows/l4.yml timeout-minutes`); when none gives it, no warning is given. Doctor `CFG-012` SHALL fail with
this text as a warning (its result's severity is `warn`; doctor's exit code is not changed by it). When the error of
L4-IMP-076 applies too, `CFG-012` SHALL be an error whose message is both texts joined by `; `. `l4 run` SHALL log the
warning once, as a WARNING, at the point where it checks L4-IMP-076, and go on; when L4-IMP-076 refuses, only the
refusal's text is printed.

#### Scenario: SCN-IMP-388 (−) A budget that shortens the job warns in doctor and in the run
- **GIVEN** `ci.time_budget: 60m`, the margin `20m`, and `L4_JOB_TIMEOUT_MINUTES=180`
- **WHEN** `l4 doctor --ci` and then `l4 run` run
- **THEN** `CFG-012` warns `ci.time_budget 60m is shorter than the job's timeout (180 min, L4_JOB_TIMEOUT_MINUTES) by
  more than soft_deadline_margin 20m: the soft deadline comes at minute 40, not at minute 160; set ci.time_budget: auto
  (the job timeout) unless the job must stop early`, doctor exits 0, and `l4 run` logs the same text once and runs its
  units

#### Scenario: SCN-IMP-389 (+) The job's timeout comes from the job, else the workflow file, else nothing is said
- **GIVEN** `ci.time_budget: 60m` and the margin `20m`, and in turn: `CI_JOB_TIMEOUT=3600`; no job variable and a
  checked-out `.github/workflows/l4.yml` with `timeout-minutes: 180`; no job variable and no workflow file;
  `ci.time_budget: 170m` with `L4_JOB_TIMEOUT_MINUTES=180`; and `ci.time_budget: auto` with `L4_JOB_TIMEOUT_MINUTES=180`
- **WHEN** `l4 doctor` runs
- **THEN** the first passes (60 min is the job's timeout), the second warns with the source `.github/workflows/l4.yml
  timeout-minutes`, and the third, the fourth (10 min shorter, not more than the margin) and the fifth pass

#### Scenario: SCN-IMP-390 (−) The configuration of the incident gets both texts
- **GIVEN** `ci.time_budget: 21m`, the margin `20m`, and `L4_JOB_TIMEOUT_MINUTES=180`
- **WHEN** `l4 doctor --ci` runs
- **THEN** `CFG-012` is an error whose message is the text of SCN-IMP-385, then `; `, then the warning with `the soft
  deadline comes at minute 1, not at minute 160`

### Requirement: L4-IMP-078 The deadline texts name the budget's source
The budget's source SHALL be `ci.time_budget` when that is a duration, else `CI_JOB_TIMEOUT`, else
`L4_JOB_TIMEOUT_MINUTES`, the same order in which the budget is read. The fix that the `deadline_repeated` halt reason
(L4-IMP-071) and the "no step fitted" warning (L4-IMP-070) name SHALL be the source's: `raise ci.time_budget (or set it
to auto)` for `ci.time_budget`, `raise the job's timeout (CI_JOB_TIMEOUT)` for `CI_JOB_TIMEOUT`, and `raise
timeout-minutes and L4_JOB_TIMEOUT_MINUTES` for `L4_JOB_TIMEOUT_MINUTES` or an unknown source. The halt reason SHALL
read `<step> does not fit in one job: <fix> or split the task, then l4 retry --unit <U> --reason TEXT (stopped twice:
…)`, unchanged for `L4_JOB_TIMEOUT_MINUTES`. The warning SHALL read `no step fitted before the soft deadline (<N> s left
at the first step); <fix>, or split the task`, with the `continuation: not requested: ` prefix of L4-IMP-070, and MUST
NOT name another source's fix. `run.started` SHALL record `job_budget_source` with the source, beside `job_timeout_s`,
when a budget is known.

#### Scenario: SCN-IMP-391 (−) A halt under ci.time_budget names ci.time_budget
- **GIVEN** `ci.time_budget: 3h` and `L4_JOB_TIMEOUT_MINUTES=180` (the set budget wins), and a green of task
  1.1 stopped at the deadline as the first step of two runs in a row
- **WHEN** the second stop halts the unit with `deadline_repeated`
- **THEN** the reason starts `task 1.1 green does not fit in one job: raise ci.time_budget (or set it to auto) or split
  the task, then l4 retry --unit`; with `ci.time_budget: auto` and `L4_JOB_TIMEOUT_MINUTES=180` it is today's text
  (`raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES or split the task`), and with `CI_JOB_TIMEOUT=10800` it names
  `raise the job's timeout (CI_JOB_TIMEOUT)`

#### Scenario: SCN-IMP-392 (−) The no-step-fitted warning names one source
- **GIVEN** a run in which no step started (the first check found no time left), in turn with `ci.time_budget: 40m`
  and with `ci.time_budget: auto` and `L4_JOB_TIMEOUT_MINUTES=180`
- **WHEN** the run ends
- **THEN** the first warning ends `raise ci.time_budget (or set it to auto), or split the task`; the second ends
  `raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES, or split the task` and does not contain `or ci.time_budget`

#### Scenario: SCN-IMP-393 (+) run.started records the budget's source
- **GIVEN** in turn `ci.time_budget: 3h`; `auto` with `L4_JOB_TIMEOUT_MINUTES=180`; `auto` with `CI_JOB_TIMEOUT=10800`;
  and `auto` with neither
- **WHEN** `l4 run` starts a unit
- **THEN** `run.started` has `job_timeout_s: 10800` and `job_budget_source` `ci.time_budget`, `L4_JOB_TIMEOUT_MINUTES`
  and `CI_JOB_TIMEOUT` in the first three, and neither key in the fourth

### Requirement: L4-IMP-079 l4 upgrade names a budget problem
`l4 upgrade` (also with `--dry-run`, for every delivery: vendored, fetched and action) SHALL print, after the files it
changes, the text of L4-IMP-076 as `error: <text>; until it is fixed, l4 run exits 2 and doctor CFG-012 fails` when it
applies, and the text of L4-IMP-077 as `warning: <text>` when it applies. For L4-IMP-077 the job's timeout SHALL be the
`timeout-minutes` of the `.github/workflows/l4.yml` that the upgrade writes when it writes one, else of the file on
disk; the job's variables of the environment that runs `l4 upgrade` are not read. These lines MUST be printed whether or
not a file changes, MUST NOT change any file, and MUST NOT change the exit code (0).

#### Scenario: SCN-IMP-394 (−) The upgrade of the incident's configuration names both problems
- **GIVEN** an action adoption with `ci.time_budget: 21m`, the margin `20m`, and a workflow that the upgrade re-renders
  with `timeout-minutes: 180`
- **WHEN** `l4 upgrade --harness-commit <sha>` runs, and again with `--dry-run`
- **THEN** both print `error: ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, …; until it is fixed, l4
  run exits 2 and doctor CFG-012 fails` and `warning: ci.time_budget 21m is shorter than the job's timeout (180 min,
  .github/workflows/l4.yml timeout-minutes) …`, `.l4/config.yaml` keeps `time_budget: 21m`, and both exit 0

#### Scenario: SCN-IMP-395 (+) An upgrade with a sound budget prints no budget line
- **GIVEN** in turn an action adoption with `ci.time_budget: auto`; a fetched adoption with `ci.time_budget: 3h` and
  the GitHub workflow; and a vendored GitLab adoption with `ci.time_budget: 60m` and no GitHub workflow
- **WHEN** `l4 upgrade` runs, with `L4_JOB_TIMEOUT_MINUTES=600` in its environment
- **THEN** no `error:` or `warning:` budget line is printed (the third has no known job timeout, and the environment's
  variable is not read)
