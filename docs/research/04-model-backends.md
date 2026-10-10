# 04 — Model backends for the Verifier and Clarifier (research as of 2026-10-03)

Labels: **[V]** verified from a primary source (URL cited), **[D]** secondary source (URL cited), **[I]** my inference, **[U]** unverified.

Primary data snapshots I pulled (raw files in this folder):
- `or_models.json`: the live `GET https://openrouter.ai/api/v1/models` catalog (466 models), fetched 2026-10-03.
- `anth_models.md`: https://platform.claude.com/docs/en/about-claude/models/overview.md
- `or/*.md`: OpenRouter docs pages (structured outputs, provider routing, reasoning, limits, API overview, Responses API, latest-resolution, Ori harness, and others)
- `ollama/*.md`: Ollama docs pages (OpenAI compatibility, structured outputs, context length, GPU, cloud)

---

## 0. Verdict (read this first)

1. **"Astra" is OpenAI's GPT-6 Astra, not Google.** OpenAI's GPT-6 family has three tiers: **Astra** (flagship, `gpt-6-astra`), **Sol** (mid tier), and **Luna** (cheap tier). Google's "Project Astra" is a DeepMind research prototype for an assistant. It is not an API model. [V] https://developers.openai.com/api/docs/models ; [D] https://codersera.com/blog/gpt-astra-vs-google-project-astra-2026/
2. **"GPT 6.1" is GPT-6.1 Sol (`gpt-6.1-sol`),** released 2026-09-29 at DevDay. No `gpt-6.1-astra` or `gpt-6.1-luna` exists yet. OpenAI describes 6.1 Sol as "near-Astra performance at a lower cost" ($2/$10 vs Astra's $10/$50 per MTok). [V] https://developers.openai.com/api/docs/models/gpt-6.1-sol ; OpenRouter catalog.
3. **"Opus 5.5" is real** (`claude-opus-5-5`, released 2026-09-22, $4/$20). Anthropic recommends it as the default. **Claude Fable 5.1** (`claude-fable-5-1`, $10/$50) is Anthropic's top tier. [V] https://platform.claude.com/docs/en/about-claude/models/overview.md
4. **Google's current Pro model is still `gemini-3.1-pro-preview`, which is in preview.** The newest stable flagship is `gemini-3.8-flash`. Gemini 3.5 Pro was announced in May 2026 but has not shipped. [V] https://ai.google.dev/gemini-api/docs/models ; [D] https://evolink.ai/blog/gemini-3-5-pro-api-release-watch
5. **Recommended abstraction:** two wire adapters plus one subprocess adapter. Do not depend on LiteLLM. Details are in §8.
   - `openai_chat`: base_url switching. It covers OpenRouter, OpenAI, Ollama, Gemini's OpenAI-compatible endpoint, vLLM, and a LiteLLM proxy if you run one.
   - `anthropic_messages`: the native Messages API.
   - `agent_cli`: runs `codex exec`, `claude -p`, or `opencode run` as a subprocess.

   The load-bearing reason Anthropic needs its own adapter: **Anthropic's OpenAI-compatible endpoint silently ignores `response_format` and `strict`**, so plain base_url switching cannot get a strict JSON verdict from Claude directly. Routing Claude through OpenRouter does work. [V] https://platform.claude.com/docs/en/api/openai-sdk.md
6. **Biggest risks for a verifier that must fail closed:**
   - OpenRouter endpoints differ in whether they support structured output. For example, the Amazon Bedrock endpoint for Opus 5.5 does not. Mitigation: always set `provider.require_parameters: true` and validate the JSON on the client side.
   - Anthropic's 5.5 and 5.1 models reject forced `tool_choice` with a 400, so the "force a tool call to get JSON" trick is dead.
   - The `~…-latest` aliases make CI non-reproducible.
   - Haiku 4.5 may be retired as early as 2026-10-15. [V] (sources in §1, §2)

---

## 1. Frontier models that exist as of 2026-10-03

All OpenRouter slugs below appear in the live `/api/v1/models` catalog **[V]** (`or_models.json`). Prices are USD per million tokens: input / output / cached-input read. "SO" means OpenRouter lists `structured_outputs` in the model's `supported_parameters`.

### 1.1 Candidate verifier/clarifier models (top tier)

| Vendor | Model | Direct API ID | OpenRouter slug | $ in / out / cache-read | Context / max out | SO | Label |
|---|---|---|---|---|---|---|---|
| Anthropic | Claude Opus 5.5 (released 2026-09-22) | `claude-opus-5-5` | `anthropic/claude-opus-5.5` | 4 / 20 / 0.20 | 1M / 128K | yes | [V] Anthropic overview + OR |
| Anthropic | Claude Fable 5.1 (released 2026-09-01) | `claude-fable-5-1` | `anthropic/claude-fable-5.1` | 10 / 50 / 0.25 | 1M / 128K | yes | [V] |
| Anthropic | Claude Sonnet 5.5 (released 2026-09-28) | `claude-sonnet-5-5` | `anthropic/claude-sonnet-5.5` | 2 / 10 / 0.20 | 1M / 128K | yes | [V] |
| Anthropic | Claude Haiku 4.5 | `claude-haiku-4-5` (alias of `claude-haiku-4-5-20251001`) | `anthropic/claude-haiku-4.5` | 1 / 5 / 0.10 | 200K / 64K | yes | [V]; **retirement "not sooner than Oct 15, 2026"**, so avoid in new configs |
| OpenAI | GPT-6 Astra (flagship, 2026-09-04) | `gpt-6-astra` | `openai/gpt-6-astra` (pro mode: `openai/gpt-6-astra-pro`) | 10 / 50 / 1.00 | 1.05M / 128K | yes | [V] OpenAI model page + OR |
| OpenAI | GPT-6.1 Sol (2026-09-29) | `gpt-6.1-sol` | `openai/gpt-6.1-sol` (pro: `openai/gpt-6.1-sol-pro`) | 2 / 10 / 0.10 | 1.05M / 128K | yes | [V] |
| OpenAI | GPT-6 Luna (2026-09-22) | `gpt-6-luna` | `openai/gpt-6-luna` | 0.10 / 0.50 / 0.01 | 1.05M / 128K | yes | [V] |
| Google | Gemini 3.1 Pro (Preview) | `gemini-3.1-pro-preview` | `google/gemini-3.1-pro-preview` | 2 / 12 / 0.20 (≤200K prompt) | 1M / 65K | yes | [V] Google models page (status: preview) + OR |
| Google | Gemini 3.8 Flash (2026-09-02; Google's "most intelligent Flash") | `gemini-3.8-flash` | `google/gemini-3.8-flash` | 0.75 / 3.75 | 1M / — | yes | [V] |
| xAI ("SpaceXAI" in OR naming) | Grok 4.7 (2026-09-21) | — | `x-ai/grok-4.7` | 2 / 6 / 0.50 | 500K / 450K | yes | [V] OR |
| Z.ai | GLM-5.3 (open weights) | — | `z-ai/glm-5.3` | 1.4 / 4.4 / 0.14 | 1M / 131K | yes (varies by provider) | [V] OR |
| Moonshot | Kimi K3 (open weights, 2.8T) | — | `moonshotai/kimi-k3` | 2.7 / 13.5 / 0.27 | 1M | yes | [V] OR |
| DeepSeek | DeepSeek V4 Pro 0813 (GA) | — | `deepseek/deepseek-v4-pro-0813` | 0.66 / 1.98 off-peak (2x during some UTC weekday windows) | 1M / 393K | yes | [V] OR |
| DeepSeek | DeepSeek V4.1 Flash | — | `deepseek/deepseek-v4.1-flash` | 0.30 / 1.20 | 1M | yes | [V] OR |
| Alibaba | Qwen3.8 Max | — | `qwen/qwen3.8-max-0902` (higher-throughput SKU: `qwen/qwen3.8-max-prime`) | 2 / 6 | 1M | yes | [V] OR |

Notes:
- OpenAI long-context surcharge: prompts over 272K input tokens cost 2x input/cache and 1.5x output on GPT-6 Astra and 6.1 Sol. [V] https://developers.openai.com/api/docs/models/gpt-6-astra , …/gpt-6.1-sol
- OpenAI reasoning effort levels on Astra and 6.1 Sol are `low`, `medium` (default on 6.1 Sol), `high`, `xhigh`, `max`. Both serve Chat Completions, Responses, and Batch. Tier-1 rate limits are 500 RPM and 500K TPM. [V] same pages
- OpenAI "pro" variants (`*-pro`) are the same model with `reasoning.mode: "pro"`. They bill the same per-token rate but use far more tokens. On OpenRouter they are available only via OpenAI and Azure endpoints. [V] `or/guides_best-practices_reasoning-tokens.md`
- Anthropic Opus 5.5: thinking cannot be disabled, and the default effort is `medium` (set it explicitly). Forced `tool_choice` (`any`/`tool`) returns 400. The same holds for Fable 5.1 and Sonnet 5.5. [V] Anthropic overview (default effort row); [V-skill] bundled Claude API reference, cached 2026-09-25, consistent with OR's `supports_tool_choice: {required:false, function:false}` for these models.
- The Artificial Analysis "coding_index" values that OpenRouter embeds in `/models` are: Fable 5.1 81.6, GPT-6 Astra 76.9, Gemini 3.8 Flash 76.3, Kimi K3 76.2, Qwen3.8 Max 76.2, GLM-5.3 74.8, Gemini 3.1 Pro 68.8, DeepSeek V4 Pro 68.8. Opus 5.5 and 6.1 Sol show null. [V that OR reports these numbers; methodology not checked. Do not treat them as a verifier-quality ranking.]

### 1.2 What the user's words most likely map to

| User said | Real model | Confidence |
|---|---|---|
| "Opus 5.5" | `claude-opus-5-5` / `anthropic/claude-opus-5.5` | [V] exists under this exact name |
| "GPT 6.1" | `gpt-6.1-sol` / `openai/gpt-6.1-sol` (the only GPT-6.1 model) | [V] exists; [I] the user meant this one |
| "Astra model" | `gpt-6-astra` / `openai/gpt-6-astra` (OpenAI's flagship) | [V] exists; [I] the user meant OpenAI's Astra. It is not Google's: Project Astra has no API model ID, and Google's models are all branded "Gemini". [D] codersera |
| (if they did mean Google) | `gemini-3.1-pro-preview` (Pro tier, preview) or `gemini-3.8-flash` (stable) | [V] |

### 1.3 OpenRouter "latest" aliases (convenient, but not for CI)

Aliases that exist [V]: `~anthropic/claude-opus-latest`, `~anthropic/claude-sonnet-latest`, `~anthropic/claude-fable-latest`, `~anthropic/claude-haiku-latest`, `~openai/gpt-astra-latest`, `~openai/gpt-sol-latest`, `~openai/gpt-luna-latest`, `~openai/gpt-terra-latest`, `~openai/gpt-mini-latest`, `~google/gemini-pro-latest`, `~google/gemini-flash-latest`, `~x-ai/grok-latest`, `~moonshotai/kimi-latest`, `~z-ai/glm-latest`, `~z-ai/glm-flash-latest`, `~deepseek/deepseek-pro-latest`, `~deepseek/deepseek-flash-latest`.

The response's `model` field reports the concrete model that served the request. [V] `or/guides_routing_routers_latest-resolution.md`

[I] The verifier should **pin concrete slugs** in committed config so that verdicts are reproducible and auditable. Allow `~latest` only in an explicit "track latest" profile, and always log `response.model`.

---

## 2. OpenRouter API for this use case

- **Endpoint and compatibility.** The main endpoint is `POST https://openrouter.ai/api/v1/chat/completions`, which follows the OpenAI Chat schema; OpenRouter says it "normalizes the schema across models and providers". [V] `or/api_reference_overview.md` Other endpoints:
  - `POST /api/v1/responses`: OpenAI Responses-compatible. **Stateless only**: `store:true` and `previous_response_id` are rejected with 400. [V] `or/api_reference_responses_overview.md`
  - `POST /api/v1/messages`: Anthropic Messages-compatible. [V] `or/api_api-reference_anthropic-messages_create-a-message.md` Claude Code and the Claude Agent SDK can be pointed at it with `ANTHROPIC_BASE_URL=https://openrouter.ai/api`, `ANTHROPIC_AUTH_TOKEN=$OPENROUTER_API_KEY`, and `ANTHROPIC_API_KEY=""`. [V] `or/guides_community_anthropic-agent-sdk.md`
  - A Batch API that accepts chat, responses, messages, and embeddings requests. [V] llms.txt index.
- **Structured outputs.**
  - Request shape: `response_format: {type:"json_schema", json_schema:{name, strict:true, schema}}`. `{type:"json_object"}` is also accepted. [V] `or/guides_features_structured-outputs.md`
  - Support is **per endpoint (provider), not per model**. Use `provider.require_parameters: true` to route only to endpoints that support it. With `strict:true`, "some guarantee schema-conforming output, while others … treat it as a strong hint, so exact compliance is not guaranteed on every endpoint." [V] same page
  - Without `require_parameters`, `response_format` and `tools` still act as a *soft* preference, but they never remove a model from your fallback list. [V] `or/guides_routing_provider-selection.md`
  - Concrete example: the **Amazon Bedrock endpoints for `anthropic/claude-opus-5.5` report no `structured_outputs`**, while the Anthropic, Vertex, and Azure endpoints do. [V] `GET /api/v1/models/anthropic/claude-opus-5.5/endpoints`, fetched 2026-10-03.
  - For Anthropic models, OpenRouter maps `response_format: json_schema` onto Anthropic structured outputs automatically. Strict tool use requires the `x-anthropic-beta: structured-outputs-2025-11-13` header; without it, OpenRouter strips `strict`. [V] provider-selection doc, "Provider-Specific Headers".
  - The optional `plugins:[{id:"response-healing"}]` repairs malformed JSON, for non-streaming requests only. [V] `or/guides_features_plugins_response-healing.md` [I] For a verifier, prefer failing closed plus your own retry over silent healing.
- **Tool calling.** Uses the OpenAI `tools` / `tool_choice` shape. OpenRouter passes it through or transforms it per provider. [V] API overview. The endpoints API exposes `supports_tool_choice` per endpoint; Anthropic 5.x endpoints show `required:false, function:false`. [V]
- **Server tools (beta)**, which are OpenRouter's "agentic" features: `openrouter:web_search`, `web_fetch`, `shell` (sandbox; Responses and Messages APIs), `bash`, `apply_patch`, `fusion` (multi-model panel), `advisor` (consult a stronger model mid-generation), `subagent`, `tool_search`, `files`. [V] `or/server-tools.md`, `or/guides_features_server-tools_advisor.md`
  - [I] `openrouter:advisor` fits the Clarifier naturally: an implementer on a cheap model can consult `anthropic/claude-opus-5.5` or `openai/gpt-6-astra` before escalating to a human. It is beta, so keep it optional.
- **Provider routing** (`provider` object). [V] provider-selection doc. Fields: `order`, `allow_fallbacks` (default true), `require_parameters` (default false), `data_collection` (`allow`/`deny`), `zdr`, `only`, `ignore`, `quantizations`, `sort` (`price`/`throughput`/`latency`), `preferred_min_throughput`, `preferred_max_latency`, `max_price`, `enforce_distillable_text`. Model-level fallback is `models: [..]`, tried in order on error, rate limit, or moderation refusal. [V] `or/guides_routing_model-fallbacks.md`
  - [I] For open-weight verifiers (GLM-5.3, Kimi K3), many hosts serve fp4/fp8 quantizations. Pin `quantizations` or use the `:exacto` variant, which prefers providers with stronger tool-calling quality. [V] for `:exacto`, `or/guides_routing_model-variants_exacto.md`
- **Reasoning.** Unified parameter `reasoning: {effort: max|xhigh|high|medium|low|minimal|none, max_tokens?, exclude?, enabled?, mode?: "pro"}`. Reasoning tokens are billed as output and **count against `max_tokens`**, so a low `max_tokens` can produce an empty visible answer. `/models` publishes a per-model `reasoning.supported_efforts` and `default_effort`. [V] `or/guides_best-practices_reasoning-tokens.md`
- **Usage and cost accounting.**
  - "Usage data is always returned for non-streaming". When streaming, it arrives once in the final chunk.
  - `usage` includes `prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens` / `cache_write_tokens`, `completion_tokens_details.reasoning_tokens`, `cost` (credits), `is_byok`, and `cost_details.{upstream_inference_cost, …, server_tool_cost}`. [V] API overview.
  - `GET /api/v1/key` returns key credit usage and limits. [V] `or/api_reference_limits.md`
- **Rate limits.** Paid models have no platform-level request cap; limits come from the upstream provider (429 with `metadata.provider_code`). Free `:free` variants are limited to 20 RPM and 50/day, or 1000/day after buying ≥$10 of credits. An in-flight spending budget applies to some low-balance prepaid accounts. Honor `Retry-After`. [V] limits doc.
- **Headers.**
  - `HTTP-Referer` (required for app attribution) and `X-OpenRouter-Title` (`X-Title` still accepted). Optional: `X-OpenRouter-Categories`, and `X-OpenRouter-App-Visibility: hidden` for a private app. [V] `or/app-attribution.md`
  - Anthropic beta pass-through: `x-anthropic-beta`. [V]
- **Fees.** No markup on inference. A 5.5% fee (minimum $0.80) applies to Stripe credit purchases. BYOK has a free allowance, then a 5% fee. [V] `or/faq.md`, `or/byok.md`
- **Agent CLIs on OpenRouter.** "Ori Harness" (`ori claude|codex|opencode|…`) launches existing agent CLIs with OpenRouter credentials. [V] `or/guides_ori_harness.md` [I] This is useful if the `agent_cli` backend should bill through OpenRouter.

---

## 3. Ollama (local backend)

- **OpenAI-compatible endpoints.**
  - `http://localhost:11434/v1/chat/completions`. The API key is required by clients but ignored by the server.
  - `/v1/responses` (stateless only, since v0.13.3), `/v1/models`, `/v1/embeddings`.
  - An Anthropic-compatible API also exists. [V] `ollama/api_openai-compatibility.md`, `ollama/api_anthropic-compatibility.md`
  - Chat Completions support: `response_format` ✓, `tools` ✓, `reasoning_effort` / `reasoning.effort` ✓, `stream_options.include_usage` ✓. **`tool_choice` ✗**, `logprobs` ✗, image URLs ✗ (base64 only). [V]
- **Structured outputs.** Native `/api/chat` takes `format: <JSON schema>` (or `"json"`). They also "work through the OpenAI-compatible API via `response_format`". Ollama's tips: set temperature to 0 and also put the schema in the prompt. **"Ollama's Cloud currently does not support structured outputs."** [V] `ollama/capabilities_structured-outputs.md`
  - [I] Ollama enforces the schema through grammar-constrained decoding. Validate on the client side anyway, because unsupported JSON-Schema keywords may be ignored. [U] I did not verify which keywords are unsupported.
- **The context-length trap.** The default context depends on VRAM: under 24 GiB gives **4k**, 24–48 GiB gives 32k, and 48 GiB or more gives 256k. Ollama recommends at least 64k for coding agents. Set `OLLAMA_CONTEXT_LENGTH=64000` or a Modelfile `PARAMETER num_ctx`; the OpenAI API cannot set context size. [V] `ollama/context-length.md`, OpenAI-compat doc. [I] A verifier on default settings would **silently truncate the diff/spec**. This is a fail-open hazard; the adapter must check `prompt_tokens` against the input length.
- **Capable local models for code review** (from the Ollama library, fetched 2026-10-03). Sizes are the q4 default tag. [V] for existence, size, and context. Quality claims are the vendors' own [D]; the ranking is [I].

  | Tag | Size (q4) | Context | Notes |
  |---|---|---|---|
  | `qwen3.8:27b` | 18 GB | 256K | tools, thinking; newest Qwen dense model |
  | `qwen3.6:27b-coding` | 18 GB | 256K | coding-tuned variant |
  | `qwen3.6:35b` | 23 GB | 256K | MoE (OpenRouter lists `qwen3.6-35b-a3b`) |
  | `laguna-xs-2.1` | 20 GB | 256K | 33B-A3B MoE for agentic coding |
  | `north-mini-code-1.0` | 19 GB | 488K | Cohere, 30B-A3B |
  | `nemotron-3.5-lightning` | 25 GB | 256K | NVIDIA, 30B-A3B |
  | `muse-glimmer:30b` | 18 GB | 128K | Meta, Apache-2.0 |
  | `gemma4:31b` | 19 GB | 128K | |
  | `gpt-oss:20b` | 14 GB | 128K | |
  | `gpt-oss:120b` | 65 GB | 128K | |

  The strongest open models (`glm-5.3`, `kimi-k3`, `deepseek-v4-pro`) are listed as **cloud** tags on Ollama, so they are not practical locally.
- **CI feasibility.**
  - Standard GitHub-hosted `ubuntu-latest` runners have **no GPU**: 4 vCPU / 16 GB RAM for public repos, 2 vCPU / 8 GB for private repos. [V] https://docs.github.com/en/actions/reference/runners/github-hosted-runners
  - The GPU larger runner is a **Tesla T4 with 16 GB VRAM**, 4 vCPU, 28 GB RAM, on a paid org plan. [V] https://docs.github.com/en/actions/reference/runners/larger-runners It costs about $0.052/min on Linux. [D] https://docs.github.com/en/enterprise-cloud@latest/billing/reference/actions-runner-pricing
  - Ollama needs an NVIDIA GPU with compute capability 5.0+ (the T4 is 7.5). [V] `ollama/gpu.md`
  - [I] Under 24 GiB VRAM the context default is 4k, and a 27B q4 model (18 GB) does not fit in 16 GB VRAM, so it would partly offload to CPU and run slowly. Conclusion: **Ollama is a local-dev or self-hosted-GPU-runner backend, not a GitHub-hosted-CI backend**. Its verdict quality is also well below frontier models; position it as a pre-filter or "offline mode", never as the sole gate.

---

## 4. LiteLLM vs plain base_url switching (and SDK notes)

- **LiteLLM** (BerriAI): the latest PyPI release is 1.103.2 (2026-10-01). It requires Python 3.10–3.14. [V] https://pypi.org/pypi/litellm/json
  - Its non-optional dependencies include `openai`, `httpx[http2]`, `tiktoken`, `tokenizers`, `aiohttp`, `pydantic`, `pydantic-settings`, `jinja2`, `jsonschema`, `click`, `importlib-metadata`, `python-dotenv`, `fastuuid`, **and `boto3`**. [V] same
  - It supports `response_format` json_schema across OpenAI, Anthropic, Gemini/Vertex, Bedrock, xAI, Groq, and Ollama, and has an optional client-side `litellm.enable_json_schema_validation=True`. [V] https://docs.litellm.ai/docs/completion/json_mode
  - **Supply-chain incident.** On 2026-03-24, PyPI versions **1.82.7 and 1.82.8** were published by the attacker group TeamPCP after its PyPI token leaked via a compromised Trivy in CI. A malicious `.pth` credential stealer ran on interpreter start, and the bad versions were live for under 5 hours. [D] https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/ , https://pypistats.com/blog/litellm-pypi-supply-chain-compromise-how-a-popular-llm-proxy-became-a-credential-stealing-backdoor-march-24-2026
  - **Recommendation [I]: do not take LiteLLM as a library dependency** in a portable, minimal-dependency harness that handles API keys. If a team already runs a **LiteLLM proxy**, it is just another OpenAI-compatible `base_url`, and the `openai_chat` adapter talks to it with no code dependency.
- **Plain base_url switching works for:**
  - OpenRouter (`https://openrouter.ai/api/v1`)
  - OpenAI (`https://api.openai.com/v1`)
  - Ollama (`http://localhost:11434/v1`)
  - Gemini (`https://generativelanguage.googleapis.com/v1beta/openai/`). Structured outputs work there via `beta.chat.completions.parse`, and `reasoning_effort` maps to `thinking_level`. Google says the compatibility layer is "still in beta". [V] https://ai.google.dev/gemini-api/docs/openai
  - vLLM / LM Studio [I]
- **Plain base_url switching does NOT work for Anthropic direct.** The `https://api.anthropic.com/v1/` OpenAI-compat layer **ignores `response_format`, `strict`, and `reasoning_effort`**, and is "not considered a long-term or production-ready solution". [V] https://platform.claude.com/docs/en/api/openai-sdk.md
- **Current SDK versions** [V] npm/PyPI registries, 2026-10-03:
  - npm: `openai` 7.27.0, `@anthropic-ai/sdk` 0.131.0, `ai` (Vercel AI SDK) 7.0.127, `@ai-sdk/openai-compatible` 3.0.62, `@openrouter/ai-sdk-provider` 3.1.0, `@openrouter/sdk` 1.4.21, `ollama` 0.6.4.
  - PyPI: `openai` 3.24.0, `anthropic` 1.11.0, `ollama` 0.6.3, `openrouter` 1.3.22.
- **Vercel AI SDK** gives a provider-agnostic `generateObject` with zod, and OpenRouter has an official provider (`createOpenRouter`). [V] `or/guides_community_vercel-ai-sdk.md` [I] It is a good choice if the harness is TypeScript-first. It adds a framework dependency, but it is lighter and more auditable than LiteLLM.

---

## 5. Direct Anthropic and OpenAI APIs: a strict JSON verdict

- **Anthropic Messages API** [V] https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md
  - Request: `output_config: {format: {type: "json_schema", schema: {...}}}` on `POST /v1/messages`. The SDK helper `client.messages.parse()` takes Pydantic or `zodOutputFormat()` and returns `parsed_output`.
  - Alternative: strict tool use (`strict: true` on a tool definition).
  - Supported on Fable 5/5.1, Opus 5.5/5/4.8, Sonnet 5.5/5, Haiku 4.5, and others. The old `output_format` parameter is deprecated.
  - Schema limits: `additionalProperties:false` is required; recursive schemas and numeric/string-length constraints are not supported (the Python and TS SDKs strip those and validate client-side).
  - Incompatible with citations and with prefill.
  - A refusal (`stop_reason:"refusal"`) or `max_tokens` stop can yield non-conforming output.
  - On Amazon Bedrock, structured outputs exist only on the legacy integration for older models. [V] doc note
  - [V-skill] Opus 5.5, Fable 5.1, and Sonnet 5.5 have a server-side `fallbacks` option (beta) for safety refusals.
  - [I] The verifier must map `refusal`, `max_tokens`, and schema-invalid results to **INCONCLUSIVE, never PASS**.
- **OpenAI Responses API** [V] https://developers.openai.com/api/docs/guides/structured-outputs
  - Request: `text: {format: {type: "json_schema", name, schema, strict: true}}`. Chat Completions uses `response_format: {type:"json_schema", json_schema:{name, schema, strict:true}}`.
  - Requirements: `additionalProperties:false`, and every field listed in `required`.
  - Refusals come back in a dedicated `refusal` field.
  - Helpers: `responses.parse()` with Pydantic or `zodTextFormat()`.
  - GPT-6 Astra and 6.1 Sol support structured outputs on Chat Completions, Responses, and Batch. [V] model pages
- [I] **Portable schema subset** that works on OpenAI strict, Anthropic, OpenRouter, Gemini, and Ollama:
  - objects with `additionalProperties:false` and every property in `required` (use `null` unions for optional fields)
  - `enum`
  - arrays of objects
  - no `minLength`, `maximum`, recursion, or `oneOf` tricks

  Example verdict shape: `{verdict: "PASS"|"FAIL"|"INCONCLUSIVE", findings: [{severity, file, line|null, claim, evidence}], unverified_claims: [..], confidence: "high"|"medium"|"low"}`.

---

## 6. "Call a tool like OpenCode or Codex": agent CLIs as backends

These run a full agent (repo reading, tests) rather than a single prompt. That fits the adversarial-review spirit, but it costs more, takes longer, and is less deterministic.

| CLI | Non-interactive call | Structured output | Read-only / safety | Model selection | Label |
|---|---|---|---|---|---|
| OpenAI Codex | `codex exec "<prompt>"` (stdin with `-`) | `--output-schema schema.json -o out.json`; `--json` streams JSONL events | `--sandbox read-only` (the default); `--ignore-user-config`, `--ignore-rules` | `-m` [U] (not on the fetched page) | [V] https://learn.chatgpt.com/docs/non-interactive-mode |
| Claude Code | `claude --bare -p "<prompt>"` | `--output-format json --json-schema '<schema>'`; the result is in `.structured_output`, and `total_cost_usd` is included | `--permission-mode dontAsk`, `--allowedTools "Read,Grep,Glob"`, `--permission-prompts none` | `--model`; can run on OpenRouter via `ANTHROPIC_BASE_URL` | [V] https://code.claude.com/docs/en/headless |
| OpenCode | `opencode run "<prompt>"`, or `opencode serve` plus `--attach` | `--format json` (raw JSON events) only. **No schema flag**: validate and re-prompt yourself | permissions are configurable [U] | `-m provider/model` (OpenRouter, Ollama, Anthropic, …) | [V] https://opencode.ai/docs/cli/ |

- Codex auth in CI uses `CODEX_API_KEY`. OpenAI recommends the official `openai/codex-action` for GitHub Actions and says never to put keys in job-level env for untrusted code. [V] Codex page
- Ollama can also launch these agents against local or cloud models: `ollama launch codex|claude|opencode`. [V] `ollama/cloud.md`

---

## 7. Cost and latency guidance per adversarial review

Token profiles are **[I] assumptions**; prices are **[V]** from §1. Costs are USD per review, ignoring cache-write premiums and OpenRouter's credit-purchase fee.

| Model | S: single shot, 15K in / 6K out (incl. reasoning) | M: single shot, 60K in / 15K out | L: agentic, ~10 turns, 400K cumulative in (70% cache hits) / 40K out |
|---|---|---|---|
| claude-opus-5.5 | $0.18 | $0.54 | $1.34 |
| claude-fable-5.1 | $0.45 | $1.35 | $3.27 |
| claude-sonnet-5.5 | $0.09 | $0.27 | $0.70 |
| gpt-6-astra | $0.45 | $1.35 | $3.48 |
| gpt-6.1-sol | $0.09 | $0.27 | $0.67 |
| gemini-3.1-pro-preview | $0.10 | $0.30 | $0.78 |
| grok-4.7 | $0.07 | $0.21 | $0.62 |
| glm-5.3 | $0.05 | $0.15 | $0.38 |
| deepseek-v4-pro-0813 (off-peak) | $0.02 | $0.07 | $0.17 |

- **Top-3 verifier candidates [I]:**
  1. `openai/gpt-6.1-sol` at effort `high`: the best price/quality per OpenAI's own claim of "near-Astra" [D/V-vendor claim]. It is also a different vendor from a Claude implementer, which reduces correlated blind spots [I].
  2. `anthropic/claude-opus-5.5` at effort `high` or `xhigh`: the stronger reviewer when the implementer is not Claude, or as a second opinion.
  3. `openai/gpt-6-astra` or `anthropic/claude-fable-5.1`: a "hard-case escalation" tier at 2.5x the Opus price.
- **Latency [D]**, from Artificial Analysis measurements:
  - Claude Opus 5.5 outputs about 75–90 tok/s. Time to first token ranges from about 5 s at low effort to over 2 min at xhigh, because thinking runs before the first visible token.
  - GPT-6 Sol outputs about 100–120 tok/s, with TTFT of roughly 2–8 s at medium/high.
  - https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-high-vs-gpt-6-sol-high
  - [I] Expect a single-shot review to take **30 s – 3 min** at high effort, and an agentic review 3–15 min. Set client timeouts of at least 10 min, use streaming for large `max_tokens`, and give `max_tokens` headroom for reasoning tokens (§2).
- **Cost controls [I]:**
  - Cache the stable prefix: system prompt, rubric, spec.
  - Use the Batch API (50% off) for non-blocking nightly re-verification. [V] The `:batch` slugs on OpenRouter are half price, e.g. `anthropic/claude-opus-5.5:batch` at $2/$10.
  - Escalate tiers only on FAIL or INCONCLUSIVE from the cheap tier.

---

## 8. Recommended minimal backend abstraction

**[I] Design.** The labeled facts it rests on are cited above.

```text
interface ModelBackend {                       # one per configured backend
  complete_structured(req) -> StructuredResult
}
req = { system, messages, json_schema, effort: low|medium|high|xhigh|max,
        max_output_tokens, timeout_s, metadata{run_id, role: verifier|clarifier} }
StructuredResult = { status: ok|refusal|truncated|schema_invalid|error,
                     parsed?, raw_text, model_resolved, provider?,
                     usage{input, cached_input, output, reasoning, cost_usd?} }
```

Three adapters cover every backend the user named:

1. **`openai_chat`**: configured with `base_url`, `api_key_env`, `model`, and `extra_body`. It speaks Chat Completions with `response_format: json_schema strict`.
   - **OpenRouter**: `base_url=https://openrouter.ai/api/v1`, `extra_body={provider:{require_parameters:true, data_collection:"deny"}, reasoning:{effort}, models:[fallbacks…]}`, plus the `HTTP-Referer` and `X-OpenRouter-Title` headers.
   - **OpenAI direct**: `api.openai.com/v1`. Use `reasoning_effort`. [I] Chat Completions is enough; Responses is optional.
   - **Ollama**: `localhost:11434/v1`. Requires a context-length check and a no-`tool_choice` mode.
   - **Gemini direct** (beta compatibility layer) and **LiteLLM proxy / vLLM**.
2. **`anthropic_messages`**: native `POST /v1/messages` with `output_config.format` and `output_config.effort`. Anthropic direct needs it because the compat layer drops `response_format`. With OpenRouter's `/api/v1/messages` it can also serve as the Claude Agent SDK base.
3. **`agent_cli`**: runs a subprocess in a read-only sandbox.
   - `codex exec --sandbox read-only --output-schema S -o out.json`
   - `claude --bare -p --permission-mode dontAsk --allowedTools Read,Grep,Glob --output-format json --json-schema S`
   - `opencode run --format json -m …`, with client-side validation and one re-prompt

Cross-cutting rules, all [I], each grounded in the [V] facts above:
- **Always validate on the client side** with JSON Schema (`jsonschema` / `ajv` / zod), even when the backend claims strict mode. Allow one repair retry, then return INCONCLUSIVE. The verifier **fails closed**.
- **Never rely on forced `tool_choice`** for JSON: it returns 400 on Opus 5.5, Fable 5.1, and Sonnet 5.5, and Ollama ignores it.
- **Pin concrete model IDs** in committed config and log `model_resolved`. Use `~…-latest` only behind an explicit flag.
- **Use cross-vendor review by default.** If the implementer runs on Claude, default the verifier to an OpenAI or Google model, and the reverse.
- **Track cost from responses.** OpenRouter returns `usage.cost`; Claude Code returns `total_cost_usd`. For direct APIs, compute cost from usage times a price table, and refresh that table from OpenRouter `/api/v1/models` instead of hard-coding it.
- **Dependencies:** Python needs `httpx` plus `jsonschema` (optionally the `openai` and `anthropic` SDKs). TypeScript needs `fetch` plus `ajv`/zod (optionally `openai` and `@anthropic-ai/sdk`). No LiteLLM.

Example config (all IDs verified to exist on 2026-10-03):

```yaml
backends:
  openrouter:   { kind: openai_chat, base_url: https://openrouter.ai/api/v1, api_key_env: OPENROUTER_API_KEY,
                  headers: { HTTP-Referer: https://github.com/<org>/<repo>, X-OpenRouter-Title: agentic-harness },
                  extra_body: { provider: { require_parameters: true, data_collection: deny } } }
  openai:       { kind: openai_chat, base_url: https://api.openai.com/v1, api_key_env: OPENAI_API_KEY }
  anthropic:    { kind: anthropic_messages, base_url: https://api.anthropic.com, api_key_env: ANTHROPIC_API_KEY }
  ollama:       { kind: openai_chat, base_url: http://localhost:11434/v1, api_key_env: null, min_context: 65536 }
  codex_cli:    { kind: agent_cli, cmd: [codex, exec, --sandbox, read-only, --output-schema, "{schema}", -o, "{out}", "-"] }
  claude_cli:   { kind: agent_cli, cmd: [claude, --bare, -p, --permission-mode, dontAsk, --allowedTools, "Read,Grep,Glob",
                                         --output-format, json, --json-schema, "{schema_inline}"] }

verifier:
  backend: openrouter
  model: openai/gpt-6.1-sol          # "GPT 6.1"
  effort: high
  escalate_to: { backend: openrouter, model: anthropic/claude-opus-5.5, effort: xhigh }   # "Opus 5.5"
  hard_case:   { backend: openrouter, model: openai/gpt-6-astra, effort: high }           # "Astra"
  offline:     { backend: ollama, model: "qwen3.8:27b" }                                  # pre-filter only

clarifier:
  backend: anthropic
  model: claude-opus-5-5             # direct-API ID (note: hyphens, not dots)
  effort: medium
  fallback: { backend: openrouter, model: google/gemini-3.1-pro-preview }
```

Note the **ID format difference** [V]: Anthropic's direct API uses `claude-opus-5-5` (hyphens), while OpenRouter uses `anthropic/claude-opus-5.5` (dot). OpenAI's direct ID `gpt-6.1-sol` becomes `openai/gpt-6.1-sol` on OpenRouter.

---

## 9. Risks and open questions

- **[V] Endpoint heterogeneity on OpenRouter.** The same model can be served by an endpoint without structured-output support (Bedrock for Opus 5.5) or by fp4-quantized hosts for open models. Without `require_parameters: true`, a verifier could receive unconstrained text.
- **[V] Haiku 4.5 retirement** "not sooner than 2026-10-15". Don't put it in defaults.
- **[V] Gemini 3.1 Pro is "preview".** Preview models can change or be removed with little notice; prefer it as a fallback, not as the primary gate.
- **[V] Anthropic 5.5/5.1 behavior changes.** Thinking is always on, effort is the only control, and Opus 5.5 defaults to `medium`. A harness that sends `thinking:{type:"disabled"}` or `budget_tokens` gets a 400.
- **[U] Unverified items:**
  - the exact Codex `-m` flag
  - OpenCode's permission flags
  - which JSON-Schema keywords Ollama's constrained decoding ignores
  - real latencies of 6.1 Sol and Astra; the AA data is for GPT-6 Sol, not 6.1
  - whether the OpenRouter Advisor tool supports `response_format` in the same call
- **[I] Model churn.** Six frontier releases landed in September 2026 alone. Keep the model table as data, refreshed from `/api/v1/models`, not as code.

## Sources (primary unless marked)
- OpenRouter models API: https://openrouter.ai/api/v1/models ; endpoints API: https://openrouter.ai/api/v1/models/{id}/endpoints
- OpenRouter docs: https://openrouter.ai/docs/llms.txt and its pages: guides/features/structured-outputs, guides/routing/provider-selection, guides/best-practices/reasoning-tokens, api_reference/limits, api_reference/overview, api_reference/responses/overview, app-attribution, guides/routing/model-fallbacks, guides/routing/routers/latest-resolution, guides/features/server-tools(+/advisor), guides/ori/harness, guides/community/anthropic-agent-sdk, faq, byok
- Anthropic: https://platform.claude.com/docs/en/about-claude/models/overview.md ; https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md ; https://platform.claude.com/docs/en/api/openai-sdk.md
- OpenAI: https://developers.openai.com/api/docs/models ; …/models/gpt-6-astra ; …/models/gpt-6.1-sol ; https://developers.openai.com/api/docs/guides/structured-outputs ; https://learn.chatgpt.com/docs/non-interactive-mode ; openai.com/index/introducing-gpt-6-1-sol (the localized page appeared in search; the fetch returned 403)
- Google: https://ai.google.dev/gemini-api/docs/models ; https://ai.google.dev/gemini-api/docs/openai
- Ollama: https://docs.ollama.com/api/openai-compatibility.md ; /capabilities/structured-outputs.md ; /context-length.md ; /gpu.md ; /cloud.md ; https://ollama.com/search , https://ollama.com/library/{model}/tags
- Claude Code headless: https://code.claude.com/docs/en/headless ; OpenCode CLI: https://opencode.ai/docs/cli/
- GitHub runners: https://docs.github.com/en/actions/reference/runners/github-hosted-runners ; https://docs.github.com/en/actions/reference/runners/larger-runners
- LiteLLM: https://pypi.org/pypi/litellm/json ; https://docs.litellm.ai/docs/completion/json_mode
- [D] secondary: https://codersera.com/blog/gpt-astra-vs-google-project-astra-2026/ ; https://evolink.ai/blog/gemini-3-5-pro-api-release-watch ; https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/ ; https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-high-vs-gpt-6-sol-high ; https://docs.github.com/en/enterprise-cloud@latest/billing/reference/actions-runner-pricing
