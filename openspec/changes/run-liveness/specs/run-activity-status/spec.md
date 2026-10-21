## Purpose

A person who asks "is the job stuck?" gets an answer from `l4 status`, `l4 yolo status` and the runbook: when the unit
last moved, which run works on it, and where that run's live log is.

## ADDED Requirements

### Requirement: L4-OPS-020 l4 status shows the last activity and the open run of a unit
`run.started` SHALL record `ci_url` when the run is in CI:
- GitHub Actions (`GITHUB_ACTIONS=true`): `<GITHUB_SERVER_URL>/<GITHUB_REPOSITORY>/actions/runs/<GITHUB_RUN_ID>`, with
  `/attempts/<GITHUB_RUN_ATTEMPT>` when the attempt is above 1;
- GitLab CI (`GITLAB_CI=true`): `CI_JOB_URL`.
Each part MUST match a plain pattern (an `https` URL with no user part, `owner/name`, digits), else the key is left
out. The link is written with the forge filter of L4-OBS-002, and is never fetched.

From the events that the unit's snapshot reads (the unit branch's ledger and the lock ref's pending ledger, as the
last fetch left them), the snapshot SHALL have:
- `last_activity`: the event with the newest `ts`, with its `ts`, `type`, `task` (when the event has one) and
  `run_id`;
- `open_run`: the newest `run.started` with `command: "run"` whose run has no `run.finished`, with its `run_id`, its
  `ts` and its `ci_url` expanded to the forge's link.

`l4 status` SHALL show a column `LAST` after `VERDICT` with `<t> ago`, or `-` when the unit has no event.
`l4 status --unit` SHALL show, after `Stopped in run:`, the line `Last activity: <t> ago (<type>[, task <k>], run
<run id>)`, and, when there is an open run, `Open run: <run id> started <t> ago, no end recorded[: <link>]`. `--json`
SHALL have `last_activity{ts, type, task?, run_id}` and `open_run{run_id, started, ci_url?}`, each `null` when it does
not apply. Times use the format of L4-IMP-023, from the clock of the computer that runs the command.

#### Scenario: SCN-OPS-34 (+) The last activity and the open run, with its link
- **GIVEN** a fixed clock, and a unit branch whose ledger has a finished run, then a run `r-20261016T1101Z-1a2b` with `run.started{command: "run", ci_url: "<forge>/owner/repo/actions/runs/123"}` 21 minutes ago and a last event `task.red_ok{task: "2.1"}` 6 minutes ago, and no `run.finished` for it; the origin is on github.com
- **WHEN** `l4 status` and `l4 status --unit <unit>` run
- **THEN** the `LAST` cell is `6m ago`, and the block has `Last activity: 6m ago (task.red_ok, task 2.1, run r-20261016T1101Z-1a2b)` and `Open run: r-20261016T1101Z-1a2b started 21m ago, no end recorded: https://github.com/owner/repo/actions/runs/123`

#### Scenario: SCN-OPS-35 (−) No open run when the newest run ended; no link without a recorded one; no time without events
- **GIVEN** in turn: a unit whose newest run has `run.finished`; an older ledger whose open run has no `ci_url`; a lock ref whose pending ledger has a sweep run (`command: "plan --sweep"`) with no end; a unit with no ledger
- **WHEN** `l4 status --unit` runs for each
- **THEN** the first has `Last activity:` and no `Open run:` line; the second has `Open run: <id> started <t> ago, no end recorded` with no link; the third has no `Open run:` line; the fourth has `LAST` `-` and neither line

#### Scenario: SCN-OPS-36 (+) The run records its CI link, and --json shows both keys
- **GIVEN** in turn the environments `GITHUB_ACTIONS=true` with `GITHUB_SERVER_URL=https://github.com`, `GITHUB_REPOSITORY=owner/repo`, `GITHUB_RUN_ID=123`, `GITHUB_RUN_ATTEMPT=2`; `GITLAB_CI=true` with `CI_JOB_URL`; no CI; and `GITHUB_REPOSITORY=../x`
- **WHEN** a run writes `run.started` and `l4 status --json` reads the unit
- **THEN** the committed `run.started` has `ci_url` `<forge>/owner/repo/actions/runs/123/attempts/2`, the GitLab one has the job link with `<forge>`, and the last two have no `ci_url`
- **AND** `--json` has `last_activity` and `open_run` with the expanded link for the first, and `open_run` without `ci_url` for the others

### Requirement: L4-OPS-021 The runbook tells a person how to see whether a job is stuck
`docs/runbook.md` SHALL have a procedure "Is the job stuck?" that gives, in order: the heartbeat line in the CI log
and what each part means; the two limits of an agent step (`implementer.idle_timeout`, default 10m, and the 30-minute
step limit) and the `agent.idle` line; `l4 status --unit` with `Last activity:` and `Open run:`, after the fetch of
section 4.4; `gh run list --workflow l4.yml --status in_progress` for the live GitHub run; and the limit that the
unit branch shows a run only from its first step commit, so the last activity can be one step old. Section 2 SHALL
have a row that leads to it. The rows of section 4.2 SHALL name the heartbeat, the `agent.idle` and the red gate
lines; section 4.4 the `LAST` column and the two lines; section 4.5 `agent.idle` and `run.started.ci_url`. The
skill's `references/operate.md` SHALL say that `l4 status --unit` shows the last activity and the open run.

#### Scenario: SCN-OPS-37 (+) The runbook answers "is my job stuck?"
- **GIVEN** `docs/runbook.md` and `plugins/l4/skills/l4/references/operate.md`
- **WHEN** a person looks for a silent job
- **THEN** section 2 has a row that leads to the procedure, and the procedure has `working <elapsed>, <c> tool calls, last activity <t> ago`, `implementer.idle_timeout`, `30 minutes`, `no activity from`, `Last activity:`, `Open run:` and `gh run list --workflow l4.yml --status in_progress`
- **AND** section 4.2 has the heartbeat, `agent.idle` and `red: <n> new tests fail, as intended` rows, section 4.4 has `LAST`, section 4.5 has `agent.idle`, and `operate.md` names the last activity

### Requirement: L4-YOLO-030 l4 yolo status shows the last activity and the open run of a plan
For a plan that is `active`, `waiting` or `stopped`, `l4 yolo status` SHALL show, after the units, the line
`  last activity: <t> ago (<what>)` for the newer of the current unit's `last_activity` (L4-OPS-020), shown as
`<type>[, task <k>], unit <unit id>`, and the plan ledger's newest event, shown as `<type>`; and, when the current
unit has an open run, the line `  open run: <run id> started <t> ago, no end recorded[: <link>]`. `--json` SHALL have
`last_activity` and `open_run` for each plan, `null` when they do not apply. A plan in a final state SHALL show
neither line. `plan_lines` of `l4 status` MUST NOT change.

#### Scenario: SCN-YOLO-72 (+) A plan shows when its current unit last moved
- **GIVEN** a fixed clock, an `active` plan whose newest plan event is 40 minutes old and whose current unit `openspec:add-x` has an open run started 21 minutes ago and a last event `task.red_ok{task: "2.1"}` 6 minutes ago, and a `completed` plan
- **WHEN** `l4 yolo status` and `l4 yolo status --json` run
- **THEN** the active plan has `  last activity: 6m ago (task.red_ok, task 2.1, unit openspec:add-x)` and `  open run: <id> started 21m ago, no end recorded: <link>`, its JSON has both keys, and the completed plan has neither line and `null` for both keys
