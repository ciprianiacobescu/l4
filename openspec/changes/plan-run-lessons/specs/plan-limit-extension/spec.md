## Purpose

A person who sees an active delivery plan run out raises its limit at once, on record, without waiting for the stop;
an agent cannot.

## ADDED Requirements

### Requirement: L4-YOLO-050 A limit of an active plan is raised without waiting for the stop
`l4 yolo resume PLAN --reason TEXT --extend-…` on an `active` plan SHALL record `plan.extended{by, actor, marker,
agent_key, reason, extend, limits_before, limits_after}` and nothing else: no resume, no run. The limits in force
(L4-YOLO-014) SHALL include it. No `--extend-…`, or one that changes no limit, SHALL be refused (exit 2). `l4 yolo
status` SHALL list the extensions and name the option in an active plan's `Next:` line.

#### Scenario: SCN-YOLO-130 (+) A run limit of an active plan is raised before the stop
- **GIVEN** an active plan `p1` with `max_runs` 90, 82 runs used and three units left
- **WHEN** a person runs `l4 yolo resume p1 --reason "three units left" --extend-runs 20`
- **THEN** `plan.extended` is recorded with `actor: person`, the reason, `extend: {runs: 20}`, `limits_before.runs` 90
  and `limits_after.runs` 110; the plan stays active; no `plan.resumed` is recorded and no run is started; the command
  prints `runs 90 -> 110` and that nothing was resumed, and exits 0

#### Scenario: SCN-YOLO-131 (+) The plan step counts the raised limit
- **GIVEN** the plan of SCN-YOLO-130 after the extension, with 90 runs used
- **WHEN** the plan step checks the limits before its next dispatch
- **THEN** no limit is reached (90 of 110), and the plan does not stop with `limit_runs`

#### Scenario: SCN-YOLO-132 (−) An active plan is not resumed without an extension
- **GIVEN** an active plan `p1`
- **WHEN** `l4 yolo resume p1 --reason TEXT` runs with no `--extend-…`
- **THEN** it exits 2 with `p1 is active: only a stopped or waiting plan resumes`, names `--extend-cost`,
  `--extend-runs`, `--extend-attempts` and `--extend-deadline`, and writes nothing

#### Scenario: SCN-YOLO-133 (−) An extension that changes no limit is refused
- **GIVEN** an active plan with no `max_runs` and the deadline 2026-10-20T18:00:00Z
- **WHEN** a person runs `l4 yolo resume` on it with `--extend-runs 5`, and then with
  `--extend-deadline 2026-10-20T12:00:00Z`
- **THEN** each exits 2 naming the limit (`has no run limit`, `is not later than the deadline in force`), and nothing is
  written

#### Scenario: SCN-YOLO-135 (+) An extension changes the limits only
- **GIVEN** three activated plan ledgers, one active, one waiting with `unit_awaiting_human`, and one stopped with
  `merge_refused` and one stale merge, each followed by `plan.extended{extend: {runs: 5}}`, and a fourth ledger with
  `plan.extended` before its activation
- **WHEN** they are folded
- **THEN** each of the three keeps its status, its wait or stop reason and its count of stale merges, and has a run
  limit 5 higher; the fourth has no extension

#### Scenario: SCN-YOLO-136 (+) The status shows the extension, and the Next line of an active plan names it
- **GIVEN** the plan of SCN-YOLO-130 after the extension
- **WHEN** `l4 yolo status p1` runs
- **THEN** it shows `runs 82 of 110`, a line `extended: runs 90 -> 110 by <who> (person): three units left`, and a
  `Next:` line that names `l4 yolo resume p1 --reason TEXT --extend-runs N`

### Requirement: L4-YOLO-051 Raising a plan's limit is a person's decision
Every `--extend-…` of `l4 yolo resume`, on an active, waiting or stopped plan, SHALL be refused (exit 2, nothing
written) for an agent (`l4.actor.actor`), unless `yolo.extend_by_agents` is `true` in `.l4/config.yaml` on the base
branch (default `false`). The refusal SHALL name the command a person runs and the key. The event SHALL record the
actor, its marker and `agent_key` (whether the key allowed it).

#### Scenario: SCN-YOLO-134 (−) An agent cannot raise a limit
- **GIVEN** the plan `p1` while it is active, and the same plan seeded again stopped with `limit_runs`
- **WHEN** `l4 yolo resume p1 --reason TEXT --extend-runs 5` runs on each with `CLAUDECODE=1` in the environment
- **THEN** each exits 2 with `raising a plan's limits is a person's decision` and a `Fix:` line that names the command
  for a person and the key `yolo.extend_by_agents`, and nothing is written

#### Scenario: SCN-YOLO-141 (+) With the key, an agent raises a limit and the event says so
- **GIVEN** `yolo.extend_by_agents: true` in `.l4/config.yaml` on the base branch, an active plan `p1` and, in turn, the
  same plan stopped with `limit_runs`
- **WHEN** an agent (`CLAUDECODE=1`, no terminal) runs `l4 yolo resume p1 --reason TEXT --extend-runs 20`
- **THEN** on the active plan `plan.extended` is recorded, on the stopped plan `plan.resumed` is recorded, each with
  `actor: agent`, `marker: CLAUDECODE`, `agent_key: true` and `extend: {runs: 20}`; with the key `false`, or absent,
  the refusal of SCN-YOLO-134 stands
