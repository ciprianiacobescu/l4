## Purpose

A person who passes `--yes` is not asked again, and no confirmation prompt ever waits where nobody can see it.

## ADDED Requirements

### Requirement: L4-YOLO-063 A person's --yes replaces the typed plan id
For a person, `--yes` SHALL replace the typed plan id in `l4 yolo accept PLAN SUBJECT`, in
`l4 yolo accept PLAN --all --force` and in `l4 yolo waive`; the command MUST still print what it prints today before
recording (the findings, the waived finding and its acceptance, the force summary). `plan.accepted`,
`plan.finding_waived` and `plan.force_accepted` SHALL record `confirmed: typed` or `confirmed: --yes`. For an agent,
`--yes` SHALL keep its rule: `l4 yolo accept PLAN SUBJECT` and `l4 yolo waive` only with
`yolo.review.accept_by_agents` true at `origin/<base>`; `--force` never.

#### Scenario: SCN-YOLO-168 (+) A person's --yes replaces the typed plan id
- **GIVEN** a subject a person may accept, and an accepted finding of an active plan a person may waive
- **WHEN** the person runs `l4 yolo accept p1 openspec:add-greeting --reason R --yes` and
  `l4 yolo waive p1 F-… --reason R --yes --no-run` in a terminal
- **THEN** no prompt is shown, the findings are printed, and `plan.accepted` and `plan.finding_waived` record
  `confirmed: --yes`; without `--yes` the person types `p1` and the events record `confirmed: typed`

#### Scenario: SCN-YOLO-169 (+) A person's --yes with --force
- **GIVEN** plan `p1` a person may force-accept
- **WHEN** the person runs `l4 yolo accept p1 --all --force --reason R --yes` in a terminal
- **THEN** the summary is printed, no prompt is shown, and `plan.force_accepted` records `confirmed: --yes`

#### Scenario: SCN-YOLO-170 (−) An agent's --yes keeps today's rule
- **GIVEN** an agent (`CLAUDECODE=1`) and no `accept_by_agents` on the base branch
- **WHEN** it runs `l4 yolo accept p1 openspec:add-greeting --reason R --yes`
- **THEN** it exits 2 with `acceptance is a person's decision`; with `accept_by_agents: true` it records
  `plan.accepted{actor: agent, confirmed: --yes}`

### Requirement: L4-YOLO-064 No confirmation prompt waits unseen
`l4 yolo accept` and `l4 yolo waive` SHALL prompt only when stdin is a terminal; without one and without `--yes` they
MUST exit 2 at once with a message that names `--yes`, and MUST NOT read stdin. Every prompt SHALL be written to
stderr and flushed before stdin is read, so that a pipe or a wrapper on stdout cannot hide it.

#### Scenario: SCN-YOLO-171 (−) Without a terminal nothing prompts
- **GIVEN** stdin that is not a terminal, no agent marker, `accept_by_agents: true` on the base branch, and a prompt
  function that fails the test when called
- **WHEN** `l4 yolo accept p1 openspec:add-greeting --reason R` and `l4 yolo waive p1 F-… --reason R --no-run` run
- **THEN** each exits 2 at once with a message that names `--yes`, and nothing is recorded

#### Scenario: SCN-YOLO-172 (+) The prompt goes to stderr
- **GIVEN** a person in a terminal without `--yes`
- **WHEN** `l4 yolo accept`, `l4 yolo accept --all --force` and `l4 yolo waive` ask for the plan id
- **THEN** each prompt is called with `err=True` and its text names the plan id
