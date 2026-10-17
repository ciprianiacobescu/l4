## Why

The owner: "make L4 also available as MCP to be configured in whatever IDE the user is having; primary purpose is to
manage plans and debug things", and "L4 should be stupidly easy to use by agents". Today an agent in an IDE drives L4
only by running `l4 …` in a shell and reading prose output; it must know the commands, the flags, the order of a plan's
steps (draft → check → review → findings → activate) and where the evidence of a stopped unit lives (the ledger,
`verification.md`, `questions.md`). An MCP server gives every MCP client (Claude Code, Cursor, VS Code, Kiro, Codex,
OpenCode, Windsurf …) typed tools for that, with descriptions an agent reads before it calls them.

## What Changes

- **`l4 mcp serve`** (L4-MCP-001): an MCP server over stdio, implemented in the harness with no new dependency
  (JSON-RPC 2.0, the protocol revision named in the code; `initialize`, `ping`, `tools/list`, `tools/call`,
  `notifications/initialized`). Tools only in this version.
- **Every tool runs the `l4` command it names** (L4-MCP-002) as a subprocess in the repository, with an agent marker in
  its environment (`AI_AGENT=l4-mcp`), so every guard of the CLI holds unchanged: the agent rules
  (`clarifier.answer_by_agents`, `yolo.review.accept_by_agents`), the push leases, the redaction. The server adds no
  write of its own. A tool returns the command's exit code, its output (redacted, cut at a limit with the cut said), and
  the parsed JSON where the command has `--json`.
- **The tools** (L4-MCP-003), for plans and for debugging:
  - read: `l4_status` (units, or one unit with its cause and next step), `l4_doctor`, `l4_plan_status`,
    `l4_plan_check` (with `worktree`: before the push), `l4_plan_findings`, `l4_plan_report`, `l4_questions`,
    `l4_question`, `l4_unit_events` (a unit's ledger events, filtered by type and count), `l4_verification` (a unit's
    `verification.md`, or a round's);
  - write, each description saying what it writes, that it pushes to origin where it does, and that CI may be running:
    `l4_plan_draft` (the working-tree file only), `l4_plan_review` (with `worktree`; it costs judge tokens and takes
    minutes), `l4_question_answer`, `l4_retry`, `l4_plan_resume`;
  - not offered: `l4 yolo activate` and `l4 yolo cancel` (a person's decision, L4-YOLO-005); `l4 run`; anything that
    starts an agent CLI. A tool's description names the command a person runs instead.
- **`l4 mcp install --client <name> [--project]`** (L4-MCP-004): writes the client's MCP configuration so the server is
  one command away, for each client whose configuration file is documented by its vendor (the source URL kept in the
  code); a client that cannot be verified is not offered. It merges into an existing file, keeps every other server,
  refuses a file it cannot parse, and prints what it wrote.
- Docs: a short "Use L4 from your IDE" section (README, quickstart), the skill's `operate.md`, the SPEC.

## Impact

- New: `src/l4/mcp/` (server, protocol, tools, install), `l4 mcp serve|install` in `src/l4/cli.py`, tests under
  `tests/unit/mcp/` (protocol framing, every tool's argv and env, the agent marker, truncation, install merges), an
  interop test with the official `mcp` client package in the dev group only.
- `docs/SPEC.md` (§ new, L4-MCP-001..004, scenarios, the CLI table, the change row), README, quickstart, the skill's
  `operate.md`, CHANGELOG.
