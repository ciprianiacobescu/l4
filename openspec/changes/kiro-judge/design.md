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
  CFG-010 are used, CFG-011 is free here and in the delegate worktree.
- **The delegate** (`delegate-answers`, 0.4.19): `read_only` mode, `serves=("claude-code", "codex", "fake")`.

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

A side effect to know: the first `--list-models` probe ran before the browser was blocked and showed `Opening
browser...`; it may have opened a Kiro sign-in page on the Mac. No login was completed.

### 2.3 What needs a live key

Recorded later in CI by task 11: a successful judge reply on 2.32.0 (`runFinished.status`, `stopReason`, `finalText`,
`finalTextTruncated`, `meteringUsage` per call) and whether any event names the model that served it; that a 150 kB
judge prompt is answered end to end; that `"tools": []` gives no `tool_call` event; the cost of a judge call in
credits; the out-of-credits wording; throttling on 2.32.0; whether `settings/cli.json` under `KIRO_HOME` is read (it is
written there [V], read [I]); stdin on the runner's installed CLI version (C1: 2.27.1 and 2.28.0 there).

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

## 3. Decisions

**D1. A tool-less harness agent, a private `KIRO_HOME`, no trust flag.** In judge mode `KiroCliAdapter.run` always
(whatever `options.agent` says) writes a fresh `KIRO_HOME` at `<step private dir>/kiro-home` (`KIRO_HOME_DIR`, removed
first) holding:
- `agents/l4-judge-<12 hex>.json` (`secrets.token_hex(6)`; a name nothing in the worktree can predict):
  ```json
  {"name": "<name>", "description": "L4 harness judge: no tools", "prompt": null, "mcpServers": {}, "tools": [],
   "toolAliases": {}, "allowedTools": [], "resources": [], "hooks": {}, "toolsSettings": {}, "includeMcpJson": false,
   "model": "<profile.model>"}
  ```
- `settings/cli.json`: `{"chat.disableInheritingDefaultResources": true, "chat.agentEngine": "v2",
  "chat.enableAutoAgentUpgrade": false, "app.disableAutoupdates": true}`.

The argv is exactly `[exe, "chat", "--no-interactive", "--v2", "--agent", <name>, "--model", <profile.model>,
"--output-format", "stream-json"]`: no `--trust-tools` (any value), no `--trust-all-tools`, no
`--require-mcp-startup` (the agent has no server), no positional prompt (D2). `env` adds `KIRO_HOME`; it never carries
`KIRO_LOG_LEVEL` (a trace log holds the whole prompt, R8). The working directory stays `judge_workdir(req)` (empty).
`TRUST_TOOLS["judge"]` is removed, so no code path can build a judge trust list. A profile without a model is refused
before the spawn (`AdapterError("a kiro-cli judge needs a model …")`): `auto` would let Kiro pick the vendor.

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
   `runStarted.engine` other than `v2` (`error`, `kiro-cli ran engine <x>; a judge runs v2`); the session file of R11
   (`<KIRO_HOME>/sessions/cli/<sessionId>.json`, a regular file of at most 1 MiB) naming a `model_id` that is not the
   profile's model under `normalise_model` (`error`, `model_mismatch: kiro-cli selected <id>, the profile names <m>`).
   A missing or unreadable session file records nothing and blocks nothing (it is the CLI's internal state).

The rest is the existing path: `AgentJudge` maps a `STRUCTURED_DETAIL` detail to `schema_invalid`, `run_judge` tries
`judge_repair` and then one repair call (`MAX_CALLS = 2`), the verdict model has the last word. `model_resolved` stays
`None` and `served_model` stays `False`: Kiro reports no served model, so `expect_model` is never set and the judge's
provenance is never `served`.

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

`served_vendor` uses the same table. `resolve_vendor` for `adapter: kiro-cli`: no model or `auto` → `(unknown,
unknown)` whatever `vendor:` says; a model of a known family → `(<family vendor>, declared)`; any other model → the
declared vendor as today. Provenance stays `declared`: the vendor is not reported by any server, so the verdict says
`declared (unverified)`. `Profile` gains a validator mirroring `_vendor_of_the_tool`: a kiro-cli profile whose
`vendor:` is set and differs from its model family's vendor fails to load with `vendor contradicts the model: <model>
is made by <vendor>` (the vendor `amazon` or `aws` is not a family: Kiro hosts the models, it does not make them). Under
`verifier.independence: different_model`, `normalise_model` also folds a `.` between digits to `-`
(`claude-sonnet-4.5` ≡ `claude-sonnet-4-5` ≡ `claude-sonnet-4-5-20250929`), and both `independence_constraint` and
`Independence.independent` compare normalised models.

Effect: a kiro judge on `claude-sonnet-4.5` is not independent of a claude-code implementer (both `anthropic`), and is
independent of a kiro implementer on `qwen3-coder-next` (`alibaba`), `declared (unverified)`. Scoped to kiro-cli:
opencode keeps its declared vendor (owner question 2).

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
without a model gets the agent's `model: null` and no `--model` (the hello of an implementer may run `auto`; only a
judge refuses it, D1). Cost: one tool-less turn (C11: 0.0105 credits on `qwen3-coder-next` with a 3-tool agent).

**D8. Roles.** `JUDGE_ADAPTERS` becomes `("claude-code", "codex", "opencode", "kiro-cli", "fake")`. With it, without
further code: `roles.judges` (step 9 and the plan-readiness review), `roles.clarifier`, the `s1_judge` stand-in, the
escalation keeper and the step-9 preflight accept a kiro-cli profile. The clarifier uses the same contract (a schema,
one document, a validated object), so it is in scope; it has no independence rule, so `auto` is allowed there. The
delegate is out of scope: it runs `read_only` with file tools, and whether a custom agent's `allowedTools` grants
trust headless is still [U] (C8); a later change can add it.

**D9. Doctor CFG-011 "kiro-cli judge profiles"** (scope config, severity error). For each kiro-cli profile in
`roles.judges`: no `model` or `model: auto` fails (`profile <p> in roles.judges has no model: Kiro picks one and its
vendor is unknown, so it is never independent; set model (kiro-cli chat --list-models)`). For each kiro-cli profile in
`roles.judges` or `roles.clarifier`: `options.agent` set is a warning (`a judge always runs the harness's tool-less
agent; options.agent is ignored here`), and `min_version` unset or below `2.32.0` is a warning (`the judge invocation
was measured on kiro-cli 2.32.0`). A warning-only result is `fail` with severity warn. A pass names each profile:
`<p>: tool-less harness agent, prompt on stdin, no trust flag, model <m> (<vendor>)`. No new live check: `LIVE-001`
runs the judges' probe ladder under `--live`, whose hello is now the judge invocation (D7); `LIVE-005` warns until the
2.32.0 fixtures are recorded (task 0 adds the directory).

**D10. Replay.** Task 0's fixtures drive the adapter tests. The simulation gets a judge replayed through the real
adapter: `JudgeScript` gains `replay: {adapter: kiro-cli, stream: "@fixture:<file>"}` (exclusive with `verdict`),
which makes the scenario's judge profile `adapter: kiro-cli` and runs `KiroCliAdapter` with a `ReplayProc` (a
`ProcRunner` stand-in in `l4.sim` that records the argv, env, cwd and stdin and writes the named stream to
`stdout_path`, exit 0). Scenario `happy-kiro-judge`: `happy-kiro` with that judge and a `judge-pass` stream; it expects
`verify.verdict PASS`, `verify.judge{profile, credits}`, `budget.cost{credits, role: judge}` and an
`availability.model_unverified` event for the judge.

**D11. Live proof.** On the owner's dummy repository (never a consumer), in CI, with its `KIRO_API_KEY` secret: a
unit whose implementer is not Anthropic (a free OpenCode model or a kiro `qwen3-coder-next` profile) and whose
`roles.judges` is `[kiro-judge]` (`{adapter: kiro-cli, auth: api_key, model: claude-sonnet-4.5, vendor: anthropic,
min_version: "2.32.0"}`); `l4 doctor --live` first (CFG-011 pass, LIVE-001 hello through the judge invocation). The run
reaches a verdict; the evidence under `docs/live/kiro-judge/` holds the raw judge stream (redacted), the
`verify.judge` and `budget.cost` events, the independence line, the CLI version, and the answers to §2.3. A negative
leg: the same unit with a claude-code implementer shows `no independent verifier` for the kiro judge on a Claude
model (no judge call).

**D12. Docs.** SPEC: §8.1 ("CLI judge" lists kiro-cli and the prompt-contract path), §8.3 (the kiro-cli row: the judge
argv, stdin, the reply, R-facts; the HB-X1 row "`kiro-cli` judge, reader" filled for the judge), §10.1 (vendor by
model family for kiro-cli, model normalisation), §15 doctor table (CFG-011), §12 ledger events
(`verify.judge.credits`, `budget.cost` with role judge or clarifier), the new requirements L4-KJD-001..011 with their
scenarios in §23 (a new subsection `23.x Kiro judge (KJD)`), and the change table row 50 in §21. The runbook: a kiro-cli judge in the profile reference, the CFG-011 fixes, and "a Kiro judge on a Claude
model is not independent of a Claude implementer". The skill: `references/adopt.md` (a kiro judge profile example and
the vendor rule) and `references/kiro.md` (Kiro as a judge). CHANGELOG `## 0.4.20 (unreleased)`: Added, Changed (the
three behaviour changes of the proposal with their fixes), Fixed (auth classification).

## 4. Files

| File | Change |
|---|---|
| `src/l4/agents/kiro_cli.py` | judge agent and settings writer, judge argv, stdin, `parse(judge=…)`, the auth rule, hello |
| `src/l4/agents/contract.py` | `attach_judge_reply` (moved from opencode) |
| `src/l4/agents/opencode.py` | calls `attach_judge_reply` |
| `src/l4/availability/vendor.py` | `MODEL_FAMILIES`, kiro-cli rule in `resolve_vendor`; `normalise_model` and `same_model` move here (an adapter must not import `l4.verifier`: `selection` imports `agent_judge`, which imports the adapters) |
| `src/l4/config/schema.py` | `Profile` validator: kiro-cli vendor against the model family |
| `src/l4/verifier/selection.py` | imports `normalise_model` (now with dot folding); model comparison through it |
| `src/l4/availability/quota.py` | `/usage` auth text |
| `src/l4/llm/agent_judge.py` | `JUDGE_ADAPTERS` |
| `src/l4/verifier/judge.py`, `src/l4/verifier/ladder.py` | `JudgeRun.credits`, events |
| `src/l4/clarifier/backend.py`, `src/l4/clarifier/clarifier.py` | `ClarifierReply.credits`, event |
| `src/l4/doctor/checks_config.py` | CFG-011 |
| `src/l4/sim/scenarios.py`, `src/l4/sim/fakes.py` (or a new `src/l4/sim/replay.py`), `src/l4/sim/builtin/scenarios/happy-kiro-judge.yaml`, the manifest | replay judge |
| `tests/fixtures/recorded/kiro-cli/2.32.0/`, `src/l4/recorded_versions.json` | fixtures (generated list) |

## 5. Risks and residuals

- **The served model is not reported.** Independence rests on the configured model (D5) and the CLI's own selection
  (D3 step 4). If Kiro routed a named model elsewhere server-side, nothing would show it; `--v2` avoids the documented
  V3 fallback (R17). `availability.model_unverified` is logged for every kiro-cli selection (existing).
- **The CLI's internal session file** (D3 step 4) may change shape; it is read fail-open (absent: no check) and
  fail-closed only on a contradiction.
- **Older CLIs.** Stdin, `--v2` and the settings keys were measured on 2.32.0 only; the runner had 2.27.1 and 2.28.0
  (C1). CFG-011 warns without `min_version: "2.32.0"`; task 11 confirms the runner's version.
- **The vendor rule is a breaking load error** for a kiro-cli profile whose `vendor:` contradicts its model (for
  example `vendor: amazon` on a Claude model). It is the claude-code and codex precedent and fails closed; the
  CHANGELOG gives the fix.
- **The implementer harness agent** (K3) inherits default resources too (R16) and runs from a private `KIRO_HOME` with
  an empty `settings/`: in the sandbox the worktree's `.kiro/steering` is masked, without the sandbox it is not. Out of
  scope here; noted for a later change.
- **A Claude model judging a Claude implementer** is refused by D5, which is the point; a team with only Kiro must pick
  a non-Anthropic judge model (GPT, DeepSeek, GLM, Qwen, Kimi) or a non-Anthropic implementer model.

## 6. Owner questions

1. **Vendor contradiction: load error or warning?** D5 makes it a load error (exit 3) as for claude-code and codex.
   Recommendation: keep the load error; it fails closed and the message names the fix.
2. **Extend the model-family rule to opencode?** An opencode profile `openrouter/anthropic/claude-…` with a declared
   `vendor: openrouter` has the same hole. Recommendation: not in 0.4.20; a later change with a doctor warning first,
   then the load error.
3. **Should the hello of every kiro-cli profile, implementers included, use the tool-less judge agent (D7)?**
   Recommendation: yes; it is cheaper, does not start the user's MCP servers, and only proves the login and the model.
4. **The live leg's judge model** (D11). Recommendation: `claude-sonnet-4.5` (1.3x) on a non-Anthropic implementer,
   which also proves the negative leg; `glm-5` (0.5x) if credits are short.
