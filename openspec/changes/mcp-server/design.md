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
`[sys.executable, "-m", "l4", ...argv]` (or the console script) in the root of a repository the instance serves (D5), with the caller's environment plus
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

### D5 Repositories (the owner: "different instances for different repos that have different location on disk")
`l4 mcp serve --repo PATH` (repeatable) fixes the repositories an instance serves; each must resolve to a git repository
root with `.l4/config.yaml` at start, else exit 2. One repository: the tools run there, and a `repo` argument may only
name it. Several: `repo` is required and must name one of them by folder name or path (a path is compared after
resolving symlinks); nothing else is ever resolved, so a tool cannot be pointed at another folder. Without `--repo`,
`$CLAUDE_PROJECT_DIR` serves when it is such a repository, else the working directory; otherwise every call answers an
error naming `--repo` (an IDE may start the server in the home folder). `l4 mcp install` writes `--repo <absolute
path>` only in a user configuration, where it names the entry `l4-<folder>` (one entry per repository); a project
file (`l4` entry) is committed, so it holds `l4 mcp serve` with no path where the client starts the server in the project (Claude Code sets
`CLAUDE_PROJECT_DIR`; VS Code, OpenCode and Codex start in the workspace), `--repo ${workspaceFolder}` for Cursor (no
documented working directory), and Kiro's project scope is refused; a worktree is served by a session started inside it. Install never replaces an entry that serves another repository (two folders can share a name: exit 2, use
`--name`), keeps the user's other keys of the entry, and for a project file refuses a symlink on the file or any folder
above it (repository content is untrusted). Not done: asking the client for its MCP roots (`roots/list`), which would
need D1's "the server sends no request" relaxed; a client that starts the server outside the workspace uses a user
entry with `--repo`. Every result names its
repository.
