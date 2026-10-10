## Purpose

Defines the adapter and LLM-backend interfaces, the exact command line and result parsing of each v1 adapter, status
normalisation, role selection with independence, and credential and concurrency handling for subscription logins.

## ADDED Requirements

### Requirement: L4-FAC-001 (part a) Adapter protocol
Every agent adapter SHALL implement the ACP-shaped `AgentAdapter` protocol (`name`, `capabilities()`, `probe()`, `run()`) so native-CLI and ACP transports are interchangeable; the registry MUST map each of `claude-code`, `codex`, `opencode`, `kiro-cli`, `command`, `acp`, `fake` to one class and reject any other adapter name.

#### Scenario: SCN-FAC-N10 (−) unknown adapter name is rejected
- **GIVEN** a profile with `adapter: gemini` (not a v1 adapter)
- **WHEN** the factory builds the profile
- **THEN** it raises a configuration error naming the profile and the seven valid adapter names, and no process is started.

#### Scenario: SCN-FAC-N11 (+) every registered adapter satisfies the protocol
- **GIVEN** the adapter registry
- **WHEN** a conformance test instantiates each registered adapter with a minimal profile
- **THEN** each exposes `name`, `capabilities()` returning `AgentCaps`, `probe()` and `run()` with the SPEC 8.1 signatures.

### Requirement: L4-FAC-001 (part b) Result schema delivery
Adapters SHALL deliver the result schema natively where the CLI supports it (Claude `--json-schema`, Codex `--output-schema`) and through the `$L4_RESULT_PATH` prompt contract otherwise (OpenCode, Kiro CLI, `command`, `acp`); every result MUST be validated client-side regardless of mode.

#### Scenario: SCN-FAC-03 (+) Native schema where available, prompt contract elsewhere
- **GIVEN** the implementer result schema
- **WHEN** commands are built
- **THEN** Claude gets `--json-schema`, Codex gets `--output-schema`, OpenCode and Kiro get the `$L4_RESULT_PATH` contract in the prompt; all results are validated client-side.

#### Scenario: SCN-FAC-N25 (−) Native-schema output that violates the schema is rejected
- **GIVEN** a Claude run in native `--json-schema` mode whose `structured_output` lacks a required property
- **WHEN** the adapter result is validated client-side
- **THEN** `structured` is `None`, the failure reason is `schema_invalid`, and the caller is offered the single repair path.

### Requirement: L4-FAC-001 (part c) Claude Code adapter
The `claude-code` adapter SHALL run `claude -p --output-format stream-json --verbose --model M --max-turns N --max-budget-usd B --session-id UUID --permission-mode dontAsk --allowedTools ... --strict-mcp-config --mcp-config F [--json-schema S]` with the prompt on stdin, add `--bare` only for `auth: api_key`, set `CLAUDE_CODE_MAX_RETRIES=1`, and MUST NOT pass `CLAUDE_CODE_RETRY_WATCHDOG`.

#### Scenario: SCN-FAC-N12 (+) api_key profile builds a bare command
- **GIVEN** a `claude-code` profile with `auth: api_key` and a result schema
- **WHEN** the command is built
- **THEN** it contains `--bare`, `--json-schema`, `--permission-mode dontAsk`, `--strict-mcp-config` and `--session-id <uuid>`, the prompt is passed on stdin, and the child env holds `ANTHROPIC_API_KEY` but no forge token.

#### Scenario: SCN-FAC-N13 (−) retry watchdog is never inherited
- **GIVEN** the runner environment sets `CLAUDE_CODE_RETRY_WATCHDOG=1`
- **WHEN** the adapter builds the child environment
- **THEN** the variable is absent and `CLAUDE_CODE_MAX_RETRIES` is `1`.

### Requirement: L4-FAC-001 (part d) OpenCode adapter
The `opencode` adapter SHALL run `opencode run --pure --format json -m provider/model [--agent A]` with permissions injected through `OPENCODE_PERMISSION` and MCP through `OPENCODE_CONFIG_CONTENT`, derive the final text from `text` parts and cost from `step_finish.cost`, and MUST enforce a wall-clock timeout and a stall watchdog because a rate-limited run emits no events while it retries.

#### Scenario: SCN-FAC-N14 (+) opencode command and environment
- **GIVEN** an `opencode` profile with model `openrouter/anthropic/claude-sonnet-5.5`
- **WHEN** the command is built
- **THEN** argv starts `opencode run --pure --format json -m openrouter/anthropic/claude-sonnet-5.5`, no `--auto` or `--yolo` flag is present, `OPENCODE_PERMISSION` holds the policy JSON, and `OPENROUTER_API_KEY` is the only credential variable passed.

#### Scenario: SCN-FAC-N15 (−) silent run is aborted by the stall watchdog
- **GIVEN** an OpenCode process that emits no event for longer than `stall_timeout_s`
- **WHEN** the adapter runs it
- **THEN** the process group is killed, `RunResult.status` is `timeout`, and the adapter returns without waiting for the hung retry.

### Requirement: L4-FAC-001 (part e) Codex adapter
The `codex` adapter SHALL run `codex exec --json -m M -s workspace-write --ignore-user-config [--output-schema S] -o OUT -` with the prompt on stdin, resume with `codex exec resume <id>` configured through `-c`, read the session from `thread.started.thread_id`, and MUST NOT emit the removed `--full-auto` flag.

#### Scenario: SCN-FAC-N16 (−) removed flag is never emitted
- **GIVEN** a `codex` profile with default options
- **WHEN** fresh and resume commands are built
- **THEN** neither contains `--full-auto`, the resume command contains no `-s`, and the sandbox is set with `-c sandbox_mode="workspace-write"`.

### Requirement: L4-FAC-001 (part f) Kiro CLI adapter
The `kiro-cli` adapter SHALL run `kiro-cli chat --no-interactive --trust-tools=<allow-list> [--agent A] [--model M] --output-format stream-json --require-mcp-startup "<prompt>"`, use the prompt contract for results, and map exit code 3 to an error with reason `mcp_startup`.

#### Scenario: SCN-FAC-N17 (−) MCP startup failure is reported as such
- **GIVEN** a Kiro run that exits with code 3
- **WHEN** the adapter normalises it
- **THEN** `RunResult.status` is `error` with reason `mcp_startup` and the profile is not cooled down.

### Requirement: L4-FAC-001 (part g) Command, ACP and fake adapters
The `command` adapter SHALL expand a user argv template with `{prompt_file}`, `{result_path}`, `{model}`, `{session_id}`; the `acp` adapter (experimental) SHALL drive `initialize`, `session/new`, `session/set_config_option` and `session/prompt` and answer permission requests from one policy; the `fake` adapter SHALL replay a scripted outcome list.

#### Scenario: SCN-FAC-N18 (−) unknown placeholder in a command template
- **GIVEN** a `command` profile whose argv contains `{prompt}` (not a supported placeholder)
- **WHEN** the factory builds the profile
- **THEN** it fails with a configuration error listing the four supported placeholders.

#### Scenario: SCN-FAC-N19 (+) fake adapter replays its script
- **GIVEN** a `fake` adapter scripted with `[rate_limited, ok]`
- **WHEN** it runs twice
- **THEN** the first `RunResult.status` is `rate_limited` with its `LimitSignal` and the second is `ok`, each with a raw events file.

### Requirement: L4-FAC-002 Status from events and exit code
`RunResult.status` SHALL be derived from the event stream and the exit code together, never from the exit code alone: an exit code of 0 MUST NOT yield `ok` when the events show a permission rejection, a max-turns stop or a null result.

#### Scenario: SCN-FAC-02 (−) Exit code 0 is not success when events say otherwise
- **GIVEN** an OpenCode run stopped by a permission rejection that exits 0, and a Claude run hitting max-turns with `result: null`
- **WHEN** normalised
- **THEN** statuses are `permission_blocked` and `max_turns` respectively, never `ok`.

### Requirement: L4-FAC-003 (part a) LLM backend protocol
LLM backends SHALL implement `complete_structured(system, messages, json_schema, effort, max_tokens, timeout_s) -> StructuredResult` with status `ok | refusal | truncated | schema_invalid | error`; `openai-chat` MUST switch provider by `base_url` and always send `provider.require_parameters: true` to OpenRouter, and `anthropic-messages` MUST use native structured output, not the OpenAI-compatible endpoint.

#### Scenario: SCN-FAC-N20 (+) OpenRouter request carries require_parameters
- **GIVEN** an `openai-chat` profile with `base_url: https://openrouter.ai/api/v1`
- **WHEN** a structured completion is requested
- **THEN** the request body has `response_format.type == "json_schema"` and `provider.require_parameters == true`, and the `Authorization` header uses the value of the profile's `api_key_env` variable.

#### Scenario: SCN-FAC-N26 (−) Anthropic backend never uses the OpenAI-compatible endpoint
- **GIVEN** an `anthropic-messages` profile
- **WHEN** a structured completion is requested
- **THEN** the request targets the native Messages endpoint, never a `/chat/completions` URL, and the body carries no `response_format` field.

### Requirement: L4-FAC-003 (part b) Client-side validation fails closed
Backends MUST validate every parsed reply against the requested JSON Schema on the client; a refusal, a truncated reply or a schema-invalid reply SHALL be returned with its own non-`ok` status and MUST be treated by callers as inconclusive, never as a pass.

#### Scenario: SCN-FAC-N21 (−) schema-invalid reply is not ok
- **GIVEN** a backend reply whose JSON lacks a required property
- **WHEN** it is validated
- **THEN** `StructuredResult.status` is `schema_invalid`, `parsed` is `None`, and the raw text is kept for the repair prompt.

### Requirement: L4-FAC-003 (part c) Served-model mismatch
When a response reports a served model different from the requested one, the harness MUST log `availability.model_mismatch`; a judge verdict from the mismatched model SHALL be discarded and the next judge tried, and for implementers the served model's vendor MUST be the one recorded for independence.

#### Scenario: SCN-AVL-15 (−) Served model differs from the requested one
- **GIVEN** a judge request for `openai/gpt-6.1-sol` whose response reports `model: openai/gpt-6.1-mini`
- **WHEN** the verdict is received
- **THEN** `availability.model_mismatch` is logged and that judge's verdict is discarded (fail closed); the next judge is tried; for implementers the mismatch is logged and the vendor of the *served* model counts for independence.

### Requirement: L4-FAC-004 System-One backend
The `system-one` backend MUST speak `POST /v1/systemone` with body `{state, model, questions: {<id>: {type, instructions, criteria?}}}`; with `engine: laya-local` it SHALL start `laya-serve` on a free localhost port for the verify step only and stop it afterwards, and it MUST log each request/response pair for calibration.

#### Scenario: SCN-FAC-04 (+) Laya served locally for the verify step only
- **GIVEN** `s1_judge: [laya]` with `engine: laya-local`
- **WHEN** a verify step runs
- **THEN** `laya-serve` starts on a free localhost port, receives `POST /v1/systemone` requests in the TypeSafe wire format, and is stopped when the step ends (no process left behind).

#### Scenario: SCN-FAC-N22 (−) laya-serve that never becomes ready
- **GIVEN** `laya-serve` does not accept connections within the start timeout
- **WHEN** the backend is entered
- **THEN** the child process is killed, the result status is `error`, and no process is left behind.

### Requirement: L4-FAC-005 No sampling parameters
No backend or adapter SHALL send or rely on `temperature`, `top_p`, `top_k` or forced `tool_choice` for determinism, because Claude Opus 5.5, Sonnet 5.5 and Fable 5.1 reject them.

#### Scenario: SCN-FAC-05 (−) No sampling parameters sent to models that reject them
- **GIVEN** judge requests to `claude-opus-5-5`
- **WHEN** request bodies are recorded
- **THEN** they contain no `temperature`, `top_p`, `top_k` or forced `tool_choice`.

### Requirement: L4-FAC-006 (part a) Role selection and explanation
`Factory.for_role(role, unit)` MUST walk the role's chain in order, apply availability, and return the first usable profile together with the skipped profiles and their reasons, and MUST log exactly one `availability.selected` event per selection.

#### Scenario: SCN-FAC-06 (+) Selection is explained
- **GIVEN** any role selection
- **WHEN** it completes
- **THEN** exactly one `availability.selected` event lists the selected profile, its index and every skipped profile with its reason.

#### Scenario: SCN-FAC-N27 (−) Unknown role is a configuration error
- **GIVEN** `Factory.for_role("reviewer", unit)` for a role with no chain in `roles`
- **WHEN** it is called
- **THEN** it raises a configuration error naming the role and the known roles, emits no `availability.selected`, and starts no process.

### Requirement: L4-FAC-006 (part b) Independence constraint in selection
`Factory.for_role` SHALL accept an independence constraint and skip every profile whose vendor was used by the implementer when `verifier.independence` is `different_vendor`, recording the reason `independence: vendor used by implementer`; independence MUST NOT be relaxed at run time.

#### Scenario: SCN-AVL-13 (+) Two-vendor implementation still gets an independent verifier
- **GIVEN** the implementer used `codex-sol` (openai) for tasks 1–2 and `claude-sonnet` (anthropic) for 3–4, and the reference configuration's chains
- **WHEN** the verifier agent and the judges are selected with `independence: different_vendor`
- **THEN** `claude-opus`, `codex-sol`, `judge-opus` and `judge-sol` are skipped (`independence: vendor used by implementer`); `opencode-gemini` and `judge-gemini` are selected.

#### Scenario: SCN-FAC-N23 (−) independence is not relaxed when nothing qualifies
- **GIVEN** every profile of the verifier chain shares a vendor with the implementer
- **WHEN** the verifier agent is selected
- **THEN** no profile is returned, every profile is listed as skipped with the independence reason, and the caller receives a waiting-capacity result instead of a relaxed choice.

### Requirement: L4-FAC-007 Contract tests pin adapter facts
Adapter facts marked [U] in SPEC 8.3 MUST be pinned by contract tests that replay recorded raw outputs of the named CLI version, and re-checked by `doctor --live` (`LIVE-*`); a profile whose live output is unrecognised MUST be skipped by selection until fixed.

#### Scenario: SCN-FAC-01 (+) RunResult normalised from events for every v1 adapter
- **GIVEN** recorded raw outputs (success, schema output, max-turns, usage limit, 429, auth failure) for Claude Code 2.1.288, Codex 0.160.0, OpenCode 1.18.x and Kiro CLI (pinned versions)
- **WHEN** each adapter parses them
- **THEN** `RunResult.status`, `final_text`, `structured`, `session_id`, `usage` and `limit` match the expected values for every recording.

#### Scenario: SCN-FAC-07 (−) CLI version drift is detected
- **GIVEN** a runner with a newer CLI version whose output format changed
- **WHEN** `l4 doctor --live` runs
- **THEN** LIVE-001/002 fail for that profile with "unrecognised output", and the profile is skipped by selection until fixed.

### Requirement: L4-FAC-008 (part a) Authentication modes
Profiles SHALL declare `auth: api_key | subscription`; `claude-code` with `subscription` MUST run without `--bare` and with `--strict-mcp-config`, authenticated by `CLAUDE_CODE_OAUTH_TOKEN` or the runner's stored login, and the token MUST be available to that profile only.

#### Scenario: SCN-FAC-08 (+) Claude subscription mode works without `--bare`
- **GIVEN** `claude-sonnet` with `auth: subscription` and `CLAUDE_CODE_OAUTH_TOKEN` available to that profile only
- **WHEN** the hello probe and a task step run
- **THEN** the command line has no `--bare`, has `--strict-mcp-config`; authentication succeeds; a `.claude/settings.json` hook added by an earlier agent step was already reverted by the guard, so no repo hook runs.

#### Scenario: SCN-FAC-N28 (−) Subscription profile cannot force --bare
- **GIVEN** a `claude-code` profile with `auth: subscription` and `options.bare: true`
- **WHEN** the factory builds the profile
- **THEN** it fails with a configuration error explaining that `--bare` authenticates only with an API key, and no process is started.

### Requirement: L4-FAC-008 (part b) Serialised subscription runs
The harness SHALL serialise concurrent runs of the same `(tool, auth identity)` on a runner up to `profile.max_concurrency` (default 1 for subscription, unlimited for api_key) so subscription OAuth refresh tokens do not race; the second run MUST wait within the soft deadline or fall back to the next profile.

#### Scenario: SCN-FAC-09 (−) Concurrent jobs do not race on one subscription login
- **GIVEN** two units on the same runner both selecting `codex-sol` (`max_concurrency: 1`)
- **WHEN** both reach an implementer step
- **THEN** the second waits for the first (bounded by the soft deadline) or falls back to the next profile; the two Codex processes never run at the same time.

### Requirement: L4-FAC-008 (part c) Quota step is subscription-only
The `quota` probe step SHALL apply to subscription auth only; API-key profiles MUST skip it and rely on HTTP 429 signals and cost budgets.

#### Scenario: SCN-FAC-N24 (−) api_key profile skips the quota step
- **GIVEN** a `claude-code` profile with `auth: api_key` and ladder `[binary, auth, quota, hello]`
- **WHEN** the ladder runs
- **THEN** the `quota` step is reported `skipped` (not failed), and `hello` still runs.
