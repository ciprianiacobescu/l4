## Purpose

Any MCP client can manage L4 plans and debug L4 units through typed tools, under the same rules as the CLI.

## ADDED Requirements

### Requirement: L4-MCP-001 l4 mcp serve is an MCP server over stdio
`l4 mcp serve` SHALL speak MCP over stdio as newline-delimited JSON-RPC 2.0: `initialize` (with a pinned protocol
revision and `capabilities.tools`), `ping`, `tools/list`, `tools/call` and `notifications/initialized`. An unknown method
SHALL answer error -32601 and malformed input -32700 or -32600; only protocol messages SHALL go to stdout. It SHALL add no
runtime dependency to the harness.

#### Scenario: SCN-MCP-01 (+) A client connects and lists the tools
- **GIVEN** `l4 mcp serve` started by an MCP client in a repository
- **WHEN** the client sends `initialize`, then `notifications/initialized`, then `tools/list`
- **THEN** the server answers with its name `l4`, its version and the tools capability, and lists every tool with a
  description and an input schema

#### Scenario: SCN-MCP-02 (−) A malformed request gets a protocol error
- **GIVEN** the running server
- **WHEN** a line that is not JSON, or a call of an unknown method, arrives
- **THEN** it answers -32700 or -32601 and keeps serving

### Requirement: L4-MCP-002 Every tool runs the l4 command it names, as an agent
Each tool SHALL run the `l4` command it names as a subprocess in the repository, with the caller's environment plus
`AI_AGENT=l4-mcp` and no terminal on stdin, so that every rule the CLI applies to an agent caller holds. The server SHALL
make no write of its own. A result SHALL carry the exit code, the redacted output cut at 64 KiB with the cut said, the
parsed JSON when the command printed JSON, and `isError` for a non-zero exit.

#### Scenario: SCN-MCP-03 (+) A read tool returns the command's output
- **GIVEN** a repository with a delivery plan `p`
- **WHEN** a client calls `l4_plan_status` with `plan: p`
- **THEN** the server runs `l4 yolo status p` with `AI_AGENT=l4-mcp` and returns its output and exit code

#### Scenario: SCN-MCP-04 (−) An agent rule still refuses through the server
- **GIVEN** a repository whose base config does not set `clarifier.answer_by_agents`, and an open verdict question
- **WHEN** a client calls `l4_question_answer` for it
- **THEN** the CLI refuses it as for any agent, and the tool returns that refusal with `isError: true`

### Requirement: L4-MCP-003 The tools manage plans and debug units
The server SHALL offer the read tools `l4_status`, `l4_doctor`, `l4_plan_status`, `l4_plan_check` (with `worktree`),
`l4_plan_findings`, `l4_plan_report`, `l4_questions`, `l4_question`, `l4_unit_events` and `l4_verification`, and the
write tools `l4_plan_draft`, `l4_plan_review` (with `worktree`), `l4_question_answer`, `l4_retry` and `l4_plan_resume`.
A write tool's description SHALL say what it writes, whether it pushes to origin, and that CI may be running;
`l4_plan_review`'s SHALL say that it costs judge tokens and takes minutes. It SHALL NOT offer `l4 yolo activate`,
`l4 yolo cancel`, `l4 run`, or anything that starts an agent CLI; the descriptions SHALL name the command a person runs.

#### Scenario: SCN-MCP-05 (+) A plan is checked before the push through the server
- **GIVEN** a working tree with a new plan file `multitenancy` and its specs, not pushed
- **WHEN** a client calls `l4_plan_check` with `plan: multitenancy, worktree: true`
- **THEN** the server runs `l4 yolo check multitenancy --worktree` and returns its findings and order

#### Scenario: SCN-MCP-06 (+) A stopped unit is debugged through the server
- **GIVEN** a unit that halted on a task
- **WHEN** a client calls `l4_status` with the unit, then `l4_unit_events` with `type: task.attempt_failed`
- **THEN** it gets the unit's cause and next step, and the failed attempts with their reasons

#### Scenario: SCN-MCP-07 (−) Activation is not a tool
- **GIVEN** the running server
- **WHEN** a client lists the tools
- **THEN** no tool runs `l4 yolo activate` or `l4 yolo cancel`, and `l4_plan_status`'s description names
  `l4 yolo activate <plan> --reason "…"` as a person's command

### Requirement: L4-MCP-004 l4 mcp install configures a client in one command
`l4 mcp install --client <name> [--project] [--dry-run]` SHALL write the client's documented MCP configuration with the
server command `l4 mcp serve`, merging into an existing file and keeping every other server, atomically; it SHALL refuse a
file it cannot parse and print what it wrote. Only clients whose configuration path and format were checked against the
vendor's documentation SHALL be offered.

#### Scenario: SCN-MCP-08 (+) A client is configured and other servers stay
- **GIVEN** a client configuration file that already lists another MCP server
- **WHEN** `l4 mcp install --client <that client> --project` runs
- **THEN** the file lists `l4` with the command `l4 mcp serve` and still lists the other server

#### Scenario: SCN-MCP-09 (−) An unparseable configuration is not overwritten
- **GIVEN** a client configuration file that is not valid JSON (or TOML)
- **WHEN** `l4 mcp install` runs for it
- **THEN** it exits 2 naming the file and writes nothing
