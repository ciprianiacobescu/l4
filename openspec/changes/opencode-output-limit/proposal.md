## Why

Judges that run through the opencode adapters end long verdicts with the finish reason `length`, so plan reviews and
verifications of large subjects fail. L4-VER-071 already cuts a step-9 prompt's criteria in halves when a reply stops
at its output limit, but a readiness review, a delegate answer or an implementer step is not cut, and a reply that a
reasoning model fills with its thinking is not helped by fewer criteria. L4 sets nothing about the output limit:
`OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` appears nowhere in `src/`, and no rendered configuration carries a
`limit.output` for a built-in provider.

What the two CLIs ask for, read in their binaries [V src]:

- **OpenCode 1** (L4 pins 1.18.34; read in the 1.18.33 binary): `maxOutputTokens(model, Z) = Math.min(model.limit.output,
  Z) || Z`, where `Z` is `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` and 32000 when the variable is unset. The request asks
  for the smaller of the model's known output limit and `Z`, and for exactly `Z` when the model's limit is unknown (0).
  The variable is a ceiling, not a setter: it cannot lift a request above a limit OpenCode knows. The same value sets the
  auto-compaction threshold: `context - maxOutputTokens` for a model without a catalog `limit.input`, `input -
  min(20000, maxOutputTokens)` for a model with one.
- **OpenCode 2** (`@opencode/cli` 2.2.6): there is no such variable. The primary request's `maxTokens` is
  `cV(limit, inputTokens)`: `Math.min(limit.output > 0 ? limit.output : 32000, 256000)`, then lowered to fit the
  context (never below 1024). The way to raise it is the model's `limit.output` in the native configuration,
  `providers.<provider>.models.<model>.limit.output` (all three `limit` fields are optional), which the loader merges
  over the catalog's model: `limit = {...catalog.limit, ...config.limit}`.

So a v1 request stops at 32000 output tokens unless the variable is set, and a v2 request stops at 32000 when the
catalog does not know the model's output limit. A custom provider's `options.provider.models.<model>.output` (v1 only)
is honoured only below 32000 today: above it, the request still asks for 32000.

A provider refuses a request whose maximum output is above the model's real maximum (HTTP 400), and OpenRouter
reserves credits for the maximum: a low-credit key answered a request for 32000 with 402, `You requested up to 32000
tokens, but can only afford 7377` [V, `tests/fixtures/recorded/opencode/1.18.33/error-openrouter-credits-max-tokens.jsonl`].
So a large value for every model is wrong when the model's limit is not known.

## What Changes

- An opencode profile can declare its model's output limit: `options.max_output_tokens`, a whole number from 1024 to
  256000, checked at load like the other opencode options. With `options.provider` it may not exceed the model entry's
  `output`; with `context_window` it must be below it.
- OpenCode 1: the run (every mode) and the hello export `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=<n>`.
- OpenCode 2: the run, the hello and `auth list` render `providers.<provider>.models.<model>.limit.output = <n>` in
  `OPENCODE_CONFIG_CONTENT`, after `agents`, and nothing else in that block.
- Without the key nothing changes: no variable, no `providers` block, byte-identical configurations.
- A run that stops with `length` on an opencode profile gets a hint in its detail that names the key (with its value
  when set); a run or hello that fails with status 400 on a profile with the key says the key may be above the model's
  maximum.
- `l4 doctor` PRV-001 notes a v1 custom-provider profile in a role chain whose model entry's `output` is above 32000
  and that has no key (the request asks for 32000).
- Docs: runbook 7.4 and a new 10.10, skill `references/adopt.md` 4h, the reference configuration, CHANGELOG.

## Capabilities

### New Capabilities

- `opencode-output-limit`: L4-FAC-023 (the key, its checks, OpenCode 1's variable, the hello, the hints, the doctor
  note) and L4-OCV-020 (OpenCode 2's `limit.output` in the native configuration).

### Modified Capabilities

- L4-OCV-005 (the native configuration may hold the `providers` block of L4-OCV-020), L4-VER-071 (the remedy names the
  key), the opencode rows of the §8.3 adapter table and the §3.2 reference configuration.

## Impact

- `src/l4/config/schema.py` (`OpencodeOptions.max_output_tokens`, `opencode_option_problems`, `Profile`),
  `src/l4/agents/opencode.py` (`output_limit_env`, the run, the hello, the hints), `src/l4/agents/opencode_v2.py`
  (`config_content_v2`, the run, the hello), `src/l4/doctor/checks_provision.py` (`_provider_notes`).
- `docs/SPEC.md` (L4-FAC-023, L4-OCV-020, SCN-FAC-52..58, SCN-OCV-49..52, amendments, change-table row 131),
  `docs/runbook.md`, `plugins/l4/skills/l4/references/adopt.md`, `CHANGELOG.md`.
- One new optional configuration key; no new event, no new doctor check id, no new environment variable outside the
  opencode v1 child environment.
