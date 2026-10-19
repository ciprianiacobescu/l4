## Purpose

An agent drives a plan with `l4 yolo go` as far as an agent may, and hands the person the exact command for the rest;
the MCP server offers the same command read-mostly; the docs and the skill teach the one command.

## ADDED Requirements

### Requirement: L4-YOLO-090 Agents run the agent-allowed steps; the MCP tool is read-mostly
For an agent caller (`l4.actor.actor`), `l4 yolo go` SHALL run preflight, the push of the hand-off (L4-YOLO-082),
check, review and findings, and SHALL accept only with `--accept-findings --yes` where `l4 yolo accept` lets an agent
accept (`yolo.review.accept_by_agents` true at `origin/<base>`). It MUST NOT prompt, MUST NOT force-accept and MUST NOT
activate; at a person's step it SHALL stop with exit 27 and the person's exact command. No configuration key SHALL
change these rules. The MCP server SHALL offer the tool `l4_plan_go`, which runs `l4 yolo go PLAN --reason TEXT --json
--no-push [--wait DURATION]` as an agent; it MUST NOT offer `--accept-findings`, `--force`, `--yes` or `--local`, and
its description SHALL say that it may ask CI for a review (judge tokens), may wait, and never pushes, accepts or
activates.

#### Scenario: SCN-YOLO-236 (+) An agent goes as far as it may
- **GIVEN** an agent (`CLAUDECODE=1`), plan `p1` reviewed with B NEEDS_REVISION on two versions, and
  `yolo.review.accept_by_agents: true` pushed in `.l4/config.yaml` on `main`
- **WHEN** the agent runs `l4 yolo go p1 --reason R --accept-findings`, then with `--yes` added
- **THEN** the first exits 29 with `Next: l4 yolo go p1 --reason R --accept-findings --yes` and records nothing; the
  second records `plan.accepted{actor: agent}` of B and exits 27 at the activation with
  `Next: a person runs: l4 yolo go p1 --reason R`; without the key the first run exits 27 at accept with
  `Next: a person runs: l4 yolo go p1 --reason R --accept-findings`; no prompt is ever called

#### Scenario: SCN-YOLO-237 (+) The MCP tool runs go read-mostly
- **GIVEN** the MCP server's tool list
- **WHEN** `l4_plan_go` is called with `plan: "p1"`, `reason: "R"` and `wait: "0"` (`wait` is a string parameter)
- **THEN** it runs `l4 yolo go --json --reason=R --wait=0 --no-push -- p1` with `AI_AGENT=l4-mcp` and no terminal, its
  schema has no `accept_findings`, `force`, `yes` or `local`, its description says it never pushes, accepts or
  activates, and no tool of the list runs `yolo accept` or `yolo activate`

### Requirement: L4-YOLO-091 Documentation of the one command
`docs/yolo-mode.md` SHALL have a section "One command: `l4 yolo go`" with the steps, the flags, the stop codes, the JSON
document, re-running, what an agent's run does and that `go` activates (`l4 yolo status` is the read-only view). The
runbook's procedure 12.2 SHALL start with "Or simply: `l4 yolo go`". The skill's `operate.md` SHALL give
`l4 yolo go <id> --reason "…"` as a person's first step of the plan runbook and the agent's use (`--json`, a bounded
`--wait`, exit 27 hands the person `next_command`, never `--force`); `plan.md` SHALL name it in the hand-off. The
CHANGELOG's `## 0.4.19 (unreleased)` section and the SPEC SHALL name the command.

#### Scenario: SCN-YOLO-238 (+) The docs teach the one command
- **GIVEN** the repository's docs and skill
- **WHEN** they are read
- **THEN** `docs/yolo-mode.md` has "One command: `l4 yolo go`" with each stop code 20 to 29 and `l4/yolo-go@1`, the
  runbook's 12.2 starts with `Or simply: l4 yolo go`, `operate.md` has `or simply: l4 yolo go` and `--wait`, `plan.md`
  names `l4 yolo go`, the CHANGELOG's `## 0.4.19 (unreleased)` names `l4 yolo go`, and `docs/SPEC.md` has
  `**L4-YOLO-080 ` to `**L4-YOLO-091 ` and `| 55 | \`yolo-go\` |`
