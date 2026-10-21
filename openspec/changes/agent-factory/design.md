## Context

SPEC 8 (agent and model factory) and 8.4 (availability) are normative; architecture section 8 gives the flow. The
reference environment is `example-group/dummy-agentic` on runner `l4-runner` (shell executor, tags
agentic/ai/opencode), which has the `opencode` and `claude` CLIs. The walking skeleton (M1) must run live there with
`claude-code`, `opencode`, `openai-chat` and `fake`. Facts about external tools keep SPEC evidence labels: [V]
verified, [D] secondary, [I] inferred/design decision, [U] unverified (a recorded-output contract test or a spike must
confirm it before code relies on it).

Product intent: "add it to my existing project and it works". The factory therefore assumes the runner has the tools
named in the profile chain. When a binary is missing the probe says exactly which one, with the minimum version, and
the message points at `l4 doctor --fix` (change 12 installs user-local tools). This change never installs anything.

## Goals / Non-Goals

Goals:
- One `AgentAdapter` protocol for all native CLIs and ACP, one `LLMBackend` protocol for tool-less models.
- Status derived from events plus exit code (L4-FAC-002), recorded raw output kept for replay tests (L4-FAC-007).
- Selection that never spends a model request on a profile known to be cooling, missing or logged out, and that
  explains every decision in one console line and one structured event (L4-AVL-008).
- Fail-fast on limits: no adapter waits for a usage window to reset.

Non-Goals:
- Installing CLIs or logging in (change 12 prints the human-only auth steps).
- The implementer prompt/TDD loop (change 6), the verifier ladder (change 8), the forge and CI (change 9).
- Running adapters inside the sandbox (change 11 wraps `Popen` through `Sandbox.wrap`; this change exposes the hook
  `ProcRunner(argv, env, cwd, wrap=None)` only).
- Auto-merge, Spec Kit, web dashboard (SPEC 0.1 out of scope).

## Decisions

### D1. Module layout (all inside the owned directories)

| Module | Contents |
|---|---|
| `l4/agents/base.py` | `AgentCaps`, `ProbeStep`, `ProbeCtx`, `ProbeResult`, `RunRequest`, `RunResult`, `Usage`, `LimitSignal`, `McpServer`, `PermissionPolicy`, `EventSink` (Protocol: `append(type, **fields)`, the signature of state-vcs-locks' `l4.state.ledger.LedgerWriter.append`, so a ledger writer is passed directly), `AgentAdapter` (Protocol), `AdapterError` |
| `l4/agents/proc.py` | `ProcRunner.run(argv, env, cwd, stdin, timeout_s, interrupt, on_line, stall_timeout_s)`: starts a new process group, streams stdout lines to `on_line` (which may return `Abort` to stop early), SIGINT on `interrupt`, SIGKILL of the group on timeout, never inherits the parent environment. The same module holds `build_env(profile, base_env, extra)`, a thin wrapper over sandbox-security's `l4.sandbox.env.build_agent_env(profile, host_env, spec)` (owner of the L4-SEC-001 allow-list: `PATH`, `HOME`, locale, proxy, `L4_RESULT_PATH`, plus the profile's own credential variables from `credential_env_names`, D6); `PATH` is runner-provisioning's `l4.provision.runner.harness_path(...)` (L4-PRV-016) so user-local CLIs are found. No second allow-list lives here. Writes raw stdout/stderr to `raw_events_path` |
| `l4/agents/factory.py` | `ADAPTERS: dict[str, type[AgentAdapter]]`, `BACKENDS: dict[str, type[LLMBackend]]`, `build(profile) -> AgentAdapter | LLMBackend`, `Selected`, `Factory.for_role(role, unit, constraints) -> Selected` |
| `l4/agents/claude_code.py`, `opencode.py`, `codex.py`, `kiro_cli.py`, `command.py`, `acp.py`, `fake.py` | one class each: `ClaudeCodeAdapter`, `OpenCodeAdapter`, `CodexAdapter`, `KiroCliAdapter`, `CommandAdapter`, `AcpAdapter`, `FakeAdapter` |
| `l4/llm/base.py` | `Msg`, `Usage` (re-exported), `StructuredResult`, `LLMBackend` (Protocol), `validate_against_schema(instance, schema)` |
| `l4/llm/openai_chat.py`, `anthropic.py`, `system_one.py`, `fake.py` | `OpenAIChatBackend`, `AnthropicMessagesBackend`, `SystemOneBackend` (+ `LayaServe` context manager), `FakeBackend` |
| `l4/availability/probes.py` | `ProbeLadder.run(profile, steps, ctx) -> ProbeReport`, one function per step, `normalise_hello(text) -> str`, `drop_identity(auth_json) -> AuthInfo` |
| `l4/availability/cooldown.py` | `CooldownKey(tool, model | None)`, `CooldownEntry`, `CooldownRegistry` (file-backed, `fcntl.flock`, atomic `os.replace`), `ProbeCache`, `ConcurrencyGate` (D9), `Clock` (Protocol; `SystemClock`, `FakeClock`) |
| `l4/availability/fallback.py` | `FallbackSelector.select(role, chain, constraints, ctx) -> Selection`, `Skipped`, `format_selected_line`, `format_skipped_line`, `to_event` |
| `l4/doctor/checks_agents.py` | `LIVE-001`, `LIVE-002` registered on the bootstrap-core doctor registry; the `command` and `acp` rows added to bootstrap-core's `checks_env.ADAPTER_BINARIES` (ENV-004/ENV-005 stay bootstrap-core's) |

Alternatives considered: one module per tool containing probe+run+parse (kept: that is what `claude_code.py` etc. are);
a plugin entry-point system for third-party adapters (rejected for v1: the `command` and `acp` adapters already cover
foreign tools, and entry points add install-time failure modes).

### D2. Core data structures (names are fixed; tasks and tests use them verbatim)

```python
@dataclass(frozen=True)
class LimitSignal:
    tool: str; model: str | None
    kind: Literal["usage_limit", "rate_limit", "spend_limit", "credits"]
    resets_at: datetime | None          # tz-aware UTC
    source: str                          # e.g. "claude.rate_limit_event", "codex.rateLimits", "opencode.retry-after", "text"
    raw_excerpt: str                     # redacted, <= 200 chars
    window_minutes: int | None = None; used_percent: float | None = None

@dataclass
class ProbeResult:
    step: ProbeStep; ok: bool
    detail: dict[str, Any]              # binary: {"version": "2.1.288"}; auth: {"logged_in","auth_method","plan"}; quota: {"windows":[...]}; hello: {"ms": 2104}
    reason: str | None                  # human reason when not ok, e.g. "not found", "unexpected reply", "timeout"
    limit: LimitSignal | None           # set when the failure is a usage/rate limit (-> cool-down)
    skipped: bool = False               # step not applicable (no zero-cost quota query, API-key auth)
```

`AgentCaps(schema_mode: Literal["native","prompt_contract"], resume: bool, preset_session_id: bool, max_turns: bool,
budget_cap: bool, mcp_injection: bool, quota_query: bool, worktree_cwd: bool)`.
`Selected(profile, impl, fallback_index, skipped: list[Skipped], probes: dict[str, dict], cached: bool, fallback_from: str | None)`.
`Selection` is the availability-side result (`Selected` without `impl`); `Factory.for_role` turns it into `Selected`.
`RunRequest`, `RunResult`, `StructuredResult` are exactly the SPEC 8.1 shapes.

### D3. Adapter command lines (exact flags from SPEC 8.3; prompt on stdin unless noted)

- `claude-code`, auth `api_key`: `claude -p --bare --output-format stream-json --verbose --model M --max-turns N
  --max-budget-usd B --session-id UUID --permission-mode dontAsk --allowedTools <list> --strict-mcp-config
  --mcp-config F [--json-schema S]` with `ANTHROPIC_API_KEY`. Auth `subscription`: identical **without `--bare`**,
  authenticated by `CLAUDE_CODE_OAUTH_TOKEN` or the runner's stored login (default `CLAUDE_CONFIG_DIR` kept). Env:
  `CLAUDE_CODE_MAX_RETRIES=1`; `CLAUDE_CODE_RETRY_WATCHDOG` is removed from the child env if present. Resume:
  `--resume <id>`. Parsing [V 2.1.288, research/02]: last `type:"result"` event (`result` may be `null`,
  `structured_output`, `total_cost_usd`, `session_id`, `subtype` in `success | error_max_turns | error_during_execution |
  error_max_budget_usd | error_max_structured_output_retries`, `is_error`, `usage`, `modelUsage`). `rate_limit_event`
  (`status`, `resetsAt` epoch s, optional `unifiedWindows.{five_hour,seven_day}.{utilization,resetsAt}`) feeds quota;
  `api_retry{error:"rate_limit"}` => interrupt within 5 s and `status = rate_limited`; `modelUsage` keys give
  `model_resolved`. The schema delivery uses one extra turn, so `max_turns` passed = requested + 1 when
  `--json-schema` is used [I].
- `opencode`: `opencode run --pure --format json -m provider/model [--agent A] [--dir <cwd>]` with the prompt on **stdin**
  and no positional message (research/02 [V source `run.ts`: piped stdin is read]; SPEC shows a positional
  `"<prompt>"`, which is limited by Linux `MAX_ARG_STRLEN` = 128 KiB per argument; stdin avoids that. Whether an empty
  positional plus stdin is accepted by 1.18.x is [U], pinned by the first contract test; fallback is the positional
  argument for prompts < 100 KB). Env: `OPENCODE_PERMISSION` (inline JSON allow/deny map), `OPENCODE_CONFIG_CONTENT`
  (`mcp{...}` with timeout >= 20000 ms for Serena). Resume `-s <sessionID>`. Parsing [V observed]: NDJSON
  `{type, timestamp, sessionID, part}` with `type in step_start | text | reasoning | tool_use | step_finish | error`;
  no terminal result event: final text = concatenated `text` parts; cost = sum of `step_finish.part.cost`; success
  requires the last `step_finish.part.reason == "stop"`; last reason `tool-calls` with exit 0 => `permission_blocked`
  [V observed]. `error` event or exit 1 => `error`. Structured output: prompt contract only (`$L4_RESULT_PATH`).
  Run mode emits nothing while it retries a 429 [V source], so M1 enforces `timeout_s` plus a stall watchdog
  (`options.stall_timeout_s`, default 180 s without any event). `opencode serve` + SSE `session.status{type:retry,next}`
  + `POST /session/:id/abort` is M2.
- `codex` (M2): `codex exec --json -m M -s workspace-write --ignore-user-config [--output-schema S] -o OUT -`;
  `</dev/null` is NOT used because the prompt is on stdin (`-`). Resume: `codex exec resume <id>` with `-c
  sandbox_mode="workspace-write"` (no `-s`). Never emits `--full-auto` (removed in 0.160.0 [V]). Parsing:
  `thread.started.thread_id`; last `item.completed` with `item.type == "agent_message"`; `turn.completed.usage` (tokens,
  no USD); `turn.failed` + exit 1 => terminal `quota` if the message matches the usage-limit shape, else `error`.
  Quota probe: stdio JSON-RPC to `codex app-server`: `initialize` -> `initialized` -> `account/rateLimits/read` [V
  re-run]; windows `primary` (300 min) and `secondary` (10080 min) with `usedPercent`, `resetsAt` (epoch s observed;
  accept ISO too), `rateLimitReachedType`. API-key auth skips the quota step.
- `kiro-cli` (M2): `kiro-cli chat --no-interactive --trust-tools=<allow-list> [--agent A] [--model M] --output-format
  stream-json --require-mcp-startup "<prompt>"` [U for headless trust, stream-json schema, `--resume-id` with
  `--no-interactive`; exit 3 = MCP startup failure [V doc]]. Auth `kiro-cli whoami`; quota `/usage` text [D].
- `command` (M2): `options.argv` template with `{prompt_file}`, `{result_path}`, `{model}`, `{session_id}`; optional
  `options.resume_argv`; probe `options.probe_argv`. Success = exit 0 and a result file valid against the schema.
- `acp` (M2, experimental): JSON-RPC over stdio: `initialize` -> `session/new{cwd, mcpServers}` ->
  `session/set_config_option(model)` -> `session/prompt`; `session/request_permission` answered from one
  `PermissionPolicy`; `stopReason` and `usage_update.cost` mapped to `RunResult`. Logs `agent.experimental` once.
- `fake`: `FakeAdapter(script: list[Step])`; a `Step` is `{status, final_text?, structured?, limit?, delay_s?, session_id?, writes?: {path: content}, events?: [...]}`.
  It writes a raw events file like the real adapters so downstream code is exercised end to end.

Isolation flags (`--bare`, `--strict-mcp-config`, `--ignore-user-config`, `--pure`, the Kiro agent flag) are not hard-coded per adapter: each `build_command` appends `l4.security.isolation.isolation_flags(adapter, auth, allow_repo_config)` (sandbox-security, L4-SEC-002), whose contract test asserts every adapter's argv contains them.

`PermissionPolicy.mode` is `implement` (workspace-write: Claude `dontAsk` + allow-list, Codex `-s workspace-write`) or `read_only`
(used by the clarifier, change 7, and the verifier's reading steps): Claude `--permission-mode plan` with an allow-list of
`Read Grep Glob`, Codex `-s read-only`, OpenCode `OPENCODE_PERMISSION` denying `edit` and `bash`, Kiro `--trust-tools=fs_read`.
Each adapter's `build_command` takes the policy, so no caller builds CLI flags itself.

### D4. Status derivation (L4-FAC-002)

Each adapter has `parse(events, exit_code, timed_out, interrupted) -> RunResult` as a pure function so recorded outputs
can be replayed. Precedence: `timeout`/`cancelled` (harness decided) > limit signal (`quota` / `rate_limited`) > `auth` >
`permission_blocked` > `max_turns` / `budget` > `error` (non-zero exit or error event) > `ok` only when the terminal
event says success **and** (when a schema was requested) the structured value exists. Exit code 0 never implies `ok`.

### D5. LLM backends

`LLMBackend.complete_structured(system, messages, json_schema, *, effort, max_tokens, timeout_s) -> StructuredResult`
with `status in ok | refusal | truncated | schema_invalid | error`. Rules shared by all backends: the returned `parsed`
is validated client-side with `jsonschema`-compatible validation (`validate_against_schema`; **dependency decision**: the
SPEC dependency list (click, pydantic, pyyaml, httpx) has no JSON-Schema validator, so validation is implemented with
pydantic's `TypeAdapter` for the subset used by the harness schemas (type, enum, required, properties, items,
minItems/maxItems, pattern, maxLength) and unsupported keywords raise at schema-load time rather than being ignored);
no `temperature`, `top_p`, `top_k` or forced `tool_choice` is ever sent (L4-FAC-005); httpx timeouts equal `timeout_s`.
- `openai-chat`: `POST {base_url}/chat/completions` with `response_format: {type: "json_schema", json_schema: {name,
  strict: true, schema}}`; when `base_url` host is `openrouter.ai` the body also carries `provider: {require_parameters:
  true}` [V]; Ollama (`http://localhost:11434/v1`) and LiteLLM use the same body; `Authorization: Bearer <env[api_key_env]>`.
  `finish_reason == "length"` => `truncated`; a `refusal` field => `refusal`.
- `anthropic-messages`: native Messages API structured output (M2); the OpenAI-compatible Anthropic endpoint is never
  used because it silently ignores `response_format` [V, research/04]. The exact request field for structured output
  is [U] until the contract test records one.
- `system-one` (M2): `POST /v1/systemone` with `{state, model, questions: {<id>: {type: noul|choice|score, instructions,
  criteria?}}}` [V docs.typesafe.ai/api]; `engine: laya-local` spawns `laya-serve` on a free port (`socket.bind(("127.0.0.1", 0))`),
  waits for readiness, and always stops it in a `finally`; request/response pairs go to `.l4-out/logs/system-one.jsonl`.
- `fake`: `FakeBackend(responses: list[StructuredResult | Exception])`.
- Model mismatch: if `model_resolved` differs from the requested model after normalisation (strip provider prefix and
  date suffix), the backend sets `StructuredResult.model_mismatch = True` and the **caller** (verifier) discards the
  verdict; `availability.model_mismatch` is emitted by `emit_mismatch(event_sink, role, requested, served)`.

### D6. Credentials and environment (secrets by env var NAME only)

`build_env` passes the allow-list plus only the variables the profile needs. SPEC gives `api_key_env` for backends only,
so adapter profiles use one built-in table keyed by adapter (and, for `opencode`, by the provider prefix of `model`):
claude-code api_key => `ANTHROPIC_API_KEY`, subscription => `CLAUDE_CODE_OAUTH_TOKEN` (optional: stored login works
without it); codex api_key => `CODEX_API_KEY`; kiro-cli => `KIRO_API_KEY`; opencode `openrouter/` => `OPENROUTER_API_KEY`,
`anthropic/` => `ANTHROPIC_API_KEY`, `openai/` => `OPENAI_API_KEY`; a profile-level `api_key_env` overrides it. The table
is implemented once as bootstrap-core's `l4.config.validate.credential_env_names(profile)` (doctor ENV-005 uses it too,
and bootstrap-core D5 accepts `api_key_env` on adapter profiles); `build_env` calls it and keeps no copy. Forge tokens are
never passed (L4-FAC-001, SPEC 18). Values never appear in logs: command lines are logged with the env names only.

### D7. Availability data model and files

- `$L4_CACHE/availability.json` (`{"version":1, "cooldowns": {...}, "probes": {...}}`), written atomically; read-modify-write
  under `fcntl.flock` on `availability.json.lock`. Expired cool-downs are ignored on read and pruned on write.
- Cool-down key `CooldownKey(tool, model)`, string form `"{tool}|{model or '*'}"`. A profile is cooling if an entry exists for
  `(tool, model)` or `(tool, None)`. For LLM backends `tool = "backend:{backend}@{host}"`. Entry fields (SPEC): `profile, until,
  kind, source, recorded_by_run`, plus `tool` and `model`.
- Probe cache key `"{profile}|{identity_hash}"`; `identity_hash = sha256(tool|auth|credential dir|env-name+value of the
  token variable)[:16]`. The value is hashed, never stored. TTL `availability.cache_ttl`. Failed probes are cached for the
  same TTL (a transient failure is therefore retried after the TTL, or immediately if the person runs `l4 doctor --live`).
  A real-run failure calls `ProbeCache.invalidate(profile)`.
- Ledger events via `EventSink`: `availability.selected`, `availability.fallback`, `availability.cooldown`,
  `availability.model_mismatch`. The ledger writer itself belongs to state-vcs-locks; this change depends only on the
  `EventSink` protocol and tests it with an in-memory sink.
- Sticky rule: a skipped profile gets a cool-down **only** when the failing step produced a `LimitSignal`. Missing binary, logged
  out, hello mismatch/timeout and custom-probe failures never write a cool-down (SCN-AVL-04/05/06/07/14).

### D8. Fallback selection algorithm (L4-FAC-006, L4-AVL-003..010)

For each profile in chain order: (1) apply `constraints` (independence: a `Callable[[Profile], str | None]` supplied by the
verifier; vendors used by the implementer come from the ledger, the SPEC-10.1 rule itself is change 8); (2) cooling?
skip with `cooling until T`; (3) concurrency gate (L4-FAC-008); (4) fresh cached probe? use it; else run the ladder,
recording each step result; first failure skips the profile. First usable profile wins. No profile usable: required role =>
`WaitingCapacity(retry_after=min(cooldown ends))` (exit 12, phase `waiting_capacity`, handled by the orchestrator);
optional role => `RoleUnavailable` (caller applies the documented degradation). Console lines follow SPEC 8.4 exactly:

```
[l4] implementer: codex-sol skipped — quota: 5h window 100% used, 0% remaining (resets 2026-10-03T14:32Z); cool-down recorded
[l4] implementer: claude-sonnet ok (binary 2.1.288 · auth subscription · quota 49% used · hello 2.1s) → selected, fallback #1
```

Format rules ([I], derived from the two SPEC examples): `skipped` line = `[l4] {role}: {profile} skipped — {step}: {reason}` +
`(resets {YYYY-MM-DDTHH:MMZ})` when known + `; cool-down recorded` when a cool-down was written; `ok` line =
`[l4] {role}: {profile} ok ({step details joined by " · "}) → selected` + `, fallback #{n}` when `n >= 1`; a cached probe
appends ` · cached` inside the parentheses. Exactly one `availability.selected` JSON event per selection with the SPEC
fields (`event, role, unit, selected, fallback_index, skipped[], probes{}`) plus `cached` and, when a fallback occurred,
`fallback_from`. A mid-run fallback additionally emits `availability.fallback{from, to, reason, resets_at}`.

### D9. Concurrency for shared subscription logins (L4-FAC-008)

`ConcurrencyGate(cache_dir)` uses N lock files `$L4_CACHE/locks/{tool}-{identity_hash}-{k}.lock` (k < max_concurrency) with
`fcntl.flock(LOCK_EX | LOCK_NB)`; the slot is held for the whole `run()` and released in `finally`, and flocks die with the
process, so a crashed run cannot leak a slot. During selection a busy profile is skipped with reason
`concurrency: max_concurrency 1 busy` when a later profile is usable; if it is the last usable candidate the selector waits
up to `ctx.wait_budget_s` (soft deadline) polling every 2 s, then skips. API-key profiles do not use the gate unless
`max_concurrency` is set.

### D10. Where [U] facts are confirmed first

| [U] fact | Confirmed by (before dependent code) |
|---|---|
| `opencode run` reads the prompt from stdin with no positional message | contract test `tests/contract/agents/test_opencode_replay.py::test_stdin_prompt` + live check in M1 task 1.27 |
| exact opencode event for an auto-rejected permission (last `step_finish.reason == "tool-calls"`) | recorded output from the `spikes` change, replay test |
| opencode `message.structured` vs `info.structured_output` (serve/SDK path) | M2 contract test; M1 uses the prompt contract so it is not needed |
| Claude `claude auth status` JSON key names (`logged_in`, `auth_method`, `plan` are the harness's names, not necessarily Claude's) | replay test `test_claude_auth_status_drops_email` |
| Claude exit code / shape when a subscription session limit is hit (research/02 [I]) | recorded output when reproducible; until then limit detection relies on `rate_limit_event.status == "rejected"` and `api_retry` |
| Kiro headless trust, stream-json schema, `--resume-id`, credit-exhaustion exit code | spike (change 0); M2 only |
| Anthropic Messages structured-output request field | M2 contract test with a recorded response |
| Codex `-c request_max_retries` effect | not required: usage limit is terminal [V] |

## Risks / Trade-offs

- R1 CLI output drift: all parsing is pure and replay-tested against pinned versions; `doctor --live` (LIVE-001/002) fails
  with "unrecognised output" and selection skips the profile (SCN-FAC-07). Mitigation: recordings live in
  `tests/fixtures/agents/<tool>/<version>/`.
- R2 OpenCode run mode cannot see a 429 sleep: wall-clock and stall watchdog bound the damage; the cool-down defaults to
  `availability.default_cooldown` unless `retry-after` text is observable. Serve mode (M2) gives exact data.
- R3 Hello probes spend real quota (about 19k Codex input tokens): the cache TTL (15 m) and the ladder order (cheap steps
  first) limit this; hello is skipped when a fresh cached success exists.
- R4 Shared state in `$L4_CACHE` between concurrent jobs: file locks plus atomic replace; corrupted JSON is treated as empty
  and rewritten (never raises into selection).
- R5 Claude subscription auth with `--bare` absent means repo-level hooks could run; the protected-path guard (L4-IMP-006,
  change 6) and `--strict-mcp-config` neutralise them. This change only builds the flags.
- R6 The M1 JSON-Schema validator subset can reject a schema the harness later adds; failing loudly at load time is
  intentional.
