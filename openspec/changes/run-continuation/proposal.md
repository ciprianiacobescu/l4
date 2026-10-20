## Why

Three observations from a consumer repository on harness 0.4.18. Its base branch is `staging`; its default branch is
`main`.

1. **The CI timeout killed a run in the middle of a step.** A `workflow_dispatch` run of `l4` on `staging` worked on
   one unit of an active delivery plan. The job has `timeout-minutes: 180` and `L4_JOB_TIMEOUT_MINUTES: "180"`. At
   2 h 35 m the harness started an agent green step; the red step before it had taken 23.5 minutes. GitHub cancelled
   the job at 180 minutes, in the middle of the step. The step's work was lost. The ledger on origin kept a
   `run.started` with no `run.finished` (the report called it `run.ended`; `l4 yolo status` prints `open run … no end
   recorded`). No continuation was dispatched, and the plan sat active for hours with nothing running.
   Cause: L4-IMP-012 is only partly built. The soft deadline (`ci.time_budget` − `ci.soft_deadline_margin`, 20 m by
   default) is checked only between units. The SPEC lists what is still to do: "the estimate per phase, the SIGINT of
   a running agent, the WIP push and the continuation dispatch". The deadline also counts from the start of `l4 run`,
   not from the start of the job, so on GitHub the checkout, setup, doctor and plan steps use up the margin without
   being counted.
2. **The schedule never moves a plan when the base is not the default branch.** GitHub runs `schedule` only on the
   default branch, with the default branch's copy of `.github/workflows/l4.yml`. That copy pins an older harness than
   `staging`'s copy, so the pin guard (L4-ADO-005, doctor CFG-008) stops the run: `l4 does no work in this run`. The
   docs and `l4 upgrade` call the schedule the fallback that starts runs on the base ("runs start on the base …
   (`l4 retry`, `l4 questions` and the schedule do that)"). With `staging` as the base, that fallback never runs.
3. **`l4 yolo status` gave the wrong next step.** For the active plan with an open run that had no end and nothing
   running, it printed `Next: nothing: CI advances the plan at each run`. Nothing was going to advance it.

## What Changes

- **The deadline counts from the job's start** (L4-IMP-066). The GitHub workflow templates get a first step that writes
  `L4_JOB_STARTED_AT` into the job environment. The soft deadline reads it, as it already reads GitLab's
  `CI_JOB_STARTED_AT`. Without it, the deadline counts from the start of the run, as before, and the run says so once.
- **A step that does not fit is not started** (L4-IMP-067). Before each implementer step (red, green, a single-phase
  chore) and each verification round, the run compares the time left with an estimate. The estimate is the longest
  step of that kind measured in this run or recorded for this unit, at least 10 minutes and at most one agent time
  limit plus one gate timeout. The first step of a run always starts while any time is left.
- **A step still running at the soft deadline is stopped** (L4-IMP-068). A timer fires at the soft deadline. Every
  agent, CLI judge and gate process the unit's run started gets SIGINT, then SIGKILL of its process group after 5 s
  (the mechanism of `ProcRunner`'s interrupt, which nothing used until now).
- **A step handed back at the deadline is resumed, not failed** (L4-IMP-069). It counts no attempt and changes no
  phase. The ledger records `deadline.reached`, and its tail and the unit branch are pushed. `run.finished` records
  `exit_code: 10` with a `reason`, and the run exits 10. Units after it in the run are not started. The next run
  continues from the last pushed step: a committed red is not done again.
- **Exactly one continuation** (L4-IMP-070). A run that handed back a step or left units at the soft deadline
  dispatches one `workflow_dispatch` of `l4.yml` on the base, even when another unit's exit code is more severe. The
  plan's own next-run start is then skipped. A run in which no step started dispatches nothing and says why.
- **A step that never fits halts** (L4-IMP-071). The same task and phase stopped at the soft deadline as the first
  step of two runs in a row, with no checkpoint between them, halts the unit with `deadline_repeated`. The reason names the fix: raise the
  job timeout or split the task. A loop of three-hour jobs that each lose their work cannot happen.
- **A run on a stale copy of the workflow relays to the base** (L4-IMP-072). In GitHub Actions, a run that the pin
  guard stops (a scheduled run on the default branch, or a push to a unit branch whose copy pins an older harness)
  dispatches one `workflow_dispatch` of `l4.yml` on the base. It does so only when the run is not on the base itself,
  when the base may have work (an active or waiting plan, an actionable unit, or anything it cannot read), and when no
  other `l4.yml` run is queued, pending, waiting or in progress on the base. It prints what it did. GitLab needs
  nothing: its schedule targets the base, and the pin guard applies only to GitHub.
- **`l4 yolo status` names a run that ended without a record** (L4-IMP-073). An open run of the current unit is
  called "ended without a record" in two cases: it is older than its job's timeout (now recorded on `run.started`), or
  the forge says that CI run has completed. For an active plan, `Next:` then gives the command that starts a run on
  the base (`gh workflow run l4.yml --ref <base>`, or GitLab's new-pipeline page). `--json` carries it.
- **Docs**: SPEC (L4-IMP-012's "implemented now", L4-ADO-005, L4-YOLO-030, L4-CI-004), runbook, `docs/yolo-mode.md`,
  the skill's error table, and CHANGELOG `## 0.4.19 (unreleased)`.

## Impact

- Code: `src/l4/deadline.py` (new), `src/l4/agents/proc.py` (`ProcOutcome.deadline`, the run-wide stop),
  `src/l4/gates/runner.py` (`GateResult.deadline`), `src/l4/implementer/workbench.py` (`run_gate_spec`,
  `wip_snapshots`), `src/l4/implementer/tdd.py` (`agent_step`), `src/l4/implementer/loop.py` (`run_task`: the check
  before each step, `step.timed`), `src/l4/llm/agent_judge.py`, `src/l4/orchestrator.py` (`run_unit`, `_defer`,
  `_verify`, `run_units`, `continue_left_units`, `run_command`, `job_remaining_s`), `src/l4/state/ledger.py`
  (`finish(reason=…)`), `src/l4/outcome.py`, `src/l4/ci/relay.py` (new), `src/l4/forge/base.py`,
  `src/l4/forge/github.py`, `src/l4/forge/gitlab.py`, `src/l4/forge/local.py` (`base_runs`, `relay_run`,
  `ci_run_state`), `src/l4/ci/templates/l4.github.yml`, `src/l4/ci/templates/l4.github-action.yml`,
  `src/l4/yolo/commands.py` (`_describe`, `_next_line`, `_activity_of`, `_render`), `src/l4/agents/fake.py` (two test
  levers).
- Ledger: new events `deadline.reached`, `step.timed`; `breaker.tripped{reason: deadline_repeated}`; new optional keys
  `run.started{job_timeout_s, job_started_at}` and `run.finished{reason}`. Older ledgers fold unchanged; older readers
  ignore the new keys and events.
- `outcome.json`: new key `relay`; a unit handed back has the `exit_reason` `soft deadline: …`.
- `l4 yolo status --json`: `open_run.ended_without_record` and `open_run.why`.
- Workflow templates: one new first step (`job start`). Consumers get it with `l4 upgrade`. Until then the deadline
  counts from the run's start, as today.
- Behaviour change: a deferred or stopped step is no longer an attempt (before, an agent killed by the CI was simply
  lost). A continuation is also dispatched when another unit of the run exits 11, 12 or 13.
- The relay works once the default branch's copy of the workflow pins 0.4.19 or later. A stopped run runs the default
  branch's harness, so that copy must be brought up to the base once, as the CFG-008 text already says.
- Spec: L4-IMP-066 to L4-IMP-073, SCN-IMP-332 to SCN-IMP-359, change-table row 56.
- No configuration key, no runtime dependency, no prompt version change.
