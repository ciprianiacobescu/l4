## Purpose

Defines how the harness decides, before spending a request, whether a profile is usable: the probe ladder, limit-signal
normalisation, the cool-down registry and probe cache, fail-fast mid-run fallback, waiting for capacity, and the exact
selection log lines.

## ADDED Requirements

### Requirement: L4-AVL-001 (part a) Probe ladder order
Probe ladder steps (`binary`, `auth`, `quota`, `hello`, `mcp`, `custom`) SHALL be configurable per profile, run cheapest first, and the ladder MUST stop at the first failing step.

#### Scenario: SCN-AVL-N18 (−) Ladder stops at the first failure
- **GIVEN** a profile whose `binary` step fails and a ladder `[binary, auth, quota, hello]`
- **WHEN** the ladder runs
- **THEN** `auth`, `quota` and `hello` are not executed and the profile is skipped with the `binary` reason.

### Requirement: L4-AVL-001 (part b) Binary step
The `binary` step MUST check that the executable is on PATH and that its version is at least the profile's `min_version`, and a missing executable SHALL skip the profile with `binary: not found` without a cool-down.

#### Scenario: SCN-AVL-04 (−) Binary missing
- **GIVEN** `kiro-cli` absent from PATH and `kiro` first in a chain
- **WHEN** selection runs
- **THEN** it is skipped with `binary: not found`; doctor ENV-004 reports error (first in chain) or warning (fallback only).

### Requirement: L4-AVL-001 (part c) Auth step
The `auth` step MUST confirm credentials are usable and record only `logged_in`, `auth_method` and `plan`; account e-mail addresses and tokens SHALL be dropped before anything is logged, cached or written to the ledger.

#### Scenario: SCN-AVL-05 (−) Logged out, e-mail never logged
- **GIVEN** `codex login status` exits 1 and `claude auth status` returns JSON containing an e-mail
- **WHEN** probes run
- **THEN** `codex-sol` is skipped with `auth: not logged in`; the Claude probe result records only `logged_in/auth_method/plan`; the e-mail string appears in no log, ledger or outcome file.

### Requirement: L4-AVL-001 (part d) Quota step
The `quota` step SHALL read remaining usage in the current window from a zero-cost source and fail when it is below `min_remaining_percent`; it MUST be skipped, not failed, when the adapter has no zero-cost query.

#### Scenario: SCN-AVL-03 (+) Below the remaining-percent threshold counts as exhausted
- **GIVEN** `min_remaining_percent: 10` and Codex at `usedPercent: 93`
- **WHEN** selection runs
- **THEN** `codex-sol` is skipped with reason `7% remaining < 10%`.

#### Scenario: SCN-AVL-N19 (+) Quota skipped when the adapter has no zero-cost query
- **GIVEN** an `opencode` profile (no quota query) and ladder `[binary, quota, hello]`
- **WHEN** the ladder runs
- **THEN** `quota` is reported `skipped`, `hello` runs, and the profile is not marked failed.

#### Scenario: SCN-AVL-N28 (−) Unrecognised quota output fails the step
- **GIVEN** a quota query whose output cannot be parsed
- **WHEN** the `quota` step runs
- **THEN** the step fails with `quota: unrecognised output` (it is not reported `skipped`), the profile is skipped, and no cool-down is recorded.

### Requirement: L4-AVL-001 (part e) Hello step
The `hello` step SHALL send a single-turn minimal prompt that must return `L4-OK` within `probe_timeout`, accepting the reply after trimming whitespace and one layer of quotes or backticks; any other reply or a timeout MUST fail the step without recording a cool-down, and the child process MUST be killed on timeout.

#### Scenario: SCN-AVL-06 (−) Hello mismatch
- **GIVEN** the hello reply is `I can't help with that`
- **WHEN** the probe runs
- **THEN** the step fails (`hello: unexpected reply`), the profile is skipped, no cool-down is recorded, the failure is cached for the TTL. (`L4-OK` wrapped in whitespace, quotes or backticks is accepted.)

#### Scenario: SCN-AVL-07 (−) Hello timeout
- **GIVEN** the hello call exceeds `probe_timeout`
- **WHEN** the probe runs
- **THEN** the child process is killed, the profile is skipped with `hello: timeout`, no cool-down.

### Requirement: L4-AVL-001 (part f) MCP step
The `mcp` step SHALL verify that the profile's configured MCP servers start (Kiro `--require-mcp-startup` exit 3; Claude and Codex init events) and MUST skip the profile when any required server fails to start.

#### Scenario: SCN-AVL-N20 (−) MCP server that fails to start
- **GIVEN** a profile with a required MCP server whose init event reports `failed`
- **WHEN** the `mcp` step runs
- **THEN** the profile is skipped with `mcp: <server> failed to start` and no cool-down is recorded.

### Requirement: L4-AVL-001 (part g) Custom step
The `custom` step SHALL run a user command from `availability.custom_probes` within its timeout and treat exit code 0 as OK; any other exit code MUST skip the profile with `custom(<name>): exit <code>`.

#### Scenario: SCN-AVL-14 (−) Custom probe fails
- **GIVEN** a custom probe `check-vpn.sh` exiting 1 for `opencode-or`
- **WHEN** selection runs
- **THEN** `opencode-or` is skipped with `custom(check-vpn): exit 1`.

### Requirement: L4-AVL-002 Normalised limit signals
Every limit signal from a probe or a real run SHALL be normalised to `LimitSignal{tool, model?, kind, resets_at?, source, raw_excerpt}` with kind `usage_limit | rate_limit | spend_limit | credits`; structured sources (Codex `resetsAt`, Claude `rate_limit_event.resetsAt`, OpenCode `retry-after`, Kiro month boundary) MUST take precedence over localized text.

#### Scenario: SCN-AVL-N21 (+) Structured reset beats localized text
- **GIVEN** a Claude stream with `rate_limit_event.resetsAt` and a message "resets 6pm (Europe/Bucharest)"
- **WHEN** the signal is normalised
- **THEN** `resets_at` equals the structured epoch and `source` is `claude.rate_limit_event`.

#### Scenario: SCN-AVL-N22 (−) Unparseable text gives no reset time
- **GIVEN** a usage-limit message whose reset phrase cannot be parsed and no structured source
- **WHEN** the signal is normalised
- **THEN** `resets_at` is `None`, `source` is `text`, and the cool-down uses `availability.default_cooldown`.

### Requirement: L4-AVL-003 Cool-down registry
The cool-down registry MUST record `{profile, until, kind, source, recorded_by_run}` in `$L4_CACHE/availability.json` and as a ledger event, selection SHALL skip a cooling profile without spending a request, and a limit without a reset time MUST use `availability.default_cooldown`.

#### Scenario: SCN-AVL-02 (+) Codex 5-hour window exhausted → Claude Code fallback
- **GIVEN** chain `[codex-sol, claude-sonnet]`, Codex app-server reports `primary.usedPercent: 100, resetsAt: T`
- **WHEN** `l4 run` selects the implementer
- **THEN** no model request is sent to Codex; a cool-down for `codex-sol` until T is recorded (cache + ledger); `claude-sonnet` passes binary/auth/quota/hello and is used; the console shows the two lines of L4-AVL-008; every commit of the step carries `L4-Fallback-From: codex-sol`; `outcome.json.units[0].profiles.fallback_from == "codex-sol"`.

#### Scenario: SCN-AVL-N23 (−) Limit without reset time uses the default cool-down
- **GIVEN** a rate-limit with no reset time and `availability.default_cooldown: 30m`
- **WHEN** the registry records it at time T
- **THEN** the entry's `until` is T + 30 minutes.

### Requirement: L4-AVL-004 Model-aware cool-down key
Model-family limits SHALL cool down one model, not the tool: the registry key MUST include the model, and a cooling `(tool, model)` MUST NOT block another model of the same tool.

#### Scenario: SCN-AVL-12 (+) Model-family limit falls back to another model on the same tool
- **GIVEN** chain `[claude-opus, claude-sonnet, codex-sol]` and Claude reports an "Opus limit"
- **WHEN** selection runs
- **THEN** the cool-down is keyed `(claude-code, claude-opus-5-5)`; `claude-sonnet` (same tool) is selected.

#### Scenario: SCN-AVL-N29 (−) A tool-level limit cools every model of the tool
- **GIVEN** a Claude session limit with no model attribution
- **WHEN** the cool-down is recorded and `claude-opus` and `claude-sonnet` are considered
- **THEN** the key is `(claude-code, *)` and both profiles are skipped as cooling.

### Requirement: L4-AVL-005 Probe cache
Probe results SHALL be cached per `(profile, auth identity hash)` for `availability.cache_ttl`, a cached success MUST avoid re-running any probe command, and a real-run failure MUST invalidate the entry immediately.

#### Scenario: SCN-AVL-01 (+) Healthy primary, cached probe
- **GIVEN** a successful probe of `codex-sol` 5 minutes ago (TTL 15 m)
- **WHEN** the implementer is selected
- **THEN** no probe command runs; `availability.selected{selected: codex-sol, fallback_index: 0, cached: true}`.

#### Scenario: SCN-AVL-N24 (−) A failed real run invalidates the cache
- **GIVEN** a cached successful probe of `claude-sonnet` and a real run that ends with status `error`
- **WHEN** the next selection happens
- **THEN** the cache entry is gone and the probe ladder runs again.

### Requirement: L4-AVL-006 (part a) Fail-fast mid-run fallback
On a mid-run limit the adapter MUST fail fast without waiting, the harness SHALL record the cool-down, keep the task's committed progress, re-select via the chain and start a fresh session on the next profile with the "previous attempt" context, and log `availability.fallback` with `from`, `to`, `reason`, `resets_at`.

#### Scenario: SCN-AVL-08 (+) Mid-run limit triggers fail-fast fallback
- **GIVEN** Claude Code emits `api_retry{error: "rate_limit"}` during the green phase of task 2.1
- **WHEN** the adapter sees it
- **THEN** the session is interrupted within 5 s, `RunResult.status = rate_limited` with a `LimitSignal`; a cool-down is recorded; the next profile is selected; it starts a fresh session whose prompt contains the "previous attempt" section; already-committed tasks are not redone; `availability.fallback{from, to, reason, resets_at}` is logged.

#### Scenario: SCN-AVL-N30 (−) Mid-run limit on the last profile of the chain
- **GIVEN** the only remaining usable profile hits `rate_limited` mid-run
- **WHEN** the harness re-selects
- **THEN** no profile is usable, committed progress is kept, the unit goes to `waiting_capacity` (exit 12) and `retry_after` is the earliest reset.

### Requirement: L4-AVL-006 (part b) Bounded wait on silent retries
An adapter whose CLI retries a rate limit silently (OpenCode honours `retry-after` for up to about 24.8 days) MUST be bounded by a wall-clock timeout, and in `serve` mode MUST be aborted on `session.status {type: retry}` with `next` recorded as the cool-down; the job MUST NOT sleep.

#### Scenario: SCN-AVL-11 (−) OpenCode 429 with a long `retry-after` does not hang
- **GIVEN** OpenCode receives a 429 with `retry-after: 18000`
- **WHEN** it runs inside the harness
- **THEN** the harness aborts it (serve mode: on `session.status{type: retry}`; run mode: wall-clock timeout) and records a cool-down of 18000 s; the job does not sleep.

### Requirement: L4-AVL-007 Waiting for capacity
If no profile of a required chain is usable the unit SHALL go to `waiting_capacity`, the run MUST exit 12, and `outcome.json` MUST carry `retry_after` equal to the earliest known reset so the sweeper can resume it after that time.

#### Scenario: SCN-AVL-09 (−) Every profile is cooling
- **GIVEN** all implementer profiles have cool-downs until T1 < T2 < T3
- **WHEN** `l4 run`
- **THEN** no agent is invoked; unit phase `waiting_capacity`; exit 12; `outcome.json.retry_after == T1`.

#### Scenario: SCN-AVL-10 (+) Sweeper resumes after the reset
- **GIVEN** the unit of SCN-AVL-09 and the clock past T1
- **WHEN** the scheduled sweeper runs
- **THEN** the unit is dispatched; selection re-probes the profile whose cool-down expired.

### Requirement: L4-AVL-008 (part a) Console line per considered profile
Every selection MUST print one human-readable `[l4] <role>: <profile> ...` line per considered profile: `skipped — <step>: <reason>` with the reset time and `; cool-down recorded` when applicable, or `ok (<details>) → selected[, fallback #n]` for the chosen one.

#### Scenario: SCN-AVL-N25 (+) Exact line format
- **GIVEN** chain `[codex-sol, claude-sonnet]`, Codex at 100% of its 5-hour window resetting at 2026-10-03T14:32Z, Claude healthy at 49% used with binary 2.1.288 and hello 2.1 s
- **WHEN** the implementer is selected
- **THEN** the console shows exactly `[l4] implementer: codex-sol skipped — quota: 5h window 100% used, 0% remaining (resets 2026-10-03T14:32Z); cool-down recorded` and `[l4] implementer: claude-sonnet ok (binary 2.1.288 · auth subscription · quota 49% used · hello 2.1s) → selected, fallback #1`.

#### Scenario: SCN-AVL-N31 (−) No cool-down suffix without a cool-down
- **GIVEN** a profile skipped because `hello` returned an unexpected reply
- **WHEN** the console line is printed
- **THEN** it reads `[l4] <role>: <profile> skipped — hello: unexpected reply` with no `(resets ...)` and no `; cool-down recorded`.

### Requirement: L4-AVL-008 (part b) Structured selection event
Every selection MUST also emit one `availability.selected` JSON event with `role`, `unit`, `selected`, `fallback_index`, `skipped[]` (profile, step, reason, and used_percent, window_minutes, resets_at when known) and `probes{}`.

#### Scenario: SCN-AVL-N26 (+) Event mirrors the console
- **GIVEN** the selection of SCN-AVL-N25
- **WHEN** the event sink is inspected
- **THEN** it holds one `availability.selected` with `selected: claude-sonnet`, `fallback_index: 1`, one skipped entry for `codex-sol` with `step: quota`, `used_percent: 100`, `window_minutes: 300`, `resets_at: 2026-10-03T14:32:00Z`, and `probes.claude-sonnet` containing `binary`, `auth`, `quota_used_percent`, `hello_ms`.

#### Scenario: SCN-AVL-N32 (−) Event carries no account identity or secret
- **GIVEN** a Claude `auth status` JSON containing an e-mail and an environment holding `ANTHROPIC_API_KEY`
- **WHEN** the `availability.selected` event is serialised
- **THEN** neither the e-mail nor any environment value appears anywhere in the event.

### Requirement: L4-AVL-009 Any exhausted window
A usage-limited profile SHALL count as exhausted when any of its windows (Codex 5-hour and weekly; Claude session, weekly and per-model weekly) has less than `min_remaining_percent` remaining, and its cool-down MUST end at that window's `resets_at`.

#### Scenario: SCN-AVL-16 (−) Weekly window exhausted while the 5-hour window is fine
- **GIVEN** Codex reports `primary.usedPercent: 20` and `secondary.usedPercent: 97` (`min_remaining_percent: 10`)
- **WHEN** selection runs
- **THEN** `codex-sol` is skipped (`weekly window 3% remaining`) with a cool-down until the secondary `resetsAt`.

### Requirement: L4-AVL-010 Required and optional roles
Roles `implementer`, `verifier_agent` and `judges` SHALL be required (no usable profile means `waiting_capacity`, exit 12); roles `clarifier`, `s1_judge` and an LLM `spec_writer` SHALL be optional and MUST be skipped with their documented degradation when no profile is usable.

#### Scenario: SCN-AVL-17 (+) Optional roles degrade, required roles wait
- **GIVEN** Laya is not installed and every clarifier profile is down, but implementer profiles are healthy
- **WHEN** a unit raises a question and later reaches verification
- **THEN** the question goes straight to a human (no auto-accept without S1); S1 steps are recorded `unavailable`; the unit is never put in `waiting_capacity` for these optional roles.

#### Scenario: SCN-AVL-N27 (−) A required role waits even when optional roles are fine
- **GIVEN** every `judges` profile is cooling and the clarifier chain is healthy
- **WHEN** the verifier selects its panel
- **THEN** the selection returns waiting-capacity with `retry_after` equal to the earliest judge reset, and no judge request is sent.
