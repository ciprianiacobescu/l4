# 05 Availability probes: ladder, cost and fallback logging per local CLI

Recorded 2026-10-03 on macOS (arm64). CLI versions: Claude Code 2.1.288, Codex CLI 0.160.0, OpenCode 1.18.33,
Gemini CLI 0.62.0. Kiro CLI is not installed; that part is from the docs only.
Labels: **[V]** observed in this spike, **[I]** inferred, **[U]** unknown, **[D]** documented by the vendor and not run here.

## Question

Do the availability probes of SPEC §8.4 (L4-AVL-001..009) work as designed for each local CLI, and what does each
probe cost? The probe ladder is binary → auth → quota → hello. A throwaway runner must print the L4-AVL-008 lines for
the chain `[codex-sol, claude-sonnet]`, with Codex quota exhaustion simulated by `usedPercent=100`.

## Method (exact commands)

All commands ran in `$SCRATCH/spikes/05-availability-probes` (a git repo, `user.email` maintainer@example.invalid) or in an empty
temp directory. stdin was `/dev/null` and every call had a wall-clock timeout of 60–120 s. Timings come from
`tools/timed.py` (the subprocess wall clock). "Logged out" cases used empty `CLAUDE_CONFIG_DIR`, `CODEX_HOME` or
`XDG_DATA_HOME` directories. Dummy keys were invalid strings, never real keys.

| Step | claude-code | codex | opencode | gemini |
|---|---|---|---|---|
| binary | `claude --version` | `codex --version` | `opencode --version` | `gemini --version` |
| auth | `claude auth status` (logged in; `CLAUDE_CONFIG_DIR=<empty>`; plus dummy `ANTHROPIC_API_KEY`; plus dummy `CLAUDE_CODE_OAUTH_TOKEN`) | `codex login status` (ChatGPT; `CODEX_HOME=<empty>`; `CODEX_HOME=<empty>`+`CODEX_API_KEY`; after `codex login --with-api-key` into a scratch `CODEX_HOME`); `codex app-server` → `account/read` | `opencode auth list` (real; `XDG_DATA_HOME=<empty>`; plus `OPENROUTER_API_KEY`) | none exists; see hello |
| quota | `claude -p "/usage" --output-format json` (default TZ, `TZ=UTC`, `LC_ALL=de_DE.UTF-8`, `--safe-mode --no-session-persistence`, api-key auth); `rate_limit_event` from the hello stream | `codex app-server`: `initialize` → `initialized` → `account/read` → `account/rateLimits/read` (`tools/codex_quota.py`, 3× ChatGPT, logged out, api-key); `model/list` | `GET https://openrouter.ai/api/v1/key` and `/api/v1/credits` (zero-cost HTTP; the key was read in-process and never printed) | — |
| hello | `claude -p --safe-mode --no-session-persistence --model {haiku,sonnet,claude-nonexistent-9} --tools "" --max-turns 1 --output-format stream-json --verbose "Reply with exactly: L4-OK"` | `codex exec --json --ephemeral --ignore-user-config -s read-only -m {gpt-6.1-sol,gpt-6-luna,gpt-nonexistent-9} -c model_reasoning_effort=low "Reply with exactly: L4-OK"` | `opencode run --pure --format json -m {openrouter/openai/gpt-5.4-mini, openrouter/anthropic/claude-haiku-4.5, google/gemini-2.5-flash-lite, openai/gpt-5.4-mini} "Reply with exactly: L4-OK"`, first with the user's config, then isolated with `XDG_CONFIG_HOME=<empty>` and `OPENCODE_CONFIG_CONTENT={"tools":{"*":false},"permission":{"*":"deny"}}` in an empty cwd | `NO_BROWSER=true gemini -p "Reply with exactly: L4-OK" -o json` |

Probe runner: `tools/probe_runner.py` (committed in the scratch repo, commit `5e5d9fd`). It was run three times:

```
uv run --no-project --python 3.14 python tools/probe_runner.py --chain codex-sol,claude-sonnet \
    --inject codex-sol:primary.usedPercent=100 --trace          # run 1: simulated exhaustion
uv run … tools/probe_runner.py --chain codex-sol,claude-sonnet --trace                  # run 2: cool-down honoured
uv run … tools/probe_runner.py --chain opencode-or,opencode-flashlite --cache availability-oc.json --trace  # run 3: real 402
```

Unit tests: `uv run --no-project --python 3.14 --with pytest python -m pytest -q tests` → **27 passed**. They cover
the hello-reply normaliser table, the `/usage` parser on recorded text (UTC and Europe/Bucharest), year rollover,
SCN-AVL-03 and SCN-AVL-16.

## Observations

### binary [V]

| CLI | stdout | parse | wall |
|---|---|---|---|
| claude | `2.1.288 (Claude Code)` | `^(\S+) \(Claude Code\)` | 0.01 s (native binary) |
| codex | `codex-cli 0.160.0` | `codex-cli (\S+)` | 0.04–0.10 s; 0.84 s on a cold first call in the runner (Node start) |
| opencode | `1.18.33` | whole line | 0.25 s |
| gemini | `0.62.0` | whole line | 0.67 s |

All exited 0.

### auth

**claude `auth status`** [V]. JSON on stdout, 0.65–0.72 s. Exit 0 when logged in and 1 when logged out.
- Fields, logged in: `loggedIn`, `authMethod`, `apiProvider`, `analyticsDisabled`, `projectsDirectory`,
  `configDirectory`, `email`, `orgId`, `orgName`, `subscriptionType`.
- Fields, logged out: the first six only (`authMethod:"none"`).
- `authMethod` values seen: `claude.ai` (stored login), `oauth_token` (`CLAUDE_CODE_OAUTH_TOKEN`), `api_key`
  (`ANTHROPIC_API_KEY`, plus `apiKeySource`), `none`.
- **Environment credentials are not validated.** A dummy `ANTHROPIC_API_KEY` or a dummy `CLAUDE_CODE_OAUTH_TOKEN`
  still gives `loggedIn:true` and exit 0.
- **`subscriptionType` is missing on the `oauth_token` path.** That is the CI path of L4-FAC-008, so `plan` is
  unknown there.
- **`orgId` and `orgName` are account identifiers**, just like `email`.

**codex `login status`** [V]. The message goes to **stderr**; stdout is empty.

| State | stderr | exit | wall |
|---|---|---|---|
| ChatGPT login | `Logged in using ChatGPT` | 0 | 0.11 s |
| Logged out | `Not logged in` | 1 | 0.05 s |
| Only `CODEX_API_KEY` set | `Not logged in` | 1 | — |
| API-key login | `Logged in using an API key - sk-dumm***67890` | 0 | — |

- The env-only row matters: `login status` does not see the environment variable.
- The API-key row prints a masked fragment of the key.

**codex app-server `account/read`** [V]. It returns `{account:{type:"chatgpt"|"apiKey", email, planType:"plus"}, requiresOpenaiAuth, workspaceRouting:{chatgptAccountId, …}}`.
- When logged out it returns `account:null`.
- It takes 0.35–0.50 s after `initialize`, which itself takes 0.05–0.23 s.
- It gives auth method and plan in the same zero-token session as the quota call.

**opencode `auth list`** [V]. Always exit 0, even with 0 credentials. 0.38–0.41 s.
- Output is a decorated list with ANSI escapes, even when stdout is not a TTY: `●  OpenRouter <esc>api`.
- It prints **display names, not provider ids**: `OpenRouter`/`openrouter`, `OpenCode Go`/`opencode-go`. Lowercasing
  and replacing spaces with `-` mapped all 9 entries correctly.
- An `Environment` section lists detected env keys (`OpenRouter OPENROUTER_API_KEY`).
- **Presence only.** `OpenAI oauth` is listed, but every OpenAI call failed with `Token refresh failed: 401`.

**gemini** [V]. There is no status command. An unauthenticated `gemini -p` exits **41** in 0.8 s with
`{"error":{"type":"Error","message":"Please set an Auth method in …/.gemini/settings.json or specify one of …
GEMINI_API_KEY, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA","code":41}}` and no model call. Gemini is not logged
in on this machine, so its quota and hello steps were skipped. The OpenCode Google key was not borrowed.

### quota

**claude `/usage`** [V].
- **Cost.** `total_cost_usd:0`, `num_turns:0`, `duration_api_ms:0`, `local_command:"usage"`.
- **Speed.** 3.3–3.7 s wall without flags; **2.2–2.8 s** with `--safe-mode --no-session-persistence`.
- **Text format.** `result` lines look like
  `Current session: 59% used · resets Oct 3 at 3pm (UTC)`,
  `Current week (all models): 17% used · resets Oct 7 at 6pm (UTC)` and
  `Current week (Fable): 0% used · resets Oct 7 at 6pm (UTC)`. The last one is the per-model weekly window. A
  "What's contributing to your limits usage?" block of local analytics follows.
- **Timezone.** The `TZ` env var sets the timezone printed in the text: the default gives `(Europe/Bucharest)`,
  `TZ=UTC` gives `(UTC)`. `LC_ALL=de_DE.UTF-8` left the text in English. **Running with `TZ=UTC` makes the parse
  deterministic.**
- **Minute rounding.** The same reset printed as `5:59pm (Europe/Bucharest)` = 14:59Z in one call and `3pm (UTC)` in
  a later one. The `rate_limit_event` said `resetsAt` = 15:00:00Z. So the text is accurate to about ±1 min, and the
  format is `h[:mm]am|pm`, with no year.
- **api-key auth.** `/usage` returns only a cost summary (`Total cost: $0.0000 …`), with no windows.

**claude `rate_limit_event`** [V]. Emitted on every stream-json hello, before `result`:

```json
{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1791039600,"rateLimitType":"five_hour",
 "overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,
 "unifiedWindows":{"five_hour":{"utilization":0.56,"resetsAt":1791039600},"seven_day":{"utilization":0.16,"resetsAt":1791396000}}}}
```

`utilization` matched `/usage` exactly (0.56 ↔ 56 %). **`unifiedWindows` has no per-model window**: the
"Current week (Fable)" window exists only in the `/usage` text.

**codex app-server** [V].
- **Timing (3 runs).** Total 0.95–1.32 s: `initialize` 0.05–0.23 s, `account/read` 0.35–0.50 s,
  `account/rateLimits/read` 0.45–0.61 s. Zero tokens.
- **Response.** `ordinaryUsageAllowed`, `rateLimits{limitId:"codex", limitName, normalModelSlug,
  primary{usedPercent, windowDurationMins:300, resetsAt}, secondary{…10080…}, credits{hasCredits, unlimited, balance},
  individualLimit, spendControlReached, planType, rateLimitReachedType}`, `rateLimitsByLimitId{codex:{…}}`,
  `rateLimitResetCredits{availableCount:1, credits:[{id, resetType:"codexRateLimits", status:"available",
  title:"Full reset (Weekly + 5 hr)", …}]}`, `accountId`, `rateLimitUpsell`.
- **Logged out:** JSON-RPC error `-32600 "codex account authentication required to read rate limits"`.
  **API-key login:** `-32600 "chatgpt authentication required to read rate limits"`. Both return in under 0.1 s.
- **Per-model buckets.** The Codex source shows buckets other than `codex`: `limit_id:"codex_other"` appears in tests,
  and `normal_model_slug` is documented as "Normal model whose display name … describe this quota alias" [V source].
  Only the `codex` bucket appeared live, so which models map to which bucket is [U].
- **Probe cost against the window.** Three Codex hellos moved `primary.usedPercent` from 0 to 1 on a Plus plan.
- **Model check.** `model/list` (also zero tokens) returned 8 models with `id`, `isDefault` and
  `defaultReasoningEffort`.

**OpenRouter** (used by `opencode-or`, `opencode-gemini` and `judge-*` on `openai-chat`) [V]. Both calls are
zero-cost.
- `GET /api/v1/key` took 0.06 s and returned `limit:2.5`, `limit_reset:"weekly"`, `limit_remaining:2.5`, `usage`,
  `usage_daily|weekly|monthly`, `is_free_tier` and `free_model_daily_requests{used,limit,remaining}`.
- `GET /api/v1/credits` took 0.04 s and returned `total_credits:15`, `total_usage:15.034`. The account balance is
  **negative**, while the key's own weekly limit still shows 2.5 remaining.

### hello

**Reply.** There were 19 successful hellos (9 Claude, 3 Codex, 7 OpenCode). 18 replied exactly `L4-OK`; one (OpenCode, user config) replied `L4-OK\n`.

| Profile / settings | wall | cost / tokens | notes |
|---|---|---|---|
| claude haiku, cold cache | 2.87 s | $0.0109 (5,336 cache-write) | empty `thinking` block, 46–49 output tokens |
| claude haiku, warm | 2.83 s | $0.00079 | |
| claude sonnet, cold | 3.42 s | $0.0092 | 7 output tokens |
| claude sonnet, warm | 3.32 s | $0.00081 | |
| claude sonnet, 5 later runs (runner, fixed empty dir, fresh temp dir) | 3.1–5.3 s | $0.0050–0.0060 | ~1.2–1.4k cache-write tokens each time; cause [U] |
| claude bad model | 2.59 s | $0 | exit 1; **`result.subtype:"success"` with `is_error:true`, `api_error_status:404`** |
| codex gpt-6.1-sol (effort low) | 4.7–5.5 s | 18,798 in (12,288 cached), 8 out | stderr `Reading additional input from stdin...` even with `</dev/null` |
| codex gpt-6-luna | 5.6 s | 18,106 in (11,008 cached), 8 out | not cheaper in tokens |
| codex bad model | 2.67 s | 0 | exit 1; `item.completed{type:"error"}`, then `turn.failed` with 400 "model is not supported when using Codex with a ChatGPT account" |
| opencode flash-lite, **user config** | 4.3–6.1 s | 22–32k in, $0.0023–0.0036 | **run 1: the model called the `write` tool and created `./L4-OK`; the Serena MCP from the user's global `opencode.jsonc` created `./.serena/`. `--pure` did not prevent either** |
| opencode flash-lite, **isolated** | 2.8–3.0 s | 5,358 tokens; $0.00054 cold / $0.000077 warm | one step, no tools, nothing written |
| opencode openrouter/* | 1.8–4.5 s | $0 | exit 1; `error.data.statusCode:402`, `isRetryable:false`, `responseBody.error.metadata.limit_source:"openrouter_credits"`, "requested up to 32000 tokens, but can only afford 7377". OpenCode asks for `max_tokens` 32000 |
| opencode openai (OAuth) | 4.5–4.8 s | $0 | exit 1; `error.name:"UnknownError"`, "Token refresh failed: 401" |
| gemini | 0.8 s | $0 | exit 41 (auth), see above |

**Normaliser** (`normalise_hello`, 20-case table, all pass):
1. Trim whitespace.
2. Remove **one** wrapping layer: a full ```` ``` ```` fence with an optional language tag, or a matching `` ` ``,
   `"` or `'` pair.
3. Trim again, then require `== "L4-OK"`.

Accepted: `` `L4-OK` ``, `"L4-OK"`, ```` ```text\nL4-OK\n``` ````.
Rejected: ``` ``L4-OK`` ```, `"'L4-OK'"`, `L4-OK.`, `**L4-OK**`, `l4-ok`, `Sure: L4-OK`, `I can't help with that`.

### Probe runner output [V]

Run 1. Real probes, with `usedPercent=100` injected into the parsed Codex result:

```
[l4] implementer: codex-sol skipped — quota: 5h window 100% used, 0% remaining (resets 2026-10-03T17:52Z); cool-down recorded
[l4] implementer: claude-sonnet ok (binary 2.1.288 · auth subscription · quota 60% used (session) · hello 3.5s) → selected, fallback #1
{"event": "availability.selected", "role": "implementer", "unit": "openspec:add-login", "selected": "claude-sonnet", "fallback_index": 1, "skipped": [{"profile": "codex-sol", "step": "quota", "reason": "usage window exhausted", "used_percent": 100, "window_minutes": 300, "resets_at": "2026-10-03T17:52:00Z"}], "probes": {"codex-sol": {"binary": "0.160.0", "auth": "subscription"}, "claude-sonnet": {"binary": "2.1.288", "auth": "subscription", "quota_used_percent": 60, "quota_window": "session", "hello_ms": 3512, "hello_cost_usd": 0.0049654}}}
```

- **Codex.** The trace shows binary 0.84 s, auth 0.60 s and quota 0.58 s, then a stop. No `codex exec` ran, so no
  model request went to Codex.
- **Claude.** Binary 0.01 s, auth 0.68 s, quota 2.68 s (`/usage`, $0) and hello 3.51 s: about 6.9 s for the full
  ladder.
- **Cool-down.** `availability.json` got
  `{"codex-sol|gpt-6.1-sol": {"until": 1791049943, "kind": "usage_limit", "source": "codex app-server account/rateLimits/read", "recorded_by_run": "spike05"}}`,
  and `ledger.jsonl` got an `availability.cooldown` event.

Run 2. No injection; the cool-down is now in the registry:

```
[l4] implementer: codex-sol skipped — cooling until 2026-10-03T17:52Z (usage_limit); no probe sent
[l4] implementer: claude-sonnet ok (binary 2.1.288 · auth subscription · quota 60% used (session) · hello 3.1s) → selected, fallback #1
```

Run 3. A real limit, with no simulation:

```
[l4] implementer: opencode-or skipped — hello: credits (402 openrouter_credits); cool-down recorded
[l4] implementer: opencode-flashlite ok (binary 1.18.33 · auth api_key · quota skipped · hello 3.0s) → selected, fallback #1
```

The `opencode-or` cool-down fell back to `default_cooldown` (30 min) because a 402 carries no reset time.

**Spend for the whole spike:**
- Claude: about $0.05 of API-equivalent usage on the Max plan. The session window went 56 % → 60 %, but other work on
  the same account was running at the same time.
- Codex: about 1 % of the 5-hour window.
- Google (through OpenCode): about $0.008.
- OpenRouter: $0, because every call was rejected.

### Tested code (copied verbatim from `tools/probe_runner.py`, so it survives the temp scratch dir)

```python
def normalise_hello(reply: str | None) -> bool:
    """L4-AVL-001 reply rule, as implemented: trim whitespace; remove ONE wrapping layer if the whole reply is
    enclosed in a matching pair of ``` fences (optional language tag), `…`, "…" or '…'; trim again; must equal L4-OK."""
    if reply is None:
        return False
    s = reply.strip()
    m = re.fullmatch(r"```[A-Za-z0-9_-]*\s*\n?(.*?)\n?\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    elif len(s) >= 2 and s[0] == s[-1] and s[0] in "`\"'":
        s = s[1:-1]
    return s.strip() == "L4-OK"

USAGE_RE = re.compile(r"^Current (session|week \((?P<scope>[^)]+)\)): (?P<pct>\d+)% used"
                      r"(?: · resets (?P<mon>[A-Z][a-z]{2}) (?P<day>\d{1,2})(?:, (?P<year>\d{4}))? at "
                      r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?(?P<ampm>am|pm) \((?P<tz>[^)]+)\))?", re.M)
# year: first candidate in [now.year, now.year+1] that is >= now - 1 day; tz "UTC" or a zoneinfo name.
# window name: "session" | "weekly (<scope>)"; exhausted when ANY window has remaining < min_remaining_percent.
```

Normaliser test table (`tests/test_probe_runner.py`). Every row passes.

| Reply | Accepted |
|---|---|
| `L4-OK` · `L4-OK\n` · `  L4-OK  ` · `` `L4-OK` `` · `"L4-OK"` · `'L4-OK'` · ```` ```\nL4-OK\n``` ```` · ```` ```text\nL4-OK\n``` ```` · `` ␠`L4-OK`␠\n `` | yes |
| ``` ``L4-OK`` ``` (two layers) · `"'L4-OK'"` (two layers) · `L4-OK.` · `**L4-OK**` · `L4-OK!` · `l4-ok` · `L4-OK L4-OK` · `I can't help with that` · empty · `None` · `Sure: L4-OK` | no |

### kiro-cli (docs only; not installed) [D]

Sources: `kiro_headless.md` and `kiro/{reference_cli-commands,reference_exit-codes,reference_slash-commands,getting-started_authentication}.md`.
The current version is 2.27.0 (changelog, 2026-10-01).

| Step | Command | Known | Still [U] for the runner |
|---|---|---|---|
| binary | `kiro-cli --version` (`-V`) [D] | flag exists | output format and regex |
| auth | `kiro-cli whoami --format json` [D] | prints user/ID, auth method (Builder ID, Identity Center, Social) and the **e-mail**, which must be dropped. Auth precedence: **an active browser login (`kiro-cli login`) beats `KIRO_API_KEY`** [D] | JSON field names; exit code when logged out; what it prints for API-key auth; whether it validates the key |
| quota | `kiro-cli chat --no-interactive "/usage"` [D: "In non-interactive runs, `/usage` prints the full usage breakdown"] | monthly credits; reset 00:00 UTC on the 1st [D, §8.3] | **whether it uses credits or a model turn**; whether it combines with `--output-format stream-json`; text format |
| hello | `kiro-cli chat --no-interactive --v3 --output-format stream-json [--model M] "Reply with exactly: L4-OK"`. Stream-json needs V2/V3 [D]. Leave out `--trust-tools`/`--trust-all-tools` so no tool is pre-approved | exit 0/1 [D] | stream-json event schema and the final-text field; credits per hello; whether a tool request with no trust exits or hangs headless; whether an empty `--trust-tools=` means "none" |
| model check | `kiro-cli chat --list-models --format json` [D] | zero-cost listing | field names |
| mcp | `--require-mcp-startup` → exit 3 [D] | 30 s deadline (V3) [D] | — |
| retry behaviour | 2.26.0 retries throttling and 5xx with backoff; idle watchdog 60 s warn / 300 s cancel; 60-min stream timeout [D changelog] | the harness wall-clock timeout must stay | whether a usage-exhausted account fails fast or retries |

## Verdict

**ADAPT.** The ladder works: all four steps ran for real, and the fallback chain produced the L4-AVL-008 lines and
event with no request sent to the exhausted Codex profile. A real OpenRouter credit limit was detected and failed over
correctly. Several per-adapter assumptions in §8.3/§8.4 are wrong or incomplete, though:
1. `--pure` does **not** isolate OpenCode: a hello under the user's config wrote a file and started Serena.
2. Env-credential `auth` checks prove presence, not validity, for every CLI.
3. `codex login status` ignores `CODEX_API_KEY`.
4. Claude's per-model weekly window appears only in the human `/usage` text.
5. The cost figures in L4-AVL-001 are off.
6. A credits limit (402) has no reset time.

## Consequences for SPEC + implementation

1. **L4-AVL-001, `auth` row.** Replace the examples with:
   - **claude:** `claude auth status` (exit 0/1). Keep only `loggedIn`, `authMethod`, and `subscriptionType` as
     `plan`. Map `claude.ai`|`oauth_token` → `subscription` and `api_key` → `api_key`. **MUST drop `email`, `orgId`,
     `orgName`, `projectsDirectory` and `configDirectory`.** `loggedIn:true` from an env credential is not proof:
     `plan` MAY be null, and `hello` is the authoritative auth check.
   - **codex:** `codex app-server` `account/read`, which gives `type` and `planType` in the same session as the quota
     call (about 1 s for both). For `auth: api_key`, check that `CODEX_API_KEY` is set: `codex login status` ignores
     it. If `login status` is used at all, read **stderr** and redact the `sk-…***…` fragment.
   - **opencode:** `opencode auth list`. It is presence-only: strip ANSI, map display names to provider ids
     (lowercase, spaces → `-`), and accept the `Environment` section. Label the step "presence only".
   - **gemini (acp/command profiles):** check that `GEMINI_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI` or
     `GOOGLE_GENAI_USE_GCA` is set, or that `settings.json` sets an auth method. Exit 41 from any call maps to
     `auth: not configured`.
2. **L4-AVL-001, `quota` row, and §8.3 quota cells.**
   - **Claude:** run `TZ=UTC claude -p --safe-mode --no-session-persistence --output-format json "/usage"`. Parse
     `^Current (session|week \((.+)\)): (\d+)% used(?: · resets (Mon) (D)(?:, YYYY)? at h(:mm)?(am|pm) \((TZ)\))?`,
     taking the year as the next occurrence. Allow ±1 min accuracy, and prefer `rate_limit_event.resetsAt` /
     `unifiedWindows` from the latest stream when one exists. With api-key auth the step is skipped (no windows).
   - **Codex:** evaluate `primary` and `secondary` of the `rateLimitsByLimitId` bucket whose `normalModelSlug` equals
     the profile model, or else `codex`. Also fail when `ordinaryUsageAllowed:false`, `rateLimitReachedType != null`
     or `spendControlReached:true`. New rule: **the harness MUST NOT redeem `rateLimitResetCredits`.**
   - **New source for OpenRouter-backed profiles** (`opencode` with `openrouter/…`, and `openai-chat` with the
     OpenRouter `base_url`): `GET /api/v1/credits` (balance = `total_credits − total_usage`) plus `GET /api/v1/key`
     (`limit_remaining`, `limit_reset`). Both are zero-cost and take 0.05 s. This replaces "none queryable" for these
     profiles. It needs a new key, `availability.min_remaining_usd` (proposed default 0.50).
3. **L4-AVL-001, `hello` row.** Replace "Claude ≈ $0.004 / 3 s; Codex ≈ 7 s" with:
   - Claude $0.0008 warm to $0.011 cold, about 3 s.
   - Codex about 5 s and about 19k input tokens; 3 hellos ≈ 1 % of a Plus 5-hour window.
   - OpenCode, isolated, $0.0005 / 3 s.

   Adopt the tested reply rule as normative wording: "trim; remove one wrapping layer — a whole ```` ``` ```` fence
   (optional language tag) or a matching `` ` `` / `"` / `'` pair; trim; must equal `L4-OK`".
   Further changes:
   - **Model choice.** `hello` SHOULD use the **profile's model**, not the cheapest one. A warm Sonnet hello costs the
     same as a warm Haiku hello, and model access and model-family limits (L4-AVL-004) are per model.
   - **Codex.** Use the zero-token `model/list` to validate the model, and run the Codex `hello` only on a cold
     cache entry (L4-AVL-005).
   - **Claude.** Status comes from `is_error` + `api_error_status`, never `subtype` (a 404 bad model has
     `subtype:"success"`). This adds to L4-FAC-002.
4. **§8.3 `opencode` row and L4-SEC-002 / SCN-SEC-02.** `--pure` is **not** isolation. Every OpenCode invocation
   (probe and run) MUST set `XDG_CONFIG_HOME=<harness-owned dir>` and an explicit `OPENCODE_CONFIG_CONTENT`; the probe
   uses `{"tools":{"*":false},"permission":{"*":"deny"}}`. The hello MUST run in an empty dir. It is still [U] whether
   a repo-level `opencode.json` applies under `--pure`: one quick test was inconclusive, so the security spike should
   pin it.
5. **L4-AVL-002.** Add these structured sources:
   - OpenCode `error.data.statusCode` (402 → `credits`, 429 → `rate_limit`) with `isRetryable` and
     `responseBody.error.metadata.limit_source`.
   - Claude `rate_limit_event.status == "rejected"` + `resetsAt`.
   - These are **not** limits: Claude `api_error_status:404` and Codex `turn.failed` 400 (configuration errors),
     OpenCode `Token refresh failed: 401` and Gemini exit 41 (`auth`).
6. **L4-AVL-003.** `kind: credits` has no reset. Give it a separate `availability.credits_cooldown` (proposed 24 h)
   plus a doctor warning, not `default_cooldown`. When an OpenRouter key limit binds, set `resets_at` to the next
   `limit_reset` boundary; the exact boundary semantics are [U].
7. **L4-AVL-008.** The quota figure in the line is the window with the highest use, named:
   `quota 60% used (session)`. The current example's bare "49% used" does not say which L4-AVL-009 window it is. Add
   `quota_window` to `probes.<profile>` in the event. Console `resets` uses `%Y-%m-%dT%H:%MZ` and the JSON uses
   seconds. Add the cooling line: `[l4] <role>: <profile> skipped — cooling until <T> (<kind>); no probe sent`.
8. **L4-AVL-009.** Claude windows are `session`, `weekly (all models)` and `weekly (<model family>)`. The per-model
   window exists only in `/usage` text, not in `rate_limit_event`. For Codex, check every window of the applicable
   bucket.
9. **L4-FAC-008.** With `CLAUDE_CODE_OAUTH_TOKEN` the plan is unknown (`subscriptionType` absent [V]). Whether `/usage`
   returns windows under `CLAUDE_CODE_OAUTH_TOKEN` is [U]: this spike did not run it. For Codex `api_key` the quota
   step is skipped: app-server returns `-32600`.
10. **L4-OBS-002 redaction.** Add these patterns:
    - the `signature` fields of Claude `thinking` blocks (the base64 holds the org id),
    - Claude `orgId`/`orgName`,
    - Codex `chatgptAccountId`/`accountId` and `sk-…***…` fragments,
    - OpenRouter `keys/<hash>` URLs, `user_…` ids and `set-cookie`.
11. **Doctor LIVE-001/002 cost.** Per profile: Claude ≤ $0.011, Codex about 19k tokens of the plan window, OpenCode
    isolated ≤ $0.0006, Kiro [U].
12. **Kiro adapter** (§8.3 row and risk R2). Use `kiro-cli whoami --format json` (drop the e-mail),
    `chat --no-interactive "/usage"` and `chat --list-models --format json`. Doctor MUST warn when a browser login
    exists on a runner whose profile uses `KIRO_API_KEY`, because the login shadows the key. The [U] items in the
    Kiro table above need recorded fixtures before GA (L4-NFR-006).

## Recorded fixtures (paths)

All are under `tests/fixtures/recorded/`. Each directory has a `spike05.index.json` with argv, env, exit and wall
time per case. E-mails, org/account/user ids, key hashes, cookies, thinking signatures and home paths are redacted, and
a grep of all 45 files found zero leaks.

- `claude-code/2.1.288/`: `version.stdout.txt`, `auth_status_logged_in.stdout.json`, `auth_status_logged_out.stdout.json`, `auth_status_api_key_env_unvalidated.stdout.json`, `auth_status_oauth_token_env_unvalidated.stdout.json`, `usage_subscription_local_tz.json`, `usage_subscription_utc.json`, `usage_api_key.json`, `hello_haiku_cold.stream.jsonl`, `hello_haiku_warm.stream.jsonl`, `hello_sonnet_cold.stream.jsonl`, `hello_sonnet_warm.stream.jsonl`, `hello_bad_model.stream.jsonl`, `hello_bad_model.stderr.txt`
- `codex/0.160.0/`: `version.stdout.txt`, `login_status_chatgpt.stderr.txt`, `login_status_logged_out.stderr.txt`, `login_status_env_key_only.stderr.txt`, `login_status_api_key_login.stderr.txt`, `app_server_account_and_rate_limits_chatgpt.json`, `app_server_logged_out.json`, `app_server_api_key_login.json`, `exec_hello_gpt-6.1-sol.jsonl`, `exec_hello_gpt-6-luna.jsonl`, `exec_hello_bad_model.jsonl`, `exec_hello.stderr.txt`
- `opencode/1.18.33/`: `version.stdout.txt`, `auth_list.stdout.txt`, `auth_list_env_only.stdout.txt`, `auth_list_empty.stdout.txt`, `run_hello_user_config_wrote_file.jsonl`, `run_hello_user_config.jsonl`, `run_hello_isolated_cold.jsonl`, `run_hello_isolated_warm.jsonl`, `run_hello_openrouter_402_credits.jsonl`, `run_hello_openai_oauth_refresh_401.jsonl`
- `gemini/0.62.0/`: `version.stdout.txt`, `hello_no_auth.json`
- `openrouter-api/v1/`: `get_key.json`, `get_credits.json`. These are HTTP API responses, not CLI output: the quota
  source for OpenRouter-backed profiles.

Spike code, outside this repo, in `$SCRATCH/spikes/05-availability-probes/`:
- `tools/probe_runner.py`: ladder, injection, cool-down registry and L4-AVL-008 output.
- `tools/codex_quota.py`: app-server client.
- `tools/export_fixtures.py`: sanitiser and exporter.
- `tests/test_probe_runner.py`.

## Addendum (M0 stage B review): the codex hello probe needs `--skip-git-repo-check`

The hello probe runs in the cache root (`l4 run`) or an empty temp dir (`l4 doctor --live`), neither a git repo.
codex-cli 0.155.0-alpha.9.2 (Mac) and 0.160.0 (l4-runner, as gitlab-runner) exit 1 there with "Not inside a
trusted directory and --skip-git-repo-check was not specified." The harness probe now passes the flag (safe with
`-s read-only --ephemeral`); the implementer argv runs in the git worktree and does not need it. SPEC 8.3.1's hello
line still omits the flag and needs the same edit (not made here: SPEC is out of scope for the implementer).
