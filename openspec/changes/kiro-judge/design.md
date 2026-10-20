## 1. Context

What exists at 0.4.18 (`aee4ca51`), read for this change:

- **The CLI judge** (`src/l4/llm/agent_judge.py`). `AgentJudge.complete_structured` renders one prompt document
  (`render_prompt`), appends `schema_suffix(schema)` when the adapter's `schema_mode` is not `native`, runs the
  adapter with `PermissionPolicy("judge")` and normalises the `RunResult` to a `StructuredResult`: statuses `auth`,
  `quota`, `rate_limited` become `limit` (the caller raises `RoleLimit` and takes the next judge); `ok` with a
  `structured` object is validated again; `ok` without one, or a detail starting with `STRUCTURED_DETAIL`, is
  `schema_invalid` with the rejected object in `raw`. A server-side overload is retried in the run (3 tries).
  `JUDGE_ADAPTERS = ("claude-code", "codex", "opencode", "fake")` is the `serves=` filter of the judges
  (`select_judge`), the plan-readiness review (`yolo/readiness.py`, role `judges`), the clarifier
  (`clarifier.py`) and `open_role_judge` (the `s1_judge` stand-in), and of `independence_keeper` and the step-9
  preflight in `ladder.py`.
- **The judge loop** (`src/l4/verifier/judge.py` `run_judge`): at most `MAX_CALLS = 2` calls; a `schema_invalid` reply
  is first repaired deterministically (`judge_repair.repair_reply`) and, if that fails, answered with one repair
  prompt that echoes the redacted rejected object. `expect_model` is set only for an adapter that reports the served
  model (`JudgeSeat`, `seat_of`): opencode and kiro-cli do not.
- **The opencode prompt-contract judge** (`OpenCodeAdapter._attach_judge_reply`): the reply text sliced from the first
  `{` to the last `}`, `json.loads`, `validate`; missing is `f"{STRUCTURED_DETAIL} missing: …"`, invalid is
  `f"{STRUCTURED_DETAIL} invalid: …"` with `rejected` set.
- **The kiro-cli adapter** (`src/l4/agents/kiro_cli.py`): `schema_mode` `prompt_contract`, `model_unverified = True`,
  `experimental = True`. `build_command` puts the prompt last in argv (`MAX_ARG_BYTES = 100_000`, else
  `AdapterError`). `TRUST_TOOLS = {"implement": …, "read_only": "fs_read", "judge": "read"}` (the task text's `""` is
  stale: the judge already avoids the empty list, but runs the default agent). An implementer step without
  `options.agent` runs a harness agent `l4-implement-<12 hex>` from a private `KIRO_HOME` (`write_harness_agent`,
  K3). `run` uses `judge_workdir(req)` (the empty `judge-cwd`) in judge mode and `stdin=None`. `parse` reads
  `stream_facts` (session id, `final_text` from `runFinished.finalText`, `run_error`, credits from `meteringUsage`,
  `last_message`, the context peak) and only knows the result-file contract (`attach_file_result`): a judge run has no
  result file, so today it could never answer. `probe_kiro`: auth is `whoami --format json`; quota is `/usage`
  (`kiro_quota`); hello runs the default agent with `--trust-tools=read` and the prompt as an argument.
- **Independence** (`src/l4/verifier/selection.py`, `src/l4/availability/vendor.py`): `resolve_vendor` gives a served
  model's vendor (`claude-`, `gpt-`/`o<digit>`, `gemini-`), else the tool's (`TOOL_VENDORS`: codex, claude-code), else
  the declared `vendor:` (`declared`), else `unknown`. `independence_constraint` and `Independence.independent`
  compare vendors, or raw `profile.model` strings under `different_model`.
- **Costs**: `JudgeRun.cost_usd`, `budget.cost{usd, profile, role: judge}` (ladder), `ClarifierReply.cost_usd`
  (clarifier); only `implementer/tdd.py` writes `budget.cost{credits, credits_source}` for a Kiro step. `fold`'s
  `_budget_cost` sums `usd` only.
- **Doctor**: `LIVE-001` (`--live`) selects the first usable profile of `implementer` and `judges`, which runs the
  probe ladder including hello; `LIVE-005` compares the CLI version with `recorded_versions.json`; CFG ids up to
  CFG-010 are used, CFG-011 is free here and in the delegate worktree (the delegate is rebased after this change).
- **The delegate** (`delegate-answers`, which follows this change; owner decision 2026-10-19: kiro-judge is 0.4.19, the delegate 0.4.20): `read_only` mode, `serves=("claude-code", "codex", "fake")`.

## 2. Research: kiro-cli 2.32.0

### 2.1 How it was run

`~/.local/bin/kiro-cli` is 2.32.0 (a link into `/Applications/Kiro CLI.app`). Every call ran through a wrapper in the
session scratchpad, so the owner's login was never read or touched:

```sh
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME=$H/home XDG_CONFIG_HOME=$H/config XDG_DATA_HOME=$H/data \
    XDG_CACHE_HOME=$H/cache TMPDIR=$H/cache TERM=dumb BROWSER=/usr/bin/false [KIRO_API_KEY=<fake>] [KIRO_HOME=$H/kh] \
  timeout -s INT -k 5 60 sandbox-exec -f kiro.sb "/Applications/Kiro CLI.app/Contents/MacOS/kiro-cli" <args>
```

`$H` is a new empty directory under the scratchpad. `kiro.sb` allows everything except: reading or writing
`~/.kiro`, `~/.aws`, `~/.local/share/kiro-cli`, `~/Library/Application Support/kiro-cli`, `…/Kiro`, `~/Library/Caches/kiro-cli`,
`~/Library/Preferences/kiro-cli`; writing anywhere under the real home or `/Applications` (no auto-update); executing
`/usr/bin/open` and reaching LaunchServices (no browser). The CLI created its store at
`$H/home/Library/Application Support/kiro-cli/data.sqlite3` (it follows `HOME` on macOS; the `XDG_*` variables are not
used there). The fake key is `ksk_l4fakejudgeprobe…`: no real key was used and no model answered. `KIRO_LOG_LEVEL=trace`
was set for the transport and trust probes only; the trace log (`$TMPDIR/kiro-log/kiro-chat.log`) shows the outgoing
request.

### 2.2 Facts

Labels: [V] observed here, [D] Kiro's documentation only, [I] inferred, [U] not checked.

| # | Fact | Label |
|---|---|---|
| R1 | `kiro-cli --version` prints `kiro-cli 2.32.0` | [V] |
| R2 | `chat --help`: `--no-interactive`, `--agent`, `--model`, `--effort`, `-a/--trust-all-tools`, `--trust-tools <TOOL_NAMES>` (its text: "trust no tools: '--trust-tools='"), `--output-format text\|stream-json` ("stream-json implies --no-interactive"), `--require-mcp-startup` (exit 3), `--agent-engine v2\|v1\|v3` (default `v2`), `--v2` ("Use the V2 agent engine (the pre-3.0 default)"), `--v3`, `--mode`, `--list-models`, `-f/--format`, `--resume-id`. `agent --help`: `list`, `create`, `edit`, `validate --path`, `migrate`, `upgrade`, `set-default` | [V] |
| R3 | `whoami --format json` with no login: `{"account":null}`, exit 1 (`whoami`: `Not logged in`, exit 1). With `KIRO_API_KEY` set to any value: `{"accountType":"ApiKey","email":null}`, exit 0: presence, not validity | [V] |
| R4 | No login and no key: `chat --no-interactive …` and `/usage` start a browser login. Stdout gets only a spinner (`Opening browser... \| Press (^) + C to cancel`, ANSI codes, no JSON event); stderr `Failed to open browser for authentication.` / `Please try again with: kiro-cli login --use-device-flow` / `error: Failed to open URL`; exit 1 (the browser was denied by the sandbox; on a runner with no display it fails the same way [I]). `agent validate` and `agent list`: `error: You are not logged in, please log in with kiro-cli login`, exit 1 | [V] |
| R5 | `agent validate --path <the judge agent of D1>` (with the fake key): exit 0, no output | [V] |
| R6 | `KIRO_HOME=<dir>`: `agent list` shows `Global: <dir>/agents` and `Workspace: <cwd>/.kiro/agents` and lists the judge agent; the CLI writes `<dir>/settings/cli.json` (`{}` when new) and `<dir>/sessions/cli/<sessionId>.json` and `.jsonl` | [V] |
| R7 | The fake key, judge agent, prompt as argument: stdout `runStarted{payloadSchema:"acp", acpProtocolVersion:1, engine:"v2"}`, `metadata{sessionId, contextUsagePercentage:3.46…}`, `metadata{sessionId, turnDurationMs:446, reasoning:{support:"unavailable", effortLevels:[]}}`, `runError{sessionId, stage:"prompt", message:"Internal error (code -32603): Encountered an error in the response stream: The bearer token included in the request is invalid. (request_id: …)"}`; stderr empty; exit 1. The trace log has HTTP 403 `AccessDeniedException` | [V] |
| R8 | Stdin: with no positional argument, a piped prompt is the instruction. A three-line prompt reached the request whole, and so did a 155,225-byte prompt (the trace's user message is 157,010 characters with the CLI's wrapper and ends with the prompt's last line). The same stream as R7 follows. With `< /dev/null` and no argument: `runError{sessionId:null, stage:"input", message:"Input must be supplied when running in non-interactive mode"}`, stderr `error: Input must be supplied when running in non-interactive mode`, exit 1 | [V] |
| R9 | The request under the judge agent (`"tools": []`) carried `tools: None` and `tool_specs: None`, `environment_variables: []`, `model_id: "claude-sonnet-4.5"`. The CLI wraps the user message (`--- CONTEXT ENTRY BEGIN ---` current time `--- CONTEXT ENTRY END ---` `--- USER MESSAGE BEGIN ---` prompt `--- USER MESSAGE END ---`) and puts `The current model is claude-sonnet-4.5.` in the history. A session starts on `kiro_default` (12 tool specs, 6,868 tokens; the first `contextUsagePercentage` is computed for it) and switches to the named agent before the prompt is sent | [V trace] |
| R10 | Trust flags, from the agent snapshot in the trace (default agent): `--trust-tools=` → `allowed_tools: {""}`; `--trust-tools=read` → `{"read"}`; no flag → `{}`; `--trust-all-tools` → `trust_all_tools: true`. On 2.28.0 the empty list trusted every tool (C7 [V]); whether the empty name still does on 2.32.0 needs a model call | [V] / [U] |
| R11 | `<KIRO_HOME>/sessions/cli/<sessionId>.json`: `session_state.rts_model_state.model_info` = `{model_name, model_id: "claude-sonnet-4.5", context_window_tokens: 200000}` (the agent's model), `session_state.agent_name`, `permissions.trusted_tools: []` whatever the trust flag. It is the CLI's own selection, not a report of the server | [V] |
| R12 | `/usage` with the fake key: exit 0, stdout `Failed to retrieve usage information: AccessDeniedError [AccessDeniedException]: Invalid token`. `chat --list-models --format json` with it: exit 1, stderr `error: service error` | [V] |
| R13 | `settings list --all` lists `chat.disableInheritingDefaultResources` ("Disable inheriting default resources — global/workspace steering, skills, and project marker files like AGENTS.md — in custom (user-defined) agents (boolean, default: false)"), `chat.agentEngine` ("'v1', 'v2' (default), or 'v3'"), `chat.enableAutoAgentUpgrade`, `app.disableAutoupdates`, `chat.disabledModelFallbacks`, `memory.mode` ("requires the KAS engine") | [V] |
| R14 | Headless auth: `KIRO_API_KEY` ("only available for Kiro Pro, Pro+, Pro Max, and Power subscribers"); "When stdin is piped and no positional argument is given, Kiro reads the full stream as the instruction"; an active `kiro-cli login` session takes priority over the key | [D] kiro.dev/docs/cli/headless, /docs/getting-started/authentication |
| R15 | Exit codes 0 success, 1 failure ("auth error, invalid args, operation failed"), 3 MCP startup, 4 requested agent not found | [D] kiro.dev/docs/reference/exit-codes |
| R16 | "By default, custom agents inherit default resources (steering files, skills, and `AGENTS.md`)" unless `chat.disableInheritingDefaultResources`; "If the specified model is unavailable, the first prompt can fail instead of falling back automatically" | [D] kiro.dev/docs/custom-agents/configuration-reference |
| R17 | Models and multipliers: Auto 1.0, Claude Opus 5.5 2.0, Opus 5/4.8/4.7/4.6/4.5 2.2, Sonnet 5.5/5/4.6/4.5/4.0 1.3, Haiku 4.5 0.4, Fable 5.1 6 (enterprise preview), GPT-5.6 Sol 4.4 / Terra 2.2 / Luna 0.6, Kimi K3 2.4, GLM-5 0.5, DeepSeek 3.2 0.25, MiniMax M2.5 0.25 / M2.1 0.15, Qwen3 Coder Next 0.05. "In a local V3 session, Kiro can move a turn to another model when the current model declines the request or is unavailable. The transcript names the model that continued." | [D] kiro.dev/docs/cli/chat/model-selection; ids as C12 [V 2.28.0] |

Added on 2026-10-19 for the owner's decision "kiro-cli should work by default with auto" (D13 to D15). R18 and R21
come from a CI run with a real `KIRO_API_KEY` on kiro-cli 2.32.0 (GitHub-hosted ubuntu-24.04); the account e-mail it
printed is not recorded anywhere in this change.

| # | Fact | Label |
|---|---|---|
| R18 | `chat --list-models --format json` prints `{"models":[…]}`, each entry `{model_name, description, model_id, context_window_tokens, rate_multiplier, rate_unit}`; the first is `{"model_name":"auto","description":"Models chosen by task for optimal usage and consistent quality","model_id":"auto","context_window_tokens":1000000,"rate_multiplier":1.0,"rate_unit":"Credit"}`; the text list marks `* auto` as the default. 21 entries: `auto`; Experimental by description (`Experimental preview …`, `… Kiro Excluded Model`): `claude-opus-5.5`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `deepseek-3.2`, `minimax-m2.1`, `qwen3-coder-next`, `kimi-k3`; the 12 others: `claude-sonnet-5.5`, `claude-opus-5`, `claude-sonnet-5`, `claude-opus-4.8`, `claude-opus-4.7`, `claude-opus-4.6`, `claude-sonnet-4.6`, `claude-opus-4.5`, `claude-sonnet-4.5`, `claude-haiku-4.5`, `minimax-m2.5`, `glm-5`, whose makers are `anthropic`, `minimax`, `zhipu`. No status field was among the recorded fields; whether one exists is [U] (task 11.1) | [V] |
| R19 | Auto "may route requests to any Active model available to the user's Kiro profile", "including models outside the administrator's approved list", and "does not route to Experimental models"; paid tiers get "Claude Opus-class quality or better"; an administrator can block Auto. The docs do not say whether Kiro reports which model Auto used | [D] kiro.dev/docs/models/available-models |
| R20 | "Pass `--model <id>` to pin the model for a run": it takes precedence over the agent's `model` and `chat.defaultModel`. "If Kiro cannot set the requested model, it writes a warning to stderr and continues the run." The warning's wording is [U]. **Observed on 2.32.0 (task 11.1): a pinned id the account does not have (`claude-sonnet-9.9`) did not warn and continue; it failed the first prompt with a `runError` at stage `prompt`, so the hello failed and the profile was skipped like any failed hello. The wording of that `runError` message was not recorded (the hello kept the stage only); since the live-findings fix the hello keeps it, redacted and cut to 200 characters** | [D] kiro.dev/docs/cli/headless; [V] for the observed failure |
| R21 | `whoami --format json` with a real key: `{"accountType":"ApiKey","email":<the account's address>}`, exit 0. R3's `null` was the fake key; a real login carries the e-mail, which the probe never keeps (it keeps `logged_in` only). An `auth: api_key` profile with `KIRO_API_KEY` set passes the `auth` step on the variable and never runs `whoami` (`credential_auth`) | [V] |
| R22 | V3 becomes the default engine "with CLI 3.0 at the end of October". In a V3 session a fallback notice names "the model that continued" or "which model answered for this turn"; V2 has no model fallback (R17) | [D] kiro.dev changelog, /docs/cli/chat/model-selection |

A side effect to know: the first `--list-models` probe ran before the browser was blocked and showed `Opening
browser...`; it may have opened a Kiro sign-in page on the Mac. No login was completed. This is why the listing of D14
runs only after the login check has passed.

### 2.3 What needs a live key

Recorded later in CI by task 11: a successful judge reply on 2.32.0 (`runFinished.status`, `stopReason`, `finalText`,
`finalTextTruncated`, `meteringUsage` per call) and whether any event names the model that served it; that a 150 kB
judge prompt is answered end to end; that `"tools": []` gives no `tool_call` event; the cost of a judge call in
credits; the out-of-credits wording; throttling on 2.32.0; whether `settings/cli.json` under `KIRO_HOME` is read (it is
written there [V], read [I]); stdin on the runner's installed CLI version (C1: 2.27.1 and 2.28.0 there).

For `auto` (D13 to D15), also recorded by task 11.1: the session file's `model_info.model_id` after an `auto` run
(`auto`, or the model that served it) and after a pinned run; any fallback notice, its event or stream and its words;
the standard-error warning when a pinned model cannot be set, if it can be provoked (a model id the account does not
have); whether an agent file with `"model": "auto"` is accepted; whether `--list-models --format json` carries a
status field (Active, Experimental) besides the description; whether the listing costs credits.

### 2.4 Shapes recorded for the fixtures

Task 0 writes these files under `tests/fixtures/recorded/kiro-cli/2.32.0/` exactly (one JSON object per line):

- `auth-invalid-key.stream.jsonl` (R7):
  ```
  {"type":"runStarted","data":{"payloadSchema":"acp","acpProtocolVersion":1,"engine":"v2"}}
  {"type":"metadata","data":{"sessionId":"a6be2967-a9ad-431b-afdb-a25a07e114a0","contextUsagePercentage":3.4625000953674316}}
  {"type":"metadata","data":{"sessionId":"a6be2967-a9ad-431b-afdb-a25a07e114a0","turnDurationMs":446,"reasoning":{"support":"unavailable","effortLevels":[]}}}
  {"type":"runError","data":{"sessionId":"a6be2967-a9ad-431b-afdb-a25a07e114a0","stage":"prompt","message":"Internal error (code -32603): Encountered an error in the response stream: The bearer token included in the request is invalid. (request_id: cad1cd54-1257-4b38-b024-38c164742315)"}}
  ```
  with `auth-invalid-key.exit.txt` = `1`.
- `input-missing.stream.jsonl` (R8): `{"type":"runError","data":{"sessionId":null,"stage":"input","message":"Input must be supplied when running in non-interactive mode"}}`, `input-missing.exit.txt` = `1`.
- `no-login.stderr.txt` (R4): the three lines `Failed to open browser for authentication.`, `Please try again with:
  kiro-cli login --use-device-flow`, `error: Failed to open URL`; `no-login.stdout.txt`: the line
  `Opening browser... | Press (^) + C to cancel` (the spinner without its ANSI codes); `no-login.exit.txt` = `1`.
- `usage-invalid-key.stdout.txt` (R12): `Failed to retrieve usage information: AccessDeniedError [AccessDeniedException]: Invalid token`, exit 0.
- `whoami-api-key.stdout.txt` (R3): `{"accountType":"ApiKey","email":null}`, exit 0.
- `version.stdout.txt`: `kiro-cli 2.32.0`.
- `judge-agent.json`: the agent file of D1 for model `claude-sonnet-4.5` (it validated, R5).
- `judge-pass.stream.jsonl`: **synthetic until task 11** (README says so): the shape of
  `2.28.0/hello.stream.jsonl` whose `agent_message_chunk` texts and `finalText` are a valid `l4/judge-verdict@1` object
  for one criterion, preceded by the sentence `Here is my verdict:` (so the slicer is exercised), with one
  `meteringUsage` of `0.0512` credits and `finalTextTruncated:false`. Task 11 replaces it with the recorded stream
  and removes the word "synthetic".
- `README.txt`: how each file was made (§2.1, no key, an isolated home), and which are synthetic.
- `list-models.json` (R18; written with this amendment, not by task 0): **reconstructed** from the recorded run. The
  `auto` entry is the exact JSON; every other entry holds only what was recorded (`model_id`, `rate_multiplier`, and
  `description` where the record showed it, cut where the record was cut); `model_name`, `context_window_tokens` and
  `rate_unit` are left out, not guessed. README says so. Task 11.1 replaces it with the raw JSON of a recorded run.

## 3. Decisions

**D1. A tool-less harness agent, a private `KIRO_HOME`, no trust flag.** In judge mode `KiroCliAdapter.run` always
(whatever `options.agent` says) writes a fresh `KIRO_HOME` at `<step private dir>/kiro-home` (`KIRO_HOME_DIR`, removed
first) holding:
- `agents/l4-judge-<12 hex>.json` (`secrets.token_hex(6)`; a name nothing in the worktree can predict):
  ```json
  {"name": "<name>", "description": "L4 harness judge: no tools", "prompt": null, "mcpServers": {}, "tools": [],
   "toolAliases": {}, "allowedTools": [], "resources": [], "hooks": {}, "toolsSettings": {}, "includeMcpJson": false,
   "model": "<M>"}
  ```
  `<M>` is the profile's model, or `auto` when it has none (D13).
- `settings/cli.json`: `{"chat.disableInheritingDefaultResources": true, "chat.agentEngine": "v2",
  "chat.enableAutoAgentUpgrade": false, "app.disableAutoupdates": true}`.

The argv is exactly `[exe, "chat", "--no-interactive", "--v2", "--agent", <name>, "--model", <M>,
"--output-format", "stream-json"]`: no `--trust-tools` (any value), no `--trust-all-tools`, no
`--require-mcp-startup` (the agent has no server), no positional prompt (D2). `env` adds `KIRO_HOME`; it never carries
`KIRO_LOG_LEVEL` (a trace log holds the whole prompt, R8). The working directory stays `judge_workdir(req)` (empty).
`TRUST_TOOLS["judge"]` is removed, so no code path can build a judge trust list. A profile without a model is not
refused: it runs `auto` (D13), whose vendor is routed (D14) and whose served model is checked when Kiro names it
(D15). (Before the owner's decision of 2026-10-19 this paragraph refused it.)

Why: with `"tools": []` the request carries no tool specification (R9), so the model has nothing to call and no
permission decision can arise; the empty trust set of "no flag" (R10) is a second wall; the private `KIRO_HOME` keeps
`~/.kiro` (MCP servers, skills, global steering, `permissions.yaml`, C9) out (R6); the setting turns off the steering,
skills and `AGENTS.md` that a custom agent inherits (R13, R16; the empty cwd already has none); `--v2` and
`chat.agentEngine` pin the engine whose format the agent file uses and which has no model fallback (R17 names V3 for
fallback). Setting `model` in both the agent file and `--model` makes their precedence irrelevant.

**D2. The prompt on stdin.** Judge mode passes the prompt as `stdin` to `ProcRunner.run` (the prompt then EOF) and no
positional argument; `MAX_ARG_BYTES` does not apply to it. R8 shows a 155 kB prompt sent whole. An empty prompt is
refused before the spawn (the CLI would answer `stage: "input"`). The implementer and read-only modes keep the argv
transport (K18 stays open; their prompts are capped by the context budget).

**D3. The reply contract.** `schema_mode` stays `prompt_contract`, so `AgentJudge` appends `schema_suffix` (the
instruction "Do not call any tool … Reply with a single JSON object …" and the compact schema). `KiroCliAdapter.parse`
gets `judge: bool` and, for a judge run that exited 0 with `runFinished.status == "success"`:
1. The reply text is `runFinished.finalText` when `finalTextTruncated` is not true, else the joined
   `agent_message_chunk` text of the run (a tool-less run never clears it).
2. The shared helper `attach_judge_reply(result, text, schema)` in `src/l4/agents/contract.py` (moved from
   `OpenCodeAdapter._attach_judge_reply`, same messages) slices from the first `{` to the last `}`, parses, validates,
   and sets `structured` and `ok`, or `detail = STRUCTURED_DETAIL + " missing: …"`, or `… invalid: …` with `rejected`.
   opencode calls the same helper; its behaviour and messages do not change.
3. A `runFinished.stopReason` other than `end_turn` with no usable object puts the stop reason in the detail
   (`… missing: the reply stopped at max_tokens`), so the repair path is taken, not "cannot run".
4. Never a verdict: any `sessionUpdate` `tool_call` in a judge run (`error`, `kiro-cli judge called a tool (<toolName>)`);
   any `runStarted` whose `engine` is not `v2`, or that names none (`error`, `kiro-cli ran engine <x>; a judge runs
   v2`, with the first such engine or `unknown`); any `runError`, whatever follows it (`error`, `kiro-cli judge run
   reported a runError (<stage>)`); for a pinned model, the
   session file of R11 (`<KIRO_HOME>/sessions/cli/<sessionId>.json`, a regular file of at most 1 MiB) naming a
   concrete `model_id` that is not the profile's model under `normalise_model` (`error`, `model_mismatch: kiro-cli
   selected <id>, the profile names <m>`), or the standard-error warning of R20 (D15; a second guard, see D15). For a pinned model a missing or
   unreadable session file with no warning records nothing and blocks nothing (it is the CLI's internal state).
   Under `auto` the session file gives the served model instead (D15).

The rest is the existing path: `AgentJudge` maps a `STRUCTURED_DETAIL` detail to `schema_invalid`, `run_judge` tries
`judge_repair` and then one repair call (`MAX_CALLS = 2`), the verdict model has the last word. The served model
(`model_resolved`), the seat's expected model and the `model_mismatch` status are D15's.

**D4. Credits.** `StructuredResult.usage` already carries `Usage.credits`. `JudgeRun` gets `credits: float | None`
(summed over its calls like `cost_usd`). `_ask_judges` adds `credits` to `verify.judge` when set and writes
`budget.cost{credits: round(c, 6), credits_source: "kiro.stream", profile, role: "judge"}`; `ClarifierReply` gets
`credits` and the clarifier writes the same event with `role: "clarifier"`. `fold` keeps summing `usd` only, and
`eval/score.py` keeps reading `usd` only: credits are plan credits, never dollars.

**D5. The vendor of a kiro-cli profile is its model's family.** One table `MODEL_FAMILIES` in
`src/l4/availability/vendor.py`, matched on the lowercased model id after its last `/`:

| Prefix | Vendor |
|---|---|
| `claude-` (also `anthropic.claude-`, `<region>.anthropic.claude-`) | `anthropic` |
| `gpt-`, `o<digit>` | `openai` |
| `gemini-` | `google` |
| `deepseek-` | `deepseek` |
| `glm-` | `zhipu` |
| `minimax-` | `minimax` |
| `qwen` | `alibaba` |
| `kimi-` | `moonshot` |

`served_vendor` uses the same table. `resolve_vendor` for `adapter: kiro-cli`: no model or `auto` → provenance
`routed` with no single vendor, whatever `vendor:` says (its vendors are the possible set of D14; wave 1 made it
`(unknown, unknown)`, task 1.3 reworks that); a model of a known family → `(<family vendor>, declared)`; any other
model → the declared vendor as today. Provenance stays `declared` for a pinned model, whatever its session file says
(D15: that file only detects a mismatch): the verdict then says `declared (unverified)`. A `vendor:` on an `auto` profile loads (the model-family
validator already returns for `auto` and for no model, `family_vendor` being None) and is ignored; CFG-011 notes it
(D9). No schema change is needed for that. `Profile` gains a validator mirroring `_vendor_of_the_tool`: a kiro-cli profile whose
`vendor:` is set and differs from its model family's vendor fails to load with `vendor contradicts the model: <model>
is made by <vendor>` (the vendor `amazon` or `aws` is not a family: Kiro hosts the models, it does not make them). Under
`verifier.independence: different_model`, `normalise_model` also folds a `.` between digits to `-`
(`claude-sonnet-4.5` ≡ `claude-sonnet-4-5` ≡ `claude-sonnet-4-5-20250929`), and both `independence_constraint` and
`Independence.independent` compare normalised models.

Effect: a kiro judge on `claude-sonnet-4.5` is not independent of a claude-code implementer (both `anthropic`), and is
independent of a kiro implementer on `qwen3-coder-next` (`alibaba`), `declared (unverified)`. A kiro judge on `auto`
is independent of a DeepSeek implementer and not of a GLM, MiniMax or Claude one (D14). Scoped to kiro-cli: opencode
keeps its declared vendor (owner question 2).

**D6. Failure classes.** `parse` (all modes) and the hello read one Kiro auth rule: a `runError` message matching
`bearer token .* invalid|invalid token|AccessDenied|not logged in|kiro-cli login|token .*expired|unauthori[sz]ed`, or
an exit 1 with no stream event whose stdout or stderr says `for authentication` or `kiro-cli login` (R4), is status
`auth` with the detail `kiro-cli could not authenticate (the login or KIRO_API_KEY is missing, expired or rejected)`.
`AgentJudge` turns `auth` into `limit`, `run_judge` raises `RoleLimit`, and `Factory.on_limit` cools the profile (kind
`auth`) and selects the next judge. Exit 4 or a `runError` at stage `init` (the harness agent was not found) and a
`runError` at stage `input` stay `error`, with the stage in the detail. The credits and throttle rules are unchanged
(throttle before credits before auth). `kiro_quota`: an exit-0 `/usage` text that says `Failed to retrieve usage
information` with the auth rule matching fails the quota step with `reason: "kiro-cli usage: authentication failed"`
and `failure_class` `auth` instead of `quota_unrecognised` (R12).

**D7. The hello is the judge invocation.** `probe_kiro` hello, for every kiro-cli profile: a temporary directory under
`ctx.cwd` (`l4-kiro-probe-`) holding an empty `cwd/` and a `kiro-home/` written as in D1 (agent and settings), the argv
of D1 with the hello prompt appended as its last argument, `KIRO_HOME` in the probe env. The hello keeps the argument
because the probe runner (`ProbeCtx.run`, type `Runner`, and `_timed`) takes no stdin, and widening that protocol would
touch every adapter's probe fakes; the 25-byte prompt needs no stdin, and R8 shows that the argument and stdin reach the
same `prompt` stage, so the hello still proves the agent, the login and the model. Stdin itself is proven for the
judge by task 11. The reply is the D3 text (`finalText`); `_hello_verdict`
decides; a `runError` is classified by D6 (auth → `failure_class` `auth`), throttle and credits as now. A profile
without a model gets `"model": "auto"` in the agent file and `--model auto` (D13). Cost: one tool-less turn (C11:
0.0105 credits on `qwen3-coder-next` with a 3-tool agent). The model listing of an `auto` profile is not part of the
hello: it runs in the `auth` step (D14).

**D8. Roles.** `JUDGE_ADAPTERS` becomes `("claude-code", "codex", "opencode", "kiro-cli", "fake")`. Since 0.4.18 the
tuple lives in `l4/config/roles.py` (L4-CFG-006, a leaf module that `agent_judge.py` and the schema's load check both
read), and the skill's `scripts/yolo_preflight.py` holds a copy that a test keeps equal; both gain `kiro-cli`, for all
four judge roles (no per-role list: an adapter profile in `roles.s1_judge` is only ever the stand-in). With it, without
further code: `roles.judges` (step 9 and the plan-readiness review), `roles.clarifier`, the `s1_judge` stand-in, the
escalation keeper and the step-9 preflight accept a kiro-cli profile. The clarifier uses the same contract (a schema,
one document, a validated object), so it is in scope; it has no independence rule, nor have the readiness review
(`yolo/readiness.py`: no implementer to be independent of) and the `s1_judge` stand-in (`open_role_judge` passes no
constraint), so `auto` serves them as it is and D14's veto does not reach them. The
delegate is out of scope: it runs `read_only` with file tools, and whether a custom agent's `allowedTools` grants
trust headless is still [U] (C8); a later change can add it.

**D9. Doctor CFG-011 "kiro-cli judge profiles"** (scope config, severity warn: since the owner's decision nothing in it
is an error). For each kiro-cli profile in `roles.judges` or `roles.clarifier`: `options.agent` set is a warning (`a
judge always runs the harness's tool-less agent; options.agent is ignored here`), and `min_version` unset or below
`2.32.0` is a warning (`the judge invocation was measured on kiro-cli 2.32.0`). A warning-only result is `fail` with
severity warn. Each such profile gets one line in the message:
- pinned: `<p>: tool-less harness agent, prompt on stdin, no trust flag, model <m> (<vendor>)`;
- no model or `auto`: `<p>: tool-less harness agent, prompt on stdin, no trust flag, model auto, routed to <vendors>
  (<source>); a pinned model makes the served model checkable`, where `<source>` is `listed <YYYY-MM-DD>` (the latest
  set recorded by the profile's probe, read from the availability cache through the lookup of D14) or `built-in` (no
  recorded set: the 2026-10-19 list).
For every kiro-cli profile that any role names, a `vendor:` on a profile with no model or `auto` adds the note `<p>:
vendor <v> is ignored: auto is routed (set model to pin a vendor)` to the message without failing the check. No new
live check: `LIVE-001` runs the judges' probe ladder under `--live`, whose `auth` step lists the models of an `auto`
profile (D14) and whose hello is now the judge invocation (D7); `LIVE-005` warns until the 2.32.0 fixtures are
recorded (task 0 adds the directory).

**D10. Replay.** Task 0's fixtures drive the adapter tests. The simulation gets a judge replayed through the real
adapter: `JudgeScript` gains `replay: {adapter: kiro-cli, stream: "@fixture:<file>"}` (exclusive with `verdict`),
which makes the scenario's judge profile `adapter: kiro-cli` with no model (so `auto`, D13; the simulation records no
model listing, so the built-in set of D14 applies, and the simulated implementers' vendor is outside it) and runs
`KiroCliAdapter` with a `ReplayProc` (a `ProcRunner` stand-in in `l4.sim` that records the argv, env, cwd and stdin
and writes the named stream to `stdout_path`, exit 0; it writes no session file, so no served model is reported).
Scenario `happy-kiro-judge`: `happy-kiro` with that judge and a `judge-pass` stream; it expects `verify.verdict PASS`,
`verify.judge{profile, credits}`, `budget.cost{credits, role: judge}` and an `availability.model_unverified` event for
the judge.

**D11. Live proof.** On the owner's dummy repository (never a consumer), in CI, with its `KIRO_API_KEY` secret. The
implementer is not Anthropic: an opencode-go DeepSeek profile (`opencode-go/deepseek-*`) that declares `vendor:
deepseek` (an undeclared vendor is unknown and vetoes every judge). Two legs, each with `l4 doctor --live` first
(CFG-011 pass, LIVE-001: the `auth` step and its listing, the hello through the judge invocation):
- **auto**: `roles.judges: [kiro-auto]`, `{adapter: kiro-cli, auth: api_key, min_version: "2.32.0"}` with no model;
- **pinned**: `roles.judges: [kiro-sonnet]`, `{adapter: kiro-cli, auth: api_key, model: claude-sonnet-5.5, vendor:
  anthropic, min_version: "2.32.0"}` (the owner asked for Sonnet 5.5 at least).
Each leg reaches a verdict; the evidence under `docs/live/kiro-judge/` holds, per leg, the raw judge stream (redacted),
the `verify.judge` and `budget.cost` events, the independence line, the CLI version, the session file's `model_id`,
any fallback notice, any standard-error warning about the model, and the answers to §2.3; the raw listing replaces the
reconstructed `list-models.json`. The CI job never runs `kiro-cli whoami` and never prints account data: with `auth:
api_key` and the key set, the `auth` step passes on the variable (R21). A negative leg: the same unit with a
claude-code implementer shows `no independent verifier` for both kiro judges (no judge call); for `auto` because
`anthropic` is among its possible vendors.

**D12. Docs.** SPEC: §8.1 ("CLI judge" lists kiro-cli and the prompt-contract path), §8.3 (the kiro-cli row: the judge
argv, stdin, the reply, R-facts; the HB-X1 row "`kiro-cli` judge, reader" filled for the judge), §10.1 (vendor by
model family for kiro-cli, `auto` routed with its possible vendors and the `routed (unverified)` status, the served
model of a Kiro run, model normalisation), §15 doctor table (CFG-011), §12 ledger events (`verify.judge.credits`,
`budget.cost` with role judge or clarifier, the routed party in the independence record), the new requirements
L4-KJD-001..015 with their scenarios SCN-KJD-01..41 in §23 (a new subsection `23.x Kiro judge (KJD)`), and the change
table row 50 in §21. The runbook: a kiro-cli judge in the profile reference (no model runs `auto`), the CFG-011 lines,
"a Kiro judge on a Claude model, or on `auto`, is not independent of a Claude implementer", and "pin a model to make the
served model checkable". The skill: `references/adopt.md` (a kiro judge profile example and the vendor rule) and
`references/kiro.md` (Kiro as a judge, `auto` by default). CHANGELOG `## 0.4.19 (unreleased)`: Added, Changed (the
behaviour changes of the proposal with their fixes), Fixed (auth classification).

**D13. `auto` by default** (owner decision 2026-10-19: "kiro-cli should work by default with auto"). Every kiro-cli
invocation passes a model: the profile's, or `auto` when it has none; a `model` of `auto` in any letter case is passed
as `auto`. This holds for the judge (D1: agent file and `--model`), the clarifier and the readiness review (the same
judge invocation), the hello (D7), the implementer (`build_command` adds `--model auto`; the harness agent file of K3
keeps `"model": null`, `--model` decides, R20) and the read-only mode. An implementer profile with `options.agent` and
no model now runs `--model auto`, which overrides a model named in that agent file (R20): to keep that model, name it
in the profile (CHANGELOG). Why explicit: the profile's view and the run agree, so the vendor rule (D14) is about the
model that actually runs and not about whatever `chat.defaultModel` or an agent file says.

**D14. The possible vendors of `auto`.** Auto routes to "any Active model available to the user's Kiro profile" and
never to an Experimental one (R19). So:
- **The listing.** In `probe_kiro`, the `auth` step of a profile on `auto`, after the login check passes (`whoami`, or
  `credential_auth` on the credential variable), runs `kiro-cli chat --list-models --format json` with the probe env in
  `ctx.cwd`, a private `KIRO_HOME` holding only the judge's `settings/cli.json` (the login stays in the CLI data
  store, which `KIRO_HOME` does not move, as for the judge and the hello) and the step timeout of 0.4.18
  (`availability.probe_step_timeout`, L4-AVL-012; a timeout records the built-in set), and adds `routed` to that
  step's detail: `{"source": "listed", "vendors": [...],
  "models": [...]}` (sorted; `models` are the normalised Active ids). Both lists are the union of the listing's and the
  built-in set's (owner's decision of 2026-10-19), so a vendor Kiro dropped from Active, or a restricted listing, never
  shrinks the set. A failed listing (exit not 0, timeout, not a JSON
  object with a `models` list, no Active entry) adds `{"source": "built-in", "vendors": …, "models": …, "reason":
  "kiro-cli chat --list-models failed (<exit or why>)"}` and the step still passes. The detail is derived data, never
  raw output, so it may be cached (`ProbeResult.detail` rule). It is the `auth` rung and not a new ladder step because
  `ProbeStep` is a fixed four-name literal, `ProbeLadder.run` skips any other name as not built, and
  `availability.default_ladder` is configurable: a new rung would touch every adapter's probe and could be left out
  of a configured ladder, while the `auth` rung always runs and is cached with the ladder report (`cache_ttl`). A
  pinned profile is never listed. `_step_text` shows `auth <method> · auto: <vendors> (<source>)` so that `l4 probe`
  says which set counts.
- **Active and Experimental.** An entry whose `model_id` is `auto` is skipped. An entry is Experimental when its
  `description` contains `experimental`, `preview` or `excluded model` (case-insensitive); every other entry is
  Active, including one with no description (a missing description adds a vendor, never removes one). The possible
  vendors are `family_vendor` of each Active id; an Active id of no known family adds `unknown`, which makes the
  profile never independent (the existing rule for an unknown vendor).
- **The built-in set** (`vendor.py`, `ROUTED_DEFAULT`): vendors `anthropic`, `minimax`, `zhipu` and the 12 normalised
  Active ids of R18, from the 2026-10-19 list; a unit test computes it from `list-models.json` and compares.
- **The lookup.** A routed profile's set is the one recorded by its latest probe, whatever its age, else the built-in
  set: `Factory.routed(name, profile)` reads the profile's cached ladder report from the availability store with no age
  limit. `independence_constraint`, `independence_keeper` and `assess_independence` take this lookup (the callers that
  have a factory pass it: `select_judge`, the keeper of the escalation, the ladder's preflight and `_ask_judges`);
  without one they use the built-in set. CFG-011 reads it the same way.
- **Selection order.** `FallbackSelector.select` applies the constraints before it probes (`_veto` before `_probe`),
  so the walk may check a judge against an older set or the built-in one. `select_judge` therefore checks a selected
  routed judge again against the `routed` detail of its own probe results (`Selected.probes["auth"]`, fresh or cached)
  and, when that set vetoes it, adds it to `skip` and selects again. A judge is never called on a set its own probe
  contradicts.
- **The rule.** Each party has a set of vendors: a routed party its possible vendors, any other party its one vendor
  (`{unknown}` when none is known). Under `different_vendor` a judge is vetoed when its set meets any implementer's
  set, or either holds `unknown`: `judge profile <j> and implementer profile <i> share the vendor` or `… has no known
  vendor`, as today. Under `different_model`, when the judge or an implementer is routed, the judge is vetoed when the
  other party's model, normalised and taken after its last `/`, is among the routed party's `models`, when the other
  party's vendor is unknown, or when both are routed (`share the model`; the routed side's missing model is not "no
  known model"); with no routed party the rule is today's. Two `auto` profiles are never independent.
- **The record.** `Provenance` gains `routed`. `Party` gains `vendors: tuple[str, ...]` (empty for a party that is
  not routed); `Party.text()` of a routed party is `<profile> routed: <vendors joined by ", "> (auto)`, e.g.
  `kiro-judge routed: anthropic, minimax, zhipu (auto)`; `to_json` adds `vendors`. `Independence.verified` is false
  when any party is `declared` or `routed`; `status` is `not independent (<mode>)` when the judge is not independent,
  else `routed (unverified)` when any party is routed, else `declared (unverified)` when any is declared, else
  `verified (<mode>)`. `resolve_vendor` gives a routed profile `(None, "routed")`; `Selected.vendor` is then None and
  `Selected.provenance` `routed`.
- **Scope.** The step-9 judges, `roles.verifier_agent`, the escalation keeper and the step-9 preflight: wherever
  `independence_constraint` applies. Not the clarifier, the readiness review or the `s1_judge` stand-in (D8).

**D15. The served model of a Kiro run.** In judge mode `parse` reads the session file of R11 (as D3 step 4, with
`l4.fsutil.read_regular_file`, at most 1 MiB) and takes `session_state.rts_model_state.model_info.model_id` when it is
a non-empty string other than `auto`:
- **Profile on `auto`.** The id is the served model: `RunResult.model_resolved = <id>`. `KiroCliAdapter.capabilities()`
  sets `served_model=True` (the run may report it), so `seat_of` gives `reports_served` and `_ask_judges` applies its
  existing check: `assess_independence(…, served_model=<id>)`; a served vendor that is an implementer's, or unknown,
  turns the result into `model_mismatch` (`served <id>: vendor <v> is not independent`), writes
  `availability.model_mismatch`, skips and cools the profile (kind `model_mismatch`) and asks the next independent
  judge (SCN-AVL-15's path). An independent served model makes the judge's provenance `served` and the line
  `<profile> <vendor> (served <id>)`. A session file naming `auto`, or none, reports nothing: the judge stays routed.
- **Pinned model.** `seat_of` sets `expect_model` to the pinned model for a kiro-cli profile (any id other than
  `auto`; today only a full Claude id counts). A session file naming another model is the D3 step-4 `error` with
  `model_resolved` set to that id, which `run_judge` turns into `model_mismatch` (`requested <m>, served <id>`). A
  standard-error line of the run that says the model could not be set (R20; until its wording is recorded, a line that
  mentions `model` together with `warn`, `could not`, `cannot`, `can't`, `unable`, `unavailable`, `not available`,
  `failed` or `fall`, case-insensitive) is `error` with the detail `model_mismatch: kiro-cli could not set <m>` and no
  `structured`; `run_judge` turns an `error` whose detail starts with `model_mismatch:` into `model_mismatch` with no
  verdict, so the ladder takes the same path.
  **What the live run saw (task 11.1, 2.32.0):** a pinned id the account does not have fails the prompt (`runError` at
  stage `prompt`) and writes no standard-error warning. That is a failed hello, so the profile is skipped like any
  other (the hello keeps the redacted, 200-character `runError` message in its reason, L4-KJD-007); in a judge call it
  is the `runError` rule above. The warning check stays as a second guard, since Kiro may warn and continue for a
  model it can set but not use, or under a different engine.
  A session file naming the pinned model reports nothing
  (`model_resolved` stays None) and the judge keeps provenance `declared`: the owner's decision of 2026-10-20 (review
  finding 3) is that this file is the CLI's own selection (R11), an echo of the configuration, not a server report, so
  it serves only to detect a mismatch. `seat_of` gives a pinned kiro-cli profile `reports_served=False` as well, so a
  served model is never believed for the provenance of a pinned Kiro judge (§5). No session file and no warning:
  nothing is reported and nothing is blocked.
- **Fallback notices** (R22) are V3's, and the judge pins `--v2`, so none is expected; no notice is parsed until task
  11.1 or a later recording shows one. If one is seen, task 11.1 stops and this design is amended before any code.
- **Files.** `src/l4/agents/kiro_cli.py` (`parse` reads the session file and the stderr text that `run` passes;
  `capabilities`), `src/l4/verifier/selection.py` (`seat_of`), `src/l4/verifier/judge.py` (`run_judge`: the
  `model_mismatch:` detail). `ladder.py` is unchanged: its served-model check and its mismatch path already exist.
  Implementer and read-only runs report no served model (out of scope).

## 4. Files

| File | Change |
|---|---|
| `src/l4/agents/kiro_cli.py` | judge agent and settings writer, judge argv, stdin, `parse(judge=…)`, the auth rule, hello; `--model auto` by default (D13); the model listing in the `auth` step (D14); the served model from the session file, the stderr warning, `served_model=True` (D15) |
| `src/l4/agents/factory.py` | `Factory.routed(name, profile)`: the latest recorded set, else the built-in one (D14) |
| `src/l4/availability/fallback.py` | `_step_text`: the `auth` text names the `auto` set and its source (D14) |
| `src/l4/agents/contract.py` | `attach_judge_reply` (moved from opencode) |
| `src/l4/agents/opencode.py` | calls `attach_judge_reply` |
| `src/l4/availability/vendor.py` | `MODEL_FAMILIES`, kiro-cli rule in `resolve_vendor`; `normalise_model` and `same_model` move here (an adapter must not import `l4.verifier`: `selection` imports `agent_judge`, which imports the adapters); `routed` provenance, the Active/Experimental rule, `ROUTED_DEFAULT` (D14) |
| `src/l4/config/schema.py` | `Profile` validator: kiro-cli vendor against the model family |
| `src/l4/verifier/selection.py` | imports `normalise_model` (now with dot folding); model comparison through it; vendor sets, the routed rule, `Party.vendors`, the `routed (unverified)` status, the re-check in `select_judge` (D14); `seat_of` for a pinned kiro-cli model (D15) |
| `src/l4/availability/quota.py` | `/usage` auth text |
| `src/l4/llm/agent_judge.py` | `JUDGE_ADAPTERS` |
| `src/l4/verifier/judge.py`, `src/l4/verifier/ladder.py` | `JudgeRun.credits`, events; `run_judge` maps a `model_mismatch:` detail to `model_mismatch` (D15); the ladder passes the routed lookup (D14) |
| `src/l4/clarifier/backend.py`, `src/l4/clarifier/clarifier.py` | `ClarifierReply.credits`, event |
| `src/l4/doctor/checks_config.py` | CFG-011 |
| `src/l4/sim/scenarios.py`, `src/l4/sim/fakes.py` (or a new `src/l4/sim/replay.py`), `src/l4/sim/builtin/scenarios/happy-kiro-judge.yaml`, the manifest | replay judge |
| `tests/fixtures/recorded/kiro-cli/2.32.0/`, `src/l4/recorded_versions.json` | fixtures (generated list); `list-models.json` (reconstructed, §2.4) |

## 5. Risks and residuals

- **The served model is only what the CLI writes down.** Independence rests on the configured model (D5), the possible
  set of `auto` (D14) and the session file (D15). If Kiro routed a pinned model elsewhere server-side, nothing would
  show it; `--v2` avoids the documented V3 fallback (R17, R22). A session file that names the pinned model is not
  taken as served: it is the CLI's record of its own selection (R11), an echo of the configuration, so a pinned Kiro
  judge stays `declared` and the file only detects a mismatch (owner's decision, review finding 3). Under `auto` the
  same file is the only per-call report of the routed model, and it makes the judge `served` (D15).
  `availability.model_unverified` is logged for every kiro-cli selection (existing).
- **`auto` may answer from outside the listing.** The docs say Auto may route to "models outside the administrator's
  approved list" (R19), while the listing shows what the user's profile has: for an organisation that restricts its
  list, the possible set may miss a vendor [U]. A session file that names the served model closes that gap per call;
  one that only says `auto` does not. The built-in set is the 2026-10-19 list and ages: a vendor added to Active later
  is missed whenever the listing fails. Owner question 5.
- **The listed set ages too.** The walk uses the latest recorded set whatever its age, and so does an implementer's
  set; the selected judge is checked again against its own probe (D14), but an implementer's set is only as fresh as
  that implementer's last probe in this availability cache.
- **Auto blocked by an administrator** (R19): `--model auto` then gets the warning of R20 and Kiro continues on some
  model [U]. Under `auto` the warning does not end the run (every Active model is in the possible set), but a model
  outside it would be missed; not observable with a personal key.
- **The CLI's internal session file** (D3 step 4, D15) may change shape; it is read fail-open (absent: no check) and
  fail-closed only on a contradiction or, under `auto`, on a served vendor that is not independent.
- **The stderr warning's wording** (R20) is still unknown: task 11.1 saw a `runError` instead of a warning for a model
  the account does not have, so the pattern stayed unexercised. D15's pattern fails closed (a false match drops one
  verdict and asks the next judge) and is replaced by the recorded wording when a run produces one.
- **Older CLIs.** Stdin, `--v2` and the settings keys were measured on 2.32.0 only; the runner had 2.27.1 and 2.28.0
  (C1). CFG-011 warns without `min_version: "2.32.0"`; task 11 confirms the runner's version.
- **The vendor rule is a breaking load error** for a kiro-cli profile whose `vendor:` contradicts its model (for
  example `vendor: amazon` on a Claude model). It is the claude-code and codex precedent and fails closed; the
  CHANGELOG gives the fix.
- **The implementer harness agent** (K3) inherits default resources too (R16) and runs from a private `KIRO_HOME` with
  an empty `settings/`: in the sandbox the worktree's `.kiro/steering` is masked, without the sandbox it is not. Out of
  scope here; noted for a later change.
- **A Claude model judging a Claude implementer** is refused by D5, which is the point; a team with only Kiro must pick
  a non-Anthropic judge model (GPT, DeepSeek, GLM, Qwen, Kimi) or a non-Anthropic implementer model. With `auto` on
  both sides (the default for a Kiro-only team) no judge is independent (D14): one side must pin a model of a vendor
  outside the other's possible set.

## 6. Owner questions

1. **Vendor contradiction: load error or warning?** D5 makes it a load error (exit 3) as for claude-code and codex.
   Recommendation: keep the load error; it fails closed and the message names the fix.
2. **Extend the model-family rule to opencode?** An opencode profile `openrouter/anthropic/claude-…` with a declared
   `vendor: openrouter` has the same hole. Recommendation: not in 0.4.19; a later change with a doctor warning first,
   then the load error.
3. **Should the hello of every kiro-cli profile, implementers included, use the tool-less judge agent (D7)?**
   Recommendation: yes; it is cheaper, does not start the user's MCP servers, and only proves the login and the model.
4. **The live leg's judge model** (D11). Decided 2026-10-19: two legs, `auto` (the default) and `claude-sonnet-5.5`
   (the owner asked for Sonnet 5.5 at least), on an opencode-go DeepSeek implementer; the negative leg stays.
5. **Union with the built-in set?** Decided 2026-10-19 by the owner: yes. D14 takes the union of the listing's
   Active vendors and models with the built-in set, so a vendor Kiro removed from Active never drops out and a
   restricted listing (§5) cannot shrink the set; the built-in set alone is used only when the listing fails.

Decision record: 2026-10-19, the owner: "kiro-cli should work by default with auto". D13 to D15 and the changes they
make to D1, D3, D5, D7, D9 and D11 follow from it.

## 7. Open items

- **kiro-cli 3.0** (end of October, R22) makes V3 the default engine. This change pins `--v2` and
  `chat.agentEngine: "v2"`, and a judge run that reports another engine is an `error` (D3 step 4). Before the
  recorded version or a profile's `min_version` moves to 3.x: re-record the 2.32.0 shapes of §2.4 against 3.0 (the
  stream, the session file, `--list-models`, whether `--v2` is still accepted), and decide whether V3's fallback
  notices (R22) become a served-model source (D15).
