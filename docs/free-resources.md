# Free resources for L4 roles: inventory, measurements and free-first role chains

Status 2026-10-06 (UTC). Runner `l4-runner`, harness `ff371c5`, dummy-agentic (118) vendored at `28b8cc3`.
Labels: **[V]** checked today (a probe, a run, a log or the code), **[doc]** vendor docs (URL given, fetched
2026-10-06), **[I]** inferred, **[U]** unknown.

Sources: the inventory [runner/free-inventory-2026-10-06.txt](runner/free-inventory-2026-10-06.txt), the role
measurements [live/free/README.md](live/free/README.md), and the code reads cited inline.

## 1. Verdict

* **Use free models first where a wrong answer is checked again; keep Claude first where it is not.**
  * Free first: the **implementer** (the gates and an independent judge check every unit), the **clarifier** and the
    **S1 stand-in** (product and ambiguous questions go to a human anyway, and the S1 router gates every
    auto-accept).
  * Claude first, two free fallbacks: the **judges** and the **verifier agent** (audit writer). The judge is the
    last check before a human merges. Free audit tests were never measured.
* **Applied to dummy-agentic** at `a38d799` (section 5). The push pipeline 3227 was green: `l4` job 5849 reported
  `nothing to do`, and doctor reported all 5 free profiles `ready` [V].
* **First free-implemented unit in CI.** The seed `add-tip-amount` ran through the new chains in `l4` job 5851 [V]:
  * Muse Spark implemented red (20 s) and green (15.5 s) at $0;
  * Laya judged both criteria in step 8;
  * Claude judged PASS 2/2 with 2 minor spec-gap findings ($0.0656);
  * MR !35 is `l4:in_review`, and the run took 178 s.
* **Laya local is free and works on the runner today.** The inventory row "blocked, would crash with SIGILL" was an
  untested inference and is wrong: job 5851's step 8 reads "2/2 criteria judged by laya-local" in 31 s [V].
* **sample-consumer is not changed.** Section 6 has a recommended block for the maintainer. Its current fallback,
  Big Pickle, may use the data it receives to improve the model [doc]. The block replaces it with LongCat, which has
  zero retention.
* **Defaults of `l4 init`.** A new repository gets a Laya profile as `roles.s1_judge` (free, local, no key). `--s1 jev`
  writes a Jev profile that reads `TYPESAFE_API_KEY`, and `--s1 none` writes neither. The hosted-runner cost of Laya and
  the Jev rows measured on a consumer are added after the live run of adoption-lessons 9.3.
* **More free capacity needs the maintainer** (section 8):
  * a Zen API key: Jev 1.13 Free as System One;
  * an `opencode auth login` for OpenRouter `:free` models and for Gemini;
  * a Kiro login, as an implementer fallback. It needs a harness change first, so that the login file is hidden
    from other agents' sandboxes.
* **Copilot and Cursor add almost nothing.** The harness can run them only through the `command` adapter, which
  implements and never judges. On their free plans the model, and so the vendor, is chosen for you, and an implementer
  of unknown vendor vetoes every judge [V].

## 2. Inventory (what is free, what works on the runner today)

Zen terms below are quoted from https://opencode.ai/docs/zen, fetched 2026-10-06 [doc]. Every Zen free model is
"available on OpenCode for a limited time". Zen publishes no rate limits, no quota endpoint and no rate-limit headers
for free models [doc, V].

| Resource | Free? Data terms (cite) | Vendor for independence | Works on the runner today? | Hello |
|---|---|---|---|---|
| `opencode/muse-spark-1.3-contributor-free` | yes; "permission to use your prompts and completions to train future Meta models" [doc] | meta [doc] | yes, no login | PASS 5.0 s |
| `opencode/mimo-v2.6-flash-free` | yes; "collected data may be used to improve the model" [doc] | xiaomi [I, name] | yes | PASS 9.0 s |
| `opencode/nemotron-3-ultra-free` | yes; "Trial use only — do not submit personal or confidential data. Your use is logged" [doc] | nvidia [doc, "NVIDIA free endpoints"] | yes | PASS 10.1 s |
| `opencode/longcat-2.5-preview-free` | yes; "zero-retention policy and does not use your data for model training" [doc] | meituan [I, name] | yes | PASS 7.2 s |
| `opencode/space-bunny-free` | yes; stealth model, zero retention [doc] | **unknown** (stealth) | yes | PASS 3.9 s |
| `opencode/big-pickle` | yes; stealth model, "collected data may be used to improve the model" [doc] | **unknown** (the dummy's `zhipu` is a guess) | yes | PASS 6.6 s |
| `opencode/nemotron-3.5-lightning-free` | yes; NVIDIA terms as above [doc] | nvidia [doc] | answers, but fails the output schema (section 3) | PASS 4.8 s |
| `opencode/ling-3.1-flash-free` | yes; "may be used to improve the model" [doc] | inclusionai [I, name] | answered the hello; HTTP 429 "Endpoint is unavailable" in its first real step | PASS 8.3 s |
| `opencode/fledge-alpha-free` | yes [doc] | unknown | **no**: 403 "not available in your country" | FAIL |
| `opencode/ling-3.0-flash-fin-free` | yes [doc] | inclusionai [I] | **no**: 400 "Endpoint is unavailable" | FAIL |
| Jev 1.13 Free (`POST https://opencode.ai/zen/v1/systemone`, `jev-1.13-free`) | yes; "Prompts and other inputs are not used for training" [doc]. The docs say to use a Zen API key | typesafe | answers **without** a key [V], but the harness `jev` engine refuses to start without a key (`system_one.py:539-542`) | HTTP 200, 0.81 s |
| Jev paid (TypeSafe key, in Mintkey) | no: $0.042 per M input tokens (https://docs.typesafe.ai/models) | typesafe | yes, already the dummy's S1 shadow | 296 ms, ≈ $0.000015 per call |
| Laya local (`laya-serve` 0.3.24, `typed-decisions`) | free (own CPU), local: no data leaves the runner | convai | **yes** [V]: job 5851 step 8, "2/2 criteria judged by laya-local", 31 s, and doctor ENV-006 "laya 0.3.24, checkpoint typed-decisions cached". The inventory's "blocked, would SIGILL" (no AVX in the guest) was not run and does not hold | – |
| magnitude (Mac, 192.0.2.10:10100, Qwen3.6-35B-A3B) | free (own hardware), only while the Mac is on | alibaba (qwen) [I] | provider injection works since `15e26a0` (probe ready, hello 30.7 s in CI), as implementer it halted on the result path with harness `84ff7cb` and **passed a unit with M1.13's `.l4-result` alias** (`481057a`), after two enum-error attempts (section 11.2) | PASS 7.3 s outside the harness; 30.7 s in CI |
| OpenRouter `:free` models (16) | yes: 20 requests per minute, 50 per day under 10 credits purchased, 1000 per day at 10 or more (https://openrouter.ai/docs/api/reference/limits). A negative balance gives 402 "including for free models" [doc]. The existing account allows 1000 per day [V] | per model id (google, nvidia, …) | **no**: needs `opencode auth login` on the runner (section 8) | not run |
| Gemini API free tier (AI Studio key) | yes, but "content used to improve our products" (https://ai.google.dev/gemini-api/docs/pricing) | google | **no**: needs `opencode auth login` | not run |
| Kiro CLI, Kiro Free | 50 credits/month, Claude Sonnet 4.5 plus open-weight models, "subject to rate limits" (https://kiro.dev/pricing/) | the pinned model's vendor (anthropic for Claude Sonnet), not "amazon" [I]; the dummy pins `glm-5`, vendor `zhipu` | **yes since 2026-10-08** [V]: 2.28.0 (`prereqs.sh` PRQ-12), `gitlab-runner` logged in (Builder ID, KIRO FREE); implemented a 2-leaf Kiro unit in CI (section 14). The `kiro-cli` adapter can only implement: it is not in `JUDGE_ADAPTERS` (`llm/agent_judge.py:30`) [V] | PASS 5.3 s (job 6146) |
| GitHub Copilot CLI, Copilot Free | an "allowance", amount not stated; automatic model choice (https://docs.github.com/en/copilot/get-started/plans) | **unknown** (auto model) | **no**: not installed, needs a login. Through the `command` adapter it could only implement, and an implementer of unknown vendor vetoes every judge [V], so the harness cannot use it while the model is chosen automatically | – |
| Cursor CLI, Hobby | "Limited Agent requests" (https://cursor.com/pricing) | **unknown** unless a model is pinned [U] | **no**: not installed, needs a login. `command` adapter, so implementer only, as for Copilot | – |
| Gemini CLI | **no longer free** with a Google login since 2026-06-18 (https://developers.google.com/gemini-code-assist/resources/privacy-notice-gemini-code-assist-individuals) | – | skip | – |
| Qwen Code | **no**: the OAuth free tier was discontinued 2026-04-15 (https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/) | – | skip | – |
| Aider | the tool is free; it adds nothing over OpenCode | – | skip | – |
| Codex (ChatGPT Plus) / Claude Pro | flat rate, already paid; the scarce resource is their usage windows | openai / anthropic (tool) | yes | – |

## 3. Measurements (2026-10-06, details in [live/free/README.md](live/free/README.md))

The runs used real L4 code paths on the runner (adapter, bubblewrap, gates, judge, independence, ledger) with a local
forge. Every unit was a **single-task toy unit** of the dummy.

**Implementer**, one unit per model, Claude as the judge:

| Model | Unit | Result | Wall | Claude verdict |
|---|---|---|---|---|
| Muse Spark 1.3 | reorder-quantity | PASS, red and green on attempt 1 | 107 s | PASS 2/2, 3 minor |
| Space Bunny | shelf-code | PASS, attempt 1 | 107 s | PASS 2/2, 3 minor |
| MiMo V2.6 Flash | tip-amount | PASS, attempt 1 | 127 s | PASS 2/2, 2 minor |
| Big Pickle | tip-amount | PASS, attempt 1 | 143 s | PASS 2/2, 2 minor |
| LongCat 2.5 Preview | reorder-quantity | PASS, attempt 1 | 227 s | PASS 2/2, 3 minor |
| Nemotron 3 Ultra | tip-amount | PASS, attempt 1 (187k tokens in) | 246 s | PASS 2/2, 1 minor |
| Nemotron 3.5 Lightning | shelf-code | **halted** after 3 red attempts: result schema ×2, untagged tests ×1 | 1,625 s | – |
| Ling 3.1 Flash | shelf-code | **429** in the first step ("Endpoint is unavailable") | 272 s | – |

**Judge**: the free model as the only judge, on two units with known Claude verdicts:
* `add-pickup-notice`: PASS, 0 findings.
* `add-shipping-fee` round 1: NEEDS_HUMAN, 2 major findings.

| Judge | pickup | shipping-fee | Both defects found |
|---|---|---|---|
| Muse, Space Bunny, Big Pickle, MiMo, Nemotron Ultra, LongCat | agree | agree | 2/2 each (Big Pickle merged them into one finding) |
| Nemotron Lightning | no verdict (schema_invalid twice) | no verdict | its discarded replies under-graded both defects |

The six that agree went **12 of 12 against Claude, but on n = 2 units** and one known defect pattern. That is too
little to tell a 95 % judge from a 70 % one. MiMo, Nemotron Ultra and LongCat tagged the defects "spec gap". That tag
changes the wording of the human's question and lets a fix unit take its scenario from the suggested fix
(`verifier/fixunit.py:121`, `verifier/verdicts.py:463`). It does not change the verdict [V, code].

Not measured: free models as audit writer, as clarifier or as S1 stand-in; implementer fitness on multi-file units.

## 4. How the harness treats a free profile (the constraints the chains are built on)

### 4.1 Vendor independence (judges and verifier agent)

* Where a vendor comes from, in order (`availability/vendor.py`) [V]:
  1. a served model id the adapter reports;
  2. the tool, for codex and claude-code;
  3. the profile's `vendor:` (**declared**);
  4. otherwise unknown.

  OpenCode run mode reports no served model, so every free profile is `declared`. A verdict that involves one reads
  `independence: declared (unverified)`. A Codex-implements, Claude-judges pair stays `verified`.
* A judge, and the verifier agent, which goes through the same `select_judge` (`verifier/ladder.py`, `writer_for`), is
  vetoed when its vendor equals the vendor of **any** implementer profile of the unit, or when either side's vendor is
  unknown (`verifier/selection.py`, `independence_constraint`) [V]. Consequences:
  * **A free implementer must carry a known `vendor:`.** With none, or with `unknown`, every judge is vetoed: `no
    independent verifier`, and the unit waits.
  * **Placeholder vendors are fiction.** `undisclosed-big-pickle` and `undisclosed-space-bunny` read as two different
    vendors and as different from anthropic. So the stealth models are kept out of the roles with an independence rule.
    Space Bunny is declared `vendor: stealth` and used only by the clarifier (and, in the sample-consumer block, the
    S1 stand-in).
  * **Two free judge fallbacks of different vendors.** One of them is always independent of a free implementer.
  * **Do not delete a profile that a ledger may name.** A missing profile resolves to no vendor and vetoes every judge
    of that unit. `opencode-free` stays defined in the dummy, outside every chain.
  * Already true before this change: a verify of a unit whose ledger records no implementer falls back to the
    whole `roles.implementer` chain (`ladder.py:1063`). Both the old and the new dummy chains cover every judge vendor,
    so such a unit has no independent judge.
* The clarifier and `s1_judge` have no independence rule (`Factory.for_role` without constraints) [V]. The
  recommendation still gives the S1 stand-in a different vendor than the clarifier's first profile, so that S1 never
  checks its own model's answer.

### 4.2 What falls through to the next profile, and what does not

| Event | Role | What happens [V, code] |
|---|---|---|
| HTTP 429 or another limit | any | cool-down until the limit's reset, else `availability.default_cooldown` (30 min); credits: 24 h. The next profile of the chain is selected (`Factory.on_limit`). The cool-down lives in `$L4_CACHE/availability.json` on the runner, so later jobs skip the profile too |
| limit in the middle of an implementer task | implementer | `_fall_back`: uncommitted changes are discarded, a red commit stays, and the task continues with the next profile in a fresh session. Every profile that authored commits counts for independence |
| judge limit, `model_mismatch` or `error` (a rejected tool call, a 5xx) | judges | the next **independent** judge is asked (`_ask_judges`) |
| judge reply that fails the schema twice (`schema_invalid`) | judges | **no fall-through**: the unit is held (NEEDS_HUMAN) and Claude is never asked. This happened to Nemotron Lightning |
| 3 failed attempts on a task (`max_task_attempts`) | implementer | **no fall-through**: the unit halts, and a person resumes it. Codex is not tried |
| failed hello | any | cached for the 15-min probe TTL (finding K1), so the profile is skipped for that long |

So "free first, Codex as fallback" holds only for limits. A free model that is available but not good enough costs a
halt, not a Codex retry. Routing by unit size or risk ("free for small units") cannot be expressed: a chain is global
per repository [V, `RolesCfg`].

### 4.3 Rate-limit handling

* **Harness.** A 429 is a `rate_limit` with a 30-min cool-down, and the chain walks on. No configuration is needed.
* **Zen.** Zen shows no quota and no rate-limit headers, so the quota step is skipped for `opencode/*` models
  (`probe_opencode`) [V]. The only signal is the 429 itself. Ling's 429 had the body "Upstream request failed:
  Endpoint is unavailable". That is an outage, not a quota (finding H3), but cooling it for 30 min is still the right
  action.
* **Geo-blocks.** Fledge Alpha's 403 `FreeTierError` "not available in your country" is classified as `auth`, which
  points at a login instead. Fledge stays out of every chain.
* **Concurrency.** `ci.max_parallel_units: 2` can send two units to the same free model at once. The second one walks
  on after its 429.
* **OpenRouter pitfall.** With `OPENROUTER_API_KEY` set as a CI variable, the quota probe requires a credit balance
  of at least `availability.min_remaining_usd` ($0.50). Below that, **`:free` models are cooled for 24 h as
  `credits`** (`availability/quota.py`, `openrouter_quota`) [V]. Keep $0.50 or more of credit, or leave the variable
  unset (the quota step is then skipped). The probe does not read `free_model_daily_requests`, so the daily cap of
  1000 only shows up as 429s.
* **Experiments vs production.** For measurements the rule is "stop on a 429": no further calls to that model, and a
  second model with a 429 ends the experiment. In production the chain handles it.

## 5. Recommended chains: dummy-agentic (applied)

The dummy holds no private code (a toy pricing library), so the Muse (training), Nemotron (logged) and MiMo (may
improve) terms are acceptable there.

```yaml
profiles:
  # codex, claude-code, kiro, laya, jev: unchanged
  opencode-free:            # kept: older ledgers may name it; in no chain
    adapter: opencode
    model: opencode/big-pickle
    vendor: zhipu
  f-muse:            {adapter: opencode, model: opencode/muse-spark-1.3-contributor-free, vendor: meta}
  f-mimo:            {adapter: opencode, model: opencode/mimo-v2.6-flash-free,            vendor: xiaomi}
  f-nemotron-ultra:  {adapter: opencode, model: opencode/nemotron-3-ultra-free,           vendor: nvidia}
  f-longcat:         {adapter: opencode, model: opencode/longcat-2.5-preview-free,        vendor: meituan}
  f-space-bunny:     {adapter: opencode, model: opencode/space-bunny-free,                vendor: stealth}
roles:
  implementer:    [f-muse, f-mimo, f-nemotron-ultra, f-longcat, codex, claude-code]
  judges:         [claude-code, f-longcat, f-muse, codex]
  clarifier:      [f-longcat, f-space-bunny, claude-code, codex]
  s1_judge:       [laya, f-muse, claude-code]
  verifier_agent: [claude-code, f-longcat, f-muse]
```

### 5.1 Why each chain

| Role | Chain | Reasoning |
|---|---|---|
| implementer | Muse, MiMo, Nemotron Ultra, LongCat, then Codex, then Claude | It uses the most tokens: 20k–190k per unit against about 7k for a judge call. All four passed their unit on the first attempt, and they are ordered by wall time. They are all named-vendor, so independence stays meaningful. The gates and Claude's judge check every unit, so a weaker implementer costs time (a halt), not a wrong merge. Codex runs only when all four are cooling. Left out: Nemotron Lightning (schema halts), Ling (429), the stealth models (no real vendor), Fledge and Ling Fin (unavailable). |
| judges | Claude, then LongCat, then Muse, then Codex | Claude stays the last word, because an invalid free reply does not fall through (4.2) and 12/12 on n=2 is not enough evidence. LongCat comes first among the free fallbacks because it is the free fallback independent of the first implementer (Muse is meta, LongCat meituan). Muse covers the case where LongCat implemented, and Codex is allowed whenever a free model or Claude implemented. Claude's 403s (job 5800, the sample-consumer org block) are exactly when the fallbacks are used. |
| clarifier | LongCat, then Space Bunny, then Claude, then Codex | No independence rule. An answer is auto-accepted only when it is technical, at medium or better confidence, with citations that resolve and the S1 router's support. Product and ambiguous questions always go to a human. LongCat has a 1M-token window for repository context. Unmeasured [U]. |
| s1_judge | laya, then Muse, then Claude | A usable `system-one` profile comes first (`clarifier/router.py`, `build_s1_judge`). Laya is free and local, and it runs (5.3), so it serves step 8 and the clarifier's S1 router. The `llm_boolean` stand-in, the first adapter profile, is used only when Laya cannot open: that is Muse, a different vendor than the clarifier's LongCat. A Zen key would add `jev-free`, which reads a larger state than Laya (section 8). The stand-in is unmeasured [U]. |
| verifier_agent | Claude, then LongCat, then Muse | Free audit tests were not measured. The guards (an audit test must pass at head and fail against zero values, `verifier/audit.py`) stop a useless test, but not one that mirrors a wrong implementation: the writer sees the head source. Claude stays first until it is measured (section 7, item 2). |

### 5.2 Live check in CI

* **Config push.** `a38d799` was pushed to `main` by CiprianSpot, as the human. Pipeline 3227 passed: `test` 5848,
  and `l4` 5849 with `[l4] run: nothing to do: no unit has a next step`. Doctor in the job: `CFG-002 pass`, and
  `PRV-001`: f-longcat, f-mimo, f-muse, f-nemotron-ultra and f-space-bunny all `ready`
  ([live/free/chains/push-a38d799-l4-job-5849.txt](live/free/chains/push-a38d799-l4-job-5849.txt)) [V].
* **One unit through the new chains.** `b398e14` seeded `add-tip-amount` on `main`. MiMo, Big Pickle and Nemotron
  Ultra had implemented this seed locally; this time it was Muse, in CI.
* **Comment fix.** `d4d66e3` corrected the `s1_judge` comment: Laya is not blocked. Pipeline 3236 passed, with `l4`
  job 5854 reporting `nothing to do`; the 21:33Z schedule pipeline 3237 passed too
  ([live/free/chains/push-d4d66e3-l4-job-5854.txt](live/free/chains/push-d4d66e3-l4-job-5854.txt)) [V].

### 5.3 Result of the seed run (pipeline 3228, `l4` job 5851, run `r-20261006T2127Z-001c`)

Log: [live/free/chains/seed-add-tip-amount-l4-job-5851.txt](live/free/chains/seed-add-tip-amount-l4-job-5851.txt) [V].

| Step | Result |
|---|---|
| implementer selection | `f-muse ok (binary 1.18.34 · auth skipped · quota skipped · hello 3.7s) → selected` |
| red | 20.0 s; 2 new tests failing as expected; red commit `b68c82f`; MR !35 opened as a draft |
| green | 15.5 s; 22/22 tests and lint pass; `tip_cents` is `(total_cents * percent + 50) // 100`; commit `e6d0c30`; cost $0.0000 |
| judge selection | `claude-code ok (… quota 9% used (weekly (all models)) · hello 4.3s) → selected` |
| gates | setup, lint, test 22/22, e2e 2/2 pass |
| step 8, S1 | `s1_judge: laya ok → selected`; 2/2 criteria judged by laya-local in 31.0 s (S1 p 0.66 each) |
| step 9, judge | claude-code (served `claude-opus-5-5`), 1 call, 16.4 s, $0.0656 |
| verdict | **PASS**, round 1, 2/2 criteria, 2 minor spec-gap findings: negative totals round toward +infinity, and float inputs are not rejected |
| independence | `declared (unverified): claude-code anthropic (served claude-opus-5-5), f-muse meta (declared)`, as predicted in 4.1 |
| hand-off | MR !35 `l4:in_review`; run exit 0 in 178.4 s; total cost $0.0656, all of it Claude's |

Not exercised by this unit: audit sampling (`audit_sample_ratio: 0`), UI test generation (no UI path changed), the
clarifier (no question), any 429.

## 6. Recommended block for sample-consumer (not applied: the maintainer decides)

sample-consumer is the owner's private code, and its units are multi-file. Free models are proven only on
single-task toy units, and a free halt costs the owner a resume. So:
* Codex stays the first implementer.
* Only the two **zero-retention** free models are used: LongCat (named vendor) and Space Bunny (stealth, so only in
  the roles without an independence rule).
* The current fallback, `opencode-free` (Big Pickle, "collected data may be used to improve the model"), leaves every
  chain. Its profile stays defined, because MF-3's ledger names it as a judge. Only implementer profiles count for
  independence, but keeping it is harmless.

```yaml
profiles:
  # codex, claude-code, opencode-free: unchanged (opencode-free kept for old ledgers, in no chain)
  laya:                     # System One on the runner's own CPU: free, and no data leaves the runner
    backend: system-one
    engine: laya-local
    model: typed-decisions
    vendor: convai
  f-longcat:                # zero retention per OpenCode Zen; vendor inferred from the model name
    adapter: opencode
    model: opencode/longcat-2.5-preview-free
    vendor: meituan
  f-space-bunny:            # stealth, zero retention per OpenCode Zen; only in roles without the independence rule
    adapter: opencode
    model: opencode/space-bunny-free
    vendor: stealth
roles:
  implementer:    [codex, f-longcat]                 # LongCat only when Codex is cooling (a limit), never after a halt
  judges:         [claude-code, f-longcat, codex]    # was [claude-code, opencode-free]; codex judges a LongCat unit
  clarifier:      [f-longcat, f-space-bunny, claude-code]
  s1_judge:       [laya, f-space-bunny, claude-code] # Laya first (step 8 and the S1 router); then the llm_boolean stand-in
  verifier_agent: [claude-code, f-longcat]
```

What it changes for the owner:
* Big Pickle no longer sees the project.
* Laya gives step 8 and the clarifier's S1 router a real System One, on the runner, at no cost. Adoption left it out
  together with Jev, but only Jev sends text off the runner. It needs about 2.5 GB of free memory next to the job
  (runner README, M1.5 probe).
* Implementer questions are answered by LongCat first. This sends code excerpts to a zero-retention provider, the same
  exposure class as today's Claude fallback.
* A Codex limit no longer parks a unit: LongCat continues it, and Claude judges.

Move LongCat to the first implementer only after it has passed several dummy units in CI and one small
sample-consumer unit by hand.

## 7. When to promote a free model further

1. **Free primary judge.**
   * Replay at least 10 known verdicts (at least 3 of them non-PASS) per candidate, with the method of
     [live/free/README.md](live/free/README.md): byte-identical prompts.
   * Promote at 0 false PASS, at least 90 % verdict agreement and 0 schema failures.
   * Or first make the harness walk to the next judge on `schema_invalid` (section 9). With that, a free primary judge
     risks only a false PASS, not a stranded unit.
2. **Free audit writer.**
   * Re-verify `add-shipping-fee` at `231f341` with `generate_missing_tests: true`, a free judge and each free
     `verifier_agent`.
   * Compare each accepted audit test with Claude's M1.3 test `tests/test_l4_audit_c_1b1fbe16_r1.py`.
   * Promote when the tests are accepted for the right reason, from the criterion text, not by mirroring head.
3. **Free implementer for sample-consumer**: as in section 6.

## 8. Maintainer actions that unlock more free resources

The harness and the agents never log in (runner README, "Authentication"). The agent's environment carries **no
credential variable** (`sandbox/env.py` `build_agent_env`, `availability/probes.py` `probe_env`) [V]. So a provider key
in a CI variable does **not** reach `opencode run`. An OpenCode provider must be logged in on the runner, where its
login lands in `~/.local/share/opencode/auth.json`. That directory is already hidden from the other agents'
sandboxes (`config/defaults.py` `CREDENTIAL_PATHS["opencode"]`) [V]. (The runner README row "for hosted models add
`OPENROUTER_API_KEY` as a masked CI variable" is therefore wrong for the run itself: that variable only feeds the
quota probe.)

| Unlocks | Precondition | Exact maintainer action | Then (agent) |
|---|---|---|---|
| **Jev 1.13 Free as System One** (s1_judge, step 8, the clarifier's S1 router) | none | Sign up at https://opencode.ai/zen and create an API key. Turn off auto-reload ("If your balance goes below $5, Zen will automatically reload $20") or set a monthly limit. Store the key as a **masked** CI variable `OPENCODE_API_KEY` on dummy-agentic (118) | add `jev-free: {backend: system-one, engine: jev, base_url: https://opencode.ai/zen, model: jev-1.13-free, api_key_env: OPENCODE_API_KEY, vendor: typesafe}` and `s1_judge: [jev-free, laya, f-muse, claude-code]` on the dummy. Jev reads the full 450-token state; Laya is capped at 300 (`S1Cfg.budget`), and the cap measurably cost accuracy (eval-framework 6.2). Jev sends the state off the runner, but its inputs are "not used for training" [doc]. The key is redacted because it is named by `api_key_env` (`config/redaction.py`). Untested end to end [I]: the engine sends `Authorization: Bearer <key>` to `<base_url>/v1/systemone` (`system_one.py`), the form the Zen docs' curl example uses [doc] |
| **OpenRouter `:free` models** (16 models, named vendors; 20/min, 1000/day across the account) | none | Create a **separate** key at https://openrouter.ai/settings/keys (`OPENROUTER_API_KEY` belongs to Hermes, and the daily count is per account [I]). Keep the balance above $0 (402 otherwise). On the runner: `sudo -u gitlab-runner -H bash -lc 'opencode auth login'`, choose OpenRouter, paste the key | add profiles `openrouter/<vendor>/<model>:free` with their vendor. Leave `OPENROUTER_API_KEY` unset in CI, or keep at least $0.50 of credit (4.3) |
| **Gemini API free tier** (Flash, low-stakes roles; Google may use the content) | none | Create a key at https://aistudio.google.com/apikey. On the runner: `sudo -u gitlab-runner -H bash -lc 'opencode auth login'`, choose Google, paste the key | `opencode models google` as gitlab-runner gives the exact id [U]; `vendor: google`; dummy only |
| **Kiro Free** (50 credits/month) | **done** (2026-10-07/08): the token store is in `CREDENTIAL_PATHS["kiro-cli"]` (K2), and `prereqs.sh` updates kiro-cli to 2.28.0 or newer | done: `gitlab-runner` is logged in (Builder ID). Never copy a Kiro login | **done on the dummy** (section 14): profile `kiro` pins `glm-5`/`zhipu` and sits in `implementer` after `magnitude-qwen`, before `codex` |
| **GitHub Copilot CLI** (Copilot Free) | harness: a test-first `prereqs.sh` step installs `@github/copilot` (Node ≥ 22), `~/.copilot` is added to `CREDENTIAL_PATHS`, and a `command` profile is written. On headless Linux the token is kept in plain text in `~/.copilot/config.json` | `sudo -u gitlab-runner -H bash -lc 'copilot login'` (device code) | **not worth it on Copilot Free**: automatic model choice means an unknown vendor, and the `command` adapter only implements. Unusable until a model can be pinned |
| **Cursor CLI** (Hobby) | harness: install step `curl https://cursor.com/install -fsS \| bash` in `prereqs.sh`, `~/.cursor` in `CREDENTIAL_PATHS`, a `command` profile | `sudo -u gitlab-runner -H bash -lc 'NO_OPEN_BROWSER=1 agent login'` | implementer fallback only, and only if `agent --model` pins a model of a known vendor on Hobby [U] |
| **magnitude** (Qwen3.6-35B-A3B on the Mac) | harness change: a profile option that adds a provider block to the injected OpenCode config, with the key read from an env var (`magnetude-api-key` in Mintkey) | keep the Mac on and reachable | implementer or clarifier candidate, while the Mac is up |

Not worth a login: Gemini CLI (no free login tier since 2026-06-18), Qwen Code (no free tier since 2026-04-15), Aider
(the same providers as OpenCode).

## 9. Harness changes that would let free models do more (none made)

1. Walk to the next judge on `schema_invalid`, as for `error`. A free primary judge would then never strand a unit.
2. After a halt on a free implementer profile, retry the unit once with the next profile. Free-first would then be
   safe for larger units.
3. A chain override per unit (size or risk). Routing "free for small units, Codex for the rest" is impossible today.
4. Keyless `jev` when `base_url` is set (Jev free answers without a key [V]), or `remote` without `/health`.
5. A custom provider block for the OpenCode adapter (magnitude).
6. OpenCode serve mode, which reports the served model: independence with free models becomes `verified` and the
   stealth models become usable.
7. The OpenRouter quota probe for `:free` models: read `free_model_daily_requests`, and stop requiring
   `min_remaining_usd`.
8. Classify Zen's 403 `FreeTierError` (geo-block) as unavailable, not `auth`; and a 429 whose body reads "Endpoint is
   unavailable" as an outage (H3).
9. `CREDENTIAL_PATHS`: add `~/.local/share/kiro-cli`, `~/.gemini`, `~/.copilot`, `~/.cursor` and `~/.qwen` before any
   such login.

## 10. Risks

* Every Zen free model is "for a limited time". Two of the ten already fail on this runner. Re-run the hellos before
  relying on a chain, and prune it when a model is withdrawn. A withdrawn model fails its hello and is skipped, so the
  chain degrades rather than breaks [I].
* Independence with a free model is declared: the harness cannot see which model served a call. The vendors of MiMo
  and LongCat come from their names [I].
* The data terms differ per model (section 2). The dummy chain sends toy code to models that train on it or log it.
  The sample-consumer block uses zero-retention models only.
* The evidence is thin: one toy unit per implementer, and two units per judge. The clarifier, S1 stand-in and audit
  writer roles are unmeasured for free models.
* Keyless Jev Free is undocumented, and the docs ask for a key.
* Claude Pro is shared with claude.ai chat, and its 403s are intermittent on the runner (job 5800). This is why the
  free judge fallbacks matter.

## 11. magnitude (Qwen3.6-35B-A3B on the Mac) as implementer: measured 2026-10-07

Evidence: [live/magnitude/](live/magnitude/) (job log, the three red-step transcripts and prompts, `outcome.json`, the
config diffs). Harness `84ff7cb` (the custom-provider merge `15e26a0`) vendored in dummy-agentic; the vendored code is
the same at harness `287b361`, which only adds docs and helper scripts.

**Setup** [V]: dummy-agentic `main` `75ce93a`, pipeline 3314, `l4` job **5895**, seed `add-pallet-count` (one task, two
scenarios), implementer chain `[magnitude-qwen]` only, judges `[claude-code, magnitude-qwen, f-longcat, f-muse,
codex]`, `availability.probe_timeout: 150s`.

| Measure | Result |
|---|---|
| Provider injection | works [V]: doctor PRV-001 "magnitude-qwen opencode ready; provider 192.0.2.10:10100 reachable" |
| Probe (hello) | `ok (binary 1.18.34 · auth api_key · quota skipped · hello 30.7s)`. The cap is global (SPEC 3.2) and 150 s was set for this reason [V, config]; whether the default would have cut it off was not tested [U]. Outside the harness the same hello took 7.3 s, so the Mac's first-token time varies [V] |
| Red attempts | **3 of 3 failed in 28 to 30 s each: `result missing: opencode wrote no result file`**. Then `halted: max_task_attempts`, exit 13, run 127.7 s, no green, no verdict, cost $0 [V] |
| Verdict (Claude) | none: nothing reached verification |
| Provider errors | none: no grammar 400, no 429, no 5xx. The red-1 transcript ends with `reason: stop` and no error event [V]; red-2 and red-3 stderr are empty [V] |

**Cause** [V, transcripts]: the work was done right in all three attempts. Qwen read the code, wrote the stub and two
tests, saw the tests fail, fixed a lint error, and then wrote its result JSON to
`<worktree>/agent-tmp/result.json`. The prompt (line 89) says to write it to
`/home/gitlab-runner/.cache/l4/units/openspec/add-pallet-count/agent-tmp/result.json`, the private result directory
outside the worktree, the one path the adapter's `external_directory` rule allows. The model changed `units/` to
`worktrees/` in 3 of 3 attempts and never tried the given path. The harness then reads the right path and finds
nothing. Muse, MiMo, Nemotron Ultra, LongCat and Space Bunny wrote it correctly in every unit of section 3 [V].
Whether the right path would have been accepted from Qwen is [U]: it was never attempted.

**Consequences**
* magnitude-qwen **cannot be an implementer today**. A halt does **not** fall through to the next profile (section
  4.2), so having it in the chain means that when everything before it is cooling, the unit halts instead of reaching
  Codex.
* **Applied** (`7935477`): implementer `[f-muse, f-mimo, f-nemotron-ultra, f-longcat, codex, claude-code]`, the
  tentative free-first chain **without** magnitude-qwen. Judges unchanged: `[claude-code, magnitude-qwen, f-longcat,
  f-muse, codex]`, because the adapter reads no result file in judge mode (`opencode.py:220`, `result_text=None if judge`) [V, code], but a magnitude
  judge verdict is **unmeasured** [U]. `probe_timeout: 150s` stays for that reason.
* The seed `add-pallet-count` stays on dummy `main` as a halted unit (branch `l4/openspec/add-pallet-count`, an open
  MR); nothing retries it unless someone runs `l4 resume`.
* To use magnitude as an implementer later, the harness would have to make the result path survive a weak model: for
  example, accept a result file at the worktree's `agent-tmp/` as well, or put the exact path in a shorter line, or
  name the file relative to the cwd. This is a harness change; **M1.13 made it** (`docs/plan/m113-plan.md`, MAG): the
  prompt of a prompt-contract implementer step says `.l4-result/result.json`, a symlink the harness makes to the step's
  private directory before the agent runs and removes after it. The result is still read only from the private
  directory: a file at `<worktree>/agent-tmp/result.json`, where magnitude-qwen wrote, is not accepted (it would be inside
  the commit). Whether magnitude-qwen then writes it right is unmeasured [U]: it needs a new live run.
* Not measured: the second attempt with a changed prompt, red-to-green on a stronger spec, magnitude as clarifier or
  judge, and any run with the Mac under load. n = 1 unit, 3 attempts, one failure mode.

### 11.2 Second measurement, M1.13 result alias (2026-10-07, harness `481057a`) [V]

To repeat this measurement with the M1.14 prompt (allowed result values next to the phase line) and to compare it with a
baseline, see [eval.md](eval.md).

Evidence: [live/m113/](live/m113/) (job log, transcripts and prompts of red 1 to 3 and green, the verification, the
config diff). Token-scanned including `mag-`; ANSI stripped.

**Setup:** dummy-agentic `main` `e37e125` (upgrade `bcca2bb` to `481057a`; implementer `[magnitude-qwen]` only; judges
`[claude-code, magnitude-qwen, f-longcat, f-muse, codex]`, `probe_timeout: 150s`). The halted unit `add-pallet-count`
(MR !36) was resumed with the `l4:resume` label (event 1678) and an `api` pipeline 3413, `l4` job **5963**.

| Measure | Result |
|---|---|
| Probe (hello) | `ok … hello 74.9s`. This is **above the 60 s default** `availability.probe_timeout`, so without the 150 s cap the profile would have been skipped [V] |
| Result path | **fixed.** All three red attempts and the green attempt wrote `.l4-result/result.json`, and the harness read it. No `result missing` |
| Red | attempt 1 **243.1 s, error**: `result invalid: status: not one of the allowed values`; attempt 2 **149.2 s, same error**; attempt 3 **118.0 s, ok**, 2 new tests failing as expected |
| Green | attempt 1, **77.3 s, ok**, 22/22 tests, lint clean |
| Gates | setup, lint, test (24/24 incl. the new two), e2e 2/2 pass; 100 % of changed executable lines ran |
| Verdict | Claude (`claude-opus-5-5`, $0.0945): **NEEDS_HUMAN**, round 1, 2/2 criteria pass, 3 findings: 1 major spec gap (a zero or negative `per_pallet` is not rejected, which the spec text asks for but no scenario covers; the implementation divides as a float), 2 minor spec gaps (float division above 2**53; zero or negative `units` unspecified). Q-001 raised, MR !36 `l4:awaiting_human` |
| Wall time | run `r-20261007T0601Z-17c1`: **824.4 s** (exit 11) for one two-test task. Of that, 510 s were the three red attempts, 77 s green, about 2.5 min verification |
| Cost | $0.0945, all of it Claude's judge; magnitude $0 |

**Cause of the two failed reds** [V, transcripts]: Qwen wrote `"status": "red"` (the value of `phase`) in attempts 1 and
2; the schema allows `done`, `blocked`, `failed` or `partial`. In attempt 3 it wrote `"status": "done"`. So the
path problem is gone and a new, weaker failure mode shows: a wrong enum value. It cost two of the three allowed attempts.

**Judgement.** Magnitude **passed as implementer** on this unit: red and green both succeeded with the result read from
the alias, the gates are green and the judge passed 2/2 criteria. Three limits [I, n = 1]:
* the verdict is NEEDS_HUMAN, not PASS, through a spec gap the spec itself left open (the other free models drew only
  minor gaps from their units), so this does not show that it matches them on quality;
* red passed on the last allowed attempt: a unit with a harder red would halt, and **a halt does not fall through** (4.2);
* it is slow (red 118 s and green 77 s for a two-test unit, against 20 s and 15.5 s for Muse on `add-tip-amount`, job 5851) and only runs while the Mac is awake.

**Applied** (dummy `b4f65dc`): implementer `[f-muse, f-mimo, f-nemotron-ultra, f-longcat, magnitude-qwen, codex,
claude-code]`: the free-first chain with magnitude after the cloud free models and before Codex. The probe skips it when
the Mac is off or slow, so then Codex runs. sample-consumer (`fde6425`): `[codex, magnitude-qwen, f-longcat]`,
private source stays on the LAN. Pipeline 3429, `l4` job 5969: doctor CFG-002 and CFG-005 pass, PRV-001 lists
magnitude-qwen `ready` with the provider reachable, and `l4` reports `nothing to do` (the evidence stays local).
**Watch:** if magnitude-qwen halts a real unit on the enum error, take it out of the chain again, or ask for the harness
to name the allowed `status` values next to the `phase` line of the prompt.


## 12. Ollama System One on the Mac (`engine: ollama`, harness m1.14) [V 2026-10-07]

Free, keyless, local to the LAN: Ollama 0.40.0 on the maintainer's Mac answers `POST /v1/systemone` with `tev1` for the
runner (l4-runner 192.0.2.20 to `http://192.0.2.10:11434`). Profile block:

```yaml
profiles:
  ollama-tev1:
    backend: system-one
    engine: ollama
    model: tev1
    base_url: http://192.0.2.10:11434   # required, a bare http(s) origin; no api_key_env
```

Chain it after the profile it should back up (`roles.s1_judge: [laya, ollama-tev1]`) or list it under
`verifier.s1.shadow`. A sleeping Mac is `unavailable` (the chain falls to the next profile); doctor ENV-013 says so.
Measured limits of this host: the request is capped at 64 KiB of "text and schema" (the engine refuses before sending,
with a margin), and the prompt at 2048 tokens on this `tev1` runner (`HTTP 400 prompt N tokens; expected 1-2048`,
reported as `unavailable: input too large` for that question only). The state budget stays `verifier.s1.max_state_tokens`
(450 approx-tokens by default), far under both. The traffic is plain HTTP on the LAN: the state is redacted before it is
sent, and no key exists to leak.

## 13. Ollama System One (`tev1`): measurement and chain decision [V 2026-10-07]

**Measured** on the M1.6 live test split (`docs/s1/`, `test.jsonl` sha256 `ae31fe7f...`, 147 rows, 342 question
answers), one pass, 147 of 147 rows answered, 0 failed, with the harness's own tools: `l4 s1 score --profile ollama-tev1
--gate gate.json`, then `l4 s1 report` over the existing base Laya, tuned Laya and Jev score files plus the new one
(commands and hashes in [s1/README.md](s1/README.md)). Ground truth is the deterministic/human label, never an engine
answer. `--gate` is the M1.6 live gate of the tuned Laya checkpoint (FAILED); it is passed only because `score`
refuses the test split without one, and tev1 was never trained on this data. The "GATE FAILED" banner in
[s1/compare-2026-10-07-tev1.md](s1/compare-2026-10-07-tev1.md) is about the tuned checkpoint, not about tev1.

| question (n) | laya base acc / ECE / Brier | tev1 acc / ECE / Brier | jev acc / ECE / Brier (n of 60-row cap) |
|---|---|---|---|
| change-covered/exercised (72) | 0.486 / 0.262 / 0.276 | 0.528 / 0.349 / 0.345 | 0.577 / 0.350 / 0.307 (26) |
| change-covered/extent (72) | 0.111 / 0.301 / 0.840 | 0.458 / 0.404 / 0.796 | 0.538 / 0.293 / 0.615 (26) |
| change-covered/untested (72) | 0.403 / 0.124 / 0.257 | 0.556 / 0.304 / 0.273 | 0.577 / 0.325 / 0.296 (26) |
| file-relevant/relatedness (18) | 0.333 / 0.356 / 0.717 | 0.889 / 0.122 / 0.182 | 0.875 / 0.122 / 0.178 (8) |
| file-relevant/relevant (33) | 0.909 / 0.350 / 0.206 | 0.970 / 0.080 / 0.026 | 0.824 / 0.102 / 0.125 (17) |
| file-relevant/unrelated (33) | 0.667 / 0.219 / 0.202 | 0.970 / 0.138 / 0.039 | 0.882 / 0.131 / 0.094 (17) |
| tests-ok/all_passed (42) | 0.548 / 0.231 / 0.237 | 1.000 / 0.095 / 0.028 | 1.000 / 0.033 / 0.006 (17) |
| all 342 answers, n-weighted | 0.447 / 0.247 / 0.395 | 0.681 / 0.262 / 0.317 | 0.708 / 0.224 / 0.269 (137) |
| unweighted mean over the 7 questions | - / 0.263 / 0.391 | - / 0.213 / 0.241 | - / 0.194 / 0.231 |
| latency per row, median / p90 / max | 836 / 1204 / 1383 ms | 1239 / 1649 / 4422 ms | 262 / 326 / 413 ms |

Same 60 rows for all three (Jev's cap; the first 60 rows, not a random sample), accuracy: change-covered
exercised/extent/untested laya 0.308/0.077/0.308, tev1 0.538/0.577/0.615, jev 0.577/0.538/0.577; relatedness
0.375/0.750/0.875; relevant 0.882/0.941/0.824; unrelated 0.706/0.941/0.882; all_passed 0.412/1.000/1.000.
The tuned Laya (0.918 overall, ECE 0.061) is far ahead of all of them but its gate FAILED, so it is not deployable
and is not a candidate.

**Reading** [V for the numbers, I for the conclusions]:

* tev1 is strictly more accurate than the base Laya on all 7 questions, on the whole split (0.681 vs 0.447) and
  on the 60 common rows. It is roughly at Jev's level on the common rows (better on 4 questions, worse on 2, equal on
  1), at $0 and with the code staying on the Mac. The n=18 and n=8 questions are too small to rank (Wilson intervals
  overlap widely); the large gain is on change-covered/extent (0.458 vs 0.111, intervals 0.35-0.57 vs 0.06-0.20).
* Calibration is **mixed, not better**: ECE is better on 4 of 7 questions (the file-relevant ones and all_passed)
  and worse on the three change-covered ones (0.30-0.40 against 0.12-0.30); n-weighted ECE is slightly worse
  (0.262 vs 0.247), unweighted it is better (0.213 vs 0.263), Brier is better either way (0.317 vs 0.395 n-weighted).
  tev1's weak area is change-covered (accuracy 0.46-0.56, close to a coin flip, ECE 0.30-0.40); the test split holds only 3
  units (README: units 16 / 3 / 3), so the answers within a unit are correlated and the intervals understate the
  uncertainty.
* Latency: 1.2 s median on the Mac itself, measured from the Mac to its own LAN IP. Laya's 0.84 s was measured
  with `laya-serve` on the Mac. In production Laya runs on the runner VM and tev1 is a LAN hop away: the
  runner-side latency of either is unmeasured here.
* Nimble: this data cannot say whether it would fix change-covered. It is not shown to be worth pulling; the
  maintainer decides downloads (nothing was pulled).

**Decision** (the stated bar was "at least as accurate and better calibrated, else shadow only"; accuracy is met,
calibration is not met on the change-covered questions): tev1 does **not** go first.

* `roles.s1_judge: [laya, ollama-tev1, ...]`: tev1 is the free, local fallback right after Laya, ahead of the
  llm_boolean stand-in and Claude (a real S1 model with probabilities, where the stand-in is a chat model). A sleeping
  Mac is `unavailable` and the chain goes on.
* `verifier.s1.shadow`: tev1 answers the same items record-only, so calibration rows accumulate on real units for a
  later promotion. dummy-agentic: `[jev, ollama-tev1]`; sample-consumer: `[ollama-tev1]` (it has no Jev).
* Promote tev1 to first only after the change-covered ECE is measured on more units than this split's 3 (the
  shadow rows give that), or after a calibration step is added.
* Privacy: tev1 gets the redacted state over plain HTTP on the LAN, to the maintainer's own Mac, the same trust
  as `magnitude-qwen` in sample-consumer. Laya stays first there because it keeps the data on the runner.

**Applied** (2026-10-07, vendored harness upgraded to `9084ed9` in both, `l4 doctor` ENV-013 passes locally first):

| project | commit | `s1_judge` | `verifier.s1.shadow` | proof |
|---|---|---|---|---|
| dummy-agentic (118) | `7f4f454` (author CiprianSpot) | `[laya, ollama-tev1, f-muse, claude-code]` | `[jev, ollama-tev1]` | l4 job 6061 green: `ENV-013 Ollama ready: ollama-tev1 (tev1, ollama 0.40.0)` and `S1-001 2 shadow profile(s) usable: jev, ollama-tev1`; test job 6064 green; log in [live/ollama/](live/ollama/dummy-agentic-l4-job-6061.txt) |
| sample-consumer (119, private) | `6193f25` (owner identity, rebased onto `dacd2cb`) | `[laya, ollama-tev1, f-space-bunny, claude-code]` | `[ollama-tev1]` | l4 job 6080 green: the same ENV-013 line and `S1-001 1 shadow profile(s) usable: ollama-tev1`; test job 6079 green; log kept in the git-ignored `adoption/sample-consumer/live/ollama/` |

Both pushes waited for `l4_idle.py` to report a quiet window (a sample-consumer unit held the runner for
about two hours). Neither l4 job had a unit to advance, so the probe line shows the profile is configured and reachable,
not yet a tev1 judgement in a real verify step: the first real step 8 with shadow rows is the next unit that reaches
the verifier. The profile carries no `vendor:` (the S1 chain has no independence rule; an unmeasured vendor is not guessed).

**Re-measurement log** (S1 engines; the decision above changes only on a new measured row):

| date | data | base Laya | tuned Laya | tev1 | Jev | effect on the chains |
|---|---|---|---|---|---|---|
| 2026-10-07 | M1.6 live test split, 147 rows, 3 units | measured (above) | gate FAILED | measured (above) | 60-row cap | tev1 second in `s1_judge`, shadow in both projects (applied) |
| 2026-10-08 | Laya round 2: first set with sample-consumer units, 2129 rows, 39 units ([s1/laya-round-2.md](s1/laya-round-2.md)) | not scored | **not trained**: the shortcut check stopped it (`inventory` decides `relevant` at 0.938 on test; no real out-of-scope rows) | not scored | 0 requests | none: nothing was re-measured, the 2026-10-07 order stands, no checkpoint to deploy |

## 14. Kiro Free as implementer: kiro-e2e H2 [V 2026-10-08]

Full write-up: [live/kiro-e2e/README.md](live/kiro-e2e/README.md) (section H2). Harness `0e4bcc8` vendored on the
dummy, runner `gitlab-runner` with kiro-cli 2.28.0 and KIRO FREE.

| Profile | Unit | Result | Wall | Credits (FREE `/usage`; stream sum) | Judge verdict |
|---|---|---|---|---|---|
| `kiro` (kiro-cli 2.28.0, `glm-5`, vendor `zhipu`) | `kiro:add-bulk-discount-h2` (Kiro-authored, 2 required leaves, 6 criteria, 2 files plus 2 test files) | **PASS**: red 2.1 and 1.1 on the first attempt; green 2.1 first, green 1.1 second (attempt 1 `The request was throttled by the service`); MR !37 merged | 856 s (job 6146) | **5.42 of 50**; 10.72 | `magnitude-qwen` PASS 6/6, 1 minor (Claude is not logged in on the runner) |
| `kiro-qwen` (`qwen3-coder-next`, the cheapest) | H1 `add-bulk-discount` on the Mac (8 leaves) | halted: 3 red attempts rejected on 2.1 | – | 1.85 (PRO) | – |
| `kiro-glm` on the Mac (PRO) | the same 2-leaf spec, local forge | PASS, every step on the first attempt | 688 s | 11.47 (PRO, the two counts agree) | Claude PASS 6/6 |

* **Chain decision (applied to dummy-agentic, `18ccc89`):** `implementer: [f-muse, f-mimo, f-nemotron-ultra,
  f-longcat, magnitude-qwen, kiro, codex, claude-code]`.
  * Kiro comes after the OpenCode free models and magnitude because it is credit-limited: about 5 of the 50
    monthly credits for this 2-leaf unit, so roughly 9 such units a month [I], and the FREE tier throttles.
  * It comes before Codex because it is free, and because it is the only free implementer measured on a multi-file,
    multi-leaf unit in CI.
  * A halt does not fall through (4.2).
* **Model:** pin `glm-5`. `qwen3-coder-next` failed red 3 times on H1. `auto` makes the vendor unknowable, which
  vetoes every judge. A `claude-*` model would take Claude out as an independent judge.
* **Open:**
  * a throttle counts as a failed attempt, not a cool-down (3 in one step halt the unit);
  * the sweep never runs the Kiro done-gate after a merge;
  * the FREE `/usage` count is about half the stream-metered count [U].


## 15. The first `l4 eval` baseline: free implementers and judges, magnitude after the status hint [V 2026-10-08]

Evidence: [eval/README.md](eval/README.md) and [eval/2026-10-08/scorecard.md](eval/2026-10-08/scorecard.md) (`l4 eval`
of M1.14 on l4-runner as `gitlab-runner`, harness `f0c703c`, the profiles of dummy-agentic's `.l4/config.yaml`
unchanged, seed set `ed59f51d…` of 4 toy units, k = 1, every cell started in a quiet window). The harness now has the
fix that section 11.2 asked for: the allowed `status` values stand next to the phase line, an enum error lists them and
the retry says that `"red"` is the phase (M1.14, `34d8018`, `153ba67`).

| Role | Profile | Result | Red attempts | Median wall |
|---|---|---|---|---|
| implementer (judge: codex) | f-muse | 3/3 PASS | 1.00 | 74 s |
| implementer (judge: codex) | f-longcat | 3/3 PASS | 1.00 | 158 s |
| implementer (judge: codex) | magnitude-qwen | 3/3 PASS, no halt | 2.67 (3, 3, 2) | 196 s |
| judge | magnitude-qwen | 4/4 agree, the designed defect caught (NEEDS_HUMAN, 8 findings, worst blocker) | - | 39 s |
| judge | f-longcat | 4/4 agree, the defect caught (NEEDS_HUMAN, 3 findings, worst blocker) | - | 54 s |
| judge | claude-code | not measured: 4/4 `invalid: login` (the runner's Claude login was gone before the run) | - | - |

**magnitude-qwen after the status hint** [V, ledgers]: the enum error is rarer but not gone. It wrote `"status": "red"`
in 3 of its 8 red attempts (once per unit: attempt 1 of add-tip-amount, and the retry after another failure on the
other two; M1.13 had it in 2 of 3 attempts on one unit). The retry's hint fixed it every time. Its other two failed
attempts were real red-phase mistakes the other models did not make: a vacuous test (the scenario whose answer is 0)
and new tests without their `@pytest.mark.l4` traces. Red succeeded on the last allowed attempt in 2 of 3 units, so a
harder unit could halt it, and a halt does not fall through (4.2). As a judge it agreed on all 4 units and caught the
designed defect, the first measurement of magnitude as a judge (section 11 had it [U]).

**Decision** [I]: the criterion "red to green without halting on at least 2 of 3 seed units" is met (3 of 3), so
magnitude-qwen moves **earlier** in dummy-agentic's implementer chain, to **second, after f-muse**: `[f-muse,
magnitude-qwen, f-mimo, f-nemotron-ultra, f-longcat, kiro, codex, claude-code]` (dummy `f285903`, pushed by
CiprianSpot as the human at 07:16Z in a quiet window, `[skip ci]` like the chain commits before it; the config was
checked with `L4Config` of harness `b4ef7d0`). Second, not first: f-muse was better on every count of this baseline (1
red attempt, 74 s). Ahead of f-longcat although f-longcat measured better here (1 attempt, 158 s): the place is for
having its own server and no Zen free-tier limits (it serves when f-muse cools), not for quality. f-mimo
and f-nemotron-ultra were not in this baseline. Take it back to fifth if it halts a real unit.

**sample-consumer** (119): **should not follow yet**, and was not changed. Its chains today [V, `main`]:
implementer `[codex, f-longcat, magnitude-qwen]`, judges `[claude-code, magnitude-qwen, f-longcat, codex]`. Moving
magnitude-qwen ahead of f-longcat there is not supported by this baseline: f-longcat measured better (1 red attempt
against 2.67), the sample-consumer units are private and multi-file where the toy units are single-task, and a halt costs the owner
a resume. Revisit after magnitude-qwen has implemented real dummy units in its new place without a halt. Its judge
result (4/4, the defect caught) supports its place as the first free judge fallback there, unchanged.

**Maintainer action**: log Claude in again on the runner (`sudo -iu gitlab-runner`, `claude`, `/login`; the harness's
login-lock commits `fa97486`..`0de761f` are about the cause). Until then claude-code, first in both projects' judge
chains, is skipped at its auth probe and both chains fall to magnitude-qwen.
