# Proposal: GitHub Copilot CLI as an L4 agent CLI (feasibility spike, 2026-10-22)

## Verdict

**Feasible, with conditions.** Copilot CLI 1.0.102 has what an L4 adapter needs:
- a headless mode that takes the prompt on stdin;
- a JSONL event stream that names the served model;
- a usage file;
- a tool allow-list that gives a truly tool-less judge and a read-only delegate;
- a deny-not-ask rule in prompt mode;
- pinnable artifacts with published sha256;
- a fresh-HOME, bubblewrap-compatible run on Linux.

Four conditions stand before an adapter is worth building:

1. **A credential the owner can actually use.** It must be one of these:
   - a *user-owned* fine-grained PAT with the "Copilot Requests" permission, which bills that one person's seat. Classic PATs are refused.
   - on GitHub Actions in an organization repository: the workflow's own `GITHUB_TOKEN` with `permissions: copilot-requests: write`. That path collides with L4's rule that forge tokens never reach an agent (see R1).
2. **One live GitHub-routed run.** Every output, error and usage shape below was measured in BYOK mode (the CLI driving a local model, no GitHub account). The GitHub-routed shapes are inferred until a run with a real Copilot token records them.
3. **The adapter interrupts on the CLI's own rate-limit retry.** The CLI waits out a 429 itself, honouring `Retry-After`. L4 adapters never wait for a limit.
4. **No max-turns cap exists.** The step's `timeout_s` is the only bound on a looping run.

Effort if the owner proceeds: **M–L**. That is about 20–25 files: the adapter plus the ~20 touch points every adapter has. It is kiro-cli-shaped work, without the agent files.

## Labels

Each claim carries one label:
- **[V]** verified in this spike: a command I ran, a file I read, or an official page fetched today.
- **[V-BYOK]** verified with the CLI driving a local OpenAI-compatible model (`COPILOT_OFFLINE=true`, `COPILOT_PROVIDER_BASE_URL`). The GitHub-routed path was not exercised.
- **[I]** inferred.
- **[G]** guessed.

Doc quotes were fetched on 2026-10-22. Some passed through a summarising fetch tool, so recheck the exact wording before quoting it elsewhere.

## 1. What was run

- **Version.** `@github/copilot@1.0.102` is npm `latest` and the GitHub release marked Latest (2026-10-21). `1.0.103-0` is a prerelease. `copilot --version` prints `GitHub Copilot CLI 1.0.102.` [V]
- **Install.** `npm install --prefix <scratch> --ignore-scripts --save-exact @github/copilot@1.0.102`. [V]
  - The package has no install scripts.
  - `bin/copilot` is a ~1 KB Node ESM shim (`npm-loader.js`). It `spawnSync`s the native binary from the optional dependency `@github/copilot-<platform>-<arch>`. The platforms are linux x64/arm64, linuxmusl x64/arm64, darwin, win32.
  - The native binary embeds Node (the log says `Node.js version: v24.20.0`).
  - So the npm route needs a system Node only for the shim. The docs say "Node.js 22 or later" [V doc]. The binary needs none.
- **Release tarball.** `copilot-linux-arm64.tar.gz` from release `v1.0.102` holds a single 193 MB binary. Its sha256 `634ee7cc…c9c9` matches the release's `SHA256SUMS.txt` [V]. That file also lists linux-x64, both musl builds, darwin, win32 and the npm tgz files.
- **No credentials.** Every run used an empty temporary `HOME`/`XDG_*`, `env -i`, and no token variable. No login, no device flow.
- **BYOK runs.** These went through a local logging proxy, which recorded the tool list each request offered the model and could inject HTTP 401/402/429/500. Models: `qwen3.5:2b` and `gpt-oss:20b`.
- **Linux.** An Ubuntu 24.04 arm64 container (glibc 2.39, bubblewrap 0.9.0) ran the release binary [V]:
  - `--version` and the unauthenticated `-p` worked with no Node installed;
  - the package cache behaved as described in row 6;
  - one BYOK run inside an L4-like `bwrap` (read-only `/`, tmpfs `HOME` and `/tmp`, rw worktree and step dir, `--clearenv`) answered correctly.
- **Live GitHub-routed test: BLOCKED.** No Copilot-entitled GitHub token is available to the harness. The secret store holds no GitHub token at all, and a classic PAT would be refused anyway.

## 2. Evidence

### 2.1 Headless auth (the first possible deal-breaker)

| Claim | Label | Source |
|---|---|---|
| Token precedence: `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN` > stored keychain login > GitHub CLI (`gh`) fallback. An env variable silently overrides a stored login. | [V] | `copilot help environment`, `copilot login --help`, docs `…/set-up-copilot-cli/authenticate-copilot-cli` |
| Supported tokens: fine-grained PAT (`github_pat_`) "owned by your personal account (not an organization)" with the **Copilot Requests** permission ("only available on user-owned fine-grained personal access tokens"); OAuth from `copilot login` or the `gh` app; GitHub App user-to-server (`ghu_`). **Classic PATs (`ghp_`) are not supported.** | [V] | same page; `copilot login --help` says "Classic personal access tokens (ghp_) are not supported." |
| GitHub Actions: "Using `GITHUB_TOKEN` (recommended for organization-owned repositories): No PAT or stored secrets required". The workflow needs `permissions: copilot-requests: write`. Org policy "Allow use of Copilot CLI billed to the organization" is "enabled by default for organizations with Copilot CLI turned on". | [V] | docs `…/automate-copilot-cli/automate-with-actions`, `…/copilot-cli/use-copilot-cli-in-actions` |
| A personal-account repository has no organization to bill, so the `GITHUB_TOKEN` path needs an org repo. The PAT path works anywhere, self-hosted and GitLab runners included. | [I] | the docs only describe org repos |
| Enterprise: Copilot CLI is a client toggle under AI controls. "Users must have an assigned GitHub Copilot seat." | [V doc] | `…/administer-copilot-cli-for-your-enterprise` |
| A token without the "Models" permission may get a 403 (an unmerged docs PR says so). | [G] | third-party mirror of a docs PR; not in the official page |
| With no credential: exit **1**, **empty stdout even with `--output-format json`**, and stderr `Error: No authentication information found.` plus a hint list (`/login`, the three variables, `gh auth login`). Same on macOS and Linux, with or without `CI=true`. | [V] | runs in this spike |
| Credential storage: OS keychain, service `copilot-cli` (macOS Keychain, libsecret on Linux). Without a keychain, the login offers plaintext `~/.copilot/config.json`. `COPILOT_HOME` moves `~/.copilot`. | [V doc + help] | auth page; `copilot help environment` |
| On macOS an empty `HOME` does not isolate the keychain: the keychain is per user, not per `HOME`. | [I] | macOS behaviour; no copilot login exists here to prove it either way |

### 2.2 Non-interactive output, exit codes, error shapes

| Claim | Label | Source |
|---|---|---|
| `-p/--prompt <text>`, **or piped stdin with no `-p`**, runs one prompt and exits. Piped stdin avoids Linux's 128 KiB single-argument cap that kiro-cli hits. | [V-BYOK] | stdin run: exit 0, reply `L4-OK` |
| `--output-format json` emits JSONL `{type, data, id, timestamp, parentId, ephemeral?}`. The event types L4 needs are listed below this table. | [V-BYOK] | recorded streams (fixtures) |
| No `session.start` and no `session.usage_record` on stdout. They are in `$COPILOT_HOME/session-state/<id>/events.jsonl`, together with the full system prompt (~22 KB) and the user prompt. | [V-BYOK] | session-state files |
| `--session-id <uuid>` presets the session id, and `result.sessionId` echoes it. | [V-BYOK] | run with a fixed UUID |
| `--usage-output-file <f>` writes `totalPremiumRequestCost`, `totalNanoAiu`, `aiCreditsStatus` (`unavailable` under BYOK), `modelMetrics.<model>.usage.{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}`, `agentMetrics`, `currentModel` and `codeChanges`. It is written even for a run that never authenticated (all zeros). | [V-BYOK] | usage files |
| Fatal model errors are a `session.error` event plus exit 1, with stderr **empty**. 401: `errorType: "authentication"` after 3 tries. 402: `errorType: "query"`, `message: "402 …"`, no retry. 500: retried 5 times (~15 s), then `"Failed to get response from the AI model; retried 5 times …"`. An invalid tool call from the model came back as a provider 400 and ended the run with exit 1. | [V-BYOK] | fault-injection runs |
| **429 with `Retry-After: 30`: the CLI waits and retries by itself.** It emits `model.call_failure {statusCode: 429, retryAttempt}` and `assistant.turn_retry {reason: "rate_limit"}` live on stdout, and was still retrying when my 150 s harness timeout killed it (exit 142 is that SIGALRM, not the CLI). Changelog 1.0.32: "Rate-limited sessions now pause queued messages and automatically retry". | [V-BYOK] + [V changelog via research] | the injected-429 run; github/copilot-cli changelog |
| Exit codes for `-p` are not documented; only `copilot workflow run` has a table (0/1/2/130). Changelog 0.0.354: "Exit with nonzero code when `-p` mode fails due to LLM backend errors (auth failures, quota exhaustion…)". | [V doc] | CLI programmatic reference; changelog |
| The GitHub-routed error text for an exhausted allowance and for Copilot's own rate limits ("session"/"weekly" limits) is not documented. A real run must record it. | [G] | docs searched, nothing found |

The event types L4 needs:
- `user.message`;
- `assistant.turn_start` and `assistant.turn_end`;
- `assistant.message {model, content, toolRequests[]}`;
- `tool.execution_start {toolCallId, toolName, arguments}`;
- `tool.execution_complete {toolCallId, success, error{code,message}, result{content}}`;
- `session.info` (for example `Disabled tools: …`, `Unknown tool name in the tool allowlist: "…"`);
- `session.error {errorType, message, statusCode}`;
- a final `{"type":"result","sessionId","exitCode","usage":{premiumRequests,totalApiDurationMs,sessionDurationMs,codeChanges}}` with no `data`.

`*_delta`, reasoning, `model.call_*` and `session.*_loaded` events are `ephemeral` and can be ignored. A run killed from outside has no `result` event.

### 2.3 Tool permissions: a true read-only mode and a confined edit mode

| Claim | Label | Source |
|---|---|---|
| `--available-tools`/`--excluded-tools` decide which tools **the model sees**. `--allow-tool`/`--deny-tool`/`--allow-all-tools` decide approval only, and deny beats allow. | [V] | `copilot help permissions` |
| `--available-tools=view,grep,glob`: the model was offered exactly those three. | [V-BYOK] | proxy log of the request's `tools` array |
| The stream then reported `servers: []` for MCP. That was observed offline, where the built-in servers are off anyway; the adapter passes `--disable-builtin-mcps` regardless. | [I] for the online path | stream `session.mcp_servers_loaded` |
| **An EMPTY allow-list is ignored.** `--available-tools` with no value, or `--available-tools=`, still offered all 17 default tools (bash, view, create, edit, grep, glob, task, sql, …). Never use it to mean "none". | [V-BYOK] | proxy log |
| **Tool-less judge:** `--available-tools=<unknown name>` offered `[]`, and the stream says `Unknown tool name in the tool allowlist`. `--excluded-tools=<every name>` also offered `[]`, but breaks when a version adds a tool. | [V-BYOK] | proxy log |
| Tool names depend on the model. For `gpt-oss` the CLI offered `apply_patch` (instead of create/edit) and `rg` (instead of grep), and `--available-tools=view,grep,glob` produced `view,rg,glob`. | [V-BYOK] | proxy log |
| Prompt mode never asks. A request outside the policy fails with `error.code: "denied"` ("Permission denied because no interactive user response was available…"), the run goes on and exits 0. `--no-ask-user` removes the `ask_user` tool. | [V-BYOK] | the outside-path and gate-rule runs |
| Reads inside the cwd (`view`) ran without any allow flag. Shell commands the CLI deems read-only (`ls`, `echo`) ran with no rule matching them, in runs that carried other `--allow-tool` rules. Writes and other shell commands (`touch`) were denied. | [V-BYOK] | the read-only and gate-rule runs |
| **The proposed implementer argv works.** With `--allow-tool=write --allow-tool=shell(./.venv/bin/python:*) --add-dir <step>`, `create` wrote `./hello2.txt` in the cwd and `<step>/result.json` outside it, exit 0. Controls with `--disallow-temp-dir`: without `--add-dir` the result-file write was denied; with it, it was written. | [V-BYOK] | three implementer-argv runs |
| The system temp directory is allowed by default, which on macOS includes `/private/tmp`. The adapter passes `--disallow-temp-dir` so `--add-dir` is the only way out of the cwd. | [V help] + [V-BYOK] | `copilot help permissions`; the controls above |
| Path policy: by default only the cwd and the system temp dir (`--disallow-temp-dir` removes temp). `--allow-all-tools` does **not** widen paths: `cat /abs/outside` and `cd .. && head outside/…` were denied. | [V-BYOK] | the absolute-path and `cd ..` runs |
| **The path check is a heuristic on the command line, not a boundary.** `python3 peek.py`, a script inside the cwd that reads `../outside/data.txt`, ran and printed the outside file. Confinement must come from L4's sandbox, as for every other adapter. | [V-BYOK] | the script-in-cwd run |
| Shell rules match the command's first word. `--allow-tool=shell(./.venv/bin/python:*)` allowed `./.venv/bin/python -m pytest -q`, but also allows `python -c …`. `shell(./.venv/bin/python -m pytest:*)` matched nothing (denied), and `shell(.venv/bin/python …)` did not match `./.venv/bin/python …`. Multi-word rules are documented for `git`/`gh` subcommands only. | [V-BYOK] + [V help] | three gate-rule runs |
| `--secret-env-vars=NAME` strips the value from the shell tool's environment (`printenv` printed nothing). Without it the value was printed. The CLI strips **its own `COPILOT_GITHUB_TOKEN`** from the shell tool by default. | [V-BYOK] | three env runs (fake values) |
| `COPILOT_ALLOW_ALL=true` (exactly) also trusts the working directory: its skills, plugins, MCP servers and **hooks that run shell commands** load. The adapter must never set it and must drop it from the env. | [V help] | `copilot help environment` |

### 2.4 Pinning, no self-update, platforms

| Claim | Label | Source |
|---|---|---|
| Auto-update is off when `CI`, `BUILD_NUMBER`, `RUN_ID` or `SYSTEM_COLLECTIONURI` is set, and off with `--no-auto-update`, `COPILOT_AUTO_UPDATE=false` or `autoUpdate: false` in `settings.json`. On npm installs it only *reports* a newer version. | [V help] | `copilot help environment`, `copilot help config` |
| Exact pins exist both ways. npm: `@github/copilot@1.0.102` plus platform packages with registry `dist.integrity` (sha512), the same trust level as L4's codex/opencode npm installs. Release tarballs: sha256 in `SHA256SUMS.txt`, recomputed here for linux-arm64, so a `KIRO_SHA256`-style table is possible. | [V] | npm view; download + `shasum -a 256` |
| The official installer (`gh.io/copilot-install`) verifies the checksum only when it can fetch `SHA256SUMS.txt`, and skips silently otherwise. L4 should not run it (as with Kiro). | [V via research] | install.sh as read by the research agent |
| Linux arm64 glibc build runs on Ubuntu 24.04 (glibc 2.39) with no Node. The minimum glibc is undocumented; musl builds exist. | [V] / [G] for older glibc | container run |
| Linux x64 was not run. | [I] | same release, same build |
| Release cadence is near daily (1.0.x), with flag semantics still moving. A recorded-fixture test per pinned version is needed, as for kiro-cli. | [V changelog] / [I] | releases page |

### 2.5 Models, quota, cost

| Claim | Label | Source |
|---|---|---|
| `--model <id>` or `COPILOT_MODEL`. `auto` exists, plus `--reasoning-effort none…max` and `--context default\|long_context`. 1.0.102's built-in list spans Anthropic (claude-opus-5.5, claude-sonnet-5.5, claude-fable-5.x, haiku), OpenAI (gpt-6.x, gpt-5.x incl. codex), Google (gemini-4-argon, 3.x flash), xAI (grok-4.x), Moonshot (kimi-k3) and Microsoft (mai-code). | [V] | `copilot help config` |
| Which models an account may use depends on the plan and policy. | [I] | — |
| Billing since 2026-06-01 is in **GitHub AI Credits** (1 credit = $0.01), priced per token by model; legacy "premium requests" survive only on annual plans until expiry. Monthly allowances: Pro 1,500, Pro+ 7,000, Max 20,000, Business 1,900/user, Enterprise 3,900/user; Free "an allowance". "All plans include Copilot CLI." | [V doc] | `…/get-started/plans`, `…/copilot-billing/models-and-pricing`, github.blog changelog 2026-06-01 |
| Over the allowance, organizations are billed for extra usage by default; with that off, "Usage is blocked until the next billing cycle". | [V doc via research] | `…/usage-based-billing` |
| L4 cost signals: `totalNanoAiu` (very likely AI credits × 1e9), `totalPremiumRequestCost` (legacy) and per-model tokens in the usage file; `result.usage.premiumRequests` on stdout. | [V-BYOK] fields; [G] the unit of `totalNanoAiu` | usage files |
| `--max-ai-credits N` is a **soft** per-session cap (minimum 30; "usage is known only after a model response returns"). | [V help] | `copilot help limits` |
| Remaining quota: the REST billing API reports *consumed* usage (`/users/{u}/settings/billing/ai_credit/usage`, only for self-purchased plans; org variants exist) and nothing about *remaining* credits. Interactive `/usage` shows session and weekly limits; whether it answers headless (like kiro's `chat --no-interactive /usage`) was not tested. | [V doc via research] / [G] headless `/usage` | REST billing docs |
| Per-call input floor (BYOK tokenizer): ~11.5 k tokens with the default tools, ~3.0 k with the three read tools, ~1.9 k tool-less. Per-token billing makes the tool-less judge far cheaper than an agent-mode call. | [V-BYOK] | `lastCallInputTokens` |

### 2.6 Isolation, sandbox, network

| Claim | Label | Source |
|---|---|---|
| `COPILOT_HOME` moves config and state (`config.json`, `settings.json`, `session-state/`, `session-store.db`, `logs/`, `installed-plugins/`). `$COPILOT_HOME/settings.json` is read: `copilot config --list` showed `autoUpdate=false`, `disableAllHooks=true`, `memory=false`, `includeCoAuthoredBy=false` from a hand-written file. | [V] | runs |
| `includeCoAuthoredBy` defaults to **true**, which tells the agent to add a Co-authored-by trailer to commits. The adapter's private home must set it false. | [V help] | `copilot help config` |
| On first run the binary extracts a **~220 MB package** to `$XDG_CACHE_HOME/copilot/pkg/<platform>/<version>/` (Linux default `~/.cache/copilot`; macOS `~/Library/Caches/copilot`). An unwritable `HOME` fails: `Failed to extract bundled package … ENOENT`, exit 1. A pre-extracted cache **mounted read-only** works, and cold extraction into tmpfs took ~0.6 s. | [V] Linux container | runs |
| An L4-like bwrap sandbox works: read-only `/`, tmpfs `HOME` and `/tmp`, `--clearenv`, `--unshare-pid/ipc`, shared net, private `COPILOT_HOME` in the step dir. | [V-BYOK] | Linux container run |
| Copilot's own command sandbox (`--sandbox`, Microsoft MXC, a bwrap backend on Linux with slirp4netns and iptables) is off by default. Nested inside L4's bwrap it would need unprivileged namespaces it does not get: keep it off. An org policy can force it ("a host that can't run the sandbox can't run shell commands at all"). | [V help] / [I] nesting | `copilot help sandbox` |
| Built-in MCP servers (`github-mcp-server`, `githubiq`) load by default. `--disable-builtin-mcps` removes them, and `--additional-mcp-config @file` is the MCP injection point (Serena). | [V help] | `--help` |
| Repo instructions (`AGENTS.md` etc.) load by default. `--no-custom-instructions` disables them. | [V help] | `--help` |
| Network: GitHub auth, model routing (Copilot API), managed-policy fetch, telemetry ("CAFE metrics", OTel off unless configured), update check (off in CI). `--disable-client-telemetry` "does not affect server-side telemetry". The exact host list is not documented. | [V log + help] / [G] hosts | process log, `--help` |
| Under BYOK with `COPILOT_OFFLINE=true` the CLI makes no GitHub calls at all. | [V-BYOK] | runs |

### 2.7 Terms

| Claim | Label | Source |
|---|---|---|
| GitHub documents and endorses scripted and CI use: programmatic `-p` examples and a GitHub Actions workflow with `COPILOT_GITHUB_TOKEN` and `--no-ask-user`. | [V doc] | `…/automate-copilot-cli/run-cli-programmatically`, `…/automate-with-actions` |
| Acceptable Use Policies forbid "using our servers for any form of excessive automated bulk activity" and "to place undue burden on our servers through automated means". | [V doc] | `…/acceptable-use-policies/github-acceptable-use-policies` §4 |
| Terms of Service: "a single login may not be shared by multiple people"; "You may not share API tokens to exceed GitHub's rate limitations"; machine accounts are allowed, and the owner is responsible for them. | [V doc via research] | `…/github-terms/github-terms-of-service` |
| One person's PAT driving a team's CI is not addressed explicitly. It reads as that person's usage on that person's seat. A team should use the org-billed `GITHUB_TOKEN` path or seats for machine users. | [I] — owner/legal call | — |
| CLI LICENSE: install-and-run plus unmodified redistribution inside a larger product. Nothing restricts automation. | [V] | `LICENSE.md` in the npm package |

### 2.8 The Copilot coding agent (now "cloud agent") as an alternative mode

| Claim | Label | Source |
|---|---|---|
| Triggered by assigning an issue to `copilot-swe-agent[bot]` (REST or GraphQL), or by the agent-tasks API (preview, user-to-server tokens only). It runs on GitHub Actions, opens its own PR, "only works with repositories hosted on GitHub", and is capped at a 59-minute session. It is customised via `.github/workflows/copilot-setup-steps.yml`, and its firewall is not compatible with self-hosted runners. Plans: Pro and up (Free excluded). | [V doc via research] | `…/cloud-agent/use-cloud-agent-via-the-api`, `…/customize-the-agent-environment`, plans page |
| **Not a fit as an L4 adapter.** L4 runs the agent CLI itself, in its own job and sandbox, one red/green step at a time, with its own result contract, gates and independent judge. The cloud agent is a whole-task black box on GitHub's infrastructure that owns its branch and PR, cannot run on GitLab, and gives L4 no step boundary to gate. At most it could be an *upstream* source of PRs that L4 verifies. That would be a separate feature, not this adapter. | [I] | — |

## 3. Adapter design sketch

The prototype `src/l4/agents/copilot_cli.py` is **unregistered**: no factory entry, no role, no pin. It has 12 unit tests against recorded 1.0.102 BYOK streams in `tests/fixtures/recorded/copilot/1.0.102-byok/`. It builds the command lines below and parses the stream. It is a starting point, not product code.

**Adapter name:** `copilot`, binary `copilot` (owner decision; `copilot-cli` mirrors `kiro-cli`).

**Common argv**, prompt on **stdin**:

```
copilot --output-format json --no-ask-user --no-auto-update --no-custom-instructions --disable-builtin-mcps
        --disable-client-telemetry --disallow-temp-dir --session-id <uuid>
        --usage-output-file <step>/copilot-usage.json [--model M]
```

Every run happens:
- with env `COPILOT_HOME=<step>/copilot-home`, a fresh directory holding only `settings.json`: `{autoUpdate:false, disableAllHooks:true, memory:false, includeCoAuthoredBy:false}`. It is the kiro private-home pattern: the session state there holds the whole prompt, so it stays in the step's private dir.
- with `COPILOT_ALLOW_ALL` removed;
- with `COPILOT_GITHUB_TOKEN` delivered by `credential_loader`, never `GH_TOKEN`/`GITHUB_TOKEN`, which are forge tokens in L4;
- with `XDG_CACHE_HOME` pointing at an L4 cache that holds the extracted package, read-only once warm.

| Role / mode | Mode flags | cwd | Reply |
|---|---|---|---|
| judge, clarifier, readiness, hello (`judge`) | `--available-tools=l4_no_tools` | `judge_workdir` (empty) | last non-empty `assistant.message.content` → `attach_judge_reply`; **fail closed** on any `tool.execution_start` |
| delegate (`read_only`) | `--available-tools=view,grep,glob` (no allow flag; reads in the cwd auto-approve) | detached worktree | `attach_read_only_reply(last message after the last tool call)`; **fail closed** on any tool outside `{view, grep, rg, glob}` |
| implementer (`implement`) | `--allow-tool=write`, `--allow-tool=shell(<gate binary>:*)`, `--add-dir <step dir>` (the result file lives there) [V-BYOK]; `--additional-mcp-config @<step>/mcp.json` + `--allow-tool=<server>` for Serena [I, not run] | worktree | prompt contract: `$L4_RESULT_PATH` → `attach_file_result` |

**Parser.** The fields come from these events:

| Field | Source |
|---|---|
| `session_id`, `exit_code` | `result` |
| `model_resolved` | `assistant.message.model`, which makes `served_model=True` possible: unlike kiro, no session-file read is needed |
| `final_text`, `last_message` | `assistant.message.content` |
| `permission_denials` | `tool.execution_complete.error.code == "denied"` |
| tool names | `tool.execution_start` |

Status mapping:
- `session.error`: `authentication`, 401 or 403 → `auth`; 429 → `rate_limited`; 402 → `quota` (credits; GitHub wording [G]); 5xx → `error` with `transient=True`.
- Exit 1 with no stream and the "No authentication information found" stderr → `auth`.

**Rate limits.** Add `copilot_signals` to `l4.agents.activity` (tool start/end from `tool.execution_*`). When an `assistant.turn_retry {reason: "rate_limit"}` arrives, the reader trips `req.interrupt` and the run ends `rate_limited` with a cool-down. This is the claude adapter's rate-limit-interrupt pattern. Otherwise the CLI silently waits out `Retry-After` inside the step.

**Usage.** Read the `--usage-output-file` document:
- tokens summed over `modelMetrics`;
- `credits = totalNanoAiu / 1e9` (AI credits, never added to `cost_usd`), with `credits_source: "copilot.usage_file"`.

A dollar figure needs the per-token price table and stays out of v1.

**Caps.**

```
AgentCaps("prompt_contract", resume=True, preset_session_id=True, max_turns=False, budget_cap=False,
          mcp_injection=True, quota_query=False, worktree_cwd=True, served_model=True)
```

`--max-ai-credits` (soft, ≥30) could back `budget_cap` later.

**Probe ladder.**
- *binary*: `copilot --version` plus a major gate (1.x) in `SUPPORTED_MAJORS`.
- *auth*: `credential_auth` passes on a set `COPILOT_GITHUB_TOKEN`. There is no `whoami`; a stored keychain login can only be proven by the hello [I].
- *quota*: skipped, unless headless `/usage` turns out to work [G].
- *hello*: the judge argv with `-p "Reply with exactly: L4-OK"`, since the probe runner has no stdin.

**Pin and install.** Either route works:

| Route | How | Trade-off |
|---|---|---|
| (a) npm, the cheapest | `NPM_PACKAGES["copilot"] = "@github/copilot"`, installed by the existing `_npm_install` (`--save-exact`; npm's sha512 integrity) | adds Node ≥ 22 just for the shim |
| (b) tarball, cleaner | a `COPILOT_SHA256` table per version and platform from `SHA256SUMS.txt`, installed like kiro's `_install_kiro` (one binary, no zip members) | no Node |

Recommend (b) for CI runners and (a) as the developer fallback. Either way:
- add `ADAPTER_BINARIES`/`ADAPTER_PINS` entries;
- add a row in `scripts/runner/prereqs.sh`, which the drift test checks;
- add `recorded_versions.json`;
- pre-extract the package cache at install time (`copilot --version` with the L4 cache as `XDG_CACHE_HOME`).

**Credentials and redaction.**
- `credential_variable("copilot") = "COPILOT_GITHUB_TOKEN"`;
- `COPILOT_GITHUB_TOKEN` in `DEFAULT_REDACT_ENV` and in `IDENTITY_ENV`;
- `CREDENTIAL_PATHS["copilot"] = ("~/.copilot",)`. That file is the plaintext token on keychain-less Linux. `~/.config/gh` is the `gh` fallback, so it must stay masked from every sandbox, as it already is.
- `hosted_login_problem`: a hosted runner needs the secret, or the workflow token path.
- Not an OAuth-refresh adapter in `gate.OAUTH_ADAPTERS` (PATs and `gho_` tokens do not rotate) [I].

**Doctor and readiness.**
- ENV-004/ENV-015 pick the adapter up from the catalog.
- PRV-001 readiness lines: "store a fine-grained PAT with Copilot Requests as the masked CI variable COPILOT_GITHUB_TOKEN", or "on GitHub Actions in an org repo: give the job `copilot-requests: write`".
- A doctor warning when the profile's role chain is in a personal-account repo and relies on `GITHUB_TOKEN`.

**Vendor and independence.** Copilot hosts many vendors' models, so a pinned model is resolved through `MODEL_FAMILIES` and `--model auto` is `routed`, like kiro `auto`. The served model in every `assistant.message` makes `provenance: "served"` possible, which is better than kiro.

**Skills.** `skills_cli` could install L4 skills to `.github/skills` / `~/.copilot/skills`. That is optional and not needed for the adapter.

**Tests.**
- recorded-stream unit tests per mode, plus one GitHub-routed recording once a token exists;
- factory, roles and catalog drift;
- the probe ladder under the login lock (`test_login_lock_coverage` already classifies the prototype module);
- the read-only fail-closed checks;
- the 429 interrupt;
- a sim scenario with a replayed copilot judge (as `happy-kiro-judge`).

## 4. Gaps and risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **Credential ownership.** The only portable credential is one person's fine-grained PAT, which bills their seat; team-wide use of it sits close to ToS "a single login may not be shared". The org-billed `GITHUB_TOKEN` path works only on GitHub Actions in org repos, and in L4 that token is the forge token, which SEC-001 never hands to an agent. | high | v1 supports `COPILOT_GITHUB_TOKEN` only. A later option: when `forge.token_env` is a separate token (App or `L4_FORGE_TOKEN`), the job's `GITHUB_TOKEN` can be scoped to `contents: read, copilot-requests: write` and passed as `COPILOT_GITHUB_TOKEN` [I, untested]. |
| R2 | The GitHub-routed shapes are unmeasured: quota-exhausted and weekly-limit errors, `aiCreditsStatus` values, whether `totalNanoAiu` is filled, auth error text for a revoked token, the required PAT permissions (the "Models" 403 [G]). | high until a live run | one live recording session with a real token before building, the kiro-e2e way |
| R3 | The CLI waits out 429s itself (`Retry-After`) and retries 5xx 5 times. | medium | stream reader interrupts on `assistant.turn_retry{rate_limit}`; `stall_timeout_s` still applies when it goes silent |
| R4 | No max-turns. A denied-call loop kept printing (one 2B-model run made >10k lines in 6 minutes), so the stall timeout does not fire. | medium | `timeout_s` per step; optionally `--max-ai-credits`; a denial-count tripwire in the stream reader |
| R5 | The shell allow rule is binary-level (`python:*` also allows `python -c`), coarser than claude's `Bash(prefix:*)`. The CLI's path check is a heuristic, not a boundary. | medium | the same posture as codex's `workspace-write`: L4's bwrap is the boundary; gates re-run tests outside the agent |
| R6 | Tool names vary by model (`grep`↔`rg`, `create/edit`↔`apply_patch`), and an empty allow-list means *all* tools. | medium | name-based fail-closed checks with both spellings; never pass an empty `--available-tools`; the recorded-fixture test per pin |
| R7 | Fast release cadence and moving flag semantics; a 193 MB binary plus a 220 MB extracted cache per platform and version. | medium | exact pins + sha256 table + major gate; an L4 cache for the extracted package (read-only when warm) |
| R8 | The default experience pulls in GitHub's MCP servers, repo instructions, hooks, memory, a Co-authored-by trailer, telemetry and remote session export. | low (all switchable) | the flag set and `settings.json` above, checked by a unit test |
| R9 | An org policy can force Copilot's own sandbox or disable bypass, which inside L4's bwrap breaks all shell commands. | low | doctor finding from the hello (a startup warning in the stream) [G] |
| R10 | The keychain login on a developer Mac is not isolated by `HOME`, so a probe on the host may pass where a sandboxed run would not. | low | in CI only the env variable counts; local runs on macOS use no bwrap anyway |

## 5. Effort

- **Adapter module.** ~500 lines with the probe, reusing `contract`, `credentials`, `probes._binary` and the prototype's parser.
- **Touch points.** These follow the kiro-cli adapter's footprint:
  - `agents/factory.py`, `config/roles.py`, `agents/credentials.py`, `agents/activity.py`;
  - `availability/cooldown.py`, `availability/vendor.py`, `availability/steps.py`;
  - `config/defaults.py`;
  - `provision/catalog.py`, `install.py`, `readiness.py`, `runner.py`;
  - `doctor/checks_agents.py`, `doctor/checks_delegate.py`;
  - `delegate/independence.py`, `ci/github.py` (cache dirs), `sandbox` cache mount, `skills_cli.py` (optional);
  - `recorded_versions.json`, `scripts/runner/prereqs.sh`, SPEC + runbook + skill notes.
- **Totals.** About 20–25 files, ~600–900 lines of tests, plus one live recording session.
- **Size: M–L.** Comparable to the kiro-judge change (one OpenSpec change, two or three implementation waves, one live validation). It is cheaper if the npm install route is accepted, and costlier if the `GITHUB_TOKEN` path (R1) is in scope.

## 6. Open questions for the owner

1. Do you have a Copilot plan, and which one (Free/Pro/Pro+/Max, or a Business/Enterprise seat)? Is Copilot CLI enabled by its policy?
2. Can you create a user-owned fine-grained PAT with "Copilot Requests" for the live recording session (stored as a masked CI variable `COPILOT_GITHUB_TOKEN`)? Is billing that seat acceptable for CI use, or is the org-billed `GITHUB_TOKEN` path (R1) a requirement?
3. Which runners matter: GitHub-hosted, self-hosted GitHub, GitLab? The `GITHUB_TOKEN` path exists only on GitHub Actions.
4. Which install route: the release tarball with a sha256 table (no Node), npm (needs Node ≥ 22), or both?
5. Is the binary-level gate rule (R5) acceptable for the implementer, the same posture as codex? Or should copilot be judge/delegate-only at first, which are the strongest modes measured here?
6. Adapter name: `copilot` or `copilot-cli`?
7. Is BYOK mode (a side finding: the CLI as a harness over any OpenAI-compatible or Anthropic endpoint, no GitHub account) interesting as a free-resource profile, or out of scope?

## Appendix: prototype and fixtures

- `src/l4/agents/copilot_cli.py`: the prototype. Its docstring says SPIKE, NOT REGISTERED, and a test asserts it is in neither `ADAPTERS` nor `HARNESS_ADAPTERS`.
- `tests/unit/agents/test_copilot_cli_spike.py` has 12 tests:
  - argv per mode (no empty allow-list, no `--allow-all-tools`);
  - stdin prompt and private home;
  - judge, delegate and implementer parsing;
  - denials;
  - the 401/402/429/500 mapping;
  - no-credential auth;
  - usage.
- `tests/fixtures/recorded/copilot/1.0.102-byok/*.jsonl`: trimmed recorded streams (deltas and reasoning dropped, paths scrubbed) and one usage file. The directory name is deliberately not a bare version, so `l4.recordedversions` ignores it: BYOK streams are not a contract recording of the GitHub-routed CLI, and `recorded_versions.json` does not list copilot.
- `tests/unit/agents/test_login_lock_coverage.py` classifies the new spawning module as a spike.
