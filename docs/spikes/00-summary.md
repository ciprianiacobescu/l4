# 00 M1 spike synthesis: verdicts, confirmed adapter invocations, SPEC amendments, runner blockers

Written 2026-10-03 from the four reports on disk (`01-loop-claude-code.md`, `02-loop-opencode.md`,
`03-loop-codex.md` and `05-availability-probes.md`), the spike-04 report text handed over by its agent, the 221
recorded files under `tests/fixtures/recorded/`, `docs/SPEC.md`, `openspec/changes/agent-factory/` and
`docs/runner/README.md`.

Labels:

- **[V]** observed in a spike, or re-checked here against a recorded fixture;
- **[I]** inferred, or a combination of separately verified parts that never ran as one command;
- **[U]** unknown;
- **[D]** vendor documentation only.

**Blocker for the index: `docs/spikes/04-openspec-contract.md` does not exist on disk.** The subagent report guard
refused that write. Its 86 fixtures are present under `tests/fixtures/recorded/openspec/1.14.0/`. The parent agent owns
saving the report text. Until then, every "spike 04" reference below points at text that exists only in the run
transcript.

## 0. Bottom line

1. **All five spikes say ADAPT; none says PROMISING or REJECT.** No verdict is contradicted by its own observations.
   Three of the reports overstate their headline numbers, though; see §1. The design holds, but SPEC §4.4, §7.2–7.6,
   §8.3–8.4, §10 and §18 need the amendments in §4 before agent-factory (change 5) and implementer-tdd-loop (change 6)
   write code. The red-phase rules **as written failed live**:
   - the stub rule false-rejected a correct red (01);
   - the red check deadlocked, and the agent then sabotaged existing code (02);
   - a preservation test was false-rejected (03).
2. **Nothing in the TDD loop has run on `l4-runner` or on `example-group/dummy-agentic` yet.** All loop spikes ran on
   macOS. The runner has only the hello probes and one bwrap sandbox probe [V, `docs/runner/`]. The M1 exit criterion
   (a seeded change implemented red→green by a real CLI on the dummy repo through a runner job) is **not met**.
3. **M1 independence cannot be satisfied on the runner with agent-factory's planned M1 slice (`claude-code` +
   `opencode` + `openai-chat`).**
   - The OpenRouter account balance was negative on 2026-10-03 (`total_credits 15`, `total_usage 15.034` [V
     `openrouter-api/v1/get_credits.json`]), and every OpenRouter call returned 402 [V].
   - OpenCode Zen models (`opencode/big-pickle`, `*-free`) do not disclose their vendor, so they can never count as
     independent (02).
   - As a result, a `claude-code` implementer has no usable different-vendor judge, and an OpenCode-Zen implementer
     has no provably independent verifier.
   - Fix (decision needed):
     - **(a)** Move the `codex` adapter (agent-factory group 4) into M1 and pair a Codex implementer with a
       `claude -p --json-schema` judge. That pairing is [V] on macOS (03), and both logins exist on the runner.
     - **(b)** Top up OpenRouter credits for the SPEC's default `judges` chain.

     Option (a) also needs the "CLI judge" amendment in §4.6.

     A third option is not recommended: the SPEC's existing `vendor:` profile field (§3.2) lets the operator declare
     a vendor for a Zen alias. That declaration cannot be verified, because the stream does not report the served
     model, so it is a trust decision presented as a fact.
4. **Every CLI leaked user configuration under the isolation flags SPEC §8.3/L4-SEC-002 prescribes** [V for all
   three]:
   - Claude without `--safe-mode` ran user SessionStart hooks that injected text;
   - OpenCode `--pure` loaded the user's `opencode.jsonc`, started Serena, and a hello wrote a file;
   - Codex injected `$CODEX_HOME/AGENTS.md` despite `--ignore-user-config --ignore-rules`.
5. **The judge as specified is the weakest link.**
   - A cheap judge (`openrouter/openai/gpt-5.4-mini`) given only the diff failed a correct implementation 2/2. A
     brute-force check of 300 000 inputs found 0 violations.
   - Neither judge noticed a real unpinned-input divergence (`"Straße"`).
   - A Sonnet judge given the gate report found a real `spec_gap` (03).

   Model and input are confounded, so "give the judge the test report" is [I]. It is still the cheapest fix.

## 1. Verdict table

| Spike | Verdict | Main consequence | What the observations actually support (skeptic's note) |
|---|---|---|---|
| 01 loop, `claude -p` implementer | ADAPT | Guarded-parameter stubs + red regression check (L4-IMP-002); claude flags `--safe-mode`, `--tools`, `Edit(…)` rules, `env -i`; per-run cost delta on resume; judge needs the test report and executable counterexamples | 2 tasks × 2 result channels completed, and result JSON was valid 17/17 [V]. But the native channel completed only **after the stub checker was changed mid-spike**: 1.2 red #1 was a false reject. The judge failed correct code 2/2. Sample is n=1–2 per variant. Auth was the macOS keychain login; the Linux credentials-file path is untested. |
| 02 loop, `opencode run` implementer | ADAPT | Real isolation (`XDG_CONFIG_HOME` + `OPENCODE_DISABLE_*`); no `ask` rules; prompt on stdin with EOF; red guard rebuilds HEAD+additions; zero values from annotations; `already_satisfied` made operational | The report claims "three complete units". **Only big-pickle did a genuine red→green on both tasks (n=1, served vendor unknown).** Both nemotron completions took the `already_satisfied` path for 1.2, so that task had no green phase. The v1 rules deadlocked and the agent stubbed out working code (O-5). The prompt scope sentence failed 2/2. **The loop passed the prompt as argv, not stdin**; stdin was verified on a hello and on spike 01's judge. |
| 03 loop, `codex exec` implementer | ADAPT | Strictified `--output-schema` (new L4-FAC-009); `--ignore-rules`; gate command `.venv/bin/python -m pytest` after harness `uv sync`; stderr capture; the JSONL stream is not an audit trail; per-criterion red rule; deterministic scenario-conflict lint | Strongest loop evidence: both tasks red→green on the first attempt in 129 s, 12/12 results valid [V]. But it is a toy task on one cheap model. Blocked detection on the plain prompt was 1/3 for `gpt-6-luna`. Its per-criterion `pre_satisfied` rule **as written has no discrimination check** (see §4.3). TypeError-as-red-failure was claimed but **not observed**: the 1.2 tests failed by assertion. |
| 04 OpenSpec 1.14.0 contract | ADAPT | Run `<node> <prefix>/…/bin/openspec.js` with isolated XDG; root check compares the repo root; own Purpose check; exact task-parser port; task id from description, not the CLI `id`; `archive --yes --json` | Best-founded spike: 64 CLI cases plus 22 recorded outputs, and the `root.path` and archive claims re-checked against fixtures here [V]. A small overstatement: "every `--json` call printed exactly one JSON document" excludes `validate --strict --json` with no item (text on stderr), which the report itself records. The report file is missing on disk. |
| 05 availability probes | ADAPT | Auth = presence, not validity; the `hello` step is authoritative; Codex auth via app-server `account/read`; Claude per-model weekly window only in `/usage` text; OpenRouter `/key` + `/credits` as zero-cost quota; `credits` has no reset; corrected costs | The ladder ran for real on claude, codex and opencode. But Codex exhaustion was **injected** (`usedPercent=100`); the only real failover was an OpenRouter 402. Gemini reached only `auth` (not logged in). Kiro is [D] only (not installed locally; installed but not logged in on the runner). Claude figures come from a Max plan; the runner is `pro`. |

### Cross-spike findings (convergent, at least 2 spikes)

| Finding | Evidence |
|---|---|
| Result JSON is reliable on all three CLIs. The repair turn never triggered, so it is untested. | 17/17 (01), 17/17 (02), 12/12 (03) [V]; repair [U] |
| Agents keep red pure unless told otherwise. When told otherwise, the harness checks catch it, and vacuity must run only after stub purity. | 01, 02, 03 [V] |
| Agent `status` is advisory, except `blocked`. | `partial` for complete work 4× (01); `partial` without questions for an unresolved conflict 2× (03) [V] |
| A red phase needs a regression check (pre-existing tests still pass). | 01 (guard can only remove behaviour), 02 (agent deleted code) [V] |
| Agents leak later tasks' scope: red stubs carry later-task parameters, and green over-implements. | 01 [V], 02 2/2 [V], 03 [V] |
| A stdin left open hangs some CLIs. Every spawn needs `stdin=DEVNULL` or prompt+EOF, plus a wall-clock timeout. | `opencode run` (02, 3/3); text-mode `openspec archive` (04) [V] |
| Facts come from the worktree, git and harness-run tests, never from the agent's stream or self-report. | Codex omits sandbox-denied and rejected calls (03); agents misreport (03); OpenCode does not show the served model (01) [V] |

## 2. Spike-04 facts that agent-factory and spec-providers rely on (no report on disk yet)

All [V] against OpenSpec 1.14.0 and the fixtures:

- `root.path` is the **repo root** (realpath), not `<repo>/openspec`.
- A repo with no `openspec/`, or an empty one, walks up to an ancestor root with `source:"nearest"`.
- A global `defaultStore` redirects to another repo (`source:"global_default"`) unless `XDG_CONFIG_HOME` and
  `XDG_DATA_HOME` are isolated.
- `archive --yes` archives with incomplete tasks, validates non-strictly, and its `--json` output **does not mention
  incomplete tasks**.
- A new capability without `## Purpose` passes `--strict` and archives with a `TBD` Purpose that then fails strict
  validation.
- `instructions apply` `tasks[].id` is an **ordinal**. Parent checkboxes count, and checkboxes inside code fences and
  HTML comments count.
- Every failure exits 1, so failures must be classified by `status[].code`.
- `.bin/openspec` exits 127 without `node` on PATH.
- About 150–200 ms per call.

## 3. Confirmed adapter invocations for agent-factory

The env lists below are the **complete** child environment, built by `build_env` (L4-SEC-001), never inherited.
"Credential var" means the profile's own variable from `credential_env_names`. All spawns use their own process group,
a wall-clock timeout, and `stdin` set to either the prompt followed by EOF or `DEVNULL`.

### 3.1 `claude-code` (Claude Code 2.1.288)

**Implementer.** [V] as one command in spike 01, except the `--mcp-config F` addition, which is [I] untested.

```
env -i PATH=<harness_path> HOME=$HOME USER=$USER LANG=<locale> TMPDIR=<tmp> \
       L4_RESULT_PATH=<result-dir>/result.json CLAUDE_CODE_MAX_RETRIES=1 [CLAUDE_CODE_OAUTH_TOKEN=…]
claude -p --output-format stream-json --verbose --model <M> --max-turns <N> --max-budget-usd <B> \
  (--session-id <uuid4> | --resume <uuid>) \
  --permission-mode dontAsk --safe-mode --strict-mcp-config [--mcp-config <F>] \
  --tools "Read,Edit,Write,Glob,Grep,Bash" \
  --allowedTools "Read,Glob,Grep,Edit(./**),Edit(//<result-dir>/**),Bash(<gate prefix>:*)" \
  [--json-schema '<implementer-result schema>']          # stdin: prompt, EOF
```

- **`--bare`.** `auth: api_key` keeps `--bare` with `ANTHROPIC_API_KEY` as in SPEC §8.3. Whether `--safe-mode` and
  `--bare` combine is untested; use `--bare` alone [I].
- **Bare allow rules.** Never use bare `Write`/`Edit` allow rules: they matched a path outside the cwd even under
  `env -i --safe-mode --tools` [V]. `Write(//abs)` and `--add-dir` grant nothing under `dontAsk` [V].
- **Gate rules.** Spike 01 used `Bash(uv run pytest:*)` and `Bash(pytest:*)`. Inside bwrap, use the
  `.venv/bin/python -m pytest` form instead (see §5). That allow-rule prefix is [I] for Claude.
- **Schema.** `--json-schema` was exercised with a **subset** of `l4/implementer-result@1`. The full schema
  (`$id`, `type: [object,null]`) is [U]: pin it with a contract test.
- **Parse.** Read the last `type:"result"` event:
  - `structured_output` [V 11/11];
  - `permission_denials[]` (`tool_name`, `tool_use_id`, `tool_input`) [V];
  - `session_id` = the preset id [V 8/8];
  - `total_cost_usd`, which is **cumulative per session on `--resume`** [V, re-checked: 0.0845 → 0.0955 in
    `red-resume-second-turn.jsonl`];
  - `modelUsage` keys give the served model [V].
- **Status.** Taken from `is_error` + `api_error_status`, never from `subtype`: a bad model returns
  `subtype:"success"`, `is_error:true`, `api_error_status:404` [V, `hello_bad_model.stream.jsonl`].

**Judge (tool-less, native schema).** [I] as a union. The base command is [V] from spike 03; `--strict-mcp-config`
and `--max-turns 3` are [V] from spike 02; `env -i` is [V] from spike 01.

```
env -i PATH HOME USER LANG TMPDIR CLAUDE_CODE_MAX_RETRIES=1 [CLAUDE_CODE_OAUTH_TOKEN]
claude -p --model <M> --output-format json --json-schema '<judge schema>' \
  --safe-mode --strict-mcp-config --tools "" --no-session-persistence --max-turns 3     # stdin: prompt, EOF
```

- Structured output costs one turn (`num_turns: 2`), so use `--max-turns ≥ 2` [V].
- Read `.structured_output`; `.result` is the same object as a JSON string [V]. Always validate client-side.
- About 13–17 s and $0.058–0.069 per 2-task diff on Sonnet [V].

**Hello.** [V] from spike 05.

```
claude -p --safe-mode --no-session-persistence --model <profile model> --tools "" --max-turns 1 \
  --output-format stream-json --verbose "Reply with exactly: L4-OK"            # stdin: DEVNULL
```

- Cost: $0.0008 warm to $0.011 cold, about 3 s.
- The stream's `rate_limit_event` (`status`, `resetsAt`, `unifiedWindows.{five_hour,seven_day}.utilization`) is a
  free quota reading [V].

**Auth.** [V] `claude auth status` gives JSON on stdout with exit 0/1.

- Keep only `loggedIn`, `authMethod` and `subscriptionType`.
- **Drop** `email`, `orgId`, `orgName`, `projectsDirectory` and `configDirectory`.
- A dummy `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` still yields `loggedIn:true`, so this step proves
  presence only [V].

**Quota.** [V] `TZ=UTC claude -p --safe-mode --no-session-persistence --output-format json "/usage"` costs $0 and takes
2.2–2.8 s.

- Parse `.result` with the `USAGE_RE` in `05-availability-probes.md`.
- The per-model weekly window ("Current week (Fable)") exists **only** here, not in `rate_limit_event` [V].
- With api-key auth there are no windows, so the step is skipped.

### 3.2 `codex` (codex-cli 0.160.0)

**Implementer.** [V] as one command in spike 03. The env is [I]: spike 03 did not state its env.

```
env: PATH HOME USER LANG TMPDIR [CODEX_API_KEY]        # default CODEX_HOME kept (stored ChatGPT login)
codex exec --json -m <M> -c model_reasoning_effort="<E>" -s workspace-write \
  --ignore-user-config --ignore-rules \
  --output-schema <strictified implementer-result.json> -o <result-dir>/result.json -   # stdin: prompt, EOF
```

- **Strict schema.** Use the strictified schema (`tests/fixtures/recorded/codex/0.160.0/implementer-result.strict.schema.json`).
  The verbatim SPEC schema fails before any work: `turn.failed` with `invalid_json_schema`, exit 1 [V, re-checked].
  Map `null` → absent before canonical validation.
- **Gate command** inside the sandbox: `.venv/bin/python -m pytest …`.
  - `uv run` fails because `~/.cache/uv` is not writable [V].
  - The network is off [V].
  - So the harness runs `uv sync --frozen` before each step.
- **Raw events.** Capture stderr next to the JSONL. `ERROR codex_core::tools::router … Rejected(…)` lines are the only
  trace of rejected calls [V].
- **Built-in `rm -f` rejection.** `rm -f` is rejected with or without `--ignore-rules` [V].
- **Isolation gap.** `$CODEX_HOME/AGENTS.md` is still injected [V]. Mitigate with a doctor check, not a per-job
  `CODEX_HOME` (that would drop the login [I]).
- Resume (`codex exec resume`) [U].

**Hello.** [V] from spike 05, with `--ignore-rules` added [I].

```
codex exec --json --ephemeral --ignore-user-config --ignore-rules -s read-only -m <M> \
  -c model_reasoning_effort=low "Reply with exactly: L4-OK"                     # stdin: DEVNULL
```

- About 5 s and about 19k input tokens; 3 hellos ≈ 1 % of a Plus 5-hour window [V].
- Validate the model first with the zero-token `model/list`. Run hello only on a cold cache entry.
- A bad model gives `turn.failed` 400 "model is not supported …", exit 1, which is a config error, not a limit [V].

**Auth + quota (one zero-token session, about 1 s).** [V] `codex app-server` over stdio JSON-RPC:

```
→ {"method":"initialize","id":0,"params":{"clientInfo":{"name":"l4","title":"L4","version":"<v>"}}}
→ {"method":"initialized"}
→ {"method":"account/read","id":1}            # keep account.type, account.planType; drop email, chatgptAccountId
→ {"method":"account/rateLimits/read","id":2}
```

- Match responses by `id`. Ignore the interleaved `remoteControl/status/changed` and `account/updated` notifications.
- Use the `rateLimitsByLimitId` bucket whose `normalModelSlug` equals the model, else `codex`. Evaluate both `primary`
  (300 min) and `secondary` (10080 min). The profile is also exhausted when `ordinaryUsageAllowed:false`,
  `rateLimitReachedType != null` or `spendControlReached:true`.
- **Never redeem `rateLimitResetCredits`.**
- Logged out or api-key login returns `-32600`; treat that as quota `skipped`.
- `codex login status` writes **stderr** only, and **ignores `CODEX_API_KEY`** [V]. For `auth: api_key`, check that the
  variable is set.

### 3.3 `opencode` (OpenCode 1.18.33; the runner has 1.18.34)

**Implementer.** [I] as a combination. Every element is [V] separately, but the spike-02 loop ran with the prompt as
argv and `stdin=DEVNULL`, without `OPENCODE_DISABLE_EXTERNAL_SKILLS` and without `snapshot:false`.

```
env: PATH HOME USER LANG TMPDIR <credential var>
     XDG_CONFIG_HOME=<empty, harness-owned, per job>          # NOT XDG_DATA_HOME: auth.json lives there
     OPENCODE_DISABLE_PROJECT_CONFIG=1 OPENCODE_DISABLE_CLAUDE_CODE=1
     OPENCODE_DISABLE_EXTERNAL_SKILLS=1 OPENCODE_DISABLE_AUTOUPDATE=1
     L4_RESULT_PATH=<result-dir>/result.json
     OPENCODE_CONFIG_CONTENT={"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled",
       "autoupdate":false,
       "provider":{"<p>":{"models":{"<m>":{"limit":{"context":<c>,"output":<o>}}}}},     # metered providers
       "permission":{"edit":"allow","read":"allow","glob":"allow","grep":"allow","list":"allow",
         "bash":{"*":"allow","git commit*":"deny","git push*":"deny","git reset*":"deny","git checkout*":"deny"},
         "external_directory":{"*":"deny","<result-dir>/**":"allow","<result-dir>/*":"allow"},
         "webfetch":"deny","websearch":"deny","question":"deny","doom_loop":"deny"}}
opencode run --pure --format json -m <provider/model> --dir <worktree> --title "l4 <unit> <task> <phase>"
                                                                   # stdin: prompt, EOF; timeout + stall watchdog
```

- **Never emit an `ask` rule.** An auto-rejected `ask` ends the run with exit 0 and last reason `tool-calls` [V,
  re-checked]. A `deny` returns an error and the agent continues [V].
- **Rule order.** OpenCode applies the last matching rule, so put the broad rule first. This depends on JSON key order
  and is [I]: pin it with a contract test.
- **Not confinement.** `external_directory` is a per-command path heuristic, so the bwrap sandbox stays required [V].
- **`--title`** saves a second request to another model [V].
- **Snapshots.** `snapshot:false` removes the snapshot hashes; the user store was 947 MB [V].
- **Output limit.** Without `limit.output`, OpenCode requests 32 000 output tokens, which a low-credit OpenRouter key
  rejects with 402 [V].
- **Parse.** `sessionID` from the first event; the final text is the concatenated `text` parts; cost is the sum of
  `step_finish.part.cost`, a **nominal** price-table estimate [V].
- **Served model.** It is not observable in the stream [V], so log `availability.model_unverified`.

**Judge (tool-less, prompt contract).** [V] from spike 01, without XDG isolation; the isolation additions make it [I].

```
cwd: empty temp dir; env as above minus L4_RESULT_PATH
OPENCODE_CONFIG_CONTENT={"snapshot":false,"share":"disabled","autoupdate":false,"tools":{"*":false},
  "permission":{"*":"deny"},"provider":{"openrouter":{"models":{"<m>":{"limit":{"context":200000,"output":6000}}}}}}
opencode run --pure --format json -m openrouter/<m> --title "l4 judge <unit>"          # stdin: prompt, EOF
```

- The mechanics work: 2/2 runs produced parseable JSON, slicing from the first `{` to the last `}`.
- The **verdict quality failed 2/2** with `gpt-5.4-mini` and no test report.
- It currently fails with 402 on the negative OpenRouter balance [V].

**Hello.** [V] from spike 05, isolated; `--title` added [I].

```
cwd: empty dir; XDG_CONFIG_HOME=<empty>; OPENCODE_CONFIG_CONTENT={"tools":{"*":false},"permission":{"*":"deny"}}
opencode run --pure --format json -m <provider/model> --title "l4 hello" "Reply with exactly: L4-OK"   # stdin: DEVNULL
```

- $0.0005 cold, about 3 s [V].
- **The hello is the auth check for OAuth providers**: an expired OpenAI OAuth login surfaces only here, as
  `Token refresh failed: 401` [V].

**Auth.** `opencode auth list` [V] is **presence only**:

- strip ANSI;
- map display names to ids (lowercase, spaces → `-`);
- accept the `Environment` section.

**Quota.** Only OpenRouter-backed profiles have a zero-cost source. [V] `GET https://openrouter.ai/api/v1/credits`
(balance = `total_credits − total_usage`) and `GET /api/v1/key` (`limit_remaining`, `limit_reset`) take about 0.05 s.
Other providers: quota `skipped`.

### 3.4 OpenSpec CLI (spec-providers, used by the harness itself)

[V] from spike 04 (direct `node …/bin/openspec.js` timing and planted-package runs):

```
argv = [<absolute node ≥ 20.19.0>, <prefix>/node_modules/@fission-ai/openspec/bin/openspec.js, *args]
env  = {PATH, HOME, TZ=UTC, DO_NOT_TRACK=1, OPENSPEC_TELEMETRY=0, OPENSPEC_NO_UPDATE_CHECK=1, NO_COLOR=1,
        XDG_CONFIG_HOME=<cache>/openspec-xdg/config, XDG_DATA_HOME=<cache>/openspec-xdg/data}   # both empty
cwd  = realpath(repo); stdin = DEVNULL; timeout 60 s; every call carries --json (archive: --yes --json)
```

### 3.5 Gemini and Kiro

- **gemini** [V auth only]. No status command exists. Any unauthenticated call exits 41 with no model call, which maps
  to `auth: not configured`.
- **kiro-cli** [D only]:
  - binary: `kiro-cli --version`;
  - auth: `kiro-cli whoami --format json` (drop the e-mail);
  - quota: `chat --no-interactive "/usage"`;
  - models: `chat --list-models --format json`;
  - an active browser login shadows `KIRO_API_KEY`.

  Every field name and exit code is [U].

### 3.6 Status derivation (L4-FAC-002), per adapter

| `RunResult.status` | claude-code | codex | opencode |
|---|---|---|---|
| `ok` | result event, `is_error:false`, and `structured_output` present when a schema was requested | exit 0, `turn.completed`, `-o` file parses | exit 0, last `step_finish.part.reason == "stop"` [V] |
| `permission_blocked` | (denials are recoverable; record `permission_denials[]`) | stderr `Rejected(…)` → `agent.tool_rejected` event only | exit 0, last reason ≠ `stop`, `tool_use` error containing "rejected permission" [V] |
| `quota` / `rate_limited` | `rate_limit_event.status == "rejected"` + `resetsAt`; `api_retry{error: rate_limit}` → interrupt [V SPEC] | `turn.failed` with the usage-limit shape [U: not reproduced] | `error.data.statusCode` 429 (reset only in body text "retry in 9h9m42s") [V] |
| `credits` limit (`LimitSignal.kind`) | — | — | `statusCode` 402, `isRetryable:false`, `limit_source:"openrouter_credits"` [V] |
| `auth` | `api_error_status` 401/403 [I] | `-32600` from the app-server quota call, not from a `codex exec` stream [V] | "Token refresh failed: 401" [V] |
| `error` (config, not retryable) | `is_error:true`, `api_error_status:404` (bad model) [V] | `turn.failed` 400 `invalid_json_schema` or "model is not supported" [V] | — |
| `error` (retryable) | — | — | "[503]" / "overloaded" [V] |
| `max_turns` / `budget` | `subtype` `error_max_turns` / `error_max_budget_usd`, `result: null` [V SPEC] | — | — |
| `timeout` | harness clock | harness clock | harness clock; silent gaps of 30–183 s are normal while it retries [V] |

### 3.7 agent-factory tasks that contradict the spikes (fix before implementing)

| Task / design | Conflict | Required change |
|---|---|---|
| design R1, task 1.8; spikes change task 1.10 | Fixture root is given three ways: `tests/fixtures/agents/`, `tests/fixtures/cli/` and the actual `tests/fixtures/recorded/` | Adopt `tests/fixtures/recorded/<tool>/<version>/` (221 files exist) and fix the other two documents |
| 1.6, design D3 | Subscription argv lacks `--safe-mode`, `--tools` and `Edit(…)` path rules; uses a bare allow-list | Use §3.1. Add a test asserting no bare `Write`/`Edit` rule is ever emitted |
| 1.7 | Status from `subtype` | Use `is_error` + `api_error_status`. Compute the per-run cost delta per `session_id` |
| 1.10, D3 | `OPENCODE_PERMISSION` + `--pure` only; stdin marked [U]; no `--title`, no XDG isolation, no `snapshot:false`, no result-dir allow | Use §3.3. Stdin is [V] (hello, spike-01 judge); use `OPENCODE_CONFIG_CONTENT.permission` (`OPENCODE_PERMISSION` alone is untested) |
| 1.11 | `tool-calls` + exit 0 → `permission_blocked` | Also require the "rejected permission" `tool_use` error. Otherwise use `error` |
| 1.19, SPEC "cheapest settings" | Hello on the cheapest model | Hello on the **profile's model**: a warm Sonnet hello costs the same as Haiku, and limits are per model [V 05] |
| 2.1 | Drops only the e-mail | Also drop `orgId`, `orgName`, `projectsDirectory` and `configDirectory` |
| 2.2 | Quota from `rate_limit_event` | Also parse the `/usage` text for the per-model weekly window (L4-AVL-009) |
| 3.2 | "retry-after extraction" | Google 429s carry the reset only in body text; parse "Please retry in XhYmZs". `retry-after` is absent [V] |
| 4.1/4.2, D3 | No `--ignore-rules`, no strict schema, `turn.failed` → quota or error | Add `--ignore-rules` and L4-FAC-009. `invalid_json_schema` and 400 "not supported" → `error` (config) |
| 4.4 | `codex login status` exit code | Prefer app-server `account/read`. `login status` uses stderr and ignores `CODEX_API_KEY` |
| M1 slice (group 1) | No independent judge is available on the runner today (§0.3) | Pull group 4 (codex) into M1 and add the CLI-judge path, or top up OpenRouter |
| 10.7 | "stdin prompt for `opencode run`" listed as [U] | Now [V] (`hello-ok-stdin-prompt.jsonl`); keep a contract test |

## 4. SPEC amendments (exact text)

New IDs assigned here: **L4-OSP-007** (Purpose; from 04), **L4-OSP-008** (task→criterion link; from 03; both spikes
had proposed "007"), **L4-FAC-009** (strict schema), **L4-ODD-004** (scenario-conflict lint), doctor **ENV-009 to
ENV-012** and **SPEC-007**, and scenarios **SCN-DET-11**, **SCN-IMP-38 to SCN-IMP-42**, **SCN-FAC-10** and
**SCN-AVL-18**. Text in quotes is the proposed normative wording.

### 4.1 §4 spec providers (from 04 unless noted)

- **L4-OSP-001** (replace):
  > "The provider MUST run OpenSpec as `[<node>, <prefix>/node_modules/@fission-ai/openspec/bin/openspec.js, …]`.
  > `<node>` is the absolute path that doctor ENV-003 resolved and checked (≥ 20.19.0). `<prefix>` is a harness-owned
  > install made by `npm ci` against a harness-shipped lockfile, or by `npm install --prefix <prefix> --save-exact
  > --no-audit --no-fund @fission-ai/openspec@<v>`, and its `--version` MUST equal `<v>`. The provider never uses the
  > `.bin` shim, `npx` or a PATH lookup. Every call uses `cwd=realpath(repo)`, `stdin=DEVNULL`, a timeout of ≤ 60 s,
  > and exactly the environment `PATH HOME TZ=UTC DO_NOT_TRACK=1 OPENSPEC_TELEMETRY=0 OPENSPEC_NO_UPDATE_CHECK=1
  > NO_COLOR=1 XDG_CONFIG_HOME=<cache>/openspec-xdg/config XDG_DATA_HOME=<cache>/openspec-xdg/data`. Commands:
  > - `list --json --sort name [--all]`;
  > - `show <id> --type change --json` and `show <cap> --type spec --json`;
  > - `validate <id> --strict --json` and `validate <cap> --type spec --strict --json` (never `validate` without an
  >   item);
  > - `instructions apply --change <id> --json`;
  > - `new change <id> --json`;
  > - `archive <id> --yes --json`.
  >
  > `status` MUST NOT be used: its `isComplete` means planning is complete. Exit 1 is the only failure exit, so
  > failures are classified by `status[].code`, and non-JSON stdout is a provider error that names the argv."
- **L4-OSP-002** (replace):
  > "The provider MUST verify `root.source == "nearest"` and `realpath(root.path) == realpath(<repository root>)`
  > (the directory containing `openspec/`). A `source` of `global_default`, `declared` or `store`, or any `store_id`
  > key, is a provider error."
- **L4-OSP-003** (append):
  > "The `--json` success output does not report incomplete tasks, so `done_gate()` is the only barrier. After
  > archiving, the provider MUST run `validate <cap> --type spec --strict --json` for every capability in the unit's
  > `deltas[].spec` (not `--all`). On failure it restores the worktree and the unit goes to `escalated`.
  > `archive_validation_failed`, `archive_spec_update_failed` and `archive_target_exists` map to `escalated` with the
  > code in the event. `archive_change_not_found` is a state error."
- **L4-OSP-004** (replace the grammar sentence):
  > "Task parsing MUST use an exact port of OpenSpec's parser: `split('\n')` (never `splitlines()`), the JavaScript
  > whitespace class including U+FEFF and U+00A0, `.` excluding `\n\r  `, ASCII digits, and JavaScript
  > `trim`. It is golden-tested against the recorded `apply-task-grammar*.json`.
  > - The task id is the description's leading number (`^(\d+(?:\.\d+)+(?:[A-Za-z]+)?)(?=\s|$)`), else `L<line>`.
  >   The CLI's `tasks[].id` (an ordinal) MUST NOT be used.
  > - Markers are written only where the bracket is exactly `[ ]`, at offset `line.index('[') + 1`.
  > - `[-]`, `[~]` and `[]` count as not done.
  > - `[ ]*` is a required task.
  > - SPEC-006 compares `(total, complete)` with `progress` (which counts text-less checkboxes) and per-line
  >   `(line, done, description)` with `tasks[]`."
- **L4-OSP-005** (append):
  > "After `new change <p>-fix-<n> --json` (which writes only `.openspec.yaml`) the harness appends `skip_specs: true`
  > and writes `proposal.md` (`show` fails without it) and `tasks.md` with `N.M` numbering under `## N.`."
- **L4-OSP-006** (append):
  > "Exact rule: any `validate` issue whose message starts with `Archive would refuse this delta:` is an ERROR."
- **L4-OSP-007 (new)**:
  > "At intake, every delta `specs/<cap>/spec.md` whose `<cap>` is not in `openspec/specs/` MUST contain a
  > `## Purpose` section of ≥ 50 characters; otherwise the unit is rejected (exit 14, `unit.rejected`). The CLI does
  > not check this, and archive writes a `TBD` Purpose that fails strict validation [V]."
- **L4-OSP-008 (new; from 03)**:
  > "OpenSpec task→criterion link: requirement names quoted in a task's text link the task to every scenario of those
  > requirements. A task without one cites all criteria of the change, and doctor reports it under SPEC-004."
- **L4-ODD-001 item 2** (replace "task→scenario mapping is advisory because OpenSpec tasks do not cite scenarios"):
  > "OpenSpec: L4-OSP-008."
- **L4-IMP-001** (OpenSpec clause):
  > "OpenSpec: the next task is the first pending checkbox in document order with no pending indented checkbox
  > children (there are no optional tasks). When the last child of a parent is ticked, the harness MUST tick the
  > parent too, or `remaining` never reaches 0."
- **L4-TMW-001** (append):
  > "OpenSpec marker offset = `index('[') + 1`. Regex group starts MUST NOT be used (`- [ ]` has an empty group).
  > `[]` cannot be written in one byte, so SPEC-007 flags it."
- **L4-SPI-001 `unit_dir()`** (append):
  > "For an archived OpenSpec unit it resolves to `openspec/changes/archive/YYYY-MM-DD-<id>/` (from
  > `list --all --json`). `archive` moves `questions.md`, `verification.md`, `.l4/` and the evidence there."
- **SCN-DET-08** (replace the Given):
  > "the repo has no `openspec/`, or an empty one, inside a directory that contains a full OpenSpec root".
- **SCN-DET-08** (replace the Then):
  > "`root.path` ≠ the repo root".
- **SCN-DET-11 (new)**:
  > "Given a runner user with a registered store and `defaultStore` set, when the provider runs with isolated XDG
  > dirs, then the CLI returns `no_openspec_root`, never the other repo."
- **SCN-SEC-08** (add a Then):
  > "a bare `openspec` resolved from PATH is never executed (with `./node_modules/.bin` first on PATH the planted
  > code ran [V])".

### 4.2 §5 intake

- **L4-ODD-004 (new; from 03)**:
  > "Before any agent spend, intake runs a deterministic scenario-conflict lint: two scenarios with the same
  > normalised WHEN (code spans compared) and different THEN, within the change or against the base specs, write a
  > `questions.md` entry of `kind: ambiguous`, and the implementer is not dispatched for the affected tasks.
  > Agent-reported `blocked` remains the fallback."

  Evidence: [V] on 1 conflicting change and 0 false positives on 1 clean change. It cannot see conflicts between
  requirement prose and a scenario [I].

### 4.3 §7 implementer

- **L4-IMP-002, red phase.** Replace from "Stubs make new symbols compile…" to "…Commit:" with the text below. This
  reconciles spikes 01, 02 and 03: annotation-based zero values (02) supersede `return None` (01/03) because of 02's
  `-> str` counterexample, and spike 03's `pre_satisfied` rule gains a discrimination check, without which
  `assert True` would pass, contradicting SCN-IMP-02.

  > **Admissible non-test changes.** "Admissible non-test changes in red are:
  > - (i) new symbols whose bodies are only a not-implemented statement;
  > - (ii) **guarded-parameter stubs**: an existing function gains only new trailing parameters with defaults, its
  >   first statement is `if <expression over its parameter names and None/True/False>: <not-implemented
  >   statement>`, and the rest of its body is AST-identical to HEAD (an existing parameter may be guarded);
  > - (iii) imports and `__all__` entries for (i) and (ii).
  >
  > A red phase with no production change is valid."
  >
  > **Guard.** "The guard rebuilds every pre-existing non-test file as HEAD plus admissible additions: new imports
  > are kept, new top-level functions are stub-ified, and any removal or change of existing code is restored
  > byte-for-byte (`guard.violation{phase: red}`). The guard MUST NOT patch the agent's file in place."
  >
  > **Check order.** "Red checks run in order and stop at the first failure:
  > 1. protected-path revert;
  > 2. stub purity;
  > 3. run (a): every new test is reported individually and fails with `AssertionError`, a test-framework failure
  >    (pytest `Failed`, e.g. `DID NOT RAISE`), or the stub's not-implemented error. Any other exception class is
  >    reported by name and is not a red failure;
  > 4. regression: every test that passed at the step's base still passes;
  > 5. run (b), the vacuity check, run only when check 2 passed.
  >
  > Zero-value stubs come from the return annotation by AST rewrite: Python `str→""`, `int→0`, `float→0.0`,
  > `bool→False`, `list→[]`, `dict→{}`, `set→set()`, `tuple→()`, `bytes→b""`; unannotated or unknown → `None`. A
  > guarded stub's guard body gets the same treatment."
  >
  > **Pre-satisfied criteria.** "When every new test tracing a cited criterion passes in run (a), the criterion does
  > not fail red if, and only if, the harness confirms discrimination. Against a scratch copy in which every public
  > function of the unit's source modules that those tests import is replaced by its zero value, at least one of the
  > tests must fail by assertion.
  > - Confirmed criteria are recorded as `criterion.pre_satisfied`, listed in `verification.md` and always included in
  >   audit sampling.
  > - Unconfirmed ones fail red (`not discriminating`).
  > - If every cited criterion is pre-satisfied, the task follows `already_satisfied` (L4-IMP-003)."
  >
  > **signature_change.** "`signature_change` (red skipped) applies only to a change that a guarded-parameter stub
  > cannot express: a changed or removed parameter, a new parameter without a default, a changed default, or a
  > changed return type."
  >
  > **Scope leak.** "A red stub that declares parameters only later tasks' criteria need is logged as
  > `stub.scope_leak` (info)."

  Evidence labels:
  - guarded stub [V 01, offline self-test 4 cases];
  - regression check [V 01/02];
  - check order [V 01/03];
  - annotation zero values [V 02];
  - discrimination scope "modules those tests import" [I]: spike 02 used "public functions of src files changed since
    the unit base" [V 2/2]; the broader scope covers preservation criteria on untouched code;
  - a `TypeError` from a not-yet-existing keyword does not count as a red failure [I, decided here: never observed;
    the prompt asks for a guarded stub, which fails with the not-implemented error instead].
- **L4-IMP-003** (append):
  > "`already_satisfied` confirmation = the pre-satisfied check of L4-IMP-002 for every cited criterion, plus a
  > `tdd_exemption.reason` naming the task or commit. On success the harness commits the tests as
  > `test(<unit>): <task> already satisfied` with `L4-TDD: already-satisfied`, flips the marker and skips green."

  Evidence [V 2/2 live]. Note: SCN-IMP-13 already exists. This makes it operational; it is not a new path.
- **L4-IMP-004** (append to the contract; per-adapter lines are rendered only for that adapter):
  > - "(claude-code) Bash is only for the standalone gate command `<gate>`. Never chain it with other commands. Use
  >   Write/Edit for every file change." [V mechanism: a chained command was denied as a whole and the agent then
  >   gave up the gate]
  > - "Write your result object to `<absolute path>`." (rendered literally; no agent read `$L4_RESULT_PATH`) [V]
  > - "Gate command: `.venv/bin/python -m pytest …`." (the form that runs inside the agent sandbox; the harness ran
  >   `uv sync --frozen` before the step) [V Codex seatbelt, V runner bwrap probe]
  > - "Before writing anything, compare this task's scenarios with each other and with the current code. If two
  >   scenarios have the same WHEN but different THEN, or a criterion contradicts another criterion or existing
  >   behaviour, change nothing and report status blocked with one question of kind ambiguous." [V 1/1 luna]
  > - "If a test needs a symbol or parameter that does not exist yet, add a signature-only stub or a guarded
  >   parameter. Stub only what this task's criteria need. Every new test must call a stubbed or changed symbol and
  >   assert on its result." [I: green-phase scope sentences failed 2/2 in 02, so the harness checks remain the
  >   control]
  > - (red template) "If the behaviour already exists, write the tests and report
  >   `tdd_exemption: {reason: "already_satisfied by <task|commit>"}`." [V 02]
  > - Never instruct `rm -f` cleanups (Codex rejects them regardless of flags) [V].
- **L4-IMP-005** (append):
  > "`status` is advisory except `blocked`: harness checks alone accept red and green, and `partial` with passing
  > checks is accepted. Delivery:
  > - claude-code: native `--json-schema` → `structured_output`, or the prompt contract with `Edit(//<dir>/**)`;
  > - codex: `--output-schema <strictified>` + `-o` (L4-FAC-009);
  > - opencode: the prompt contract with an `external_directory` allow for the result directory.
  >
  > The result directory is the agent sandbox's private temp dir (L4-SEC-005)."

  The repair turn stays, labelled [U] (never triggered, 0 of 46).
- **L4-IMP-006** (append):
  > "(5) Test tamper is detected per test function on the AST (a trailing newline is not tamper) [V].
  > (6) Adapter permission rules are not a freeze: shell redirects write files under `Edit(./**)` [V]. The hash freeze
  > and revert are mandatory for every adapter. `--disallowedTools "Edit(./tests/**)"` in green MAY be added as
  > defence in depth [I]."
- **L4-IMP-007**: add the trailer value `L4-TDD: already-satisfied`.
- **L4-IMP-008** (append):
  > "A result `partial` or `failed` without `questions` counts as a failed attempt and triggers the one-shot
  > questions call [V 2×]. When green ends `blocked`, the harness snapshots the worktree to the WIP branch
  > (L4-IMP-011) and resets the unit worktree to the red commit before recording the questions [I]."
- **L4-IMP-009** (append):
  > "Per-run cost for claude-code = `total_cost_usd` − the last total recorded for that `session_id` (the value is
  > session-cumulative on `--resume` [V]). OpenCode `step_finish.cost` is nominal (reported for unbilled free-tier
  > calls; `0` for Zen) [V]. Codex reports tokens only [V]. Budgets for opencode and codex profiles MUST bound
  > iterations and wall time, and codex budgets are token or plan-window budgets."
- **L4-IMP-010**: label [V]. The preset `--session-id` was honoured 8/8, and `--resume` keeps the id and returns
  `structured_output`. Resume costs about $0.01–0.02 on Sonnet. Codex `exec resume` stays [U].

### 4.4 §8 agent factory and availability

- **§8.3 intro** (append):
  > "Every adapter spawn uses `stdin` = the prompt followed by EOF, or `DEVNULL`, plus a wall-clock timeout: an open
  > stdin hangs `opencode run` with no output [V 3/3]."

  Spike 02 filed this under L4-IMP-012; that is a misattribution, because IMP-012 is the soft deadline.
- **§8.3 `claude-code` row.** Replace the subscription invocation and the Permissions cell with §3.1. Key text:
  > "auth `subscription`: `--safe-mode` (suppresses user plugin hooks, skills and auto-memory; keeps the stored
  > login [V]), `--tools "Read,Edit,Write,Glob,Grep,Bash"`, and allow rules `Edit(./**)`, `Edit(//<result-dir>/**)`,
  > `Bash(<gate prefix>:*)` generated from `gates.test`. Bare `Write`/`Edit` rules MUST NOT be emitted (they match
  > paths outside the cwd [V]). The child env is built with `env -i` from the L4-SEC-001 allow-list (it also drops
  > the inherited `CLAUDECODE`/`CLAUDE_CODE_*`). `RunResult` carries `permission_denials[]`."
- **§8.3 `codex` row** (replace):
  > "`codex exec --json -m M -c model_reasoning_effort="E" -s workspace-write --ignore-user-config --ignore-rules
  > --output-schema <strict S> -o OUT -`, prompt on stdin. Stderr is captured into `raw_events_path`, and
  > `codex_core::tools::router … Rejected(…)` lines become `agent.tool_rejected`. The `--json` stream omits
  > sandbox-denied and policy-rejected calls [V]."

  Quota cell: add `account/read` (auth + plan) in the same app-server session, the bucket selection by
  `normalModelSlug`, and "never redeem `rateLimitResetCredits`".
- **§8.3 `opencode` row** (replace):
  - invocation and env as in §3.3;
  - Result & session: "`sessionID` from the first event; served model not reported [V]";
  - Permissions: "allow/deny only, never `ask` (auto-reject ends the run with exit 0 [V]); `external_directory`
    `*: deny` then `<result-dir>/**: allow`";
  - Quota signal: "429 reset appears only in the error body text for Google [V]; 402 credits has no reset; OpenRouter
    `/api/v1/key` + `/api/v1/credits` are zero-cost [V]".
- **L4-FAC-002** (append): the per-adapter table in §3.6.
  > "Claude status comes from `is_error` + `api_error_status`, never `subtype` [V]."
- **L4-FAC-003** (append):
  > "OpenCode run mode does not report the served model [V]: log `availability.model_unverified` and use the
  > profile's declared `vendor`. A profile whose model is an undisclosed alias (OpenCode Zen `opencode/big-pickle`,
  > `*-free`) has vendor `unknown`, which is never independent of anything (L4-VER-001)."

  The CLI-judge proposal for §10 (judges role) is in §4.6.
- **L4-FAC-007** (append):
  > "Recordings live in `tests/fixtures/recorded/<tool>/<version>/`. A runner CLI whose version differs from the
  > recorded one only in the patch component runs with doctor `LIVE-*` warning `unrecorded version`, and is not
  > refused [I, decision]."
- **L4-FAC-008** (append):
  > "With `CLAUDE_CODE_OAUTH_TOKEN` the plan is unknown (`subscriptionType` is absent [V]). For codex `api_key` the
  > quota step is skipped (app-server returns `-32600` [V])."
- **L4-FAC-009 (new; from 03)**:
  > "For native schema mode on Codex, and on any OpenAI-strict backend [I for `openai-chat`], the adapter MUST send a
  > strictified copy of the canonical schema: `additionalProperties:false` on every object, every property in
  > `required`, optional properties nullable, `$id` removed. It MUST map `null` back to absent before validating
  > against the canonical schema. A rejection with `invalid_json_schema` is `RunResult.status=error` (configuration),
  > never quota and never retried."
- **L4-AVL-001** (replace the Examples column):
  - **auth:**
    > "claude `auth status` (keep `loggedIn`, `authMethod`, `subscriptionType`; drop `email`, `orgId`, `orgName`,
    > `projectsDirectory`, `configDirectory`); codex app-server `account/read` (keep `type`, `planType`), or for
    > `api_key` the presence of `CODEX_API_KEY`; opencode `auth list` (presence only); gemini credential env or
    > settings (exit 41 = not configured). Env-credential auth proves presence, not validity: `hello` is the
    > authoritative auth check."
  - **quota:**
    > "codex app-server `account/rateLimits/read` (both windows of the model's bucket, plus `ordinaryUsageAllowed`,
    > `rateLimitReachedType` and `spendControlReached`; never redeem reset credits); claude `TZ=UTC claude -p
    > --safe-mode --no-session-persistence --output-format json "/usage"` (the only source of the per-model weekly
    > window), or the latest `rate_limit_event`; OpenRouter-backed profiles: `GET /api/v1/credits` + `/api/v1/key`
    > against the new key `availability.min_remaining_usd` (default 0.50)."
  - **hello:**
    > "on the profile's own model; the reply is accepted after: trim; remove one wrapping layer (a whole ``` fence
    > with an optional language tag, or a matching `` ` ``/`"`/`'` pair); trim; equals `L4-OK`. Costs: Claude $0.0008
    > warm to $0.011 cold, about 3 s; Codex about 5 s and about 19k input tokens (run only on a cold cache entry,
    > after the zero-token `model/list`); OpenCode isolated $0.0005, about 3 s, with `--title`."
- **L4-AVL-002** (append):
  > "Structured sources also include OpenCode `error.data.statusCode` (402 → `credits`, 429 → `rate_limit`) with
  > `responseBody.error.metadata.limit_source`, and Claude `rate_limit_event.status == "rejected"`. Google 429
  > resets are parsed from the body text `Please retry in <h>h<m>m<s>s`. Not limits: Claude
  > `api_error_status:404`, Codex `turn.failed` 400 (configuration), OpenCode `Token refresh failed: 401` and Gemini
  > exit 41 (`auth`)."
- **L4-AVL-003** (append):
  > "`kind: credits` has no reset time: it uses `availability.credits_cooldown` (default 24h) and a doctor warning.
  > For a binding OpenRouter key limit, `resets_at` is the next `limit_reset` boundary [boundary semantics U]."
- **L4-AVL-004**: label [V]. A Google free-tier 429 hit one model while sibling models still answered.
- **L4-AVL-008** (replace the example quota fragment and add a line):
  > "`quota <N>% used (<window>)` names the most-used window. The event adds `quota_window`. The cooling line is
  > `[l4] <role>: <profile> skipped — cooling until <YYYY-MM-DDTHH:MMZ> (<kind>); no probe sent`."
- **L4-AVL-009** (append):
  > "Claude windows are `session`, `weekly (all models)` and `weekly (<model family>)`. Codex: every window of the
  > model's bucket."
- **§3.2 availability block**: add `min_remaining_usd: 0.50` and `credits_cooldown: 24h`.

### 4.5 §10 verifier (from 01, 02 and 03)

- **L4-VER-001** (append):
  > "A profile with vendor `unknown` is never independent. An implementer with vendor `unknown` makes every
  > verifier non-independent, so the unit waits."
- **L4-VER-002 step 9 and §10.3** (append):
  > "The judge prompt contains the gate report (per-test outcome with criterion IDs) as well as the diff. Every
  > criterion verdict `fail` MUST carry `counterexample: {call, expected, actual}`, which the harness executes in the
  > gate sandbox on a scratch copy of head (never the unit worktree: the `call` is model-written code) before the
  > verdict counts. A `fail` whose counterexample does not reproduce is downgraded to
  > `insufficient_evidence`. The judge prompt asks for inputs that no scenario pins down, which are reported as
  > `spec_gap` findings."

  §10.3 schema: add the optional `counterexample` object to `criteria[]`. Evidence: 2/2 wrong `fail` verdicts without
  a report or counterexample [V]; the Sonnet judge with the report found a real `spec_gap` [V]; causality [I].

### 4.6 §8.1/§10 CLI judge (new; needed for M1 on the runner)

- **L4-FAC-003** (append):
  > "A `judges` or `clarifier` profile MAY name an agent adapter instead of a backend when that adapter supports
  > native schema with tools disabled. It is run tool-less (`claude-code`: §3.1 judge argv; `codex`:
  > `exec -s read-only --output-schema` [U, not run as a judge]) and normalised to `StructuredResult`."

  Reason: the only verified independent pairing available on the runner today is a Codex implementer with a
  `claude -p` judge [V on macOS].

### 4.7 §14, §15 and §18

- **L4-OBS-002** (append patterns):
  - Claude `thinking.signature` (the base64 holds the org id), `orgId` and `orgName`;
  - Codex `chatgptAccountId`, `accountId` and `sk-…***…` fragments;
  - OpenRouter `keys/<hash>` URLs, `user_…` ids and `set-cookie`.
- **§15 doctor** (new checks):

  | Check | Level | Condition |
  |---|---|---|
  | ENV-009 (was "CODEX-AGENTS-001") | error in CI, warn locally | `$CODEX_HOME/AGENTS.md` or `$CODEX_HOME/rules/*` exists for the runner user |
  | ENV-010 | warn | OpenCode snapshot store size, and user `opencode.json[c]` MCP servers that isolation drops |
  | ENV-011 | warn | A profile's provider key is free tier (Google: 20 requests per day per model, while one phase uses 4–14), or the OpenRouter balance is below `min_remaining_usd` |
  | ENV-012 | warn | A Kiro browser login exists while a profile uses `KIRO_API_KEY` (the login shadows the key [D]) |
  | SPEC-007 | error under `sdd.enforce` | Unchecked forms other than `[ ]` (`[]`, `[  ]`, `[ ](…)`), and checkboxes inside code fences or HTML comments |
  | ENV-003 (amend) | — | Check the **same absolute node path** the provider will run, and the prefix `--version` == pin |
- **L4-SEC-001** (append):
  > "Adapter-set variables are part of the allow-list: `XDG_CONFIG_HOME`, `OPENCODE_DISABLE_*`,
  > `OPENCODE_CONFIG_CONTENT`, `CLAUDE_CODE_MAX_RETRIES`. `XDG_DATA_HOME` MUST NOT be redirected for OpenCode
  > (credentials live in `~/.local/share/opencode/auth.json`)."
- **L4-SEC-002** (replace the adapter list):
  > "claude subscription: `--safe-mode` + `--strict-mcp-config` + protected paths; claude api_key: `--bare`; Codex
  > `--ignore-user-config --ignore-rules` plus doctor ENV-009 (`$CODEX_HOME/AGENTS.md` is injected regardless [V]);
  > OpenCode: `--pure` **and** an empty `XDG_CONFIG_HOME` **and** `OPENCODE_DISABLE_PROJECT_CONFIG`,
  > `_CLAUDE_CODE` and `_EXTERNAL_SKILLS` **and** an explicit `OPENCODE_CONFIG_CONTENT` (`--pure` alone loaded user
  > config and MCP servers [V])."
- **L4-SEC-005** (append):
  > "OpenCode `external_directory` and Claude path rules are heuristics, not confinement [V]."
- **SCN-SEC-02 / SCN-FAC-08** (Then): add
  > "the claude command line has `--safe-mode`; the opencode env has an empty `XDG_CONFIG_HOME`".

### 4.8 New scenarios

| Scenario | Content |
|---|---|
| **SCN-IMP-38** (+) | Guarded-parameter stub accepted |
| **SCN-IMP-39** (−) | Red that breaks a pre-existing test is rejected (`red broke pre-existing tests`) |
| **SCN-IMP-40** (+) | Green of 1.1 over-implements 1.2; red 1.2 is confirmed `already_satisfied`; no green runs |
| **SCN-IMP-41** (−) | A call-only `already_satisfied` test → `not discriminating` |
| **SCN-IMP-42** (−) | Vacuity is not run when stub purity failed (no "vacuous" label on a leak) |
| **SCN-FAC-10** (−) | A non-strict schema sent to Codex → `error` (config), no retry, no cool-down |
| **SCN-AVL-18** (+) | OpenRouter 402 → `credits` cool-down for `credits_cooldown`, fallback #1. Spike 05 run 3 recorded the 402 detection and fallback #1 live, but it applied `default_cooldown` (30 min); the `credits_cooldown` value is this amendment |

## 5. Open items that need the runner (`l4-runner`, dummy repo)

Each item needs a CI job on the runner, not the macOS machine.

1. **M1 loop end to end on `example-group/dummy-agentic`.** Run red → green → judge in a pipeline job. Nothing in §3 has run
   there except hello and the bwrap edit probe.
2. **Independence pairing** (§0.3). Decide between pulling codex into M1 and topping up OpenRouter. Also check
   whether the runner's `OPENROUTER_API_KEY` is the same account as the negative-balance one [U].
3. **Claude on Linux.** Untested combinations:
   - `env -i` + `--safe-mode` with `~/.claude/.credentials.json`; spike 01 used the macOS keychain [U];
   - `/usage` text and the per-model weekly window on the runner's **pro** plan; spike 05 used Max [U];
   - `/usage` under `CLAUDE_CODE_OAUTH_TOKEN` [U].
4. **Repo-level Claude config.** Does `--safe-mode` also suppress **project** `.claude/settings.json` hooks
   (SCN-SEC-02)? Only user plugin hooks were tested [U].
5. **OpenCode 1.18.34 on the runner vs the 1.18.33 fixtures.** Re-record the contract cases or adopt the patch-drift
   rule (L4-FAC-007).
6. **OpenCode `magnitude` provider.** The runner's user config defines it; `XDG_CONFIG_HOME` isolation drops it, so a
   profile that uses it must re-supply `provider.magnitude` in `OPENCODE_CONFIG_CONTENT` [I]. The same isolation also
   drops the user config's `npx …@latest` MCP servers, which is intended.
7. **OpenCode `.git/opencode` in a linked worktree**, where `.git` is a file [U]. Also whether a worktree `AGENTS.md`
   or `opencode.json` is read under `OPENCODE_DISABLE_PROJECT_CONFIG=1` + `--pure` [U].
8. **Gate command inside bwrap for Claude and OpenCode.**
   - `uv run` will likely fail on a read-only `~/.cache/uv`, as it did in Codex's seatbelt [I].
   - The runner's sandbox probe used `.venv/bin/python -m pytest` after `uv sync` outside [V].
   - Confirm the Claude allow-rule prefix `Bash(.venv/bin/python -m pytest:*)` [I].
   - Alternative: `UV_CACHE_DIR` on a writable mount + `UV_OFFLINE=1` [U].
9. **Codex on Linux** (landlock inside bwrap): `-o` and a result dir in the sandbox's private temp. Also check whether
   `exclude_tmpdir_env_var` defaults differ [U]. The bwrap probe passed for an edit plus pytest only.
10. **Codex `exec resume` across phases, and a real mid-run usage-limit `turn.failed` shape** [U]. The limit is
    needed to pin the `quota` row in §3.6.
11. **OpenSpec prefix alignment.**
    - PRQ-08 installs to `~/.local/share/l4/npm` without `--save-exact`; L4-OSP-001 now wants an exact pin or
      `npm ci` + lockfile.
    - Pick one location and record the absolute node path (`~/.local/share/l4/node` or the system node 22.23.3).
12. **Gemini and Kiro.**
    - Kiro 2.27.1 is installed but not logged in. Every Kiro fact is [D]/[U] until a logged-in recording exists
      (L4-NFR-006).
    - Gemini has no login anywhere.
13. **WIP snapshots (L4-IMP-011) and a non-toy task.** No spike exercised either [U].

Not runner-bound, but still open:

- the result repair turn (0 of 46 triggered);
- whether Claude enforces `pattern`/`enum` in `--json-schema`;
- the full `l4/implementer-result@1` schema under Claude native mode;
- the OpenCode `external_directory` last-match ordering;
- the OpenCode serve-mode structured-output field;
- the `openai-chat` backend against OpenRouter with `json_schema`. **No spike exercised it**, and it is in
  agent-factory's M1 slice.

## 6. Housekeeping for the `spikes` change

- `openspec/changes/spikes/tasks.md` names the reports `01-runner-inventory` … `08-tdd-python` and the fixture root
  `tests/fixtures/cli/`. The actual reports are `01`–`05` as listed above, and the fixtures are in
  `tests/fixtures/recorded/`. Update the tasks, or add a mapping in `docs/spikes/README.md`.
- Tasks 1.0 (report template and checker), 1.10 (redaction test and manifest) and 1.11 (SPEC amendments) are not done.
  §4 is the input for 1.11.
- A redaction scan of all 221 fixtures, run for this summary, found no e-mail, home path, key prefix or unredacted
  account id [V].
- **Prototype code lives only in the session scratchpad and will be lost**:
  - `proto_loop.py` ×3;
  - `l4_trace.py` and `l4_pytest_report.py`;
  - `strictify.py`, `intake_lint.py` and `probe_runner.py`;
  - `osp_tasks.py` and the test suites.

  Copy the reusable ones (`strictify.py`, `intake_lint.py`, the pytest trace plugin, `normalise_hello`/`USAGE_RE`,
  and the exact task-parser port) into the repo before the session ends, or re-derive them from the reports.
