## Why

The harness never starts a role on an agent or model it has not checked. Today there is no code that turns a profile
(`codex-sol`, `claude-sonnet`, `judge-sol`, ...) into something that can be probed, run, rate-limited, cooled down and
replaced by the next profile of a role's chain. Every later change depends on this seam: the implementer (change 6)
needs `AgentAdapter.run`, the clarifier (change 7) and verifier (change 8) need `LLMBackend.complete_structured`, and
all roles need the availability ladder and fallback so a job is never burned on a missing binary, an expired login or
an exhausted usage window. The product goal is "easy to use": a runner that has the tools just works, and one that
lacks them is told precisely what is missing (the installer itself is change 12).

## What Changes

- Add `src/l4/agents/`: the ACP-shaped `AgentAdapter` protocol, `RunRequest`/`RunResult`, the adapter registry and the
  `Factory.for_role` selector, plus adapters `claude-code`, `opencode`, `fake` (M1) and `codex`, `kiro-cli`,
  `command`, `acp` (M2). Result status is derived from the event stream and the exit code, never the exit code alone.
- Add `src/l4/llm/`: the `LLMBackend` protocol with `openai-chat` (OpenRouter/OpenAI/Ollama/LiteLLM via `base_url`),
  `anthropic-messages`, `system-one` (Jev hosted, `laya-serve` local) and `fake`; client-side JSON Schema validation,
  served-model mismatch detection, no sampling parameters.
- Add `src/l4/availability/`: probe ladder (`binary`, `auth`, `quota`, `hello`, `mcp`, `custom`), normalised
  `LimitSignal`, the cool-down registry (`$L4_CACHE/availability.json` + ledger events), the probe cache, and the fallback
  selector that emits the exact console lines and the `availability.selected|fallback|cooldown|model_mismatch` events
  of SPEC 8.4.
- Add per-profile concurrency serialisation for subscription logins (`max_concurrency`).
- Register doctor checks LIVE-001 and LIVE-002 through the bootstrap-core doctor framework, and add the `command`/`acp` rows to bootstrap-core's ENV-004 binary table (ENV-004 and ENV-005 themselves are bootstrap-core's; registering them twice would raise `DuplicateCheckError`).
- M1 scope (walking skeleton): `claude-code`, `opencode`, `fake` adapters; `openai-chat` and `fake` backends; `binary`
  and `hello` probes; cool-down registry; fallback chain with the logged lines. Everything else is M2.

## Capabilities

### New Capabilities
- `agent-factory`: adapter and backend interfaces, adapter command/parse specifications, status normalisation,
  profile-to-instance factory, role selection with independence, auth modes and subscription concurrency.
- `availability`: probe ladder, limit-signal normalisation, cool-down registry, probe cache, mid-run fail-fast
  fallback, `waiting_capacity`, required/optional role degradation, selection logging.

### Modified Capabilities

None.

## Impact

- Owned source paths: `src/l4/agents/{base,factory,proc,claude_code,codex,opencode,kiro_cli,command,acp,fake}.py`,
  `src/l4/llm/{base,openai_chat,anthropic,system_one,fake}.py`, `src/l4/availability/{probes,cooldown,fallback}.py`,
  `src/l4/doctor/checks_agents.py` (LIVE-001, LIVE-002).
- Owned tests: `tests/unit/agents/`, `tests/unit/llm/`, `tests/unit/availability/`, `tests/contract/agents/`,
  recorded raw outputs under `tests/fixtures/agents/<tool>/<version>/`.
- Consumes (does not own): `l4.config.schema.Profile` and `availability.*` config (bootstrap-core), the ledger
  `EventSink` (state-vcs-locks), exit code 12 constant (bootstrap-core), recorded outputs from the `spikes` change.
- Consumed by: implementer-tdd-loop (6), clarification-loop (7), verifier (8), simulation-harness (4, fakes).
