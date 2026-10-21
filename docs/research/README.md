# Research evidence (2026-10-03)

These reports were produced by research agents during the design session and are kept as the evidence base for
[`../architecture.md`](../architecture.md) and [`../SPEC.md`](../SPEC.md). Every claim inside is labelled
**[V]** (primary source or reproduced locally), **[D]** (secondary source), **[I]** (inferred) or **[U]**
(unverified). They are agent-written: treat [D]/[I]/[U] claims as leads, not facts.

| Report | Topic |
|---|---|
| [01-spec-frameworks.md](01-spec-frameworks.md) | OpenSpec 1.14.0, Kiro specs + Kiro CLI, GitHub Spec Kit, other SDD frameworks, detection rules |
| [02-agent-clis.md](02-agent-clis.md) | Headless Claude Code, Codex, OpenCode, Kiro CLI, Gemini CLI and others; ACP; availability, quota and cool-down signals |
| [03-eval-verification.md](03-eval-verification.md) | Identification of Jev (TypeSafe AI) and Laya (ConvAI Innovations); deterministic verification ladder; Playwright test agents; LLM-as-judge determinism |
| [04-model-backends.md](04-model-backends.md) | Current frontier model IDs (Opus 5.5, Fable 5.1, Sonnet 5.5, GPT-6 Astra, GPT-6.1 Sol, Gemini 3.x), OpenRouter, Anthropic, Ollama, LiteLLM |
| [05-serena-memory.md](05-serena-memory.md) | Serena 1.7.0 memories, MCP wiring per CLI, CI gotchas, reproducible lessons design |
| [06-ci-orchestration.md](06-ci-orchestration.md) | Prior art (gh-aw, bmad-loop, Ralph loop…), definitions of L4, GitHub Actions and GitLab CI mechanics, state/locking/loop safety |
| [07-paper-2609.00006.md](07-paper-2609.00006.md) | arXiv 2609.00006 "Harness Engineering": vetted findings for the harness, guidance-file protection, tool-less calls in an empty directory, per-step caps |
| [08-understanding-harness-engineering.md](08-understanding-harness-engineering.md) | "Understanding Harness Engineering" (@techNmak): what it means for the harness, from four read-only audits and a skeptical re-check |
| [09-agentic-evals-and-judges.md](09-agentic-evals-and-judges.md) | How Anthropic, OpenAI and Cursor evaluate coding agents and judges: six candidates measured on Python, C#/xUnit and TS/Jest with a pre-registered score; the test-path freeze (L4-IMP-006 (7)) adopted |

## Claims re-verified independently by the orchestrator

The most load-bearing claims were reproduced outside the agents that reported them:

| Claim | How it was checked |
|---|---|
| OpenSpec tolerates `questions.md` and a sub-directory inside a change; `archive` moves them along | Ran OpenSpec 1.14.0 in a scratch repo: `validate --strict` passed, archive folder contained both |
| A change without spec deltas fails `validate --strict` unless `.openspec.yaml` has `skip_specs: true`; with it, it validates and archives | Same scratch repo |
| `openspec instructions apply --json` reports `progress {total, complete, remaining}` and `state` | Same scratch repo |
| Codex quota is readable at zero cost | `codex app-server` → `account/rateLimits/read` on Codex CLI 0.160.0: primary window 300 min, secondary 10080 min, `usedPercent`, `resetsAt`; 0.6 s, no model call |
| Claude Code `/usage` is free and `claude auth status` is JSON | Claude Code 2.1.288: `num_turns 0`, `total_cost_usd 0`; auth status JSON includes the account e-mail (must be dropped by the probe) |
| Model slugs exist | Raw OpenRouter `/api/v1/models` snapshot (466 models): `anthropic/claude-opus-5.5`, `anthropic/claude-fable-5.1`, `anthropic/claude-sonnet-5.5`, `openai/gpt-6-astra`, `openai/gpt-6.1-sol`, `google/gemini-3.1-pro-preview`, `google/gemini-3.8-flash`, all with structured outputs |
| Serena licensing | PyPI `serena-agent` latest = 1.7.0 (MIT); repo `main` = 2.0.0.dev0, `GPL-3.0-or-later` |
| Laya / Jev exist as described | PyPI `laya` 0.3.24 (Apache-2.0, first release 2026-09-18, 32 releases); PyPI `typesafe-sdk` 0.7.2; TypeSafe API reference (`POST /v1/systemone`, `noul`/`choice`/`score`) read live |
| Reference GitLab environment | GitLab API via Mintkey: server 17.5.2 CE; runner #12 tags/flags; project `example-group/dummy-agentic` settings |
