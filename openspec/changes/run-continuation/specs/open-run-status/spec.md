## Purpose

`l4 yolo status` names an open run that ended without a record (killed by the CI timeout, or cancelled), and an active
plan with nothing running or queued on the base, and gives the command that starts the next run instead of saying that
CI advances the plan.

## ADDED Requirements

### Requirement: L4-IMP-073 l4 yolo status names a run that ended without a record
For a plan that is `active`, `waiting` or `stopped`, `l4 yolo status` SHALL call the current unit's open run (L4-OPS-020,
L4-YOLO-030) "ended without a record" when either of these holds:
- its `run.started` has a `ci_url` and its age exceeds its job's timeout plus 5 minutes. The timeout is
  `run.started.job_timeout_s`; for an older event it is `ci.time_budget` when that is not `auto`, else 180 minutes,
  and the text then says `assumed`. An open run without a `ci_url` (a local run) gets no age rule.
- the forge says the CI run of its `ci_url` has completed. For a re-run, the attempt of the URL is the one read
  (`/actions/runs/<id>/attempts/<n>` on GitHub). This is asked only when a token is available and the age rule does not
  hold, with a timeout of at most 10 seconds. Any failure to ask leaves the rule unused.
The open-run line MUST keep its words and add `: it ended without a record (<why>)`. `--json` SHALL carry
`open_run.ended_without_record` and, when it is true, `open_run.why`. For an `active` plan, the one `Next:` line (and
`next` in `--json`) SHALL give the command that starts a run on the base (`gh workflow run l4.yml --ref <base>` on
GitHub, the new-pipeline page of the project on GitLab) when its open run ended without a record (the line says so and
that the unit continues from its last pushed step), and when it has no open run that may still be running and the forge
says that no run of the harness's CI is queued, pending, waiting or in progress on the base. It MUST NOT then say
`nothing: CI advances the plan`. When the forge cannot be asked, today's line stays. A `waiting` or `stopped` plan keeps
its own `Next:`.

#### Scenario: SCN-IMP-357 (+) An open run older than its job timeout names the command
- **GIVEN** an active plan on GitHub with base `staging`, whose current unit's ledger on origin has a `run.started`
  with a `ci_url` and `job_timeout_s: 10800`, 3 h 30 m ago, and no `run.finished`
- **WHEN** a person runs `l4 yolo status p1`, and then `l4 yolo status p1 --json`
- **THEN** the open-run line ends `no end recorded: it ended without a record (older than its job timeout (180 min):
  likely the CI timeout)`; the last line is `Next: the run <id> of <unit> ended without a record (…); the unit
  continues from its last pushed step: start a run on staging: gh workflow run l4.yml --ref staging`; the JSON has
  `open_run.ended_without_record: true`, `open_run.why` and the same `next`; with a `run.started` that has no
  `job_timeout_s`, the why says `180 min, assumed`

#### Scenario: SCN-IMP-358 (+) The CI says the run completed
- **GIVEN** the plan of SCN-IMP-357 with an open run 20 minutes old whose CI run the forge reports `completed` with the
  conclusion `cancelled`
- **WHEN** `l4 yolo status p1` runs with a forge token
- **THEN** the open run is called ended without a record (`its CI run is completed (cancelled)`) and the same `Next:`
  is printed

#### Scenario: SCN-IMP-359 (−) A young open run with no answer from the forge is unchanged
- **GIVEN** the plan of SCN-IMP-357 with an open run 20 minutes old and no forge token
- **WHEN** `l4 yolo status p1` runs
- **THEN** the open-run line is the one of L4-YOLO-030, `open_run.ended_without_record` is false, and `Next:` is the
  active plan's line of today

#### Scenario: SCN-IMP-372 (+) The forge is asked only when the age does not decide
- **GIVEN** the open run of SCN-IMP-357 (older than its timeout), a forge token, and a forge that fails the test when
  called; then an open run 20 minutes old whose `ci_url` ends `/actions/runs/77/attempts/2`; then an open run 4 hours
  old with no `ci_url`
- **WHEN** `l4 yolo status p1` runs for each
- **THEN** the first makes no forge call; the second reads `/repos/{r}/actions/runs/77/attempts/2`; the third gets no
  age rule and is not called ended

#### Scenario: SCN-IMP-373 (+) A stopped plan shows the suffix and keeps its Next
- **GIVEN** a plan stopped with `limit_runs` whose current unit's open run is older than its job timeout
- **WHEN** `l4 yolo status p1` runs
- **THEN** the open-run line has the suffix, and `Next:` is the stop's (the resume with `--extend-runs`)

#### Scenario: SCN-IMP-374 (+) An active plan with nothing running or queued on the base names the command
- **GIVEN** an active plan whose current unit has no open run, and a forge that reports no run of `l4.yml` queued,
  pending, waiting or in progress on `staging`
- **WHEN** `l4 yolo status p1` runs
- **THEN** `Next:` is `nothing is running or queued on staging: start a run on staging: gh workflow run l4.yml --ref
  staging`, not `nothing: CI advances the plan at each run`; with a run queued on `staging`, today's line is printed
