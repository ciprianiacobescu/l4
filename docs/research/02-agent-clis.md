# 02 — Coding-agent CLIs for the Implementer/Verifier abstract factory

Research date: 2026-10-03. Author: research subagent. Scope: non-interactive invocation, structured output, resume, permissions, MCP, model, exit codes, CI gotchas, worktrees, ACP, and (added scope) availability / quota / cooldown detection.

## Labels and method

- **[V]** verified from a primary source: the CLI binary's own `--help` or behaviour run locally at the stated version, the project's source at the release tag, or the vendor's official docs (URL cited).
- **[D]** secondary source (third-party blog/README), URL cited.
- **[I]** inferred from verified facts; not directly observed.
- **[U]** unverified; do not build on it without checking.

Local verification was done in a scratch git repo with these binaries (installed into the scratchpad, not globally):

| Tool | Version verified | How | Release date (GitHub/npm) |
|---|---|---|---|
| Claude Code | 2.1.288 | local `claude --help` + live `-p` runs | n/a (installed) |
| OpenAI Codex CLI | 0.160.0 (`@openai/codex`) | local `--help`, live `exec` runs, source at tag `rust-v0.160.0` | 2026-10-01 |
| OpenCode | 1.18.33 local; 1.18.34 latest | local `--help`, live `run` + `acp` runs, source at tag `v1.18.34` (repo moved `sst/opencode` -> `anomalyco/opencode`) | 2026-09-30 |
| Gemini CLI | 0.62.0 | local `--help`, unauthenticated runs, docs/source at tag `v0.62.0` | 2026-09-29 |
| GitHub Copilot CLI | 1.0.91 (`@github/copilot`) | local `--help`, unauthenticated runs, `--acp` probe | 2026-10-01 |
| Goose | 1.53.0 (repo moved `block/goose` -> `aaif-goose/goose`) | docs + source at tag (not run) | 2026-10-02 |
| Kiro CLI | not installed | kiro.dev docs only | n/a |
| Cursor CLI (`agent`) | not installed | cursor.com docs only | n/a |
| Aider | 0.86.0 | source `aider/args.py` at tag (not run) | 2025-08-09 (no release in ~14 months) |
| ACP schema | v1 1.24.1 stable; v2 2.0.0-alpha.7 | repo `agentclientprotocol/agent-client-protocol` at HEAD 2026-10-03 | 2026-09-30 |
| claude-agent-acp | 0.85.1 | npm install + live ACP probe | 2026-10-02 |
| codex-acp | 0.16.0 | npm install + ACP `initialize` probe | 2026-06-08 |

Source URLs for the version rows: GitHub releases API `https://api.github.com/repos/<owner>/<repo>/releases/latest` and `npm view <pkg> version` [V].

---

## 1. Claude Code (`claude -p`, Agent SDK)

Primary docs: https://code.claude.com/docs/en/headless, https://code.claude.com/docs/en/cli-reference, https://code.claude.com/docs/en/agent-sdk/typescript, https://code.claude.com/docs/en/authentication.

**Invocation.** `claude -p "<prompt>"` [V help]. The prompt can also come from stdin (`cat x | claude -p "instr"`), and piped stdin is capped at 10 MB [V headless doc]. There is no prompt-file flag. Use stdin or `$(cat file)`, and use `--append-system-prompt-file` / `--system-prompt-file` for long instructions [V cli-reference].

**Structured output.**
- `--output-format json` returns a single result object. `stream-json` returns NDJSON whose last line is the `result` message; `stream-json` needs `--verbose` [V headless doc].
- I verified the fields of a result object locally on 2.1.288: `type:"result"`, `subtype` (`success` | `error_max_turns` | `error_during_execution` | `error_max_budget_usd` | `error_max_structured_output_retries`), `is_error`, `result` (text), `structured_output`, `session_id`, `total_cost_usd`, `usage{input_tokens,output_tokens,cache_*}`, `modelUsage{<model>:{costUSD,inputTokens,…}}`, `num_turns`, `terminal_reason`, `stop_reason`, `permission_denials`, `errors[]`, `api_error_status`, `duration_ms` [V].
- On `error_max_turns`, `result` was `null` (not a string, despite the TS type in the SDK doc) and the reason was in `errors: ["Reached maximum number of turns (1)"]` [V observed]. **Adapter must not assume `result` is a string.**
- `--json-schema '<schema>'` (print mode only) validates the final answer and puts it in `.structured_output` [V headless doc + live run]. An invalid schema now hard-errors (v2.1.205+) [V doc].
- The structured output is produced via a tool call, so it consumes a turn: a trivial schema run reported `num_turns: 2` [V observed]. Size `--max-turns` with that extra turn in mind [I].

**Session / resume.**
- `--session-id <uuid>` presets the ID [V help]. That lets the harness know the ID before launch, so it can resume after a crash even if no output was captured [I].
- `--resume <id|name|/abs/path/to/transcript.jsonl>`, `--continue`, and `--fork-session` exist [V cli-reference]. Resume by ID searches every project on the machine (v2.1.223+) [V].
- Resuming from an absolute `.jsonl` path makes cross-runner restart possible: save the transcript as a CI artifact, restore it, then `--resume /path/x.jsonl` [V doc; I for the CI pattern]. `CLAUDE_CONFIG_DIR` relocates all state [V auth doc].
- `--no-session-persistence` disables resume [V].
- SIGTERM exits with code 143 and records no result for the in-flight turn. Send SIGINT instead to end the turn cleanly. `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=1` continues an interrupted turn on resume [V headless doc].

**Permissions (CI).**
- `--permission-mode` choices are `acceptEdits | auto | bypassPermissions | manual(default) | dontAsk | plan` [V help].
- `dontAsk` denies anything not pre-allowed. That makes it the deterministic choice for locked-down CI combined with `--allowedTools "Bash(git *) Read Edit …"` [V headless doc].
- `--dangerously-skip-permissions` is equivalent to `bypassPermissions` [V].
- `--permission-prompts none` (v2.1.259+) denies anything that would prompt and tells the model not to retry [V].
- Gotcha: with no mode set, a `-p` run starts in the built-in default, "which can be `auto`" (classifier-based). **Always pass the mode explicitly** [V headless doc].
- `--restricted` is a hardened eval mode [V].

**MCP.** `--mcp-config <file|json…>` plus `--strict-mcp-config` ignores all other MCP sources [V].
- With `-p`, it waits up to `MCP_TIMEOUT` (30 s default) for servers to connect [V].
- Invalid `--mcp-config` entries are skipped silently, and the run exits 0. Check `system/init.mcp_server_errors` / `mcp_servers[].status` in stream-json to fail CI [V headless doc].
- `--bare` skips auto-discovery of hooks, plugins, CLAUDE.md, `.mcp.json` and keychain. It is recommended for CI and "will become the default for `-p`" [V]. Bare mode authenticates **only** with `ANTHROPIC_API_KEY`/`apiKeyHelper`, not with `CLAUDE_CODE_OAUTH_TOKEN` [V auth doc].
- Without `--bare`, `-p` runs the repo's `.claude/settings.json` hooks and `.mcp.json` servers with **no trust prompt** [V headless doc]. This is a security issue for untrusted PR code [I].

**Model.** `--model <alias|full-id>` and `--fallback-model a,b` [V]. Effort is set with `--effort` [V].

**Limits.**
- `--max-turns N` (print only; exits with an error at the limit) [V cli-reference; verified exit 1 + `subtype:error_max_turns`]. Note that `--max-turns` is **absent from `claude --help`**. The docs say help is not exhaustive [V].
- `--max-budget-usd` [V].
- There is no wall-clock timeout flag. Use an external timeout plus SIGINT [V by absence in help/docs; I].

**Exit codes.** 0 on success, non-zero on failure. Max-turns gives 1 [V observed], SIGTERM gives 143 [V]. Failures inside the run (for example missing auth) are printed **as the result on stdout** [V headless doc].

**Worktree.** `-w/--worktree [name]` creates `<repo>/.claude/worktrees/<name>`, or one branched from a PR/MR [V]. The Agent SDK has `projectConfigRoot` so that a `cwd` worktree reads project config from the trusted checkout [V SDK doc].

**Auth in CI.**
- Precedence: Bedrock/Vertex/Foundry (`CLAUDE_CODE_USE_*`) > `ANTHROPIC_AUTH_TOKEN` (bearer, for gateways) > `ANTHROPIC_API_KEY` > `apiKeyHelper` > `CLAUDE_CODE_OAUTH_TOKEN` (1-year token from `claude setup-token`, subscription) > profiles/WIF > `/login` [V auth doc].
- `ANTHROPIC_BASE_URL` routes to any gateway exposing the Anthropic format. Anthropic does not support non-Claude models through gateways [V llm-gateway doc]. OpenRouter compatibility therefore depends on the gateway exposing the Anthropic Messages format [I].

**CI integrations.**
- `anthropics/claude-code-action@v1`. Inputs include `prompt`, `claude_args`, `settings`, `anthropic_api_key`, `claude_code_oauth_token`, WIF inputs, `use_bedrock/vertex/foundry`, and `path_to_claude_code_executable`. Outputs include `conclusion`, `execution_file`, `branch_name`, `structured_output` (when `--json-schema` is in `claude_args`), and `session_id` [V action.yml on main].
- GitLab CI/CD is **beta and maintained by GitLab**. Its sample job uses `claude -p … --permission-mode acceptEdits --allowedTools "…"` [V https://code.claude.com/docs/en/gitlab-ci-cd].

## 2. OpenAI Codex CLI (`codex exec`)

Primary docs: https://learn.chatgpt.com/docs/non-interactive-mode (redirect target of developers.openai.com/codex/noninteractive), https://learn.chatgpt.com/docs/extend/mcp?surface=cli. Source: `openai/codex@rust-v0.160.0`.

**Invocation.** `codex exec [OPTIONS] [PROMPT]`. The prompt can be passed as an argument, as `-` (read stdin), or as an argument plus piped stdin (appended as a `<stdin>` block) [V help]. There is no prompt-file flag; use `codex exec - < file` [V]. Progress goes to stderr; only the final message goes to stdout [V doc].

**Gotcha.** When stdin is not a TTY, exec prints `Reading additional input from stdin...` and reads it [V observed]. Run it with `</dev/null` in CI to avoid blocking on an open pipe [I].

**Structured output.**
- `--json` prints JSONL `ThreadEvent`s: `thread.started{thread_id}`, `turn.started`, `turn.completed{usage{input_tokens,cached_input_tokens,cache_write_input_tokens,output_tokens,reasoning_output_tokens}}`, `turn.failed{error{message}}`, `item.started/updated/completed{item{id,type,…}}`, `error{message}` [V source `exec/src/exec_events.rs` + live run].
- Item types are `agent_message{text}`, `reasoning`, `command_execution{command,aggregated_output,exit_code,status}`, `file_change`, `mcp_tool_call`, `collab_tool_call`, `web_search`, `todo_list`, and `error` [V source].
- The final text is the last `agent_message` item, or the file written by `-o/--output-last-message <file>` [V].
- **There is no cost in USD, only tokens** [V].
- `--output-schema <file.json>` makes the final `agent_message.text` a JSON string matching the schema [V help + source comment "a JSON string when structured output is requested"].

**Resume.**
- `codex exec resume <SESSION_ID|thread-name> [PROMPT]` or `--last`; `--all` disables the cwd filter [V help]. `codex exec fork` also exists [V].
- The thread/session ID is `thread.started.thread_id` [V].
- Gotcha: `exec resume` does **not** accept `-s/--sandbox`, `-C`, or `--add-dir`. Use `-c sandbox_mode="workspace-write"` and run from the original cwd [V help; I for the `sandbox_mode` key, which parses under `--strict-config`].
- Sessions persist under `$CODEX_HOME` (default `~/.codex`). `--ephemeral` disables persistence, and therefore resume [V].

**Permissions.**
- The exec default is a **read-only sandbox** [V doc], and the approval policy is hard-wired to `never` in headless mode [V source `lib.rs`: `approval_policy: Some(AskForApproval::Never)`].
- Use `-s workspace-write` to allow edits, or `--dangerously-bypass-approvals-and-sandbox` for an externally sandboxed runner [V].
- **`--full-auto` is removed in 0.160.0** (`error: unexpected argument '--full-auto'`) [V observed]. The docs still say it "prints a warning" [V doc]. Docs and binary disagree; trust the binary.
- `-a/--ask-for-approval` exists only on the top-level interactive command, not `exec` [V help].
- `--approve-for-me` routes approvals to an automatic reviewer [V help]. `--ignore-user-config` and `--ignore-rules` give hermetic CI runs [V].

**MCP.** `[mcp_servers.<name>]` tables in `config.toml`:
- stdio servers use `command`, `args`, `env`, `env_vars`, `cwd`. HTTP servers use `url`, `bearer_token_env_var`, `http_headers`.
- Shared options: `startup_timeout_sec` (10), `tool_timeout_sec` (60), `enabled`, `required`, `enabled_tools`/`disabled_tools`, `default_tools_approval_mode` [V MCP doc].
- Inline override is possible via `-c mcp_servers.serena.command="…"` [I from the `-c` dotted-path semantics].
- `required = true` makes exec **exit 1** if the server fails to start [V source test `mcp_required_exit.rs`].

**Model.** `-m/--model`, `-p/--profile` (layers `$CODEX_HOME/<name>.config.toml`), `--oss`/`--local-provider` [V help].

**Limits.** There is **no max-turns and no timeout flag** [V by absence in help].

**Exit codes.** Exit 1 when a non-retried error notification arrives or the turn completes `Failed`/`Interrupted` [V source `lib.rs` `error_seen`]. Also exit 1 on a server error (test `server_error_exit.rs`) [V], on a required MCP failure [V], and on auth failure (observed: retried "Reconnecting… 5/5", then `turn.failed`, exit 1) [V].

**Worktree.** `--worktree` runs the session in a new managed Git worktree. The `worktrees` feature is `stable true` in 0.160.0 [V `codex features list`]. It is **not supported with `exec resume`** or `--ephemeral` [V source]. So a resumable run should bring its own worktree [I].

**Auth in CI.**
- `CODEX_API_KEY=<key> codex exec …` is the recommended inline form. The docs warn never to set `OPENAI_API_KEY` job-wide in workflows that check out code [V doc; source test `exec_uses_codex_api_key_env_var`].
- `codex login --with-api-key` reads stdin; `--with-access-token` also exists [V help].
- ChatGPT-plan auth means persisting `~/.codex/auth.json` [V doc].

**CI integration.** `openai/codex-action` (latest tag v1.12) [V tags API].
- Inputs include `prompt`/`prompt-file`, `output-file`, `codex-args`, `model`, `effort`, `sandbox`/`permission-profile`, `output-schema`/`-file`, `safety-strategy` (`drop-sudo` default | `unprivileged-user` | `read-only` | `unsafe`), and `codex-home`. The output is `final-message`. Windows requires `safety-strategy: unsafe` [V README via WebFetch, https://github.com/openai/codex-action].

## 3. OpenCode (`opencode run`, `serve`, `acp`)

Primary: local `opencode run --help` (1.18.33), source `anomalyco/opencode@v1.18.34`, https://opencode.ai/docs/cli/, /permissions/, /mcp-servers/, /server/, /sdk/, /agents/, /github/, /gitlab/.

**Invocation.**
- `opencode run [message..]` [V]. Other flags: `-f/--file` attaches files, `--command` runs a slash command, `--dir`, `--agent`, `-m provider/model`, `--variant` (reasoning effort), `--title`, `--share` [V help].
- Piped stdin is read [V source run.ts].
- `--attach http://host:4096` runs against a long-lived `opencode serve` [V].
- `--pure` disables external plugins, which is useful for CI determinism [V].

**Structured output (CLI).** `--format json` prints NDJSON events `{type, timestamp, sessionID, part}` [V source `emit()`; live run].
- `type` is one of `step_start`, `text`, `reasoning`, `tool_use`, `step_finish`, `error`.
- `step_finish.part` carries `cost` (USD) and `tokens{total,input,output,reasoning,cache{read,write}}` plus `reason` (`stop` | `tool-calls` …) [V observed].
- There is **no terminal "result" event**. The final text is the concatenation of `text` parts, and cost is the sum of `step_finish.cost` [V observed].
- The session ID looks like `ses_…` [V].

**Structured output (schema).**
- **Not exposed on the CLI.** The SDK/HTTP `session.prompt` accepts `format: {type:"json_schema", schema, retryCount}`. It injects a `StructuredOutput` tool with `toolChoice: required` and stores the result on the message; failure raises `StructuredOutputError` [V source `session/prompt.ts`].
- The docs say the result is at `result.data.info.structured_output` [V https://opencode.ai/docs/sdk/]. The 1.18.34 source assigns `message.structured` [V]. The field name is uncertain, so test it before relying on it [U].

**Resume.** `-s/--session <id>`, `-c/--continue`, `--fork` [V help]. Sessions live in a local SQLite DB. `opencode export <id>` / `opencode import <file>` move sessions between runners [V help].

**Permissions.**
- `opencode.json` has a `permission` map (`allow | ask | deny`, with per-pattern rules) for `read, edit, glob, grep, bash, task, skill, lsp, question, webfetch, websearch, external_directory, doom_loop` [V doc]. Most keys default to `allow`; `doom_loop` and `external_directory` default to `ask` [V doc].
- In non-interactive `run`, **any `ask` is auto-rejected**, unless `--auto` (also hidden `--yolo` / `--dangerously-skip-permissions`) is passed. In that case non-denied requests are approved [V source + observed].
- `question` and `plan_*` are always denied in `run` [V source].
- `OPENCODE_PERMISSION` (inline JSON) and `OPENCODE_CONFIG_CONTENT` inject config without files [V doc].

**MCP.** `"mcp": {"serena": {"type":"local","command":[…],"environment":{…},"timeout":5000}, "pw": {"type":"remote","url":…,"headers":{…}}}`. Tools can be disabled per agent with globs [V doc].

**Model.** `-m provider/model` and `--variant` [V].

**Limits.** No CLI max-turns flag. Use agent config `"steps": N`; at the limit the agent is forced to summarise [V agents doc]. No timeout flag [V help].

**Exit codes.** `process.exitCode = 1` on a `session.error` or command error [V source]. **Gotcha (observed):** a run that stopped because a permission was auto-rejected **exited 0**, with the last `step_finish.reason == "tool-calls"` and no answer [V]. The adapter must treat a last reason other than `stop` as failure.

**Server/SDK.**
- `opencode serve` provides the HTTP API: `POST /session`, `POST /session/:id/message`, `/prompt_async`, `/abort`, SSE `GET /event`, OpenAPI at `/doc`, basic auth via `OPENCODE_SERVER_PASSWORD` [V doc].
- The SDKs are `@opencode-ai/sdk` (`createOpencode`, `createOpencodeClient`) [V doc].

**CI integrations.**
- GitHub: `anomalyco/opencode/github@latest` (inputs `model`, `agent`, `share`, `prompt`, `use_github_token`, `mentions`, `variant`; needs `id-token: write`) [V doc]; `opencode github install|run` [V help].
- GitLab: a community component `nagyv/gitlab-opencode` [V doc page; it is third-party].

**Worktree.** No native flag [V by absence in help]. Pass `--dir <worktree>` [V].

## 4. Kiro CLI (`kiro-cli`)

Primary: https://kiro.dev/docs/cli/headless/, https://kiro.dev/docs/reference/cli-commands/, https://kiro.dev/docs/cli/acp/, kiro.dev exit-codes page (via search snippet). Not installed locally, so every item is docs-level at best.

- **Invoke:** `kiro-cli chat --no-interactive "<prompt>"`, or with stdin (`printf … | kiro-cli chat --no-interactive`). A non-empty instruction is required, and there is no mid-session input [V doc].
- **Permissions:** `--trust-all-tools` or `--trust-tools=read,grep` [V doc].
- **Agent/model:** `--agent <name>`, `--model <id>`, `--effort <level>` [V doc].
- **Output:** `--output-format stream-json` gives JSONL run events, but "requires V2 or V3 (`--agent-engine v2|v3`)" [V doc]. Event names and fields are **not documented** [U]. No JSON-schema output is documented [U].
- **Resume:** `--resume` (latest in this dir), `--resume-id <UUID>`, `--list-sessions`, `--delete-session` [V doc]. Whether these combine with `--no-interactive` is not documented [U]. Sessions are stored in `~/.kiro/` [V doc].
- **MCP:** `.kiro/settings/mcp.json` (workspace), `~/.kiro/settings/mcp.json` (user), or `mcpServers` in agent config [V doc]. `--require-mcp-startup` exits **3** if any server fails or doesn't report within 30 s [V doc].
- **Exit codes:** 0 success, 1 general failure (auth, args, operation), 3 MCP startup failure [V exit-codes page per search snippet; D-level confidence].
- **Auth (CI):** `KIRO_API_KEY` env var. API keys are only for Pro/Pro+/Pro Max/Power plans and may need admin enablement [V doc]. `kiro-cli whoami` shows auth status [V cli-commands doc].
- **ACP:** `kiro-cli acp [--agent x]`. It supports `session/load`; `session/set_model` is CLI-v2 only; extensions are under `_kiro.dev/` [V doc].
- **Worktree:** none documented [U].

## 5. Gemini CLI (`gemini -p`)

Primary: local `gemini --help` 0.62.0; docs at tag (`docs/cli/headless.md`, `session-management.md`, `trusted-folders.md`, `git-worktrees.md`, `reference/configuration.md`); `packages/core/src/output/types.ts`.

- **Invoke:** `gemini -p "<prompt>"` (appended to stdin if piped). A non-TTY also triggers headless mode [V].
- **Output:**
  - `-o json` gives `{session_id, response, stats, error{type,message,code}, warnings}` [V source types].
  - `-o stream-json` gives `init{session_id,model}`, `message`, `tool_use`, `tool_result`, `error`, and `result{status, stats{total_tokens,input_tokens,output_tokens,cached,duration_ms,tool_calls,models{…}}}` [V source].
  - **No USD cost and no JSON-schema option** [V by absence].
- **Resume:** `-r/--resume latest|<index>|<uuid>` [V help + doc], `--session-id <uuid>` presets the ID, and `--session-file <json>` loads a session file [V help].
- **Permissions:** `--approval-mode default|auto_edit|yolo|plan` or `-y/--yolo`. `--allowed-tools` is deprecated in favour of the Policy Engine (`--policy`) [V help]. `-s/--sandbox` is available [V].
- **CI gotcha:** an untrusted folder in headless mode throws `FatalUntrustedWorkspaceError`. Use `--skip-trust` or `GEMINI_CLI_TRUST_WORKSPACE=true` [V doc].
- **MCP:** `settings.json` `mcpServers.<name>` with `command/args/env/cwd`, `url` (SSE), `httpUrl` (streamable HTTP), `headers`, `timeout`, `trust`, `includeTools`/`excludeTools`. Avoid `_` in server aliases, because policy FQN parsing breaks [V reference/configuration.md]. `--allowed-mcp-server-names` filters servers [V help].
- **Model:** `-m`.
- **Limits:** `model.maxSessionTurns` (setting) [V].
- **Exit codes:** docs list 0, 1 (general/API), 42 (input), 53 (turn limit) [V headless.md]. **Observed: exit 41 on missing auth**, which is not in the docs list [V observed].
- **Worktree:** `-w/--worktree [name]` creates `.gemini/worktrees/<name>`. It is experimental and needs `experimental.worktrees: true` [V doc].
- **Auth:** `GEMINI_API_KEY`, `GOOGLE_API_KEY` + `GOOGLE_GENAI_USE_VERTEXAI`, or Code Assist OAuth [V doc].
- **CI action:** `google-github-actions/run-gemini-cli` v0.1.22. It runs `gemini --yolo --prompt "${PROMPT}" --output-format json`. Inputs include `gemini_api_key`, `gemini_model`, `settings`, `prompt`, `use_vertex_ai`, and WIF inputs; outputs are `summary` and `error` [V action.yml].
- **ACP:** `--acp` [V help + probe].

## 6–9. Brief: Goose, Aider, Cursor CLI, Copilot CLI

**Goose 1.53.0** (repo now `aaif-goose/goose`). Docs at tag `documentation/docs/guides/goose-cli-commands.md`.
- **Invoke:** `goose run -t "<text>"` or `-i <file|->`. Other flags: `--system`, `--recipe`, `--no-session`, `-n/--name`, `-r/--resume`, `--max-turns` (default 1000), `--max-tool-repetitions`, `--provider`, `--model`, `--with-extension "name:cmd…"` (stdio MCP), `--with-streamable-http-extension <url>`, `-q`, and `--output-format text|json|stream-json` [V doc].
- **JSON:** `json` gives `{messages[], metadata{total_tokens,input_tokens,output_tokens,cache_*,cost_usd,status}}`; `stream-json` events are `message`, `notification`, `error`, `complete{…cost_usd}` [V source `session/mod.rs`]. **No session_id in the JSON output** [V by struct], so the adapter must use `--name` to make resume addressable [I].
- **Structured output:** via a recipe `response.json_schema` [V recipe-reference].
- **Permissions:** `GOOSE_MODE=auto` [V headless tutorial].
- **ACP:** `goose acp` [V doc].
- **Exit codes:** the docs say "check exit codes", and the source has many `process::exit(1)` calls [V]. Exit-code behaviour at the max-turns limit is [U].

**Aider 0.86.0.**
- **Invoke:** `--message/-m`, `--message-file/-f`, `--yes-always`, `--auto-commits/--no-auto-commits`, `--restore-chat-history` [V args.py].
- **Gaps:** no JSON output, no MCP, no session-ID resume [V by absence in args.py]. No release since 2025-08 [V].
- **Fit:** poor for this factory [I].

**Cursor CLI** (binary is now `agent`). Docs: https://cursor.com/docs/cli/headless, /reference/parameters, /reference/output-format.
- **Flags:** `-p/--print`, `--output-format text|json|stream-json`, `--model`, `--resume [chatId]`/`--continue`, `--force`/`--yolo`, `--sandbox enabled|disabled`, `--approve-mcps`, `--trust` (headless), `--workspace`, `--worktree` (under `~/.cursor/worktrees/<repo>/<name>`), `--mode plan|ask`. `agent acp` and `agent create-chat` (returns an ID) also exist [V doc].
- **JSON:** `{type:"result", subtype, is_error, duration_ms, duration_api_ms, result, session_id, request_id}` [V doc].
- **Failure:** non-zero exit, stderr message, and **no JSON emitted** [V doc].
- **Auth:** `CURSOR_API_KEY` [V doc].

**GitHub Copilot CLI 1.0.91.**
- **Flags:** `copilot -p "<prompt>"`, `--allow-all-tools` ("required for non-interactive mode"; env `COPILOT_ALLOW_ALL`), `--allow-all`/`--yolo`, `--allow-tool`/`--deny-tool`, `--available-tools`, `--output-format text|json` (JSONL), `-s/--silent`, `--model`, `--reasoning-effort`, `-r/--resume [id]`, `--continue`, `--session-id <id>` (resume or preset), `--usage-output-file <file>` (final usage JSON), `--max-ai-credits`, `--additional-mcp-config <json|@file>` (augments `~/.copilot/mcp-config.json`), `--disable-builtin-mcps`, `--secret-env-vars`, `--no-ask-user`, `--mode autopilot|plan`, `--acp`, `--no-auto-update` [V help].
- **Auth:** `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN`. BYOK via `COPILOT_PROVIDER_BASE_URL/TYPE/API_KEY` [V `copilot help environment`].
- **Exit codes:** 1 on missing auth [V observed].
- **Worktree:** help text mentions a `--worktree` directory, but no `--worktree` option is listed [U].

---

## 10. Comparison table (CI-adapter essentials)

| CLI | Invoke + prompt input | Structured output: final text / cost / session ID | Schema output | Resume | CI-safe permissions | MCP config | Model | Exit codes | Worktree |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code 2.1.288 | `claude -p "…"`; arg or stdin | `--output-format json` → `.result` (null on max-turns), `.total_cost_usd`, `.session_id`; stream-json last line `type:result` [V] | `--json-schema` → `.structured_output` [V] | `--resume <id\|path.jsonl>`, `--session-id <uuid>` preset, `--continue`, `--fork-session` [V] | `--permission-mode dontAsk` + `--allowedTools`; or `bypassPermissions` in a sandbox; `--bare`, `--strict-mcp-config` [V] | `--mcp-config <file\|json>` + `--strict-mcp-config` [V] | `--model`, `--fallback-model` [V] | 0 ok; 1 on max-turns (verified) or failure; 143 on SIGTERM [V] | `-w/--worktree` [V] |
| Codex 0.160.0 | `codex exec "…"`; arg, `-` stdin, or arg plus stdin | `--json` JSONL: last `item.completed` `agent_message.text`; tokens in `turn.completed.usage` (no USD); `thread.started.thread_id`; `-o file` [V] | `--output-schema file` → JSON string in final message [V] | `codex exec resume <id>` / `--last` (no `-s`/`-C`: use `-c`) [V] | `-s workspace-write` (approvals forced `never`), or `--dangerously-bypass-approvals-and-sandbox`; `--full-auto` removed [V] | `config.toml [mcp_servers.x]`, `-c` overrides, `required=true` [V] | `-m`, `-p profile` [V] | 1 on failed turn, fatal error, required MCP failure, or auth [V]; no max-turns flag | `--worktree` (not with resume) [V] |
| OpenCode 1.18.x | `opencode run "…"`; arg, stdin, `-f` files | `--format json` NDJSON; sum `text` parts; `step_finish.cost`/`.tokens`; `sessionID` on every event [V] | SDK/HTTP only: `format:{type:"json_schema"}` [V src; field name U] | `-s <ses_id>`, `-c`, `--fork`; export/import [V] | `ask` auto-rejected; `--auto` approves non-denied; `permission` in config / `OPENCODE_PERMISSION` [V] | `opencode.json` `mcp{local\|remote}` or `OPENCODE_CONFIG_CONTENT` [V] | `-m provider/model`, `--variant` [V] | 1 on session error; **0 even when stopped by a permission rejection** [V] | none (use `--dir`) [V] |
| Kiro CLI | `kiro-cli chat --no-interactive "…"`; arg or stdin [V doc] | `--output-format stream-json` (v2/v3 engine) — schema undocumented [U] | none documented [U] | `--resume`, `--resume-id <uuid>` (with no-interactive [U]) | `--trust-all-tools` / `--trust-tools=…` [V doc] | `.kiro/settings/mcp.json`, agent `mcpServers`; `--require-mcp-startup` [V doc] | `--model`, `--agent` [V doc] | 0 / 1 / 3 (MCP) [V-ish] | none [U] |
| Gemini 0.62.0 | `gemini -p "…"`; arg plus stdin | `-o json` → `.response`, `.stats` (tokens only), `.session_id` [V] | none [V] | `--resume <uuid\|latest\|idx>`, `--session-id`, `--session-file` [V] | `--approval-mode yolo\|auto_edit`, `--policy`, `--skip-trust` [V] | `settings.json mcpServers` [V] | `-m` [V] | 0, 1, 41 (auth, observed), 42, 53 (turn limit) [V] | `-w` (experimental) [V] |
| Goose 1.53 | `goose run -t "…"` / `-i file\|-` | `--output-format json` → `messages`, `metadata.cost_usd`; no session ID [V src] | recipe `response.json_schema` [V] | `--name` + `-r` [V doc] | `GOOSE_MODE=auto` [V doc] | `--with-extension`, `--with-streamable-http-extension` [V] | `--provider --model` [V] | non-zero on failure [V-ish] | none [U] |
| Aider 0.86 | `aider -m "…"` / `-f file` | text only [V] | no | no | `--yes-always` [V] | no | `--model` | [U] | n/a |
| Cursor `agent` | `agent -p "…"` | `--output-format json` → `.result`, `.session_id` [V doc] | no [U] | `--resume <chatId>` [V doc] | `--force`, `--trust`, `--approve-mcps` [V doc] | `.cursor/mcp.json` [U] | `--model` [V doc] | non-zero on failure, no JSON [V doc] | `--worktree` [V doc] |
| Copilot 1.0.91 | `copilot -p "…"` | `--output-format json` (JSONL); `--usage-output-file` [V help] | no [U] | `--resume <id>`, `--session-id` [V] | `--allow-all-tools` (required), `--deny-tool` [V] | `--additional-mcp-config` [V] | `--model` [V] | 1 on auth failure [V] | [U] |

**Native git-worktree support:**
- Claude Code (`-w`) [V], Codex (`--worktree`, not resumable) [V], Gemini (`-w`, experimental) [V], and Cursor (`--worktree`) [V] have it.
- OpenCode, Kiro, Goose, Aider, and Copilot do not (Copilot is unclear).
- **Recommendation:** the harness creates and owns worktrees (`git worktree add`) and passes them as cwd. Each CLI's worktree feature uses a different location and different resume semantics [I].

---

## 11. ACP (Agent Client Protocol) as a uniform driver — serious evaluation

**What it is.** ACP is JSON-RPC 2.0 over the agent's stdio. The client spawns the agent subprocess [V docs + schema].
- Stable **v1** (schema 1.24.1, 2026-09-30) agent methods: `initialize`, `authenticate`, `session/new`, `session/load`, `session/set_mode`, `session/set_config_option`, `session/prompt`, `session/cancel`, `session/list`, `session/delete`, `session/resume`, `session/close`, `logout`. Client methods: `session/request_permission`, `session/update`, optional `fs/*` and `terminal/*`, and `elicitation/*` [V `schema/v1/meta.json`].
- **v2 is alpha** (2.0.0-alpha.7) [V CHANGELOG].

**What maps cleanly onto the factory** [V schema]:
- `session/new {cwd, mcpServers[], additionalDirectories?}`: **MCP servers are a required per-session parameter**. All agents MUST support stdio MCP; http/sse depends on capability. Serena and Playwright can therefore be injected uniformly without touching each CLI's config format.
- `session/prompt` → `stopReason ∈ {end_turn, max_tokens, max_turn_requests, refusal, cancelled}`. That is a uniform terminal status.
- `session/request_permission` is answered by **our client** (`allow_once` / `reject_once` …). That gives one permission policy engine for all agents.
- Resume through `session/load` (capability `loadSession`) or `session/resume` (`sessionCapabilities.resume`).
- `session/cancel` handles timeouts.
- `usage_update {used, size, cost{amount,currency}?}` is in stable `SessionUpdate`. `PromptResponse.usage` (token counts) is **unstable-only** in the schema, but adapters already send it [V observed].
- Model selection uses `session/set_config_option` on the option whose `category == "model"`.

**Who implements it.**
- Native, listed on https://agentclientprotocol.com/get-started/agents [V]: Gemini CLI, OpenCode, Kiro CLI, Goose, GitHub Copilot, Cursor, Qwen Code, Cline, Augment, Factory Droid, Junie, Mistral Vibe, OpenHands, and others.
- Via adapter: Claude (`@agentclientprotocol/claude-agent-acp`, on the Agent SDK) and Codex (`@zed-industries/codex-acp`).

**Empirical headless probe.** I wrote a ~90-line Python client that spawns the agent, calls `initialize` → `session/new` → `set_config_option(model)` → `session/prompt`, and auto-approves permissions [V].
- **OpenCode** `opencode acp --pure` with model `opencode/big-pickle`: `stopReason:end_turn`, text "PONG", `usage_update.cost`. Capabilities: `loadSession`, `resume`, `fork`, `list`, `close`, mcp `http`/`sse`.
- **Claude** `claude-agent-acp` 0.85.1 with model option `haiku`: "PONG", `stopReason:end_turn`, `usage_update.cost.amount=0.0585 USD`. Config options were `mode` (default/acceptEdits/plan/auto/bypassPermissions), `model`, `effort`, and `fast`. Capabilities: load, resume, fork, list, close, delete, additionalDirectories, subagents.
- **Gemini** `--acp`, **Copilot** `--acp`, and **codex-acp** all initialised fine and advertised `loadSession:true` plus MCP http. They failed `session/new` only for lack of auth in my sandbox. Their advertised `authMethods` were: Gemini `gemini-api-key`, `vertex-ai`, …; Copilot `copilot-login`; Codex `codex-api-key`, `openai-api-key`, `chatgpt`.

**Gaps that keep ACP from being the whole answer** [V schema unless marked]:
1. **No structured-output / JSON-schema in the protocol.** The verifier verdict must come from a prompt contract plus client-side JSON-schema validation and repair/retry. The alternative is adapter-specific `_meta`: claude-agent-acp forwards `_meta.claudeCode.options` (allow-listed SDK options) to the Agent SDK [V source]. That is not portable.
2. **No max-turns or budget in the protocol.** Only `stopReason:max_turn_requests` is reported. Enforce wall-clock and cost limits client-side by watching `usage_update` and calling `session/cancel` [I].
3. **Model and mode values are agent-defined strings** (`haiku` vs `opencode/big-pickle` vs `gpt-…`). Category tags are optional ("MUST NOT be required for correctness"). The factory still needs a per-agent model map.
4. **Auth is out-of-band** (env vars or the agent's own login). `authenticate` and `authMethods` are interactive-oriented [I].
5. **Adapter fidelity and lag.** codex-acp `main` pins codex crates at **rust-v0.137.0**, while the CLI is 0.160.0 [V Cargo.toml]. The Claude adapter **loads the user's normal Claude config** (CLAUDE.md, user MCP, plugins), so ACP-driven Claude cost about 6× the tokens of the `--safe-mode` CLI probe (0.0585 vs 0.0097 USD) [V observed; I attribution]. In CI, isolate it with `CLAUDE_CONFIG_DIR` or `_meta` options [I].
6. **Protocol churn.** v2 is in alpha, and many useful pieces are `unstable` (`PromptResponse.usage`, `session/fork`, subagents, MCP-over-ACP) [V].
7. **Headless client tooling.** `acpx` (openclaw) is a headless ACP CLI client (`acpx codex exec "…"`, `--format json` NDJSON, named sessions) but is "pre-1.0, evolving" [D https://cdn.jsdelivr.net/gh/openclaw/acpx@main/README.md]. The official ACP SDKs (TS/Python/Rust) are the safer base [I].

**Verdict [I, high confidence].** ACP is viable as the **primary transport** for most adapters: one client, uniform MCP injection, permission policy, cancel, resume, usage/cost, and model switching. It massively shrinks the per-CLI surface. Keep a **native-CLI adapter path** for:
- (a) schema-enforced verifier verdicts (Claude `--json-schema`, Codex `--output-schema`);
- (b) hard caps (`--max-turns`, `--max-budget-usd`);
- (c) agents or features whose ACP adapter lags.

Design the factory interface around ACP's concepts (session, prompt, stopReason, updates, permission callback), and make "native CLI" one implementation of that interface rather than the reverse.

**Direct-API verifier backends.** For a no-tools verifier, call provider APIs directly with their native structured-output features (Anthropic/OpenAI/Gemini JSON-schema output). Exact parameter names are [U] and were not re-verified in this pass. Alternatively, use `opencode serve` + `format:json_schema` as a provider-agnostic router [V that the feature exists]. No cross-vendor standard exists for structured verdicts; ACP doesn't cover it [V]. MCP standardises tools, not agent control [I].

---

## 12. Availability, quota & cooldown (added scope)

Goal: pre-run checks (version, auth, smoke prompt), detection of usage-limit or cooldown windows, and fall-back with a logged reason and a `cooldown_until` timestamp.

### 12.1 Codex CLI

- **Zero-token quota query (best in class) [V observed].**
  - `codex app-server` (stdio JSON-RPC): `initialize` → `initialized` → `account/rateLimits/read` returned `{ordinaryUsageAllowed:true, rateLimits:{limitId:"codex", primary:{usedPercent:0, windowDurationMins:300, resetsAt:<epoch s>}, secondary:{usedPercent:0, windowDurationMins:10080, resetsAt:<epoch s>}, planType:"plus", rateLimitReachedType:null, credits:{hasCredits,unlimited,balance}}, rateLimitsByLimitId:{codex:{…}}, …}` in **2.2 s with no model call**.
  - `account/read` gives the auth type (`chatgpt`) and plan [V].
  - Schema: `app-server-protocol/src/protocol/v2/account.rs` [V].
  - `rateLimitReachedType ∈ {rate_limit_reached, workspace_owner_credits_depleted, workspace_member_credits_depleted, workspace_owner_usage_limit_reached, workspace_member_usage_limit_reached}` [V source].
  - The comment on `ordinaryUsageAllowed` says to treat null as unknown and not to infer recovery [V source].
  - This only makes sense for ChatGPT-plan auth. API-key auth has no plan windows [I].
- **`codex exec --json` carries NO rate-limit data and NO cost** [V source + live run: only `turn.completed.usage`]. Core `TokenCountEvent{info, rate_limits{primary/secondary{used_percent, window_minutes, resets_at(epoch s)}}}` exists and is written to rollout files under `$CODEX_HOME/sessions` [V source: rollout items include `EventMsg::TokenCount`]. Parsing the rollout after a non-ephemeral run is a fallback [I].
- **Usage-limit hit mid-run.**
  - `UsageLimitReached` and `QuotaExceeded` are **terminal (never retried)**. Transient `RateLimitExceeded`, `UnexpectedStatus`, and stream errors are retried with backoff and server advice [V `protocol/src/error.rs` `retry_delay`].
  - In exec this surfaces as `turn.failed {error:{message}}` and **exit 1** [V source].
  - The message is human and **localized**: "You’ve hit your usage limit. … Try again at 3:45 PM." / "… or try again at Oct 4th, 2026 3:45 PM." [V source]. The structured `resets_at` is not in the exec JSONL [V], so after a failure call `account/rateLimits/read` to get the epoch reset [I].
- **Fail-fast knobs.** Per-provider `request_max_retries` and `stream_max_retries` in `[model_providers.<id>]` [V config sample in source]. Whether these apply to the built-in `openai` provider via `-c` is [U]. Observed: a 401 retried "Reconnecting… 5/5" (~5–10 s) before failing [V].
- **Pre-run checks.** `codex --version`; `codex login status` (exit 1 + "Not logged in" when unauthenticated [V observed]); the `account/rateLimits/read` probe. The minimal smoke `codex exec --ephemeral --ignore-user-config -s read-only --json "Reply with exactly: hello" </dev/null` took **7.2 s** wall and about 18.8k input tokens (12.3k cached), 5 output tokens [V observed]. The cost is a slice of the 5h window, not USD [I].

### 12.2 Claude Code

- **Zero-cost quota query [V observed].** `claude -p --output-format json "/usage"` returned `num_turns:0, total_cost_usd:0, duration_api_ms:0` (0.45 s internal, 2.4 s wall). The result text was "Current session: 50% used · resets Oct 3 at 6pm (Europe/Bucharest) / Current week (all models): 14% used · resets Oct 7 at 9pm …".
  - It is **human text in the local TZ**, so a fragile parse. The SDK doc confirms `/usage` output arrives as an assistant message [V].
  - Subscription auth only [I].
- **Machine-readable windows on every real request [V observed].** `--output-format stream-json --verbose` emits `{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":<epoch s>,"rateLimitType":"five_hour","overageStatus":…,"unifiedWindows":{"five_hour":{"utilization":0.49,"resetsAt":…},"seven_day":{"utilization":0.14,"resetsAt":…}}}}`.
  - The documented type lists only `status (allowed|allowed_warning|rejected)`, `resetsAt?`, `utilization?`, and `errorCode:"credits_required"` [V SDK doc]. `rateLimitType` and `unifiedWindows` are observed but undocumented, so treat them as optional.
  - The status line JSON documents `rate_limits.five_hour/seven_day.{used_percentage, resets_at(epoch s)}`, only for Pro/Max subscribers and only after the first response [V statusline doc].
- **Minimal probe cost [V observed].** `claude -p --safe-mode --no-session-persistence --model haiku --tools "" --max-turns 1 --output-format stream-json --verbose "Reply with exactly: hello"` cost **0.0041 USD**, `duration_ms` 991, about 3 s wall, and also yields the rate_limit_event. `claude auth status` gives JSON auth state, exit 0 logged in / 1 not [V cli-reference].
- **Limit messages.** "You've hit your session limit · resets 3:45pm", "…weekly limit · resets Mon 12:00am", "…Opus limit…", "…Sonnet limit…". Model-family limits can be bypassed by switching model; session and weekly limits cannot [V errors doc]. "You've hit your monthly spend limit · …" [V]. `API Error: Request rejected (429) …` covers API-key/Bedrock/Vertex quotas [V]. Exit code and `result`/`api_error_status` shape for these in `-p` are not observed; expect `is_error:true`, non-zero exit [I].
- **Retry/wait controls.**
  - `CLAUDE_CODE_MAX_RETRIES` (default 10, cap 15) [V env-vars doc]. Set it low (for example `0` or `1`) for fail-fast; whether `0` is accepted is [I].
  - **Do NOT set `CLAUDE_CODE_RETRY_WATCHDOG=1`** in the harness: it retries 429/529 indefinitely and **waits out a usage window until reset** (spend-limit and credit 429s still fail at once) [V].
  - `api_retry` events in stream-json carry an `error` category (`rate_limit` = 429 quota vs `overloaded` = 529) and `retry_delay_ms` [V headless doc]. Abort on the first `rate_limit` retry to fail fast [I].
  - Interactive "wait for reset" / auto-continue applies to interactive sessions only [V errors doc].

### 12.3 OpenCode

- **No quota query.** Quota is provider-specific; `opencode stats` is local history only [V help; I].
- **429/limits [V source `session/retry.ts`].**
  - Retries match `/429|500|502|503|504|524/` and "rate limit|too many requests|try again…" up to **5 retries**.
  - The delay honours `retry-after-ms` / `retry-after` **capped only at about 24.8 days** (2^31 ms). Without headers it backs off exponentially, capped at 30 s.
  - **A subscription 429 with `retry-after: 18000` would make `opencode run` sleep for hours: a CI hang.**
  - OpenCode Go/Zen limits produce messages like "<limit> usage limit reached. It will reset in 4 hours 12 minutes…" (from `retry-after`) [V].
- **Detection.** `opencode run --format json` emits **nothing** while retrying (retry status is not mirrored) [V run.ts]. Use `opencode serve` + SSE `/event` and watch `session.status {type:"retry", attempt, message, next}` [V processor.ts]. Then `POST /session/:id/abort` and record `next`/`retry-after` as the cooldown [I].
- **Terminal errors:** `{"type":"error","error":{…}}` and exit 1 [V].
- **Minimal probe [V observed].** `opencode run --pure --format json -m opencode/big-pickle "Reply with exactly: PONG"` returned exit 0, cost 0 (free model), about 28k tokens. A provider-specific cheap model is needed for a real availability check [I].

### 12.4 Kiro CLI (docs-level only)

- Quota query: `kiro-cli chat --no-interactive "/usage"` prints an ANSI usage table with monthly credits %, reset date, and bonus credits [D CodexBar docs, https://mintlify.wiki/steipete/codexbar/providers/other-providers]. `/usage` is a documented slash command [V kiro cli-commands]. Whether it consumes credits is [U].
- `kiro-cli whoami` gives the auth status [V doc].
- When monthly credits are exhausted, "requests pause until your limits reset at the start of the next month". The billing month resets at 00:00 UTC on the 1st, so the reset time is computable without an API. Add-on credits exist on paid plans [V https://kiro.dev/docs/billing/related-questions/].
- The headless exit code and error string for credit exhaustion are [U]. Assume exit 1 [I].

### 12.5 Gemini CLI (brief)

- Daily request quotas per auth type, for example Code Assist individual 1,000/day and API-key free 250/day [V `docs/resources/quota-and-pricing.md`].
- The `ModelAvailabilityService` **falls back to another model on quota/server errors**. By default it prompts, and some utility calls fall back silently [V `docs/cli/model-routing.md`]. Headless behaviour of that prompt is [U]. **Risk: a silent model switch.** Check `stats.models` in the JSON output to confirm which model actually ran [I].
- `/stats model` shows quota interactively [V doc]. Headless use is [U].
- Exit codes 1 (API) and 41 (auth, observed) [V].

### 12.6 Harness implications for availability

1. **Probe tiers.** Tier 0 is zero-cost: version, auth status, quota query where one exists (Codex `account/rateLimits/read`, Claude `/usage`, Kiro `/usage`, Copilot `--max-ai-credits` is a cap, not a query). Tier 1 is a one-token smoke prompt on the cheapest model, about 3–7 s and a fraction of a cent. Cache the results per (tool, model, auth identity) with a TTL [I].
2. **Normalise every limit signal to `{tool, model?, kind: usage_limit|rate_limit|spend_limit|credits, resets_at_epoch?, source}`.**
   - Sources: Codex `rateLimits.*.resetsAt`; Claude `rate_limit_event.resetsAt` / `unifiedWindows`; OpenCode `retry-after`; Kiro month boundary.
   - Text parsing ("resets 3:45pm", "Try again at 3:45 PM") is a last resort, because it is localized.
3. **Fail fast, never wait.**
   - Codex: usage limit is terminal (exit 1).
   - Claude: `CLAUDE_CODE_MAX_RETRIES` low, no watchdog, abort on the first `api_retry{error:"rate_limit"}`.
   - OpenCode: a wall-clock timeout is mandatory, or use serve + abort on `session.status.retry`.
4. **Model-family limits (Claude Opus/Sonnet, Gemini Pro) are per-model**, so fall back to another model on the same tool before another tool [V Claude errors doc; I].

---

## 13. Top design implications for the adapter interface

1. **Result normalisation is mandatory, not cosmetic.** Every CLI reports completion differently:
   - Claude: `subtype` + `is_error`, with `result` possibly null.
   - Codex: `turn.failed` + exit 1, tokens only.
   - OpenCode: no result event, and exit 0 even after a permission-rejection stop.
   - Gemini: exit codes 41/42/53.
   - Cursor: no JSON at all on failure.

   Define `RunResult{status: ok|max_turns|budget|permission_blocked|auth|quota|error|timeout|cancelled, final_text, structured, session_id, cost_usd?, tokens?, exit_code, raw_events_path}`. Derive it from events plus exit code, never from the exit code alone.
2. **Session ID is captured, or preset, before the work starts.** Preset where possible (Claude `--session-id`, Gemini `--session-id`, Copilot `--session-id`). Otherwise capture from the first event (Codex `thread.started`, OpenCode every event, Gemini `init`). Goose has none, so use `--name`. Persist the agent's state dir as a CI artifact (`CLAUDE_CONFIG_DIR` / transcript `.jsonl`, `CODEX_HOME`, `opencode export`, `--session-file`) so resume works on a fresh runner.
3. **Structured verdicts need a capability flag plus a portable fallback.** There are only three native schema paths: Claude `--json-schema`, Codex `--output-schema`, and OpenCode SDK `format`. ACP has none. Implement `schema_mode: native | prompt_contract`, always validate client-side, and allow one repair turn via resume.
4. **Permissions and MCP must be generated per adapter from one harness policy.** Native options are Claude `--permission-mode dontAsk --allowedTools … --mcp-config … --strict-mcp-config --bare`, Codex `-s workspace-write` + `-c mcp_servers.*`, OpenCode `OPENCODE_PERMISSION`/`OPENCODE_CONFIG_CONTENT` + `--auto`, Gemini `--approval-mode` + `--skip-trust`, and Kiro `--trust-tools`. Alternatively, inject MCP via ACP `session/new.mcpServers` and answer `request_permission` centrally. Always disable repo-supplied hooks and MCP (Claude `--bare`, Codex `--ignore-user-config/--ignore-rules`, OpenCode `--pure`). In CI, `-p` modes trust the repo silently.
5. **Prefer ACP as the default transport and keep a native-CLI fallback, with the harness owning timeouts, worktrees, and quota.** ACP gives uniform cancel, resume, permission, MCP, and usage for Gemini, OpenCode, Kiro, Copilot, Cursor, Goose, and Claude/Codex via adapters [V probe]. Watch adapter lag (codex-acp at codex 0.137) and the lack of max-turns or schema. The harness should own:
   - the git worktree (CLI worktree flags diverge and Codex's is not resumable);
   - a wall-clock timeout with SIGINT/`session/cancel`. Turn caps are inconsistent: Claude `--max-turns`, Goose `--max-turns`, Gemini `maxSessionTurns`, OpenCode agent `steps`, Copilot `--max-autopilot-continues`, and none in Codex. None of the CLIs has a wall-clock cap;
   - the availability, cooldown, and fallback registry from section 12.

## 14. Docs-vs-binary discrepancies found (trust the binary)

- Codex docs say `--full-auto` "prints a warning". 0.160.0 **rejects it** as an unknown argument [V].
- Claude SDK type says `result: string`. With `error_max_turns`, the CLI emitted `result: null` + `errors[]` [V].
- Claude `rate_limit_event` emits `rateLimitType` and `unifiedWindows`, which are not in the documented type [V].
- Claude `--max-turns` is missing from `claude --help` but documented and working [V].
- Gemini docs list exit codes 0/1/42/53. Missing auth produced **41** [V].
- OpenCode SDK doc says `info.structured_output`; the source sets `message.structured` [V/U].
- Repo moves: `sst/opencode` → `anomalyco/opencode`, `block/goose` → `aaif-goose/goose`, `zed-industries/claude-code-acp` → `agentclientprotocol/claude-agent-acp` [V GitHub API].
- WebFetch summaries hallucinated fields (for example a `rateLimitType` enum and an `api_retry` shape) that the raw docs don't contain. All load-bearing fields here were re-checked against raw markdown, source, or live output.

## 15. Open items / unverified

- Kiro stream-json event schema, headless resume combined with `--no-interactive`, and the credit-exhaustion exit code and message [U].
- Whether Codex `request_max_retries` can be overridden for the built-in OpenAI provider via `-c` [U].
- Exit code and JSON shape of Claude `-p` when a subscription session limit is hit (not reproducible without exhausting quota) [I].
- Gemini headless behaviour when model fallback would prompt [U].
- Copilot worktree flag; Cursor MCP file location [U].
- Side note: a `.serena/` directory appeared in the scratch repo during the test window (between the Claude CLI runs and the OpenCode run). The source was not isolated. It is a reminder that non-bare `-p` and ACP adapter runs may start user-level MCP servers [U].
