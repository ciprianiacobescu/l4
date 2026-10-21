# 03 — Verifier: deterministic evaluation, "Jav"/"Laia", and the evidence ladder

Research date: 2026-10-03. Labels: **[V]** checked against a primary source (URL given) or reproduced in a local experiment (marked *local*); **[D]** secondary source; **[I]** my inference; **[U]** not verified.

Local experiment artifacts live in `scratchpad/research/layatest/` (`det.py`, `disc.py`, `ts_client.py`), `scratchpad/research/pwinit/` (output of `playwright init-agents`), and downloaded docs in `scratchpad/research/{ts,laya,pw,misc}/`.

---

## 0. Verdict up front

| Garbled word | Identification | Confidence | Why |
|---|---|---|---|
| **"Jav"** | **Jev**, the first "System One" model from **TypeSafe AI** (hosted API, `jev-latest` / `jev-1.13.0`) | **High (~95%)** | One vowel off. It is marketed as a typed decision model, not a text generator. The user installed the TypeSafe Claude Code plugin (`typesafe@typesafe-ai` v0.5.7) on 2026-09-20 *[V local: `~/.claude/plugins/marketplaces/typesafe-ai`, file mtimes]*. DeepEval ships a `JevEval` metric "for when you … want it decided the same way every run" *[V https://deepeval.com/docs/metrics-jev-eval]*. |
| **"Laia"** | **Laya**, the open-weight (Apache-2.0) System-1 decision model from **ConvAI Innovations** (`pip install laya`, repo `NandhaKishorM/laya`, HF `convaiinnovations/laya`) | **High (~90-95%)** | "Laya" is pronounced like "Laia". It was released 3 days after Jev as an open alternative. Its server speaks **Jev's wire protocol** (`POST /v1/systemone`). Pairing it with Jev ("Jev or Laya") is the natural pairing: hosted vs self-hosted versions of the same idea. |

**Both are one tool category, not LLM-as-judge frameworks.** They are fast classifiers that read the evidence plus *typed questions* (Choice / Score / Noul = yes-no probability) and return **calibrated probabilities**, never generated text. In a Verifier they fit as the step **between deterministic tool checks and a full LLM review**. They answer narrow, per-criterion questions over evidence that tools already produced, and they escalate when uncertain. They are **not** code reviewers. Laya's context window is small (512-1,024 tokens by default), and zero-shot Laya is unreliable (see §1.5).

**What a Verifier should prefer, in order:** re-run builds, types, lint and tests itself → check the tests' integrity (no weakening) → check spec-scenario ↔ test traceability → generate any missing tests (Playwright for UI), proving each fails before the change and passes after → measure test quality (diff coverage, mutation on changed code) → check contracts, properties and security → then calibrated typed judgments (Jev/Laya) → then an adversarial LLM judge with a schema, rubric, citations and a panel → then a human. Details in §2.2.

---

## 1. Task A — Identifying "Jav" and "Laia"

### 1.1 Method
1. Brainstormed phonetic and contextual candidates (list below), then searched the web and GitHub for each.
2. A search for "deterministic evaluation harness" surfaced `marianoberton/agent-evals`, described as "Deterministic evaluation harness for LLM agents, with a calibrated judge (**Jev**)". That led to TypeSafe *[V https://github.com/marianoberton/agent-evals]*.
3. Confirmed the user's environment already has the TypeSafe plugin installed *[V local]*. Prior Claude transcripts mention it only in skill listings, with no conversation about it *[V local grep]*. The `agent-history` index had no hits for "Laia".
4. A search for "Laia" plus "calibrated decision model" surfaced **Laya**. Verified it on GitHub, PyPI and Hugging Face, then installed and ran it locally.

### 1.2 Candidate scoring

Scores run 0-5. "Phonetic" means how close the name sounds to the transcribed word. "Context" means fit with "deterministic model or approach … repositories on GitHub for each".

| Candidate | For | Phonetic | Context | Notes |
|---|---|---|---|---|
| **Jev (TypeSafe AI)** | Jav | 5 | 5 | Typed, calibrated decision model. GitHub org `typesafe-ai`: skills repo (2,545★), Python/JS SDKs, WorkflowEvals *[V GitHub API 2026-10-03]*. |
| G-Eval ("gee-eval") | Jav | 3 | 1 | An LLM-generative judge. DeepEval's own docs contrast it with JevEval *[V deepeval JevEval page]*. |
| Judgeval (Judgment Labs) | Jav | 2 | 2 | OSS SDK, but needs a hosted `JUDGMENT_API_KEY`. Tracing plus prompt-based "agent judges" *[V https://github.com/JudgmentLabs/judgeval]*. Not deterministic. |
| Javelin / "Jarvis" | Jav | 3 | 0 | Gateway and assistant names, not eval tools. |
| **Laya (ConvAI)** | Laia | 5 | 5 | Open-weight System-1 decision model. Wire-compatible with Jev. Ships an eval CLI and an MCP server *[V README]*. |
| Galileo Luna / Luna-2 | Laia | 2 | 3 | Small evaluation models from Galileo, a hosted product *[D https://galileo.ai/luna]*. |
| Lighteval (HF) | Laia | 1 | 2 | Benchmark harness, not a verifier judge. |
| Lyra / LLaDA / GAIA | Laia | 3 | 0-1 | No matching eval tool. LLaDA is a diffusion LLM (TypeSafe forked it). GAIA is a benchmark. |
| Atla Selene / Patronus Lynx·Glider / Prometheus / Flow-Judge | either | 0-1 | 3 | Generative judge LLMs. Good "small judge" alternatives, but the names don't match. |

The strongest evidence is that the two names **cohere as a pair**. Laya's README positions it explicitly against Jev ("Laya (with routing) vs Jev", "Where Jev leads", "Self-Hosting: HTTP Server (Jev-compatible)") *[V https://github.com/NandhaKishorM/laya]*.

### 1.3 Jev (TypeSafe AI): what it is and how to use it

- **What it is.** "Jev is TypeSafe's flagship model and the first System One model… returns typed answers and probabilities rather than generating text or reasoning explanations." It is trained with RLCD ("reinforcement learning for calibrated decisions") *[V https://docs.typesafe.ai/concepts/system-one.md, https://docs.typesafe.ai/introduction/machine-learning-primer.md]*.
- **Launch.** Announced around 2026-09-15 with a $40M seed *[D https://www.datacamp.com/blog/system-one-models-jev, https://www.explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026]*. The `typesafe-sdk` PyPI package first appeared 2026-09-09 and is now at 0.7.2 (2026-09-26) *[V pypi.org/pypi/typesafe-sdk/json]*. Early access is behind a waitlist *[D explainx]*.
- **Primitives.**
  - `choice` picks one of N options and returns probabilities plus confidence.
  - `score` returns a probability-weighted position on ordered, described levels, plus confidence.
  - `noul` returns P(yes).
  - All questions in a request are evaluated in parallel and in isolation against one `state` *[V https://docs.typesafe.ai/introduction.md]*.
- **API.** `POST https://api.typesafe.ai/v1/systemone` with `{state, model, questions}` and `Authorization: Bearer $TYPESAFE_API_KEY`.
  - Python: `pip install typesafe-sdk`; `from typesafe_sdk import TypeSafeClient, Choice, Noul, Score`.
  - JS: `@typesafe-ai/sdk` *[V https://docs.typesafe.ai/introduction/quickstart.md, https://docs.typesafe.ai/models.md]*.
  - The base URL can be overridden via the `TYPESAFE_BASE_URL` environment variable *[V https://docs.typesafe.ai/sdk/python/api/constants.md]*.
- **Model, price and limits.** `jev-1.13.0` (aliases `jev-latest`, `jev-preview`). $0.042 per million input tokens; output is free. Context is 64k per request, with 32k for `state` plus the longest question. Text only. Rate limits "adjusting dynamically". Pin the versioned ID if you tune thresholds *[V https://docs.typesafe.ai/models.md]*.
- **Latency.** 236-276 ms p50 in third-party measurements *[D https://github.com/AbdelStark/jev-benchmarks; https://github.com/nibzard/decision-model-benchmark reports a 267-316 ms median]*.
- **Determinism (load-bearing for this design).**
  - TypeSafe's own self-consistency cookbook ran a 14-question rubric 15 times, adding a fresh throwaway `uid` to each call. The mean per-question std dev was **0.0102**, lower than every LLM condition, *including LLMs at temperature 0*. But one answer ranged **0.43-0.53, crossing a 0.5 threshold**. The cookbook therefore maps 0.30-0.70 to an explicit `uncertain` outcome *[V https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md]*.
  - So Jev is **near-deterministic, not guaranteed bit-identical**. Whether byte-identical requests return byte-identical answers is **[U]**: no API key was available (`TYPESAFE_API_KEY` is not set), and I did not use any credential.
- **Known weak spots ("jaggedness").** It can't count reliably, is weak on dates and temporal ordering, and its accuracy drops as irrelevant state grows. Do counting and arithmetic in code *[V https://docs.typesafe.ai/model-jaggedness/jev-1.13.md]*. Banking77 (77 labels): Jev 0.870 *[V Laya README, citing third-party runs]*.
- **CI integration.**
  - **DeepEval `JevEval`**: a weighted mean over Noul, Score and Choice questions you write. Default threshold 0.5. "No LLM is involved at any point: even the reason is deterministic text built from Jev's answers." It runs under `deepeval test run` (pytest) *[V https://deepeval.com/docs/metrics-jev-eval, https://deepeval.com/docs/metrics-introduction]*.
  - `marianoberton/agent-evals` (TS) has `jevJudge` (gateable) vs `llmJudge` (excluded from gates by default), plus `agent-evals run --fail-under`. It is a tiny repo (0★), so use it as a pattern, not a dependency *[V GitHub]*.
  - `typesafe-ai/system-one-adapter-python` is a drop-in `TypeSafeClient` backed by OpenAI, Anthropic or Gemini, for comparing Jev against an LLM *[V raw README]*.
- **Repos.** https://github.com/typesafe-ai/skills (the installed plugin), https://github.com/typesafe-ai/typesafe-sdk-python, https://github.com/typesafe-ai/typesafe-sdk-js, https://github.com/typesafe-ai/WorkflowEvals *[V]*.

### 1.4 Laya (ConvAI Innovations): what it is and how to use it

- **What it is.** A "Multilingual, non-autoregressive System 1 decision engine… trained with reinforcement learning against strictly proper scoring rules (RLCD)". The English checkpoint is ModernBERT-large (421M parameters, 512-token context). `laya-multilingual` is mmBERT-base (322M parameters, 1,024 tokens, up to 8,192 with `max_len`). There is also a fine-tuned `laya-typed-decisions` checkpoint. Apache-2.0 *[V https://github.com/NandhaKishorM/laya README; https://huggingface.co/convaiinnovations/laya]*.
- **Release.** PyPI 0.1.0 on 2026-09-18 and 0.3.24 on 2026-10-02: **32 releases in 15 days**, so expect API churn. The repo has 30.3k★ *[V pypi JSON; GitHub page]*.
- **Install and run.** `python -m pip install laya` (Python ≥3.10). Extras: `[serve]`, `[mcp]`, `[onnx]`, `[langchain]`, `[fast]`. TS port: `laya-ts`. Usage: `Router().predict(state, questions)`, with the same question JSON as Jev *[V README]*.
- **Jev-compatible server.** `pip install "laya[serve]"; laya-serve` exposes `POST /v1/systemone` and `/v1/systemone/batch`.
  - "Laya's answer payload is already schema-identical to what Jev returns."
  - Differences: an option budget per question (about 20 options before options get trimmed); every score level needs a description; and the `confidence` formula differs, so thresholds don't transfer *[V README §Self-Hosting]*.
- **MCP server.** `pip install "laya[mcp]"; laya-mcp-server` exposes the tools `laya_predict`, `laya_predict_batch`, `laya_route`, `laya_decide` (JSON-schema-driven), `laya_shortlist` and `laya_preset` *[V README §MCP]*. A community plugin, `omp-laya-judge`, is a "local System-1 judge MCP server … confidence-gated escalation" *[V README; plugin not inspected]*.
- **Built-in eval gate.** `laya-evals run data.jsonl --model english --min-accuracy 0.8 --max-ece 0.05 --baseline baseline.json` exits non-zero on failure, so it drops into CI. Use it to **gate the judge itself** on your labelled verdicts *[V README §Evaluation harness]*.
- **Honest limits (self-reported).**
  - "The base checkpoints are near chance on typed-decisions zero-shot" (0.362/0.352 vs 0.318 random and a 0.461 majority-class baseline). The 0.766 figure comes from the fine-tuned checkpoint.
  - Calibration as shipped is over-confident. Mean ECE goes 0.466 → 0.081 only after per-bucket temperature fitting.
  - It fails on negation in some cases (e.g., picked `cancel_account` for negated requests with p=0.9998).
  - It is weak with more than 20 options *[V README §Honest limits, §Calibration]*.
  - Its comparison numbers for Jev are third-party, "never measured here" *[V README]*.

### 1.5 Local experiments

Run 2026-10-03 on macOS arm64, CPU, laya 0.3.24 and typesafe-sdk 0.7.2.

| Experiment | Result | Label |
|---|---|---|
| **Determinism.** Same state and questions, 5 calls per process × 3 fresh processes (one with `LAYA_THREADS=1`, `OMP_NUM_THREADS=1`) | **15/15 byte-identical** answer JSON (sha `2012e6e2d363`) | [V local] |
| **Discrimination, zero-shot.** Criterion "empty email → 'Email is required'" against test output that is PASS / FAIL / unrelated | English checkpoint: PASS → noul 0.83, choice A ✓. FAIL → noul **0.78** (should be low ✗), choice B ✓. Unrelated → noul 0.51, choice C (p=0.38, barely). Multilingual: PASS → noul **0.001** ✗. Unrelated → noul **0.97** ✗ | [V local] n=3, illustrative only |
| **Backend swap.** Official `TypeSafeClient(base_url="http://127.0.0.1:8765")` against local `laya-serve` | Works unchanged. Response `model: "laya-rl-agent"`, 3/3 identical | [V local] |

What this implies [I]:
- (a) Code the harness against the TypeSafe SDK or wire format, then choose **hosted Jev** (better zero-shot, costs money, waitlist, near-deterministic) or **local Laya** (free, offline, bit-deterministic on CPU, but needs fine-tuning and calibration on your own labelled verdicts before you trust it).
- (b) Never let a typed judgment *override* a deterministic signal. The FAIL case shows why.
- (c) Whether DeepEval `JevEval` honours `TYPESAFE_BASE_URL` (so it could run on Laya) is plausible, because it uses the TypeSafe SDK, but it is **untested [U]**.

### 1.6 Where Jev/Laya belong in the Verifier

- **Good uses [I].** Narrow semantic gate questions over *already-collected evidence*. For example:
  - "Does this Playwright step log show the error text required by Scenario X?" (Noul)
  - "Which of {implemented, partially, not implemented, contradicted} best describes criterion 3.2, given this test name, its assertions, and the diff hunk summary?" (Choice)
  - "Is this PR description claim supported by the cited test output?" This follows TypeSafe's "citation check / verify and escalate" pattern *[V SKILL.md, docs/cookbooks/citation_check]*.
  - Triage: routing failures to the right fixer; scoring severity of reviewer findings.
- **Gate with a band.** Accept at p ≥ 0.9, reject at p ≤ 0.1, and escalate everything in between to the LLM judge. Pin the model version. Log every request so it can be replayed. This mirrors TypeSafe's `uncertain` band *[V cookbook]*.
- **Bad uses.**
  - Judging raw code correctness or large diffs: Laya's window is 463 tokens of state on the English checkpoint *[V README]*, and Jev's limit is 32k.
  - Counting assertions, comparing dates, arithmetic (*[V jaggedness doc]*): do these in code.
  - Being the only gate for anything irreversible *[D width.ai, citing the vendor]*.

### 1.7 Runner-up frameworks (if the user meant "a framework" instead)

| Tool | CI usage | Deterministic checks | LLM-judge backends | Repo |
|---|---|---|---|---|
| **DeepEval** 4.2.8 (PyPI) | `deepeval test run` (pytest) | JSON Correctness, Tool Correctness, Argument Correctness, **JevEval**. DAG makes the *graph structure* deterministic, but nodes still use an LLM: "No… their outputs can vary" *[V https://deepeval.com/docs/metrics-dag]* | OpenAI, Azure (`deepeval set-azure-openai`), Anthropic (`AnthropicModel`), Gemini (`set-gemini`), Ollama (`set-ollama`), LiteLLM, custom `DeepEvalBaseLLM` *[V docs]* | github.com/confident-ai/deepeval |
| **promptfoo** 0.123.1 (npm) | `promptfoo eval`; non-zero exit on failures | equals, contains*, regex, is-json, contains-json, is-sql, is-xml, javascript, python, webhook, latency, cost, is-valid-openai-tools-call, tool-call-f1, `not-` negation *[V https://www.promptfoo.dev/docs/configuration/expected-outputs/]* | llm-rubric, g-eval, factuality, select-best, `pi`, `classifier`. Grader set per assertion via `provider` | github.com/promptfoo/promptfoo |
| **Inspect AI** 0.3.276 (PyPI) | `inspect eval`; sandboxed tool execution | includes, match, pattern, exact, f1, choice, math *[V https://inspect.aisi.org.uk/scorers.html]* | model_graded_qa, model_graded_fact (any provider Inspect supports) | github.com/UKGovernmentBEIS/inspect_ai |
| **Judgeval** 1.3.3 | Hosted platform | none notable | prompt-based "agent judges" | github.com/JudgmentLabs/judgeval |

---

## 2. Task B — Deterministic verification toolbox

### 2.1 Principles
1. **Never trust the implementer's own evidence. Re-run it [I].** The Verifier checks out the head commit in a clean environment and runs everything itself. Implementer logs are leads, not evidence. This is the "a system's own output is never its own oracle" rule from the user's CLAUDE.md.
2. **Deterministic before probabilistic.** A check that can be expressed as an exit code, a schema validation, or a diff predicate must not be delegated to a model. TypeSafe's own guidance agrees: "Keep known rules, calculations, exact lookups, and execution in code" *[V SKILL.md]*.
3. **Missing check ⇒ build the check.** If an acceptance criterion has no executable test, the Verifier writes one (Playwright for UI). It must prove the test is meaningful: it fails on the base commit and passes on the head. This is SWE-bench's FAIL_TO_PASS / PASS_TO_PASS discipline *[V https://github.com/SWE-bench/SWE-bench docs/guides/datasets.md]*.
4. **Every verdict cites evidence that a machine can re-check:** file:line, test ID, trace path, command and exit code.

### 2.2 The evidence ladder (run in order; stop on a hard fail)

| Rung | Check | Typical tools | Output evidence | Label |
|---|---|---|---|---|
| **E0 Integrity and scope** | Diff touches only files the plan allows. No deleted or skipped tests (`.skip`, `.only`, `test.fixme`, `xit`, `@pytest.mark.skip`, `t.Skip`). No new `eslint-disable`, `# type: ignore`, `@ts-expect-error` or `nolint` without justification. Assertion count is not reduced. No lockfile drift unless planned. No secrets | `git diff --numstat`, grep rules or semgrep custom rules, `gitleaks git --log-opts="base..head"` *[V gitleaks README]* | JSON list of violations | [I] design; tools [V] |
| **E1 Build / types / lint / format** | Project-native commands (see §2.3) | per ecosystem | exit codes and logs | [I] |
| **E2 Tests** | Full suite plus changed tests. Re-run new and changed tests N times to detect flakiness | pytest `--junitxml`, jest/vitest junit, `go test -json`, `cargo test`; Playwright `--repeat-each N`, `--fail-on-flaky-tests`, `--only-changed` *[V Playwright test-cli docs]* | JUnit XML / JSON | [V] flags |
| **E3 Spec ↔ test traceability** | Every OpenSpec `#### Scenario:` and every Kiro EARS criterion maps to ≥1 **executed, passing** test (§2.6) | parser plus JUnit/JSON report join | coverage matrix (scenario → test IDs → status) | [I] design |
| **E4 Generated tests for gaps** | For unmapped scenarios: generate the test (unit, API or Playwright), run it on **base (expect fail)** and **head (expect pass)** | Playwright planner/generator (§2.9), Hypothesis/fast-check | new test files plus fail→pass proof | [I] (FAIL_TO_PASS [V]) |
| **E5 Test quality** | Coverage of *changed lines*. Mutation testing restricted to changed code; surviving mutants count as findings | `diff-cover coverage.xml --fail-under=N` (10.6.0) *[V README]*; Stryker `--incremental` (core 10.0.0) *[V docs/incremental.md]*; mutmut 3.8 `mutmut run "module*"`, `mutate_only_covered_lines` *[V README]*; cosmic-ray 8.7; PIT `scmMutationCoverage` / `withHistory` *[D pitest.org via search]*; cargo-mutants `--in-diff` *[V book]* | mutation score on diff; survivors list | as cited |
| **E6 Contracts and schemas** | API: OpenAPI breaking-change diff plus schema-driven fuzzing. JSON-schema validation of configs and payloads. Consumer contracts. DB migrations apply and roll back | schemathesis 4.29 `schemathesis run <openapi>` *[V README]*; oasdiff `breaking` *[U, README not fetched]*; Pact *[U]* | failing operations, breaking diffs | as cited |
| **E7 Properties** | Invariants from spec ("for any…") as property-based tests | Hypothesis 6.168, fast-check 4.10 *[V PyPI/npm]*; Kiro derives "correctness properties" from EARS and generates PBT *[V https://kiro.dev/docs/specs/correctness/]* | shrunk counterexamples | as cited |
| **E8 Static analysis and security** | New findings only, vs base | `semgrep scan --baseline-commit=<base>` ("Only show results that are not found in this commit") *[V https://semgrep.dev/docs/cli-reference]*; CodeQL; `npm audit`, `pip-audit`, `osv-scanner` *[U versions]* | SARIF | as cited |
| **E9 Calibrated typed judgments** | Per-criterion Noul/Choice over evidence from E2-E8. Confidence-banded | Jev or Laya (§1) | probabilities plus request log | [V] tools, [I] placement |
| **E10 Adversarial LLM judge** | Rubric per criterion, structured output, required citations re-checked by code, panel and stability (§2.10) | session model / panel | verdict JSON | [I] |
| **E11 Human** | Anything still uncertain, or any irreversible change | — | — | [I] |

### 2.3 Ecosystem detection (deterministic command discovery) [I]

| Signal file | Build / type / lint | Tests (machine-readable) | Mutation |
|---|---|---|---|
| `package.json` (read `scripts`; `packageManager` / lockfile picks npm/pnpm/yarn/bun) | `tsc --noEmit`, `eslint .`, `prettier --check` | vitest/jest with junit reporter; `@playwright/test` → `npx playwright test --reporter=junit,json,html` | Stryker |
| `pyproject.toml` / `setup.cfg` / `requirements*.txt` (uv/poetry/pip) | `ruff check`, `ruff format --check`, `mypy`/`pyright` | `pytest --junitxml=…` plus `coverage xml` | mutmut, cosmic-ray |
| `go.mod` | `go build ./...`, `go vet`, `golangci-lint run` | `go test -json -coverprofile` | gremlins / go-mutesting [U] |
| `Cargo.toml` | `cargo build`, `cargo clippy -D warnings`, `cargo fmt --check` | `cargo test` / nextest junit | cargo-mutants `--in-diff` |
| `pom.xml` / `build.gradle(.kts)` | `mvn -q verify` / `./gradlew check` | surefire XML | PIT |
| `*.csproj` | `dotnet build -warnaserror` | `dotnet test --logger trx` | Stryker.NET [U] |

Prefer explicit project config (CI workflow files, `Makefile`/`justfile`/`Taskfile`, `package.json` scripts) over guessed commands. Parse `.github/workflows/*.yml` to reuse exactly what CI runs [I].

### 2.4 Anti-gaming checks the Verifier must own [I]
Agents under pressure make tests pass by weakening them. Deterministic detectors:
- The diff touches test files **and** source for the same behaviour. Flag assertion deletions and weakened matchers, e.g. `toEqual` → `toBeTruthy`, or snapshot updates (`-u`, `--update-snapshots`) without spec cause.
- New `skip`/`fixme`/`xfail`/`only`, lowered coverage thresholds, edited CI config, edited `.semgrepignore`/`.eslintrc`.
- **Playwright healer risk (verified).** The generated healer definition literally says it may fix "assertions and expected values", may "mark this test as test.fixme()", and must "do the most reasonable thing possible to pass the test" *[V local: `npx playwright init-agents --loop=claude` output in `pwinit/.claude/agents/playwright-test-healer.md`]*. The healer may therefore repair **locators/waits only** on acceptance tests. Any change to an `expect(...)` line, or any added `fixme`/`skip`, fails E0 and needs explicit justification.

### 2.5 Test quality: coverage diff and mutation
- **Coverage on changed lines** (diff-cover) is cheap; run it every time. Its weakness is that coverage ≠ assertion strength *[I]*.
- **Mutation testing on the diff only** keeps cost bounded:
  - Stryker incremental reuses prior results and only re-runs mutants affected by code or test changes *[V docs]*.
  - cargo-mutants `--in-diff` "tests only mutants that overlap with regions changed in the diff". Its caution: a diff that only changes test code triggers no mutants *[V book]*.
  - mutmut: function-level selection *[V]*.
  - PIT: `scmMutationCoverage` (ADDED/MODIFIED files) and `withHistory` *[D]*.
- Surviving mutants on new lines are the most objective signal that tests don't pin the behaviour. They feed back to the implementer as concrete findings *[I]*.

### 2.6 Spec-scenario → test traceability (deterministic design) [I]
- **Sources.**
  - OpenSpec delta specs use `### Requirement:` plus `#### Scenario:` with `- **WHEN** … - **THEN** …` bullets *[V https://github.com/Fission-AI/OpenSpec README]*. `openspec validate --strict --json` checks structure *[V docs/cli.md]*.
  - OpenSpec's own `/opsx:verify` is **LLM-driven** (completeness/correctness/coherence; "Does not block archive") *[V docs/commands.md]*. It is a useful second opinion, not a deterministic gate.
  - Kiro `requirements.md` uses EARS ("WHEN … THE SYSTEM SHALL …") with numbered criteria *[D search summaries; kiro.dev correctness page V]*.
- **Stable IDs.** Derive `SCN-<capability>-<slug(scenario title)>` (OpenSpec) or `REQ-<n>.<m>` (Kiro) deterministically. Store a manifest `verification/scenarios.json`.
- **Tagging convention.**
  - Playwright: `test('…', { tag: ['@SCN-auth-empty-email'] }, …)`, selectable via `--grep` *[V docs/src/test-annotations-js.md]*.
  - pytest: `@pytest.mark.scenario("SCN-…")`.
  - Go: `// scenario: SCN-…` plus a `t.Run` name prefix.
  - Generic fallback: an ID in the test title.
- **Join.** Parse JUnit/JSON reports (Playwright JSON and JUnit reporters *[V docs]*) into a matrix `scenario → [test ids] → {passed, failed, skipped, missing}`.
- **Gate.** Every scenario has ≥1 passed, non-skipped test that was run in this verification, and every new test passes the fail(base) → pass(head) check. A scenario with only a unit test, where the scenario is user-visible UI, is flagged "needs e2e" by a deterministic rule: the scenario mentions UI nouns (page/click/button/shows), or the change touches UI paths [I].

### 2.7 Property-based testing
- Hypothesis (Python) and fast-check (TS) are current and maintained *[V registries]*. Kiro frames EARS criteria as universally quantified "correctness properties" and runs generated PBT cases *[V kiro.dev/docs/specs/correctness]*.
- Verifier rule [I]: for criteria phrased "for any / all / every / never", generate a property test. Persist the seed and shrunk counterexample as evidence (`@seed`, Hypothesis database).

### 2.8 Playwright for web UI

**Versions.** `playwright`/`@playwright/test` latest is **1.63.0**; `@playwright/mcp` is **0.0.83** *[V npm registry 2026-10-03]*.

**Playwright Test Agents — introduced in v1.56, confirmed** *[V https://github.com/microsoft/playwright docs/src/release-notes-js.md §1.56; docs/src/test-agents-js.md]*:
- **planner** explores the app and writes a Markdown plan to `specs/*.md`. It takes a `seed.spec.ts` and an optional PRD.
- **generator** turns the plan into `tests/*.spec.ts`, "verifies selectors and assertions live".
- **healer** replays failures and patches the test, or marks it `fixme`.
- `npx playwright init-agents --loop=…` choices in 1.63: **claude, codex, copilot, opencode, vscode, vscode-legacy** *[V local `--help`]*.
- For Claude it writes `.claude/agents/playwright-test-{planner,generator,healer}.md` (frontmatter `model: sonnet`), `seed.spec.ts`, `specs/README.md`, and `.mcp.json` with server `playwright-test` → `npx playwright run-test-mcp-server` *[V local run]*.
- Regenerate the definitions after every Playwright upgrade *[V docs]*.

**Playwright MCP (`@playwright/mcp`).** Accessibility-snapshot-based browser control ("No vision models needed"). Key flags:
- `--headless`, `--isolated`, `--output-dir`, `--snapshot-mode`, `--caps vision,pdf,devtools`.
- Opt-in `--caps=testing` adds `browser_verify_element_visible`, `browser_verify_text_visible`, `browser_verify_list_visible`, `browser_verify_value` and `browser_generate_locator`.
- Install: `claude mcp add playwright npx @playwright/mcp@latest` *[V https://github.com/microsoft/playwright-mcp README]*.
- Since 1.62, Playwright itself bundles `npx playwright mcp` and `npx playwright cli` *[V release notes §1.62]*.

**Agent-relevant features added after 1.56** *[V release notes]*:
- 1.59:
  - `npx playwright test --debug=cli` (agents attach via `playwright-cli`).
  - `npx playwright trace open|actions|action|snapshot` for CLI trace analysis.
  - `page.screencast` "agentic video receipts" with chapters and action overlays.
  - `Browser.bind` to share a browser across `playwright-cli`/MCP.
- 1.60: `toMatchAriaSnapshot` on Page; `boxes` option on aria snapshots "for AI consumption"; `TestInfoError.errorContext` (aria snapshot at failure).
- 1.61: video modes matching trace modes (`retain-on-failure-and-retries`, …); `FullConfig.failOnFlakyTests`; HAR and trace include WebSockets.
- 1.63: aria and screen snapshots inside traces (`trace: { snapshots: { dom, aria, screen } }`); `ariaSnapshotJSON`; `perfetto` reporter.

**Recommended Verifier flow for UI criteria [I, built on the features above]:**
1. From E3, collect UI scenarios with no passing e2e test.
2. Ensure a `seed.spec.ts` that boots the app, using `webServer` in `playwright.config.ts`.
3. Run the **planner** with the scenario text as the PRD; require one plan section per scenario ID. Then run the **generator**. Require `{ tag: '@SCN-…' }` and web-first assertions mapped one-to-one to THEN clauses: role-based locators, `toHaveText`, `toHaveURL`, `toMatchAriaSnapshot`.
4. Deterministic validation of the generated test:
   - (a) `git stash`/worktree at **base**: the new test must **fail**.
   - (b) At **head**: it must **pass** under `--repeat-each=3 --fail-on-flaky-tests`.
   - (c) There must be at least one assertion per THEN clause (static count).
   - (d) No `waitForTimeout` and no `networkidle` (the healer definition itself bans `networkidle`) *[V local agent file]*.
5. Allow the **healer** only for locator/timing fixes on generated tests. E0 rejects assertion edits.
6. CI command (headless is the default in `playwright test`):
   `npx playwright test --grep "@SCN-" --reporter=junit,json,html --trace=retain-on-failure` (use `--trace=on` when collecting evidence for the verdict).
   Upload the `test-results/**/trace.zip`, screenshots, videos and the HTML report as artifacts. Link the evidence from the verdict. Optionally record a screencast "receipt" per scenario for human review.
7. A model may read traces through `npx playwright trace actions --grep="expect"`. That text, not screenshots, is what goes into E9/E10 judgments [I].

### 2.9 LLM-as-judge made as deterministic as possible

| Lever | Status / recommendation | Label |
|---|---|---|
| **temperature 0** | **Not available on current top Claude models.** `temperature`/`top_p`/`top_k` return **400** on Claude Opus 5.5, Opus 5, Fable 5/5.1, Opus 4.8/4.7 and Sonnet 5. Non-default values return 400 on Sonnet 5.5. Still allowed on Opus/Sonnet 4.6 and Haiku 4.5 | [V Claude API skill bundle, cached 2026-09-25: `shared/error-codes.md`, thinking table] |
| temperature 0 ≠ deterministic anyway | Production servers batch requests; reduction kernels are not batch-invariant, so logits differ by batch size. With batch-invariant kernels, vLLM got 1,000/1,000 identical completions (vs ~80 distinct by default) | [D summaries of Thinking Machines "Defeating Nondeterminism in LLM Inference", Sep 2025] |
| seed | OpenAI `seed` plus `system_fingerprint` is "best effort… (mostly) consistent". No Anthropic seed parameter documented | [V cookbook.openai.com reproducible_outputs]; Anthropic [U/I] |
| Structured output | Claude: `output_config.format` (JSON schema) or `strict: true` tools. Forced `tool_choice` any/tool returns **400** on Opus 5.5, Sonnet 5.5 and Fable 5.1 (use `auto` + strict or structured outputs) | [V skill bundle] |
| Rubric decomposition | One question per acceptance criterion: categorical verdict (`pass`/`fail`/`insufficient_evidence`) plus required `evidence` array (file:line, test ID, trace path). Code then checks each citation exists and matches (grep the file:line; test ID in the JUnit report with status). Any unverifiable citation ⇒ `insufficient_evidence` | [I] |
| Fixed graph | DeepEval DAG-style trees make the mapping from findings to scores explicit, but nodes still sample | [V deepeval DAG docs] |
| Panel / jury | PoLL: a panel of smaller models from *different families* beat a single GPT-4 judge, with less intra-model bias, at over 7× lower cost | [V arXiv 2404.18796] |
| Stability over repeats | Run the judge k times and report **pass^k** = E[C(c,k)/C(n,k)] (all k trials succeed) rather than pass@k. Require unanimity or a stable majority for "pass" | [V arXiv 2406.12045 html] |
| Typed judges | Prefer Jev/Laya-style probabilities with an `uncertain` band over 1-10 scores | [V TypeSafe cookbook] |
| Caching and replay | Cache verdicts keyed by sha256(evidence bundle + rubric + model ID + version), so re-runs are identical by construction. Log full requests | [I] |
| Self-hosted determinism | If bit-reproducibility is required: batch-invariant vLLM mode or a local encoder (Laya on CPU: 15/15 identical) | [D]/[V local] |

### 2.10 Suggested verdict artefact [I]
`verification/<change-id>/verdict.json`:
```json
{
  "change": "add-dark-mode", "head": "<sha>", "base": "<sha>",
  "rungs": {"E0": "pass", "E1": "pass", "E2": {"status": "pass", "junit": ["..."]},
            "E3": {"scenarios": 7, "covered": 7}, "E4": {"generated": 2, "fail_to_pass": 2},
            "E5": {"diff_coverage": 0.93, "mutants_survived_on_diff": 1},
            "E8": {"new_findings": 0}},
  "criteria": [{"id": "SCN-theme-toggle", "verdict": "pass", "deterministic": true,
                "evidence": ["tests/theme.spec.ts:12 @SCN-theme-toggle passed x3", "test-results/.../trace.zip"],
                "typed_judgment": {"engine": "laya-0.3.24|jev-1.13.0", "noul": 0.97},
                "llm_judge": null}],
  "overall": "pass|fail|needs-human", "escalations": []
}
```
Rule: `overall = pass` only if every criterion is `pass`, and each pass rests on E2-E8 evidence (`deterministic: true`) or on a unanimous panel with verified citations [I].

---

## 3. Risks, open questions, what could be wrong

1. **Identification risk.** I found no direct record of the user mentioning either name. The identification rests on phonetics, launch timing (Jev 2026-09-15, Laya 2026-09-18), and the installed TypeSafe plugin. If the user meant a generic LLM-judge framework, DeepEval (which now includes JevEval) is the bridge candidate. **Confirm with the user.**
2. **Both products are three weeks old.** Laya ships about two releases a day. Jev is waitlisted with "dynamically adjusting" rate limits. Pin versions and keep the Verifier functional without them (they are an optional step, E9).
3. **Laya zero-shot quality is poor** (README plus my 3-case probe). It needs a labelled verdict set from this harness, `laya-evals` gating, and calibration before use. **Jev near-determinism is vendor-measured.** Byte-identical replay is [U].
4. **Claude judges cannot be pinned to temperature 0** on the current flagship models. Determinism must come from structure (schemas, citations re-checked by code, panels, pass^k, caching), not sampling settings.
5. **Healer and generator agents optimise for "green".** Without E0's assertion-diff rule, they can silently convert real failures into `fixme` or weakened expectations (verified in the generated agent text).
6. Unverified items: PIT SCM goal details, oasdiff CLI, Pact, Stryker.NET, gremlins, Anthropic seed absence, and DeepEval JevEval + `TYPESAFE_BASE_URL` → Laya.

## 4. Sources (primary unless marked)
- TypeSafe docs index https://docs.typesafe.ai/llms.txt. Pages: models, system-one, quickstart, machine-learning-primer, model-jaggedness/jev-1.13, cookbooks/consistency_noul_cookbook, sdk/python/api/constants (all `.md`)
- TypeSafe GitHub: https://github.com/typesafe-ai/skills · /typesafe-sdk-python · /typesafe-sdk-js · /system-one-adapter-python · /WorkflowEvals
- Laya: https://github.com/NandhaKishorM/laya · https://huggingface.co/convaiinnovations/laya · https://pypi.org/project/laya/ · https://laya-ai.com/ (community site, not affiliated)
- DeepEval: https://deepeval.com/docs/metrics-jev-eval · https://deepeval.com/docs/metrics-dag · https://deepeval.com/docs/metrics-introduction
- promptfoo assertions: https://www.promptfoo.dev/docs/configuration/expected-outputs/
- Inspect scorers: https://inspect.aisi.org.uk/scorers.html
- Judgeval: https://github.com/JudgmentLabs/judgeval
- agent-evals (Jev judge pattern): https://github.com/marianoberton/agent-evals
- Third-party Jev benchmarks: https://github.com/AbdelStark/jev-benchmarks · https://github.com/nibzard/decision-model-benchmark
- Playwright: https://github.com/microsoft/playwright/blob/main/docs/src/test-agents-js.md · release-notes-js.md · test-cli-js.md · test-annotations-js.md · test-reporters-js.md · https://github.com/microsoft/playwright-mcp
- OpenSpec: https://github.com/Fission-AI/OpenSpec (README, docs/commands.md, docs/cli.md)
- Kiro correctness / PBT: https://kiro.dev/docs/specs/correctness/
- Stryker incremental: https://github.com/stryker-mutator/stryker-js/blob/master/docs/incremental.md · mutmut: https://github.com/boxed/mutmut · diff-cover: https://github.com/Bachmann1234/diff_cover · cargo-mutants in-diff: https://github.com/sourcefrog/cargo-mutants/blob/main/book/src/in-diff.md · PIT: https://pitest.org/quickstart/maven/ [D]
- semgrep CLI: https://semgrep.dev/docs/cli-reference · gitleaks: https://github.com/gitleaks/gitleaks · schemathesis: https://github.com/schemathesis/schemathesis
- SWE-bench FAIL_TO_PASS: https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/datasets.md
- τ-bench pass^k: https://arxiv.org/html/2406.12045 · PoLL: https://arxiv.org/abs/2404.18796
- OpenAI seed: https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter
- Batch invariance [D]: https://www.morphllm.com/defeating-nondeterminism-llm-inference (summary of Thinking Machines, Sep 2025)
- Secondary on Jev/Laya [D]: https://www.width.ai/post/what-is-jev-ai-typesafe · https://www.datacamp.com/blog/system-one-models-jev · https://vantaverse.in/blog/laya-ai-open-source-decision-model-explained · https://aiweekly.co/alerts/convai-ships-laya-a-421m-modernbert-decision-model-apache-20
