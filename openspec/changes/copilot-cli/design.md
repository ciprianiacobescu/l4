## 1. Context

The owner's intent: GitHub Copilot CLI becomes a fifth agent CLI of L4. It can be an implementer, a judge, a clarifier,
a readiness reviewer and a delegate. It is experimental, and no default role chain names it. This design is built
for 0.4.27 on amaster 0.4.25 (`f84897f2`) plus the spike commit `58f31c40`.

What exists, read for this change [V code]:

- **The spike.** `docs/plan/proposal-copilot-cli.md` holds the evidence. `src/l4/agents/copilot_cli.py` is an
  unregistered prototype: its `NAME` is `copilot`, its probe answers only the `binary` step, and it ignores
  `resume_session_id`. `tests/unit/agents/test_copilot_cli_spike.py` has 12 tests. The streams recorded in BYOK mode
  are in `tests/fixtures/recorded/copilot/1.0.102-byok/`. `test_login_lock_coverage.py` classifies the module as a
  spike.
- **Recorded versions.** `l4.recordedversions.generate` keys `recorded_versions.json` by the fixture directory name,
  and `unrecorded(adapter, version)` looks the adapter name up. A directory `copilot/` therefore never answers for an
  adapter named `copilot-cli`. A version directory must match `^\d+(\.\d+)+$`, so `1.0.102-byok` is ignored. An
  adapter with no recordings at all gets no LIVE-005 finding.
- **The process runner.** `ProcRunner.run(..., on_line=f)` calls `f(line)` for every stdout line. When `f` returns
  True, `_wait` kills the process group and sets `ProcOutcome.aborted`. No adapter uses `on_line` today. The SPEC row
  of claude-code says "`api_retry{error: rate_limit}` → interrupt", but that was never built (agent-factory task 1.9
  is open). `req.interrupt` is the caller's cancel event, and no adapter sets it.
- **The sandbox.** `bwrap.py` puts a tmpfs over the home. It binds `$L4_HOME` read-only into every sandbox
  (`derive_tool_paths`: `add(l4_home(host_env))`). It hides the logins of every other adapter, and it binds the
  selected adapter's own `CREDENTIAL_PATHS` read-write (`bwrap.py`: `spec.credential_paths.get(spec.adapter)`).
- **The agent environment** is built from an allow-list (L4-SEC-001). An agent never gets `CI`, `GITHUB_ACTIONS` or
  `GITLAB_CI` (L4-SEC-040), and never gets `GH_TOKEN` or `GITHUB_TOKEN`.
- **Kiro is the model.** It has an exact pin, a digest table, an archive install (`_install_kiro`, `_swap_in_kiro`), a
  major gate (`SUPPORTED_MAJORS`, `MAJOR_WORDS`), a tool-less judge, a read-only delegate, a `routed` `auto`
  (`is_routed`, `ROUTED_DEFAULT`, `RoutedSet`), and the PRQ-12 step. In several modules a special case reads
  `profile.adapter == "kiro-cli"`. §5.6 lists every one of them that this change touches.

## 2. Facts

### 2.1 Labels

Each claim carries one label:
- [V] verified by the spike: a command run, a file read, or an official page fetched on 2026-10-22.
- [V-BYOK] verified with the CLI driving a local model (no GitHub account).
- [V help] read in the CLI's own help.
- [V here] verified while this design was written (2026-10-22): `SHA256SUMS.txt` fetched with curl, and the first tar
  header of each Linux and macOS tarball read with HTTP range requests.
- [I] inferred. [G] guessed. [U] not known until a task records it.

Every [I], [G] and [U] claim has a task or a risk in §6.

### 2.2 The facts this design rests on

| # | Fact | Label |
|---|---|---|
| F1 | `copilot --version` prints `GitHub Copilot CLI 1.0.102.` | [V] |
| F2 | Piped stdin with no `-p` runs one prompt and exits; `-p <text>` does the same | [V-BYOK] |
| F3 | `--output-format json` writes JSONL: `{type, data, id, timestamp, parentId, ephemeral?}`. The events L4 reads: `user.message`, `assistant.turn_start`, `assistant.turn_end`, `assistant.message {model, content, toolRequests}`, `tool.execution_start {toolCallId, toolName, arguments}`, `tool.execution_complete {toolCallId, success, error{code, message}, result{content}}`, `session.info`, `session.error {errorType, message, statusCode}`, `assistant.turn_retry {reason}`, `model.call_failure {statusCode, retryAttempt, …}`, and a final `{"type": "result", "sessionId", "exitCode", "usage"}` with no `data`. A run killed from outside has no `result` event | [V-BYOK] |
| F4 | `--session-id <uuid>` presets the session id; `result.sessionId` echoes it. No resume flag was observed | [V-BYOK] |
| F5 | `--usage-output-file <f>` writes `totalNanoAiu`, `aiCreditsStatus`, `modelMetrics.<model>.usage.{inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}` and more, also for a run that never authenticated | [V-BYOK] |
| F6 | A fatal model error is a `session.error` and exit 1, with stderr empty. 401: `errorType: "authentication"` after 3 tries. 402: `errorType: "query"`, no retry. 500: 5 retries (about 15 s), then `errorType: "query"`, `statusCode: 500` | [V-BYOK] |
| F7 | A 429 is retried by the CLI itself. `model.call_failure {statusCode: 429}` comes at once. `assistant.turn_retry {reason: "rate_limit"}` comes when the CLI retries: 32.7 s after the failure in the recorded run (the `Retry-After: 30` wait). Nothing is printed during the wait | [V-BYOK]; timing [V here, timestamps of `error-429-retrying.jsonl`] |
| F8 | With no credential: exit 1, empty stdout even with `--output-format json`, stderr `Error: No authentication information found.` | [V] |
| F9 | Token precedence: `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN` > stored keychain login > `gh` fallback. A user-owned fine-grained PAT with "Copilot Requests" works; classic `ghp_` tokens are refused | [V] |
| F10 | `--available-tools` decides which tools the model sees; `--allow-tool` and `--deny-tool` decide approval, and deny beats allow. An EMPTY `--available-tools` is ignored: the model sees every tool. An unknown name gives the model no tool, and `session.info` says `Unknown tool name in the tool allowlist`. The recorded runs used `l4_none` and `l4_no_such_tool`; the name `l4_no_tools` was not run | [V help]; [V-BYOK]; `l4_no_tools` [I] |
| F11 | `--available-tools=view,grep,glob` gave the model exactly those. On a gpt-oss model the CLI served `view,rg,glob`, and `apply_patch` instead of `create` and `edit` | [V-BYOK] |
| F12 | Prompt mode never asks. A call outside the policy ends with `error.code: "denied"`, the run goes on and exits 0. `--no-ask-user` removes the `ask_user` tool | [V-BYOK]; [V help] |
| F13 | Reads inside the cwd run with no allow flag. Shell commands the CLI deems read-only (`ls`, `echo`) run with no rule. Writes and other shell commands are denied | [V-BYOK] |
| F14 | `--allow-tool=write --allow-tool=shell(./.venv/bin/python:*) --add-dir <step> --disallow-temp-dir`: `create` wrote in the cwd and wrote `<step>/result.json`; without `--add-dir` that write was denied | [V-BYOK] |
| F15 | The CLI's path check is a heuristic: a script inside the cwd read a file outside it | [V-BYOK] |
| F16 | A shell rule matches the command's first word. `shell(./.venv/bin/python:*)` also allows `python -c`; `shell(.venv/bin/python …)` does not match `./.venv/bin/python …` | [V-BYOK] |
| F17 | The CLI removes its own `COPILOT_GITHUB_TOKEN` from the shell tool's environment | [V-BYOK] |
| F18 | `COPILOT_ALLOW_ALL=true` also trusts the working directory: its skills, plugins, MCP servers and hooks load | [V help] |
| F19 | Auto-update is off with `--no-auto-update`, `COPILOT_AUTO_UPDATE=false`, `autoUpdate: false` in `settings.json`, or when `CI`, `BUILD_NUMBER`, `RUN_ID` or `SYSTEM_COLLECTIONURI` is set | [V help] |
| F20 | `COPILOT_HOME` moves config and state. `$COPILOT_HOME/settings.json` is read: `autoUpdate`, `disableAllHooks`, `memory`, `includeCoAuthoredBy`. `includeCoAuthoredBy` defaults to true | [V]; [V help] |
| F21 | Release `v1.0.102` has a `SHA256SUMS.txt` (§5.4). Each of the six Linux and macOS tarballs starts with one member `copilot`, a regular file of mode 0755 (sizes in §5.4). The spike listed the whole linux-arm64 archive: one binary. For the other five, a second member after the first was not checked | [V here]; whole archive [V] linux-arm64, [U] the others |
| F22 | On its first run the binary extracts a package of about 220 MB to `$XDG_CACHE_HOME/copilot/pkg/<platform>/<version>/` (Linux default `~/.cache/copilot`). An unwritable cache fails: `Failed to extract bundled package … ENOENT`, exit 1. A pre-extracted cache mounted read-only works; a cold extraction took about 0.6 s | [V, Linux container] |
| F23 | `copilot --version` alone extracts the package, to `$XDG_CACHE_HOME/copilot/pkg/<platform>/1.0.102/` (~220 MB) on Linux (task 0.1, arm64 native and x64 under emulation) | [V] |
| F24 | The binary embeds Node; the tarball install needs no system Node. The npm package `@github/copilot` needs Node 22 or later for its shim | [V]; [V doc] |
| F25 | An L4-like bwrap run (read-only `/`, tmpfs `HOME` and `/tmp`, `--clearenv`, rw worktree and step dir) answered | [V-BYOK] |
| F26 | Built-in MCP servers load by default; `--disable-builtin-mcps` removes them. `--additional-mcp-config @file` adds servers. The file's format | [V help]; format [G] |
| F27 | `--allow-tool=<server name>` approves an MCP server's tools | [I] |
| F28 | `--no-custom-instructions` stops repository instructions (`AGENTS.md` and others) from loading. Whether an instruction file in the directory of a file the agent views still loads | [V help]; [U] |
| F29 | `--model <id>`; `auto` exists; the built-in list of 1.0.102 holds models of Anthropic, OpenAI, Google, xAI, Moonshot and Microsoft. The exact ids are recorded by task 0.1 | [V help]; ids [U] |
| F30 | `assistant.message.model` named the BYOK model. Under GitHub routing it names the model that served the call, also under `auto` | BYOK [V-BYOK]; GitHub-routed [I] |
| F31 | `totalNanoAiu` is AI credits × 10^9 (1 credit = $0.01) | [G] |
| F32 | The GitHub-routed shapes of a rejected token, of exhausted credits, of a rate limit and of a session or weekly limit | [G] |
| F38 | A rejected (well-formed, random) token, GitHub-routed: exit 1, empty stdout, stderr `Error: Authentication token found but could not be validated.` then `Failed to fetch PAT user login (401): GitHub returned: Bad credentials` (fixture `1.0.102-firstcalls/bad-token.stderr.txt`) | [V] |
| F39 | Under `--model auto` the stream holds `session.auto_mode_resolved {chosenModel, candidateModels, availableModels, routingMethod: "auto_v2", fallback, categoryScores, endToEndLatencyMs, hasImage}` before the reply, not ephemeral; `assistant.message.model` is the chosen id (fixture `judge-auto.jsonl`) | [V] |
| F40 | A Copilot Free account with a fine-grained token runs headless: exit 0 in about 3 s; `auto` offered only `gpt-6-luna`; `aiCreditsStatus` `complete`, `totalNanoAiu` 37117500 for one tiny call; stdout also carries `session.usage_checkpoint {totalNanoAiu, totalPremiumRequests, accountingSnapshot, ...}` (not ephemeral); no login or e-mail in the stream | [V] |
| F41 | The tool-less judge argv on the GitHub-routed path: two `session.info` lines (`Disabled tools: ...` and `Unknown tool name in the tool allowlist: "l4_no_tools"`) and no tool call, as under BYOK | [V] |
| F33 | No max-turns flag exists. A denied-call loop of a 2B model printed more than 10,000 lines in 6 minutes | [V-BYOK] |
| F34 | Linux x64 was not run. The minimum glibc of the gnu builds is not documented; musl builds exist | [I]; [G]; [V] |
| F35 | On macOS `XDG_CACHE_HOME` has no effect: the package lands in `$HOME/Library/Caches/copilot/pkg/darwin-arm64/1.0.102/` (task 0.1) | [V] |
| F36 | `--allow-tool=write` approves `apply_patch` on an OpenAI-served model | [U] |
| F37 | The CLI finds a warm package through a symbolic link at `$XDG_CACHE_HOME/copilot/pkg` into a read-only directory, and writes nothing under it (task 0.1) | [V] |

### 2.3 What needs a real token

Task 8.1 records these with the owner's token: a GitHub-routed judge reply, delegate run and implementer run; the
model that `assistant.message.model` names under `auto` and under a pinned model (F30); `totalNanoAiu` and
`aiCreditsStatus` (F31); the shape of a rejected token (F32); a 402 or a 429 only if one happens (no deliberate
spend); MCP injection with Serena (F26, F27); `apply_patch` approval if the plan has an OpenAI model (F36).

## 3. Goals and non-goals

Goals: one adapter `copilot-cli` that runs all four modes with fail-closed checks; a pinned, digest-checked install
with no Node; the package cache warm and read-only; one credential, `COPILOT_GITHUB_TOKEN`; a run that never waits
for a limit and never loops on denials unbounded; tokens and credits recorded; the vendor rules of 10.1; a release
gate on one GitHub-routed recording.

Non-goals, with the reason:
- **The Actions `GITHUB_TOKEN` with `copilot-requests: write` (proposal R1).** In L4 the job's `GITHUB_TOKEN` is the
  forge token, and SEC-001 never hands a forge token to an agent. Supporting it needs a forge token that is not the
  job's own (an App token or `L4_FORGE_TOKEN`) and a second, scoped token; that is a design of its own.
- **BYOK as a free profile (proposal question 7).** It drives a local model through the CLI. That is a different
  product surface (provider variables, no GitHub account), with its own isolation questions.
- **The npm install route.** `npm install --prefix <dir> --save-exact @github/copilot@1.0.102` (Node 22 or later) is
  documented for a person's machine only. The harness installs the tarball.
- **The Copilot cloud agent** (proposal §2.8). It is not a CLI step that L4 can gate.
- **A headless quota query.** Whether `/usage` answers headless is [G]; the `quota` step is skipped.
- **A budget cap.** `--max-ai-credits` is soft and has a minimum of 30 [V help]; `budget_cap` stays False.
- **Copilot's own sandbox** (`--sandbox`): off, as by default; L4's bwrap is the boundary.
- **Skills install** (`.github/skills`, `~/.copilot/skills`) and Windows builds.
- **A doctor finding for an org policy that forces Copilot's sandbox** (proposal R9): the startup warning is [G].

## 4. Decisions

The owner's delegate decided D1 to D17 in their core. Where this design adds a rule that the delegate's list did not
cover, the decision says "(added)" and §8 lists it.

**D1. The adapter.** The adapter id is `copilot-cli` (as `kiro-cli`). The binary is `copilot`. `CopilotCliAdapter`
replaces the prototype in `src/l4/agents/copilot_cli.py`, with `name = "copilot-cli"` and `experimental = True`
(every run is announced once as `agent.experimental`). It joins `ADAPTERS` (factory), `HARNESS_ADAPTERS` and
`JUDGE_ADAPTERS` (`l4/config/roles.py`), `DELEGATE_SERVES` (`l4/delegate/independence.py`) and
`ADAPTERS_THAT_SERVE` (`l4/doctor/checks_delegate.py`), and the two copies in the skill's `yolo_preflight.py`. No
default role chain names it, and `l4 init` writes no Copilot profile. SPEC §3.2 shows a commented reference profile.

**D2. The common invocation.** Every run:
- `argv` = `[exe, "--output-format", "json", "--no-ask-user", "--no-auto-update", "--no-custom-instructions",
  "--disable-builtin-mcps", "--disable-client-telemetry", "--disallow-temp-dir", "--session-id", <id>,
  "--usage-output-file", <step>/copilot-usage.json, "--model", <model>]` followed by the mode flags (D3 to D5). No
  argv entry holds the prompt. `<id>` is `req.preset_session_id`, else a new uuid4.
- **The model** is the profile's model, or `auto` when it has none or when it is `auto` in any letter case (added; as
  kiro-cli D13). Then the profile's view and the run agree, and a profile with no model is routed (D10).
- **The prompt** goes on stdin, then EOF (F2). An empty prompt is refused before the spawn.
- **The private home** (added detail): `COPILOT_HOME=<step private dir>/copilot-home`, removed first and written
  fresh. It holds only `settings.json` = `{"autoUpdate": false, "disableAllHooks": true, "memory": false,
  "includeCoAuthoredBy": false}` (F20). The CLI writes its session state there, which holds the whole prompt; it stays
  in the step's private directory, as Kiro's private home does.
- **The environment** is `req.env` plus `COPILOT_HOME`, plus `COPILOT_AUTO_UPDATE=false`, plus
  `XDG_CACHE_HOME=<step private dir>/xdg-cache`: a per-run cache directory (D14) (added). `COPILOT_ALLOW_ALL` is
  removed if it is there (F18).
- **Auto-update is off three ways**: `--no-auto-update`, `autoUpdate: false`, and `COPILOT_AUTO_UPDATE=false`. The
  delegate's list named "CI env" as the third way; L4-SEC-040 says an agent process MUST NOT receive `CI`, so the
  third way is the documented variable `COPILOT_AUTO_UPDATE=false` (F19) (added).
- **The credential** comes through `credential_loader` (D12). `GH_TOKEN` and `GITHUB_TOKEN` are forge tokens in L4:
  the allow-listed environment never has them, and the adapter never adds them.

**D3. Judge mode** (the judges, the clarifier, the readiness review, the `s1_judge` stand-in, and the hello's argv).
Mode flag: `--available-tools=l4_no_tools`, an unknown tool name, so the model is offered no tool (F10). The adapter
NEVER passes an empty `--available-tools` or `--available-tools=`: that means every tool. No `--allow-tool`,
`--allow-all-tools`, `--yolo` or `--allow-all` in any mode. The working directory is `judge_workdir(req)` (the empty
`judge-cwd`). The reply is the content of the last `assistant.message` whose content is not blank, given to
`attach_judge_reply(result, text, schema)` (the shared slicer of kiro-judge). Fail-closed: a judge run that holds any
`tool.execution_start` ends as `error` with the detail `copilot-cli judge called a tool (<first toolName>)` and no
`structured`, whatever else the stream holds. `schema_mode` is `prompt_contract`, so `AgentJudge` appends the schema
instruction. The name `l4_no_tools` itself was not run (F10 [I]); task 0.1 cannot check it without a model, so the
unit tests assert the argv, and task 8.1 records the `session.info` line and the empty tool set.

**D4. Read-only mode** (the delegate). Mode flag: `--available-tools=view,grep,glob` and no allow flag: reads inside
the cwd are approved without one (F13). The working directory is the detached worktree. Fail-closed: a run that
started any tool whose name is not in `{view, grep, rg, glob}` (`rg` is how the CLI serves `grep` to OpenAI models,
F11) ends as `error` with the detail `copilot-cli delegate called a tool outside the read set (<sorted names>)` and
no `structured`. Otherwise the reply is `attach_read_only_reply(result, last_message, final_text, schema)`, where
`last_message` is the content of the last assistant message after the last `tool.execution_start` (F3). The
delegate's detached worktree is built with `masked=True`, as for opencode (added): whether a nested instruction file
loads when the agent views a file is [U] (F28), and the masked tree removes those files (L4-DLG-016).

**D5. Implement mode.** Mode flags, in this order: `--allow-tool=write`; `--allow-tool=shell(<first word of
gate_prefix>:*)` when the policy has a gate prefix; `--add-dir <step private dir>` (the result file lives there,
F14). With MCP servers in the request (Serena): the adapter writes `<step>/copilot-mcp.json` = `{"mcpServers":
{<name>: server.config_entry()}}` and adds `--additional-mcp-config @<that path>` and one `--allow-tool=<name>` per
server. The file's format is [G] (F26) and the allow rule [I] (F27); task 8.1 records a run with Serena and the last
task fixes the mapping if it is wrong. Serena starts with `--context copilot-cli` (added in review: Serena 1.7.0
ships that context [V], and `l4/memory/serena.py` had no entry for the adapter, so a Copilot implementer got no Serena).
The working directory is the worktree. The result is the prompt contract:
`$L4_RESULT_PATH`, read with `read_result_file`, given to `attach_file_result(result, text, schema, "copilot-cli")`.
The gate rule matches the command's first word only (F16): `.venv/bin/python` and `./.venv/bin/python` are different
words. The implementer's prompt already names the gate command as `gate_prefix` says it; the gate rule uses the same
first word, so the two agree. The rule also allows any other command that starts with that word (R5).

**D6. The stream and the status.** `parse` reads the JSON objects with a string `type` (other lines are skipped) and
takes: `session_id` and the stream's own exit code from the `result` event; `model_resolved` from the last
`assistant.message.model` that is a non-empty string; `final_text` from the last non-blank assistant content;
`last_message` (D4); `permission_denials` = one `{"tool_name": <name>}` per `tool.execution_complete` whose
`error.code` is `denied` (the name from its `tool.execution_start`, else `unknown`); `api_status` from
`session.error.statusCode`. The status, first match wins:
1. The stop watcher of D7 stopped the run: D7.
2. The run timed out or stalled, and the stream holds an `assistant.turn_retry` with `reason: "rate_limit"` or a
   `model.call_failure` with `statusCode: 429`, and no `result` event: `rate_limited` (D7) (added).
3. The run timed out or stalled: `timeout`. The caller cancelled it (`interrupted`): `cancelled`.
4. Exit not 0, no JSON event on stdout, and stderr matches `No authentication information found`: `auth`, detail
   `copilot-cli found no credential (set COPILOT_GITHUB_TOKEN)` (F8). Exit not 0, no JSON event on stdout, and stderr
   matches `Authentication token found but could not be validated`: with `(401)` or `(403)` in stderr, `auth`, detail
   `copilot-cli could not authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)`, limit kind `auth`,
   source `copilot.stderr` (F38: the GitHub-routed shape of a rejected token; it never reaches the stream); without
   either status, `error`, `transient`, detail `copilot-cli could not validate COPILOT_GITHUB_TOKEN (no 401 or 403:
   the network?)` (the CLI's own text says the token may still be valid).
5. A `session.error` (the last one):
   - `errorType` `authentication`, or `statusCode` 401 or 403: `auth`, detail `copilot-cli could not authenticate
     (COPILOT_GITHUB_TOKEN is missing, expired or rejected)`, limit kind `auth`, source `copilot.session_error`;
   - `statusCode` 429: `rate_limited`, detail `copilot-cli reported a rate limit (session.error 429)`, limit kind
     `rate_limit`, source `copilot.session_error`;
   - `statusCode` 402: `quota`, detail `copilot-cli reported that the AI credits are used up (session.error 402)`,
     limit kind `credits`, source `copilot.session_error`;
   - any other: `error`, detail `copilot-cli reported an error (<errorType or unknown>, status <statusCode or
     none>)`, `transient` when the status is in `TRANSIENT_STATUSES` or at least 500.
6. Exit not 0 and stdout or stderr says `Failed to extract bundled package`: `error`, detail `copilot-cli could not
   extract its bundled package (the L4 package cache is cold or not writable): run l4 doctor --fix` (F22) (added).
7. Exit not 0: `error`, detail `copilot-cli exited with code <n>`.
8. Exit 0: the mode decides (D3, D4, D5).

A rejected token's GitHub-routed shape is [V] (F38, rule 4). The GitHub-routed wording of 402, 429 and of session or
weekly limits is [G] (F32). Rule 5 uses the recorded BYOK shapes; task 8.1 records the GitHub-routed ones, and the last task changes the mapping where they differ.

**D7. The run never waits for a limit and never loops on denials unbounded.** One stateful line watcher,
`CopilotStop`, is passed to `ProcRunner.run` as `on_line`, beside `reader=copilot_signals` (added: the mechanism).
It keeps two numbers and one reason, never the text of a line:
- On the first `model.call_failure` whose `data.statusCode` is 429, or the first `assistant.turn_retry` whose
  `data.reason` is `rate_limit` if that comes first, it records `reason = "rate_limit"` and the event type, and returns
  True: the runner kills the run before the CLI waits out `Retry-After`.
- It counts `tool.execution_complete` events whose `error.code` is `denied`; any other `tool.execution_complete`
  sets the count back to 0. When the count reaches `DENIAL_LIMIT = 20`, it records `reason = "denials"` and returns
  True.
- A line that is not a JSON object is ignored. The watcher never raises.

`parse` gets `stop: "rate_limit" | "denials" | None` = the watcher's `reason` (not `outcome.aborted`: when the CLI
exits right after the line, `_wait` never sets the flag). With `stop == "rate_limit"`: `rate_limited`, detail
`copilot-cli hit a rate limit (HTTP 429); the harness stopped the run (it never waits for a limit)`, limit kind
`rate_limit`, source `copilot.model_call_failure` (or `copilot.turn_retry` when that event came first). With `stop == "denials"`: `permission_blocked`, detail `copilot-cli was
stopped after 20 denied tool calls in a row: its permission rules refuse what it tries` (the status that the SPEC
status table uses for a run that permission rules stopped). Rule 2 of D6 gives the detail `copilot-cli was waiting
out a rate limit when the run timed out` and source `copilot.model_call_failure` or `copilot.turn_retry`.
- **Cool-down.** No reset time is read (`resets_at` None): the Retry-After of a GitHub-routed 429 is [G]. The
  factory then applies `availability.default_cooldown` (added). The next profile of the chain takes the step;
  `max_task_attempts` is not used.
- **Why the trigger is the failure and not the retry.** F7 shows that `assistant.turn_retry` comes only after the CLI
  has waited out `Retry-After` once (32.7 s in the recording), while `model.call_failure {statusCode: 429}` comes at
  once. L4 adapters never wait for a limit, so the failure is the trigger (the orchestrator's review decision; the
  retry stays a second trigger). Rule 2 of D6 still reads a run that timed out with a 429 in its stream as a rate
  limit (a probe has no watcher). Task 8.1 records the GitHub-routed shape of a 429.
- **The step timeout** stays the outer bound (no max-turns flag, F33).
- A stopped or killed run leaves no usage file (SIGKILL, no grace): its usage is zero (D8).

**D8. Usage and credits.** The usage document is `<step>/copilot-usage.json`, removed before the run and read after
it with `read_regular_file` (a regular file, at most 1 MiB; a link or a larger file is no document). Tokens:
`input_tokens`, `output_tokens` and `cached_input_tokens` are the sums of `inputTokens`, `outputTokens` and
`cacheReadTokens` over `modelMetrics`. Credits: `totalNanoAiu / 1e9` when it is a number above 0, with
`credits_source = "copilot.usage_file"`; else None. `cost_usd` stays None: credits are never added to a dollar total
(the existing rule of `budget.cost`). A missing or unreadable document is zero usage. No context peak is reported
(L4-FAC-011). The unit of `totalNanoAiu` is [G] (F31); task 8.1 compares one run's value with the GitHub billing
page.

**D9. The stream reader** (L4-FAC-012). `copilot_signals(line)` in `l4/agents/activity.py`: `start(toolCallId)` for
`tool.execution_start`, `end(toolCallId)` for `tool.execution_complete`, nothing else. It returns no signal and does
not raise for a line that is not JSON or not an object, and it keeps no text.

**D10. Vendor, `auto` and the served model.**
- `MODEL_FAMILIES` gains `grok-` → `xai` and `mai-` → `microsoft` (added). The prefixes come from the spike's reading
  of `copilot help config` [V help]; task 0.1 records the exact ids.
- `ROUTED_ADAPTERS = ("kiro-cli", "copilot-cli")`. `is_routed(profile)` is true for an adapter of that tuple with no
  model, a blank model, or `auto` in any letter case. Every `== "kiro-cli"` routed special case of §5.6 reads it.
- A copilot-cli profile with a pinned model has the vendor of its model's family, provenance `declared`; a model of
  no known family keeps the declared `vendor:`. The `Profile` validator of kiro-judge (a `vendor:` that contradicts
  the family fails to load) applies to `copilot-cli` too.
- `auto` is routed. Its possible vendors are the built-in set `COPILOT_ROUTED_DEFAULT`: the normalised model ids of
  1.0.102's `copilot help config` list, which task 0.1 records, and their makers. The design expects `anthropic`,
  `google`, `microsoft`, `moonshot`, `openai`, `xai` (F29). A listed id of no known family is not allowed into the
  set: task 1.3 stops and reports it, so that `unknown` never enters by accident. No model listing command is known,
  so the probe records no listed set; `built_in_routed(name, profile)` returns the set of the profile's adapter.
- Under `auto` the stream names the routed model before any reply: `session.auto_mode_resolved {chosenModel,
  candidateModels, availableModels, routingMethod}` (F39). `parse` takes `chosenModel` as `model_resolved` when no
  `assistant.message.model` follows (a run that failed after routing). On a Copilot Free account `availableModels` was
  `["gpt-6-luna"]` only (F40): such a profile is an OpenAI-family judge in practice, and the runbook says so.
- `served_model=True`. Under `auto`, a concrete `assistant.message.model` (not empty, not `auto`) is the served
  model: `_ask_judges` checks it with `assess_independence` as for every adapter that reports one, and the verdict's
  line reads `served <id>`. For a pinned model, `seat_of` gives `expect_model = <pinned>` and `reports_served =
  False`: a served id that is not the pinned one under `normalise_model` is `model_mismatch`, and one that is the same
  reports nothing, so the judge stays `declared` (added; kiro-judge D15's rule). Why: under BYOK the field echoed the
  request (F30), and whether GitHub routing reports a different id is [I]. Task 8.1 records both. If it shows a pinned
  model served as itself by GitHub (the id differs in a way only the server could know, for example a dated id), a
  later change may make it `served`.
- Under `independence: different_vendor` a copilot-cli judge on `auto` is never independent of a claude-code or codex
  implementer (their vendors are in its set). The runbook says: pin a model.

**D11. The probe ladder.**
- `binary`: `_binary("copilot", …)` with `copilot_env(ctx.environ)` added to its environment (D14), then the major
  gate (D15) and `min_version`, as for every gated CLI.
- `auth`: `credential_auth(profile, ctx)`. A set `COPILOT_GITHUB_TOKEN` passes with `{"auth_method": "env"}`. When it
  is unset the step fails with `COPILOT_GITHUB_TOKEN is not set`, whatever `auth:` says (added: a private
  `COPILOT_HOME` hides every stored login, and no `whoami` exists).
- `quota`: skipped with the reason `copilot-cli has no headless quota query`.
- `hello`: a `tempfile.TemporaryDirectory(dir=ctx.cwd, prefix="l4-copilot-probe-")` holding an empty `cwd/` and a
  `copilot-home/` written as in D2. argv = the common argv (D2, with the temp dir's usage file and a new uuid) +
  `--available-tools=l4_no_tools` + `-p`, `ctx.hello_prompt` (the probe runner has no stdin). Env = `probe_env(ctx,
  {**credential env, **copilot_env(ctx.environ), "COPILOT_HOME": <temp home>})`. The reply is D3's text, given to
  `_hello_verdict`. A `tool.execution_start` fails it (`copilot-cli hello called a tool (<name>)`, class `other`). A
  `rate_limit` retry or a 429 call failure in its stdout is a rate limit (`LimitSignal` kind `rate_limit`, source
  `copilot.model_call_failure` or `copilot.turn_retry`), also when the hello timed out, with the reason `copilot-cli hit a
  rate limit (hello)`. The other failures map as D6 rules 4 to 7, with the failure class of `status_class(statusCode)` or
  `auth` for rule 4.
- The probe never reads `~/.copilot`, the keychain or `gh`.

**D12. The credential.** `credential_variable("copilot-cli", <any auth>) = "COPILOT_GITHUB_TOKEN"`: a user-owned
fine-grained PAT with the "Copilot Requests" permission (F9). It reaches a run through `credential_loader` (a 0600 file
read by the `/bin/sh` loader, L4-PRV-024), never through the environment dict or an argv. It is in
`DEFAULT_REDACT_ENV` and in `IDENTITY_ENV["copilot-cli"]`. The token shape `github_pat_` is already in the redactor.
`credential_secrets` names it in the generated GitHub job without a change. `CREDENTIAL_PATHS["copilot-cli"] =
("~/.copilot",)`: `~/.copilot/config.json` holds a plaintext token on a Linux machine without a keychain. Every other
adapter's sandbox hides it. The copilot-cli sandbox hides it too and binds nothing of it (added): bwrap binds the
selected adapter's own login read-write today, and copilot-cli runs from its private `COPILOT_HOME`, so
`NO_LOGIN_BIND = frozenset({"copilot-cli"})` (in `l4/sandbox/base.py`) makes `hidden_credential_paths` hide its paths
and `bwrap.py` skip their bind. `copilot-cli` is not in `gate.OAUTH_ADAPTERS`: a PAT does not rotate. Readiness
(PRV-001), for both auth modes:
1. `create a fine-grained personal access token owned by your personal account (not an organization) with the
   Copilot Requests permission (classic ghp_ tokens are refused)`;
2. `store it as the masked CI variable COPILOT_GITHUB_TOKEN` (on GitHub `steps_for` rewrites the last words to the
   secret's place, as for every adapter).
Billing: the token bills its owner's seat. ToS: "a single login may not be shared by multiple people" [V doc]; one
person's PAT driving a team's CI is the owner's call (R1).

**D13. The pin and the install.** `COPILOT_VERSION = "1.0.102"` joins `ADAPTER_PINS`; `catalog_pins()` gains
`agent:copilot-cli`, so the agent-CLI cache key moves once with this release. The harness installs from
`https://github.com/github/copilot-cli/releases/download/v<version>/copilot-<asset>.tar.gz` and checks the sha256
against `COPILOT_SHA256[version][key]` (§5.4), a table that ships with the harness; it never fetches
`SHA256SUMS.txt` at install time and never runs the vendor's installer (`gh.io/copilot-install`).
- **Platform keys** (added): `copilot_platform(platform, libc)` gives `linux-x64` or `linux-arm64` when a glibc
  version is found, `linux-x64-musl` or `linux-arm64-musl` when none is, and `darwin-x64` or `darwin-arm64` on macOS;
  any other platform raises `ValueError`. Asset names: `linux-x64-musl` → `linuxmusl-x64`, the others as the key. The
  gnu build's minimum glibc is [G] (F34): no threshold is guessed; R7 holds the risk.
- **macOS** (added): the darwin tarball is one binary, like Linux, so the harness installs it too (unlike Kiro's disk
  image). The darwin builds were not run [I]; task 0.1 runs `--version` on the development Mac.
- **`_install_copilot(ctx, tool)`**, after `_install_kiro`: key; digest (a version or key with no digest never gets
  here: `plan_fixes` made the action `manual`); download into `tempfile.TemporaryDirectory(prefix="copilot-",
  dir=ctx.downloads)`; `verify_sha256(archive, expected, "the harness's digest")`; open with `tarfile` (`r:gz`); the
  member `copilot` must exist, be a regular file (`isreg()`) and be at most `COPILOT_MEMBER_MAX` (512 MiB); stage it to
  `~/.local/bin/.copilot.tmp.<pid>` (unlink first, `O_CREAT|O_EXCL|O_NOFOLLOW`, a bounded copy, mode 0755), keep an
  existing target as `copilot.bak.<pid>`, `os.replace` the staged file onto `~/.local/bin/copilot`, restore the backup
  if the rename fails, and remove the staged file and the backup in every case. Nothing else of the archive is read; no
  member name becomes a path. Then the warm-up of D14.
- **`plan_fixes`** and **`_verified`** treat `copilot-cli` as they treat `kiro-cli` (added): `ARCHIVE_ADAPTERS =
  ("kiro-cli", "copilot-cli")` in `catalog.py`. A version outside the table is `manual` with `copilot <v> (<source>)
  has no sha256 in this harness (it holds 1.0.102): install it yourself and keep it, or hold one of those`; a
  present copilot of another major is `manual` on a person's machine and replaced under `--ci --fix`; an install is
  always checked exactly; a digest mismatch fails with the Kiro text (no manual command); HTTP 403 or 404 fails with
  `cannot download copilot <v> from <host> (<reason>): that version may no longer be served; hold another version in
  ci.cli_versions (one the harness holds) or report it`. `ci.cli_versions: {copilot-cli: …}` works as for Kiro: only a
  held version is installed.
- `manual_command` for copilot-cli: §5.5 T24.
- **npm** (`@github/copilot@1.0.102`, Node 22 or later) is documented in the runbook as a person's alternative and is
  not implemented.

**D14. The package cache.** `copilot_cache(environ) = l4_home(environ) / "copilot-cache"`. It lies under `$L4_HOME`,
so:
- the sandbox already binds it read-only (`derive_tool_paths`), and a warm cache runs read-only (F22);
- the action's agent-CLI cache saves it with `~/.local/share/l4` (about 220 MB more per platform and version).

Probe steps, provisioning's `--version` reads and doctor's `--version` reads are single processes: they use
`copilot_env(environ)` = `{"COPILOT_AUTO_UPDATE": "false", "XDG_CACHE_HOME": str(copilot_cache(environ))}`.

**A run does not** (added). The CLI's shell tool gives its environment to every command the agent runs (F17 strips
only the token), and `build_agent_env` sets no cache variable for an agent. A read-only `XDG_CACHE_HOME` would make Go
(`GOCACHE` defaults to `$XDG_CACHE_HOME/go-build`), pnpm, uv without `UV_CACHE_DIR` and other tools fail inside the
implementer's own gate runs; today they write to the tmpfs `~/.cache`. So every run (all four modes, one rule) gets a
per-run cache directory: `write_run_cache(step_dir, environ)` removes `<step private dir>/xdg-cache`, creates it, creates
`xdg-cache/copilot/`, and makes `xdg-cache/copilot/pkg` a symbolic link to `copilot_cache(environ)/copilot/pkg`. The
CLI finds its warm package through the link (inside the read-only bind); every other tool writes under
`xdg-cache/<tool>`, which is writable. The directory is made fresh for each run, so a package that an agent planted in
an earlier run's directory (it is inside `--add-dir <step>`) is never used. The CLI follows a link at
`$XDG_CACHE_HOME/copilot/pkg` into a read-only cache and writes nothing there [V] (F37, task 0.1).

**Warm-up**, at install: `copilot --version` with `copilot_env(env)` and a throw-away `COPILOT_HOME`; then
`_verified` checks the exact version and that `<cache>/copilot/pkg/` holds at least one directory, else the action
fails with `copilot <version> did not extract its package into <cache>/copilot/pkg (copilot --version ran with
XDG_CACHE_HOME=<cache>)`. `--version` extracts the package [V] (F23, task 0.1). A cold cache at run time fails (D6 rule 6),
and `l4 doctor --fix` is the fix. On macOS `XDG_CACHE_HOME` has no effect [V] (F35): the CLI extracts into
`$HOME/Library/Caches/copilot`. There is no sandbox on macOS, so that cache still runs: on `darwin-*` the warm-up runs
with the person's own `HOME`, `_verified` checks the version only, and the per-run link of `write_run_cache` is made
but unused. A run whose agent environment sets another `HOME` extracts the package once into it (about 220 MB and a
few seconds per run; R-mac).

**D15. The major gate** (L4-OCG-006). `SUPPORTED_MAJORS["copilot-cli"] = 1`, from the pin. `MAJOR_WORDS["copilot-cli"]`
is in §5.5 T18. Every caller of L4-OCG-001 and L4-OCG-002 applies it: the probe `binary` step, ENV-004, LIVE-005,
`l4 doctor --fix` and PRQ-22. `F1`'s `GitHub Copilot CLI 1.0.102.` gives `1.0.102` to `reported_version`.

**D16. prereqs.sh PRQ-22** (added: the delegate's list said "a row in prereqs.sh"; this makes it opt-in, because no
default chain uses copilot-cli). PRQ-20 is reserved for opencode-v2 and PRQ-21 is taken. A `--with-copilot` switch
(default off; `report PRQ-22 SKIP "Copilot CLI" "pass --with-copilot to install"`). The top block gets
`COPILOT_VERSION=${COPILOT_VERSION:-1.0.102}` and four `COPILOT_SHA256_*` lines (x86_64, aarch64, x86_64 musl,
aarch64 musl) from §5.4. `check_copilot` passes only when the runner user's `copilot --version` reports exactly
`COPILOT_VERSION`; another major adds `Copilot CLI <n>; L4 runs Copilot CLI 1`. `apply_copilot`, as the runner user:
picks the asset from `uname -m` and `ldd --version` (glibc present → gnu, else musl), downloads into a `mktemp -d`
under the runner user's home with `curl -fsSL`, checks it with `sha256sum -c`, extracts only `copilot`, runs `install
-m 755` into `~/.local/bin/copilot`, then runs `copilot --version` once with `XDG_CACHE_HOME` set to the L4 cache (the
warm-up of D14). A drift test compares the pin and the four digests with the catalog.

**D17. Fixtures, the release gate and the live recording.**
- The BYOK streams move to `tests/fixtures/recorded/copilot-cli/1.0.102-byok/` (added: the delegate's list said
  `copilot/1.0.102`, but `recordedversions` keys by directory name and the adapter is `copilot-cli`; under `copilot/`
  LIVE-005 would never find the recording). The suffix keeps them out of `recorded_versions.json`. A `README.txt`
  says how they were made and that they are not a contract recording.
- Task 0.1 adds `tests/fixtures/recorded/copilot-cli/1.0.102-notoken/` (version, `help config`, the no-credential
  stderr): outputs that need no account, also outside `recorded_versions.json`.
- **Release gate.** The change is not released while `recorded_versions.json` has no `copilot-cli` entry. The entry
  comes only from task 8.1, the last task: ONE GitHub-routed recording session with the owner's token, on the owner's
  dummy repository, never a consumer. It adds `tests/fixtures/recorded/copilot-cli/1.0.102/`, regenerates
  `recorded_versions.json`, and fixes any mapping that the recording disproves. Every implementer task before it runs
  without a token.
- Until then, LIVE-005 reports nothing for a copilot-cli profile (no recordings at all), and the runbook says the
  adapter is experimental.

**D18. Simulation** (added; the proposal listed it under Tests). A judge replayed through the real adapter, as
`happy-kiro-judge`: `JudgeScript.replay.adapter` accepts `copilot-cli`; `l4/sim/replay.py` builds a
`CopilotCliAdapter(ReplayProc(stream), exe=REPLAY_EXE)` for it; scenario `happy-copilot-judge` is `happy-openspec`
with that judge, a profile with no model (so `auto`, routed on the built-in set), and a synthetic judge stream
`judge_pass.copilot.jsonl` in the shape of `judge-hello.jsonl` whose last assistant content is a valid verdict and
whose `assistant.message.model` is `gpt-6.1-sol`. Its family is `openai`, inside the routed set and not the
simulated implementer's vendor (`sim-implementer`), so the round is independent and the verdict line reads `served
gpt-6.1-sol`. The stream is synthetic, and the fixture's README says so.

**D19. Docs.** SPEC: §3.2 (the commented profile and the `credential_paths` line); §8.3 (a `copilot-cli` row and a
new subsection 8.3.3 with L4-FAC-013 to L4-FAC-022); the lists in L4-FAC-011 (no peak) and L4-FAC-012 (the
reader); L4-PRV-044 (the three switches); L4-PRV-047 to L4-PRV-050 after L4-PRV-046; L4-OCG-006 after L4-OCG-005;
ENV-004's major list; the HB-X1 rows; §10.1 (Copilot `auto` routed, served model); §15 PRV-001; L4-DLG-015 (five
adapters); §21 row 67 (row 66 is `replay-restore-confined`, on another branch); §23.28 with the scenarios. Runbook:
a new 10.8 "A GitHub Copilot CLI profile", the 7.1 delegate list, 7.4's major line. Skill: `references/adopt.md` (a
Copilot profile and its token). `docs/runner/README.md`: the PRQ-22 row. CHANGELOG `## 0.4.27 (unreleased)`.

## 5. Contracts (texts, exact)

The tasks share these. Do not change one without the orchestrator.

### 5.1 Constants and signatures

```python
# src/l4/agents/copilot_cli.py
NAME = "copilot-cli"
BINARY = "copilot"
CREDENTIAL_VARIABLE = "COPILOT_GITHUB_TOKEN"
HOME_DIR = "copilot-home"
USAGE_FILE = "copilot-usage.json"
MCP_FILE = "copilot-mcp.json"
USAGE_LIMIT = 1_048_576
NO_TOOLS = "l4_no_tools"
READ_TOOLS = ("view", "grep", "glob")
READ_TOOL_NAMES = frozenset({"view", "grep", "rg", "glob"})
AUTO_MODEL = "auto"
DENIAL_LIMIT = 20
HOME_SETTINGS = {"autoUpdate": False, "disableAllHooks": True, "memory": False, "includeCoAuthoredBy": False}
COMMON_FLAGS = ("--output-format", "json", "--no-ask-user", "--no-auto-update", "--no-custom-instructions",
                "--disable-builtin-mcps", "--disable-client-telemetry", "--disallow-temp-dir")
RUN_CACHE_DIR = "xdg-cache"
def effective_model(profile: Profile) -> str: ...            # the profile's model, else "auto"; "AUTO" -> "auto"
def write_home(home: Path) -> Path: ...                       # removed first; holds only settings.json
def write_run_cache(step_dir: Path, environ: Mapping[str, str]) -> Path: ...
    # removes and recreates <step_dir>/xdg-cache; xdg-cache/copilot/pkg -> copilot_cache(environ)/copilot/pkg (D14)
def gate_rule(gate_prefix: str | None) -> list[str]: ...      # ["--allow-tool=shell(<first word>:*)"] or []
def build_command(req: RunRequest, *, exe: str, session_id: str, usage_path: Path,
                  mcp_config: Path | None = None) -> list[str]: ...
def events(text: str) -> list[dict[str, Any]]: ...
def stream_facts(stream: Sequence[Mapping[str, Any]]) -> dict[str, Any]: ...
    # keys: session_id, result_seen, model, final_text, last_message, tools, denials, error, retry_reasons,
    #       call_failure_statuses
def usage_of(document: Any) -> Usage: ...
class CopilotStop:                                            # the on_line watcher of D7
    reason: Literal["rate_limit", "denials"] | None
    def __call__(self, line: str) -> bool: ...
def parse(text: str, *, exit_code: int, raw_events_path: Path, mode: str = "implement", stderr_text: str = "",
          usage_document: Any = None, result_text: str | None = None, schema: dict[str, Any] | None = None,
          timed_out: bool = False, interrupted: bool = False,
          stop: Literal["rate_limit", "denials"] | None = None) -> RunResult: ...
def probe_copilot(profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult: ...
class CopilotCliAdapter:
    name = "copilot-cli"; experimental = True
    def __init__(self, runner: ProcRunner | None = None, exe: str | None = None) -> None: ...  # exe: the sim's replay
    def capabilities(self) -> AgentCaps:
        return AgentCaps("prompt_contract", False, True, False, False, True, False, True, served_model=True)

# src/l4/agents/activity.py
def copilot_signals(line: str) -> tuple[Signal, ...]: ...

# src/l4/config/defaults.py
COPILOT_CACHE_DIR = "copilot-cache"
def copilot_cache(environ: Mapping[str, str]) -> Path: ...    # l4_home(environ) / COPILOT_CACHE_DIR
def copilot_env(environ: Mapping[str, str]) -> dict[str, str]: ...
    # {"COPILOT_AUTO_UPDATE": "false", "XDG_CACHE_HOME": str(copilot_cache(environ))}
DEFAULT_REDACT_ENV = (..., "COPILOT_GITHUB_TOKEN")
CREDENTIAL_PATHS["copilot-cli"] = ("~/.copilot",)

# src/l4/agents/credentials.py: credential_variable("copilot-cli", any) == "COPILOT_GITHUB_TOKEN"
# src/l4/availability/cooldown.py: IDENTITY_ENV["copilot-cli"] = ("COPILOT_GITHUB_TOKEN",)
# src/l4/sandbox/base.py
NO_LOGIN_BIND = frozenset({"copilot-cli"})                    # its login paths are hidden in its own sandbox too

# src/l4/availability/vendor.py
MODEL_FAMILIES += ((re.compile(r"^grok-"), "xai"), (re.compile(r"^mai-"), "microsoft"))
ROUTED_ADAPTERS = ("kiro-cli", "copilot-cli")
COPILOT_ROUTED_DEFAULT: RoutedSet                             # from task 0.1's help-config.txt; source "built-in"
ROUTED_DEFAULTS: dict[str, RoutedSet] = {"kiro-cli": ROUTED_DEFAULT, "copilot-cli": COPILOT_ROUTED_DEFAULT}
def is_routed(profile: Profile) -> bool: ...                  # adapter in ROUTED_ADAPTERS and model blank or auto
def built_in_routed(name: str, profile: Profile) -> RoutedSet: ...  # ROUTED_DEFAULTS[adapter], else ROUTED_DEFAULT

# src/l4/provision/catalog.py
COPILOT_VERSION = "1.0.102"
COPILOT_DOWNLOAD = "https://github.com/github/copilot-cli/releases/download"
COPILOT_SHA256: dict[str, dict[str, str]]                     # §5.4; keys of PLATFORM_KEYS below
COPILOT_MEMBER = "copilot"
COPILOT_MEMBER_MAX = 512 * 1024 * 1024
ADAPTER_BINARIES["copilot-cli"] = "copilot"
ADAPTER_PINS["copilot-cli"] = COPILOT_VERSION
SUPPORTED_MAJORS["copilot-cli"] = 1                           # derived from the pin
MAJOR_WORDS["copilot-cli"] = MajorWords("Copilot CLI", "Copilot CLI {major}", "copilot {supported}.x", T18)
ARCHIVE_ADAPTERS = ("kiro-cli", "copilot-cli")                # installed from a held-digest archive
def copilot_platform(platform: str, libc: object = _HOST_LIBC) -> str: ...
def copilot_archive_url(version: str, key: str) -> str: ...   # f"{COPILOT_DOWNLOAD}/v{version}/copilot-{asset}.tar.gz"
def copilot_digest(version: str, key: str) -> str | None: ...
def copilot_unheld_text(version: str, source: str) -> str: ...  # T19

# src/l4/provision/install.py
def _install_copilot(ctx: _Ctx, tool: ToolSpec) -> None: ...

# src/l4/provision/readiness.py
HUMAN_STEPS[("copilot-cli", "subscription")] = HUMAN_STEPS[("copilot-cli", "api_key")] = (T25a, T25b)
```

### 5.2 argv per mode

`<common>` = `copilot --output-format json --no-ask-user --no-auto-update --no-custom-instructions
--disable-builtin-mcps --disable-client-telemetry --disallow-temp-dir --session-id <id> --usage-output-file
<step>/copilot-usage.json --model <model>`. The prompt is on stdin, except in the hello.

| Mode | argv after `<common>` | cwd |
|---|---|---|
| judge (judges, clarifier, readiness, `s1_judge` stand-in) | `--available-tools=l4_no_tools` | `<step>/judge-cwd` (empty) |
| hello (probe) | `--available-tools=l4_no_tools -p "<hello prompt>"` (the usage file and home in the probe's temp dir) | `<temp>/cwd` (empty) |
| read_only (delegate) | `--available-tools=view,grep,glob` | the detached, masked worktree |
| implement | `--allow-tool=write [--allow-tool=shell(<first word of gate_prefix>:*)] --add-dir <step> [--additional-mcp-config @<step>/copilot-mcp.json --allow-tool=<server> …]` | the worktree |

No mode ever has an argv entry equal to `--available-tools` or `--available-tools=`, or starting with
`--allow-all`, `--yolo`, `--deny-tool` or `--sandbox`.

### 5.3 Environment and private home

Run: `req.env` (the allow-list) + `COPILOT_HOME=<step>/copilot-home` + `COPILOT_AUTO_UPDATE=false` +
`XDG_CACHE_HOME=<step>/xdg-cache` (made by `write_run_cache(step, req.host_env)`: `xdg-cache/copilot/pkg` is a link to
`copilot_cache(req.host_env)/copilot/pkg`); without `COPILOT_ALLOW_ALL`; `COPILOT_GITHUB_TOKEN` only through the
credential loader. `<step>/copilot-home/settings.json` = `{"autoUpdate": false, "disableAllHooks": true, "memory":
false, "includeCoAuthoredBy": false}` (indent 2).
Probe steps: `probe_env(ctx, …)` + `copilot_env(ctx.environ)`; the hello adds the credential and its temp
`COPILOT_HOME`. Provisioning and doctor `--version` reads: their environment + `copilot_env(env)`.

### 5.4 The sha256 table

Source: `https://github.com/github/copilot-cli/releases/download/v1.0.102/SHA256SUMS.txt`, fetched with curl on
2026-10-22 [V here]; that file's own sha256 is `8753dd200b4d5c6d1989b7ffc2804b5762f9bf5a3ddee5e098aac4d78f89f4d2`.
linux-arm64 was recomputed over the bytes by the spike [V]; the others are as published until task 0.1 recomputes
them. Sizes [V here]: the archive's `Content-Length` and the member's tar header size.

| key | asset | sha256 | archive bytes | `copilot` bytes |
|---|---|---|---|---|
| `linux-x64` | `copilot-linux-x64.tar.gz` | `cabbb04a88a8034ddfa21234cbd52b7676536aec2b292624e6fd6796f891a8ff` | 128,117,626 | 197,462,848 |
| `linux-arm64` | `copilot-linux-arm64.tar.gz` | `634ee7cc4fa4b7447ac41e2c3ce54928d8f5214f418954e3af36f372e849c9c9` | 129,124,281 | 193,334,016 |
| `linux-x64-musl` | `copilot-linuxmusl-x64.tar.gz` | `7e6d64a86b287105415357d158b459bdaede840de797e03677213d5419a597c9` | 123,390,875 | 196,258,160 |
| `linux-arm64-musl` | `copilot-linuxmusl-arm64.tar.gz` | `995c180500e741688c10e4e2368059ee2751fcc8812bdc58337e4ac920ef2971` | 119,704,585 | 188,238,736 |
| `darwin-x64` | `copilot-darwin-x64.tar.gz` | `7a2af746ce5d11e2be486f06d85ce2fc620d5965413c8088fea8ceb2b1d9cb54` | 125,014,508 | 188,215,792 |
| `darwin-arm64` | `copilot-darwin-arm64.tar.gz` | `606f9539b88af1198523f671ffeeb6e58571ab71564252efbc3b2196f1ed3f2b` | 118,403,475 | 180,666,640 |

`prereqs.sh`: `COPILOT_SHA256_X86_64` = linux-x64, `COPILOT_SHA256_AARCH64` = linux-arm64,
`COPILOT_SHA256_X86_64_MUSL` = linux-x64-musl, `COPILOT_SHA256_AARCH64_MUSL` = linux-arm64-musl.

### 5.5 Texts

Run details (`RunResult.detail`) and errors:
- T1 `copilot was not found on the agent PATH` (AdapterError)
- T2 `the prompt is empty; copilot-cli reads its prompt from stdin` (AdapterError)
- T3 `copilot-cli judge called a tool (<toolName>)`
- T4 `copilot-cli delegate called a tool outside the read set (<names, sorted, joined by ", ">)`
- T5 `copilot-cli found no credential (set COPILOT_GITHUB_TOKEN)`
- T6 `copilot-cli could not authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)`
- T7 `copilot-cli reported a rate limit (session.error 429)`
- T8 `copilot-cli hit a rate limit (HTTP 429); the harness stopped the run (it never waits for a limit)`
- T9 `copilot-cli was waiting out a rate limit when the run timed out`
- T10 `copilot-cli reported that the AI credits are used up (session.error 402)`
- T11 `copilot-cli reported an error (<errorType or unknown>, status <statusCode or none>)`
- T12 `copilot-cli exited with code <n>`
- T13 `copilot-cli could not extract its bundled package (the L4 package cache is cold or not writable): run l4 doctor
  --fix`
- T14 `copilot-cli was stopped after 20 denied tool calls in a row: its permission rules refuse what it tries`

Limit sources: `copilot.session_error`, `copilot.turn_retry`, `copilot.model_call_failure`. Credits source:
`copilot.usage_file`.

Probe:
- T15 `COPILOT_GITHUB_TOKEN is not set` (the `auth` step)
- T16 `copilot-cli has no headless quota query` (the skipped `quota` step)
- T17 `copilot-cli hello called a tool (<toolName>)`
- T17a `copilot-cli was retrying a rate limit (hello)`

Major gate:
- T18 `{binary} {version} is Copilot CLI {major}; L4 runs Copilot CLI {supported}: install copilot {pin} (in CI l4
  doctor --ci --fix installs it; l4 doctor prints the command for this machine); Copilot CLI {major} support comes in
  a later L4 release`. The derived texts follow `MajorWords` as for Kiro, for example `found 2.0.0 (Copilot CLI 2),
  need copilot 1.x (pinned 1.0.102)` and `copilot reports no version, so its Copilot CLI major cannot be checked`.
- T18b the load error of `ci.cli_versions`: `ci.cli_versions: copilot-cli: <value> is Copilot CLI <major>; this harness
  runs Copilot CLI 1 (L4-OCG-001, L4-OCG-006); a major moves with an L4 release, not with configuration`
  (`major_config_error` names L4-OCG-006 for `copilot-cli` only; the Kiro and OpenCode texts are unchanged).

Install:
- T19 `copilot <version> (<source>) has no sha256 in this harness (it holds 1.0.102): install it yourself and keep it,
  or hold one of those`
- T20 `cannot download copilot <version> from <host> (<reason>): that version may no longer be served; hold another
  version in ci.cli_versions (one the harness holds) or report it`
- T21 `<the IntegrityError text>; do not install it by hand: report it, or hold another version in ci.cli_versions
  (one the harness holds)`
- T22 `copilot is missing from the Copilot CLI archive`; `copilot in the Copilot CLI archive is not a regular file`;
  `copilot in the Copilot CLI archive is larger than 536870912 bytes`; `the copilot member of the Copilot CLI archive
  is larger than its header says`
- T23 `copilot <version> did not extract its package into <cache>/copilot/pkg (copilot --version ran with
  XDG_CACHE_HOME=<cache>)`
- T24 manual command, Linux: `curl -fsSL -o <asset> <url> && echo "<digest>  <asset>" | sha256sum -c - && tar -xzf
  <asset> copilot && mkdir -p ~/.local/bin && install -m 755 copilot ~/.local/bin/copilot &&
  XDG_CACHE_HOME=<cache> COPILOT_AUTO_UPDATE=false ~/.local/bin/copilot --version`; macOS: the same with `shasum -a
  256 -c -` in place of `sha256sum -c -`; a version with no digest: `install copilot <version> yourself from <url>
  and keep it`.

Readiness:
- T25a `create a fine-grained personal access token owned by your personal account (not an organization) with the
  Copilot Requests permission (classic ghp_ tokens are refused)`
- T25b `store it as the masked CI variable COPILOT_GITHUB_TOKEN`

prereqs.sh PRQ-22:
- DETAIL `copilot ${v:-missing} at ${p:-none} (pinned $COPILOT_VERSION)`, plus `; Copilot CLI ${v%%.*}; L4 runs Copilot
  CLI ${COPILOT_VERSION%%.*}` for another major
- skip `report PRQ-22 SKIP "Copilot CLI" "pass --with-copilot to install"`
- digest failure on stderr `sha256 differs: when COPILOT_VERSION is set, set the four COPILOT_SHA256_* to its digests`

SPEC §3.2 commented profile (the model id is one that task 0.1 recorded; `claude-sonnet-5.5` until then):

```yaml
  # copilot:                       # GitHub Copilot CLI, experimental, in no default chain (L4-FAC-013)
  #   adapter: copilot-cli
  #   model: claude-sonnet-5.5     # pin one: no model runs auto, which is routed (L4-FAC-020)
  #   auth: api_key                # COPILOT_GITHUB_TOKEN: a fine-grained PAT with Copilot Requests (L4-PRV-049)
  #   vendor: anthropic
```

### 5.6 Touch points

| File | Change | Task |
|---|---|---|
| `tests/fixtures/recorded/copilot/1.0.102-byok/` → `tests/fixtures/recorded/copilot-cli/1.0.102-byok/` | moved, `README.txt` added | 0.2 |
| `tests/fixtures/recorded/copilot-cli/1.0.102-notoken/`, `docs/live/copilot-cli/README.md` | new: no-token evidence | 0.1 |
| `src/l4/provision/catalog.py` | pin, table, member, platform, URL, `ADAPTER_*`, `SUPPORTED_MAJORS`, `MAJOR_WORDS`, `ARCHIVE_ADAPTERS`, `manual_command` | 1.1 |
| `src/l4/config/defaults.py` | `copilot_cache`, `copilot_env`, `DEFAULT_REDACT_ENV`, `CREDENTIAL_PATHS` | 1.2 |
| `src/l4/agents/credentials.py`, `src/l4/availability/cooldown.py`, `src/l4/provision/readiness.py` | variable, `IDENTITY_ENV`, `HUMAN_STEPS` | 1.2 |
| `src/l4/sandbox/base.py`, `src/l4/sandbox/bwrap.py` | `NO_LOGIN_BIND` | 1.2 |
| `src/l4/availability/vendor.py`, `src/l4/config/schema.py` | families, `ROUTED_ADAPTERS`, `COPILOT_ROUTED_DEFAULT`, `built_in_routed`, `resolve_vendor`, the validator | 1.3 |
| `src/l4/agents/activity.py` | `copilot_signals` | 1.4 |
| `src/l4/agents/copilot_cli.py` | the adapter: parse, watcher, usage (2.1); run, argv, env, MCP (3.1); probe (4.1) | 2.1, 3.1, 4.1 |
| `tests/unit/agents/test_copilot_cli_spike.py` → `tests/unit/agents/test_copilot_cli.py` | replaced | 2.1 |
| `scripts/runner/prereqs.sh`, `docs/runner/README.md` | PRQ-22 | 2.2 |
| `src/l4/provision/install.py`, `src/l4/provision/runner.py`, `src/l4/doctor/checks_env.py` | `_install_copilot`, warm-up, `ARCHIVE_ADAPTERS` rules, version env | 3.2 |
| `src/l4/availability/probes.py` | `_binary` env for `copilot` | 4.1 |
| `src/l4/agents/factory.py`, `src/l4/config/roles.py`, `plugins/l4/skills/l4/scripts/yolo_preflight.py` | registration, roles, `Factory.routed` fallback | 4.2 |
| `tests/unit/agents/test_login_lock_coverage.py` | `copilot_cli.py` is GATED; a copilot-cli profile in its dynamic tests | 4.2 |
| `src/l4/verifier/selection.py`, `src/l4/delegate/independence.py`, `src/l4/doctor/checks_delegate.py`, `src/l4/delegate/run.py` | `seat_of`, routed rules, `DELEGATE_SERVES`, `ADAPTERS_THAT_SERVE`, masked tree | 4.3 |
| `src/l4/sim/scenarios.py`, `src/l4/sim/replay.py`, `src/l4/sim/runner.py`, `src/l4/sim/builtin/scenarios/happy-copilot-judge.yaml`, `src/l4/sim/builtin/fixtures/openspec-basic/payloads/judge_pass.copilot.jsonl`, `src/l4/sim/builtin/manifest.py` | replay judge | 5.1 |
| `docs/SPEC.md` | D19 | 6.1 |
| `docs/runbook.md`, `plugins/l4/skills/l4/references/adopt.md`, `CHANGELOG.md` | D19 | 6.2 |
| `tests/fixtures/recorded/copilot-cli/1.0.102/`, `src/l4/recorded_versions.json`, `docs/live/copilot-cli/README.md` | the live recording | 8.1 |

Not changed: `src/l4/ci/github.py` (`credential_secrets` and the cache paths already cover it), `gate.OAUTH_ADAPTERS`,
`src/l4/skills_cli.py`, the delegate's prompt (its tool sentence is generic; no prompt version change), `l4 init`.

## 6. Unverified claims and who settles them

| Claim | Label | Settled by |
|---|---|---|
| The name `l4_no_tools` gives no tool, like `l4_none` (F10) | [I] | task 8.1 records the judge's `session.info`; R6 |
| Whole-archive member list of the six tarballs (F21) | [V] | task 0.1: one member `copilot`, 0755 |
| Which command extracts the package (F23) | [V] | task 0.1: `--version` |
| `XDG_CACHE_HOME` on macOS (F35) | [V] no effect | task 0.1 |
| MCP file format (F26), the MCP allow rule (F27) | [G], [I] | task 8.1 runs an implementer with Serena; R10 |
| Nested instruction files under `--no-custom-instructions` (F28) | [U] | the masked tree (D4); R11 |
| Exact model ids of 1.0.102 (F29) | [U] | task 0.1 (`help-config.txt`) |
| `assistant.message.model` under GitHub routing (F30) | [I] | task 8.1; D10 believes it only under `auto` |
| `totalNanoAiu` unit (F31) | [G] | task 8.1; R8 |
| GitHub-routed error shapes (F32) | [G] | task 8.1; R4 |
| Linux x64 runs; minimum glibc (F34) | [I], [G] | task 0.1 (x64 container) and task 8.1 (ubuntu-24.04 x64); R7 |
| `apply_patch` approval by `--allow-tool=write` (F36) | [U] | task 8.1 if the plan has an OpenAI model; R6 |
| The GitHub-routed timing of the 429 retry (F7) | [G] | task 8.1 only if a 429 happens; R3 |
| The CLI follows the `pkg` link of the per-run cache (F37) | [V] | task 0.1 |
| The macOS keychain login is not isolated by `HOME` | [I] | R12 |
| The network hosts the CLI reaches | [G] | R13 |
| An org policy that forces Copilot's sandbox | [G] | non-goal; R14 |

## 7. Risks

- **R1 Credential ownership and terms.** The only credential is one person's PAT, billed to that seat. ToS says a
  login is not shared by several people. The runbook says so; the owner decides per team. The org-billed path is a
  non-goal (§3).
- **R2 The release gate holds the release.** Nothing ships until task 8.1 has a token. That is the point: every
  GitHub-routed shape is unmeasured until then.
- **R3 A short limit costs a profile switch.** The watcher stops at the first 429, so a per-minute limit that the CLI
  would have waited out in 30 s moves the step to the next profile and cools this one for
  `availability.default_cooldown`. That is the rule of every L4 adapter (never wait for a limit); task 8.1 records
  whether a GitHub-routed 429 carries a reset time that could shorten the cool-down.
- **R4 GitHub-routed error wording** (F32). A rejected token or exhausted credits may come with another `errorType` or
  status. D6 maps by status and by `errorType: "authentication"`; an unmapped shape is `error`, which costs one attempt,
  not a wrong verdict. Task 8.1 records and fixes.
- **R5 The shell rule is coarse** (F16). `shell(.venv/bin/python:*)` also allows `.venv/bin/python -c …`. The same
  posture as codex's `workspace-write`: L4's sandbox is the boundary, and the gates run the tests again outside the
  agent.
- **R6 Tool names vary by model** (F11, F36), and an empty allow-list means every tool. The fail-closed sets name both
  spellings (`grep`, `rg`); the argv test forbids an empty list. If `--allow-tool=write` does not approve
  `apply_patch`, an OpenAI-served implementer is denied every edit and the tripwire stops it (T14): a visible failure.
- **R7 Platforms.** A gnu build on an old glibc may not start. `_verified` fails the action with both versions, and
  the person can hold musl by hand. The musl and darwin builds are as published until task 0.1.
- **R8 Credits.** If `totalNanoAiu` is not credits × 10^9, `budget.cost.credits` is off by a factor; no dollar total
  depends on it.
- **R9 Size.** The binary is about 190 MB and the package about 220 MB, per platform and version, in the agent-CLI
  cache. Only a repository whose chains name copilot-cli installs it (`adapters_in_use`).
- **R10 MCP injection** is unrun (F26, F27). A wrong shape makes Serena unavailable to a Copilot implementer: the
  step still runs.
- **R11 Repository guidance.** `--no-custom-instructions` [V help] plus the sandbox masks; the delegate's masked tree.
  A guidance file the agent views on purpose is read as data, as for every adapter (L4-SEC-002).
- **R12 macOS keychain.** With the sandbox off (macOS), a run with no `COPILOT_GITHUB_TOKEN` may still find a keychain
  login. The probe fails without the variable (D11), so no role selects such a profile; a direct run is a developer's.
- **R13 Network.** The hosts are not documented; the agent sandbox has the network, as for every adapter.
- **R14 Org policy.** A policy that forces Copilot's own sandbox would break shell commands inside bwrap. The hello
  and the run then fail visibly.
- **R15 Fast release cadence** (near daily 1.0.x). Exact pin, digest table, major gate, and a recording per pin.
- **R16 The agent can write its own private home.** `--add-dir <step>` covers `copilot-home/` and the usage file. The
  settings are read at start; the usage file is written by the CLI at the end and read as a regular file of at most
  1 MiB. The same posture as Kiro's private home in the step directory.

- **R-mac A macOS run with its own `HOME` extracts the package again** (F35): about 220 MB and a few seconds per run on
  a developer Mac. macOS has no sandbox, so this costs time and disk only; task 3.1 says where that HOME lives.

## 8. Decisions this design added

The delegate's list did not cover these; the orchestrator checks them:
1. `--model auto` when the profile has no model (D2).
2. `COPILOT_AUTO_UPDATE=false` instead of `CI` (D2; L4-SEC-040).
3. The stop mechanism is `on_line` (`CopilotStop`), not `req.interrupt` (D7); a timed-out run with a 429 call
   failure or a rate-limit retry is `rate_limited` (D6 rule 2); `permission_blocked` for the tripwire (D7); the
   cool-down is `availability.default_cooldown` (D7).
4. `resume` is False in the caps (no resume flag was observed; the proposal's True had no evidence) (§5.1).
5. The delegate's tree is masked (D4).
6. A pinned model's served id only detects a mismatch; `auto`'s is believed (D10).
7. `grok-` → `xai`, `mai-` → `microsoft`; Copilot's own built-in routed set (D10).
8. The `auth` step fails without the variable whatever `auth:` says (D11).
9. `NO_LOGIN_BIND`: `~/.copilot` is never bound into any sandbox (D12).
10. gnu when a glibc is found, else musl, no threshold; macOS installs the tarball (D13).
11. `ARCHIVE_ADAPTERS` generalises the Kiro rules of `plan_fixes`, `_verified` and `_apply` (D13).
12. The cache under `$L4_HOME/copilot-cache` (D14).
13. PRQ-22, opt-in with `--with-copilot` (D16).
14. The fixtures live under `copilot-cli/`, not `copilot/` (D17).
15. The simulation scenario (D18).
16. A run's `XDG_CACHE_HOME` is a fresh per-run directory whose `copilot/pkg` links to the warm cache, so the
    agent's own tools keep a writable cache (D14); probes, provisioning and doctor use the cache itself.
17. The `ci.cli_versions` load error of another Copilot major names L4-OCG-006 (T18b); the Kiro and OpenCode texts keep
    `(L4-OCG-001, L4-OCG-005)`.
18. A Copilot implementer's Serena runs with Serena's own `copilot-cli` context (D5, SCN-FAC-50).
