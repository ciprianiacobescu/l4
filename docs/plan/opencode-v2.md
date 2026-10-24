# OpenCode v1 and v2: what breaks, what L4 does about it (2026-10-19)

Goal: know, with evidence, what OpenCode 2 changes for the `opencode` adapter, make the harness refuse a v2 binary
where it expects v1 today, and add v2 as an opt-in adapter whose every unverified fact has a named, conservative
behaviour until one live run records it.

Two OpenSpec changes cover it:

* `openspec/changes/opencode-major-gate/` (change table row 51): the major-version gate. Every fact it rests on is [V].
  It is needed now, whatever happens to v2.
* `openspec/changes/opencode-v2/` (change table row 68, first planned as row 52): the opt-in v2 adapter
  (`options.cli_major: 2`, default 1). Its [U] facts each have a named fallback and an orchestrator task that records
  them live.

2026-10-24: change A shipped in 0.4.18. Change B resumes for 0.4.28 on the 0.4.27 tree (design "0.4.28 amendment").
The same isolated, no-key check on `@opencode/cli` 2.1.4 found the CLI surface of 2.0.32 unchanged (design E1), so the
matrix below and the 2.0.32 pin stand. Both versions wait without output while stdin stays open [V].

Labels: **[V]** observed (command output, recorded file, code read, vendor page read), **[I]** inferred, **[U]** not
checked (needs a live key or a long run), **[D]** from the vendor's docs only. Everything below was recorded in an
isolated HOME (empty `HOME` and XDG directories, minimal `PATH`, no keys, no user config) with both CLIs installed side
by side from npm: v1 = `opencode-ai@1.18.34`, v2 = `@opencode/cli@2.0.32`. Free models (`opencode/…`) answered
without a key on both versions unless every tool was denied, until the free tier began refusing the recording
machine's network (row 24).

## 0. Verdict

* v2 is released as a separate npm package, `@opencode/cli` (2.0.0 on 2026-09-11, 2.0.32 on 2026-10-16), installed by
  `opencode.ai/v2/install`, the brew tap `anomalyco/tap/opencode-v2`, or npm. v1 (`opencode-ai`) is still maintained
  (1.19.3 on 2026-10-16) [V].
* **L4 0.4.17 cannot run v2.** v2 rejects `--pure` and `--dir` (`Unrecognized flag`, exit 1), so every run and every
  hello fails [V].
* **L4 does not notice.** `prereqs.sh` PRQ-11 accepts `opencode v2.0.32` as `>= 1.18.34` (`sort -V` puts the digit
  first), `min_version` passes, only doctor LIVE-005 warns ("unrecorded version"), and the failed hello is classed
  `transient`, so an opencode profile just looks unavailable and the unit parks in `waiting_capacity` with no named
  cause [V: code read and the recorded outputs].
* `l4 doctor --fix` accepts a v2 `opencode` already on the machine: `runner.py` leaves a present tool alone when it
  meets `min_version` [V code].
* v2 changes four things that decide a run's outcome: success detection (the final `step_finish` is missing in most
  successful runs), `ask` handling (a rejected ask no longer ends the run), the error schema (limit and auth
  classification silently stop working), and the execution model (a shared per-user daemon that serves one client
  another client's configuration unless `--standalone` is passed) [V].
* Recommendation: pin v1 and ship the major gate (change A) in the next 0.4.x; ship v2 as an opt-in, experimental
  adapter (change B) whose [U] cases sit on conservative fallbacks until one live CI run records them.

## 1. Incompatibility matrix

| # | Item | v1 1.18.34 | v2 2.0.32 | Label | L4 impact | Change |
|---|---|---|---|---|---|---|
| 1 | Package and binary | npm `opencode-ai`, bin `opencode` | npm `@opencode/cli`, bins `opencode` and `opencode2`; also curl installer and brew tap | V | Installing both into one npm prefix lets the later one take `.bin/opencode` silently [V]. `opencode upgrade --major` moves a runner to v2 [D] | A refuses a v2 `opencode`; B installs v2 in its own prefix and links only `opencode2` |
| 2 | Runtime | native binary | native binary; writes `.bun-*` libraries into `TMPDIR` | V | the sandbox `TMPDIR` is writable already | none |
| 3 | `--version` | `1.18.34` | `opencode v2.0.32` | V | the Python parser finds both; `ver_ge` in `prereqs.sh` passes v2 | A |
| 4 | `run --pure` | supported | removed: `ERROR Unrecognized flag: --pure in command opencode run` on stderr, the run help on stdout, exit 1; no `OPENCODE_PURE` in the binary | V | every run and hello fails | A classes it `unsupported_version`; B never passes it |
| 5 | `run --dir` | supported | removed the same way; v2 uses the cwd | V | L4 already sets the cwd | A, B |
| 6 | Other run flags | `--format json`, `-m`, `--title`, `--agent`, `-s`, `-c`, `--fork`, `-f`, `--variant`, `--attach`, `--share`, `--port` | kept `--format json`, `-m` (now `provider/model#variant`), `--title`, `--agent`, `-s`, `-c`, `--fork`, `-f`, `--auto`; gone `--variant`, `--attach`, `--share`, `--port`, `-i`; new `--standalone`, `--server` | V | L4 uses only kept flags apart from `--pure` and `--dir` | B |
| 7 | Prompt on stdin | works | works | V | none | none |
| 8 | Execution model | in-process | starts a shared per-user daemon (`serve --service`) that outlives the client, on the fixed port 127.0.0.1:49374, registered in `$XDG_STATE_HOME/opencode/service.json`. The daemon keeps the **first** client's environment: client B was served client A's `OPENCODE_CONFIG_CONTENT`; through the daemon the client's `OPENCODE_API_KEY` was invisible; a second HOME could not start its own daemon (port taken). `models`, `auth list` and `debug config` start it. With `--standalone` a private in-process server ran and nothing was left after the client ended | V (reproduced again on 2026-10-19: a second `debug config` in the same HOME was answered with the first call's configuration) | without `--standalone` concurrent jobs and users get each other's permission rules and keys | B: `--standalone` on every v2 call, a private `XDG_STATE_HOME` per call, never `debug config` |
| 9 | `OPENCODE_CONFIG_CONTENT` | read | read by the server process; v1 keys are normalised in memory without a warning for all six L4 shapes: `snapshot`→`snapshots`, `autoupdate:false`→`update:"disable"`, `share` kept, the `permission` map → an ordered `permissions` array (last match wins in both; order kept), `bash`→`shell`, the `tools` map → deny/allow rules, `provider`→`providers` (`npm`→`package:"aisdk:…"`, `options`→`settings`, `tool_call`→`capabilities.tools`). `list` and `doom_loop` survive but are not v2 actions | V | today's `config_content` would work as is | B emits the native shape and drops `list`, `doom_loop` |
| 10 | `ask` in run mode | auto-rejected, the session ends (3 events, exit 0) | auto-rejected with "This non-interactive run cannot ask the user for permission, so the request was rejected. Continue without this action." and the run **continues**: 30 tool calls in 151 s until the timeout | V | `config_content` uses `refuse="ask"` for `opencode/` free models (a full deny gets 403 on both versions [V]), so a v2 free judge loops until its timeout | B: a per-role `agents.build.steps` bound. A v1-syntax `maxSteps: 3` stopped v2 after 3 steps with a summary, exit 0 [V]; the native `agents.build.steps: 3` resolves to the same configuration value [V: `debug config`, 2026-10-19] |
| 11 | Denial text | deny: "…prevents you from using this specific tool call…"; ask: "The user rejected permission…" | deny: "Permission denied: shell", "Permission denied: external_directory"; ask: row 10's text | V | `_REJECTED` matches neither, so `permission_blocked` and `permission_denials` never fire on v2 | B |
| 12 | `external_directory` default | ask | allow | V docs, V run | L4's explicit `*: deny` plus the result-directory allow held on v2: an outside read was denied and the result file outside the cwd was written | B keeps the explicit rules |
| 13 | `error` event | `error.name`, `error.data.{message, statusCode, isRetryable, responseHeaders, responseBody}` | `error.{type: "provider.auth", message, status, response.body}`; also `unknown`, `aborted` | V (a 403 on both) | `_error_data`, `_classify_error`, `_hello` and `limits._opencode` read `data.statusCode`, so on v2 a 403 is not `auth` and a 402 or 429 is not a limit (code path certain; the 402 and 429 shapes and where `retry-after` lives are U) | B |
| 14 | Final `step_finish` | 6 of 6 finished runs end with `step_finish` reason `stop` | only 3 of 16 finished runs emit it; the stream ends at `text`, exit 0 | V (cause I: the CLI returns on `session.execution.succeeded` before writing the last step) | `parse()` needs a last reason `stop`, so most v2 successes would be `error`, and usage, cost and the context peak are lost | B: `opencode2 session export --standalone <id>` gives `info.outcome: "succeeded"`, `finish: "stop"`, tokens and cost [V] |
| 15 | Other events | `{type, timestamp, sessionID, part}`; `step_finish.tokens.total` | same envelope; no `tokens.total`; `tool_use.part` has `partID`, `id` = a call UUID, no `callID`; tool `shell`; the write input is `path` (was `filePath`) | V | `opencode_signals`, the session id and usage summing still work | B fixtures |
| 16 | Exit codes | error 1; a permission stop 0 | error 1; bad flag 1; aborted 1; SIGINT 130 | V for 1, I for 130 | the exit code becomes load-bearing because of row 14 | B |
| 17 | Auth store and `auth list` | `$XDG_DATA_HOME/opencode/auth.json`; a table with `●` rows and an Environment section | SQLite `opencode.db` (a credential table; `auth.json` is imported by a migration); `auth list` prints "No authenticated integrations"; `auth list --standalone --format json` prints `[]` without a key, and with `OPENCODE_API_KEY` set lists `opencode-go` (an `env` connection) and `opencode` ("OpenCode Console", an `env` connection with `status: needs_auth`) | V | `_auth_providers` finds nothing on v2 | B reads the JSON; credential paths, the login lock and "never redirect `XDG_DATA_HOME`" still hold |
| 18 | `OPENCODE_API_KEY`, model ids | lists Zen and Go models | with `--standalone`, 29 `opencode-go/*` models with the same ids (for example `deepseek-v4.1-flash`); `opencode/` shows as "OpenCode Console"; the positional `models <provider>` is gone | V; the free lists differ between the binaries today (cause I); `openrouter/…` U; the provider renames `azure-cognitive-services`→`azure`, `google-vertex-anthropic`→`google-vertex` are V docs | a v2 profile that names a renamed provider fails at the hello | B refuses the old ids on a v2 profile at load |
| 19 | Environment switches | `OPENCODE_DISABLE_PROJECT_CONFIG`, `_CLAUDE_CODE`, `_EXTERNAL_SKILLS`, `_AUTOUPDATE` | reads `PROJECT_CONFIG` (alias `OPENCODE_CONFIG_PROJECT_DISABLE`), `CLAUDE_CODE`, `CLAUDE_CODE_SKILLS`, `AUTOUPDATE`, `OPENCODE_CONFIG_DIR`, `OPENCODE_DB`; **no** `DISABLE_EXTERNAL_SKILLS` | V (binary strings) | under L4's environment v2 did not load the repository's `AGENTS.md`, `.agents/skills` or `.claude/skills` while the control did [I]; v2 drops `CLAUDE.md` [D] | B keeps all four, adds `_CLAUDE_CODE_SKILLS` and denies the `skill` action |
| 20 | XDG paths, database | as above | the same, plus `service.json` in config and state; the same `opencode.db` file | V; the coexistence below is V for 1 trial | v2 migrated a v1 database additively and v1 still ran afterwards | B: the live run checks v1 after v2 on one runner |
| 21 | Server API and SDK | `serve`, `--attach` | a new API, `--server`, `@opencode/client` | V docs | not used by L4 | none |
| 22 | MCP and skills files | `mcp.<name>{enabled}` | `mcp.servers.<name>{disabled}`; the v1 form is still accepted | V docs | `mcp/install.py` keeps working; the opencode adapter passes no MCP server | none |
| 23 | Hello reply | `L4-OK` | once `"…</think>L4-OK"` (a closing tag with no opening one), 1 of 6 recorded v2 hellos | V once; cause I (model output or v2's reasoning split) | `normalise_hello` fails it, and leaked reasoning with braces would break the judge reply's `{…}` slice | B strips through a leading `</think>` on v2 |
| 24 | Free tier from a flagged network | (not observed) | 403 `provider.auth` "OpenCode's free models aren't available from your current network because we've detected abusive traffic from this IP address…", `FreeTierError` in `response.body`, exit 1 | V on v2, 2026-10-19, the recording machine; v1 I | a runner whose address is flagged loses every free `opencode/` profile, whatever the major | B classes it `auth` (re-probed after `auth_failure_ttl`); the fixture is kept |

## 2. What each change covers

| Need | Change | Requirement |
|---|---|---|
| Read the major from both `--version` forms, everywhere a version is read, with or without `min_version` | A | L4-OCG-001 |
| A wrong major fails closed with a named reason: probe `binary` step, ENV-004, LIVE-005, LIVE-001 | A | L4-OCG-002 |
| A run or hello that a v2 binary rejects is `unsupported_version`, never `transient`, never cached | A | L4-OCG-003 |
| `doctor --fix` and PRQ-11 replace a wrong major with the pinned v1; PRQ-15 never starts a v2 daemon | A | L4-OCG-004 |
| `options.cli_major: 1 \| 2`, default 1, no automatic switching | B | L4-OCV-001 |
| `opencode2` from `@opencode/cli@2.0.32` in its own prefix, in `catalog_hash`, PRQ-20 | B | L4-OCV-002 |
| `--standalone` on every v2 call, a private `XDG_STATE_HOME`, never `debug config` | B | L4-OCV-003 |
| argv and environment | B | L4-OCV-004 |
| the native v2 configuration | B | L4-OCV-005 |
| per-role step bounds | B | L4-OCV-006 |
| status from the exit code, the error event and the exported outcome; usage from the export | B | L4-OCV-007, L4-OCV-008 |
| v2 errors, limits and denials | B | L4-OCV-009 |
| `auth list --standalone --format json` | B | L4-OCV-010 |
| the `</think>` leak | B | L4-OCV-011 |
| probe, doctor and recorded versions per major | B | L4-OCV-012 |
| every [U] case on a named fallback, recorded by one live run | B | L4-OCV-013 |

## 3. Step bounds (change B, L4-OCV-006)

v2's `agents.<id>.steps` is "a positive maximum number of model steps. On the final step, OpenCode removes tools and
asks the model to summarize in text" [D]. With `steps: 3` the recorded v2 ask loop ran two rejected tool calls and a
third, tool-less step that wrote "Maximum steps for this agent have been reached" with a summary, exit 0 [V].

* **Judge mode: 3.** Judge mode covers every tool-less call: the judges, the clarifier, the verifier's generate, audit
  and test-writer calls, the readiness review, the delegate, and the hello probe. All of them go through
  `PermissionPolicy("judge")` [V code]. A judge reply needs exactly one model step: one text turn with the JSON and no
  tool call. A judge-mode step that is not the answer is a tool attempt, which a free model's `ask` rule rejects. v1
  tolerates none (the first rejected ask ends the run, `permission_blocked`). Three steps give one answering step, one
  tolerated rejected attempt and the forced final text step, so v2 is no stricter than v1 and costs at most 3 model
  calls instead of the 30 calls in 151 s recorded without a bound. The floor is 2. With `steps: 1` the only step is
  the final, tool-less "summarize" step [I from the vendor text; the run that would check it was refused by the free
  tier's network block, row 24].
* **Implementer: 200.** Observed maxima: 19 tool calls and 14 model steps per implementer phase (the OpenCode loop
  spike, 7–14 steps and 7–19 tool calls per phase); 18 tool calls / 14 steps in the largest recorded OpenCode
  implementer fixture (`red-ok`); 16 tool calls / 7 steps in the largest live free-model red step; 20 tool calls in
  the largest Kiro implementer fixture. A step is one model turn and several tool calls can share it, so steps ≤
  tool calls. 200 is about 10× the largest tool-call count and about 14× the largest step count. **These maxima come
  from small spike repositories.** A consumer's real step can be longer, which is why the bound is a per-profile
  option (`options.steps.implement`) and why the wall-clock timeout stays the primary bound. An implementer has no
  `ask` rule (edit and shell are allowed, git writes are denied), so its bound only stops a model that never ends.
* v1 is unchanged: no bound is added to a v1 profile, and `options.steps` on a v1 profile is a configuration error.
* A run that reaches its bound is never `ok`. It is `permission_blocked` when denials were recorded, else `error` with
  the detail `step_bound`. The bound is detected from the count of `step_start` events: one per step [V].

## 4. What needs the live run

Each [U] item has a named fallback that the implementation ships with a test that pins it. An orchestrator task
records the real behaviour in CI on the owner's dummy repository with a real `OPENCODE_API_KEY`, never on a consumer
repository. Implementers do not write a parser for a [U] shape from a guess.

| # | [U] fact | Fallback name | Fallback |
|---|---|---|---|
| U1 | the 402 and 429 error shapes, and where `retry-after` lives | `status_only` | `error.status` 429 → `rate_limited` with no reset (`availability.default_cooldown`); 402 → `quota`, kind `credits` (`availability.credits_cooldown`); the body and headers are never parsed |
| U2 | whether a v2 `deny` drops the tool's schema from the request | `tools_by_permission` | `options.tools` on a v2 profile becomes a deny-all rule plus allow rules; the free judge keeps `ask` for `read` and `shell` (a deny-all gets 403 on v2 [V]) |
| U3 | the custom provider's `{file:…}` key under `providers.<id>.settings.apiKey` | `provider_refused` | `cli_major: 2` with `options.provider` is a configuration error at load |
| U4 | the OAuth "Token refresh failed" text on v2 | `auth_by_status` | `status` 401 or 403, `type: "provider.auth"`, or the existing auth wording → `auth`; nothing new is parsed |
| U5 | how often `step_finish` is missing on long runs | `export_decides` | the final `step_finish` is never required; the v1 rule (last reason `stop`) applies only when the export is unavailable |
| U6 | guidance isolation in a real prompt (`AGENTS.md`, `.agents/skills`, `.claude/skills`, `.opencode/skills`) | `deny_skill_and_mask` | all `OPENCODE_DISABLE_*` switches plus `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`, a `skill: deny` rule, the empty judge directory, and the L4-SEC-005 sandbox masks |
| U7 | the exported `outcome` values other than `succeeded`, including that of a run that reached its step bound | `not_ok_named` | any other value is not `ok`; the detail names it; a bounded run is never `ok` whatever the export says |
| U8 | v1 and v2 sharing one `opencode.db` on a runner over time | `live_coexistence` | none in code; the live job runs a v1 hello after the v2 steps on the same runner |
| U9 | the cause of the `</think>` leak, and whether `steps: 1` turns step 1 into the summary step | `strip_leading_think`, judge floor 2 | a v2 text part that holds `</think>` before any `<think>` loses everything through the first `</think>`; the judge bound stays ≥ 2 |
| U10 | SIGINT exit code 130 | `harness_interrupt` | the harness's own interrupt flag decides `cancelled`; the exit code is not consulted |
| U11 | how a multi-step run's export lays out its messages (one recorded export has one assistant message) | `sum_messages` | usage is the sum over assistant messages, the context peak their largest input + cache read + cache write |

The live job (orchestrator): on the owner's dummy repository, in CI on the shared runner, with `OPENCODE_API_KEY` as
a masked secret, profiles `cli_major: 2` on `opencode-go/deepseek-v4.1-flash` (implementer) and a free `opencode/`
judge, plus one `cli_major: 1` profile. One unit end to end. The orchestrator records each [U] fixture under
`tests/fixtures/recorded/opencode/2.0.32/live-*`, scrubbed. The adapter's `experimental` flag comes off only when
every row above has a fixture or a LIVE check (L4-NFR-006).

## 5. Order

1. Change A (two implementer groups), released in 0.4.18. It needs nothing from B.
2. Change B, groups B1–B7 in order, then the orchestrator's live validation (B8), then the docs and the experimental
   flag (B9). B is opt-in: no profile changes behaviour until it sets `options.cli_major: 2`.

Status, 2026-10-24: A is done (released in 0.4.18). B1 to B7 are done and ship in 0.4.28 with the adapter experimental
and not yet checked against a live run (design E8, the owner's decision). B8 (the live validation) and B9 (replacing
fallbacks by recorded behaviour, removing the experimental flag) are deferred to a later release. Every [U] row of
section 4 is still open.
