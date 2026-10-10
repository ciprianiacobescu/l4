# Evaluation framework: how L4 decides a unit is done, and how to fit it per project

2026-10-04 · for the maintainer of the L4 harness.

**Staleness (HB-14).** The status below is a snapshot of 2026-10-04 and is out of date: `main` has since reached M1.5 (live exit on dummy-agentic, PASS) and the `hb` branch adds HB-1 to HB-12. Treat each `main`, `m12`, `m13`, `m15` label as true only at the commit named here; re-verify with the code before relying on it.

**What was checked.** Status is as of `main` @`655bf87` (M0 + M1.1; `main` has moved past `09429fc` since; its only
`src/` change after `655bf87` is `1df7ed2`, a job-log progress trace that changes no evaluation behaviour) and the unmerged branches `m12` @`295a49e`, `m13` @`664fc78` (plus uncommitted work in
progress: 19 files at 17:30 on 2026-10-04) and `m15` @`7a3ae0a` (Stages A and B only). The Jev numbers come from 30 live calls to the TypeSafe API, served by `jev-1.13.0`, on
2026-10-04.

**Labels.**
* [V] verified: code read, grep over `src/l4/**/*.py` (schema and defaults excluded), or measured.
* [I] inferred.
* [G] a starting value to calibrate.
* [plan] written in a plan but not built.

**Status words.**
* `main`, `m12`, `m13`, `m15`: built on that branch.
* `m15-unwired`: the module and its tests exist, but the Stage C wiring does not, so it never runs inside a unit.
* **IGNORED**: the key passes schema validation, but nothing on any branch reads it, so setting it changes nothing.
* `deferred`: the OpenSpec task has been pushed to M2.

---

## Answer in brief

1. **The framework.** The harness collects evidence in layers before a unit can PASS. Intake comes first, then the
   implementer's red/green proof, then the verifier ladder (steps 0–10), then deterministic aggregation. Three rules
   hold everywhere:
   * Deterministic evidence decides: a gate, a test or an integrity check.
   * An LLM judge can only hold back a PASS. On its own it can never FAIL a unit.
   * A human decides product questions.
2. **What fits it to a project today.** A small set of levers changes outcomes on `main`:
   * the gate commands (what the oracle is);
   * the test and forbidden path globs;
   * which judges run, under which independence rule;
   * how strict the clarifier is.

   `m13` adds audit, traceability and fix-loop levers. About 20 other evaluation keys are **IGNORED on every
   branch** [V], and several code constants cap the levers that do work (§3).
3. **How to fit it better.**
   * Eval profiles: presets that `l4 init` writes (a proposal that needs no new runtime key, §4).
   * A calibration loop over labels the ledger already records (§5).
   * Project canaries: seeded changes that must be caught and correct changes that must pass (§5.4).
4. **Jev** suits narrow judgments over evidence the harness has already collected: whether a criterion is satisfied
   by its evidence (verifier step 8), and whether a citation shows a specific claim.

   > **Regression risk.** Wiring Jev with the SPEC's current router and citation questions and thresholds turns
   > clarifier auto-accept **off**. The router question scored 0.24 and 0.42 on two technical questions; the rule
   > needs ≤ 0.1. Genuinely supportive citations peaked at 0.89; the rule needs ≥ 0.9 [V]. The only live auto-accept
   > so far ran on the `llm_boolean` stand-in, whose p is always 0 or 1 and is not a probability. Redesign the
   > questions first (§6).
5. **The Jev API key** is stored in Mintkey as `typesafe-jev-api-key`. I confirmed the name and that its size is
   107 bytes, which matches a key of that shape, by listing metadata only; the value was not read [V]. It was copied,
   unprinted, into the masked GitLab CI variable `TYPESAFE_API_KEY` (`scripts/forge/gitlab_ci_var_from_mintkey.py`),
   and pipeline 2612 got HTTP 200 from the runner [V, `docs/runner/README.md`]. The key was pasted in plain text
   into a chat, so it is in a local session transcript. **Rotate it**, store the new value in the same Mintkey
   secret, and re-run the copier.

---

## 1. The framework in one picture

```
spec merged to base
  │
  ▼
INTAKE (deterministic, no agent spend)
  ODD checks · test oracle required (else exit 14) · scenario-conflict lint (L4-ODD-004)
  · open questions listed in design.md are raised
  │                                   ┌──────────────────────────────────────────────────────────┐
  ├── blocking question ────────────► │ CLARIFIER (LLM answer + S1 checks)                       │
  │                                   │ auto-accept only when: kind technical (both sides),      │
  │                                   │ confidence ≥ min_confidence, ≥ 1 citation and each one   │
  │                                   │ resolves at the cited place, S1 router p(product) ≤ 0.1, │
  │                                   │ every citation's support p ≥ 0.9                         │
  │                                   │ otherwise ─► human answers in questions.md               │
  │ ◄──────── answer committed ─────  └──────────────────────────────────────────────────────────┘
  ▼
IMPLEMENTER (TDD evidence, per task)
  red:   new tests fail; nothing that passed at base breaks; static gates hold
  green: red tests frozen; full gate; no new failures; static gates hold
  guards: forbidden paths reverted · max_task_attempts → breaker → halted
  ▼
VERIFIER LADDER (fresh worktree; judge independent of every implementer that committed)
  0 preconditions   1 integrity           2 setup/build/lint/typecheck   3 full tests (+ e2e)
  4 traceability    4a audit sample       5 generate missing tests        6–7 extra gates (opt-in)
  8 S1 per criterion (records p only)     9 LLM judge                     10 aggregation (code)
  ▼
VERDICT
  PASS        → verified → MR ready → human merges → archive MR
  FAIL        → m13: fix unit on the same branch (≤ max_fix_rounds), else escalated (exit 13)
                main: `fixing` (exit 10), no fix unit is created
  NEEDS_HUMAN → awaiting_human (exit 11); m13: `Kind: verdict` questions answered accept / reject
```

The ladder above is the SPEC §10.2 target [V]. `main` runs steps 0, 2, 3, 9 and 10 only; `m13` adds 1, 4 and 4a;
`m15` builds 5 (UI criteria only) and 8 but does not wire them; 6–7 are not built anywhere. The fresh verifier
worktree (verifier 1.5) is not built either: the steps run in the run's unit worktree.

### Principles and where they are enforced

| Principle | Meaning | Enforced by | Status |
|---|---|---|---|
| Deterministic first | A criterion `fail` and a unit FAIL rest only on a failing gate, test or integrity check, or (m13) on a human `reject` of a verdict question | `verifier/aggregate.py` | main, m13 [V] |
| LLM judgments never FAIL alone (P7) | A judge `fail` becomes `needs_human`. It blocks a PASS and nothing more. | `aggregate.py`. Counterexamples are never executed (deferred, verifier 1.5) | main, m13 [V] |
| Independence | The judge's vendor (or model) differs from every implementer profile that committed in the unit; `unknown` is never independent | `verifier.independence` | main uses the declared vendor; m12 adds the served model and its provenance |
| Fail closed | An error, refusal, timeout, invalid schema or missing capacity gives `needs_human` or `waiting_capacity`, never PASS | aggregation, availability | main |
| Non-vacuity | Zero tests, a missing report or a missing new test is a fail | gate runner | main |
| Every criterion traced | A PASS needs discriminating test evidence for each criterion | step 4, `sdd.require_traceability` | **m13 only.** On main a PASS rests on the gates, the red/green proof and one judge ("traceability: not checked (M0)") |
| Humans own product decisions | `product` and `ambiguous` questions are never auto-accepted; humans accept or reject verdict questions | `ALWAYS_HUMAN_KINDS`, m13 verdict questions | main, m13 |
| S1 never decides alone | An S1 `p` can only make clarifier auto-accept stricter (the router and citation checks are extra conditions); at step 8 it is only recorded | clarifier router; verifier step 8 | main (clarifier); m15-unwired (step 8) |

---

## 2. What each layer catches and misses

| Layer | Catches | Misses or known holes | Live evidence (`docs/live/README.md`) |
|---|---|---|---|
| Intake | Conflicting scenarios (same GIVEN and WHEN, different THEN), a missing oracle, open questions listed in `design.md` | A vague spec that defers to an unstated rule; inputs that no scenario covers | `add-vat`: the lint raised Q-001 before any agent ran (#2553). `add-is-empty`: Codex quietly decided the listed open question itself (#2593); deterministic intake then raised it (#2601) |
| Implementer TDD | Tests that never failed first; regressions; broken static gates; edits to forbidden paths | On main: weak or vacuous assertions that still fail at red, tests tied to the wrong criterion, and production edits made during red (the red-scope guard is m13) [V]. On **every branch**: a loosened gate config (`ruff.toml`, `.eslintrc*`, `package.json` scripts), because `tdd.gate_config_globs` is IGNORED [V] | `add-discount-codes`: tasks 1.1 and 1.2 went red then green, with `L4-TDD` trailers (#2530) |
| Integrity (step 1) | m13: deleted or skipped tests, a broken red→green freeze, result-forcing hooks or `addopts`, undeclared suppressions, TDD history order | Deferred: support files patching unit symbols (2.7), test-only dependencies added in green (2.8), gate config and script entries (2.9), snapshots and scope (2.11), secrets (2.12), every language except Python | main: `not_run` |
| Gates (steps 2–3) | Build, lint, typecheck and test failures; vacuous runs | Flaky tests (they are not repeated: `flaky_repeats` is IGNORED); behaviour that no test checks; UI behaviour (`m15-unwired`) | Every live PASS |
| Traceability and audit (4, 4a) | m13: criteria with no discriminating test; over-tagged tests; implementer tests that agree with a wrong implementation (the audit writes its own test from the criterion text) | At most 2 audits per round (`MAX_AUDIT_PER_ROUND`). Step 5 (non-UI generation) is not built, so an uncovered criterion becomes `needs_human` | Not live yet |
| S1 (step 8) | Nothing yet: it records `p` | — | Not live |
| LLM judge (step 9) | Spec gaps that no scenario pins down; test adequacy (m13); interactions between units | It cannot FAIL a unit or dispute a criterion: counterexamples are not executed and citations are not re-checked. On main, a diff over 120,000 characters is a hold, so that unit can never PASS (on m13 a human `accept` of the verdict question waives the hold) | `add-discount-codes`: 7/7 criteria passed, 4 **minor** spec gaps, $0.16, 33 s. `add-vat`: 3/3 criteria passed, plus a **major** spec gap (VAT is charged on the subtotal and ignores the discount merged in !1: 121.00 instead of 108.90), so the verdict was **NEEDS_HUMAN** (#2564) |
| Clarifier | Technical questions the repository answers | The tension between auto-accept precision (SC-13) and escalation rate (SC-14) | `add-average-price`: a correct answer with 3 resolving citations, rated `medium`, was escalated under `min_confidence: high` (#2553). `add-is-empty`: a context-only `design.md` citation scored 0.0, so the every-citation rule refused (#2586). After `clarifier@3` and deterministic intake, auto-accept ran end to end (#2601), **on the `llm_boolean` stand-in** |

**What follows** [I]:
* **On main, a PASS means gates, red/green proof and one independent judge.** It does not yet mean "every criterion
  has discriminating evidence". `m13` closes that gap.
* **The judge was the only layer that caught the `add-vat` defect, and all it could do was park the unit.** Until
  counterexample execution (verifier 1.5) and citation re-checks (1.12) exist, every judge objection costs a human
  touch (SC-05, SC-14).
* **Loosened gate config is the largest open tampering hole.** It is in SC-03's tampering subset, and no branch
  detects it.

---

## 3. Per-project levers

### 3.1 The levers that move outcomes

| # | Lever | Key | Default | Effect | Change it when | Status |
|---|---|---|---|---|---|---|
| 1 | Test oracle | `gates.test.command`, `.reports`, `.format` | `""`, `[.l4-out/junit.xml]`, `junit` | Required; without it, intake exits 14. Used for the baseline, red, green and step 3. A missing report fails the gate | Always set it, with a JUnit report | main. Only `junit` is parsed; other formats fail ("not supported in M0") |
| 2 | Static gates | `gates.lint`, `gates.typecheck` | `[]` | A gate that passed at the step's base must still pass at red and at green. A gate already failing at base is only a warning (`gate.static_baseline_failed`). Step 2 blocker | Always: they are cheap discriminators | main |
| 3 | Setup and build | `gates.setup`, `gates.build` | `[]` | Setup runs before the baseline and before and after every red and green agent step (skipped when HEAD has not moved), always with network, whatever `gates.network` says; a failure is a step 2 blocker | Dependency install; compiled projects | main (`build` in the verifier only) [V] |
| 4 | Gate limits | `gates.timeout`, `gates.network` | `30m`, `allow` | Per-gate timeout; `none` removes network from the gate sandbox | Slow suites; hermetic builds with cache mounts | main |
| 5 | E2E gate | `gates.e2e.*` | disabled | One spawn serves the app and runs e2e, at head and at merge-base | Web UI projects | m15-unwired. **Set `format: junit`**: the default `playwright-json`, or empty `reports`, exits 2 |
| 6 | Test paths | `tdd.test_globs` | SPEC list | main: decides whether red changed a test file and which files the red→green freeze covers. m13: also the red-scope guard, which restores red's changes outside these globs (main does not restrict red to them) | Non-standard layouts. Ruby `*_spec.rb` is **not** matched by `**/*.spec.*` [V] | main; red scope m13 [V] |
| 7 | Support paths | `tdd.test_support_globs` | SPEC list | Red may create these; they are frozen from red to green | Custom fixture or helper directories | main |
| 8 | Runner config | `tdd.runner_config_files` | SPEC list | Exempt from the red-scope restore; scanned at step 1 | Project-specific runner configs | m13 |
| 9 | Forbidden paths | `odd.forbidden_paths` | `.github/workflows/**`, `.gitlab-ci.yml`, `**/migrations/**`, `infra/**` | Agent edits there are **reverted after every step, with no error** (only a `guard.violation` event). On m13, a base→head change there is a step 1 blocker | Add sensitive directories. **Remove `**/migrations/**` if units should add migrations** | main, m13 |
| 10 | Attempts | `implementer.max_task_attempts` | `3` | When reached, `breaker.tripped` and the unit goes to `halted` | Lower it for expensive models | main |
| 11 | Judge chain | `roles.judges` (+ `profiles.<p>.vendor`) | `[]`; empty exits 2 | main uses only `judges[0]`. m12 walks the chain and falls back on a limit or a served-model mismatch | Include a vendor that no implementer uses | main, m12. On main, m13 and m15 a judge must be a `claude-code` profile (`JUDGE_ADAPTERS`; main builds only the `codex` and `claude-code` adapters); m12 adds `codex` and `opencode` judges. `backend:` judge profiles are not built anywhere [V] |
| 12 | Independence | `verifier.independence` | `different_vendor` | A judge that is not independent gives `waiting_capacity` (exit 12) | Single-vendor setups: `different_model`. Use `none` only for experiments | main, m12 |
| 13 | Audit writer | `roles.verifier_agent` | `[]` | Empty means step 4a is `not_run`. Configured but unavailable, or not independent of the implementers, gives `waiting_capacity` | Add a vendor independent of the implementers | m13. The writer must be a `claude-code` profile on m13 (`serves=JUDGE_ADAPTERS`); an `opencode` writer needs m12 [V] |
| 14 | Audit share | `verifier.audit_sample_ratio` | `0.3` | Audits `max(ceil(ratio × covered new criteria), 1)` criteria, pre-satisfied ones first and all of them even past that count; then the cap. `0` turns the step off. The audit test is written as `tests/test_l4_audit_c_<hex>_r<n>.py`, so it only works on pytest projects | Raise for high-risk domains; `0` to save cost | m13, **capped at 2 per round** [V] |
| 15 | Criteria per test | `verifier.max_criteria_per_test` | `3` | A test that traces more criteria than this is not evidence for any of them | 1–2 for fine-grained specs; raise for e2e flows | m13 (step 4); m15 (e2e) |
| 16 | Traceability | `sdd.require_traceability` | `true` | An uncovered criterion becomes `needs_human` | Keep `true` | m13. `false` only changes the reason text |
| 17 | Fix rounds | `verifier.max_fix_rounds` | `3` | Fix units per parent; `0` escalates on the first FAIL | Lower to cap spend; raise for complex units | m13 |
| 18 | Minor findings | `verifier.fix_minor_findings` | `false` | A PASS with minor findings becomes a fix unit; a spec gap becomes an ADDED regression scenario | Turn on to pin spec gaps automatically | m13 |
| 19 | Auto-accept kinds | `clarifier.auto_accept_kinds` | `[technical]` | Both the implementer's and the clarifier's kind must be in the list. An implementer kind `product` or `ambiguous` always goes to a human; the clarifier's own kind is checked only against the list | `[]` for regulated code. **Never add `product`**: it would let a clarifier-labelled `product` answer through on a question the implementer called `technical` [V] | main |
| 20 | Confidence floor | `clarifier.min_confidence` | `high` | `medium` lets correct but modestly rated answers through (the `add-average-price` case) | After audit data (SC-13) | main |
| 21 | S1 in the clarifier | `clarifier.s1_router`, `clarifier.s1_standin`, `verifier.s1.enabled` | `true`, `none`, `true` | Without a usable S1, nothing is auto-accepted. `s1_router: false` also means **nothing** is auto-accepted | Use `llm_boolean` only until a real S1 is wired | main |
| 22 | S1 thresholds | `verifier.s1.accept_threshold`, `reject_threshold` | `0.9`, `0.1` | Clarifier only: citation support ≥ accept, router p(product) ≤ reject. **The verifier does not read them** | Only from calibration data (SC-16) | main (clarifier) |
| 23 | UI paths | `verifier.playwright.ui_paths` | `web/**`, `frontend/**`, `app/**/*.tsx`, `src/**/*.vue`, `templates/**` | A criterion is UI-facing when the unit's changed files match | Match the project's layout. A Next.js `src/app/page.tsx` is not matched by `app/**/*.tsx` (globs are anchored at the repository root) [V] | m15-unwired |
| 24 | Lessons | `memory.enabled`, `max_lessons`, `max_bytes` | `true`, `40`, `12000` | Turns lessons on or off and caps the file | — | m15: `l4 lessons lint` checks the two caps; injection and curation, the only readers of `enabled`, are unwired (on main `memory` is an opaque dict) [V] |

**Effective default.** With `s1_standin: none` and no S1 backend wired, the clarifier only suggests answers and never
auto-accepts. The live auto-answer in M1.1 used `llm_boolean` [V].

### 3.2 Keys that validate but are IGNORED on every branch [V]

Setting any of these changes nothing today. A per-project config that relies on them is silently weaker than it
looks.

| Area | IGNORED keys | Deferred task |
|---|---|---|
| SDD and TDD | `sdd.scope_check`, `tdd.mode` (strict is hard-coded), `tdd.gate_config_globs` | verifier 2.11; implementer 2.18, verifier 2.9 |
| ODD intake | `odd.allowed_paths`, `odd.require_test_oracle`, `odd.bootstrap_tests`, `odd.verify_preexisting` (main hard-codes: no oracle exits 14, no bootstrap unit) | implementer 1.6, 1.7 |
| Gates | `gates.extra`, `gates.test.targeted` | verifier 3.11 (`gates.extra`); none found for `targeted` |
| Implementer | `implementer.task_grouping`, `result_repair_attempts`, `session_resume` | — |
| Verifier | `verifier.flaky_repeats`, `generate_missing_tests`, `secret_scan` (gitleaks is not on the runner), `panel.size`, `panel.tie_breaker`, `panel.pass_k` | 3.2, 2.12, 4.5, 4.6 |
| CI and locks | `ci.time_budget`, `ci.soft_deadline_margin`, `ci.max_parallel_units`, `ci.continuation`, `locks.lease` (`l4 run --time-budget` is read; the config key `ci.time_budget` is not; the only lease is a local flock with no expiry [V `vcs/locks.py`]) | M2 (remote lease refs, state-vcs-locks 1.25) |
| Budgets | all of `budgets.*`. `budget.cost` is recorded but never enforced; spend is bounded only by `max_task_attempts` × tasks and by `max_fix_rounds` [I] | implementer 1.24, 2.21–2.24, 2.30 |

Read, but unable to change a verdict yet:
* `sdd.require_traceability: false` only changes the reason text (m13).
* `verifier.s1.*_threshold` is read only by the clarifier.
* S1 step 8 records `p` and never decides (m15-unwired).

### 3.3 Code-only constants that cap a lever (changing them per project needs a patch)

| Constant | Value | Effect | Where |
|---|---|---|---|
| `MAX_AUDIT_PER_ROUND` | 2 | Caps `audit_sample_ratio`: a ratio of 1.0 still audits at most 2 criteria per round | m13 `verifier/audit.py` [V] |
| `S1_STATE_BUDGET_CAP` | 300 | Clamps `max_state_tokens` (450) for **every** S1 engine, Jev included | m15 `config/defaults.py` [V] |
| `MAX_DIFF_CHARS` | 120,000 | A longer diff adds a hold, so on main that unit can never PASS (m13: a human can waive it) | main `verifier/ladder.py` [V] |
| `MAX_FIX_TASKS` | 5 | Tasks per fix unit; the rest are listed as "not converted" | m13 `verifier/fixunit.py` [V] |
| `JUDGE_TIMEOUT_S`, judge `MAX_CALLS` | 600, 2 | Judge timeout; one schema-repair call | main |
| `MIN_QUOTE_CHARS`, `LINE_TOLERANCE`, `MAX_RANGE_LINES` | 8, 2, 60 | How citations are resolved | main `clarifier/router.py` |
| `ALWAYS_HUMAN_KINDS` | product, ambiguous | Overrides `auto_accept_kinds` for the implementer's kind only | main |
| UI generator `MAX_ATTEMPTS` | 2 | One retry | m15 `verifier/generate.py` |
| Prompt templates | in the package | `.l4/prompts/` overrides are not built | main |

Every key with its default is in `docs/SPEC.md` §3.2.

---

## 4. Eval profiles per project type (proposal)

**Mechanism (proposal).** Add `l4 init --eval-profile <name>`, which writes one of the snippets below into
`.l4/config.yaml` with its comments. That needs **no new runtime key**: the config remains the single source of truth
and is trusted only from the base branch head (L4-CFG-004). The schema is strict (`extra="forbid"`) [V], so every
snippet uses existing keys only. A line marked `# intent only` sets an IGNORED or unwired key. It validates but has
no effect today, and starts working when that feature lands.

Profile names in the snippets (`claude-opus`, `opencode-gemini`) are the SPEC §3.2 examples. They must exist under
`profiles:`: a role chain that names an unknown profile makes `l4 run` exit 2 (preflight) and fails doctor's reduced
CFG-002 (CFG-003 in the SPEC) [V]. `opencode-gemini` can only judge on m12 (see lever 11); on main, m13 and m15 it is never
reached as a judge, because they use `judges[0]` only.

The floor is the same for every profile: a JUnit test oracle, at least one static gate, a judge independent of the
implementers, and `sdd.require_traceability: true`. Profiles tune strictness and cost above that floor; none of them
removes it.

### 4.1 Python library

```yaml
gates:
  setup: ["uv sync --frozen"]
  lint: [".venv/bin/ruff check --extend-exclude .l4 ."]
  typecheck: [".venv/bin/mypy src"]
  test:
    command: ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"
    reports: [".l4-out/junit.xml"]
    format: junit
roles:
  judges: [claude-opus, opencode-gemini]   # vendors that the implementer chain does not use
verifier:
  independence: different_vendor
  max_criteria_per_test: 2                 # m13: library criteria are small and precise
  audit_sample_ratio: 0.3                  # m13 (max 2 per round)
  max_fix_rounds: 2                        # m13
clarifier:
  auto_accept_kinds: [technical]
  min_confidence: high
```

Why: the live setup was this shape (setup, lint and test gates; Codex implementing; Claude judging). Typecheck is the
cheapest extra discriminator. Two criteria per test keeps evidence specific.

### 4.2 Web app with a UI (Playwright)

```yaml
gates:
  setup: ["npm ci", "uv sync --frozen"]     # uv: the Python env with pytest-playwright for the e2e gate
  build: ["npm run build"]
  lint: ["npx eslint ."]
  typecheck: ["npx tsc --noEmit"]
  test:
    command: "npx vitest run --reporter=junit --outputFile=.l4-out/junit.xml"
    reports: [".l4-out/junit.xml"]
    format: junit
  e2e:                                      # intent only until M1.5 Stage C is wired
    command: ".venv/bin/python -m pytest e2e --junitxml=.l4-out/e2e-junit.xml"   # m15 is pytest-playwright only
    reports: [".l4-out/e2e-junit.xml"]
    format: junit                           # the default playwright-json is refused (exit 2)
    serve:
      command: "npm run start:test"
      ready_url: "http://127.0.0.1:3000/health"
      timeout: 120s
verifier:
  max_criteria_per_test: 4                  # m13/m15: one e2e flow legitimately covers several scenarios
  playwright:
    ui_paths: ["src/app/**", "src/components/**", "src/pages/**"]   # intent only; match the real layout
```

Why: `e2e/**`, `**/*.spec.*`, `playwright.config.*` and `vitest.config.*` are already in the default globs and
runner-config list, so leave them. The real per-project work is `ui_paths` and a `serve` command that boots a test
build. m15's e2e gate takes JUnit only and runs the server and the tests in one spawn with `--unshare-net`, so the app
must boot offline on loopback; the UI tests it generates are `e2e/test_l4_c_<hex>.py` (pytest-playwright), so a Node
`npx playwright test` command would never run them [V]. Until Stage C is wired, nothing writes a missing e2e test. On m13, a UI criterion with no discriminating test
is uncovered and ends up `needs_human`; on main, only the judge looks at it.

### 4.3 Data / ETL pipeline

```yaml
gates:
  setup: ["uv sync --frozen"]
  lint: [".venv/bin/ruff check ."]
  test:
    command: ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"   # data-contract checks as ordinary tests
    reports: [".l4-out/junit.xml"]
    format: junit
  timeout: 45m
  network: none                             # tests must not reach live sources; gates.setup keeps its network
tdd:
  test_support_globs: ["**/conftest.py", "**/fixtures/**", "**/testdata/**", "tests/data/**", "**/sample_data/**"]
odd:
  forbidden_paths: [".github/workflows/**", ".gitlab-ci.yml", "infra/**", "deploy/**"]   # migrations removed on purpose
verifier:
  max_criteria_per_test: 2
  audit_sample_ratio: 0.5                   # m13 (max 2 per round)
```

Why:
* ETL bugs are usually value-level (joins, rounding, null handling). An independent audit test written from the
  criterion text is the best catch for them [I].
* `gates.extra` is IGNORED, so data-contract checks belong in the test suite.
* If units add schema migrations, `**/migrations/**` must leave `forbidden_paths`, or their work is silently
  reverted.

### 4.4 Regulated or financial codebase

```yaml
gates:
  lint:
    - ".venv/bin/ruff check ."
    - "semgrep --error --config p/python ."   # here because gates.extra is IGNORED; see the note below
roles:
  judges: [claude-opus, opencode-gemini]      # m12 walks the chain; main uses judges[0] only
  verifier_agent: [opencode-gemini]           # audit writer; needs m12's opencode support (m13 alone: claude-code only)
verifier:
  independence: different_vendor
  max_criteria_per_test: 1
  audit_sample_ratio: 1.0                     # m13; still at most 2 per round
  max_fix_rounds: 2
  fix_minor_findings: true                    # m13: spec gaps become regression scenarios
  s1:
    enabled: false                            # keeps code excerpts away from a third-party API; Laya once calibrated
  flaky_repeats: 5                            # intent only
  panel: {size: 2}                            # intent only
  secret_scan: gitleaks                       # intent only
clarifier:
  auto_accept_kinds: []                       # every question goes to a human; the clarifier still suggests
```

Why and traps:
* **Do not put `billing/**`, `tax/**` or `auth/**` in `odd.forbidden_paths`.** Agent edits there are reverted with
  no error, so a unit that implements tax would silently lose its work. Risk tiers by path need a new key (§4.6).
* **semgrep in `gates.lint` runs at red and at green of every task**, and a failure that already exists at base is
  only a warning there. Verifier step 2 is stricter: any lint failure at head is a blocker, so a rule set that
  already fails on the base branch makes every unit FAIL [V]. Start from a clean base. That is acceptable for a fast
  rule set. Mutation testing does not belong there (§5.4).
* **On m13 alone, `opencode-gemini` cannot be the audit writer**: m13 serves `verifier_agent` from `claude-code`
  profiles only, so this snippet parks the unit at `waiting_capacity` whenever step 4a has a criterion to audit,
  until m12's adapters are merged [V].
* One criterion per test plus the maximum audit is the most a project can tighten today. The panel, flaky repeats and
  the secret scan are recorded as intent only.

### 4.5 Prototype or spike

```yaml
implementer:
  max_task_attempts: 2
verifier:
  independence: different_model               # a single-vendor setup is acceptable here
  audit_sample_ratio: 0                       # m13: skip the audit
  max_fix_rounds: 1
clarifier:
  min_confidence: medium                      # only matters once an S1 (or the stand-in) is usable
```

Why: this cuts cost (attempts, audit, fix rounds) and lets more technical answers through, but keeps the
deterministic floor. `min_confidence: medium` alone changes nothing while `s1_standin: none` and no S1 backend is
wired.

### 4.6 New keys worth adding (PROPOSED, not in the schema; `l4` exits 2 on them today)

| Proposed key | Replaces or adds | Why |
|---|---|---|
| `verifier.audit_max_per_round` | `MAX_AUDIT_PER_ROUND = 2` | Lets high-risk projects audit more than 2 criteria per round |
| `verifier.judge.max_diff_chars` | `MAX_DIFF_CHARS = 120000` | Large refactors can never PASS on main |
| `verifier.risk_paths: [{glob, policy: always_human}]` | — | Risk tiers by path (billing, tax, auth): no clarifier auto-accept there, and any judge finding goes to a human, without reverting edits |
| `verifier.s1.question_set: <id>@<version>` | — | Versioned question sets with project policy in the criteria (§6.4) |
| `verifier.s1.decisions.<router\|citation\|criterion>.{accept,reject}` | the global thresholds | Thresholds per decision and per project, set by calibration |
| `verifier.s1.margin` (start at 0.05) and `verifier.s1.repeats` (2, averaging both option orders) | — | Identical requests drift by up to 0.09 (§6.2) |
| `profiles.<p>.max_state_tokens` | the global `S1_STATE_BUDGET_CAP = 300` | Today the Laya cap also truncates Jev and costs accuracy (§6.2) |

---

## 5. Fitting by calibration

### 5.1 Labels the harness already writes

| Label | Meaning | Event | Branch |
|---|---|---|---|
| False auto-accept | A human overrode an `answered-by-clarifier` answer: the most expensive error | `question.override` | main |
| Suggestion quality | A clarifier suggestion `accepted` unchanged versus replaced by the human | `questions.md` status, `question.answered` | main |
| Human verdict | accept or reject on a NEEDS_HUMAN criterion or finding: **ground truth for the judge** | `human.verdict`, `human.void` | m13 |
| Audit disagreement | An independent audit test fails at head where the implementer's tests passed: a proxy for a false PASS | `verify.audit` | m13 |
| Gaming | Guard reverts and test tampering | `guard.violation`, `guard.test_tamper`, `stub.purity`, `test.untraced` | main, m13 |
| Rounds to PASS | Fix units per parent | `fix.spawned`, `fix.done` | m13 |
| Judge reliability | Repair calls, discards, served model | `verify.judge`, `availability.model_mismatch` | main, m12 |
| Cost and time | USD per role; seconds per ladder step | `budget.cost`, `verdict.json` `steps[].seconds` | main |
| S1 outcome pairs | `p` next to the deterministic and judge outcomes | `$L4_CACHE/s1-calibration.jsonl` | m15-unwired |

### 5.2 Metrics

| Metric | Definition | Source | Target |
|---|---|---|---|
| False PASS | must-catch canaries that end PASS ÷ must-catch canaries | canary `verdict.json` | SC-03: 0 of ≥ 20 on the tampering subset; ≤ 1 of ≥ 60 overall |
| False FAIL | must-pass canaries that end FAIL ÷ must-pass canaries | canary `verdict.json` | SC-04 ≤ 15 % |
| False NEEDS_HUMAN | correct units parked by verifier disputes ÷ correct units | `verify.verdict` + `human.verdict` accept | SC-14 ≤ 25 % |
| Auto-accept precision | 1 − overrides ÷ auto-accepts | `clarifier.result`, `question.override` | SC-13 ≥ 95 % |
| Escalation of correct answers | suggestions accepted unchanged ÷ escalated suggestions | `questions.md`, `clarifier.result` | Drives `min_confidence` |
| Judge agreement | judge verdict == human decision | `verify.judge`, `human.verdict` | Drives judge chain order |
| Audit disagreement | failing audits ÷ audits | `verify.audit` | Drives `audit_sample_ratio` |
| Human touches per unit | human commits and labels per unit | ledger | SC-05 ≤ 1.5 |
| Cost and time per unit | median and p90 | `budget.cost`, `steps[].seconds` | SC-11, SC-15 |
| S1 calibration | ECE of `p` against outcomes | `s1-calibration.jsonl` | SC-16: ECE ≤ 0.1, otherwise auto-accept stays off |

### 5.3 The loop (proposal)

**Trigger:** every 20 finished units per project, or weekly, whichever comes first.

1. **Collect.** Gather the ledger events, `verdict.json` per round, and the S1 logs. There is no export tool yet;
   propose `l4 calibrate`, which spends no tokens.
2. **Join labels** per (project, decision, question-set version, served model).
3. **Estimate** each metric with a 95 % Wilson interval.
4. **Decide per lever.** These are rules, not judgement calls:

| Lever | Rule [G] |
|---|---|
| `clarifier.min_confidence` | Move `high` → `medium` only when the Wilson lower bound on the precision of `medium` suggestions is ≥ 0.95 |
| S1 thresholds (per decision) | The lowest threshold whose Wilson lower bound on auto-accept precision is ≥ 0.95. Until a project has about 30 labels, use the global value; after that, blend the project's estimate with the global prior (beta-binomial shrinkage) |
| `audit_sample_ratio` | Raise it after any audit disagreement; lower it after ≥ 30 audits with no disagreement |
| `max_fix_rounds` | p90 of rounds-to-PASS among units that did pass |
| `roles.judges` order | By agreement with human verdicts, then by cost per call |
| `tdd.*_globs`, `odd.forbidden_paths` | Each `guard.violation` on a legitimate path means the glob is wrong for this layout |
| `max_criteria_per_test` | Raise it when legitimate e2e flows keep drawing the "too many criteria" minor finding |

5. **Apply through an MR to the base branch.** Config is trusted only from there (L4-CFG-004). Put the metric values
   in the MR description.
6. **Re-run the canaries** after every config change and every `l4 upgrade`.

**Sample-size reality check** [V by arithmetic]. With zero errors, the Wilson 95 % lower bound is n ÷ (n + 3.84). 30
correct auto-accepts out of 30 only proves precision ≥ 0.89. Proving ≥ 0.95 takes **73 in a row with no error**. A
single project rarely reaches that quickly, which is why per-project thresholds must borrow from a global prior and why
ECE is computed globally with bootstrap intervals.

### 5.4 Project canaries

* **Must-catch set**, seeded per project. It mirrors SC-03's tampering subset:
  * delete a pre-existing test;
  * skip a test;
  * weaken an assertion;
  * an import-only or otherwise vacuous test;
  * a result-forcing `conftest.py` hook;
  * an over-tagged test;
  * an off-by-one bug in a criterion's behaviour;
  * **loosened gate config**, which is expected to be missed on every branch today, so record it as a known miss;
  * a UI-only defect (web projects, once m15 is wired).
* **Must-pass set:** at least 5 correct units. Watch them for NEEDS_HUMAN, which is the SC-14 cost.
* **Where:** a canary branch or fork of the project (for the reference, `example-group/dummy-agentic`).
* **When:** per harness upgrade and per eval-config change.
* **Mutation testing as a gate:** it belongs in steps 6–7 through `gates.extra` (verifier 3.11), which is IGNORED. Until that lands, run
  mutmut or Stryker on changed files as a separate CI job. Do not put it in `gates.lint`, which runs at red and green
  of every task.

### 5.5 Gaps that block a full calibration loop today

* `s1-calibration.jsonl` rows (m15) have no field for the later human outcome, although L4-VER-008 already requires
  it; verifier 4.3's "fill the human outcome on merge" is not built [V]. Only the export tooling is v1.1 in the SPEC.
  ECE can only be computed against deterministic or judge outcomes, not against human ground truth.
* The clarifier's S1 calls are not written to the calibration file.
* No export tooling exists.
* The SC-03 and SC-04 benchmarks need units labelled by someone outside the system.

---

## 6. Where Jev, Laya and an LLM judge fit

### 6.1 Fit by decision

| Decision | Jev fit | Evidence |
|---|---|---|
| Criterion satisfied by its evidence (step 8) | **Good** | [V] |
| Claim-level citation grounding ("does this text show this claim?") | **Good** | [V] |
| Finding-severity triage | Promising | [V], small n, possible bias |
| Spec-ambiguity triage at intake | Promising | [V], small n, possible bias |
| Router as one yes/no "is this a product decision?" | Poor | [V] |
| Whole-answer citation support | Poor | [V] |
| A contradiction that needs one reasoning step | Poor | [V] |
| Choice confidence used as a correctness signal | Poor | [V] |

### 6.2 Measured (30 calls, `jev-1.13.0` pinned and served every time, 0 errors, 0 replies with HTTP 429)

| Property | Result |
|---|---|
| Stability | Identical requests are **not** bit-identical. 4 repeats gave 4 distinct answers. Mean standard deviation per field 0.013–0.019; largest range 0.08 on a yes/no value and 0.09 on a choice confidence. The API rounds to 0.01 |
| Latency | 251–472 ms; p50 273 ms, p90 312 ms (from the Mac, new TLS connection per call). Question count barely matters: 5 questions took 258–312 ms and 18 took 291 ms. From the runner (pipeline 2612): 272 ms |
| Tokens | 595–2,267 input tokens per request (median 985). The questions dominate: the states were about 50–140 tokens |
| Cost | $0.00134 for all 30 requests, about $0.045 per 1,000 requests. Computed, not billed: 31,922 input tokens at the published $0.042 per million input tokens; output tokens are free |
| Per unit [I] | About 10–15 calls, about $0.0007, about 3–4 s if the calls run one after another |
| Step 8 (C-5427d9c3) | Passing relevant test 0.96; **failing test 0.04**; passing but unrelated test 0.16. The 4-way choice was right in all three (implemented 1.00, contradicted 0.99–1.00, not_implemented 0.81–0.85). For comparison, zero-shot Laya scored a failing case 0.78 (research/03) |
| Router, SPEC question | Technical: **0.24**, **0.42**. Product: 0.91, 0.78. Borderline: 0.74. As a choice with criteria, p(technical) was 0.88 and 0.99 on the technical cases and 0.00 on the product cases |
| Citation, SPEC wording | Highest supportive score **0.89**, on the spec line itself. A citation that **contradicts** the answer still got 0.45. A choice question said "supports" at 0.78 for that contradiction |
| Claim-level citation | Plain question: supportive claims scored 0.92–0.97, with the "opposite" question at 0.04–0.05; a partial citation (the window that does not show `total()`) still scored 0.91, opposite 0.04. With true/false criteria: supportive 0.90–0.97, partial 0.67. A false claim scored 0.08 (criteria 0.04), opposite 0.80 |
| State cap | `S1_STATE_BUDGET_CAP = 300` applies to Jev too. The prefix cut left the wrong text: the claim-level score fell from 0.97 to 0.37–0.56 |
| Option order | Reversing the options swings the product/ambiguous split by 0.13–0.21. That is harmless if both are merged into "needs the owner" |

Jev's probabilities are calibrated for the literal sentence, not for our labels. "Decimal vs float" does change money
amounts, so a high p(user-visible) is arguably correct. Project policy therefore has to live in the question's
criteria, and thresholds have to be our own.

### 6.3 Recommended question designs and starting gates

| Decision | Design | Starting gate [G] |
|---|---|---|
| Router | One choice {technical, product, ambiguous} with what / not_for / examples criteria. Ask it in both option orders in the same request and average. Merge product and ambiguous into "needs the owner". Add yes/no `d_internal` and `d_external_fact` questions | Auto-accept only if the average p(technical) ≥ 0.85 **and** `d_internal` ≥ 0.8 |
| Citation | `l4/clarifier-answer@2`: each citation carries a `claim`. Ask "Does `cited_text` state or show `claim`?" with true/false criteria, plus an "opposite" question. Cut the cited text around the quote, sized per engine, not by prefix | Each ≥ 0.9 **and** opposite ≤ 0.2. Relevance of the claim to the answer stays with the other rules and with human or LLM review |
| Step 8 | Keep the SPEC question, add true/false criteria and the 4-way choice. Record only; it may decide only in the traceability-off row | 0.9 |
| Severity | Choice in both orders + score + "is this a spec gap?". Use it to route or order fixes, or to flag disagreement with the judge for a human; **never to FAIL** | Disagreement with the judge → human |
| Ambiguity at intake | Score + "defers to an unstated rule" + "uncovered input". Raise a question before any agent spend | Defers ≥ 0.8 or score ≥ 2.5 |

Every starting gate is a guess from one toy project with roughly one sample per cell. Values within about 0.05 of a
threshold go to a human, or are asked k = 2–3 times and averaged. On the measured cases that margin already bites: the
`is_empty` router case averages p(technical) 0.875, and one supportive claim scored exactly 0.90 with criteria [V].

### 6.4 Levers for fitting S1 per project

1. **Question sets** with a version: project policy goes into the criteria (for example, "money types are technical
   when the codebase already uses Decimal"), and examples come from the project's own answered questions.
2. **Decomposition**: atomic yes/no questions, combined in code with weights set per project.
3. **State shaping**: a token budget per engine and a relevance cut instead of a prefix cut.
4. **Thresholds per decision and per project**, set by cost. A wrong auto-accept of a product question is expensive;
   a wrong refusal costs one human review.
5. **A ±0.05 margin** and averaging over both option orders.
6. **A pinned model**, with thresholds kept per model version.
7. **Risk tiers by path** (billing, tax, auth always go to a human), via the `risk_paths` proposal.

### 6.5 Configuring Jev (when M1.5 Stage C is wired)

```yaml
profiles:
  jev:
    backend: system-one
    engine: jev
    base_url: https://api.typesafe.ai
    api_key_env: TYPESAFE_API_KEY      # masked CI variable copied from Mintkey `typesafe-jev-api-key`
    model: jev-1.13.0                  # pin it; the SPEC example and the smoke-test default say jev-latest
roles:
  s1_judge: [jev]
```

* Today this changes nothing inside a unit. On main, `roles.s1_judge` is used only by the `llm_boolean` stand-in. On
  m15, `open_s1_backend` is built, but nothing calls it, nor step 8 (`run_s1`, `record_calibration`): the router
  wiring is Stage C line 28 of the m15 plan [V].
* **Plan of record versus this proposal.** The M1.5 plan's engine is Laya on the runner (P2: `engine: laya-local`,
  maintainer override 2026-10-04, `docs/plan/m15-progress.md` on m15). Using Jev for the clarifier and step 8 is this
  document's proposal, not a decision. Jev is mock-tested in the harness and live-tested only by the smoke scripts (`scripts/dev/jev_smoke.py`,
  `scripts/runner/ci-jev-smoke.py`).
* **Key handling:**
  * The key lives in Mintkey only.
  * The CI job reads `TYPESAFE_API_KEY`, which is already in `observability.redact_env`.
  * Never put it in the repository or in `.l4/config.yaml`. SCN-CLI-05's case, a literal `api_key:` key under a
    profile, is rejected at load (exit 2, value not echoed) only because the strict schema has no such key. A literal
    key pasted into a string field such as `api_key_env:` loads without complaint [V, loader test on main], so do
    not rely on a secret check.
* **Data egress:** code and spec excerpts go to a third-party API. Redaction applies; zero data retention is
  enterprise-only. Regulated projects should keep S1 off, or use Laya.

### 6.6 Laya

* **Strengths:** local and private (nothing leaves the runner) and bit-deterministic on CPU [V, research/03].
* **Weakness:** zero-shot quality is near chance on typed decisions (0.36 against 0.32 random; the fine-tuned
  checkpoint reaches 0.766) [V, research/03]. Its window is small, which is why the 300-token cap exists.
* **Role (proposal; the M1.5 plan currently makes Laya the runner's S1 engine, §6.5):** the **calibration twin** and
  the private option. Run the same question sets on both engines in shadow mode, fine-tune Laya on the harness's own labels, and switch a privacy-sensitive project to Laya once its ECE
  passes SC-16. Do not trust any `p` before per-project calibration.

### 6.6a Never train Laya on Jev's answers (contract constraint)

TypeSafe's Master Customer Agreement §2.3(b) forbids using the Services or any Output "to perform model distillation, train a model to imitate the output of the Services, or develop … a similar or competing product or service" [V, https://typesafe.ai/legal/mca, read 2026-10-04]. So Jev output is **never** a training label for Laya (no Jev→Laya distillation, no weight tuning from Jev answers). Allowed: fine-tune Laya on the harness's **own** labels (human verdicts and overrides, deterministic outcomes such as red/green results, discriminating evidence and mutation results), tune each engine's thresholds and temperature against those labels, and score both engines separately against the same ground truth. Other providers' judge outputs (Claude, Codex) may be restricted as training data by their terms too — prefer human and deterministic labels.

### 6.7 Where an LLM judge is still needed

* **Finding spec gaps.** Both live finds came from the judge: four minor gaps on `add-discount-codes`, and the major
  VAT-ignores-discount gap on `add-vat`. S1 answers questions; it does not discover them.
* **Test adequacy.** "Does this test check the criterion's observable outcome?"
* **Counterexamples and multi-step reasoning**, including whether a cited claim is relevant to the answer.
* **New findings that need a severity.** Jev's severity triage may route or order them, never decide them.

### 6.8 Risks

* **A small, possibly biased sample.** One toy project, mostly single samples, and the definitions were written
  knowing the cases.
* **Not tested:** prompt injection planted in spec or code text, a Laya rerun with the new questions, and latency
  inside the harness's own HTTP client.
* **Availability.** Rate limits change without notice. S1 must stay an optional, fail-closed role and never the only
  gate.

---

## 7. Recommended next steps

| # | Step | Why | Milestone | Versus the plan |
|---|---|---|---|---|
| 1 | Merge m13 (traceability, integrity, audit, verdict questions, fix units) | Makes a PASS mean "every criterion has discriminating evidence"; produces `human.verdict` labels | M1.3 | As planned |
| 2 | **Redesign the router and citation questions before wiring S1 into the clarifier** | Otherwise a real S1 turns auto-accept off (§6.2) | M1.5 Stage C (router line 28) | Change |
| 3 | Add choice/score support to `SystemOneBackend.ask` (yes/no only today), a state budget per engine with a relevance cut, a pinned model, and the served model plus question-set hash in `clarifier.result` and in the calibration rows | Needed by every design in §6.3, and to calibrate per model version | M1.5 | Change |
| 4 | Wire step 8 (`run_s1`, `record_calibration`) as record-only | Starts the SC-16 data set | M1.5 | As planned |
| 5 | Counterexample execution (verifier 1.5) and citation re-checks (1.12) | Without them a judge can only block a PASS, so every objection is a human touch (SC-05, SC-14) | M2 | **Pull forward** to an M1.3 follow-up |
| 6 | Enforce `tdd.gate_config_globs` (implementer 2.18, verifier 2.9) | Closes a hole in SC-03's tampering subset | M2 | **Pull forward** |
| 7 | `flaky_repeats` (verifier 3.2) and the secret scan (2.12, after installing gitleaks on the runner) | Flaky tests and secrets are in the SC-03 benchmark | M2 | As planned |
| 8 | `gates.extra` (verifier 3.11) | Enables mutation and semgrep gates at steps 6–7 | M2 | As planned |
| 9 | Enforce `budgets.*` (implementer 1.24, 2.21–2.24, 2.30) | SC-08; spend is bounded only indirectly today | M2 | As planned |
| 10 | Doctor check: warn when a non-default value is set on a key that nothing reads (proposal) | Stops per-project tuning from being silently ignored (§3.2) | Any; best with M1.4 doctor work | New |
| 11 | Turn the code constants into config (`audit_max_per_round`, `judge.max_diff_chars`, `max_state_tokens` per engine) | They cap levers projects need (§3.3) | M1.3, M1.5 | New |
| 12 | `l4 calibrate` (export and join); the human-outcome fill in `s1-calibration.jsonl` (verifier 4.3); log the clarifier's S1 calls | Without these the §5.3 loop cannot run | Export: v1.1 in the SPEC; human outcome: L4-VER-008, not built | Pull forward |
| 13 | `l4 init --eval-profile <name>` with the §4 presets | Per-project fit without new runtime keys | M1.4 or M2 | New |
| 14 | A canary benchmark on `example-group/dummy-agentic` (must-catch and must-pass) | SC-03 and SC-04 baseline; re-run on every upgrade | Before M2 sign-off | New |
| 15 | Rotate the Jev key; keep it only in Mintkey and the masked CI variable | It was pasted in a chat | Now | — |
| 16 | Copy the raw Jev results (`results.jsonl`, with no key) and the experiment scripts from the session scratchpad into `docs/research/` | The §6.2 numbers then have a durable source | Follow-up | — |

### SPEC changes these steps need

* **L4-CLR-002 rule 4 and L4-CLR-003.** Replace the router's single yes/no question with the choice design. Replace
  "Does `cited_text` support `answer`?" with claim-level questions plus an "opposite" check. Bump
  `l4/clarifier-answer` to `@2` with a per-citation `claim`.
* **§3.2.**
  * Add the `remote` engine (new in m15).
  * Make `max_state_tokens` per engine.
  * Change the Jev example to a pinned model.
  * Mark the IGNORED keys as "reserved, no effect until <milestone>".
  * Add the §4.6 keys that are accepted.
* **§10.2 step 8.** Add true/false criteria and the 4-way choice to the question; keep it record-only.
* **L4-VER-008.** Add the served model and the question-set hash to each calibration row (it already requires the
  later human outcome; m15's row has a `model` field filled by the caller). Move the export tooling from v1.1 to M2.
* **§15.** Add a doctor check for keys that have no effect.
* **§2.1.** Add `l4 init --eval-profile`.

---

### Sources

* **Levers inventory:** a per-key grep of `src/l4/**/*.py` on main, m12, m13, m14 and m15 (schema and defaults
  excluded), with every hit checked by eye. Spot-checked again for this doc: the IGNORED hits are docstrings only, and
  the code constants and `extra="forbid"` were confirmed [V].
* **Jev experiments:** 30 calls on 2026-10-04 (raw files are still in the session scratchpad; see step 16).
* **Repository documents:** `docs/live/README.md` (live runs M0 and M1.1), `docs/runner/README.md` (Jev smoke test,
  pipeline 2612), `docs/research/03-eval-verification.md` (Laya), `docs/SPEC.md` §3.2, §10 and Part II (SC-01 to
  SC-17), and `docs/plan/m12-plan.md` to `docs/plan/m15-plan.md`.
