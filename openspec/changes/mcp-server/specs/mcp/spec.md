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

### Requirement: L4-MCP-005 An instance serves the repositories it was started for
`l4 mcp serve` SHALL take `--repo PATH`, repeatable. Each PATH SHALL be resolved to the root of a git repository that has
`.l4/config.yaml`, else the server SHALL exit 2 before it serves. With one `--repo`, every tool SHALL run in that
repository and a tool's `repo` argument, when given, SHALL name it (its name or its path), else the call is refused. With
several, every tool SHALL take a required `repo` argument that names one of them (the folder name, or the path), and any
other value SHALL be refused, never resolved on its own. Without `--repo`, the server SHALL serve the repository of its
working directory when that is a git repository with `.l4/config.yaml`, and SHALL otherwise answer every tool call with
an error that names `--repo`. Every tool result SHALL name the repository it ran in. A tool SHALL NOT run in a
repository the server was not started for.

#### Scenario: SCN-MCP-10 (+) Two IDE entries serve two repositories
- **GIVEN** two servers configured as `l4 mcp serve --repo /work/mint-mory` and `l4 mcp serve --repo /work/mintkey`
- **WHEN** a client calls `l4_status` on each
- **THEN** each runs in its own repository and its result names that repository

#### Scenario: SCN-MCP-11 (−) A repository the instance does not serve is refused
- **GIVEN** a server started with `--repo /work/mint-mory --repo /work/mintkey`
- **WHEN** a client calls `l4_plan_status` with `repo: /etc` or `repo: other`
- **THEN** the call is refused with the list of the repositories it serves, and nothing runs

#### Scenario: SCN-MCP-12 (−) No repository, no guess
- **GIVEN** a server started without `--repo` in a folder that is not a git repository with `.l4/config.yaml`
- **WHEN** a client calls any tool
- **THEN** the result is an error that says to start the server with `--repo PATH`

### Requirement: L4-MCP-002 Every tool runs the l4 command it names, as an agent
Each tool SHALL run the `l4` command it names as a subprocess in the repository, with the caller's environment plus
`AI_AGENT=l4-mcp` and no terminal on stdin, so that every rule the CLI applies to an agent caller holds. The server SHALL
make no write of its own. A result SHALL carry the exit code, the redacted output cut at 64 KiB with the cut said, the
parsed JSON when the command printed JSON, and `isError` for a non-zero exit.

#### Scenario: SCN-MCP-03 (+) A read tool returns the command's output
- **GIVEN** a repository with a delivery plan `p`
- **WHEN** a client calls `l4_plan_status` with `plan: p`
- **THEN** the server runs `l4 yolo status --json -- p` with `AI_AGENT=l4-mcp` and returns its output and exit code

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
- **THEN** the server runs `l4 yolo check --worktree -- multitenancy` and returns its findings and order

#### Scenario: SCN-MCP-06 (+) A stopped unit is debugged through the server
- **GIVEN** a unit that halted on a task
- **WHEN** a client calls `l4_status` with the unit, then `l4_unit_events` with `type: task.attempt_failed`
- **THEN** it gets the unit's cause and next step, and the failed attempts with their reasons

#### Scenario: SCN-MCP-07 (−) Activation is not a tool
- **GIVEN** the running server
- **WHEN** a client lists the tools
- **THEN** no tool runs `l4 yolo activate` or `l4 yolo cancel`, and `l4_plan_status`'s description names
  `l4 yolo activate <plan> --reason "…"` as a person's command

#### Scenario: SCN-MCP-13 (+) A unit's ledger events are read, filtered and cut
- **GIVEN** a unit whose ledger holds three events of type `task.attempt_failed` and others
- **WHEN** `l4 status --unit U --events --type task.attempt_failed --last 2 --json` runs
- **THEN** it prints `l4/events@1` with the newest two of them, `total: 3` and `shown: 2`, and writes nothing

#### Scenario: SCN-MCP-14 (+) A unit's verification.md is read from its branch
- **GIVEN** a unit branch on origin that holds `verification.md`
- **WHEN** `l4 status --unit U --verification` runs
- **THEN** it prints that file; for a unit without one it says `no verification.md`

#### Scenario: SCN-MCP-15 (+) A plan that is not pushed is admitted from the working tree
- **GIVEN** a plan file and its unit folders only in the working tree
- **WHEN** `l4 yolo check <plan> --worktree` runs
- **THEN** it prints the order and exits 0, recording nothing; without `--worktree` it exits 2

### Requirement: L4-MCP-004 l4 mcp install configures a client in one command
`l4 mcp install --client <name> [--project] [--repo PATH] [--name NAME] [--dry-run]` SHALL write the client's
documented MCP configuration with the server command `l4 mcp serve --repo <the repository's absolute path>` (default: the
repository of the working directory) under the entry NAME (default `l4` for `--project`, `l4-<repository folder name>`
for the user scope, so that several repositories have one entry each), merging into an existing file and keeping every other server, atomically; it SHALL refuse a
file it cannot parse and print what it wrote. Only clients whose configuration path and format were checked against the
vendor's documentation SHALL be offered.

#### Scenario: SCN-MCP-08 (+) A client is configured and other servers stay
- **GIVEN** a client user configuration file that already lists another MCP server and an entry `l4-mint-mory`
- **WHEN** `l4 mcp install --client <that client> --repo /work/mintkey` runs
- **THEN** the file adds `l4-mintkey` with the command `l4 mcp serve --repo /work/mintkey`, and still lists the other
  server and `l4-mint-mory` unchanged

#### Scenario: SCN-MCP-09 (−) An unparseable configuration is not overwritten
- **GIVEN** a client configuration file that is not valid JSON (or TOML)
- **WHEN** `l4 mcp install` runs for it
- **THEN** it exits 2 naming the file and writes nothing
