## Purpose

GitHub Copilot CLI is an L4 agent CLI, `copilot-cli`: an implementer, a tool-less judge, clarifier and readiness
reviewer, and a read-only delegate. It runs from a private home with one credential, `COPILOT_GITHUB_TOKEN`, at a
pinned version installed from a digest-checked tarball, never waits for a limit, never loops on denials unbounded, and
records its tokens and AI credits. It is experimental: no default role chain names it, and it is not released before
one GitHub-routed recording.

## ADDED Requirements

### Requirement: L4-FAC-013 copilot-cli runs every mode from a private home with one common invocation
The harness SHALL register the adapter `copilot-cli` (binary `copilot`) in the factory, in `HARNESS_ADAPTERS`, in
`JUDGE_ADAPTERS` and in the adapters that serve the delegate, and SHALL announce each of its runs as experimental. No
default role chain and no `l4 init` output SHALL name it. Every run SHALL start `copilot --output-format json
--no-ask-user --no-auto-update --no-custom-instructions --disable-builtin-mcps --disable-client-telemetry
--disallow-temp-dir --session-id <id> --usage-output-file <step>/copilot-usage.json --model <model>` followed by the
flags of its mode, where `<id>` is the preset session id or a new uuid4 and `<model>` is the profile's model, or
`auto` when the profile has none or names `auto` in any letter case. The prompt SHALL go on standard input followed
by EOF, never into the argv; an empty prompt SHALL be refused before the spawn. Each run SHALL set `COPILOT_HOME` to a
fresh `<step private dir>/copilot-home` that holds only `settings.json` = `{"autoUpdate": false, "disableAllHooks":
true, "memory": false, "includeCoAuthoredBy": false}`, SHALL set `COPILOT_AUTO_UPDATE=false` and `XDG_CACHE_HOME` to
a fresh per-run directory `<step private dir>/xdg-cache` whose only entry is `copilot/pkg`, a link to the harness's
Copilot package cache (L4-PRV-048), and SHALL NOT pass `COPILOT_ALLOW_ALL`, `CI`, `GH_TOKEN` or `GITHUB_TOKEN`. No argv entry SHALL be `--available-tools` or `--available-tools=`, or start with `--allow-all`,
`--yolo`, `--deny-tool` or `--sandbox`.

#### Scenario: SCN-FAC-22 (+) Every Copilot run has the common argv, its prompt on stdin and a private home
- **GIVEN** a `copilot-cli` profile with `model: claude-sonnet-5.5` and an implement-mode request with a preset session
  id, run with a recording process runner
- **WHEN** the adapter runs it
- **THEN** the argv after the executable starts with the common flags of this requirement in that order, with that
  session id and `--model claude-sonnet-5.5`, the runner's `stdin` is the prompt and no argv entry holds it
- **AND** the environment's `COPILOT_HOME` is `<step>/copilot-home`, which holds exactly `settings.json` with the four
  keys, the environment has `COPILOT_AUTO_UPDATE=false` and `XDG_CACHE_HOME=<step>/xdg-cache`, and
  `<step>/xdg-cache/copilot/pkg` is a link to `<L4 home>/copilot-cache/copilot/pkg`
- **AND** a file left in `<step>/xdg-cache` by an earlier run is gone

#### Scenario: SCN-FAC-23 (+) A Copilot profile with no model runs auto
- **GIVEN** a `copilot-cli` profile with no `model`, and another with `model: AUTO`
- **WHEN** a judge call is made for each
- **THEN** each argv holds `--model auto` and no adapter error is raised

#### Scenario: SCN-FAC-24 (−) No forge token, no trust-all switch and no CI variable reaches the CLI
- **GIVEN** a request whose environment has `COPILOT_ALLOW_ALL=true`, a harness environment with `GH_TOKEN`,
  `GITHUB_TOKEN`, `CI=true` and `COPILOT_GITHUB_TOKEN` set, and an empty prompt in a second request
- **WHEN** the adapter runs the first and then the second
- **THEN** the first spawn's environment has none of `COPILOT_ALLOW_ALL`, `GH_TOKEN`, `GITHUB_TOKEN`, `CI` and
  `COPILOT_GITHUB_TOKEN`, the token reaches the CLI only through the credential loader's file, and no argv entry is
  an empty `--available-tools` or starts with `--allow-all` or `--yolo`
- **AND** the second is refused with `the prompt is empty; copilot-cli reads its prompt from stdin` before any spawn

#### Scenario: SCN-FAC-25 (+) copilot-cli serves every role and no default chain names it
- **GIVEN** the harness's adapter tables and a fresh `l4 init` configuration
- **WHEN** they are read
- **THEN** `copilot-cli` is in the factory's adapters, `HARNESS_ADAPTERS`, `JUDGE_ADAPTERS`, the delegate's serving
  adapters and both copies in the skill's `yolo_preflight.py`
- **AND** the `l4 init` configuration names no `copilot-cli` profile

### Requirement: L4-FAC-014 A Copilot judge offers the model no tool and fails closed on a tool call
In judge mode (the judges, the clarifier, the readiness review and the `s1_judge` stand-in) the adapter SHALL add
exactly `--available-tools=l4_no_tools` and no allow flag, and SHALL run in the empty `judge-cwd`. The reply SHALL be
the content of the last `assistant.message` whose content is not blank, sliced and validated by the shared
prompt-contract helper, so a missing or invalid object takes the judge's repair path. A judge run whose stream holds
any `tool.execution_start` SHALL end as `error` with the detail `copilot-cli judge called a tool (<toolName>)` and no
structured result.

#### Scenario: SCN-FAC-26 (+) The judge argv names an unknown tool and no allow flag
- **GIVEN** a judge-mode request for a `copilot-cli` profile
- **WHEN** the adapter runs it with a recording process runner
- **THEN** the mode flags are exactly `--available-tools=l4_no_tools`, no argv entry starts with `--allow`, and the
  working directory is the empty `judge-cwd`

#### Scenario: SCN-FAC-27 (+) A judge reply with prose around the JSON is the verdict
- **GIVEN** the recorded `judge-hello.jsonl` with its last assistant content replaced by `Here is my verdict:` and a
  valid judge-verdict object
- **WHEN** it is parsed in judge mode with the judge schema and exit 0
- **THEN** the status is `ok`, `structured` is that object, and `model_resolved` is the stream's
  `assistant.message.model`
- **AND** the unchanged recording (`L4-OK`) gives a detail that starts with the structured-output marker

#### Scenario: SCN-FAC-28 (−) A judge that called a tool gives no verdict
- **GIVEN** the recorded `delegate-view.jsonl` (a `view` call, then text) with a valid verdict as its last content
- **WHEN** it is parsed in judge mode with exit 0
- **THEN** the status is `error`, the detail is `copilot-cli judge called a tool (view)`, and `structured` is None

### Requirement: L4-FAC-015 A Copilot delegate offers only the read tools and fails closed on any other tool
In read-only mode the adapter SHALL add exactly `--available-tools=view,grep,glob` and no allow flag, and SHALL run in
the delegate's detached worktree, built with the instruction files removed as for opencode. A run that started any
tool whose name is not `view`, `grep`, `rg` or `glob` SHALL end as `error` with the detail `copilot-cli delegate
called a tool outside the read set (<sorted names>)` and no structured result. Otherwise the reply SHALL be the
assistant text after the last tool call, else the last assistant text, read by the shared read-only helper.

#### Scenario: SCN-FAC-29 (+) The delegate reads and answers after its last read
- **GIVEN** a read-only request for a `copilot-cli` profile, and the recorded `delegate-view.jsonl` whose last
  assistant content after its `view` call is replaced by a valid delegate-result object
- **WHEN** the adapter builds the argv and parses that stream with exit 0
- **THEN** the mode flags are exactly `--available-tools=view,grep,glob` with no allow flag, the detached tree is
  built masked, and the status is `ok` with that object

#### Scenario: SCN-FAC-30 (−) A delegate that ran a non-read tool gives no reply, and rg counts as a read
- **GIVEN** the recorded `implement-bash.jsonl` (a `bash` call), and a stream whose only tool call is `rg` followed by
  a valid object
- **WHEN** each is parsed in read-only mode with exit 0
- **THEN** the first is `error` with `copilot-cli delegate called a tool outside the read set (bash)` and no
  `structured`
- **AND** the second is `ok`

### Requirement: L4-FAC-016 A Copilot implementer edits the worktree, runs only the gate binary and writes its result
In implement mode the adapter SHALL add, in this order, `--allow-tool=write`, `--allow-tool=shell(<first word of the
gate prefix>:*)` when the policy has a gate prefix, and `--add-dir <step private dir>`, and SHALL run in the worktree.
With MCP servers in the request it SHALL write `<step>/copilot-mcp.json` = `{"mcpServers": {<name>: <server
entry>}}` and add `--additional-mcp-config @<that path>` and one `--allow-tool=<name>` per server. The result SHALL be
the prompt contract: the file that `$L4_RESULT_PATH` names, validated against the request's schema. Each
`tool.execution_complete` whose `error.code` is `denied` SHALL be recorded as a permission denial with the tool name
of its start event, and SHALL NOT by itself fail the run.

#### Scenario: SCN-FAC-31 (+) The implementer argv allows writes, the gate binary and the result directory
- **GIVEN** an implement-mode request with the gate prefix `.venv/bin/python -m pytest` and no MCP server
- **WHEN** the adapter builds the argv
- **THEN** the mode flags are exactly `--allow-tool=write --allow-tool=shell(.venv/bin/python:*) --add-dir <step>`

#### Scenario: SCN-FAC-32 (+) The result file decides, and a denial is recorded
- **GIVEN** the recorded `implement-denied.jsonl` with exit 0 and no result file, and the recorded
  `implement-bash.jsonl` with exit 0 and the result file `{"status": "green"}`
- **WHEN** each is parsed in implement mode with a schema that requires `status`
- **THEN** the first has `permission_denials == [{"tool_name": "bash"}]` and no structured result
- **AND** the second is `ok` with `structured == {"status": "green"}`

#### Scenario: SCN-FAC-33 (+) An MCP server is injected through a file and its own allow rule
- **GIVEN** an implement-mode request with the MCP server `serena`
- **WHEN** the adapter runs it with a recording process runner
- **THEN** `<step>/copilot-mcp.json` holds `{"mcpServers": {"serena": …}}` with the server's command and args, and
  the argv holds `--additional-mcp-config @<step>/copilot-mcp.json` and `--allow-tool=serena`

### Requirement: L4-FAC-017 A Copilot run's status comes from its stream, its exit code and its standard error
The adapter SHALL take the session id from the final `result` event, the served model from the last
`assistant.message.model`, and the HTTP status from `session.error.statusCode`. Unless L4-FAC-018 decides it, a run
SHALL end, first match wins: `timeout` when it timed out or stalled; `cancelled` when the caller interrupted it;
`auth` with `copilot-cli found no credential (set COPILOT_GITHUB_TOKEN)` when it exited non-zero with no JSON event
and its standard error says `No authentication information found`; from the last `session.error`: `auth` with
`copilot-cli could not authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)` for `errorType`
`authentication` or status 401 or 403, `rate_limited` with `copilot-cli reported a rate limit (session.error 429)`
for 429, `quota` with a `credits` limit and `copilot-cli reported that the AI credits are used up (session.error
402)` for 402, else `error` with `copilot-cli reported an error (<errorType or unknown>, status <statusCode or
none>)`, retryable when the status is a server-side overload or at least 500; `error` with `copilot-cli could not
extract its bundled package (the L4 package cache is cold or not writable): run l4 doctor --fix` when it exited
non-zero and its output says `Failed to extract bundled package`; `error` with `copilot-cli exited with code <n>` for
any other non-zero exit; else its mode decides. Every limit SHALL name the source `copilot.session_error`.

#### Scenario: SCN-FAC-34 (+) The recorded errors map to statuses
- **GIVEN** the recorded `error-401.jsonl`, `error-402.jsonl` and `error-500.jsonl`, each with exit 1
- **WHEN** each is parsed
- **THEN** they are `auth` (limit kind `auth`), `quota` (limit kind `credits`) and `error` with `api_status` 500 and
  `transient` true, each with the detail of this requirement

#### Scenario: SCN-FAC-35 (−) No credential is an auth failure with no stream
- **GIVEN** an empty stdout, exit 1 and the standard error `Error: No authentication information found.`
- **WHEN** it is parsed
- **THEN** the status is `auth` and the detail is `copilot-cli found no credential (set COPILOT_GITHUB_TOKEN)`

#### Scenario: SCN-FAC-36 (−) A cold package cache and an unknown exit are errors that name the cause
- **GIVEN** exit 1 with a standard error that holds `Failed to extract bundled package`, and exit 3 with no stream and
  an empty standard error
- **WHEN** each is parsed
- **THEN** the first is `error` with the extraction detail of this requirement and the second is `error` with
  `copilot-cli exited with code 3`

### Requirement: L4-FAC-018 A Copilot run is stopped on its own rate-limit retry and on a loop of denied calls
Every run SHALL pass a line watcher to the process runner as its stop hook. The watcher SHALL stop the run on the first
`assistant.turn_retry` whose `reason` is `rate_limit`, and when 20 `tool.execution_complete` events in a row have
`error.code` `denied` (any other completion SHALL set the count back to zero). It SHALL keep no text of a line and
SHALL NOT raise. A run the watcher stopped for a rate limit SHALL end as `rate_limited` with the detail `copilot-cli
was retrying a rate limit; the harness stopped the run (it never waits for a limit)` and a `rate_limit` limit from
`copilot.turn_retry` with no reset time, so the profile cools for `availability.default_cooldown` and the next profile
takes the step. A run it stopped for denials SHALL end as `permission_blocked` with the detail `copilot-cli was
stopped after 20 denied tool calls in a row: its permission rules refuse what it tries`. A run that timed out or
stalled with no `result` event, whose stream holds a `rate_limit` retry or a `model.call_failure` with status 429,
SHALL end as `rate_limited` with the detail `copilot-cli was waiting out a rate limit when the run timed out`. The
decision SHALL come from the watcher's own record and the stream, not only from the runner's abort flag.

#### Scenario: SCN-FAC-37 (+) The first rate-limit retry stops the run and the next profile takes the step
- **GIVEN** a process runner that feeds the recorded `error-429-retrying.jsonl` line by line to the stop hook and
  stops at the first line for which it returns true
- **WHEN** an implementer step runs on that profile with a second implementer profile in the chain
- **THEN** the hook returned true on the first `assistant.turn_retry` line, the run is `rate_limited` with the detail
  of this requirement and a limit from `copilot.turn_retry`, the profile cools for `availability.default_cooldown`, and
  the second profile takes the step without using an attempt

#### Scenario: SCN-FAC-38 (−) A run that stalled while the CLI waited out a 429 is a rate limit, not a timeout
- **GIVEN** the first six lines of `error-429-retrying.jsonl` (one 429 `model.call_failure`, no retry yet, no
  `result`) and an outcome that stalled
- **WHEN** it is parsed
- **THEN** the status is `rate_limited` with `copilot-cli was waiting out a rate limit when the run timed out`

#### Scenario: SCN-FAC-39 (−) Twenty denials in a row stop the run; a success in between resets the count
- **GIVEN** a stream of 20 `tool.execution_complete` events with `error.code: "denied"`, and another of 19 denied,
  one successful and 19 denied completions
- **WHEN** each is fed to a new watcher
- **THEN** the first watcher returns true on the 20th denial and the parsed run is `permission_blocked` with the detail
  of this requirement
- **AND** the second watcher never returns true

### Requirement: L4-FAC-019 Copilot usage counts tokens and AI credits, never dollars, and its reader counts tool calls
The adapter SHALL read `<step>/copilot-usage.json` after the run as a regular file of at most 1 MiB. Input, output and
cached input tokens SHALL be the sums of `inputTokens`, `outputTokens` and `cacheReadTokens` over `modelMetrics`.
`totalNanoAiu / 1e9`, when it is a number above 0, SHALL be the run's credits with the source `copilot.usage_file`;
`cost_usd` SHALL stay None, and credits SHALL NOT be added to any dollar total. A missing, linked, oversized or
unreadable document SHALL be zero usage. No context peak SHALL be reported. The stream reader `copilot_signals` SHALL
return `start(toolCallId)` for `tool.execution_start` and `end(toolCallId)` for `tool.execution_complete`, and no
signal, without raising, for any other line; it SHALL keep no text.

#### Scenario: SCN-FAC-40 (+) Tokens and AI credits are recorded, never as dollars
- **GIVEN** the recorded `implement-bash.usage.json`, and a document with `totalNanoAiu: 2500000000` and one model of 10
  input and 2 output tokens
- **WHEN** each is read as the run's usage
- **THEN** the first has 21350 input, 63 output and 20891 cached input tokens and no credits
- **AND** the second has 10 input and 2 output tokens, `credits == 2.5`, `credits_source == "copilot.usage_file"` and
  `cost_usd` None

#### Scenario: SCN-FAC-41 (+) The reader sees each tool call open and close, and nothing else
- **GIVEN** the lines of the recorded `implement-bash.jsonl`, a line that is not JSON and a JSON array line
- **WHEN** `copilot_signals` reads each
- **THEN** it returns `start(call_ek41zsie)` for the `tool.execution_start` line, `end(call_ek41zsie)` for the
  `tool.execution_complete` line, and no signal for every other line, without raising

### Requirement: L4-FAC-020 A Copilot profile's vendor is its model's family, auto is routed, and the served model is checked
The vendor of a `copilot-cli` profile with a pinned model SHALL be its model family's vendor with provenance
`declared` (`MODEL_FAMILIES`, which SHALL also map `grok-` to `xai` and `mai-` to `microsoft`), and a `vendor:` that
contradicts that family SHALL fail to load as for `kiro-cli`. A `copilot-cli` profile with no model, a blank model or
`auto` SHALL be routed: its possible vendors and models SHALL be the built-in set of Copilot CLI 1.0.102's model list,
whatever `vendor:` says. The adapter SHALL report `served_model`. Under `auto`, a concrete served model (neither empty
nor `auto`) SHALL be the judge's served model and SHALL be checked against the implementers' vendors as for every
adapter that reports one. For a pinned model, a served model that differs under model normalisation SHALL be
`model_mismatch`, and one that is the same SHALL report nothing, so the judge stays `declared`.

#### Scenario: SCN-FAC-42 (−) A Copilot profile's vendor follows its model, and a contradicting vendor does not load
- **GIVEN** `copilot-cli` profiles `{model: claude-sonnet-5.5}`, `{model: grok-4.1}` and `{model: claude-sonnet-5.5,
  vendor: microsoft}`
- **WHEN** the configuration is loaded and the vendors are resolved
- **THEN** the first is `anthropic` and the second `xai`, both `declared`
- **AND** the third fails to load with `vendor contradicts the model: claude-sonnet-5.5 is made by anthropic`

#### Scenario: SCN-FAC-43 (−) A Copilot judge on auto is not independent of a Claude Code implementer
- **GIVEN** `roles.judges: [copilot-judge]` with `{adapter: copilot-cli}` (no model) and a unit implemented by a
  claude-code profile, under `independence: different_vendor`
- **WHEN** a judge is selected
- **THEN** `copilot-judge` is vetoed (`anthropic` is among its possible vendors) and, with no other judge, the unit
  waits with `no independent verifier`

#### Scenario: SCN-FAC-44 (−) A served model is checked under auto and compared under a pinned model
- **GIVEN** a unit implemented by `{adapter: opencode, model: opencode-go/deepseek-v4.1-flash, vendor: deepseek}`; a
  Copilot judge on `auto` whose reply names `assistant.message.model: mystery-model-1` (no known family); and a Copilot
  judge pinned to `gpt-6.1-sol` whose reply names `claude-sonnet-5.5`
- **WHEN** each judge answers in step 9
- **THEN** both results are `model_mismatch`, no verdict of either is used, and each profile cools with kind
  `model_mismatch`
- **AND** the `auto` judge whose reply names `gpt-6.1-sol` gives its verdict with the line `served gpt-6.1-sol`, and
  the pinned judge whose reply names `gpt-6.1-sol` gives its verdict with provenance `declared`

### Requirement: L4-FAC-021 The Copilot probe ladder proves the binary, the token and one tool-less reply
The `binary` step SHALL read `copilot --version` with `COPILOT_AUTO_UPDATE=false` and `XDG_CACHE_HOME` = the package
cache, and SHALL apply the major gate (L4-OCG-006) and `min_version`. The `auth` step SHALL pass when
`COPILOT_GITHUB_TOKEN` is set and SHALL fail with `COPILOT_GITHUB_TOKEN is not set` when it is not, whatever `auth:`
says; it SHALL read no stored login. The `quota` step SHALL be skipped with the reason `copilot-cli has no headless
quota query`. The `hello` step SHALL run the common argv with `--available-tools=l4_no_tools` and `-p <hello prompt>`
from an empty directory and a private `COPILOT_HOME` in a temporary directory, with the credential, and SHALL pass on
the reply `L4-OK`. A hello that started a tool SHALL fail with `copilot-cli hello called a tool (<toolName>)`. A hello
whose output holds a `rate_limit` retry or a 429 `model.call_failure` SHALL fail as a rate limit with `copilot-cli was
retrying a rate limit (hello)`, also when it timed out.

#### Scenario: SCN-FAC-45 (+) The auth step reads the variable only and the quota step is skipped
- **GIVEN** a `copilot-cli` profile with `auth: subscription`, once with `COPILOT_GITHUB_TOKEN` set and once without
- **WHEN** the `auth` and `quota` steps run with a recording probe runner
- **THEN** the first `auth` passes with `auth_method: env`, the second fails with `COPILOT_GITHUB_TOKEN is not set`,
  and neither starts a process
- **AND** the `quota` step is skipped with `copilot-cli has no headless quota query`

#### Scenario: SCN-FAC-46 (+) The hello is a tool-less call with the prompt as an argument
- **GIVEN** a probe runner that records the argv, environment and working directory and answers with the recorded
  `judge-hello.jsonl`
- **WHEN** the `hello` step runs
- **THEN** the argv holds `--available-tools=l4_no_tools`, `-p` and the hello prompt, the environment has
  `COPILOT_HOME` inside the step's temporary directory, `COPILOT_AUTO_UPDATE=false`, the package cache and the token,
  the working directory is empty, and the step passes

#### Scenario: SCN-FAC-47 (−) A hello that waited out a 429 is a rate limit
- **GIVEN** a probe runner that answers with the first six lines of `error-429-retrying.jsonl` and exit 124
- **WHEN** the `hello` step runs
- **THEN** it fails with `copilot-cli was retrying a rate limit (hello)`, a `rate_limit` limit and the failure class
  `limit`

### Requirement: L4-FAC-022 BYOK streams are no contract recording, and a GitHub-routed recording gates the release
The BYOK streams SHALL live in `tests/fixtures/recorded/copilot-cli/1.0.102-byok/` and the outputs recorded without a
token in `tests/fixtures/recorded/copilot-cli/1.0.102-notoken/`; `recorded_versions.json` SHALL NOT list
`copilot-cli` for either. The change SHALL NOT be released before one GitHub-routed recording session with a real
token, on the owner's dummy repository and never a consumer, has added `tests/fixtures/recorded/copilot-cli/1.0.102/`,
regenerated `recorded_versions.json` and corrected every mapping that the recording disproves. No test SHALL need a
token.

#### Scenario: SCN-FAC-48 (+) The BYOK and no-token fixtures are not a recorded version
- **GIVEN** the fixture tree before the live recording
- **WHEN** `python -m l4.recordedversions --write` runs
- **THEN** `recorded_versions.json` has no `copilot-cli` key and LIVE-005 reports nothing for a `copilot-cli` profile

#### Scenario: SCN-FAC-49 (+) The GitHub-routed recording lists the version and its streams parse
- **GIVEN** the recording session of this requirement, done with the owner's token in CI on the owner's dummy
  repository
- **WHEN** its streams are written to `tests/fixtures/recorded/copilot-cli/1.0.102/` and `recorded_versions.json` is
  regenerated
- **THEN** `recorded_versions.json` lists `copilot-cli: ["1.0.102"]`, and the adapter's parse tests pass on the
  recorded judge, delegate and implementer streams with the statuses and texts of L4-FAC-014 to L4-FAC-019

### Requirement: L4-PRV-047 Copilot CLI is pinned and installed from its release tarball against the harness's digests
The catalog SHALL pin `copilot-cli` at `COPILOT_VERSION = "1.0.102"` in `ADAPTER_PINS`, and `catalog_pins()` SHALL list
`agent:copilot-cli`. The harness SHALL install it from
`https://github.com/github/copilot-cli/releases/download/v<version>/copilot-<asset>.tar.gz` and SHALL compare the
archive's sha256 with `COPILOT_SHA256` (by version, then by `linux-x64`, `linux-arm64`, `linux-x64-musl`,
`linux-arm64-musl`, `darwin-x64`, `darwin-arm64`); it SHALL never fetch `SHA256SUMS.txt` to install and never run the
vendor's installer. On Linux the gnu build SHALL be chosen when a glibc version is found, else the musl build. A
mismatch SHALL remove the archive, change nothing in `~/.local/bin`, and fail the action naming both digests and
ending `do not install it by hand: report it, or hold another version in ci.cli_versions (one the harness holds)`. A
download refused with HTTP 403 or 404 SHALL fail with `cannot download copilot <version> from <host> (<reason>): that
version may no longer be served; hold another version in ci.cli_versions (one the harness holds) or report it`. The
harness SHALL extract only the member `copilot`, a regular file of at most 512 MiB, stage it beside its target with
mode 0755, and rename it over `~/.local/bin/copilot`, restoring the earlier file if the rename fails; it SHALL read no
other member and download into a temporary directory that is removed when the step ends. A version with no digest in
the table SHALL be a `manual` action with `copilot <version> (<source>) has no sha256 in this harness (it holds
1.0.102): install it yourself and keep it, or hold one of those`. Under `l4 doctor --ci --fix` a present `copilot` of
another version SHALL be replaced by the pin, and every install SHALL be checked exactly.

#### Scenario: SCN-PRV-129 (+) doctor --ci --fix installs Copilot CLI from the pinned tarball
- **GIVEN** a `linux-x64` runner with glibc 2.39, no `copilot`, a `copilot-cli` profile in a role chain, and a fetcher
  that serves a tarball whose sha256 equals a test table's entry for that key
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** the only URL fetched for Copilot is
  `https://github.com/github/copilot-cli/releases/download/v1.0.102/copilot-linux-x64.tar.gz`, `~/.local/bin/copilot`
  exists with mode 0755 and no other new file is there, the temporary directory is gone, and the action is `applied`
  with `copilot 1.0.102`

#### Scenario: SCN-PRV-130 (−) A tarball whose digest differs installs nothing
- **GIVEN** the same runner and a fetcher that serves a tarball whose sha256 is not the table's
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** the action is `failed` naming both digests and ending `do not install it by hand: report it, or hold
  another version in ci.cli_versions (one the harness holds)`, nothing under `~/.local/bin` changed, and doctor exits 3

#### Scenario: SCN-PRV-131 (+) The tarball follows the system, the architecture and the libc
- **GIVEN** `linux-arm64` with glibc 2.39, `linux-x64` where no glibc version can be read, and `darwin-arm64`
- **WHEN** the harness picks the Copilot tarball for each
- **THEN** they get `copilot-linux-arm64.tar.gz`, `copilot-linuxmusl-x64.tar.gz` and `copilot-darwin-arm64.tar.gz`,
  each checked against its own row of the table

#### Scenario: SCN-PRV-132 (−) A missing, linked or oversized member is never extracted
- **GIVEN** tarballs whose digest matches a test table and that hold no `copilot`, `copilot` as a symbolic link, and
  `copilot` with a header size above 512 MiB
- **WHEN** each is installed
- **THEN** each action is `failed` with its text of design T22, and `~/.local/bin` is unchanged

#### Scenario: SCN-PRV-133 (−) A version the harness holds no digest for is never downloaded
- **GIVEN** `ci.cli_versions: {copilot-cli: "1.0.103"}` on a Linux runner without `copilot`, and a fetcher that
  answers HTTP 404 for the pinned version on a second runner
- **WHEN** `l4 doctor --ci --fix` runs on each
- **THEN** the first action is `manual` with `copilot 1.0.103 (ci.cli_versions) has no sha256 in this harness (it
  holds 1.0.102): install it yourself and keep it, or hold one of those` and nothing is fetched
- **AND** the second action is `failed` with `cannot download copilot 1.0.102 from github.com (HTTP 404): that
  version may no longer be served; hold another version in ci.cli_versions (one the harness holds) or report it`

### Requirement: L4-PRV-048 The Copilot package is extracted at install into an L4 cache that runs read-only
The harness's Copilot package cache SHALL be `<L4 home>/copilot-cache`, under the L4 home, which the sandboxes bind
read-only. `XDG_CACHE_HOME` of a probe step and of a provisioning or doctor version read SHALL be that directory. An
agent run SHALL reach the package only through the link of its per-run cache directory (L4-FAC-013), so the commands the
agent runs keep a writable cache of their own. After an install the harness SHALL run the pinned `copilot` once with
that cache (the warm-up) and SHALL fail the action with `copilot <version> did not extract its package into
<cache>/copilot/pkg (copilot --version ran with XDG_CACHE_HOME=<cache>)` when `<cache>/copilot/pkg/` then holds no
directory.

#### Scenario: SCN-PRV-134 (+) The install warms the package cache
- **GIVEN** an install runner whose `copilot --version` stub writes `<XDG_CACHE_HOME>/copilot/pkg/linux-x64/1.0.102/`
  when that variable is set, and another stub that writes nothing
- **WHEN** the Copilot install runs with each
- **THEN** the first action is `applied`, and the stub saw `XDG_CACHE_HOME=<L4 home>/copilot-cache` and
  `COPILOT_AUTO_UPDATE=false`
- **AND** the second action is `failed` with the warm-up text of this requirement

#### Scenario: SCN-PRV-135 (+) Version reads use the cache, and a run links to it from a writable directory
- **GIVEN** a probe `binary` step, a doctor ENV-004 version read, and a `copilot-cli` implementer step with its agent
  sandbox spec
- **WHEN** each builds its command
- **THEN** the probe and doctor environments have `XDG_CACHE_HOME=<L4 home>/copilot-cache`
- **AND** the implementer's environment has `XDG_CACHE_HOME=<step>/xdg-cache`, inside the writable step directory, and
  the bwrap argv binds the L4 home with `--ro-bind`

### Requirement: L4-PRV-049 Copilot's only credential is COPILOT_GITHUB_TOKEN, and no Copilot login enters a sandbox
The credential variable of a `copilot-cli` profile SHALL be `COPILOT_GITHUB_TOKEN` under every `auth:` value, delivered
to a run only through the credential loader (L4-PRV-024). The variable SHALL be in the default redaction list and in
the identity variables of the probe cache and the cool-downs. `~/.copilot` SHALL be a `copilot-cli` login path that
every sandbox hides, the `copilot-cli` sandbox included, and no sandbox SHALL bind it. `copilot-cli` SHALL NOT be an
adapter whose login the harness serialises as a refreshable OAuth store. Doctor PRV-001 SHALL print, for a `copilot-cli`
profile that is not ready, `create a fine-grained personal access token owned by your personal account (not an
organization) with the Copilot Requests permission (classic ghp_ tokens are refused)` and `store it as the masked CI
variable COPILOT_GITHUB_TOKEN`, worded for a GitHub secret on GitHub.

#### Scenario: SCN-PRV-136 (+) The token reaches the run through the loader and is redacted
- **GIVEN** a `copilot-cli` profile with `auth: subscription`, another with `auth: api_key`, and a harness environment
  with `COPILOT_GITHUB_TOKEN` set
- **WHEN** the credential variable is read, a run is spawned and a line holding the value is redacted
- **THEN** both profiles name `COPILOT_GITHUB_TOKEN`, the run's argv starts with the credential loader and its
  environment dict has no `COPILOT_GITHUB_TOKEN`, and the redacted line holds no part of the value

#### Scenario: SCN-PRV-137 (−) ~/.copilot is hidden from every sandbox, Copilot's own included
- **GIVEN** a home with `~/.copilot/config.json`, and agent sandbox specs for a `copilot-cli` step and a `claude-code`
  step
- **WHEN** the bwrap argv of each is built
- **THEN** both hide `~/.copilot` and neither has a `--bind` or `--ro-bind` of it
- **AND** the `claude-code` step still binds its own login as before

#### Scenario: SCN-PRV-138 (+) Readiness names the token and where it goes
- **GIVEN** a `copilot-cli` profile whose `auth` probe fails, on GitLab and on GitHub with the environment `ci`
- **WHEN** PRV-001 runs
- **THEN** the GitLab steps are the two texts of this requirement, the second GitHub step names a secret of the GitHub
  environment `ci` called `COPILOT_GITHUB_TOKEN` (the existing `steps_for` wording), and the detail is `<profile>:
  COPILOT_GITHUB_TOKEN is not set`

### Requirement: L4-PRV-050 prereqs.sh installs Copilot CLI at the pin on request (PRQ-22)
`scripts/runner/prereqs.sh` SHALL have a step PRQ-22 "Copilot CLI" that runs only with `--with-copilot` and otherwise
reports `SKIP` with `pass --with-copilot to install`. Its top block SHALL hold `COPILOT_VERSION` and the four Linux
digests of the catalog's pin row, which a drift test SHALL compare with the catalog. Its check SHALL pass only when
the runner user's `copilot --version` reports exactly `COPILOT_VERSION`, and SHALL name another major as `Copilot CLI
<n>; L4 runs Copilot CLI 1`. Its apply SHALL download the asset of the machine's architecture and libc, check it with
`sha256sum -c` before anything is installed, extract only `copilot`, install it with `install -m 755` into the runner
user's `~/.local/bin`, run the warm-up of L4-PRV-048, and run no installer script.

#### Scenario: SCN-PRV-139 (+) PRQ-22 is opt-in and its pins equal the catalog's
- **GIVEN** the text of `scripts/runner/prereqs.sh`
- **WHEN** its steps and its top block are parsed
- **THEN** PRQ-22 is a step guarded by `WITH_COPILOT` set by `--with-copilot`, the default reports `SKIP`, and
  `COPILOT_VERSION` and the four `COPILOT_SHA256_*` equal the catalog's pin row

#### Scenario: SCN-PRV-140 (−) PRQ-22 accepts only the exact pin and checks the digest first
- **GIVEN** `check_copilot` with a stub runner user whose `copilot --version` prints `GitHub Copilot CLI 1.0.101.`,
  then `GitHub Copilot CLI 2.0.0.`, then `GitHub Copilot CLI 1.0.102.`, and the text of `apply_copilot`
- **WHEN** the check runs for each and the apply text is read
- **THEN** only the last passes, the second's DETAIL names `Copilot CLI 2; L4 runs Copilot CLI 1`, and in the apply
  text `sha256sum -c` comes before `install -m 755` and no `curl … | sh` appears

### Requirement: L4-OCG-006 A copilot of another major than 1 is refused with a named reason
The supported major of the `copilot-cli` adapter SHALL be the major of the pinned `COPILOT_VERSION` (1), in
`SUPPORTED_MAJORS`. Every caller of L4-OCG-001 and L4-OCG-002 SHALL apply it to `copilot --version` whether or not the
profile sets `min_version`: the probe `binary` step SHALL fail without running `auth`, `quota` or `hello`; doctor
ENV-004 and LIVE-005 SHALL report it; `l4 doctor --ci --fix` SHALL replace it with the pin and a person's `l4 doctor
--fix` SHALL leave it as a `manual` action; PRQ-22 SHALL not accept it. The reason SHALL be `copilot <version> is
Copilot CLI <major>; L4 runs Copilot CLI 1: install copilot <pin> (in CI l4 doctor --ci --fix installs it; l4 doctor
prints the command for this machine); Copilot CLI <major> support comes in a later L4 release`, with the effective pin.
The OpenCode and Kiro texts SHALL stay unchanged.

#### Scenario: SCN-OCG-15 (−) The probe refuses a Copilot CLI 2 by name
- **GIVEN** a `copilot-cli` profile and a `copilot --version` that prints `GitHub Copilot CLI 2.0.0.`
- **WHEN** the probe ladder runs
- **THEN** the `binary` step fails with `copilot 2.0.0 is Copilot CLI 2; L4 runs Copilot CLI 1: install copilot 1.0.102
  (in CI l4 doctor --ci --fix installs it; l4 doctor prints the command for this machine); Copilot CLI 2 support comes
  in a later L4 release`, and no `auth`, `quota` or `hello` step runs

#### Scenario: SCN-OCG-16 (−) CI replaces a Copilot CLI 2 and a person's fix leaves it
- **GIVEN** a Linux runner whose `~/.local/bin/copilot` reports `2.0.0`, and a `copilot-cli` profile in a role chain
- **WHEN** `l4 doctor --ci --fix` runs, and on a copy of that machine `l4 doctor --fix` runs
- **THEN** the CI action is `planned` with `found 2.0.0 (Copilot CLI 2), need copilot 1.x (pinned 1.0.102)` and ends
  `applied` with `copilot 1.0.102`
- **AND** the person's action is `manual` with the same reason and the manual command, and the file is unchanged
