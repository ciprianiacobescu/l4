## Purpose

`l4 yolo status` names an open run that ended without a record (killed by the CI timeout, or cancelled), and gives the
command that starts the next run, instead of saying that CI advances the plan.

## ADDED Requirements

### Requirement: L4-IMP-073 l4 yolo status names a run that ended without a record
For a plan that is `active`, `waiting` or `stopped`, `l4 yolo status` SHALL call the current unit's open run (L4-OPS-020,
L4-YOLO-030) "ended without a record" when either of these holds:
- its age exceeds its job's timeout plus 5 minutes. The timeout is `run.started.job_timeout_s`; for an older event it
  is `ci.time_budget` when that is not `auto`, else 180 minutes, and the text then says `assumed`.
- the forge says the CI run of its `ci_url` has completed. This is asked only when a token is available and the age
  rule does not hold. Any failure to ask leaves the rule unused.
The open-run line MUST keep its words and add `: it ended without a record (<why>)`. `--json` SHALL carry
`open_run.ended_without_record` and, when it is true, `open_run.why`. For an `active` plan whose open run ended without
a record, the one `Next:` line (and `next` in `--json`) SHALL say that the run ended without a record, that the unit
continues from its last pushed step, and give the command that starts a run on the base:
`gh workflow run l4.yml --ref <base>` on GitHub, the new-pipeline page of the project on GitLab. It MUST NOT say
`nothing: CI advances the plan`. A `waiting` or `stopped` plan keeps its own `Next:`.

#### Scenario: SCN-IMP-357 (+) An open run older than its job timeout names the command
- **GIVEN** an active plan on GitHub with base `staging`, whose current unit's ledger on origin has a `run.started`
  with `job_timeout_s: 10800`, 3 h 30 m ago, and no `run.finished`
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
