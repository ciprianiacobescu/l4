## Purpose

When no model can review a plan, a person can still activate it: one audited decision accepts every unit and batch as
it stands, bound to their text, shown wherever the plan and its units are shown, and never taken by an agent.

## ADDED Requirements

### Requirement: L4-YOLO-057 A person can force-accept every subject of a plan without a review
`l4 yolo accept PLAN --all --force --reason TEXT [--yes]` SHALL accept every unit of the plan and every batch with more
than one unit as it stands, whatever the review says or lacks: no review, a review for other inputs, BLOCKED, a
blocking finding, a material finding and fewer than `yolo.review.accept_after_rounds` judged versions are all
overridden. It MUST NOT call a model. It SHALL print each subject with what it overrides, then take the person's
confirmation (L4-YOLO-063), then append in one leased write `plan.admitted` (unless the plan is already admitted or
reviewed at this digest with this order) and `plan.force_accepted{plan_digest, subjects, reason, by, actor: person,
marker: null, confirmed}`, where each subject has its digest (a batch: its units' digests), `skipped` (`no_review`,
`stale_review`, `blocked`, `blocking`, `material`, `rounds`, `not_ready`, or none), `review_at`, `verdict` and
`material`. `--force` without `--all`, `--all` without `--force`, `--all` with a SUBJECT, and neither a SUBJECT nor
`--all` MUST exit 2 before anything is read.

#### Scenario: SCN-YOLO-150 (+) A person force-accepts a plan whose review is BLOCKED by the judge
- **GIVEN** plan `p1` with units A and B in batch `b1`, reviewed at the current digests with A BLOCKED (`schema_invalid`)
  and B READY, and a judge factory that fails the test if it is built
- **WHEN** a person in a terminal runs `l4 yolo accept p1 --all --force --reason "the judge is down; build as written"`
  and types `p1`
- **THEN** it prints A with `BLOCKED` and B with `READY at these inputs: nothing is overridden`, records
  `plan.force_accepted` with `subjects.A.skipped == ["blocked"]`, `subjects.B.skipped == []`, the review's `at` as
  `review_at`, `actor: person`, `confirmed: typed`, no judge is built and no review is recorded, and it exits 0

#### Scenario: SCN-YOLO-151 (+) A plan with no review is force-accepted and admitted
- **GIVEN** plan `p1` pushed and never reviewed (no ledger event)
- **WHEN** a person runs `l4 yolo accept p1 --all --force --reason R` and types `p1`
- **THEN** `plan.admitted` and then `plan.force_accepted` are recorded, every subject has `skipped: ["no_review"]` and
  `review_at: null`, and `l4 yolo status p1` shows the plan `admitted`

#### Scenario: SCN-YOLO-152 (−) Any answer other than the plan id records nothing
- **GIVEN** plan `p1` that a person may force-accept
- **WHEN** the person answers `yes` to the prompt
- **THEN** it exits 2 with `the plan id was not typed: nothing was recorded`, and the plan ref does not move

#### Scenario: SCN-YOLO-153 (−) The flags are checked before anything is read
- **GIVEN** any repository
- **WHEN** `l4 yolo accept p1 --force --reason R`, `l4 yolo accept p1 --all --reason R`,
  `l4 yolo accept p1 openspec:a --all --force --reason R` and `l4 yolo accept p1 --reason R` run
- **THEN** each exits 2 naming what is missing or too much, and nothing is fetched or written

### Requirement: L4-YOLO-058 Only a person in a terminal force-accepts
`l4 yolo accept --all --force` SHALL be refused (exit 2, before the plan is fetched, nothing written) for every caller
that `l4.actor.actor` does not name a person: an agent marker is set, or stdin is not a terminal. It MUST be refused
for an agent even when `yolo.review.accept_by_agents` is true, and for every MCP caller (the server runs the CLI with
`AI_AGENT=l4-mcp` and no terminal); the MCP server MUST offer no tool that runs `l4 yolo accept`. The refusal SHALL say
that it is a person's decision, why the caller is not one, and the command a person runs.

#### Scenario: SCN-YOLO-154 (−) An agent is refused even when the target lets agents accept
- **GIVEN** `yolo.review.accept_by_agents: true` in `.l4/config.yaml` on the base branch and `CLAUDECODE=1`
- **WHEN** `l4 yolo accept p1 --all --force --reason R --yes` runs
- **THEN** it exits 2 with `accept: --force is a person's decision, never an agent's (CLAUDECODE is set)` and
  `l4 yolo accept p1 --all --force --reason "..."`, and the plan ref does not move

#### Scenario: SCN-YOLO-155 (−) An MCP caller is refused
- **GIVEN** the environment the MCP server gives a tool (`AI_AGENT=l4-mcp`, no terminal)
- **WHEN** `l4 yolo accept p1 --all --force --reason R` runs in it
- **THEN** it exits 2 naming `AI_AGENT is set`, and no tool of the server's tool list runs `yolo accept`

#### Scenario: SCN-YOLO-156 (−) Without a terminal it is refused
- **GIVEN** no agent marker and stdin that is not a terminal
- **WHEN** `l4 yolo accept p1 --all --force --reason R --yes` runs
- **THEN** it exits 2 naming `stdin is not a terminal`, and nothing prompts

### Requirement: L4-YOLO-059 What a force acceptance never overrides
`l4 yolo accept --all --force` SHALL keep, with their own refusal and nothing recorded: a missing plan file or one that
is not a plan; the plan status rule of L4-YOLO-027 (before the activation, or stopped with `inputs_changed` or
`unit_rejected`); every finding of the admission that `l4 yolo activate` runs (among them `unknown_unit` for a unit
folder that does not exist on the target, `cycle`, `unknown_dependency`, `intake`, `open_questions`); and a unit whose
current digest is missing (`unit_missing`).

#### Scenario: SCN-YOLO-157 (−) A unit with no folder on the target is still refused
- **GIVEN** a plan that names `openspec:ghost`, which has no folder on the target
- **WHEN** a person runs `l4 yolo accept p1 --all --force --reason R`
- **THEN** it exits 2 with `accept: p1 is not admitted:` and a line `unknown_unit: …`, before any prompt, and
  nothing is recorded; a known unit whose current digest is missing is refused with `(unit_missing)` the same way

#### Scenario: SCN-YOLO-158 (−) A dependency cycle is still refused
- **GIVEN** a plan where A depends on B and B on A
- **WHEN** a person runs `l4 yolo accept p1 --all --force --reason R`
- **THEN** it exits 2 with a `cycle: dependency cycle: …` line and records nothing

#### Scenario: SCN-YOLO-159 (−) An active plan cannot be force-accepted
- **GIVEN** an active plan `p1`
- **WHEN** a person runs `l4 yolo accept p1 --all --force --reason R`
- **THEN** it exits 2 with `p1 is active: an acceptance is possible before activation, or when the plan is stopped
  with inputs_changed or unit_rejected` and records nothing

### Requirement: L4-YOLO-060 A force acceptance is bound to the text it accepted
A force acceptance SHALL hold for a subject while the plan file's digest is the one it recorded and the subject's
current unit digest (a batch: each of its units') is the one it recorded, by the digest rule of the activation and of
`inputs_changed`. A change of the plan file MUST void it for every subject; a change of a unit's spec MUST void it for
that unit and every batch that holds the unit. A later `plan.force_accepted` SHALL replace the earlier one.
`l4 yolo accept PLAN --all --force --withdraw --reason TEXT` SHALL record `plan.force_acceptance_withdrawn{reason, by,
actor, marker}`; it MUST NOT be refused for who runs it, and is refused after the activation and when no force
acceptance is recorded.

#### Scenario: SCN-YOLO-160 (−) A spec change voids it for that unit and its batch
- **GIVEN** a force acceptance of `p1` (A and B in batch `b1`), after which a person pushes a change to A's `spec.md`
- **WHEN** the holds are computed
- **THEN** A and `batch:b1` do not hold and B holds; after a change of the plan file none holds; a tick in A's
  `tasks.md` changes nothing

#### Scenario: SCN-YOLO-161 (+) A withdrawal removes it, whoever runs it
- **GIVEN** a force acceptance of `p1` before the activation, and an agent (`AI_AGENT=1`)
- **WHEN** the agent runs `l4 yolo accept p1 --all --force --withdraw --reason "spec reworked"`
- **THEN** `plan.force_acceptance_withdrawn{actor: agent}` is recorded, the state has no force acceptance, and a second
  withdrawal exits 2 with `nothing to withdraw`

#### Scenario: SCN-YOLO-162 (+) A later force acceptance replaces the earlier one
- **GIVEN** a force acceptance of `p1` voided for A by a spec change
- **WHEN** a person force-accepts `p1` again
- **THEN** the state holds only the new one and every subject holds

### Requirement: L4-YOLO-061 Activation of a force-accepted plan
`l4 yolo activate` SHALL NOT require a review when a force acceptance holds for every subject of the plan (a missing or
stale review is not a refusal; the findings of a current review on a subject the acceptance did not override still are);
every other refusal of L4-YOLO-005 stays. Otherwise the review rules of L4-YOLO-005 apply, and a subject that a holding force
acceptance overrode (its recorded `skipped` is not empty) MUST count as cleared whatever a current review says of it.
`plan.activated{accepted}` SHALL hold each such subject as `{findings: [], reason, by, actor: person, force: true}` and
the event SHALL record `review: force_accepted` when it holds one. A refusal while a force acceptance is recorded MUST
name the subjects it no longer holds for.

#### Scenario: SCN-YOLO-163 (+) A plan never reviewed is activated after a force acceptance
- **GIVEN** plan `p1` never reviewed and force-accepted by a person
- **WHEN** `l4 yolo activate p1 --reason go` runs
- **THEN** it exits 0, prints `openspec:add-greeting: force-accepted without review by <by> (<reason>)` for each subject,
  and `plan.activated` has `review: force_accepted` and `accepted.<subject> == {findings: [], reason, by, actor:
  person, force: true}` for A, B and `batch:b1`

#### Scenario: SCN-YOLO-164 (+) A review recorded after the force acceptance does not undo it
- **GIVEN** a force acceptance of `p1`, then a CI review at the same digests that says A is BLOCKED
- **WHEN** `l4 yolo activate p1 --reason go` runs
- **THEN** it exits 0 and A is a force item of `plan.activated{accepted}`

#### Scenario: SCN-YOLO-165 (−) Activation after a voiding change is refused and names the subjects
- **GIVEN** a force acceptance of `p1`, then a pushed change to A's spec and no review since
- **WHEN** `l4 yolo activate p1 --reason go` runs
- **THEN** it exits 2 with the review refusal and `the force acceptance by <by> no longer holds for
  openspec:add-greeting, batch:b1: their spec or the plan file changed`, and records nothing

### Requirement: L4-YOLO-062 A force acceptance is shown wherever the plan and its units are
`l4 yolo status` and `l4 yolo findings` (text and `--json`) SHALL show each overriding subject of a recorded force
acceptance as `<subject>: force-accepted without review by <by> (<reason>)`, with `; no longer holds: its spec or the
plan file changed` when it does not hold, and `l4 yolo status` SHALL name `l4 yolo activate` in its `Next:` line when
it covers the plan. After the activation the status, the plan report and each force-accepted unit's PR body SHALL name
it, and the unit's implementer prompt SHALL carry the reason with the rule that no model reviewed the specification.

#### Scenario: SCN-YOLO-166 (+) Status and findings name the force acceptance
- **GIVEN** plan `p1` force-accepted while its review was BLOCKED for A
- **WHEN** `l4 yolo status p1`, `l4 yolo status p1 --json`, `l4 yolo findings p1` and `l4 yolo findings p1 --json` run
- **THEN** the text shows `openspec:add-greeting: force-accepted without review by alex@example.com (R)` and
  `Next: l4 yolo activate p1 --reason TEXT`; the JSON has `force_accepted` with `covered: true` and each subject's
  `holds`, `skipped`, `review_at` and `verdict`

#### Scenario: SCN-YOLO-167 (+) The implementer gets the reason; the report and the PR body name it
- **GIVEN** a plan activated with a force item for unit A
- **WHEN** A is dispatched, its implementer prompt is built, its PR is opened and the plan report is written
- **THEN** `.l4/review-accepted.json` has the item with `force: true` and no findings, the prompt's block
  `accepted review findings` holds the force rule and `Accepted without review (<by>): <reason>`, the PR body has
  `- Force-accepted without review by <by> (<reason>): no model reviewed this unit's specification before it was
  built.`, and the report has `- openspec:add-greeting: force-accepted without review by <by> (<reason>)`; the merge
  guard has no accepted finding open for A

### Requirement: L4-YOLO-067 Documentation of the force path and of the confirmation
`docs/yolo-mode.md` SHALL have a section "When the reviewer is unavailable" with the force path, who may run it, what it
never overrides, the risk that specifications no model reviewed get built, and the alternative of reviewing in CI with
`l4 yolo review <plan>` without `--local`. The runbook SHALL give the procedure. The skill's `plan.md` and `operate.md`
MUST tell an agent never to run `--force` and to give the person the exact command. The CHANGELOG's 0.4.18 section and
the SPEC SHALL name the force path, a person's `--yes` and the acceptance binding fix.

#### Scenario: SCN-YOLO-176 (+) The docs teach the force path and keep agents off it
- **GIVEN** the repository's docs and skill
- **WHEN** they are read
- **THEN** `docs/yolo-mode.md` has "When the reviewer is unavailable" with `l4 yolo accept <plan> --all --force` and
  `l4 yolo review <plan>`, the runbook's 12.2a has the procedure, `plan.md` and `operate.md` say never to run `--force`,
  and the CHANGELOG's 0.4.18 section names `plan.force_accepted`
