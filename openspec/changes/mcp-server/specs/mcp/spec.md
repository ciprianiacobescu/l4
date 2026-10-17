## Purpose

Any MCP client can manage L4 plans and debug L4 units through typed tools, under the same rules as the CLI.

## ADDED Requirements

### Requirement: L4-MCP-001 l4 mcp serve is an MCP server over stdio
`l4 mcp serve` SHALL speak MCP over stdio as newline-delimited JSON-RPC 2.0: `initialize`, `ping`, `tools/list`,
`tools/call` and `notifications/initialized`. It SHALL answer -32601 for an unknown method and -32700 or -32600 for
malformed input, put only protocol messages on stdout, add no runtime dependency, read and write UTF-8 under any
locale, and send a rising `progress` value.

#### Scenario: SCN-MCP-01 (+) A client connects and lists the tools
- **GIVEN** `l4 mcp serve` started by an MCP client in a repository
- **WHEN** the client sends `initialize`, then `notifications/initialized`, then `tools/list`
- **THEN** the server answers with its name `l4`, its version and the tools capability, and lists every tool with a
  description and an input schema

#### Scenario: SCN-MCP-02 (−) A malformed request gets a protocol error
- **GIVEN** the running server
- **WHEN** a line that is not JSON, or a call of an unknown method, arrives
- **THEN** it answers -32700 or -32601 and keeps serving

#### Scenario: SCN-MCP-20 (+) The protocol is UTF-8 under a non-UTF-8 locale
- **GIVEN** the server started with `LC_ALL=C` and Python's UTF-8 mode off
- **WHEN** a client sends `initialize` and `tools/list`
- **THEN** both are answered, as UTF-8, with the `…` of a description intact, and the server does not die

#### Scenario: SCN-MCP-22 (+) Progress rises with every notification
- **GIVEN** a call that carries a progress token and runs long enough for several notifications
- **WHEN** the server sends them
- **THEN** each `progress` value is greater than the one before

### Requirement: L4-MCP-005 An instance serves the repositories it was started for
`l4 mcp serve` SHALL take `--repo PATH`, repeatable, each the root of a git repository with `.l4/config.yaml`, else exit
2 before serving. A tool SHALL run only in a served repository: `repo` is optional with one, required with several, and
any other value is refused. Without `--repo` the working directory serves when it qualifies, else every call errors,
naming `--repo`. Results and `initialize` SHALL name the repositories.

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

#### Scenario: SCN-MCP-25 (+) Instances for different repositories can be told apart
- **GIVEN** two servers, one per repository
- **WHEN** a client reads each `initialize` result and `tools/list`
- **THEN** `serverInfo.title`, `instructions` and every tool description name that server's repositories and no other

### Requirement: L4-MCP-002 Every tool runs the l4 command it names, as an agent
Each tool SHALL run the `l4` command it names as a subprocess in the repository, with the caller's environment plus
`AI_AGENT=l4-mcp` and no terminal on stdin, so that every CLI rule for agents holds. The server SHALL make no write of
its own. A result SHALL carry the exit code, the redacted output cut at 64 KiB, the parsed JSON, and `isError`. A
timeout or cancel SHALL stop the whole process group.

#### Scenario: SCN-MCP-03 (+) A read tool returns the command's output
- **GIVEN** a repository with a delivery plan `p`
- **WHEN** a client calls `l4_plan_status` with `plan: p`
- **THEN** the server runs `l4 yolo status --json -- p` with `AI_AGENT=l4-mcp` and returns its output and exit code

#### Scenario: SCN-MCP-04 (−) An agent rule still refuses through the server
- **GIVEN** a repository whose base config does not set `clarifier.answer_by_agents`, and an open verdict question
- **WHEN** a client calls `l4_question_answer` for it
- **THEN** the CLI refuses it as for any agent, and the tool returns that refusal with `isError: true`

#### Scenario: SCN-MCP-19 (−) A stopped call leaves no descendant running
- **GIVEN** a command whose descendant ignores SIGTERM
- **WHEN** the call times out or is cancelled
- **THEN** after the grace period the whole process group is killed, also when the command itself already exited

### Requirement: L4-MCP-003 The tools manage plans and debug units
The server SHALL offer the read tools `l4_status`, `l4_doctor`, `l4_plan_status`, `l4_plan_check`, `l4_plan_findings`,
`l4_plan_report`, `l4_questions`, `l4_question`, `l4_unit_events`, `l4_verification` and the write tools `l4_plan_draft`,
`l4_plan_review`, `l4_question_answer`, `l4_retry`, `l4_plan_resume`. It SHALL NOT offer `l4 yolo activate`,
`l4 yolo cancel` or `l4 run`. A `number` argument SHALL be finite.

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

#### Scenario: SCN-MCP-15 (+) A plan that is not pushed is refused without `worktree` and admitted with it
- **GIVEN** a plan file and its unit folders only in the working tree (the command is L4-YOLO-034's)
- **WHEN** a client calls `l4_plan_check` for it without `worktree`, then with `worktree: true`
- **THEN** the first result is an error because origin has no such file; the second prints the order and exits 0,
  recording nothing

#### Scenario: SCN-MCP-21 (+) A write tool says what it writes
- **GIVEN** the tool list
- **WHEN** a client reads the description of a write tool
- **THEN** it says what it writes, whether it pushes to origin and that CI may be running; `l4_plan_review`'s also says
  that it costs judge tokens and takes minutes

#### Scenario: SCN-MCP-23 (−) A number that is not finite is refused
- **GIVEN** the running server
- **WHEN** a client calls `l4_plan_resume` with `extend_cost` NaN or infinity
- **THEN** the call is an error and nothing runs; `l4 yolo resume --extend-cost=nan` itself exits 2

### Requirement: L4-MCP-004 l4 mcp install configures a client in one command
`l4 mcp install --client <name> [--project] [--repo PATH] [--name NAME] [--dry-run]` SHALL write the client's
documented MCP configuration with the server command, one entry per repository, merging into an existing file,
keeping other servers and the user's keys, atomically. It SHALL refuse what it cannot parse, an entry that serves
another repository and a symlink, writing nothing. Only clients checked against the vendor's documentation SHALL be
offered.

#### Scenario: SCN-MCP-08 (+) A client is configured and other servers stay
- **GIVEN** a client user configuration file that already lists another MCP server and an entry `l4-mint-mory`
- **WHEN** `l4 mcp install --client <that client> --repo /work/mintkey` runs
- **THEN** the file adds `l4-mintkey` with the command `l4 mcp serve --repo /work/mintkey`, and still lists the other
  server and `l4-mint-mory` unchanged

#### Scenario: SCN-MCP-09 (−) An unparseable configuration is not overwritten
- **GIVEN** a client configuration file that is not valid JSON (or TOML)
- **WHEN** `l4 mcp install` runs for it
- **THEN** it exits 2 naming the file and writes nothing

#### Scenario: SCN-MCP-16 (+) A committed project file serves each worktree
- **GIVEN** `l4 mcp install --client claude-code --project` committed its `.mcp.json`, and a git worktree of the repository
- **WHEN** the server starts with that file's arguments in the worktree and a tool is called
- **THEN** the file holds no absolute path and the result names the worktree

#### Scenario: SCN-MCP-17 (−) An entry of another repository is not replaced
- **GIVEN** the entry `l4-app` serves `/work/app`
- **WHEN** `l4 mcp install --repo /oss/app` runs
- **THEN** it exits 2 naming both paths and `--name`, and writes nothing

#### Scenario: SCN-MCP-18 (−) A symlink in the repository is not followed
- **GIVEN** a repository that commits `.mcp.json` as a symlink to a file outside it
- **WHEN** `l4 mcp install --client claude-code --project` runs
- **THEN** it exits 2 and the file outside is unchanged

#### Scenario: SCN-MCP-24 (+) The printed Claude Code command is shell-quoted
- **GIVEN** a repository whose path holds a space or a quote
- **WHEN** `l4 mcp install --client claude-code` prints its `claude mcp add` line
- **THEN** the line, split as a shell splits it, gives the exact `l4 mcp serve --repo <path>` arguments
