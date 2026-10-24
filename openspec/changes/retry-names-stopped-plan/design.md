# Design: retry-names-stopped-plan

## Decisions

**D1. Name the command, do not resume.** Resuming is a plan-level decision with its own record (`plan.resumed`, its
reason in the plan ledger) and its own refusals (L4-YOLO-013, -014: refused while the cause is still there). A retry
that resumed as a side effect would write a plan record nobody asked for and hide a refusal. The retry names the exact
command instead; the operator, or the agent, runs it.

**D2. No run when the run would be wasted.** A run started while the plan is stopped finds the unit held and ends with
`nothing to do`, and it counts against the plan's `max_runs`. When a stopped plan holds the retried unit, the retry
skips the start of L4-OPS-002 and its line says why; `l4 yolo resume` starts the run (L4-OPS-002 of the resume).

**D3. The same lookup as `l4 yolo status`.** The plan files at `origin/<base>` and the folded plan states, read the way
`l4 yolo status` reads them (`l4.yolo.plans.plan_files_at`, `holds_of`, the fold of the plan ledger), so the two
commands never disagree on what holds a unit. Any error in the lookup is logged at debug level and ignored.

## Failure cases

- Unit held by a stopped plan: the hint line, no run, exit 0.
- Unit held by an active or waiting plan, or by no plan: the run starts as before.
- `--no-run` with a stopped plan: the hint line, no run (as asked).
- Plan files or states unreadable: as before, without the hint.
