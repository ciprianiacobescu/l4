## Decisions

### D1 Own stdio server, no SDK
The harness keeps its dependencies lean (click, httpx, pydantic, pynacl, pyyaml). A tools-only stdio server is a small,
stable part of MCP: newline-delimited JSON-RPC 2.0 messages on stdin/stdout; `initialize` answers the pinned protocol
revision (accept the client's revision when it is one the server knows, else answer its own), `capabilities: {tools:
{}}`, `serverInfo {name: l4, version}`; `tools/list` returns each tool's `name`, `description`, `inputSchema` (JSON
Schema from a pydantic model); `tools/call` returns `content: [{type: text, text}]`, `structuredContent` when the
command gave JSON, and `isError: true` for a non-zero exit. Unknown methods are JSON-RPC error -32601, malformed input
-32700/-32600. Nothing but protocol messages goes to stdout; logs go to stderr. An interop test drives the server with the
official `mcp` client (dev dependency only).

### D2 Every tool is a subprocess of the CLI
`[sys.executable, "-m", "l4", ...argv]` (or the console script) in the repository root (the server's working directory,
or the tool's `repo` argument, which must be a directory inside a git repository), with the caller's environment plus
`AI_AGENT=l4-mcp`, stdin closed (so `actor()` sees an agent), a timeout per tool, and the output redacted again and cut
at 64 KiB with a line that says so. The server never imports and calls command functions directly: the CLI is the one
place where policy lives, and a subprocess keeps the server stateless.

### D3 The tool set
Read tools have no side effect beyond a fetch the command itself does. Write tools take every value as an explicit
argument (no defaults that write), name the command in their description, and say whether they push. Activation,
cancel, `l4 run` and agent CLIs are left out: the descriptions of `l4_plan_status` and `l4_plan_check` say which command
a person runs next. `l4_unit_events` reads the ledger the CLI reads (`l4 status --unit U --json` where it exists, or a new
read-only `l4 ledger --unit U [--type T] [--last N] --json` if needed — the implementer adds the smallest read-only
command that gives it).

### D4 Install
`l4 mcp install --client X [--project]` writes the documented configuration of X (for example Claude Code's `.mcp.json`
/ `claude mcp add`, Cursor's `.cursor/mcp.json` / `~/.cursor/mcp.json`, VS Code's `.vscode/mcp.json` (`servers`), Kiro's
`.kiro/settings/mcp.json` / `~/.kiro/settings/mcp.json`, Codex's `~/.codex/config.toml` `[mcp_servers.l4]`, OpenCode's
`opencode.json` `mcp`) with the command `l4 mcp serve`. Each path and shape is checked against the vendor's documentation
during implementation and its URL kept in a comment; one that cannot be checked is left out. The write merges, keeps
other servers, is atomic, refuses an unparseable file, and with `--dry-run` prints the result.

## Risks
- An IDE agent calls write tools without reading the runbook: the descriptions carry the warnings, and the CLI's agent
  rules still decide (an agent cannot answer a verdict without `answer_by_agents`, etc.).
- The protocol evolves: the pinned revision and the interop test show a mismatch before a release.
