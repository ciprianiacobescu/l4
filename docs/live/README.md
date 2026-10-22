# Live runs on `example-group/dummy-agentic`

Evidence of the harness running for real: GitLab 17.5.2 CE at `gitlab.example.com`, runner `l4-runner`
(shell executor, bubblewrap sandbox), harness installed with `l4 init --ci gitlab --vendor` (the harness repo itself
stays local, decision Q1). Every row links the raw job log or artefact saved next to this file.

## 2026-10-04 — M0 walking skeleton (harness `2bb68f7`)

Setup: dummy-agentic `main` @ `e1db758` (seed pricing library + `.l4/` from `l4 init`), Codex `gpt-6-luna` (effort
low) as implementer, Claude Code (subscription `pro`, served `claude-opus-5-5`) as the independent judge, project
access token `l4-bot` as `L4_FORGE_TOKEN`. Pipelines started through the API with `L4_UNIT`.

| Run | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 | #2527 / 5420 | **failed, exit 1** — red phase of task 1.1 committed, then `git push` was refused: `remote: You are not allowed to push code to this project.` Cause (probe pipeline #2528): gitlab-runner 19.4 injects `url.https://gitlab-ci-token:<job token>@<host>.insteadOf https://<host>`, so pushes went out with the job token and the `l4-bot` credential helper was never asked. Fixed in `2bb68f7`: pushes use `https://oauth2@<host>/<path>.git` as `remote.origin.pushurl` (no insteadOf prefix can match it), and the runner's `<project>.tmp` dir is hidden from both sandboxes | [../runner/live-m0-2026-10-04-job-5420.txt](../runner/live-m0-2026-10-04-job-5420.txt), [../runner/ci-probe-gitconf-2026-10-04-pipeline-2528.txt](../runner/ci-probe-gitconf-2026-10-04-pipeline-2528.txt) |
| 2 | #2530 / 5424 | **success, exit 0, ~4 min** — `openspec:add-discount-codes`: red → green for tasks 1.1 and 1.2 (commits by `l4-bot`, `L4-TDD` trailers, checkpoints `[skip ci]` → their pipelines skipped), verification round 1 **PASS** (gates setup/lint/test + one Claude judge, 7/7 criteria, 4 minor spec-gap findings, $0.16), hand-off commit without `[skip ci]` → the project's own CI ran on it (pipeline #2541 success), **MR !1 ready, label `l4:in_review`** | [job log](2026-10-04-job-5424-add-discount-codes.txt), [commits + trailers](2026-10-04-add-discount-codes-commits.txt), [verification.md](2026-10-04-add-discount-codes-verification.md) |
| 3 | #2543 / 5428 | **exit 11 (awaiting_human), allowed failure, 29 s** — `openspec:add-vat` (deliberately ambiguous: no rates, no rule for unsupported countries): Codex reported `blocked` in red instead of inventing rates; the harness wrote `questions.md` (Q-001, kind `ambiguous`, blocking 1.1), committed it `[skip ci]`, **draft MR !2 with labels `l4:awaiting_human`, `l4:needs-answers`** | [job log](2026-10-04-job-5428-add-vat.txt), [questions.md](2026-10-04-add-vat-questions.md) |

What M0 does **not** do yet (planned M1, see `docs/plan/implementation-map.md`): resume a blocked unit from a human
answer, the LLM clarifier, fix specs from verifier findings, post-merge archive MR, fallback chains and cool-downs,
OpenCode/Kiro adapters, automatic "only when there is work" triggering, GitHub, memory/Serena lessons, Playwright and
System-One judges, criterion→test traceability (an M0 PASS rests on gates + red/green proof + one judge).

## 2026-10-04 — M1.1 "close the human loop" (harness `f43a84b`, upgraded in place with `l4 upgrade`)

Setup: dummy-agentic `main` @ `7de15d3` (`l4 upgrade` changed only `.l4/vendor/`, `.l4/ci/l4.gitlab-ci.yml` and the
`harness.commit` pin; roles `clarifier` and `s1_judge` = claude-code, `clarifier.s1_standin: llm_boolean` added by
hand). The operator acted as the human (maintainer permission 2026-10-04). Nobody set `L4_UNIT`: every `l4` job below
was started by the routed CI rules. Raw job logs and artefacts are in [m11/](m11/).

| Step | Pipeline / job | Result |
|---|---|---|
| 1 upgrade pushed to `main` | #2550 / 5432 | **pass** — one `l4` job ran automatically, `nothing to do`, exit 0 in **8 s**, no agent probe; doctor CI-001 confirms the oauth2@ push path |
| 2 human merges MR !1 | #2551 / 5434 | **pass** — sweeper: `MR !1 merged` → phase `merged` → **archive MR !3** `[l4] archive add-discount-codes`: 8 renames into `openspec/changes/archive/2026-10-04-add-discount-codes/` + new base spec `openspec/specs/discounts/spec.md` + folded ledger; the archive push ran only the project's `test` job |
| 3 operator closes old MR !2, deletes its branch | — | done |
| 4 seeds pushed (`add-average-price`, re-seeded `add-vat`) | #2553 / 5437 | **4b pass**: `add-vat` — intake lint (L4-ODD-004) raised Q-001 (`ambiguous`, both scenarios quoted) before any agent ran; clarifier classified it `product`, suggested 21 % (RO VAT since 2025-08-01) and escalated; draft **MR !5** `l4:awaiting_human` + `l4:needs-answers`. **4a deviation**: `add-average-price` — Codex asked the expected `technical` question (Decimal or float); the clarifier answered correctly with 3 resolving citations but rated it `medium`, so (default `min_confidence: high`) it escalated → draft **MR !4**. Job exit 11 (allowed failure) |
| 5 loop safety | #2565–#2584 | **pass** — 12 `[skip ci]` checkpoint pushes → pipelines skipped; the hand-off push H ran only `test`; only human pushes started `l4` jobs |
| 6 human answers add-vat Q-001 (+ deletes the 119.00 scenario) | #2564 / 5439 | **resume pass, verdict NEEDS_HUMAN**: base-branch checkout, plan `answers submitted: Q-001`, red→green ×2 with Codex, gates green, judge passed 3/3 criteria but raised a **major spec gap**: VAT is computed on the subtotal and ignores discount codes (merged in !1) — 10 % off + RO gives 121.00 vs 108.90. Unit waits for a human (verdict questions and fix units are M1.3) |
| 6b human accepts the clarifier's suggestion on add-average-price | #2577 / 5441 | **pass** — `accepted` suggestion consumed as the answer, red→green, PASS, **MR !4 ready** `l4:in_review`, MR head = hand-off commit H, run tail in `refs/l4/locks/openspec/add-average-price` (`[skip ci]`, L4-LCK-001 JSON) |
| 7 API pipeline on `main` | #2585 / 5444 | **pass** — `nothing to do`, exit 0 in 6.8 s, no second archive MR |
| variant: `clarifier.min_confidence: medium` + seed `add-is-empty` | #2586 / 5446 | auto-answer path ran live up to the last rule: clarifier `high` / `technical`, S1 stand-in asked for the question (p_product 0.00) and for each citation (1.0, **0.0**, 1.0) — the cited `design.md` line ("follow the conventions") is context, not evidence, so the strict every-citation rule refused auto-accept. Fix: the clarifier prompt now asks for evidence-only citations and calibrated confidence (re-test below) |

Read-only acceptance test (`tests/live/test_m1_1_acceptance.py`, G13) after step 7: 7 passed, 2 skipped, 6 failed —
the failures are the two real deviations above (4a escalated instead of auto-answered; add-vat NEEDS_HUMAN, hence no
lock ref and no ready MR) and test artefacts (an exact commit-message match in step 1, step 4b checking labels after
step 6 changed them).

| Re-test | Pipeline / job | Result |
|---|---|---|
| clarifier prompt `clarifier@3` (`ea452a3`: evidence-only citations, calibrated confidence); `add-is-empty` reset and re-run | #2593 / 5448 | unit **PASS → MR ready** in one unattended run — but **no question was raised**: Codex decided the listed open question itself (the spec names `Cart.is_empty()`), ignoring contract@2. The implementer-dependent path is nondeterministic, so the fix is deterministic: intake raises the open questions listed in `design.md` before any agent runs (in progress) |
| deterministic intake of listed open questions (`b0a35a8`); `add-is-empty` reset and re-run | #2601 / 5451 | **pass — the LLM-first clarifier path ran end to end, unattended**: intake raised Q-001 (`technical`, source `intake_open_questions`) before any agent → `implementing → clarifying` → Claude answered `confidence: high`, S1 stand-in p_product 0.00 and citation support [1.0, 1.0] → **auto-accepted** (`answered-by-clarifier`, `question.answered{by: clarifier}`) → `clarifying → implementing` → red → green → verified → hand-off → MR ready. [questions.md](m11/add-is-empty-questions-run3-auto-answered.md), [job log](m11/p11-job-5451.txt) |

## 2026-10-04 — M1.2 "availability, fallback chains and more adapters" (harness `8dce4b0`, live-fixes `0fa4ad1`, `bf85faa`)

Live exit protocol of [`docs/plan/m12-plan.md`](../plan/m12-plan.md) ("Live exit protocol on `example-group/dummy-agentic`
through `l4-runner`"), run by the operator acting as human and maintainer (Q9 standing permission). Before the
run: `uv run pytest -q` at `8dce4b0` = 2305 passed, 39 skipped; G14, G17 and G18 recorded done in `m12-progress.md`.
Every pipeline below was started by a push to `main` except #2624 (API pipeline, the step-1 retry). Job logs (ANSI and
section markers stripped) and ledger/commit extracts are in [m12/](m12/) (named `s<step><attempt>-…`), job artefacts in
`artifacts/job-<id>/l4-out/`.

**Verdict:** as written, the protocol FAILS at step 1 (a protocol defect, not a harness bug — see the first deviation
below). With one documented change of the P1 lever and the protocol's own retry rules, steps 1–6 behaved as expected:
the implementer fell back past a quota-exhausted codex and a logged-out Kiro to OpenCode (`fallback #2`, commits
`L4-Fallback-From: codex`), the judge fell back to the operator-declared OpenCode profile (`fallback #1`) with
`independence: declared (unverified)`, a chain with nothing left parked the unit (exit 12, `retry_after`), and
`l4 probe --no-cache` cleared the codex cool-down. Two harness bugs were found and fixed on `main` (`0fa4ad1`, `bf85faa`).

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 upgrade to `8dce4b0` (dummy `0c108cb`), first idle pipeline | [#2613](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2613) / [5456](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5456) | **pass** — the progress trace prints: `[l4] sweeper: openspec:add-discount-codes: archive MR !3 is open`, `[l4] run: nothing to do: no unit has a next step`; exit 0 | [m12/s0-upgrade-job-5456.txt](m12/s0-upgrade-job-5456.txt) |
| 1 as written (`a718100`: `claude-judge` with `min_version: "99.0.0"` heads `judges`) | [#2614](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2614) / [5458](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5458) | **FAIL, exit 3 (doctor_failed)** before any plan: `ENV-004 error fail judges head 'claude-judge': claude 2.1.288 found, 99.0.0 or newer is required`. This is SPEC SCN-DOC-02 / SCN-AVL-04 (an unusable chain head is a doctor *error*), built by M1.4 after the M1.2 plan chose this lever. `doctor --ci --fix` also ran the official claude installer for the floor version: `fix claude failed … install.sh exited 1` (the runner's claude 2.1.288 is intact; the installer left a 0-byte `~gitlab-runner/.local/share/claude/versions/99.0.0`, see cleanup) | [m12/s1a-doctor-fail-job-5458.txt](m12/s1a-doctor-fail-job-5458.txt) |
| 1 variant lever (`8b3347d`: `claude-judge` = `auth: api_key`, no `min_version`; refused at the probe's auth step, zero cost, no cool-down) | [#2615](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2615) / [5460](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5460) | selection exactly as expected (lines below); codex red → green; big-pickle judge passed 4/4 criteria but raised a **major** spec-gap finding ("non-Decimal amount type not specified") → **NEEDS_HUMAN, exit 11**, draft MR !9. Retry rule applied: MR !9 closed, branch deleted (no lock ref existed) | [m12/s1b-needs-human-job-5460.txt](m12/s1b-needs-human-job-5460.txt), [verification.md](m12/s1b-add-money-format-verification.md), [commits](m12/s1b-add-money-format-commits.txt), [ledger](m12/s1b-add-money-format-availability-events.jsonl) |
| 1 retry (one API pipeline on `8b3347d`) | [#2624](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2624) / [5462](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5462) | **pass** — `[l4] implementer: codex ok (binary 0.160.0 · auth subscription · quota 3% used (weekly window) · hello 4.2s · cached) → selected`; `[l4] judges: claude-judge skipped — auth: auth: api_key is not supported in M0 (…)`; `[l4] judges: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello 6.2s · cached) → selected, fallback #1`; red/green commits `L4-Agent: codex/gpt-6-luna`, no `L4-Fallback-From`; ledger `availability.selected{judges, opencode-free, fallback_index 1, fallback_from claude-judge}` + `availability.model_unverified{opencode-free}`, no `availability.cooldown`; `verification.md` PASS, `independence: declared (unverified): opencode-free zhipu (declared), codex openai (tool)`; **[MR !10](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/10) ready, `l4:in_review`**, exit 0 | [m12/s1c-retry-job-5462.txt](m12/s1c-retry-job-5462.txt), [verification.md](m12/s1c-add-money-format-verification.md), [commits](m12/s1c-add-money-format-commits.txt), [ledger](m12/s1c-add-money-format-availability-events.jsonl), [artefacts](artifacts/job-5462/l4-out/) |
| 2 `l4 probe claude-code --json` on the runner | — (mk-ssh, between P1 and P2) | **pass** — ok; quota windows `session` 0 %, `weekly (all models)` 2 %; `cooldowns: []`; one hello. Gate for step 3: codex used 3 % (≥ 1 %), claude ≥ 10 % left in every window | [m12/s2-probe-claude-code.json](m12/s2-probe-claude-code.json) |
| 3 reserve on codex, Kiro in the chain, Q9 judges (`861e6ff`) | [#2632](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2632) / [5465](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5465) | selection **as expected**: `[l4] implementer: codex skipped — quota: weekly window 3% used, 97% remaining < 100% (profile reserve) (resets 2026-10-10T12:52Z); cool-down recorded`, `[l4] implementer: kiro skipped — auth: kiro-cli installed, not authenticated`, `[l4] implementer: opencode-free ok (… hello 6.2s · cached) → selected, fallback #2`; ledger `availability.cooldown{codex, usage_limit, until 2026-10-10T12:52:23Z, source codex.rateLimits}`, skipped `codex/quota`, `kiro/auth`. Then **halted, exit 13**: big-pickle did the red step right three times but its `result.json` lacked `status` and `summary` (`result invalid: status: required; summary: required`) — **harness bug**: the prompt-contract prompt never gave the schema. Fixed in `0fa4ad1`; MR !11 closed, branch deleted | [m12/s3a-halted-job-5465.txt](m12/s3a-halted-job-5465.txt), [ledger](m12/s3a-add-split-amount-availability-events.jsonl), [artefacts](artifacts/job-5465/l4-out/) (`agent/*/1.1-red-1.jsonl` shows the write) |
| 3 re-run on harness `0fa4ad1` (`8d1780b`, push) | [#2635](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2635) / [5467](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5467) | **pass** — codex still cooling (retry rule): `[l4] implementer: codex skipped — cooling until 2026-10-10T12:52Z (usage_limit); no probe sent`, kiro skipped at auth, `opencode-free ok (… hello 8.4s) → selected, fallback #2`; red → green by opencode-free, both commits `L4-Agent: opencode-free/opencode/big-pickle` + **`L4-Fallback-From: codex`**; no codex agent step (every `step.started` is `opencode-free`, `agent/` holds the opencode red/green streams and the claude judge only; the red prompt now carries the result schema); `[l4] judges: claude-code ok (binary 2.1.288 · auth subscription · quota 2% used (weekly (all models)) · hello 4.1s) → selected`; `verification.md` PASS 5/5, `independence: declared (unverified): claude-code anthropic (served claude-opus-5-5), opencode-free zhipu (declared)`; `outcome.json` `profiles == {"implementer": "opencode-free", "fallback_from": "codex"}`; **[MR !12](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/12) ready, `l4:in_review`**; judge $0.13; exit 0 | [m12/s3b-rerun-job-5467.txt](m12/s3b-rerun-job-5467.txt), [verification.md](m12/s3b-add-split-amount-verification.md), [commits](m12/s3b-add-split-amount-commits.txt), [ledger](m12/s3b-add-split-amount-availability-events.jsonl), [artefacts](artifacts/job-5467/l4-out/) |
| 4 `l4 probe … --json` on the runner, ~1.5 min after P2 | — (mk-ssh) | **pass** — `codex skipped — cooling until 2026-10-10T12:52Z (usage_limit); no probe sent`; `kiro skipped — auth: kiro-cli installed, not authenticated`; `opencode-free ok (… · cached)`; `claude-code ok (… · cached)`; `claude-judge skipped — auth: …` (named explicitly: `l4 probe` with no name probes only profiles in a chain, and step 3 took it out of every chain); no paid call; exit 12 | [m12/s4-probe-named.json](m12/s4-probe-named.json), [text](m12/s4-probe-named.txt), [unnamed form](m12/s4-probe-all.json) |
| 5 (optional) `roles.implementer: [codex]`, seed `add-percent-of` (`0ca6892`) | [#2643](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2643) / [5470](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5470) | **pass** — `[l4] implementer: codex skipped — cooling until 2026-10-10T12:52Z (usage_limit); no probe sent` → `phase ready → waiting_capacity (required_role_unavailable)`, **exit 12** (allowed failure, pipeline green), `outcome.json` `phase_after: waiting_capacity`, `retry_after: 2026-10-10T12:52:23Z`; no branch, no MR, no agent directory | [m12/s5-exit12-job-5470.txt](m12/s5-exit12-job-5470.txt), [artefacts](artifacts/job-5470/l4-out/) |
| 6 cleanup (`7409c21`) | [#2644](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2644) / [5472](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5472) | **pass** — reserve and `claude-judge` removed, `implementer: [codex, opencode-free, claude-code]`, `judges: [claude-code, opencode-free, codex]`, seed C deleted; `nothing to do`, exit 0. Then `l4 probe --no-cache --json codex`: `status ok`, quota 3 % used, **`cooldown_cleared: true`**; `l4 probe --json`: codex, opencode-free, claude-code ok, **no cool-down** (`availability.json` `cooldowns: {}`) | [m12/s6-cleanup-job-5472.txt](m12/s6-cleanup-job-5472.txt), [L4_LIVE_PROBE_6](m12/s6-probe-nocache-codex.json), [L4_LIVE_PROBE_6B](m12/s6b-probe-all.json), [text + availability file](m12/s6b-probe-all.txt) |
| 7 (optional) human merges A and B | — | not run: archive MR !3 is still open and archive MRs go one at a time; MRs !10 and !12 stay ready | — |

Deviations and findings (V = seen in logs or files, I = inferred):

* **Step 1's lever conflicts with doctor ENV-004** [V, job 5458]. A chain head below its `min_version` is a doctor
  error by SPEC SCN-DOC-02, so the run never reaches selection; `--ci --fix` additionally tries to install the floor
  version. Recommendation for the maintainer: change the plan's step-0 lever to `auth: api_key` (what ran here) and the
  G20 regex at `tests/live/test_m1_2_acceptance.py:163` to `auth: …api_key is not supported`, or decide in SPEC whether
  ENV-004 should only warn when a later profile of the same chain is usable. Neither the plan nor that assertion was
  edited here.
* **Harness bug, fixed `0fa4ad1`** [V]: the implementer prompt of a prompt-contract adapter (opencode, kiro-cli,
  command) named the result path but not the schema, and said "schema enforced". It now names `status` and `summary`
  and carries the compact `l4/implementer-result@1` schema; the native prompt is byte-identical. Test-first in
  `tests/unit/implementer/test_prompt.py` and `test_tdd_prompt_contract.py`; `tests/unit/implementer tests/unit/agents
  tests/scenarios tests/contract` 346 passed, ruff clean; dummy upgraded to `0fa4ad1` in `8d1780b`.
* **G20 bug, fixed `bf85faa`** [V]: `implementer_commits` read every `test(`/`feat(` commit reachable from the unit
  branch, so main's merged `add-discount-codes` codex commits failed step 3's `L4-Agent` check (and made step 1 pass by
  coincidence). It now keeps only commits whose `L4-Unit` names the unit (`protocol_m12.unit_implementer_commits`,
  unit-tested). `tests/live` is not vendored, so the dummy repo needed no upgrade.
* **G20 result** (`L4_LIVE=1`, saved probe files): as committed, **5 passed, 2 failed** — step 1 at the
  `min_version 99.0.0` regex (the lever variant) and step 3 at the codex quota regex (the retry ran while codex was
  already cooling; the quota line, `availability.cooldown` and the `codex/quota` skip are in job 5465 above). A local,
  uncommitted copy with exactly those assertions relaxed: **7 passed**. [as-is](m12/g20-acceptance-asis.txt),
  [relaxed](m12/g20-acceptance-relaxed-local.txt), [ids](m12/g20-ids.json).
* **Wording deltas against the plan's expected lines** [V]: codex shows `auth subscription` (plan: `auth chatgpt
  <plan>`; the probe JSON has `auth_method chatgpt`, `plan plus`); the api_key skip reads `auth: auth: api_key …`
  (the reason repeats the step name, cosmetic); the unit-prefixed duplicates carry short reasons (`codex skipped — usage
  window exhausted`, `— cooling`); `l4 probe` exits 12 whenever a probed profile fails or cools (known, SPEC rule owed).
* **big-pickle as judge** [V]: one valid NEEDS_HUMAN (a major "spec gap" on input types the spec never mentions), then
  PASS on the retry with the same findings rated minor. It is a stricter, less stable judge than Claude.
* **Sandbox** [I]: opencode ran through the harness' agent path (`wb.sandbox.wrap`, G17 passed on this runner); the
  job logs do not print the bwrap argv.
* **Cleanup:** MR !9 and !11 closed and their branches deleted (retry resets); config restored and seed C deleted
  (step 6); codex cool-down cleared (step 6). **Left for a maintainer with shell access**: `rm
  ~gitlab-runner/.local/share/claude/versions/99.0.0` (0 bytes, left by the job-5458 installer attempt; the operator is
  read-only on the runner).
* **Spend** [V/I]: codex 2 red/green runs (jobs 5460, 5462) + 2 hellos (job 5460, step-6 re-probe), weekly window at
  3 % used; claude one judge call $0.13 + 2 hellos (step 2, job 5467); OpenCode Zen $0.

## 2026-10-04 — M1.4 "Kiro specs, doctor `--fix`, dry run, simulation" (harness `c9e2c0d`, G7 live-fix `6eaee92`)

Live exit protocol of [`docs/plan/m14-plan.md`](../plan/m14-plan.md) ("LIVE exit protocol on `example-group/dummy-agentic`
through `l4-runner`"), run by the operator acting as human and maintainer. Before the run:
`uv run pytest -q` at `c9e2c0d` = 2308 passed, 39 skipped ([m14/s0-pytest-c9e2c0d.txt](m14/s0-pytest-c9e2c0d.txt)).
Preconditions as found: M1.2's protocol had finished (runner `availability.json` `cooldowns: {}`); M1.3 is not merged,
so its protocol has not run and its levers were never set on the dummy. The step-1 reset therefore writes the defaults
explicitly (`verifier.fix_minor_findings: false`, `roles.verifier_agent: []`). `profiles.kiro` from M1.2 was kept, and
so were M1.2's fallback chains. Job logs (ANSI and section markers stripped) and extracts are in [m14/](m14/), job
artefacts in `artifacts/job-<id>/l4-out/`.

**Verdict: PASS, steps 0–4 as written.** P1 (probe branch) predicted the Kiro unit's first step without touching
anything. P2 (`main`) then ran the seeded Kiro spec end to end with Codex and one Claude judge call:
* wave order: 2.1 before 1.1, against document order;
* the optional 1.2 was never started;
* both parents were ticked in their last child's green commit, so `tasks.md` differs from the seed in exactly 4
  marker bytes;
* verdict PASS 4/4 (`Req 1.1`…`Req 1.4`), and MR !13 is ready with `l4:in_review`.

The only failure was in the plan's acceptance code G7 (`tests/live/test_m1_4_acceptance.py`), not in the harness. It
was fixed in `6eaee92`; G7 then passed 7/7. Optional step 5 was not run (reason below). Step 6 is blocked by Q5.

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 local: `l4 simulate --all --json` ×2; actionlint on `render_github_ci(<dummy config>)` | — | **pass** — both runs `{"pass": 5, "fail": 0, "pending": 16}` with identical `events_sha256` per scenario. actionlint 1.7.12 with `self-hosted-runner: {labels: [agentic]}`: no finding, exit 0. Control without the config: only `label "agentic" is unknown` | [run 1](m14/s0-simulate-all-1.json), [run 2](m14/s0-simulate-all-2.json), [actionlint](m14/s0-actionlint.txt) |
| 1 local: `l4 upgrade` to `c9e2c0d`, config delta, Kiro seed → C1 [`b0b384d`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/b0b384ddaf81a69cd4754150af7ccfaf36c6f21e) | — | **pass** — the upgrade changed only `.l4/vendor/src/l4/_commit.py` and `harness.commit` (the template already starts with `doctor --ci --fix`, since M1.2's upgrade to `8dce4b0`). `l4 plan --json`: `kiro:add-loyalty-points` `implement`, tasks `{done 0, total 4}` (optional 1.2 not counted); every other unit `none`; `--detailed-exitcode` 10. `l4 doctor`: `SPEC-001 pass openspec, kiro`, `SPEC-002 pass 1 Kiro unit(s) validate`, `SPEC-004 pass … every leaf cites a requirement`. ENV-004 and PRV-001 fail only on the Mac (no codex there). Local `run --dry-run`: `task=2.1 (red)`, `would exit 0` | [C1 + config diff](m14/s1-c1-upgrade-and-config.txt), [plan](m14/s1-plan-local.json), [doctor](m14/s1-doctor-local.txt), [dry run](m14/s1-dry-run-local.txt) |
| 2 P1: push `probe/m14` = C1 + C2 (probe job, `ci/m14-probe.sh`) | [#2645](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2645) / [5473](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5473) | **pass** — one job `m14-probe` on runner #12 (`l4-runner`), success in 26 s. Summary: `plan exit 10`, `dryrun exit 0`, `simulate exit 0`, `doctor-unit exit 0`, `fix1 exit 0`, `fix2 exit 0`, `refs unchanged`, `sudo never called`, no `TOKEN SHAPE FOUND`. `plan.env`: `L4_EXIT=10`, `L4_UNITS_ACTIONABLE=1`. Dry run: `kiro:add-loyalty-points  phase=none  next=implement  task=2.1 (red)`, `command: codex exec … -m gpt-6-luna …`, table `… implement  2.1   unknown       0`, last line `would exit 0`; `2.1-red.prompt.md` lists `Req 1.1`…`Req 1.4`; no `agent.session`/`availability.selected` anywhere. Simulate: `happy-openspec` and `happy-kiro` pass. doctor `--unit`: global rows plus SPEC-001/002/004 (`1 Kiro unit`). fix1 (scratch `L4_HOME`/`L4_CACHE` under `$CI_BUILDS_DIR`): `openspec applied` (`npm install --prefix …/.l4-m14-5473/home/npm --save-exact @fission-ai/openspec@1.14.0`), ENV-003 pass in the same report; uv 0.12.22, node 22.23.3, claude 2.1.288, codex 0.160.0 and opencode 1.18.34 `already present`; PRV-002 pass; PRV-001 `claude-code ready; codex ready; opencode-free ready`. fix2: all six `already present`, no install line. MR list for `l4/kiro/add-loyalty-points`: empty | [job log](m14/s2-probe-job-5473.txt), [artefacts](artifacts/job-5473/l4-out/) (`probe/*.out`, `probe/summary.txt`, `dry-run/…/2.1-red.prompt.md`) |
| 3 P2: push C1 to `main` | [#2646](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2646) / [5475](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5475) | **pass** — **a.** `$ .l4/bin/l4 doctor --ci --fix`: every `fix … already present`, no download line, PRV rows as in P1, exit 0. **b.** `plan --sweep`: `kiro:add-loyalty-points  -  0/4  implement`; every OpenSpec unit `none`. **c.** `[l4] implementer: codex ok (binary 0.160.0 · auth subscription · quota 3% used (weekly window) · hello 3.8s) → selected`. Ledger under `.kiro/specs/add-loyalty-points/.l4/ledger/`. `task.started` order `2.1, 1.1`. Commits red [`f47cc09`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/f47cc09abc954a37353902e9ee291f8ac9586971) → green [`1866c91`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/1866c9116077dd161293f33dd9100c0e97473d90) for 2.1, then red [`dc36746`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/dc367463ec2be4415c507aa44ad4a1674b363d1d) → green [`3f14b18`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/3f14b181552079ab52ac1a2c43db9a43dfa36bbe) for 1.1. Each has `L4-TDD`, `L4-Agent: codex/gpt-6-luna` and `[skip ci]`, and their pipelines were `skipped`. Parent `2.` is ticked in 2.1's green commit and `1.` in 1.1's; `1.2` stays `- [ ]*` and was never started. Base..H changes `tasks.md` at exactly 4 byte offsets (26, 64, 305, 328: `' '→'x'`). Every `step.started` has its `step.finished` (4/4, status ok), with `wip.snapshot` per step. **d.** `verify.step 0` ok; gates setup/lint/test pass (24 tests); `[l4] judges: claude-code ok (… quota 2% used (weekly (all models)) · hello 3.4s) → selected`; `verdict PASS (round 1, 4/4 criteria pass, 3 finding(s))` with rows `Req 1.1`…`Req 1.4`; `independence: verified (different_vendor)`; `verification.md` committed in [`c42ec28`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c42ec284fd9790cde94cd0cbad6db5a7fb69020c). **e.** H [`940c6ff`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/940c6ff5ebdcf0849eb978a8692a6c7d84a19ca1) has no `[skip ci]`; its pipeline [#2657](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2657) ran only `test` (job 5476, success). **[MR !13](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/13) `[l4] add-loyalty-points` ready, `l4:in_review`, head = H**. Run tail in `refs/l4/locks/kiro/add-loyalty-points` (`71d071e`). **f.** `run finished: exit 0 in 192.9s, cost $0.1038`; job success in 208 s; `l4.env` `L4_EXIT=0`, `L4_PHASES=kiro:add-loyalty-points=in_review`; `.l4-out/logs/r-20261004T1741Z-3ebb.jsonl` (160 lines), no token shape | [job log](m14/s3-p2-job-5475.txt), [commits + trailers](m14/s3-add-loyalty-points-commits.txt), [tasks.md bytes](m14/s3-add-loyalty-points-tasks-md.txt), [verification.md](m14/s3-add-loyalty-points-verification.md), [ledger extract](m14/s3-ledger-extract.txt), [full run ledger](m14/s3-add-loyalty-points-ledger-pending.jsonl), [artefacts](artifacts/job-5475/l4-out/) |
| 4 read-only: P1's prediction vs P2 | — | **pass** — P1 `task=2.1 (red)`, codex; P2's first `step.started` = `{task 2.1, phase red, attempt 1, agent codex}`. P1 left no ref (11 refs before = after, none under `kiro`), no branch and no MR (MR !13 was created at 17:42:07Z by P2's job, which started at 17:41Z). `probe/m14` was deleted after the G7 run; the probe's scratch dir is gone from the runner | [comparison + hand-off facts](m14/s4-dry-run-vs-p2-and-handoff.txt) |
| G7 `L4_LIVE=1 pytest tests/live/test_m1_4_acceptance.py -m live` | — | after step 2: 3 passed, 4 skipped (step 3 not yet). After step 3, **as committed (`c9e2c0d`): 5 passed, 2 failed**, both G7 bugs (below). **At `6eaee92`: 7 passed** | [after step 2](m14/g7-after-step2.txt), [as-is](m14/g7-asis-c9e2c0d.txt), [fixed](m14/g7-fixed-6eaee92.txt), [ids](m14/g7-ids.json) |
| 5 (optional, HUMAN) merge MR !13 | — | **not run.** Trial merges in a scratch clone show that merging !13 would put every other open unit MR (!4, !5, !8, !10, !12) into conflict in `src/pricing/cart.py`/`__init__.py`. A later protocol's human-merge step may still need those MRs. Left to the maintainer | [trial merges](m14/s5-not-run-merge-conflicts.txt) |
| 6 (optional) GitHub | — | not run: blocked by Q5 (no GitHub repository) | — |

Deviations and findings (V = seen in logs or files, I = inferred):

* **G7 bugs, fixed `6eaee92`** [V]. This is acceptance code in `tests/live`; it is not vendored, so the dummy repo
  needed no upgrade.
  * `test_p2_plan_sweep_lists_the_kiro_unit_and_nothing_else` matched `line.lstrip().startswith(unit)`, but GitLab 17
    prefixes every job-log line with a timestamp and a stream marker (`2026-10-04T17:41:05Z 01O kiro:…`). So it never
    found the plan row, and its "every OpenSpec unit `none`" check passed vacuously.
  * `test_probe_branch_left_no_mr_and_no_unit_branch` re-checked a step-2 postcondition after P2, and failed on P2's own
    MR !13.
  * The fix adds `tests/live/protocol_m14.py` (`log_text`, `command_output`, `plan_rows`, `created_before`), unit-tested
    first in `tests/unit/live_support/test_protocol_m14.py`. The MR check now counts only MRs created before P2's `l4`
    job started, and once P2 has pushed, the refs check reads P1's own `refs-after.txt`. `tests/unit/live_support`:
    21 passed; `ruff check .` clean.
* **Plan expectations that were already met before this run** [V]: the upgrade changed one vendored file and one pin
  scalar, not "`.l4/vendor/`, `.l4/ci/`, `.l4/bin/l4` and two pins". The template line `doctor --ci --fix` reached the
  dummy with M1.2's upgrade to `8dce4b0`, which already contained M1.4.
* **PRV-001 has no `kiro` row** [V]. The plan marked that row [U] (`installed-not-authenticated` or `unknown`). PRV-001
  lists only profiles that are in a role chain, and `profiles.kiro` is in none. The plan's seed comment says the same
  ("reported by PRV-001 only: in no role chain").
* **`opencode` is also in the install list** [V] (`already present`, 1.18.34 at `/usr/local/bin`), because M1.2's
  chains name `opencode-free`. "fix2 makes zero fetches" is read from the absence of any install line or command
  [I]: the doctor JSON has no fetch counter.
* **Judge inputs** [I]. The judge prompt is not an artefact. `ladder.py` builds its sources with the same
  `collect_sources(unit path)` as the implementer prompt, and that prompt carries `<l4:data source="design.md">` and
  `<l4:data source="requirements.md">`. The judge's findings quote the subtotal definition and `tasks.md`'s optional
  1.2. Its prompt sha256 is in `verification.md`.
* **Ledger fidelity** [V, cosmetic]: `task.done{task: 2.1}` and `{task: 1.1}` carry `parents: []`, although `2.` and
  `1.` were ticked in those same commits. `KiroProvider.set_marker` closes the parent itself, so
  `tick_completed_parents` finds nothing left to report. `tasks.md` and `l4 status` (`4/4`) are right.
* **Local `l4 plan` vs CI** [V]: a fresh clone shows the four `in_review` units as `verified → hand_off` until
  `git fetch origin '+refs/l4/locks/*:refs/l4/locks/*'`, because their hand-off tail lives in the lock refs, which only
  the CI ref refresh fetches.
* **Judge findings (minor, not blocking)** [V]:
  * sub-cent subtotal rounding before flooring is unspecified;
  * no loyalty test with quantity > 1;
  * the optional property-based task 1.2 is not done.
* **Spend** [V]: Codex: 4 agent steps (two tasks, red and green) plus one hello; weekly window 3 % used at selection.
  Claude: one judge call, $0.1038, plus one hello. P1 spent nothing.
* **Cleanup:** `probe/m14` deleted, and the runner scratch dir removed by the probe script. Nothing else was created
  besides the protocol's own outputs: C1 on `main`, the unit branch, the lock ref and MR !13. Still open from M1.2:
  `~gitlab-runner/.local/share/claude/versions/99.0.0` (0 bytes) is still on the runner [V, `ls` 2026-10-04]; the
  operator is read-only there.

## 2026-10-04 — M1.3 "verifier depth and fix units" (harness `d1e0631`, live-fixes `e9735ff`, `f0f6524`; G6 fixes `ce43a4b`, `e40e797`)

Live exit protocol of [`docs/plan/m13-plan.md`](../plan/m13-plan.md) ("Live exit protocol on `example-group/dummy-agentic`
through `l4-runner`"), run by the operator acting as human and maintainer. Preconditions as found: M1.1 G13 and
M1.2's protocol (with its cleanup) had passed (sections above); M1.4's protocol had reset M1.3's levers
(`verifier.fix_minor_findings: false`, `roles.verifier_agent: []`), which step 0.4 sets again. Job logs (ANSI and
section markers stripped) and extracts are in [m13/](m13/), job artefacts in `artifacts/job-<id>/l4-out/`. No saved
file has a token shape (`glpat-`, `glcbt-`, `apikey_`, `sk-`).

**Verdict: PASS, by branch 1B then step 2, and steps 3 and 4; after one 1C and two harness live-fixes.**
* P1 (job 5478) went the 1A way up to the fix unit: task 1.1 red with two `zero_value` proofs, the full ladder, PASS
  2/2, one accepted audit test, `add-shipping-fee-fix-1` from three minors.
* Then Codex reported `blocked` on the fix task ("RED test for existing behavior"): a 1C. Diagnosis: two harness bugs,
  fixed test-first on `main` (`e9735ff`: the red prompt lacked SPEC 7.3's already-satisfied line; `f0f6524`: a fix
  unit kept one scenario per criterion instead of one per finding). The dummy was upgraded to `f0f6524` and the unit
  reset by the retry rule.
* The retry (job 5480) ended round 1 NEEDS_HUMAN with two `Kind: verdict` questions (judge majors: the free-shipping
  threshold and the negative-subtotal check were not implemented).
* The operator rejected both with a WHEN/THEN from the requirement text (commit `748cf82`). P2 (job 5482) then
  reused round 1 at aggregation (no judge call), FAILed on the two rejected findings, and created
  `add-shipping-fee-fix-1` holding both scenarios verbatim. Codex implemented the fix task red→green in the same job.
  Round 3 ran the full ladder: PASS 4/4, hand-off, and **[MR !15](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/15)
  is ready with only `l4:in_review`**. Exit 0.

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 local | — | **pass** — 0.1: `uv run pytest -q` at `d1e0631` (under the suite lock) 2666 passed, 50 skipped. 0.2: `l4 plan --json` on a fresh clone of `main` `b0b384d` with `l4/*` and `refs/l4/locks/*` fetched: every unit `none` (`add-vat` `awaiting_human: no new answers`). 0.3: `l4 upgrade` to `d1e0631`: 38 changed and 16 new files, all under `.l4/vendor/` (among them `gates/pytest_trace/l4_trace.py`, `verifier/{audit,evidence,fixloop,fixunit,integrity,traceability,verdicts}.py`), plus `harness.commit`; `.l4/ci/l4.gitlab-ci.yml` and `.l4/bin/l4` unchanged (as in M1.4). 0.4: `roles.verifier_agent: [claude-code]`, `verifier.fix_minor_findings: true`, `max_fix_rounds: 1`, `audit_sample_ratio: 0.1`. 0.5: seed byte-identical to the plan's blocks. 0.6: `openspec validate add-shipping-fee --strict` (1.14.0) valid; `l4 doctor` exit 0 (ENV-004/PRV-001 warn-level fails on the Mac only: no codex there) | [s0-local.txt](m13/s0-local.txt) |
| 1 P1: one push of [`75a00a1`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/75a00a126f024bb0e356801a4f6586b6deaeaff2) "Upgrade the vendored L4 harness to d1e0631 (M1.3)" + [`12f660b`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/12f660bdaea2e86b1e40579897715f16ba55000e) "Seed add-shipping-fee" to `main` | [#2658](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2658) / [5478](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5478) | **1C (Codex `blocked`), exit 11.** Plan: `openspec:add-shipping-fee - 0/1 implement pending tasks`, every other unit `none`. Red [`8131608`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/8131608b74283b271e65d2864d22562ead0aaec7) (`L4-TDD: red`) → green [`ea3eddd`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/ea3edddb7faff239a08c3728b49c02ae8eabfae4) (`L4-TDD: green`); `stub.purity{task: 1.1, stubs: [UnsupportedShippingCountry, shipping_fee], restored: 0}`; `task.red_ok.criteria` = `C-e25f06d8`, `C-1b1fbe16`, both `zero_value` (the stop condition did not fire: the ids reached the report under bwrap). Round 1: rows 0, 1 (6 sub-checks), 2, 3, 4 (2/2 covered, `zero_value`), 4a (`C-1b1fbe16` accepted, `tests/test_l4_audit_c_1b1fbe16_r1.py` in [`e5c5073`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/e5c50736c8150cf02a6876a700e7c2530e84a040) `test(add-shipping-fee): verifier round 1 [skip ci]`, `L4-Phase: verifying`), 9 (`claude-opus-5-5`, `independence: verified (different_vendor)`), 10. `verdict PASS (round 1, 2/2 criteria pass, 3 finding(s))` → `fix.spawned{fix_unit: add-shipping-fee-fix-1, round: 1}`, [`7a079a4`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/7a079a498ef3fa2a9615732c3d980663de93f31c) `docs(add-shipping-fee): fix unit 1 [skip ci]` (`.openspec.yaml`, `proposal.md`, `tasks.md`, `.l4/fix.json`, `specs/shipping/spec.md` with `Shipping fee — regression 1`), `verifying → verified → fixing`. Then `[add-shipping-fee-fix-1] question Q-001 raised (ambiguous): RED test for existing behavior` (Codex: "A test asserting the requested result would pass, which conflicts with the RED-phase requirement that new tests fail"), [MR !14](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/14) `l4:fixing`, `l4:needs-answers` | [job log](m13/s1-p1-job-5478.txt), [commits](m13/s1-p1-commits.txt), [verification round 1](m13/s1-p1-verification-round-1.md), [fix unit + code](m13/s1-p1-fix-unit-and-code.txt), [ledger](m13/s1-p1-ledger.jsonl) ([extract](m13/s1-p1-ledger-extract.txt)), [blocked agent reply](artifacts/job-5478/l4-out/agent/r-20261004T1934Z-f30b/1.1-red-1-r2.jsonl) and [its prompt](artifacts/job-5478/l4-out/agent/r-20261004T1934Z-f30b/1.1-red-1-r2.prompt.md), [artefacts](artifacts/job-5478/l4-out/) |
| live-fixes, then the retry rule | — | Harness `main`: `e9735ff` (red@3), `f0f6524` (per-finding scenarios), plus `ce43a4b` (G6). Affected chunks (implementer, sim, verifier, orchestrator, gates, planner, specs, `test_openspec_fix_unit.py` with `L4_LIVE=1` on 1.14.0) green, `ruff check .` clean. Dummy: `l4 upgrade` to `f0f6524` (3 vendored files + the pin) in [`8ff4f03`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/8ff4f030617b06e39a905172d9db608ea46ee1bb) `[skip ci]` (its push pipeline #2671 `skipped`). Reset: MR !14 closed, `l4/openspec/add-shipping-fee` deleted; there was no `refs/l4/locks/openspec/add-shipping-fee` (P1 released its lock; the ledger lived on the branch). `l4 plan --json` then: `add-shipping-fee implement`, every other unit `none` | [s1-retry-reset.txt](m13/s1-retry-reset.txt) |
| 1 retry: one pipeline on `main` (API, `ref=main`) | [#2672](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2672) / [5480](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5480) | **1B, exit 11.** Red [`3319cb2`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/3319cb24a7d5ee0b7c7fc82196d83570ef21729c) → green [`231f341`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/231f3413ed0e7e66cb466075e51d5bbfcac20705), both criteria `zero_value`. Round 1: same ladder, 2/2 covered, audit `C-1b1fbe16` accepted ([`2e06216`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2e06216d43e7506aa5c8bf4b5648b6b281d0f312)), judge `judge@3`, `independence: verified`. Codex had implemented only the two scenarios: the judge raised two majors from the requirement text, `Free shipping at subtotal >= 50.00 not implemented` (F-f2c8f81d) and `Negative subtotal does not raise ValueError` (F-a0fac71a). `verdict NEEDS_HUMAN (round 1, 2/2 criteria pass, 3 finding(s))`, `question Q-001/Q-002 raised (verdict)`, each `Blocking tasks: none`; [MR !15](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/15) draft, `l4:awaiting_human`, `l4:needs-answers`, sticky "Waiting for a human answer" listing both | [job log](m13/s1-p1r-job-5480.txt), [verification round 1](m13/s1-p1r-verification-round-1.md), [questions.md](m13/s1-p1r-questions-at-46b01dc.md), [sticky note](m13/s1-p1r-mr15-sticky.md), [ledger](m13/s1-p1r-ledger.jsonl), [artefacts](artifacts/job-5480/l4-out/) |
| 2 the operator, as the human: one commit [`748cf82`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/748cf82c9ff9b71e7b14571802298521ff7ada00) on `l4/openspec/add-shipping-fee`: Q-001 `reject: WHEN an order with a subtotal of 50.00 ships to RO THEN the shipping fee is 0.00` (the protocol's text), Q-002 `reject: WHEN an order with a subtotal of -1.00 ships to RO THEN a ValueError is raised` (from the requirement text), both `answered` | [#2681](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2681) / [5482](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5482) | **pass, exit 0.** Plan `openspec:add-shipping-fee awaiting_human 1/1 verify verdicts answered: Q-001, Q-002`. `question Q-00{1,2} answered by human`, two `human.verdict{decision: reject, by: human}`, `awaiting_human → verifying (verdicts_answered)`. Round 2: steps 0–9 `reused (round 1)`, no `verify.judge` for round 2, `verdict FAIL (round 2, …)` on the two `[major, human]` findings. `fix.spawned{fix_unit: add-shipping-fee-fix-1, consumed: [Q-001, Q-002]}`, [`6adf550`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/6adf550ed1e3997d22625ce37cf4727488a82a02) `docs(add-shipping-fee): fix unit 1`: `### Requirement: Shipping fee — regression 1` with both operator scenarios verbatim (new criteria `C-8cf4dd8e`, `C-38128a5b`), task `1.1 … (F-f2c8f81d, F-a0fac71a; C-e25f06d8, C-8cf4dd8e, C-38128a5b)`. `verifying → fixing (verify_fail_fix)`. Fix task: red attempts 1–2 refused (`no new test traces C-e25f06d8`), attempt 3 red [`0051b41`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/0051b41a314af202d97310792598221a4dc86742) (`L4-Unit: openspec:add-shipping-fee-fix-1`, 2 × `red_assertion` + `criterion.pre_satisfied` for `C-e25f06d8`) → green [`6080880`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/60808804393113223dbbf2f642e8f2eaec1368ce); `fix.done`, `fixing → verifying (fix_unit_done)`. Round 3, full ladder: 4/4 covered, audit `C-e25f06d8` accepted ([`bf7fb30`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bf7fb30f5a1b9ba9f66b9e9e30be4df4fec55659)), `verdict PASS (round 3, 4/4 criteria pass, 3 finding(s))`, the three minors "not converted: fix rounds used 1/1". Hand-off H [`390aa7e`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/390aa7eacae3abc10b0b3d676b29132c5ef60254) `docs(add-shipping-fee): hand off to review`; `MR !15 marked ready for review`, labels `l4:in_review` only, head = H, sticky "Nothing is waiting for a human answer."; `refs/l4/locks/openspec/add-shipping-fee` (`ac1fcc3`) holds `ledger-pending/r-20261004T2013Z-f889.jsonl` (103 events). `run finished: exit 0 in 223.9s, cost $0.2040`; `L4_PHASES=openspec:add-shipping-fee=in_review` | [job log](m13/s2-p2-job-5482.txt), [answer commit](m13/s2-human-answer-commit-748cf82.diff), [verification round 2](m13/s2-p2-verification-round-2.md), [round 3](m13/s2-p2-verification-round-3.md), [fix unit + code at H](m13/s2-p2-fix-unit-and-code-at-h.txt), [commits + trailers](m13/s2-commits-8ff4f03..390aa7e.txt), [ledger extract](m13/s2-ledger-extract.txt), [branch ledger](m13/s2-p2-ledger-branch.jsonl), [pending ledger (lock ref)](m13/s2-p2-ledger-pending.jsonl), [sticky](m13/s2-p2-mr15-sticky.md), [artefacts](artifacts/job-5482/l4-out/) |
| 3 loop safety, read-only over pipelines #2658–#2692 | — | **pass** — every push and MR pipeline on a `[skip ci]` checkpoint is `skipped` with no job (red, green, verifier round, verification, fix unit, questions, ledger). H's pipeline [#2692](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2692) ran only `test` (job 5483, success). No `l4` job ran on an `l4-bot` commit: the three `l4` jobs ran on the operator's seed push (5478), the retry rule's API pipeline (5480) and the operator's answer push (5482) | [s3-loop-safety.txt](m13/s3-loop-safety.txt) |
| 4 read-only, on a checkout of H | — | **pass** — `openspec validate add-shipping-fee-fix-1 --strict` valid (and `add-shipping-fee`); per (unit, task): `openspec:add-shipping-fee 1.1` red `3319cb2` before green `231f341`, `openspec:add-shipping-fee-fix-1 1.1` red `0051b41` before green `6080880`; both audit files (`tests/test_l4_audit_c_1b1fbe16_r1.py`, `tests/test_l4_audit_c_e25f06d8_r3.py`) carry `@pytest.mark.l4` | [s4-readonly-on-h.txt](m13/s4-readonly-on-h.txt) |
| G6 `L4_LIVE=1 pytest tests/live/test_m1_3_acceptance.py -m live` | — | before step 1 (`tests/live` at `fc05dc9`, identical to `d1e0631`): 7 failed on an HTTP 404 (the unit branch did not exist yet), fixed in `ce43a4b` (after the reset: 1 passed, 8 skipped). After step 1 (retry): 4 failed, 2 passed, 3 skipped: six bugs in G6 (below), fixed in `e40e797`. **After step 4, at `e40e797`: 7 passed, 2 skipped** (1A did not happen; step 5 not run) | [after the reset](m13/g6-after-reset-ce43a4b.txt), [after step 1, as-is](m13/g6-after-step1.txt), [after step 4, fixed](m13/g6-after-step4-fixed.txt), [ids](m13/g6-ids.json) |
| 5 (optional, HUMAN) merge MR !15 | — | not run: left to the maintainer, as with !13 in M1.4 | — |

Deviations and findings (V = seen in logs or files, I = inferred, U = not checked):

* **Harness bug 1, fixed `e9735ff` (red@3)** [V]. SPEC 7.3 lists a red-template line, "If the behaviour already
  exists, write the tests and report `tdd_exemption: {reason: "already_satisfied by <task|commit>"}`" (spikes/02).
  red@2 lacked it and said only that new tests MUST fail. A fix unit's regression scenario pins what the code does now
  (D6: the judge's `suggested_fix` describes current behaviour), so P1's fix task asked Codex for tests that must fail
  against code that already behaved so; Codex blocked. red@3 adds the line and tells the agent to write the tagged
  tests against the existing code and report `done`; the pre-satisfied check (L4-IMP-002) decides. P2's red attempt 3
  used it: one `criterion.pre_satisfied` test beside two failing ones.
* **Harness bug 2, fixed `f0f6524`** [V code, test; I for P2]. `plan_fix_unit` groups the findings of one criterion
  into one task but kept only the first finding's WHEN/THEN (`cand.scenario = cand.scenario or scenario`). In P1,
  three minors on `C-e25f06d8` became one task that cited all three, with one scenario (49.995); the NaN and -0.00
  scenarios were pinned by nothing. The protocol expects "one scenario per converted finding". With the old code, P2's
  second reject (`-1.00 → ValueError`) would have been dropped the same way [I]. P2's fix unit holds both.
* **G6 bugs (acceptance code, not vendored)** [V]:
  * `ce43a4b`: `LiveGitLab.pages` raised on GitLab's 404 for a tree of a branch that does not exist yet, so seven tests
    failed before step 1 instead of skipping.
  * `e40e797`:
    * the unit branch lists `main`'s history, so the 1.1 TDD count included `add-discount-codes`' 1.1;
    * the operator's `[skip ci]` upgrade commit counted as a harness checkpoint;
    * `of_type(events, kind, **where)` could not filter a field named `kind`;
    * a fix unit's `task.red_ok{task: 1.1}` was read as the parent's;
    * `fix.spawned` also happens in 1B, so 1A ran and 1B skipped;
    * `task.red_ok` has no `sha` since C22;
    * step 4 took a `pr.updated` for a hand-off, while the real `in_review` change lives in the lock ref, which the API
      cannot read.

    Pure rules in `tests/live/protocol_m13.py`, unit-tested in `tests/unit/live_support/test_protocol_m13.py`
    (28 passed).
* **Pin moved mid-protocol** [V]: P1 ran on `d1e0631`; the retry and P2 ran on `f0f6524` (`d1e0631` plus the two
  live-fixes, both re-tested). M1.3's levers were not touched by the upgrade.
* **Retry pipeline source** [V]: the retry rule says "one web pipeline"; it was started through the API (`source:
  api`). The job rule treats `web` and `api` alike.
* **Why P1 and the retry differ** [V]: in P1 Codex implemented the whole requirement (threshold, negative check), so
  the judge found only minor spec gaps (1A). In the retry it implemented only the two scenarios, so the judge found two
  majors that no deterministic check confirmed (1B). Each branch was taken for the reason the plan gives.
* **Fix task citing the parent criterion costs attempts** [V]. The fix task cites `C-e25f06d8` (the criterion the
  findings named) beside the two new ones. Codex's red attempts 1 and 2 tagged only the new criteria ("The existing
  tagged test covers the Romanian below-threshold criterion"). They were refused with `no new test traces C-e25f06d8`;
  attempt 3 added a pre-satisfied test. Within the attempt budget, but worth a design look.
* **`guard.violation{rule: "run ledger", action: restored}`** in the fix task's green step [V]. It is listed in round
  3's "Guard events". The ledger has no gap (seq 1–103 contiguous) [V]. Cause not investigated [U]: the harness's own
  appends during the child workbench's agent step are the likely trigger [I].
* **Cosmetic** [V]:
  * `task.red_ok.frozen` lists 28 vendored sim fixture files (`.l4/vendor/src/l4/sim/builtin/fixtures/**`) beside
    `tests/test_shipping.py`;
  * round 3's findings read "(spec gap) (spec gap)";
  * the trace prints `question Q-001 raised (verdict): None` (already known, merge log);
  * the fix task's red line reads `3 new test(s) failing as expected` while the gate shows 2 failing and 1 passing
    (the pre-satisfied one);
  * `stub.purity` and `task.red_ok` of a fix unit share the parent's ledger and task key; they carry a `fix_unit` field.
* **Spend** [V]:
  * Codex: P1 3 agent steps (red, green, the blocked fix red); retry 2; P2 4 (3 red attempts and 1 green); weekly
    window 3 % used at each selection.
  * Claude (`claude-opus-5-5`): 6 calls (3 judge, 3 audit), $0.1508 + $0.1185 + $0.2040 = $0.4733.
* **add-vat (MR !5) was not exercised: the requested verdict question does not exist** [V]. (Done on 2026-10-05 through the legacy-round path: see "add-vat (legacy round)" below.) `!5`'s NEEDS_HUMAN is
  M0-era (round 1 by `judge@2`, `traceability: not checked (M0)`). Its `questions.md` holds only Q-001 (`ambiguous`,
  answered and consumed in M1.1), and its ledger has no `question.raised{kind: verdict}`. So under M1.3 its plan is
  `awaiting_human: no new answers`, and no human answer can bring it back to verifying. Two routes were rejected:
  * a hand-written `Kind: verdict` question: the planner reads verdict questions from `questions.md`, but
    `consume_verdicts` records only questions the harness raised, so such a question would stay "ready" for ever;
  * a reset of the unit (closing or reusing !5 and deleting its branch): it would discard the M1.1 state, and step 2
    above already ran the requested mechanics end to end. `main`'s `add-vat` spec also still has the conflicting RO
    scenarios (119.00 and 121.00; the human's fix lives only on the unit branch), so a fresh run would start with the
    intake question again unless the maintainer first removes the outdated scenario on `main`.

  Observation for the owner: a pre-M1.3 NEEDS_HUMAN unit has no way back into verification short of a reset. The
  planner/`consume_verdicts` asymmetry for a verdict question the ledger does not know could re-trigger
  VERDICTS_ANSWERED in a loop if a later round ends NEEDS_HUMAN with no verdict question open [I, from the code].
* **Levers left on the dummy** [V]: `roles.verifier_agent: [claude-code]`, `verifier.fix_minor_findings: true`,
  `max_fix_rounds: 1`, `audit_sample_ratio: 0.1`, pin `f0f6524`. By parallel-ownership §4 item 17 and the §5.3 reset
  table, the next protocol's own step 0 resets them (M1.5: `fix_minor_findings: false`, `audit_sample_ratio: 0`).
* **Cleanup** [V]:
  * MR !14 closed and `l4/openspec/add-shipping-fee` (first attempt) deleted by the retry rule; P1's commits stay
    reachable through !14;
  * no probe branch or scratch dir was created;
  * the runner's build dir is not readable by the operator account (`Permission denied`), so harness leftovers there
    could not be checked [U].

### add-vat (legacy round), 2026-10-05 (harness `69ef5b4` on the dummy; live-fixes `69ef5b4`, `a1a0ca3`)

Goal: finish `add-vat` ([MR !5](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5)), parked since 2026-10-04 in `awaiting_human` on a round 1
NEEDS_HUMAN with no verdict question (see "add-vat (MR !5) was not exercised" above), through the legacy-round path of
`7dbf43a` (SPEC L4-VER-013, SCN-VER-47). The operator acted as the human and maintainer. Logs (ANSI and section markers
stripped) are `m13/addvat-*`, job artefacts `artifacts/job-<id>/l4-out/`. No saved file has a token shape (`glpat-`,
`glcbt-`, `apikey_`, `sk-`); the runner's upload lines carry GitLab's own truncated job-token prefix (`token=64_…`,
6 characters), as the M1.3 logs do.

**Verdict: PASS, with deviations.** MR !5 is ready (`draft: false`, labels `l4:in_review` only, head the hand-off
[`30ccf6a`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/30ccf6a281e044fc3e49686f78462699325d44f4), `mergeable`). Step 1 went as planned. Step 3 did not
finish in the one answer pipeline: it took three, for three reasons.
* The human had to merge `main` into the unit branch first (the harness does not, by design so far).
* Codex's first red step on the fix task asked a question, because of harness bug 2 below.
* The three M1.1 criteria had to be accepted by hand: their tests carry no criterion tags.

Harness bug 1 was found in a local rehearsal and fixed before anything went live. Without it the human's reject would
have been dropped live as well.

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 local | — | **pass**. A fresh clone of `main` `8ff4f03` (`l4/*`, `refs/l4/*` fetched). `add-vat` at [`3017899`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/3017899bf57dd1db2a983eb7cbecf6fcb96d722b): round 1 by the **M1.1** harness (`f43a84b`, `judge@2`, not M0). Its `verdict.json` has no `subject_sha` and no `family_criteria`. Findings: major `F-366420f0` "VAT ignores any applied discount code" (criterion `null`, `spec_gap`, `suggested_fix`) and minor `F-051c6652`. Read with the current `read_verdict`/`restore_round` without error. Config reset (parallel-ownership 5.3, M1.4 row): `roles.verifier_agent: []`, `verifier.fix_minor_findings: false`, `max_fix_rounds: 1` kept; `audit_sample_ratio: 0.1` is inert with no verifier agent. `l4 upgrade` to `69ef5b4`: 23 vendored files (22 changed, `verifier/legacy.py` new) plus `harness.commit`. `l4 plan`: `openspec:add-vat awaiting_human 2/2 verify legacy round 1: NEEDS_HUMAN without verdict questions, the run raises them`, every other unit `none`. A local rehearsal on a mirror (`forge.type: local`, no sandbox, no implementer reachable) found harness bug 1 and the step 0 merge requirement (below) | — |
| 1: one push of [`bb5f347`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bb5f34771042df85daf273a0027ac9c0f7430d80) "Upgrade the vendored L4 harness to 69ef5b4 (add-vat legacy-round test); reset M1.3's verifier levers" to `main` (no `[skip ci]`) | [#2693](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2693) / [5485](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5485) | **pass, exit 11, no agent call.** `doctor --ci --fix` all pass. `[l4] openspec:add-vat question Q-002 raised (verdict): None`, then `run: openspec:add-vat: round 1 ended NEEDS_HUMAN without verdict questions (an earlier harness); raised Q-002`, then `commit 7a7d1563dd docs(add-vat): verdict questions [skip ci]`, then `run finished: exit 11 in 0.4s`. Ledger: `question.raised{Q-002, kind: verdict, target: F-366420f0, round: 1}`. The artefacts have no `agent/` directory, and `cost_usd` is unchanged (0.175024, from M1.1). MR !5 stays a draft; labels `l4:awaiting_human` → `l4:awaiting_human`, `l4:needs-answers`; head [`65bce24`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/65bce247a4038114d61d2d5e0e99371a9077ddd4); sticky "Waiting for a human answer: Q-002 (verdict)". Q-002 has `Blocking tasks: none` and carries the M1.1 finding's "It reports behaviour that no scenario pins down" and "Suggested fix:" lines | [job log](m13/addvat-s1-job-5485.txt), [questions.md](m13/addvat-s1-questions-at-65bce24.md), [sticky](m13/addvat-s1-mr5-sticky.md), [ledger](m13/addvat-s1-ledger.jsonl), [artefacts](artifacts/job-5485/l4-out/) |
| 2: the operator, as the human, in one push: [`b16c9fd`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/b16c9fd80a4560878f44dd7c2381b32c8e118bbd) merges `main` (`bb5f347`) into `l4/openspec/add-vat` (clean; nothing of `add-vat`'s own files, `src` or `tests` changes), then [`9e778f6`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/9e778f64271c4438b0e02ec0c5c442640684d1ef) answers Q-002: `reject: WHEN a 10 % discount code is applied to a RO cart with subtotal 100.00 THEN total_with_vat is 108.90`. The text was used as given: the branch spec's RO rate is 21 % ("Romanian customer, current rate", 121.00; `vat.py` `RO: 0.21`), the function is `Cart.total_with_vat(country)`, and 100.00 × 0.90 × 1.21 = 108.90 | [#2696](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2696) / [5487](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5487) | **partial, exit 11.** `question Q-002 answered by human`, then `awaiting_human → verifying (verdicts_answered)`, then `human.verdict{Q-002, target: F-366420f0, reject}`. Round 2 is judged afresh: the M1.1 record cannot be reused, and the merge is a new subject. Judge `claude-opus-5-5`, $0.1639. It re-raised the finding under another title and on `C-5427d9c3` ("The owner's answer on discounts (Q-002) is not implemented…"). The live-fix carried the reject: `[major, human] VAT ignores any applied discount code`, `verdict FAIL (round 2, 0/3 criteria pass, 3 finding(s))`, then `fix.spawned{fix_unit: add-vat-fix-1, consumed: [Q-002]}`. [`501e83e`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/501e83e50aaa89ef1a48d14b386ab4d8c11d3eb7) `docs(add-vat): fix unit 1` holds the human's scenario verbatim under `VAT by country — regression 1` (`C-04e19140`), task `1.1 … (F-366420f0; C-04e19140)`; then `verifying → fixing`. Codex's red step then reported `blocked`: `[add-vat-fix-1] question Q-001 raised (ambiguous): VAT base for discounted carts` ([`4c87e8e`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/4c87e8ebd539b2070547e0901d9bb70b61ef7f06)), because of harness bug 2. Labels `l4:fixing`, `l4:needs-answers` | [job log](m13/addvat-s2-job-5487.txt), [human commits](m13/addvat-s2-human-commits-b16c9fd-9e778f6.diff), [verification round 2](m13/addvat-s2-verification-round-2.md), [fix unit + Q-001](m13/addvat-s2-fix-unit-at-501e83e.txt), [ledger](m13/addvat-s2-ledger.jsonl), [blocked red prompt](artifacts/job-5487/l4-out/agent/r-20261005T0003Z-3ffd/1.1-red-1.prompt.md) and [reply](artifacts/job-5487/l4-out/agent/r-20261005T0003Z-3ffd/1.1-red-1.jsonl), [artefacts](artifacts/job-5487/l4-out/) |
| 2b: the human answers the fix unit's Q-001 in [`1212041`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/12120418139f0a61a7af0efeb132eb682760cd00): "Apply VAT to the discounted total (108.90). This is already decided: add-vat Q-002 …" | [#2705](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2705) / [5489](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5489) | **pass to round 3, exit 11.** `[add-vat-fix-1] question Q-001 answered by human`. Red [`ed5732a`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/ed5732ad6400113d96eec21262c42971c8efcf7e): `1 new test(s) failing as expected`, `test_cart_total_with_vat_uses_discounted_total`, `@pytest.mark.l4("C-04e19140")`, `red_assertion`. Green [`a6f7e24`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/a6f7e241599d6cdcf005e929c82117052ea13623): `self.subtotal()` → `self.total()`, 22 passed. Then `fixing → verifying (fix_unit_done)`. Round 3 ran the full ladder (step 0 ok: the branch holds `main`'s head). Judge `claude-opus-5-5`, $0.1901. Traceability 1/4, with the three M1.1 criteria `uncovered`. Result: `verdict NEEDS_HUMAN (round 3, 1/4 criteria pass, 3 finding(s))`, all three findings minor, and `Q-003`/`Q-004`/`Q-005` "accept as satisfied?" | [job log](m13/addvat-s3-job-5489.txt), [verification round 3](m13/addvat-s3-verification-round-3.md), [artefacts](artifacts/job-5489/l4-out/) |
| 3: the human accepts Q-003, Q-004, Q-005 in [`7c2ceb7`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/7c2ceb7f01f87d1130a39b1fba0ef5e4f9000b5b), each naming the passing M1.1 test (`test_cart_total_with_vat_for_supported_countries[RO-…]`, `[DE-…]`, `…rejects_unsupported_country`) | [#2714](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2714) / [5491](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5491) | **pass, exit 0.** Plan `openspec:add-vat awaiting_human 2/2 verify verdicts answered: Q-003, Q-004, Q-005`, then three `human.verdict{accept}`. Round 4 reused round 3 (steps 0–9 `reused (round 3)`, no judge call): `verdict PASS (round 4, 4/4 criteria pass, 3 finding(s))`, `verifying → verified`. Hand-off `30ccf6a` `docs(add-vat): hand off to review`, then `MR … merge_requests/5 marked ready for review`, `verified → in_review`, `MR !5 labels: l4:in_review`, `run finished: exit 0 in 13.7s`, and `L4_PHASES=openspec:add-vat=in_review`. Sticky: "Nothing is waiting for a human answer." `refs/l4/locks/openspec/add-vat` (`ebf195b`) holds `ledger-pending/r-20261005T0020Z-a44c.jsonl` (25 events) | [job log](m13/addvat-s4-job-5491.txt), [questions.md](m13/addvat-s4-questions-at-7c2ceb7.md), [verification round 4](m13/addvat-s4-verification-round-4.md), [sticky](m13/addvat-s4-mr5-sticky.md), [pending ledger](m13/addvat-s4-ledger-pending.jsonl), [ledger extract, all four runs](m13/addvat-ledger-extract.txt), [artefacts](artifacts/job-5491/l4-out/) |
| loop safety, read-only over #2693–#2717 | — | **pass.** `l4` jobs ran only on the operator's four pushes (5485, 5487, 5489, 5491). Every `l4-bot` `[skip ci]` commit's push and MR pipeline is `skipped` with no job. The hand-off's pipeline [#2717](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2717) ran only `test` (5492, success). No `guard.violation` in any of the four runs (the M1.3 "run ledger restored" event did not recur) | [addvat-loop-safety.txt](m13/addvat-loop-safety.txt) |
| 5 (optional, HUMAN) merge MR !5 | — | not run: left to the maintainer | — |

Deviations and findings (V = seen in logs or files, I = inferred, U = not checked):

* **Harness bug 1, fixed in `69ef5b4` before the live run** [V, rehearsal and test]. A human `reject` of a judge finding
  was dropped in a round judged afresh.
  * A finding's id hashes its title and criterion. In the rehearsal the round-2 judge re-raised `F-366420f0` on
    `C-5427d9c3` as `F-0b6dec97`.
  * `_finalize` applies verdicts only to the current round's ids, so the round ended NEEDS_HUMAN and asked the same
    thing again (`Q-006`). With no re-raise at all, the unit even PASSed over the reject (a new test).
  * This broke SCN-VER-47's last clause and L4-VER-013's "a dispute cannot loop". The fixture test passed only because
    its fake judge repeated the finding byte for byte.
  * Fix: `carry_rejects`. An unconsumed reject moves to this round's judge finding of the same title, else the stored
    finding comes back as the human's. Live, the judge renamed the finding, so the second branch (the carried finding)
    is the one that ran.
  * Tests: chunks verifier, implementer and gates gave 732 passed and 1 skipped. Orchestrator, archive, state, vcs,
    specs, planner and sim gave 640 passed and 2 skipped. `ruff check .` is clean. `check_spec` reports 148
    requirements and 309 scenarios (new SCN-VER-48).
* **Harness bug 2, fixed in `a1a0ca3` after the live run; not vendored** [V]. The fix unit's `proposal.md` cut the
  finding detail at 600 characters, and the cut fell on the human's decision appended at its end ("… gives 108.90.
  [reject..."). Codex then read "Two reasonable implementations give different answers" with no decision and blocked.
  * M1.3's `add-shipping-fee-fix-1` proposal lost its second decision the same way ("an…"); Codex did not block there.
  * Fix: the task detail starts "Decided by human in Q-NNN: <reason>." (L4-VER-006).
  * Tests: the same chunks gave 734 passed and 1 skipped, and 640 passed and 2 skipped; `ruff` is clean.
  * The dummy stays pinned at `69ef5b4`. `add-vat-fix-1` was already committed, `max_fix_rounds: 1` allows no
    other fix unit, and an upgrade would move `main` and force another merge before a full-ladder round.
* **Step 0 needs the base head; the human merged it** [V]. The rehearsal's answer-only run stopped with `cli: the unit
  branch does not contain the base head (main); merge it in first (M1)` (exit 1). `merge_base_into` is deferred
  (implementation-map, state-vcs-locks 1.27/1.28), so the operator merged `main` into the branch in the answer push
  (`b16c9fd`). Side effect: the branch now has `main`'s CI include (`doctor --ci --fix`). Any later move of `main`
  needs the same merge before a round that runs step 0.
* **The legacy-unit tax** [V]. The M1.1 tests (`tests/test_vat.py`) carry no `@pytest.mark.l4` tags, so under M1.3 a
  fresh round always finds the three original criteria `uncovered`, and the human must accept each one. This is by
  design: `aggregate_criterion` asks for an uncovered criterion even with `sdd.require_traceability: false`. It cost
  the third answer pipeline.
* **The M1.1 record is not M0** [V]. SCN-VER-47 and the fixture (`M0_FINDING_KEYS`) call it M0, but round 1 ran on
  `f43a84b` and stored `spec_gap` and `suggested_fix`. So the live Q-002 carries "It reports behaviour that no
  scenario pins down" and a "Suggested fix:" line, which the implementer's quoted fixture text lacks.
* **Left open on the unit (all minor, not converted, `fix_minor_findings: false`)** [V, round 4 report]:
  * The parent requirement still says "cart subtotal plus VAT", while the code and the regression scenario use the
    discounted total. The maintainer should reword it before merging !5.
  * Double rounding: `total()` quantizes, then `total_with_vat` quantizes again.
  * The country code lookup is case-sensitive.
* **Design observation** [I]. The contract line "If … a criterion contradicts another criterion or existing behaviour,
  change nothing and report status blocked" holds for every fix unit by construction: a regression scenario
  contradicts current behaviour. Codex did not cite it here, but it may.
* **Cosmetic** [V]:
  * `question Q-00N raised (verdict): None` (known).
  * Step 1's ledger records no `pr.*` event, though the labels and sticky changed.
  * Round 4's report repeats round 3's judge cost ($0.1901) as "Cost" although no call was made.
* **Spend** [V]:
  * Live Claude judge (`claude-opus-5-5`): 2 calls, $0.1639 + $0.1901 = $0.3540. `outcome.json` `cost_usd` went
    from 0.175024 to 0.529101 (cumulative since M1.1).
  * Codex: 3 agent steps (the blocked red, then red and green).
  * Local rehearsal on the operator's Claude subscription: 2 judge calls (`claude-sonnet-5-5`), $0.0985 + $0.0189.
* **Levers left on the dummy** [V]: `roles.verifier_agent: []`, `verifier.fix_minor_findings: false`,
  `max_fix_rounds: 1`, `audit_sample_ratio: 0.1` (inert), pin `69ef5b4`. No GitLab project setting was changed.
* **Cleanup** [V]:
  * No probe branch was created.
  * The rehearsal's mirror and clones are in the session scratchpad only.
  * The rehearsal's worktree and lock file under `~/.cache/l4` were removed.
  * The runner's build dir was not checked [U].

## 2026-10-05 — M1.7 "the base merge at verification step 0" (harness `319eb14`, live-fixes `ba54759`, `12cc820`)

Live protocol of [`docs/plan/m17-plan.md`](../plan/m17-plan.md) ("Live protocol on `example-group/dummy-agentic`"), run by the
operator acting as human and maintainer. M1.7 was landed on harness `main` first: `319eb14` merges `m17` (`055289d`)
into `main` (`f48b82e`, M1.5 included). Two conflicts were resolved by keeping both sides: the `base_moved` import in
`src/l4/sim/dryrun.py`, and in `src/l4/verifier/ladder.py` `VerifyContext.base_note` next to M1.5's `ui_writer`/`s1`
(field and call). Job logs (ANSI and section markers stripped) and checks are in [m17/](m17/), job artefacts in
`artifacts/job-<id>/l4-out/`. No saved file has a token shape (`glpat-`, `glcbt-`, `apikey_`, `sk-`). The runner's
upload lines carry GitLab's own truncated job-token prefix (`token=64_…`, 6 characters), as earlier logs do.

**Verdict: PASS, after two harness live-fixes, with deviations.**
* **Clean merge (A, `add-item-count`).** Step 0 merged `main` into the unit branch as a two-parent `[skip ci]` commit and
  pushed it at once. The full ladder 0–10 then ran on the merged tree (no `reused`), with PASS 2/2, and the hand-off H.
  [MR !18](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/18) is ready, `l4:in_review`, `diverged_commits_count: 0`.
* **Source conflict (B, `add-cart-clear`).** Codex appended `clear()` at the end of `Cart`, where `main` had appended
  `line_count()`. The run exited 1 with a red job, recorded `base.conflict` and `verify.step 0 error`, and pushed no merge
  commit. It set the sticky "Base merge needed".
* **Harness-owned conflict (B).** After `main` reverted the helpers, step 0 merged clean except an add/add
  `questions.md`, which the harness resolved to the branch's bytes (the newer human answer). PASS 2/2, H, and
  [MR !16](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/16) ready. The sticky no longer has "Base merge needed".
* **GitLab skips the merge commit's pipeline** [V]: push #2739 and MR #2740 for A's merge, #2754 and #2755 for B's,
  are all `skipped`. Until this run that was only inferred from the CI template.
* **Two harness bugs were found live and fixed test-first:**
  * `12cc820` is an M1.7 bug: `git merge` needs a committer identity, and the runner has none.
  * `ba54759` is an M1.3 red-gate message that Codex could not act on.

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 local | — | **pass.** The chunked suite at `319eb14`, under the suite lock, gives 3121 passed, 66 skipped, 0 failed, against 3086 and 66 at the M1.5 landing. `ruff check .` is clean. `l4 run --dry-run` on a fresh clone of dummy `main` `bb5f347`, with `l4/*` and `refs/l4/locks/*` fetched, lists no unit and has no `base moved` line: the seven `in_review` units are `none` | [s0-local.txt](m17/s0-local.txt) |
| 1: one push of [`388989d`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/388989db90dd83e0df3eeb1bedc559a20e10c59a) (`l4 upgrade` to `319eb14`: 24 added and 29 changed files under `.l4/vendor/`, plus the pin; `.l4/ci` and `.l4/bin` unchanged; `clarifier.enabled: false`) and [`07cfcea`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/07cfcea927e1f0d0d5d62ef25a47f47296328e43) (the seeds of A and B) | [#2718](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2718) / [5494](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5494) | **pass, exit 11.** Each unit gets `question Q-001 raised (product)`, then `implementing → awaiting_human (questions_blocking)`. Draft MRs [!16](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/16) (B) and [!17](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/17) (A) carry `l4:awaiting_human` and `l4:needs-answers`. Both branches hold only `l4-bot` commits | [s1-job-5494.txt](m17/s1-job-5494.txt) |
| 2: push M2 [`9ffb20f`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/9ffb20f949ccb680a9d9aa2fe42b6eebb4e518c3), a docstring under `class LineItem:` | [#2723](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2723) / [5496](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5496) | **pass.** `run: nothing to do`, exit 0 | [s2-job-5496.txt](m17/s2-job-5496.txt) |
| 3, attempt 1: A's Q-001 answered on the branch ([`f9654aa`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/f9654aa537472dbdf06c9ec57b547e4ec906a3aa)) | [#2724](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2724) / [5498](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5498) | **fail, exit 13, not an M1.7 path.** All three red attempts failed with the same message: `vacuous: C-bc4c166e (its tests pass or error against the zero-value stubs: tests.test_cart::test_new_cart_item_count_is_zero) … a test of an edge case needs a sibling that asserts on a real one`. The scenario "New cart → item count is 0" expects the `int` zero value itself. Codex wrote the sibling test each time, but tagged it only with the other criterion. The unit then went `implementing → halted (breaker_or_budget)`. **Harness bug, fixed in `ba54759`** (below) | [s3-attempt1-job-5498.txt](m17/s3-attempt1-job-5498.txt), [Codex attempt 3](artifacts/job-5498/l4-out/agent/r-20261005T0403Z-de9e/1.1-red-3.jsonl) |
| reset, by the M1.3 retry rule | — | MR !17 closed (it keeps attempt 1's commits) and `l4/openspec/add-item-count` deleted. There was no lock ref | [s3-reset.txt](m17/s3-reset.txt) |
| 3 re-intake: push U [`d070326`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/d070326779dcc884f057a08d899dcb1bcf794e46) (`l4 upgrade` to `ba54759`: 2 vendored files and the pin) | [#2727](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2727) / [5500](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5500) | **pass, exit 11.** A's Q-001 is raised again, in draft [MR !18](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/18) | [s3-reintake-job-5500.txt](m17/s3-reintake-job-5500.txt) |
| 3: push M2′ [`fdc400a`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/fdc400ab83c64815f65adaa1c9d1ac5e81d23077), a module docstring at the top of `src/pricing/cart.py` (A now forks after M2) | [#2730](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2730) / [5502](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5502) | **pass.** `nothing to do`, exit 0 | [s2b-job-5502.txt](m17/s2b-job-5502.txt) |
| 3, attempt 2: A's Q-001 answered again ([`f002840`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/f002840e0ca591406bacba1a1fe144edd173d936)) | [#2731](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2731) / [5504](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5504) | **fail at step 0, exit 1 (`internal_error`).** Red attempt 1 hit the vacuity check again, with the new message. Attempt 2 then passed: Codex tagged the quantities test `@pytest.mark.l4("C-cab85837", "C-bc4c166e")`, so the ba54759 fix is verified live. Green followed, then `implemented → verifying`, then `cli: git merge of the base failed without a conflict: Committer identity unknown`. Nothing was merged or recorded: no `base.*` or `verify.*` event. **M1.7 harness bug, fixed in `12cc820`** (below) | [s3-job-5504.txt](m17/s3-job-5504.txt) |
| 3 (clean merge): push U2 [`0c43167`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/0c43167896b22148961da6864eee7fa52fbaaf78) (`l4 upgrade` to `12cc820`: 2 vendored files and the pin); A is `verifying`, so the `main` job verifies it | [#2738](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2738) / [5506](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5506) | **pass, exit 0.** Merge commit [`dc05253`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/dc05253b41ea26c5a8ab2ec706cf4c97863d9503) has `parent_ids` `[8df73efca7…, 0c43167896…]` (the old head, then the base). Its subject is `chore(add-item-count): merge main@0c43167896 into the unit branch [skip ci]`, with trailers `L4-Unit`, `L4-Run`, `L4-Iteration: 3` and `L4-Phase: verifying`, and its pipelines #2739 and #2740 are `skipped`. The ledger has `base.merged{behind: 2, resolved: [], frozen_touched: []}`, and every `verify.step` has `subject_sha` = the merge. Steps 0–10 ran and none is `reused`; the step-0 note reads "base merged: main@0c43167896 as dc05253b41 (2 commits)". The judge gave PASS 2/2 with 3 minors. H is [`9a14683`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/9a14683cca8f5a4b135d9667de3d195cb9412ef8); its pipeline [#2743](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2743) ran `test` (success) on the merged tree, and `merge-base --is-ancestor 0c43167 H` holds. MR !18 is ready, `l4:in_review`, `diverged_commits_count: 0`, `mergeable` | [s3-verify-job-5506.txt](m17/s3-verify-job-5506.txt), [s3-checks.txt](m17/s3-checks.txt), [verification.md](m17/s3-verification-add-item-count-round-1.md) |
| 4: push M3a [`806c672`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/806c6726bb11372ad6d40c68ac1b41f90e127838) (`add_all` after `add`, `skus` after `subtotal`, `has_code` after `apply_code`, `line_count` at the end of `Cart`), then M3b [`c647207`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c647207a9619945595ce9d5d13e7c5e1abc596f4) (`openspec/changes/add-cart-clear/questions.md` = B's branch file with Q-001 `answered` "yes (main copy, older)") | [#2744](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2744) / [5509](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5509), [#2745](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2745) / [5511](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5511) | **pass.** Both jobs say `nothing to do`: the planner reads B's `questions.md` from the branch, not from `main` [V, `status.py:107`]. The local `l4 run --dry-run --unit openspec:add-cart-clear` prints `base moved: step 0 merges main@c647207a9619 (6 commits behind; changed on both sides: openspec/changes/add-cart-clear/questions.md)` | [s4-m3a-job-5509.txt](m17/s4-m3a-job-5509.txt), [s4-m3b-job-5511.txt](m17/s4-m3b-job-5511.txt), [dry run](m17/s4-dryrun-add-cart-clear.txt) |
| 5 (source conflict): B's Q-001 answered on the branch ([`1190135`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/1190135a58c75f343ddf0d5e6ec5cb130ee1803d)), "yes: clear() also forgets the code (branch, newer)" | [#2746](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2746) / [5513](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5513) | **pass, job red, exit 1.** Red (1 attempt) and green were followed by `verifying` and `base merge conflict with main@c647207a96: src/pricing/cart.py; merge it by hand and push (exit 1)`. The ledger has `base.conflict{files: [src/pricing/cart.py], resolved: [openspec/changes/add-cart-clear/questions.md]}` and `verify.step{round 1, step 0, status error, reason base-merge-conflict}`, and no `verify.verdict`. The branch head is the ledger commit `3441ffa`, there is no merge commit, and `main` is not an ancestor. MR !16 is `l4:verifying`, with the sticky "### Base merge needed · Merging `main`@`c647207a96` into `l4/openspec/add-cart-clear` conflicts in src/pricing/cart.py. …" | [s5-job-5513.txt](m17/s5-job-5513.txt), [s5-checks.txt](m17/s5-checks.txt) |
| 6 (harness-owned conflict): push M4 [`703a776`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/703a7768d6731c56dc253e3f12e14ba865e516fd) = `git revert` M3a | [#2753](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2753) / [5515](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5515) | **pass, exit 0.** The dry run, taken right after the push, prints `7 commits behind; changed on both sides: openspec/changes/add-cart-clear/questions.md, src/pricing/cart.py`. The job made merge [`46cfa14`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/46cfa14b88814a730520a8f4fb232a84ac20b257) with parents `[3441ffa8ba…, 703a7768d6…]`. Its pipelines #2754 and #2755 are `skipped`, and the ledger has `base.merged{behind: 7, resolved: [openspec/changes/add-cart-clear/questions.md], frozen_touched: []}`. The merged `questions.md` is **byte-identical to the branch file** (sha256 `59e484b8…`, the same in `3441ffa`; `main`'s copy is `09d21038…`), and the branch answer was kept. The merged `cart.py` has `main`'s two docstrings and the branch's `clear()`. The full ladder gave PASS 2/2. H is [`a8764fd`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/a8764fd24878e91fc03234993cb903fcbae009e5), its pipeline [#2758](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2758) ran `test` only, and MR !16 is ready, `diverged_commits_count: 0`. The sticky now reads "Nothing is waiting for a human answer." | [s6-job-5515.txt](m17/s6-job-5515.txt), [s6-checks.txt](m17/s6-checks.txt), [dry run](m17/s6-dryrun-add-cart-clear.txt), [verification.md](m17/s6-verification-add-cart-clear-round-1.md) |
| 7 (optional, verdict path) | — | **not run**: A and B both passed round 1, so neither ended NEEDS_HUMAN | — |
| cleanup: push [`274a02d`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/274a02d43c0112b49ef5baf0daf98cb18f763dc0) (the `clarifier.enabled` line deleted) | [#2759](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2759) / [5518](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5518) | **pass.** `nothing to do`, exit 0. MRs !16 and !18 stay open for the maintainer | [cleanup-job-5518.txt](m17/cleanup-job-5518.txt) |
| loop safety, read-only over #2718–#2759 | — | **pass.** The 12 `l4` jobs ran only on the operator's pushes, and none on an `l4-bot` commit. All 24 pipelines whose head is a `[skip ci]` commit are `skipped` with no job, among them the four of the two merge commits. The two hand-offs ran only `test` | [loop-safety.txt](m17/loop-safety.txt) |

The trace lines of the two merges (jobs 5506 and 5515) and of the conflict (job 5513):

```
[l4] openspec:add-item-count commit dc05253b41 chore(add-item-count): merge main@0c43167896 into the unit branch [skip ci]
[l4] openspec:add-item-count pushed l4/openspec/add-item-count 8df73efca7..dc05253b41 https://gitlab.example.com/example-group/dummy-agentic/-/compare/8df73efca7af477fc95ddf93c2a551fa0ba5705d...dc05253b41ea26c5a8ab2ec706cf4c97863d9503
[l4] openspec:add-item-count base merged: main@0c43167896 into l4/openspec/add-item-count as dc05253b41 (2 commits)
[l4] openspec:add-cart-clear base merge conflict with main@c647207a96: src/pricing/cart.py; merge it by hand and push (exit 1)
[l4] openspec:add-cart-clear commit 46cfa14b88 chore(add-cart-clear): merge main@703a7768d6 into the unit branch [skip ci]
[l4] openspec:add-cart-clear pushed l4/openspec/add-cart-clear 3441ffa8ba..46cfa14b88 https://gitlab.example.com/example-group/dummy-agentic/-/compare/3441ffa8ba2a48fb7becf0a1e66308b86563b16d...46cfa14b88814a730520a8f4fb232a84ac20b257
[l4] openspec:add-cart-clear base merged: main@703a7768d6 into l4/openspec/add-cart-clear as 46cfa14b88 (7 commits; resolved openspec/changes/add-cart-clear/questions.md)
```

Deviations and findings (V = seen in logs or files, I = inferred, U = not checked):

* **Harness bug 1 (M1.7), fixed in `12cc820`** [V]. `merge_base_into` ran `git merge --no-ff --no-commit` without an identity,
  and only the commit after it got the bot identity. git asks for a committer identity even with `--no-commit`. The
  runner user has none, and git could not guess one from the host name, so the merge stopped with "Committer identity
  unknown" and the run ended with exit 1 (`MergeRefused`).
  * Every local test passed because git guessed an identity on the Mac. The reviewer's alpine git 2.34 parity check did
    not hit it either [I: an identity was set there].
  * Fix: the merge gets `user.name`/`user.email` as `-c` pairs, like `Git.commit`.
  * Test: `tests/unit/vcs/test_merge.py::test_merge_runs_with_the_bot_identity_when_git_has_none`. It sets
    `user.useConfigOnly`, failed before the fix with the live message, and passes after it.
  * Chunks orchestrator/archive/state/vcs/specs (506 passed, 2 skipped) and verifier/implementer/gates (888 passed,
    3 skipped) are green, and `ruff check .` is clean.
  * The conflict run (step 5) and the second merge (step 6) ran on the fix.
* **Harness bug 2 (M1.3 red gate), fixed in `ba54759`** [V]. A scenario whose expected answer is the zero value itself
  ("New cart → item count is 0") can only be proved by a test that also asserts a real answer. The red template says
  nothing about this. The retry text, "a test of an edge case needs a sibling that asserts on a real one", was read three
  times in a row as "a test of the other criterion".
  * Fix: `Vacuity.message` says to assert a real answer in the same test too, or to tag a test that did fail on the zero
    values with the criterion as well. It names that test and the two-id marker.
  * Tests: `test_vacuity.py::test_the_vacuous_message_names_the_remedy_for_a_zero_answer_scenario` and
    `::test_with_no_proved_test_the_message_still_says_how_to_prove_a_zero_answer`.
  * Chunk verifier/implementer/gates gives 888 passed and 3 skipped, `tests/unit/sim` 88 passed.
  * Live, attempt 2 of the red step used the marker and passed.
  * **Owed:** the same sentence in `red.md` (a red@4 bump), so that the first attempt does not fail. Without it, the
    first red attempt of every such scenario is spent [V: job 5504's attempt 1].
* **The two-id remedy and the judge disagree** [V, A's round 1]. The judge raised a minor, "Quantity-sum test is wrongly
  traced to the New cart criterion", and "the judge called a test inadequate". A test asserting both cases in one body
  (the message's first option) would avoid that. Design note for the owner: the vacuity rule and the judge's view of
  traceability pull apart for an edge-case-only criterion.
* **The judge read the harness-resolved `questions.md` as the implementer's edit** [V, B's round 1]. It raised a minor,
  "The implementer's branch rewrote the human answer in questions.md". The judge's diff is `merge-base...head`. After the
  merge, the merge base is `main`, which holds M3b's copy, so the resolved file shows up as a branch change. This is
  harmless here (minor), but a resolved `questions.md` could be left out of the judge diff, or named in the judge
  prompt [I].
* **Pin moved mid-protocol** [V]. Step 1 ran on `319eb14`, A's re-intake and attempt 2 on `ba54759`, and everything
  from U2 on `12cc820`. B was intaken on `319eb14` and implemented and verified on `12cc820`.
* **More commits behind than planned** [V]. U, M2′ and U2 are `main` commits the plan did not have. A merged 2 commits
  (plan: 1). B's dry runs showed 6 and then 7 (plan: 3 and 4).
* **M3a covers more than the plan** [V]. The plan put a helper only after `add` and at the end of `Cart`. Codex had put
  `is_empty` and `average_unit_price` after `subtotal` on earlier units [V, those branches], so M3a also filled the gaps
  after `subtotal` and `apply_code`. Codex put `clear()` at the end of `Cart`, which the plan covered anyway.
* **Step 3 took two jobs after the reset** [V]. Job 5504 consumed the answer and went red → green → `verifying`. Job
  5506, the U2 push to `main`, verified, so there is no "answers submitted" line in the job that merged.
* **Dry run before step 1** [V]. It showed `implement 1.1` for A and B, but the real run first raised the
  `design.md` question (`awaiting_human`). The dry run does not model intake questions.
* **M1.5 on the dummy for the first time** [V]. These settings were inert or optional here:
  * `memory.serena` is `ok` (startup about 1.4 s).
  * Every agent step logged `guard violation: .serena/project.yml … → removed`, so `settle_serena_project` did not
    recognise what the agent's Serena wrote [U: cause].
    * **Most likely cause [I, not reproduced]:** the two-step write below races the `initialize` reply. On the Mac,
      the normalised form was written 3 ms before the reply (0.841 s and 0.844 s after the start, one probe), and the
      harness reads the file right after that reply. On the runner the order may flip, so that the check keeps the
      9770-byte template while the agent's Serena ends with the 9778-byte form, and every step then reads as a
      mismatch. The new log line (`differs from what Serena wrote at its check (sha256 …, the check's …)`) shows it on
      the next live step if the dummy is not seeded yet.
    * **The race exists [V: Serena 1.7.0 source, review of 2026-10-05]; that it flipped on the runner is still [I].**
      With no `project.yml`, `SerenaAgent.__init__` calls `add_project_from_path(asynchronous_autogen=True)`:
      `ProjectConfig.autogenerate` saves the template with `language_servers: []` at once, then the daemon thread
      `project-language-determination` detects the languages and saves again. Only `create_language_server_manager`
      (a background task) waits for that thread; the MCP `initialize` reply does not, and `_handshake` kills Serena
      right after the reply. The job logs carry no write times, so they cannot settle the order. What they show is
      consistent with it: one `guard.violation{path: .serena/project.yml, action: removed}` per agent step, 8 of 8
      (jobs 5498, 5504: 3 each; 5513: 2), `memory.serena` `ok` at 1379 ms and 1470 ms (Mac: about 840 ms), and
      `?? .serena/` in the agent's own `git status`. Not excluded: the agent's Serena killed by its CLI in the middle of
      that second save. The seed below removes both, since a file in the final form starts no autogeneration.
    * **Follow-up (after this run).** The dummy has no `.serena/project.yml` (`l4 init` never
      wrote one, although SPEC L4-INS-002 says it does). Serena 1.7.0 then generates it at every start, and the settle
      step compares the file with what Serena wrote at the harness's check. Locally (Serena 1.7.0, Mac) the two
      starts give the same bytes, in every variation tried (fresh or used `SERENA_HOME`, minimal environment, other cwd,
      several languages in the tree), so the live cause is [U]. What was found: Serena writes the file in two steps,
      the template and, about 90 ms later, a normalised form (9770, then 9778 bytes), and it rewrites a short or
      missing file into the full form once, then leaves that form alone.
    * **Fix: `l4 init` and `l4 upgrade` seed `.serena/project.yml` in that final form** (harness keys in it,
      `l4/memory/serena_project.yml`; an existing file is never overwritten). The test
      `test_serena_1_7_0_leaves_the_seed_byte_identical` starts a real Serena twice on the seed (run with
      `L4_SERENA_BIN=<serena 1.7.0>`; run on the Mac at landing and again at review) and finds no byte changed. A committed file in this form
      makes the check and the settle step irrelevant, whatever the cause was. A mismatch still logs
      `.serena/project.yml differs from what Serena wrote at its check (sha256 …)`.
    * **To close it:** run `l4 upgrade` in dummy-agentic, commit `.serena/project.yml`, and look for the guard violation
      in the next live agent step. The dummy's own file is not seeded yet [V].
  * Step 8 is `unavailable` ("claude-code: not a backend: system-one profile"), so it spent nothing.
  * No lesson was curated (nothing under `.serena/` on either branch).
* **Cosmetic** [V]:
  * a base-merge conflict ends with `l4 exit 1 (internal_error): harness bug or infrastructure failure`, which reads
    worse than the documented M1 form;
  * `question Q-001 raised (product): None` (known).
* **Left on `main`** [V]. M3b's `openspec/changes/add-cart-clear/questions.md` stays on `main`; merging !16 replaces it
  with the branch's file [I]. M3a is reverted, and `cart.py` keeps the two docstrings.
* **Spend** [V]:
  * Claude (`claude-opus-5-5`): 2 judge calls, $0.0960 + $0.0794 = $0.1754.
  * Codex: 8 agent steps (A: 3 red in attempt 1, then 2 red and 1 green; B: 1 red and 1 green), against 4 planned,
    with the weekly window at 3 % used at each selection.
  * No clarifier, audit or S1 call.
* **Levers left on the dummy** [V]:
  * pin `12cc820`;
  * `clarifier.enabled` deleted (default `true`);
  * `roles.verifier_agent: []`, `verifier.fix_minor_findings: false`, `max_fix_rounds: 1`;
  * `audit_sample_ratio: 0.1` (inert) and `roles.s1_judge: [claude-code]` (step 8 `unavailable`).

  No GitLab project setting was changed.
* **Still open from the M1.7 review** [V]:
  * a ledger file planted on `main` under `<unit>/.l4/ledger/` is merged and folded unchecked (within the trust model);
  * the `lessons.md` union resolver is owed. No unit MR was merged into `main` in this run, so step 0 never met two
    sides of that file.
* **Cleanup** [V]:
  * MRs !16 and !18 are open and ready for the maintainer.
  * !17 (attempt 1) is closed, and its branch is deleted.
  * No probe branch was created.
  * The clones are in the session scratchpad only.
  * The runner's build dir was not checked [U].

## 2026-10-05 — M1.5 "lessons, Serena, Playwright and System One" (harness `2a68eff`, acceptance live-fixes `71970d6`, `8ff9fee`)

Live exit protocol of [`docs/plan/m15-plan.md`](../plan/m15-plan.md) ("Live exit protocol on `example-group/dummy-agentic`
through `l4-runner`"), run by the operator acting as human and maintainer. Decisions that override the plan:
Laya runs on the runner (`engine: laya-local`; no Mac step), and Jev runs (`profiles.jev`: `backend: system-one`,
`engine: jev`, `model: jev-1.13.0` as SPEC 3.2 pins it, `api_key_env: TYPESAFE_API_KEY`, the masked CI variable). The
harness was pinned to `main` `2a68eff` (M1.1–M1.7, docs-only above `1957727`). Job logs (ANSI and section markers
stripped) and extracts are in [m15/](m15/), job artefacts in `artifacts/job-<id>/l4-out/`. No saved file has a token
shape (`glpat-`, `glcbt-`, `glptt-`, `apikey_`, `sk-…`, `mk_agent_`, the Jev key or its prefix: 0 hits over every saved
file of this run).

**Verdict: PASS, steps 0–5 as written (with the S1 arrangement below), and step 6 (Jev) run: the clarifier escalated
on Jev's probabilities.** No harness bug was found. Two bugs in the plan's acceptance code were fixed test-first
(`tests/live` is not vendored, so the dummy needed no upgrade). `tests/live/test_m1_5_acceptance.py` with `L4_LIVE=1`:
**13 passed** at `8ff9fee`.

* P1 (show-item-count) ran end to end in one job:
  * Serena was ready before the first agent step;
  * Codex went red → green;
  * the verifier generated `e2e/test_l4_c_de7f2d3f.py` (base fail, head pass, 1 attempt);
  * step 8 asked Jev (p 0.95), and its shadow half asked Jev and a `laya-serve` started on the runner the same items;
  * the judge gave PASS;
  * lesson `L-09421538` was curated in a `chore(memory)` commit before H.
* P2 (the human merge of !19) opened archive MR !20.
* P3 (show-subtotal): the lesson was injected into every red and green prompt before the first agent session. Codex
  then wrote the e2e test itself (`e2e/test_l4_c_68f2e098.py`), so step 5 generated nothing and the lesson was not
  reinforced (the plan's informational branch A). The verdict was PASS.
* No `.serena/project.yml` guard violation in any agent step: the seeded file closes the M1.7 finding.

**S1 arrangement** (not in the plan; needed to get both engines). `roles.s1_judge: [jev, laya, claude-code]` makes Jev
the S1 of the clarifier and of step 8 (both take the first usable `backend: system-one` profile), and
`verifier.s1.shadow: [laya]` makes step 8's record-only half ask the first usable s1_judge profile (Jev) and then
laya-local the same items (M1.6 `run_shadow`). `claude-code` stays the `llm_boolean` stand-in, which a usable Jev never
reaches.

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 runner | — (mk-ssh) | **pass, no change.** `prereqs.sh --check --with-serena --with-playwright --with-laya`: missing 0, failed 0. PRQ-13 `serena 1.7.0 … pyright 1.1.403 warm`, PRQ-14 `chromium for playwright 1.63.0 in /home/gitlab-runner/.cache/l4/shared/ms-playwright: yes`, PRQ-18 `laya 0.3.24 (pinned 0.3.24), typed-decisions checkpoint cached`. Nothing to `--apply`. The check after the run is identical except PRQ-16's available memory. M15-G2 was not re-run: it is done (pipeline 2549, job 5430, m15-progress line 2), and its P2 question (runner or Mac) is now a decision | [before](../runner/prereqs-2026-10-05-check-m15-live-before.txt), [after](../runner/prereqs-2026-10-05-check-m15-live-after.txt) |
| 0b archive MR !3 merged (operator as human) | [#2760](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2760) / [5520](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5520) | **pass.** Archive MRs open one at a time (`postmerge.py`, L4-ARC-007), and !3 (M1.1) was still open, so step 3's archive MR would have stayed `pending`. [!3](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/3) had no conflicts; merge commit `cae4731`. Job: `[l4] sweeper: openspec:add-discount-codes: lock ref retired to refs/l4/archived/…`, `[l4] run: nothing to do` | [s0b-archive3-job-5520.txt](m15/s0b-archive3-job-5520.txt) |
| 1 local | — | **pass.** `l4 upgrade` to `2a68eff`: 27 added and 26 changed files under `.l4/vendor/` plus the pin, and `created .serena/project.yml (in Serena's own form …)`; `.l4/ci` and `.l4/bin` unchanged. Seeds verbatim from the plan, except `.serena/project.yml` (below). `uv lock`: playwright 1.63.0, pytest-playwright 0.9.0. Locally `pytest -q` 16 passed (e2e not collected), ruff clean, `pytest e2e` against a started `pricing.web.app` 1 passed. `l4 plan`: only `openspec:show-item-count implement`. Local Jev smoke with `jev-1.13.0`: HTTP 200, served `jev-1.13.0` | [s1-local.txt](m15/s1-local.txt) |
| 2 P1: push [`58215b5`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/58215b53f3abe6129e4b636e52d92eb6e7b2e2db) (upgrade) + [`c453c04`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c453c045b8f59f455b4d28fa0a0f91b17fefc47b) "Seed the cart web page, e2e smoke test and show-item-count; enable lessons, Serena, Playwright and Laya (M1.5)" | [#2761](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2761) / [5522](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5522) | **pass, exit 0 in 169.7 s, $0.1196.** **Doctor:** `MEM-001 pass 0 lessons, lint clean`, `ENV-006 pass laya 0.3.24, checkpoint typed-decisions cached`, `ENV-007 pass Chromium for playwright 1.63.0 cached …`, `ENV-008 pass serena 1.7.0`, `S1-001 pass 1 shadow profile(s) usable: laya`. **Plan:** `show-item-count implement`. **Implementer:** `memory.serena{status: ok, startup_ms: 1476}` (seq 12) before the first `agent.session` (seq 17); Codex red → green for 1.1; no `lessons.injected`; no `guard.violation`. **Verifier, ledger order:** steps 0–6, 8, 9, 10 ok (4a `not_run`: ratio 0); step 3 e2e gate 1 test passed; `verify.generated{criterion: C-de7f2d3f, test: e2e/test_l4_c_de7f2d3f.py, base: fail, head: pass, attempts: 1, status: accepted, model: claude-opus-5-5}`; `verify.s1{criterion: C-de7f2d3f, p: 0.95, model: jev-1.13.0, engine: jev}`; `verify.s1_shadow{items: 3, asked: 3, engines: [jev:ok, laya:ok]}`; `laya-serve` started and stopped inside step 8 (its shadow half); judge PASS 1/1, 3 findings (1 deterministic, 2 judge spec gaps, all minor). **Commits:** red [`d3da213`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/d3da213278755df963bfb31a58f5b2b3c040d24b), green [`58c24ac`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/58c24ac9fb5fa9f9310e43ec1b0fd4fc09a9c233), `test(show-item-count): verifier round 1 [skip ci]` [`174a758`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/174a75844f32be180d72a86b8ea945a61ca10da6), `docs(…): verification round 1 [skip ci]` [`bcdf2b4`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bcdf2b48844a1ae37ed6add4bc20c279c16c6ab5), `chore(memory): lesson L-09421538 created [skip ci]` (`L4-Phase: lessons`) [`af0f196`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/af0f1961f00aa7be2c4c1f851910189a258b896f), H [`4f689c8`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/4f689c8ec30da21e8d18b3a44d2afc82362a8d47). **Lesson:** `lessons.curated{action: created, id: L-09421538, origin: verifier_finding_fixed}`; `lessons.md` on the branch has `## L-09421538 · UI criteria need an end-to-end test`, Scope `` `src/pricing/web/**` ``, Dedupe key `ui-criterion-without-e2e-test`. **`verification.md`:** PASS; row `C-de7f2d3f` lists the generated test with base fail / head pass and S1 p 0.95. **MR** [!19](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/19) ready, `l4:in_review`, head = H; H's pipeline [#2770](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2770) ran only `test` (success) | [job log](m15/s2-p1-job-5522.txt), [commits + trailers](m15/s2-show-item-count-commits.txt), [verification.md](m15/s2-show-item-count-verification.md), [lessons.md](m15/s2-lessons-md-on-branch.md), [artefacts](artifacts/job-5522/l4-out/) (`s1/`, `logs/system-one.jsonl`, `logs/laya-serve.log`) |
| 3 HUMAN: merge !19 (operator, API) | [#2771](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2771) / [5525](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5525) | **pass.** Merge commit `ab18818`. `[l4] sweeper: openspec:show-item-count: MR !19 merged`, `archive MR !20 opened`, `[l4] run: nothing to do`. `main` holds `lessons.md` with `L-09421538` and `e2e/test_l4_c_de7f2d3f.py`. The archive push [#2772](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2772) ran only `test` | [s3-p2-merge-job-5525.txt](m15/s3-p2-merge-job-5525.txt), [archive MR !20](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/20) |
| 4 P3: push [`59b0257`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/59b0257784ea6f38f1748a1d6e567c0dccf98aef) "Seed show-subtotal" | [#2773](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2773) / [5528](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5528) | **pass, exit 0 in 247.4 s, $0.0755.** **Lesson injection:** the red prompt holds `<l4:data kind="lessons" ids="L-09421538">`; `lessons.injected{ids: [L-09421538], channel: prompt_section, bytes: 321}` (seq 11) and `prompt.rendered{role: red, lessons: [L-09421538]}` (seq 12) before the first `agent.session` (seq 18), and again before red attempt 2 and before green. `memory.serena{ok, 1410 ms}`. **Red attempt 1 failed:** Codex wrote a Playwright test in `tests/test_web_page.py`, which the test gate runs with no server (`TimeoutError: Locator.inner_text`, "neither an assertion nor NotImplementedError"). **Attempt 2:** Codex wrote `e2e/test_l4_c_68f2e098.py` (`@pytest.mark.l4("C-68f2e098")`) plus a unit test. Green, then e2e gate 3 passed. **Informational branch A:** no `verify.generated`, step 5 ok with nothing generated, no `lessons.curated{reinforced}`. `verify.s1{C-68f2e098, p 0.96, jev-1.13.0}`; `verify.s1_shadow{items 4, engines [jev:ok, laya:ok]}`; PASS 1/1, 3 minor findings. MR [!21](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/21) ready, `l4:in_review`, head = H [`51ddd00`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/51ddd00ca7c75aa5fb29780d358179b2febf616e); H's pipeline [#2780](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2780) ran only `test` | [job log](m15/s4-p3-job-5528.txt), [commits + trailers](m15/s4-show-subtotal-commits.txt), [verification.md](m15/s4-show-subtotal-verification.md), [artefacts](artifacts/job-5528/l4-out/) (`agent/…/1.1-red-1.prompt.md`) |
| 5 read-only checks | — | **pass.** `.l4-out/s1/<run>.jsonl` of P1 and P3: one step-8 row each (`C-de7f2d3f` and `C-68f2e098`), with `engine jev`, `served_model jev-1.13.0`, `p`, a 64-hex `state_sha256` and `judge: pass`, next to the shadow's `item`/`answer` records. No `laya-serve` left (`pgrep -u gitlab-runner -f laya-serve` empty, 08:24Z). All 18 `[skip ci]`-headed pipelines from #2760 to #2785 are `skipped` with no job, and no `l4` job ran on an `l4-bot` commit (the hand-offs and the archive push ran `test` only). Peak memory: the job logs have no peak line (the harness prints none). A read-only sampler during P3 recorded peak `used` 3350 of 3801 MB, swap **2047 of 2047 MB**, `laya-serve` RSS 2079 MB, serena 283 MB, chromium 102 MB | [loop safety](m15/s5-loop-safety.txt), [step 6 loop safety](m15/s6-loop-safety.txt), [pgrep](m15/s5-no-laya-serve-left.txt), [memory P3](../runner/memsample-2026-10-05-m15-p3-job-5528.txt), [memory step 6](../runner/memsample-2026-10-05-m15-step6-job-5531.txt) |
| 6 Jev (the plan's "not run" step, run by decision): push [`2ab5799`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2ab57991483d15afa37e6deacf74b8039ac8884d) "Seed add-cent-rounding", a non-UI unit whose `design.md` lists one `(technical)` open question the code answers (`Decimal`) | [#2781](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2781) / [5531](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5531) | **pass (escalation), exit 11 (allowed failure), $0.1015.** Intake raised Q-001 (`technical`, source `intake_open_questions`). `[l4] … s1_judge: jev ok → selected`. Claude answered "Use `Decimal` … `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`" with three citations of `cart.py`, `confidence: high`. **Jev (`clarifier-s1@2`, `jev-1.13.0`):** router `route_a` 0.99, `route_b` 1.0 (p_technical 0.995, p_product 0.005), internal 0.81; citations shows 0.94/0.97/0.97, opposite 0.03/0.02/0.02, **establishes 0.71/0.65/0.77, each below `establishes_min` 0.80**. The question was escalated to a human, and draft MR [!22](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/22) carries `l4:awaiting_human`, `l4:needs-answers`. Codex did nothing but a hello | [job log](m15/s6-jev-clarifier-job-5531.txt), [questions.md](m15/s6-add-cent-rounding-questions.md), [artefacts](artifacts/job-5531/l4-out/) (`logs/system-one.jsonl`: the 4 Jev requests and answers) |
| cleanup: archive MR [!20](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/20) merged (operator as human; an open archive MR blocks the next one, as !3 did) | [#2786](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2786) / [5533](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5533) | **pass.** Merge commit `655a0e2`. `[l4] sweeper: openspec:show-item-count: lock ref retired to refs/l4/archived/openspec/show-item-count/r-20261005T0840Z-8e41`, `[l4] run: nothing to do`. End of run (08:39Z, mk-ssh): no `laya-serve`, `serena`, Chromium or Codex process of `gitlab-runner` | [s7-archive20-job-5533.txt](m15/s7-archive20-job-5533.txt), [end-of-run check](m15/s7-end-of-run-runner.txt) |
| G8 `L4_LIVE=1 pytest tests/live/test_m1_5_acceptance.py -m live` | — | After P1, at `2a68eff`: `KeyError: 'criterion'` (acceptance bug 1). At `71970d6`: 8 passed, 5 skipped (steps 3–5 not yet run). After P3, at `71970d6`: 11 passed, 2 skipped (acceptance bug 2). **At `8ff9fee`: 13 passed** | [as-is after P3](m15/acceptance-after-step4-asis-71970d6.txt), [final](m15/acceptance-final.txt), [ids](m15/acceptance-ids.json) |

The trace lines (jobs 5522, 5528, 5531). The console trace has no handler for `memory.serena`, `lessons.*`,
`verify.generated`, `verify.s1` and `verify.s1_shadow`, so those are quoted from the run log (`.l4-out/logs/r-*.jsonl`,
ledger events):

```
[l4] openspec:show-item-count gate e2e-base fail (exit 1, 2 tests: 1 passed, 1 failed) — exit code 1
[l4] openspec:show-item-count gate e2e-head pass (exit 0, 2 tests: 2 passed, 0 failed)
[l4] openspec:show-item-count s1_judge: jev ok → selected
[l4] system_one: laya-serve started: pid 135889, port 58763, model typed-decisions, laya 0.3.24
[l4] system_one: laya-serve stopped: pid 135889, exit code -15
[l4] openspec:show-item-count verdict PASS (round 1, 1/1 criteria pass, 3 finding(s))
[l4] openspec:show-item-count commit af0f1961f0 chore(memory): lesson L-09421538 created [skip ci]
[l4] openspec:show-subtotal task 1.1 red attempt 1 failed: new tests fail with an error that is neither an assertion nor NotImplementedError: tests.test_web_page::test_page_shows_demo_cart_subtotal[chromium] (playwright._impl._errors.TimeoutError: …
[l4] openspec:show-subtotal gate e2e pass (exit 0, 3 tests: 3 passed, 0 failed)
[l4] openspec:add-cent-rounding question Q-001 raised (technical): None
[l4] openspec:add-cent-rounding s1_judge: jev ok → selected
[l4] openspec:add-cent-rounding clarifier Q-001: escalated to a human (citation src/pricing/cart.py#L38-L39: S1 p(the cited text establishes the answe…; citation src/pricing/cart.py#L44: S1 p(the cited text establishes the answer)=0…; citation src/pricing/cart.py#L54: S1 p(the cited text establishes the answer)=0…)
[l4] openspec:add-cent-rounding phase clarifying → awaiting_human (clarifier_needs_human)

5522 memory.serena {"status": "ok", "reason": "", "startup_ms": 1476}
5522 verify.generated {"criterion": "C-de7f2d3f", "test": "e2e/test_l4_c_de7f2d3f.py", "base": "fail", "head": "pass", "attempts": 1, "status": "accepted", "model": "claude-opus-5-5", …}
5522 verify.s1 {"round": 1, "criterion": "C-de7f2d3f", "p": 0.95, "model": "jev-1.13.0", "status": "ok", "engine": "jev", "checkpoint": "jev-1.13.0"}
5522 verify.s1_shadow {"round": 1, "items": 3, "asked": 3, "engines": ["jev:ok", "laya:ok"]}
5522 lessons.curated {"action": "created", "id": "L-09421538", "origin": "verifier_finding_fixed"}
5528 lessons.injected {"ids": ["L-09421538"], "channel": "prompt_section", "bytes": 321}
5528 prompt.rendered {"role": "red", "task": "1.1", "template_version": "contract@5+red@4", "lessons": ["L-09421538"], …}
5528 verify.s1 {"round": 1, "criterion": "C-68f2e098", "p": 0.96, "model": "jev-1.13.0", "status": "ok", "engine": "jev"}
5531 clarifier.result {"id": "Q-001", "kind": "technical", "confidence": "high", "auto_accepted": false, "s1_model": "jev-1.13.0", "s1_questions": "clarifier-s1@2", "p_technical": 0.995, "p_internal": 0.81, "citation_support": [0.94, 0.97, 0.97], "citation_opposite": [0.03, 0.02, 0.02], "s1_detail": {"citation1.establishes": 0.71, "citation2.establishes": 0.65, "citation3.establishes": 0.77, …}}
```

S1 answers per engine, shadow half of step 8 (`.l4-out/s1/<run>.jsonl`, `answer` records; `p_true` of the `noul`
questions; `relatedness` is a 0–2 score):

| Job | Item (subject, set) | Jev `jev-1.13.0` | laya-local `typed-decisions` (served `laya-rl-agent`) |
|---|---|---|---|
| 5522 | `src/pricing/web/page.py`, file-relevant@1 (expected relevant) | relevant 0.98, unrelated 0.02, relatedness 2.0 (293 ms) | relevant 0.519, unrelated 0.4075, relatedness 1.35 (10781 ms) |
| 5522 | `tests/test_web_page.py`, file-relevant@1 (expected relevant) | 0.95 / 0.03 / 1.93 (240 ms) | 0.5203 / 0.3511 / 1.39 (9897 ms) |
| 5522 | `tests`, tests-ok@2 (expected all passed) | all_passed 0.99 (245 ms) | all_passed 0.6575 (1433 ms) |
| 5528 | `src/pricing/web/page.py`, file-relevant@1 | 0.98 / 0.02 / 2.0 (278 ms) | 0.5099 / 0.4034 / 1.41 (9032 ms) |
| 5528 | `tests/test_web_page.py`, file-relevant@1 | 0.96 / 0.03 / 1.95 (356 ms) | 0.518 / 0.364 / 1.40 (9938 ms) |
| 5528 | `e2e/test_l4_c_68f2e098.py`, file-relevant@1 | 0.89 / 0.06 / 1.37 (261 ms) | 0.5034 / 0.3937 / 1.36 (12722 ms) |
| 5528 | `tests`, tests-ok@2 | all_passed 0.99 (245 ms) | all_passed 0.6721 (1446 ms) |

Step 8's own question (criterion met) went to Jev only: `C-de7f2d3f` p 0.95, `C-68f2e098` p 0.96.

Deviations and findings (V = seen in logs or files, I = inferred, U = not checked):

* **Acceptance bug 1, fixed `71970d6`** [V]. M1.6's shadow appends `item` and `answer` records (`kind`, no
  `criterion`) to the same `.l4-out/s1/<run>.jsonl` as step 8's rows. The M1.5 tests read every line as a step-8 row,
  so they failed with `KeyError: 'criterion'` on job 5522. This was confirmed by running the `2a68eff` copy of the
  test against the live data. `tests/live/protocol_m15.py` `s1_lines` now splits the shapes. Unit tests are in
  `tests/unit/live_support/test_protocol_m15.py`.
* **Acceptance bug 2, fixed `8ff9fee`** [V]. `unit_commits` took "the branch commits not on `main`". After step 3's
  human merge that set is empty, so the two step-2 commit checks skipped in a run after the protocol: 11 passed, 2
  skipped. It now takes the commits above the seed commit (`commits_above`, unit-tested), which is the same set before
  and after the merge. `ruff check .` is clean, and `tests/unit/live_support` gives 33 passed.
* **`.serena/project.yml` is the seeded full form, not the plan's five-key text** [V]. `l4 upgrade` (`215000b`)
  writes Serena 1.7.0's own form with the harness keys. The plan's short form would be rewritten by Serena at every
  start, which was the M1.7 guard violation. `project_name` was set to `dummy-agentic`; the upgrade had taken the clone
  directory's name. Result: 0 `guard.violation` in 5 agent steps (P1: 2, P3: 3), against 8 of 8 in M1.7. This closes
  that finding live.
* **Serena available to the implementer, not used** [V/I].
  * [V] `memory.serena{ok}` at 1476 and 1410 ms, before the first agent step. This is the harness's own MCP
    `initialize` through the agent wrapper.
  * [V] Codex made no Serena tool call: no `mcp_tool_call` item in its 5 event streams.
  * [I] The P3 sampler saw a `serena` process at 283 MB RSS while Codex ran. That is consistent with Codex starting
    the configured MCP server. The Codex argv is not an artefact, and no agent config with `serena` was left under
    the runner's `~/.cache/l4/units/` (checked at 08:39Z).
* **The lesson works, and its test is not evidence** [V, P3]. In red attempt 1 the injected lesson led Codex to write
  a browser test, but under `tests/`. The lesson says "a browser test that traces it by id" and names no directory,
  and the red prompt does not mention `e2e/` or `L4_E2E_BASE_URL`. So one red attempt was spent [V].
  * The e2e test from attempt 2 is listed under "Not evidence" in `verification.md`: "no proof that it discriminates
    (no red, audit or generated record)". The red gate runs `gates.test` only, so an implementer-written e2e test is
    never red-proved. And because it traces the criterion, step 5 does not generate one either.
  * C-68f2e098 is therefore covered only by its unit test (`red_assertion`). This is the plan's branch A as written.
  * Owner decision [I]: either the lesson text names `e2e/`, or step 5 proves an existing unproved e2e test (base
    fail, head pass) or generates its own.
* **Jev escalated a correct answer** [V, step 6]. The router (0.995 technical) and every `shows` (≥ 0.94) and
  `opposite` (≤ 0.03) check passed. Each citation's `establishes` was 0.65–0.77 against `establishes_min` 0.80, which
  SPEC calls the least calibrated threshold. The suggestion (`Decimal`, `ROUND_HALF_UP`) is right. This is
  calibration data, not a fix. M1.1's auto-accept did not reproduce, and the plan's risk section predicted that for
  Laya. Q-001 is left `open` for a human.
* **Laya vs Jev on the same items** [V]: laya-local is near chance and slow. `relevant` was 0.50–0.52 on files that
  are relevant, against Jev's 0.89–0.98, and `all_passed` was 0.66–0.67 against 0.99. It took 9–13 s per file item
  on the runner, against Jev's 0.24–0.36 s. This matches research/03.
* **Memory** [V]. The VM did not balloon during this run: `free -m` total stayed 3801 MB (08:01Z baseline, both
  samplers, PRQ-16). During P3's shadow half, `laya-serve` reached 2079 MB RSS and swap was **full** (2047/2047 MB).
  The job survived. The "VM balloons to 10 GB" premise did not show here [U: the hypervisor side].
* **Cosmetic** [V]: `question Q-001 raised (technical): None` (known since M1.7).
* **`outcome.json`** [V]: P1 and P3 have `units[0].verdict: PASS` and `profiles: {implementer: codex, s1_judge: jev}`;
  step 6 has exit 11 and no verdict.
* **Spend** [V]:
  * Claude: P1 generator $0.0358 + judge $0.0837, P3 judge $0.0755, step 6 clarifier $0.1015, so $0.2965 in all.
  * Codex: 5 agent steps (P1 red and green; P3 2 red and 1 green) and 2 hellos (P3's probe was cached), with the
    weekly window at 3 %.
  * Jev: 13 requests (P1 4, P3 5, step 6 4).
  * Laya: 7 shadow answers.
* **Levers left on the dummy** [V]:
  * pin `2a68eff`;
  * `roles.s1_judge: [jev, laya, claude-code]`, `roles.verifier_agent: [claude-code]`;
  * `verifier.fix_minor_findings: false`, `max_fix_rounds: 1`, `audit_sample_ratio: 0`;
  * `verifier.playwright {enabled: true, ui_paths: [src/pricing/web/**]}`, `verifier.s1.shadow: [laya]`;
  * `gates.e2e` (serve `pricing.web.app` on 8765);
  * `memory {enabled, serena 1.7.0}`;
  * profiles `laya` (laya-local) and `jev` (`jev-1.13.0`, `TYPESAFE_API_KEY`);
  * `clarifier.s1_standin: llm_boolean` and `min_confidence: medium`, as found from M1.1.

  No GitLab project setting was changed.
* **Cleanup and open state** [V]:
  * MRs !3 (step 0b), !19 (step 3) and archive !20 (cleanup) are merged. No archive MR is open.
  * Open: !21 ready (show-subtotal), and !22 draft `awaiting_human` (add-cent-rounding, Q-001 open; it is stable: no
    `l4` job runs on it until a human answers).
  * The M1.1–M1.7 MRs !4, !5, !8, !10, !12, !13, !15, !16 and !18 are untouched.
  * The runner is unchanged: `--check` was all OK before and after, and nothing was applied. At 08:39Z no
    `laya-serve`, `serena`, Chromium or Codex process of `gitlab-runner` was left.
  * The clones are in the session scratchpad only.

## 2026-10-05 — M1.6 "change evidence and tuning Laya on ground truth" (harness `641af1f`, live-fix `7c7d7c9`)

Live exit protocol of [`docs/plan/m16-plan.md`](../plan/m16-plan.md) ("Live exit protocol on `example-group/dummy-agentic`
through `l4-runner`"), run by the operator acting as human and maintainer. The dummy was reset first
(parallel-ownership §5.3; there is no M1.6 row, so the plan's own config block was applied over M1.5's levers, see
"Levers left on the dummy"). Job logs (ANSI and section markers stripped) and extracts are in [m16/](m16/), job
artefacts in `artifacts/job-<id>/l4-out/`. Labels: [V] seen in a log, file or API answer; [I] inferred; [U] not
checked.
Token scan of every file saved by this run (job logs, artefacts, `m16/`, `docs/s1/*-live*`, the runner files): no
GitLab, Mintkey or API-key token prefix, and neither the Jev key nor its first 8 characters (0 hits over 133 files;
the key was read from Mintkey into a child process environment only).

**Verdict: steps 1–4 and 7 PASS (step 2 on its second run, after live-fix `7c7d7c9`); steps 5–6 not run because the gate FAILED (an allowed, recorded outcome).**
The laya-evals gate ran on a held-out test split and **failed** with 5 failures: the tuned checkpoint is worse than
base Laya on functions that did run (`mutation:none`, `mutation:add_passing_test`), and one refitted temperature sits on
Laya's clamp. Its overall numbers are much better than base (noul accuracy 0.933 vs 0.552), and that is not enough:
the slice failures have the same signature as the 2026-10-05 evidence run (m16-progress, finding 1), and one-token stumps on the state
text already reach 0.97 (`relevant`) and 0.86 (`exercised`) on the same test split. So nothing was deployed and P4
did not run.

* Step 2 needed one harness live-fix (`7c7d7c9`, test-first): the red guard dropped Codex's `if TYPE_CHECKING:` import
  block but kept the import and the stub that used it, so all three red attempts failed the lint gate and the unit
  halted (exit 13, job 5537). After the fix the unit was reset (MR !23 closed, branch deleted) and steps 1–2 were run
  again (jobs 5539, 5541).
* **The live-fix itself was not exercised live** [V]: in the re-run Codex wrote `def bulk_discount(cart)` with no
  annotation and no `TYPE_CHECKING` block (`stub.purity{restored: 0}`). The fix is proven by
  `tests/unit/implementer/test_stubs_type_checking.py`, which replays the file of job 5537 byte for byte.
* Coverage ran in the job's own venv [V]: `evidence.json` `diff_coverage {status: ok, percent: 7.9}`. coverage.py came
  from the dummy's dev dependency (`coverage>=7.6`, locked 7.16.2, installed by `gates.setup` `uv sync --frozen`).
  Join deviation 8 ("coverage under the real sandbox is unproven") is closed by this run [V for the result; I that the
  gate ran under bwrap: `sandbox.mode` is `auto` and the runner's bwrap works (PRQ-04)].
* `tests/live/test_m1_6_acceptance.py` with `L4_LIVE=1`: **8 passed, 2 skipped** (the two P4 tests, which need a passed
  gate) after step 3, taken before the branch was deleted (the tests read the branch). The same result after step 4, before the cleanup: [acceptance-final.txt](m16/acceptance-final.txt), [ids](m16/acceptance-ids.json).

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 0 runner and reset | — (mk-ssh, read-only) | **pass, no runner change.** `prereqs.sh --check --with-serena --with-playwright --with-laya`: missing 0, failed 0 (PRQ-13 serena 1.7.0, PRQ-14 Chromium 1.63.0, PRQ-18 laya 0.3.24 + typed-decisions). PRQ-16: **7101 MB total** (M1.5 saw a fixed 3801 MB). `TYPESAFE_API_KEY` and `L4_FORGE_TOKEN` are masked and not protected, only `main` is protected, so Jev is reachable on `l4/*` branches (API listing, no value read). After the run: identical (missing 0, failed 0); PRQ-16 now `OK 9945 MB total`. | [before](../runner/prereqs-2026-10-05-check-m16-live-before.txt), [after](../runner/prereqs-2026-10-05-check-m16-live-after.txt) |
| 1 P1: push [`dfe0e33`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/dfe0e33a4ddb15167c44e91af256a7f691359661) (upgrade to `641af1f`) + [`89fb3ad`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/89fb3ad1367f9f25d11e23501c5ab22f6a639998) "Seed inventory module, coverage, bulk discount unit; enable evidence and S1 shadow (M1.6)" | [#2787](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2787) / [5535](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5535) | **pass, exit 11 in 32.8 s, $0.1182.** Intake raised Q-001 from `design.md` (`ambiguous`); the clarifier (Claude) suggested "units" and escalated (`implementer kind ambiguous always goes to a human; clarifier kind product is not in clarifier.auto_accept_kinds`); draft MR !23. Locally before the push: `uv sync --frozen`, pytest 19 passed, ruff clean, `l4 plan` only `add-bulk-discount implement`, `l4 doctor` COV-001 pass | [job log](m16/s1-p1-job-5535.txt), [questions.md](m16/s1-p1-questions-at-b3f9a0c.md), [ledger](m16/s1-p1-ledger-r-20261005T0851Z-0b3c.jsonl), [artefacts](artifacts/job-5535/l4-out/) |
| 2 HUMAN push [`c3cbd07`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c3cbd075038dbbc62fe0d7cf2d3ed76bfa9bdf6a) (Q-001 "units", `LOW_STOCK_THRESHOLD = 3`, new `src/pricing/receipt.py`, 53 executable statements in `format_line` 17, `format_total` 12, `format_receipt` 24, counted with coverage.py's own parser) | [#2792](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2792) / [5537](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5537) | **FAIL, exit 13 (halted), harness bug.** Codex's red stub imported `Cart` under `if TYPE_CHECKING:` (a plain import is circular: `cart.py` imports `discounts.py`). The red guard kept `from typing import TYPE_CHECKING` and `def bulk_discount(cart: Cart)` but did not apply the block (`guard.violation … the statement at line 7 was not applied`), so the rebuilt file failed ruff with F401 and F821. The agent's own file was clean, and the rejection text shows only the lint output, so Codex sent the same file three times; `max_task_attempts (3)`. Live-fix [`7c7d7c9`](#m16-live-fix) | [job log](m16/s2-p2-halted-job-5537.txt), [ledger](m16/s2-p2-halted-ledger-r-20261005T0853Z-adaa.jsonl), [commits](m16/s2-p2-halted-commits.txt), [branch as a patch](m16/s2-halted-branch.patch), [lint log](artifacts/job-5537/l4-out/gates/r-20261005T0853Z-adaa/015-lint.log) |
| reset: MR !23 closed, branch deleted (API), push [`b98d1d0`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/b98d1d06de9be5f42939fc71c88cd8988e4b5046) (upgrade to `7c7d7c9`) = P1′ | [#2795](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2795) / [5539](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5539) | **pass, exit 11 in 31.6 s, $0.0227.** As P1: Q-001 raised and escalated, draft MR [!24](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/24) | [job log](m16/s1b-p1-rerun-job-5539.txt), [artefacts](artifacts/job-5539/l4-out/) |
| 2′ HUMAN push [`f7e75d7`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/f7e75d7230d4c12d18cb03bb1fa25a239f595918) (the same three edits, `receipt.py` byte-identical) = P2′ | [#2800](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2800) / [5541](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5541) | **pass, exit 11 in 410.4 s, $0.1372.** Plan `answers submitted`; Codex red (1 attempt, stub `bulk_discount(cart)`, no guard violation) → green; gates test 20/20, e2e 2/2. **Step 0** `base main@b98d1d06de contained`. **Step 1** `6 sub-checks; scope: 8 changed file(s), 1 held`, content scan ok (the step-1 blocks of the join review raised nothing on human code). **Step 3** tests ran 22/22, 1 new test passed, `tests_ok: true`. **Step 6** `7.9% of the changed executable lines ran`: `receipt.py` `<module>` 0/5, `format_line` 0/17, `format_receipt` 0/24, `format_total` 0/12 uncovered; `bulk_discount` 3/3 covered. **Holds:** `H-f427d7fb` scope (`src/inventory/stock.py`, module `inventory`) and `H-2426ce7a` diff coverage (the four receipt functions). **Step 8** laya-local S1 on 2 criteria (p 0.561, 0.533), then the shadow: `verify.s1_shadow{items: 12, asked: 12, engines: [laya:ok, jev:ok]}`, 24 answer records. **Verdict NEEDS_HUMAN**, 4 verdict questions (Q-002, Q-003 on two major judge findings about the same two files; Q-004, Q-005 on the holds). `verification.md` has the Evidence section, "Needs attention" first. No `guard.violation` in the run: the human's edits survived. **The shadow did not decide** [V, `verification.md`]: its section is "S1 (recorded for calibration, never decides)", "Needs a human" lists only the two deterministic holds, and both criteria pass for "the judge passed it and a discriminating test passes" (the all-0 / all-1 invariance itself is a unit test, not a live observation) | [job log](m16/s2b-p2-job-5541.txt), [verification.md](m16/s2b-add-bulk-discount-verification.md), [evidence.json](m16/s2b-evidence-round-1.json), [questions.md](m16/s2b-questions-at-a8000ac.md), [artefacts](artifacts/job-5541/l4-out/) ([S1 items and answers](artifacts/job-5541/l4-out/s1/r-20261005T0921Z-1804.jsonl), [laya-serve log](artifacts/job-5541/l4-out/logs/laya-serve.log)) |
| 3 HUMAN push [`21caaea`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/21caaeab003dbc2f0b384282a7d496f74a7dd3b8): Q-004 `reject: inventory is not part of bulk discounts`, Q-005 `accept: receipt helper lands with its own unit`, Q-002 and Q-003 `accept` (decided on the holds) | [#2809](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2809) / [5543](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5543) | **pass, exit 11 in 8.8 s.** `human.verdict` ×4 (reject on `H-f427d7fb`, accept on `H-2426ce7a`, `F-7026922b`, `F-72872195`); **one** label record `{kind: label, item_key: 27cf4d6a…, truth: {relevant: false}, label: out_of_scope, source: human:verdict}` in the job's `.l4-out/s1/` and the runner cache, none for the coverage hold; round 2 NEEDS_HUMAN (steps 0–9 reused), the rejected hold asked again as Q-006: the unit stays with the human. **Operator, after the final acceptance run** (the tests read the branch): MR !24 closed, branch deleted, see cleanup. | [job log](m16/s3-p3-job-5543.txt), [verification round 2](m16/s3-add-bulk-discount-verification-round-2.md), [the deleted branch as a patch, `b98d1d0..ad2000c`](m16/s3-add-bulk-discount-branch.patch), [commits](m16/s3-add-bulk-discount-commits.txt), ledgers [P1′](m16/ledger-r-20261005T0919Z-b5be.jsonl), [P2′](m16/ledger-r-20261005T0921Z-1804.jsonl), [P3](m16/ledger-r-20261005T0930Z-1874.jsonl), [questions.md](m16/s3-questions-at-ad2000c.md), [label record](artifacts/job-5543/l4-out/s1/r-20261005T0930Z-1874.jsonl), [acceptance](m16/acceptance-after-step3.txt) |
| 4 Mac: canary | — | **pass with the quotas unmet (exit 2, as designed).** `l4 s1 canary --repo <py_multi> --also-repo <dummy clone> --seed 1606 --target 600` over a fresh `py_multi` and a dummy clone with one local branch per unit (`add-bulk-discount` included; archive branches left out), test command overridden as in the 2026-10-05 run: **1380 items**, 14 real and 8 synthetic source units, 462 s. Real items: 12 units (file-relevant 214 true / **6 false**, change-covered 155 / 85, tests-ok 50 / 98). The 6 real `relevant=false` rows all come from `add-bulk-discount`: its `stock.py`, and `transplant_hunk` / `template_edit` now apply because the dummy has a second module. `add-shipping-fee` now gives items (the round-5 exemption fix). `show-item-count` and `show-subtotal` were dropped (`baseline_failed`, 14 runs). Quotas: `relevant=false: share 22% below 30%`, `11 in the test split, 30 wanted`, `exercised=true: 26 in the test split, 30 wanted` | [canary log](../s1/canary-2026-10-05-live.txt) |
| 4 Mac: export | — | **pass.** Sources: the canary file plus the runner's `$L4_CACHE/s1-calibration.jsonl`, copied read-only through `mk-ssh.sh` (`sudo cat`, sha256 `54dc64b6…` equal on both sides; 19 items, 38 answers, **1 label**, 4 v1 lines). Seed 1606 refused: `l4/file-relevant@1: no test row with label false (split seed 1606; --allow-gaps writes it anyway)`; under 1606 the test split would have held 58 rows, 6 of them change-covered and no `relevant=false`. Rule applied: the first seed from 1606 whose export passes the export's own checks, so **seed 1607**: 1239 rows, train 873 / calib 195 / test 147 (units 16 / 3 / 3), `dataset_sha256 6db8b6f1…`. Label sources: `deterministic:diff-coverage` 587, `deterministic:scope` 382, `deterministic:tests-ran` 270, `human:verdict` **1**; `rejected_label_source: 0`, no engine or judge source. The human label overrides the scope label of item `27cf4d6a…` (`human_overrides_deterministic: 1`; in `train.jsonl` with `expected.relevant: false` and the tag `label_source:human:verdict`). `laya-evals validate` (0.3.24) exits 0 for each split (873, 195, 147 examples, 7 question ids) | [manifest](../s1/manifest-2026-10-05-live.json), [shortcut check](../s1/shortcuts-2026-10-05-live.json) |
| 4 Mac: train and gate | — | **train pass, gate FAILED.** `laya_tune.py train --base typed-decisions@7b928d82… --epochs 2 --micro-batch 1 --grad-accum 16 --seed 1606 --device mps` on the full train split: 2121 items, **2113 s**, peak RSS 7.24 GB, final epoch; temperatures raw `[1.0, 4.38, 5.47]`, applied `[1.0, 4.38, 5.0]` (index 2 on Laya's clamp); every fitted threshold null. Disk 75 → 72 GiB free. `laya_tune.py gate` (laya-evals' own metric code, `scripts/s1/gates.json`): base → tuned noul accuracy 0.552 → **0.933**, score MAE 1.401 → 0.361, ECE 0.081 → 0.038, Brier 0.245 → 0.057, AURC 0.390 → 0.031. The four per-qid rules pass (`exercised`, `untested` 0.889, n 72; `relevant` 0.970, `unrelated` 1.000, n 33). **Failures (5):** `mutation:add_passing_test` `exercised` 0.88 vs base 1.00 and `untested` 0.76 vs 0.94 (n 17); `mutation:none` `exercised` 0.67 vs 1.00 and `untested` 0.50 vs 1.00 (n 6); `temperature[2] sits on Laya's clamp (5.47)`. `gate.passed: false` and the document's sha256 are recorded in `l4-train.json` before any comparison | [train record](../s1/train-2026-10-05-live.json), [train log](../s1/train-log-2026-10-05-live.txt), [gate](../s1/gate-2026-10-05-live.json), [gate log](../s1/gate-log-2026-10-05-live.txt), [thresholds](../s1/thresholds-2026-10-05-live.json) |
| 4 Mac: score and report | — | **pass.** `l4 s1 score` on `test.jsonl` with `--gate`: base Laya 147 rows, tuned Laya 147 rows (the score-only path for a failed gate), Jev `jev-1.13.0` **60 requests**, 0 failed, 87 not asked (key from Mintkey into the child environment only). `l4 s1 report --gate --profile laya-tuned`: **GATE FAILED** header, cross-check against laya-evals ok, same `dataset_sha256`. Real and synthetic rows apart below | [compare](../s1/compare-2026-10-05-live.md), [slices](../s1/slices-2026-10-05-live.md) |
| 5 deploy | — | **not run**: the gate failed (protocol: only if the gate passed) | — |
| 6 P4 (`laya-tuned`) | — | **not run**: the gate failed | — |
| 7 read-only checks | — | **pass.** No `laya-serve` left (`pgrep -u gitlab-runner -f laya-serve` empty at 10:28Z; no serena, Chromium or Codex process of `gitlab-runner`). Peak memory from a read-only sampler (the job logs print none): P2′ used 3530 of **3801 MB**, swap **2047 / 2047 MB**, `laya-serve` 2120 MB RSS; during P1 the VM had **9945 MB** total. All 22 `[skip ci]` pipelines from #2788 to #2813 were skipped with no job; `l4` ran only on the 5 human pushes and the cleanup | [runner after](m16/s7-runner-after.txt), [memory](../runner/memsample-2026-10-05-m16-live.txt), [loop safety](m16/s7-loop-safety.txt) |
| cleanup: MR !24 closed, branch deleted (API), push [`9627b99`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/9627b99aea572a3c443dfd6d7e5bd67f139c29d9) retiring `openspec/changes/add-bulk-discount` (a deleted unit branch with the change still on `main` would start P1 again) and restoring `clarifier.auto_accept_kinds` | [#2814](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2814) / [5545](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5545) | **pass.** `[l4] run: nothing to do: no unit has a next step`, exit 0 | [job log](m16/s8-cleanup-job-5545.txt) |

Accuracy on the test split, real (`example-group/dummy-agentic`: `add-split-amount`, `add-cart-clear`) and synthetic
(`py_multi`: `cart-totals`) rows apart, every row each engine scored (Jev: its 60 of 147). From
[slices](../s1/slices-2026-10-05-live.md); all test rows are canary rows (no live item fell in test):

| question | real base | real tuned | real Jev | synthetic base | synthetic tuned | synthetic Jev |
|---|---|---|---|---|---|---|
| exercised | 0.458 (24) | 0.917 (24) | 0.778 (9) | 0.500 (48) | 0.875 (48) | 0.471 (17) |
| relevant | 1.000 (13) | 1.000 (13) | 0.714 (7) | 0.850 (20) | 0.950 (20) | 0.900 (10) |
| unrelated | 1.000 (13) | 1.000 (13) | 0.714 (7) | 0.450 (20) | 1.000 (20) | 1.000 (10) |
| relatedness | 0.833 (6) | 0.833 (6) | 0.667 (3) | 0.083 (12) | 1.000 (12) | 1.000 (5) |
| all_passed | 0.538 (26) | 1.000 (26) | 1.000 (10) | 0.562 (16) | 1.000 (16) | 1.000 (7) |

Untouched functions (`mutation:none`, `exercised`): real base 4/4, tuned 2/4, Jev 0/1; synthetic base 2/2, tuned 2/2,
Jev 1/1. The real slice has **no `relevant=false` row** in test (13 true): every out-of-scope test row is synthetic,
and the only real out-of-scope unit (`add-bulk-discount`) landed in train. So file relevance on real data is still not
tested.

The trace lines (jobs 5535, 5537, 5541, 5543, 5545). The console has no handler for the evidence, the shadow and the
labels, so those are quoted from the run log, `evidence.json` and `.l4-out/s1/`:

```
5535 [l4] openspec:add-bulk-discount question Q-001 raised (ambiguous): None
5535 [l4] openspec:add-bulk-discount clarifier Q-001: escalated to a human (implementer kind ambiguous always goes to a human; clarifier kind product is not in clarifier.auto_accept_kinds)
5537 [l4] openspec:add-bulk-discount guard violation: red scope on src/pricing/discounts.py → restored
5537 [l4] openspec:add-bulk-discount task 1.1 red attempt 3 failed: lint gate `.venv/bin/ruff check --extend-exclude .l4 .` failed (exit code 1): F401 [*] `typing.TYPE_CHECKING` imported but unused --> src/pricing/discounts.py:…
5537 [l4] run: openspec:add-bulk-discount halted: task 1.1: max_task_attempts (3) reached
5541 [l4] openspec:add-bulk-discount gate test pass (exit 0, 20 tests: 20 passed, 0 failed)
5541 [l4] openspec:add-bulk-discount s1_judge: laya ok → selected
5541 [l4] system_one: laya-serve started: pid 157076, port 56045, model typed-decisions, laya 0.3.24
5541 [l4] system_one: laya-serve stopped: pid 157076, exit code -15
5541 [l4] system_one: laya-serve started: pid 157171, port 55311, model typed-decisions, laya 0.3.24
5541 [l4] system_one: laya-serve stopped: pid 157171, exit code -15
5541 [l4] openspec:add-bulk-discount verdict NEEDS_HUMAN (round 1, 2/2 criteria pass, 5 finding(s))
5543 [l4] openspec:add-bulk-discount phase awaiting_human → verifying (verdicts_answered)
5543 [l4] openspec:add-bulk-discount verdict NEEDS_HUMAN (round 2, 2/2 criteria pass, 5 finding(s))
5545 [l4] run: nothing to do: no unit has a next step

5537 guard.violation {"phase": "red", "path": "src/pricing/discounts.py", "rule": "red scope", "action": "restored", "region": "the statement at line 7 was not applied"}
5541 verification.md ladder: 0 preconditions ok "base main@b98d1d06de contained"; 1 integrity ok "6 sub-checks; scope: 8 changed file(s), 1 held"; 6 quality ok "7.9% of the changed executable lines ran"; 8 s1 judge ok "2/2 criteria judged by laya-local"
5541 evidence.json holds [{"id": "H-f427d7fb", "kind": "scope", "subjects": ["src/inventory/stock.py"]}, {"id": "H-2426ce7a", "kind": "coverage", "subjects": ["src/pricing/receipt.py::<module>", "…::format_line", "…::format_receipt", "…::format_total"]}]
5541 evidence.json diff_coverage {"status": "ok", "percent": 7.9, "unmeasured_files": []}; tests_ran {"tests_ok": true, "summary": {"total": 22, "passed": 22, "new": 1, "new_passed": 1}}
5541 verify.s1 {"criterion": "C-534a6caa", "p": 0.5614, "engine": "laya-local", "checkpoint": "typed-decisions"} and C-5de37e46 p 0.5334
5541 verify.s1_shadow {"round": 1, "items": 12, "asked": 12, "engines": ["laya:ok", "jev:ok"]}
5541 memory.serena {"status": "ok", "startup_ms": 1443}
5543 human.verdict {"question": "Q-004", "target": "H-f427d7fb", "decision": "reject", "reason": "inventory is not part of bulk discounts"}
5543 human.verdict {"question": "Q-005", "target": "H-2426ce7a", "decision": "accept", "reason": "receipt helper lands with its own unit"}
5543 .l4-out/s1 {"kind": "label", "item_key": "27cf4d6a6ace08e74307bc2dca843668", "truth": {"relevant": false}, "label": "out_of_scope", "source": "human:verdict", "by": "human"}
```

Shadow answers of P2′ (`p_true` of `relevant` or `exercised`, expected label in brackets; 12 items, both engines): `src/inventory/stock.py`
(false) laya-local 0.453, Jev 0.04; `src/pricing/receipt.py` (true: module `pricing` is named) laya-local 0.489, Jev
0.09; `src/pricing/discounts.py` (true) 0.494 / 0.98; `receipt.py::format_receipt` (false) 0.625 / 0.05;
`discounts.py::bulk_discount` (true) 0.682 / 0.65; `tests` all_passed (true) 0.713 / 0.99. laya-local took 8.6–22.8 s
per item on the runner (196 s for the shadow), Jev 234–334 ms.

<a id="m16-live-fix"></a>**Live-fix `7c7d7c9`** — `m1.x(live-fix): the red guard keeps an if TYPE_CHECKING import
block as an import (L4-IMP-002 iii)`. `l4.implementer.stubs`: a module-level `if TYPE_CHECKING:` (or
`typing.TYPE_CHECKING`) with no `else` and only imports in its body is an import (SPEC L4-IMP-002 (iii): imports for a
stub are admissible). A new block goes after the imports; a block that keeps every import of HEAD's block (the same
statement, or the same `from` import with more names) replaces it; anything else is not applied, as before. Test first:
`tests/unit/implementer/test_stubs_type_checking.py` (7 tests; the live file of job 5537 rebuilt byte for byte and
`ruff check` clean on it; three were red before the fix). Checks: `tests/unit/verifier tests/unit/implementer
tests/unit/gates` 989 passed, 3 skipped, 1 xfailed; `tests/contract tests/scenarios tests/integration` 52 passed, 2
skipped; `ruff check .` clean. The dummy took it through `l4 upgrade` (`b98d1d0`: `stubs.py` and the pin).

Deviations and findings (V = seen in logs, files or API answers; I = inferred; U = not checked):

* **Harness bug, fixed** [V]: see the live-fix. Two related gaps were **not** fixed (owner):
  * the rejection text the agent gets (`<l4:data source="previous attempt">`) carries the lint output only; the guard's
    notes (`the statement at line 7 was not applied`) reach the ledger, not the agent, so Codex resent a file that was
    clean on its side three times [V];
  * a type-checking block that is still not applied (an `else`, a non-import statement) leaves names a stub's annotation
    may use undefined (F821): names bound inside a dropped block are not in the guard's `dropped` set [I, from the code];
    and a second new block next to an unchanged HEAD block is compared with HEAD's block and refused [I].
* **The live-fix path was not exercised live** [V]: in P2′ Codex wrote `def bulk_discount(cart)` with no annotation
  (`stub.purity{stubs: [src/pricing/discounts.py:bulk_discount], restored: 0}`). The fix rests on the replay test.
* **Two judge findings on the same two files** [V]. The judge raised major findings F-7026922b (the threshold change)
  and F-72872195 (the untested receipt module), and the verifier asked about them (Q-002, Q-003) next to the
  deterministic holds (Q-004, Q-005), with the note "no deterministic check confirms it" although the scope and
  coverage checks did. The human had to decide each issue twice. The plan expected two verdicts; four were recorded.
  They were answered `accept` with the hold decisions as the reason; a `reject` on a finding starts a fix unit, which the
  protocol does not want. Owner decision: let a hold subsume a judge finding on the same subject.
* **A rejected hold is asked again** [V]: round 2 raised Q-006 on the same `H-f427d7fb`. This is the code's reading of
  "a reject leaves the unit with the human" (`unresolved_holds`), and the unit stays `awaiting_human`. It contradicts
  the plan's C-M16-3 wording "an answered hold is not asked again", which holds for `accept` only.
* **COV-001 is `skip` in CI** [V]: `no project interpreter found (gates.test.command or .venv/bin/python)`. The doctor
  runs before `gates.setup` creates `.venv`. On the Mac, after `uv sync`, it passed. The check is order-bound, not wrong.
* **The canary cannot use units whose tests live in `e2e/`** [I]: `show-item-count` and `show-subtotal` added
  `e2e/test_l4_c_*.py`, which the canary's `tests/`-only command never runs, so `check_tests_ran` reports "new test file
  ran no test", the untouched baseline is not clean and all 14 runs are `baseline_failed` (join deviation 3 seen from the
  canary side). Not re-run with `collect_evidence` on one head.
* **Shortcuts, before training** [V, `shortcuts-2026-10-05-live.json`]: one token chosen on train, scored on test:
  `inventory` decides `relevant` at 0.970 (n 33, majority 0.667), `def` decides `exercised` at 0.861 (n 72, majority
  0.486), `1` decides `all_passed` at 0.833. The tuned model's 0.970 on `relevant` equals the stump. Both modules are
  named `inventory` in `py_multi` and now in the dummy too.
* **The failure signature repeats** [V]: tuned is right on every template (`untested_function` 18/18, `template_edit`
  6/6) and wrong on code that ran (`mutation:none` `untested` 3/6, `add_passing_test` `untested` 13/17). The accuracy gain
  is still mostly template learning; the gate catches it.
* **Seed** [V]: the export refused the default split seed 1606 and passed at 1607 (rule above). No other seed was
  scored, and 1607's numbers are not compared with any other split.
* **Memory** [V]. The VM's total memory moves: 7101 MB at 08:43Z, 9945 MB during P1, 3801 MB during P2′, 9945 MB at
  10:28Z. During P2′'s shadow half `laya-serve` reached 2120 MB RSS and swap was full (2047/2047 MB); the job
  survived. Two interactive `opencode` sessions of the admin user `admin` (about 0.5 and 0.6 GB RSS, running for about
  two days, not L4) were left alone.
* **Laya vs Jev on the runner** [V]: laya-local stays near chance on the shadow items (`relevant` 0.45–0.57,
  `exercised` 0.59–0.71 whatever the label), Jev separates them, and Jev called `receipt.py` unrelated (0.09) where the
  deterministic label is relevant (module `pricing` is named): a module-level scope rule calls a file in scope that a
  reader would not.
* **Cosmetic** [V]: `question Q-00n raised (…): None` (known since M1.7).
* **Spend** [V]:
  * Claude: P1 clarifier $0.1182, P1′ clarifier $0.0227, P2′ judge $0.1372, so $0.2781 in all.
  * Codex: 5 agent steps (3 red in the halted P2, red and green in P2′) and 2 hellos, weekly window 3–4 %.
  * Jev: 72 requests (12 in P2′'s shadow, 60 in step 4).
  * Laya on the runner: 2 step-8 answers and 12 shadow answers; on the Mac: one fine-tune (2113 s) and 2 × 147 scored
    rows.
* **Levers left on the dummy** [V]:
  * pin `7c7d7c9`;
  * `sdd.scope_check: warn`, `verifier.evidence.diff_coverage {mode: warn, min_percent: 80, languages: [python]}`;
  * `roles.s1_judge: [laya, claude-code]`, `verifier.s1.shadow: [jev]`, `roles.verifier_agent: [claude-code]`;
  * `verifier.fix_minor_findings: false`, `max_fix_rounds: 1`, `audit_sample_ratio: 0`;
  * from M1.5, unchanged: `verifier.playwright` (`ui_paths: src/pricing/web/**`), `gates.e2e`, `memory` with Serena
    1.7.0, profiles `laya` and `jev`;
  * `clarifier.s1_standin: llm_boolean`, `min_confidence: medium`; `clarifier.auto_accept_kinds` restored to the
    default (removed from the file);
  * `src/inventory/` (threshold 5) and `tests/test_stock.py` on `main`; `coverage>=7.6` in the dev group.

  No GitLab project setting was changed.
* **Open state** [V]: MRs !23 and !24 closed, `l4/openspec/add-bulk-discount` deleted, the unit's change retired from
  `main` (`9627b99`). Open as before: !21 ready, !22 draft `awaiting_human`, and the M1.1–M1.7 MRs. No archive MR is
  open. Runner unchanged. The clones and the data set are in the session scratchpad only (sha256s in
  [docs/s1/README.md](../s1/README.md)).

## 2026-10-05 — Handbook fixes live (harness `1aa6f36` = `hb` + `fu`, live-fix `89a51ae`)

A check of the handbook items (`hb`) and the M1.5/M1.6 follow-ups (`fu`) on `example-group/dummy-agentic` through
`l4-runner`, run by the operator acting as human and maintainer. The runner's Claude login is **dead** ("OAuth
session expired and could not be refreshed"; the maintainer was asked to log in again): it was not touched, no CLI
login file was read, copied or refreshed, and `claude` was never run by hand. The dummy kept every M1.6 lever; its
judges chain `[claude-code, opencode-free, codex]` therefore has to fall back past the dead head, and that fallback is
itself one of the checks. Job logs (ANSI and section markers stripped) and extracts are in [hb/](hb/), job artefacts
in `artifacts/job-<id>/l4-out/`. Labels: [V] seen in a log, file or API answer; [I] inferred; [U] not checked.
Token scan of every file saved by this run (job logs, artefacts of jobs 5547, 5553 and 5556, `hb/`, the runner probe
file): no `glpat-`, `glcbt-`, `glptt-`, `apikey_`, `sk-`, `mk_agent_` or JWT shape, and neither the Jev key nor its
first 8 characters (0 hits; the key was read from Mintkey into the scanning process only). The scanner was checked on
a planted `glpat-`/`sk-` file first (2 hits).

**Verdict: steps 1, 2, 3 and 5 PASS; step 4 PASS on its second run, after one harness live-fix (`89a51ae`).**
* The first unit run went end to end: Codex red → green, the judge fell back to opencode-free, verdict PASS, MR !25
  ready.
* It failed one HB-5 check: the published judge prompt did not hash to `verdict.json`'s `prompt_sha256`. The cause is
  a harness bug that only a prompt-contract judge shows (below).
* After the fix the unit was reset and run again (job 5556): the hashes are equal and every other check held again.

Plain-language rows and the lines to look for: [EVIDENCE.md, "Handbook fixes live"](EVIDENCE.md#handbook-fixes-live-safer-secrets-sandbox-sockets-published-judge-prompts-2026-10-05).

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 upgrade to `1aa6f36`, push [`97be5eb`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/97be5eb2cb39d756bd3e36177c52f0427f834847) | [#2815](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2815) / [5547](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5547) | **pass.** `l4 upgrade`: `.l4/vendor/` 9 added, 43 changed; the `harness.commit` pin; `.l4/ci/l4.gitlab-ci.yml` gains `environment: {name: l4, action: prepare}` (HB-2). GitLab created environment `l4` (id 27) with this pipeline. `l4 plan --json` on the clone (unit branches and `refs/l4/*` fetched) had no actionable unit before the push. Job: `nothing to do: no unit has a next step`, exit 0. Doctor: `PRV-001 warn fail claude-code claude-code installed-not-authenticated; codex codex ready; opencode-free opencode ready`. No setting of the dummy was changed. The fallback is proven in step 4's jobs (an idle run selects no judge): `[l4] judges: claude-code skipped — auth: claude is not logged in` and `[l4] judges: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello 5.0s) → selected, fallback #1`. Ledger: `availability.selected{role: judges, selected: opencode-free, fallback_index: 1, skipped: [{profile: claude-code, step: auth, reason: "claude is not logged in"}], fallback_from: claude-code}` and `availability.model_unverified{opencode-free, opencode/big-pickle, zhipu}`. `verification.md`: `independence: declared (unverified): opencode-free zhipu (declared), codex openai (tool)` | [job log](hb/s1-upgrade-job-5547.txt), [artefacts](artifacts/job-5547/l4-out/) |
| 2 doctor in CI + `sandbox-probe.sh` | 5547, 5553, 5556; probe over mk-ssh | **pass.** Each of the three `l4` jobs prints `SANDBOX-002  error     pass    no container-daemon socket is reachable from the agent or the gate sandbox`. The doctor runs `l4.sandbox.bwrap.base_flags` once with the network shared and once with `--unshare-net`. The probe ran with `CLIS="codex opencode" SANDBOX=m0` (claude was left out: dead login). It ran as gitlab-runner, in the production agent argv, and printed `SANDBOX codex (m0) \| PASS \| 20.8s \| exit=0 edit=yes tests=pass testdiff=none canary=ok result=yes` and `SANDBOX opencode (m0) \| PASS \| 11.0s \| … canary=ok`. `canary=ok` covers six things inside the sandbox: no docker, containerd, podman or dbus socket; empty `/run/containerd` and `/run/dbus`; `connect()` + `GET /_ping` on `/var/run/docker.sock` fails; DNS resolves `pypi.org`; planted `.claude/` and `.agents/` are empty (HB-X1); no env leak, other login or writable `.git`. Control outside the sandbox, as gitlab-runner (groups `gitlab-runner docker`): all three sockets present, docker `/_ping` → `HTTP/1.0 200 OK`, DNS resolves. So the canaries are not vacuous | [probe output + control](../runner/sandbox-probe-2026-10-05-hb.txt) |
| 3 HB-2 scoped secrets | [#2816](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2816) / 5548, 5549; [#2817](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2817) / 5550, 5551 | **pass.** *Does CE 17.5 support scopes?* POST `L4_SCOPE_PROBE=hello`, `environment_scope: l4` → 201; read back `"environment_scope":"l4"`; the `*` lookup → 404. A presence-only probe on the throwaway branch `l4-probe/scope` (two `tags: [agentic]` jobs) confirmed it before any secret was touched: the plain job got `L4_SCOPE_PROBE ABSENT`, the job in environment `l4` got `L4_SCOPE_PROBE PRESENT`. The probe variable was deleted (204). *Changes:* `mk-gitlab-bot-token.sh --project 118 --rotate --environment-scope l4` printed `NEW token 'l4-bot' id=63 … expires=2027-10-05 bot_user_id=61`, `SET variable L4_FORGE_TOKEN created (masked, not protected, raw, environment scope l4)` and `OK new token can read project 'example-group/dummy-agentic' as the bot user`. `gitlab_ci_var_from_mintkey.py --secret typesafe-jev-api-key --variable TYPESAFE_API_KEY --environment-scope l4` printed `created TYPESAFE_API_KEY on project 118: environment scope l4 masked=True protected=False raw=True`. Once both scoped variables answered 200, the unscoped ones (`*`) were deleted (204, 204; afterwards `*` → 404, `l4` → 200 for both). *Proof* (#2817): `scope-probe-plain` printed `L4_FORGE_TOKEN ABSENT`, `TYPESAFE_API_KEY ABSENT`; `scope-probe-l4env` printed `L4_FORGE_TOKEN PRESENT`, `TYPESAFE_API_KEY PRESENT`. `l4-probe/scope` was deleted. The next `l4` pipelines still pushed 4 commits each and opened MRs !25 and !26 as the new bot user `project_118_bot_example…`. Their Jev shadow answered (`verify.s1_shadow{engines: [laya:ok, jev:ok]}`), so the scoped `TYPESAFE_API_KEY` reaches the `l4` job. No value was read or printed: presence was read from HTTP status codes, and the scripts keep values in memory | [variable record](hb/s3-ci-variables.txt), [before: plain](hb/s3-probe-before-plain-job-5548.txt), [before: l4](hb/s3-probe-before-l4env-job-5549.txt), [after: plain](hb/s3-probe-after-plain-job-5550.txt), [after: l4](hb/s3-probe-after-l4env-job-5551.txt) |
| 4 seed `add-cart-is-free` ([`c72d240`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c72d24021fd62b8b43075b0e7aad802184152d60): `Cart.is_free()` is true exactly when `Cart.total()` is 0.00; 2 scenarios; 1 task; `openspec validate --strict` valid) | [#2818](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2818) / [5553](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5553) | **FAIL on HB-5 only.** Codex red [`268eac1`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/268eac160891efea4dcdcc2931aed8d21bef2902) → green [`a724822`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/a7248223e335d9dacbdfc201b3a711772d585e80); judge fallback as in step 1; verdict PASS 2/2 (3 minor findings); hand-off `2f6343c`; MR !25 ready `l4:in_review`; exit 0 in 222.9 s. But `agent/…/verify-judge-r1-1.prompt.md` hashes to `c193aaee…`, while `verdict.json` `prompt_sha256` is `a9f280d9…`. The file's prefix up to `SCHEMA_INSTRUCTION` hashes to `a9f280d9…`, so the file held the prompt document plus the schema instruction that a prompt-contract adapter (opencode) gets appended. The hash covers the document only (SPEC L4-VER-005). With a native judge (claude-code) the two are equal, which is why the HB-5 unit test passed | [job log](hb/s4-unit-job-5553.txt), [commits](hb/s4a-add-cart-is-free-commits.txt), [verification.md](hb/s4a-add-cart-is-free-verification.md), [verdict.json](hb/s4a-add-cart-is-free-verdict.json), [code](hb/s4a-add-cart-is-free-code.diff), [argv sample](hb/s4a-argv-sample-job-5553.jsonl), [artefacts](artifacts/job-5553/l4-out/) |
| live-fix `89a51ae` + retry rule | — | Harness `main`, test first (`test_a_prompt_contract_judge_publishes_the_document_whose_hash_is_the_verdicts` failed on the file content first): the judge request factory publishes `prompt.removesuffix(schema_suffix(schema))`. This is an exact suffix strip, so instruction text inside a diff is not searched. The agent is still sent the instruction. Chunks verifier, llm, agents, implementer, clarifier and the template lock: 1407 passed, 10 skipped, 1 xfailed. `ruff check .` clean. Reset: MR !25 closed; `l4/openspec/add-cart-is-free` and `refs/l4/locks/openspec/add-cart-is-free` deleted; `l4 plan` showed the unit `implement` again. Dummy upgraded (3 vendored files + pin) in [`4c88649`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/4c886494446a98f7d088bdec2f5b8219c0f00fc9) | — |
| 4 retry: the push of `4c88649` | [#2826](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2826) / [5556](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5556) | **pass.** Implement: `[l4] implementer: codex ok (binary 0.160.0 · auth subscription · quota 4% used (weekly window) · hello 6.6s) → selected`, then red [`2513137`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2513137bb9688c7dab3f88e10c6efebc13365713) → green [`189272e`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/189272eb7ce62b58986041de110bc9cebcd30568) (`L4-TDD`, `L4-Agent: codex/gpt-6-luna`, `[skip ci]`). Verify: the same fallback lines (hello 5.9s), gates setup/lint/test/e2e pass, `verdict PASS (round 1, 2/2 criteria pass, 4 finding(s))` (4 minor: three spec gaps on zero-total edge cases, one on the proof token). Hand off: [`365afed`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/365afeda06287098b44f8f3d0de42f122e9ff0f5); **[MR !26](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/26) ready, `l4:in_review`**; `run finished: exit 0 in 230.6s`. The HB checks: **HB-5** `verify-judge-r1-1.prompt.md` sha256 = `verdict.json` `prompt_sha256` = `d28539ae226638db88e6a1975f610e4e8b783ab7fe52d0b1e555dfded427e02a`, with `template: judge@3` and `harness_commit: 89a51ae…`. **HB-10** `run.started` has `runner: {id: "12", description: "l4-runner"}` and `tools: {python: 3.13.16, git: 2.34.1, bwrap: 0.6.1}`. **HB-X1** No artefact records an argv, so the argv was read on the runner from `/proc/<pid>/cmdline` during both runs (read-only sampler, `--setenv` values redacted). The Codex agent argv has `-c project_doc_max_bytes=0` (both runs), and every L4 agent and gate bwrap argv sampled (8 in job 5553, 7 in job 5556; Codex's own inner sandbox not counted) has `--tmpfs /run` + `--ro-bind-try /run/systemd/resolve/stub-resolv.conf …`. There is no guidance mask, correctly: the dummy has no guidance dir (only `.kiro/specs`, not a masked `.kiro/` subdir), so the mask itself is proven by step 2's planted-guidance canary. **HB-7/8** `outcome.json` `exit_reason: null` on this exit 0, as specified (set on halts and escalations). **HB-4** there is no `guard.*` event at all, `guard.secret` included | [job log](hb/s4b-unit-rerun-job-5556.txt), [commits](hb/s4b-add-cart-is-free-commits.txt), [verification.md](hb/s4b-add-cart-is-free-verification.md), [verdict.json](hb/s4b-add-cart-is-free-verdict.json), [code](hb/s4b-add-cart-is-free-code.diff), [argv sample](hb/s4b-argv-sample-job-5556.jsonl), [artefacts](artifacts/job-5556/l4-out/) |
| 5 read-only | pipelines #2815–#2833; mk-ssh | **pass.** Every bot `[skip ci]` push and MR pipeline is `skipped` with no job (12). The hand-off pipelines #2825 and #2833 ran only `test` (runner 8). The only `l4` jobs ran on the operator's pushes to `main` (5547, 5553, 5556). After each run, `ps -u gitlab-runner` is empty: no bwrap, codex, opencode, laya-serve, serena or pytest process is left. The only agent processes are the admin user's 2-day-old interactive sessions (not L4) | [loop safety](hb/s5-loop-safety.txt), [runner processes](hb/s5-runner-processes.txt) |

Deviations and findings:

* **Harness bug, fixed `89a51ae`** [V]: HB-5's published judge prompt matched `prompt_sha256` only for a native judge
  (step 4). The first live run with a prompt-contract judge exposed it; the unit test had used the native fake adapter.
* **Audit-writer hash, open** [I, code read; not exercised: `audit_sample_ratio: 0`]. `verifier/testwriter.py` hashes
  `system + user` with no blank line, while the published `.prompt.md` is `render_prompt(...)` (system, blank line,
  user). So an audit writer's `prompt_sha256` cannot equal its published file, even on a native adapter. SPEC
  L4-VER-005 binds only the judge's `verdict.json` value, so this is a consistency gap, not a SPEC violation. No test
  pins it.
* **The skip reason** [V]: `claude is not logged in` is the CLI's own `claude auth status` verdict (`loggedIn:
  false`), taken at the probe's auth step. The "OAuth session expired" wording is what a hello would print; the auth
  step never sends one, so it cannot carry that text.
* **`outcome.json` `profiles` omits the judge** [V]. It lists `implementer` and `s1_judge` only; the judge, its
  fallback and the independence label are in `verification.md`, `verdict.json` and the ledger. Cosmetic.
* **A dead Claude login leaves one required role empty** [I]. `roles.verifier_agent: [claude-code]` has no fallback.
  A unit that changes `src/pricing/web/**` (step 5, UI test generation) or draws an audit sample would find the role
  unavailable while the login is dead. `clarifier` falls back to codex; `s1_judge` starts with laya.
* **Not exercised** [U]: a non-null `exit_reason`; a guidance mask in a unit's own argv (no guidance dir).
* **Variable and token changes on project 118:**
  * `L4_FORGE_TOKEN` and `TYPESAFE_API_KEY` now exist only with environment scope `l4` (masked, not protected, raw);
    the unscoped (`*`) ones were deleted.
  * `L4_SCOPE_PROBE` was created and deleted.
  * Project access token `l4-bot` id 63 was minted (expires 2027-10-05, bot user 61); it is the value in
    `L4_FORGE_TOKEN`.
  * Token id 62 (2026-10-03) was **revoked** after this run (`DELETE projects/118/access_tokens/62` → 204); `GET
    access_tokens` lists only id 63, so the rotation is complete.
  * Runner 12 `run_untagged` is `false` [V, `GET runners/12`], so that README item needs no change.
* **Spend** [V]:
  * Codex: 4 agent steps (red and green, twice), 2 hellos and 1 m0 probe task; weekly window at 4 %.
  * opencode-free (OpenCode Zen, $0): 2 judge calls, 2 hellos, 1 m0 probe task.
  * Jev: 8 shadow items.
  * Laya on the runner: 4 step-8 answers and 8 shadow answers.
  * Claude: nothing (login dead).
* **Left on the dummy** [V]:
  * pin `89a51ae`; every M1.6 lever unchanged;
  * `openspec/changes/add-cart-is-free` on `main`;
  * MR !26 ready (`l4:in_review`) with its lock ref; MR !25 closed.
  * Open as before: !21 ready, !22 draft, the M1.1–M1.7 MRs. No archive MR is open.
  * The clones are in the session scratchpad only.

## 2026-10-06 — M1.8 "easy adoption" live (harness `6b72c0d` = the M1.8 merge `c8808e6` + the plan log)

Live check of M1.8 on two projects, run by the operator acting as maintainer. M1.8 adds `l4 setup gitlab`, `l4 doctor
--adoption` (GATE-001), the CI include written by `l4 init` and the run fixes R1–R6.
* **dummy-agentic (118):** vendored-harness upgrade, then `l4 setup gitlab` twice in its Mintkey form
  (`scripts/forge/mk-l4-setup-gitlab.sh`).
* **sample-consumer (119):** the same upgrade, `doctor --adoption` and `setup gitlab`.

Both clones are fresh SSH clones in the session scratchpad. Dummy logs (ANSI and section markers stripped) and API
snapshots are in [m18/](m18/). The sample-consumer evidence stays in the git-ignored
`docs/adoption/sample-consumer/live/m18/` (private source text), so below it is given as counts and pass/fail only.
Labels: [V] seen in a log, file or API answer; [I] inferred; [U] not checked.

**Token scan** of the 23 saved files (both folders): no `glpat-`, `glcbt-`, `glptt-`, `apikey_`, `sk-`, `mk_agent_` or
JWT shape, and no Jev key or its first 8 characters (0 hits). The scanner was checked first on a planted
`glpat-`/`sk-` file (1 file, both patterns found). Variable values were never printed. `setup gitlab` prints none, and
the before/after checks compare SHA-256 digests in-process.

**The brief said the runner's Claude login is dead. It is not** [V]. A read-only `claude auth status`, run as
`gitlab-runner` over `mk-ssh.sh` with its output cut down to three fields, says `loggedIn: true`, `authMethod: claude.ai`.
PRV-001 reports `claude-code ready` in jobs 5570, 5572 and 5574. The login was not otherwise touched.

**Verdict: PASS on every required check, with no harness change.** The findings below are small gaps and one
untested risk (F2).

### dummy-agentic (118)

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 `l4 upgrade` to `6b72c0d`, push [`bc8d59d`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bc8d59d79b9053564deaeeab8b5439f672c819b6) | [#2848](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2848) / [5570](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5570) | **pass.** `.l4/vendor/`: 12 files added, 24 changed, 0 removed. Also changed: the two `harness` pins and the template, whose doctor line gains `${L4_ADOPTION_CHECK:+--adoption}`. Every doctor row at error passes. CI-002 is warn/fail (the repository's `test` job is untagged and runs on runner #8, as intended). PRV-001: claude-code, codex and opencode-free are ready. `plan`: 11 units `in_review`, `add-cent-rounding` `awaiting_human`. `run`: `nothing to do`. | [s1-upgrade-l4-job-5570.txt](m18/s1-upgrade-l4-job-5570.txt) |
| 2 `setup gitlab --project 118`: `--dry-run`, then `--watch` | [#2849](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2849) / [5572](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5572) | **pass.** OK: the project (`internal`, branch `main`) and the include (own jobs: `test`). WARN: runner #12 `instance_type, online` (the internal-project text), and `jobs` (`test` lacks `[agentic]`). **KEPT**: token `l4-bot id=63` and variable `L4_FORGE_TOKEN` (environment scope `l4`, masked), so there was no rotation. **NEW**: schedule `l4 sweep` `*/30 * * * *` UTC on `main` (id 1). Pipeline #2849 was triggered with `L4_ADOPTION_CHECK=1` and watched to `success`. Summary: `4 ok, 1 new, 0 set, 2 kept, 2 warn, 0 fail -> exit 0`. In job 5572: `GATE-001 error pass HEAD bc8d59d79b; … gates ran bwrap: setup: pass; lint: pass; test: pass (19/19 passed)`, then `nothing to do`. | [s2-setup-dry-run.txt](m18/s2-setup-dry-run.txt), [s2-setup-run1.txt](m18/s2-setup-run1.txt), [s2-check-l4-job-5572.txt](m18/s2-check-l4-job-5572.txt), [s2-state-before.txt](m18/s2-state-before.txt) |
| 3 second run, `--no-pipeline` | — | **pass, no changes.** KEPT: token, variable and schedule. Summary: `3 ok, 0 new, 0 set, 3 kept, 2 warn, 0 fail -> exit 0`. Checked from outside: tokens, variable keys, scopes and flags, the schedule (with its `updated_at`) and the newest pipeline are identical after run 1 and after run 2. The value digests are equal before run 1, after run 1 and after run 2. | [s3-setup-run2.txt](m18/s3-setup-run2.txt), [s3-state-after-run1.txt](m18/s3-state-after-run1.txt), [s3-state-after-run2.txt](m18/s3-state-after-run2.txt) |
| 4 the first scheduled sweep | [#2852](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2852) / [5578](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5578) | **pass.** The schedule ran at 21:33Z. Its owner (the proxy credential's user) may run pipelines on the protected `main`, which closes the plan's [U]. `l4` took 16 s, `nothing to do`; `test` took 7 s on runner #8. | [s4-schedule-l4-job-5578.txt](m18/s4-schedule-l4-job-5578.txt) |

Runner #12 [V, `GET runners/12`]: `instance_type`, online, tags `agentic, ai, opencode`, `run_untagged: false`
([s2-runner-12.txt](m18/s2-runner-12.txt)). `setup gitlab` printed its type but not its tags (F1).

### sample-consumer (119): counts and pass/fail only

| Step | Result |
|---|---|
| upgrade to `6b72c0d` (the project's documented author identity), 1 commit, 38 files, all under `.l4/` | pass (the same 12 added / 24 changed vendor files) |
| `.l4/bin/l4 doctor --adoption` on the laptop (the upgraded shim) | **exit 0**, 117 s. 9 rows: 5 pass (CI-002, CFG-002, CFG-005, SPEC-001, GATE-001), 4 skip (Kiro, memory off). GATE-001 ran unsandboxed (no bwrap on the Mac): setup, lint and test pass, 192/192 |
| push of the upgrade commit (the only change pushed to 119) | **pipeline #2850 green**: `test` (runner #12) and `l4` succeed. Every doctor row at error passes; PRV-001: claude-code and codex ready. `plan`: the one unit is `in_review` → `nothing to do` |
| `setup gitlab --project 119`: `--dry-run`, then `--no-pipeline` | exit 0 both times. Real run: `3 ok, 1 new, 0 set, 2 kept, 1 warn, 0 fail`. KEPT: token `l4-bot id=64` and the scoped variable (no rotation; value digest unchanged). NEW: schedule `l4 sweep` `*/30` UTC (id 2). WARN: runner #12 is an instance runner on a private project |
| the first scheduled sweep (#2851) | green: `test` 89 s on runner #12, `l4` 11 s, `nothing to do` |
| the parking note on MR !1 | **does not apply** [V]: `build-without-extra-modules` is `in_review` (verdict PASS), not parked, and Claude is logged in. MR !1 was not touched (last update 2026-10-05 18:47Z) |
| the check pipeline (`L4_ADOPTION_CHECK=1`) | **not triggered, on purpose** (`--no-pipeline`). On the runner, GATE-001 installs `--extra index`, which at this base has 4 Linux-only test failures [I: job 5561's baseline on the same tree]. So the `l4` job would exit 3 and turn the pipeline red until PR-1 merges. The laptop passes 192/192 [V]: this is the plan's "a Mac cannot see it" fact. Triggering it is the maintainer's call |

### Command count for a fresh adoption

The target of the plan is 5 commands and 0 file edits on a green base, against 37 commands and 2 edits on 2026-10-05.
It was measured on the laptop only, on a local copy of sample-consumer with nothing pushed.

At `fed8f84` (the owner's "prepare" commit, which has `uv.lock` and ruff in `dev`):
1. `init --ci gitlab --vendor` exits 0. It writes the config, `.gitlab-ci.yml` (the include plus a `test` job tagged
   `agentic`, whose first line exits on a schedule), and two `.gitignore` lines. It prints the `.serena/` carve-out note
   and the extras note.
2. `doctor --adoption` exits 3. GATE-001: lint fails even narrowed to `F,E9`; the test gate passes (186/192 passed).
3. One config edit: `gates.lint: []`, as GATE-001 suggests.
4. `doctor --adoption` again exits 0.

**Count: 6 commands and 1 edit**:
* steps 1–4 above make 3 commands and the edit;
* commit, `push -o ci.skip` and `setup gitlab` add 3 more.

Add 1 for `git remote add` or for creating the project when either is missing. The repository from before the prepare
commit needs one more command, `uv lock`: init writes that as a `# TODO` (F4).

Measured [V]: init and doctor; `setup gitlab` on the two existing projects. Not exercised [U]: commit, push and setup
on a project that is new to GitLab (push-to-create), and the check pipeline of a fresh adoption.

### Findings (nothing here blocks M1.8)

* **F1, minor** [V]: `setup gitlab` names an instance runner's type but not its tags. The WARN row says "these tags",
  and the tag list appears only for a project or group runner. #12 actually carries `agentic, ai, opencode`.
* **F2, risk, not hit** [V measured, I outcome]: a brokered Mintkey JWT lives about 600 s (598 s measured).
  * The wrapper fetches one JWT. `watch_pipeline` re-raises any `AdminError` that is not a 5xx error
    (`ci/watch.py:68–73`).
  * So `--watch` in the Mintkey form ends with exit 1 on a 401 if the check pipeline finishes more than about 10 minutes
    after the wrapper starts, although the pipeline keeps running.
  * Dummy's check pipeline took 26 s (created 21:20:14Z, finished 21:20:40Z). sample-consumer's (the index
    extra, a 90 s test job, and runner #12 at `concurrent = 1`) could come close.
* **F3, minor** [V]: GATE-001's lint advice on sample-consumer ("fails even narrowed to F,E9: fix those, or set
  gates.lint to []") narrows the rules but never the paths. The project's own rule (`--select F,E9` on its source and
  test directories) passes, so following the advice drops lint altogether.
* **F4, minor** [V]: init writes "no `uv.lock`, run `uv lock`" and "ruff is not a dependency" only as `# TODO` lines in
  `.l4/config.yaml`. Its console output has neither (0 matches for `uv lock`).
* **F5, cosmetic** [V/I]: `test: pass (186/192 passed)` does not say what the other 6 were. They are not failures,
  since the gate passed, so presumably skips.
* **F6, cosmetic** [V]: the watcher repeats the pipeline URL right after the OK row, and prints `pipeline #2849 success`
  before the last job's `success` line.
* **F7, capacity** [V]: sample-consumer's hand-written `test` job is tagged `agentic` and has no schedule guard
  (only init writes one). With the new `*/30` schedule it runs about 90 s on runner #12 every half hour, in the same
  minute as dummy's sweep (`concurrent = 1`). The fix is the maintainer's: `setup gitlab --project 119 --cron
  '0 * * * *'`, or the guard line in that job. Nothing was changed on 119 beyond the upgrade.
* **Not exercised** [U]:
  * R1–R6 in a live unit: no unit ran or parked. The "Waiting for capacity" note, `exit_reason` and
    `availability.unavailable` were not seen.
  * `--rotate`/`--revoke-old`, `--secret`, `l4 ci watch` on its own, and a check pipeline that fails.

**Left behind:**
* dummy-agentic: pin `6b72c0d`, schedule id 1 (`*/30`).
* sample-consumer: pin `6b72c0d`, schedule id 2 (`*/30`).
* Tokens 63 and 64 and both `L4_FORGE_TOKEN` variables are unchanged.
* No MR, label or note changed on either project.
* The clones and the local adoption copies are in the session scratchpad only.

## 2026-10-06 — M1.9 "re-verify after the hand-off" live (harness `fce8a68` = the M1.9 merge `3da5fce` + the plan log, live-fix `7ccbc43`)

Live check of M1.9 on two projects. The operator acted as the human on dummy-agentic and as maintainer on both.
* **sample-consumer (119), G1 + G3 + P4 + P5:** MR !1 had an owner commit `7ac1702` after the hand-off `d731a47`
  that changes only `.gitlab-ci.yml`. The upgrade push had to re-verify it, list the owner's change as information,
  hand off again (H2) and leave H2's project `test` job green.
* **dummy-agentic (118), G2 + P4 + P5 + loop safety:** the human made the project's own `test` job stricter than the
  L4 gates. A seeded unit had to hand off green on the L4 gates and red on the project job. Then the sweep had to
  record `ci.failed`, `l4 run` take `in_review → verifying (repository_ci_failed)`, step 0 fail with
  `repository CI failed: test`, a chore fix unit run, a full round pass, H2 be made, and H2's project CI be green.

Both clones are fresh SSH clones in the session scratchpad. Dummy logs (ANSI and section markers stripped), ledgers and
reports are in [m19/](m19/), with job artefacts under [artifacts/](artifacts/). The sample-consumer evidence stays in the git-ignored
`docs/adoption/sample-consumer/live/m19/` (private source text), so below it is given as counts and pass/fail only.
Labels: [V] seen in a log, file or API answer; [I] inferred; [U] not checked.

**Token scan** of the 230 saved files (both folders, the job artefacts and the new test fixture): no `glpat-`,
`glcbt-`, `glptt-`, `apikey_`, `sk-`, `mk_agent_` or JWT shape, and no Jev key or its first 8 characters (0 hits). The
scanner was checked first on a planted `glpat-`/`sk-` file (1 file, both patterns found).

**Verdict: PASS on every required check.** One M1.9 defect was found live and fixed (`7ccbc43`): the evidence a G2 fix
task gets was runner boilerplate. The fix was re-checked live, and the evidence now holds the job's error. In that
re-check Codex's fix was wrong; the judge caught it, and the unit escalated by the dummy's `max_fix_rounds: 1`.

### The harness change: `7ccbc43` m1.9(live-fix)

* **The defect** [V]: `ci.failed.jobs[].tail` is the raw GitLab trace. It keeps per-line runner timestamps
  (`2026-…Z 01O `), `section_start/section_end` markers and the runner's closing `cleanup_file_variables` section.
  * `ci_detail` opens a fix task with the last 300 characters of that tail ("Log ends: …"). In job 5604 those were
    only cleanup lines and `ERROR: Job failed: exit code 1`.
  * The fix prompt of job 5606 had 0 occurrences of `E501`. Codex found the cause itself by reading `.gitlab-ci.yml`
    and running the stricter ruff command (its agent log).
* **The fix:** `job_log_text` in `forge/gitlab.py`. It drops the runner prefix, the section markers, lines of control
  sequences only, and the runner's `upload_artifacts_on_*` and `cleanup_file_variables` sections, before `clip_log`.
  `strip_ansi` is now public in `forge/base.py`.
* **Tests:** two new tests in `tests/unit/forge/test_gitlab_pipelines.py`, written first and seen failing. One uses a
  fixture shaped like job 5604's trace and asserts that the `ci_detail` summary holds `E501`; the other covers a
  trace without timestamps.
* **Checks:** `tests/unit/forge`, `tests/unit/ci`, `test_fixunit.py`, `test_preconditions.py` and
  `test_review_reentry.py` give 380 passed. Ruff check and format are clean on the three files.
* **Offline proof on the real trace** ([b8-livefix-tail-of-job-5604.txt](m19/b8-livefix-tail-of-job-5604.txt)):
  before, the summary has no `E501`; after, it reads `Log ends: ...lect E501 --line-length 92 src E501 Line too long
  (108 > 92) --> src/pricing/notices.py:2:93 | … Found 1 error`.

### sample-consumer (119): counts and pass/fail only

| Step | Pipeline / job | Result |
|---|---|---|
| A1 `l4 upgrade` to `fce8a68`, 1 commit `47004fa` (the project's documented author identity), pushed to `main` (the only push to 119) | — | **pass.** 43 files: 42 under `.l4/` (6 vendored files added, 35 changed) and `pyproject.toml`. `upgrade` printed `registered the l4 pytest marker in pyproject.toml`: one entry appended to the existing multi-line `markers` array, and `tomllib` parses it. The quote style differs from the file's (F3) |
| A2 the push pipeline | #2859 / `test` 5591 success, `l4` 5592 success (360 s) | **pass, G1 + G3.** `plan --sweep` row: `verify  in_review: commit(s) after the hand-off not made by the harness: 7ac1702edc`. The trace reads `phase in_review → verifying (commit_after_handoff: 1 commit, 7ac1702edc <the owner's CI commit> by <owner>)`. The base merge followed: `1543e00`, `main@47004fa883`, 2 behind. Round 2's `subject_sha` is `1543e00`, whose first parent is `7ac1702`. Step 1 integrity was ok, with `protected paths … no protected path differs from the base (+1 changed by humans, listed)`. `verification.md` has the section "Protected paths changed by humans (allowed, L4-SEC-004)" with `.gitlab-ci.yml: 7ac1702edc`, and the scope row for that file reads `changed by human commit 7ac1702edc` (no hold). Gates: test 196/196 and audit 197/197; `test-presatisfied fail (expected: zero values must fail)` (P6). Verdict PASS 3/3, 5 minor findings (F4), $0.40. H2 is `b692e87` (bot, `L4-Run`, `L4-Phase: verified`, no `[skip ci]`). MR !1 is ready with `l4:in_review` and sha `b692e87`. `pr.ready{url: <forge>/…/merge_requests/1, head: b692e87…}` |
| A2 draft before the first push (L4-ARC-008 c) | MR !1 notes | **pass** [V, API timestamps]: marked draft 23:37:55.991Z, then the labels at 23:37:56.996Z and the sticky "Re-verifying after the hand-off" (naming `7ac1702edc`) at 23:37:57.919Z. The first push came after these (23:37:59.581Z). After H2 the sticky is back to "Nothing is waiting for a human answer." |
| A3 H2's project CI | #2865 / `test` 5595 | **pass.** 197 passed, 51 deselected. The pipeline had only `test` (H2 carries `L4-Run`) |
| P5 on the branch and lock ref | — | **pass.** The 4 new branch commits add 0 lines with the forge host. The new pending ledger has 0 host hits and 1 `<forge>`. The older pending ledger (`r-20261005T1818Z`) keeps its host, as planned (history is not rewritten) |
| A4 loop safety: the next scheduled sweep | #2905 / `l4` 5609 | **pass.** `ci: H b692e878aa green`, then `run: nothing to do`. `ls-remote refs/l4/* refs/heads/*` is unchanged, and MR !1 was last updated at 23:43:40Z |

MR !1 was not merged. The sample-consumer pin stays at `fce8a68` (the live-fix was not pushed to 119).

### dummy-agentic (118)

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| B1 `l4 upgrade` to `fce8a68`, push [`e5ea81c`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/e5ea81c79941d56b3c1a37f28bf92df360a35416) | [#2860](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2860) / [5594](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5594) | **pass.** 43 files. `registered the l4 pytest marker in pyproject.toml` (one `markers = [...]` line under `[tool.pytest.ini_options]`). Every doctor row at error passes. `plan --sweep` printed 11 `ci: H <sha10> green` lines (every old in-review unit's H pipeline was green, checked before the push), then `nothing to do`. The refs are byte-identical apart from `main` | [b1-upgrade-l4-job-5594.txt](m19/b1-upgrade-l4-job-5594.txt) |
| B2 as the human: the `test` job gains `uv run ruff check --select E501 --line-length 92 src`, and the seed `add-return-policy` (a constant) is added ([`71ec72f`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/71ec72f)) | #2866 / test 5596, l4 5597; #2871 / 5599; #2880 / 5601 | **seed error, then reset.** Q-001 (`ambiguous`, intake lint L4-ODD-004) came from my two scenarios with the same WHEN. Answered. Then Codex's red phase stubbed the constant as a function, and green raised Q-002 and, after acceptance, Q-003 (F5). Reset by the retry rule: MR !27 closed, branch deleted | [5597](m19/b2-seed-l4-job-5597.txt), [5599](m19/b3-implement-l4-job-5599.txt), [5601](m19/b3b-implement-l4-job-5601.txt), [questions.md](m19/b3-add-return-policy-questions-at-cf6c2f7.md) |
| B3 reseed [`f2274d4`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/f2274d4cac234c974d26ec4c11b4ebf374d38b82): `add-return-notice`, `pricing.notices.return_policy()` returns an exact 95-character text, one scenario | [#2887](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2887) / test [5602](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5602), l4 [5603](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5603) | **pass.** The base anchor `test` 5602 is green, including the new step (`All checks passed!`). Codex went red → green, the L4 gates passed (lint 110), and the judge gave PASS 1/1. H is [`2320b4e`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2320b4e3d26a339702b46c96a011c4a4078f2a8f) and [MR !28](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/28) is ready. The natural line is 108 characters | [b4-implement-l4-job-5603.txt](m19/b4-implement-l4-job-5603.txt), [base test](m19/b4-base-test-job-5602.txt) |
| B4 H's project CI | [#2894](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2894) / [5604](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5604) | **red, as designed.** `E501 Line too long (108 > 92)` at `src/pricing/notices.py:2:93`, `Found 1 error.` | [b5-h1-test-job-5604.txt](m19/b5-h1-test-job-5604.txt) |
| B5 the `*/30` schedule (00:03Z): sweep, then `l4 run`, in one job | [#2895](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2895) / [5606](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5606) | **pass, G2 end to end** (details below the table) | [b6-sweep-reverify-l4-job-5606.txt](m19/b6-sweep-reverify-l4-job-5606.txt), [ci.failed ledger](m19/b6-sweep-ci-failed-pending-ledger-r-20261006T0003Z-d2b3.jsonl), [run ledger](m19/b6-reverify-pending-ledger-r-20261006T0003Z-a64f.jsonl), [round 2](m19/b6-verification-round2-step0.md), [round 3](m19/b6-verification-round3.md), [fix proposal](m19/b6-fix-unit-1-proposal-at-4cc06e6.md), [commits](m19/b6-add-return-notice-commits.txt), [MR notes](m19/b6-mr28-notes-from-0000.txt) |
| B6 H2's project CI | [#2904](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2904) / [5607](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5607) | **pass.** The stricter step prints `All checks passed!` | [b7-h2-test-job-5607.txt](m19/b7-h2-test-job-5607.txt) |
| B7 loop safety: a green sweep on H2 writes nothing | #2906 / 5611, #2914 / 5614, #2925 / 5616 | **pass.** Three later sweeps print `openspec:add-return-notice: ci: H c8dfcd9560 green`. The branch stays `c8dfcd9` and the lock ref `d792726f` | [5611](m19/b8-livefix-upgrade-shipping-notice-l4-job-5611.txt) |
| P5 | — | **pass.** The 9 branch commits add 0 lines with the forge host and 6 with `<forge>`. The 3 pending ledgers have 0 host hits. The console trace, the `.l4-out/logs` mirror and `outcome.json` keep the full URL, as designed | — |
| B8 live-fix re-check: upgrade to `7ccbc43` (3 vendored files and the pin; no marker line, as it is already there) and the seed `add-shipping-notice` ([`bb427bf`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bb427bf)) | #2906 / [5611](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5611); H [`0272e10`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/0272e10c233ca7f18a6fd81900ea54acc8113c1a) red in #2913 / 5612 | **pass.** PASS 1/1, [MR !29](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/29) ready, H red on the 108-character line | [b8-h1-shipping-test-job-5612.txt](m19/b8-h1-shipping-test-job-5612.txt) |
| B9 the 00:33Z schedule | [#2914](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2914) / [5614](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5614) | **the live-fix holds** [V]. The `ci.failed` tail has 0 timestamp lines and 0 section markers, and ends `E501 Line too long (108 > 92)` … `Found 1 error.` `ERROR: Job failed: exit code 1`. The fix prompt holds `E501 … footer.py:2:93`. The sticky read "Re-verifying after the hand-off … The project's own CI is red on the hand-off commit `0272e10c23` (pipeline 2913): `test`" while the round ran. **But Codex's fix was wrong:** it put the literal in parentheses on its own line (105 > 92) and ran only pytest. The round-3 judge caught it ("Fix for F-2aa04fcb probably does not fix the E501 CI failure", major) and the verdict was NEEDS_HUMAN with verdict question Q-001 | [5614](m19/b9-livefix-sweep-reverify-l4-job-5614.txt), [ci.failed ledger](m19/b9-livefix-sweep-ci-failed-pending-ledger.jsonl), [fix proposal](m19/b9-fix-unit-1-proposal-at-b5a130a.md), [round 3](m19/b9-verification-round3-needs-human.md), [sticky log](m19/b9-mr29-sticky-watch.txt) |
| B10 as the human: `reject` on Q-001 ([`6b4b7af`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/6b4b7af)) | #2925 / [5616](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5616) | **escalated, as configured.** `verdict FAIL (round 4 …)` led to `phase verifying → escalated (verify_fail_exhausted)`, exit 13: the dummy's `max_fix_rounds: 1` was used up. The unit did not hand off a red head (decision 11 f) | [5616](m19/b10-verdict-reject-escalated-l4-job-5616.txt), [round 4](m19/b10-verification-round4-escalated.md) |

**G2 in job 5606, line by line** [V]:
* **The sweep.** `plan --sweep` printed `openspec:add-return-notice: ci: H 2320b4e3d2 red: test (recorded)` and the plan
  row `verify  in_review: repository CI failed on 2320b4e3d2: test`. The pending ledger of the sweep run has
  `ci.failed{head: 2320b4e…, pipeline: 2894, jobs: [{name: test, stage: test, url: <forge>/…/jobs/5604, tail}],
  preexisting: []}`. The base job `test` was green (5602), so the red job counted as new.
* **The edge.** `phase in_review → verifying (repository_ci_failed: test on 2320b4e3d2)`. MR !28 was marked draft at
  00:03:38.402Z, before the first push at 00:03:43.005Z.
* **Round 2.** Step 0 `failed`, with the note `repository CI failed: test`. Steps 1–9 `not_run`, verdict
  `FAIL (round 2, 0/0 criteria pass, 1 finding(s))`. There is no `verify.judge` event in round 2 and no
  `verify-judge-r2` prompt in the artefacts. The judge was still *selected* first, which the plan lists as a known cost.
* **The fix unit.** `add-return-notice-fix-1`, with `fix.json` `chores: [F-2aa04fcb]` and the task
  `1.1 repository CI failed: test (F-2aa04fcb)`. It ran one `single` step (`L4-TDD: exempt`). Codex split the
  literal: [`69822d6`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/69822d64141b57b0c66fc6b059b0b4c72d8d91a6).
* **Round 3.** A full ladder: gates, S1, judge PASS 1/1 with 2 minor findings, $0.08.
* **The hand-off.** H2 is [`c8dfcd9`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c8dfcd956095035ea99c82641b29a255ec48955b),
  a new commit without `[skip ci]`. `pr.ready.head` is H2. MR !28 is ready with `l4:in_review`.

### Findings

* **F1, M1.9 defect, fixed live** [V]: the G2 fix task got runner boilerplate instead of the job's error (see "The
  harness change" above). Re-checked live in B9: the evidence is right now.
* **F2, design gap, M1.9 scope** [V]: nothing checks deterministically that a `repository CI failed` chore fixed the
  job.
  * The chore step runs only the L4 gates, and the project job's command is not one of them.
  * In B9 a wrong fix (105 > 92) passed every gate; only the judge's reading caught it.
  * Candidates for later: re-run the red job's script lines locally when they are runnable, or let the fix step
    see the CI command.
* **F3, cosmetic** [V]: `register_l4_marker` picks the array's quote character from the last *quoted run* it can
  match, so `"… -m 'not ui'"` yields `'`.
  * On sample-consumer the new entry is single-quoted in a double-quoted array. It is valid TOML and
    `tomllib`-checked.
  * Cause: `_quote` in `init/pytest_marker.py`; its regular expression cannot match a double-quoted string that
    contains `'`.
* **F4, judge noise on re-verification** [V]:
  * On sample-consumer the judge raised minors about the owner's CI change. The plan names this risk.
  * Both re-verifications got a minor finding about the previous round's `verification.md`, committed in the unit
    folder ("stale PASS"/"stale FAIL"). The judge's diff includes harness-owned files that the scope check already
    exempts.
  * On sample-consumer the judge also flagged an audit test committed after its diff was taken.
* **F5, pre-existing, not M1.9** [V]: after a human accepts an answer that says "correct the frozen red test", green
  still cannot edit the test. The red manifest restores it, so green asks again (Q-002, then Q-003). The only way out
  is the retry rule.
* **Seed errors, mine, not the harness's:** two scenarios with the same WHEN trip L4-ODD-004 by design (`ambiguous`
  always escalates, even when the clarifier says "no conflict"). A spec for a constant gives red no honest failing
  stub.
* **F6, minor trace gap** [V]: plan line 11's WARNING `repository CI failed on <H10>: … (pipeline N); l4 run
  re-verifies` never prints live. The sweeper's `_UnitRun` writer has no progress observer. The console shows only
  `ci: H … red: test (recorded)` and the run's `phase … (repository_ci_failed: …)` line, which carry the same facts.
* **F7, cosmetic, pre-existing** [V]: `question Q-001 raised (verdict): None`: the verdict question's title prints as
  `None` (also seen in M1.3).
* **Agent behaviour, n = 1 each** [V]: with the useless evidence (B5) Codex investigated and fixed the job right. With
  good evidence (B9) it trusted the text and fixed it wrong. No causal claim.
* **Not exercised** [U]:
  * `ci.preexisting` (no job red on both H and the base);
  * the spec-edit route `spec_edit_after_handoff`;
  * a lost H;
  * GitHub check runs;
  * the G1 route on the dummy.

**Spend** [V, traces]:
* Codex: 9 agent steps (red and green for 3 units, 1 more green attempt in the reset unit, 2 chore steps); its weekly
  window at 4 %.
* Claude:
  * dummy: 3 clarifier calls and 4 judge calls, $0.45;
  * sample-consumer: 1 audit and 1 judge call, $0.40.
* Laya (local) and Jev: S1 and shadow on each full round.

**Left behind:**
* dummy-agentic:
  * pin `7ccbc43`; the 92-character step stays in `.gitlab-ci.yml` on `main`;
  * MR !28 `add-return-notice` ready (`l4:in_review`, H2 green);
  * MR !29 `add-shipping-notice` draft, `l4:escalated` (its last fix is still 105 > 92);
  * MR !27 closed and its branch deleted;
  * `openspec/changes/add-return-policy` removed from `main`; schedule id 1 unchanged.
* sample-consumer:
  * pin `fce8a68`, marker entry in `pyproject.toml`;
  * MR !1 ready at H2 `b692e87`, not merged;
  * schedule id 2 (`7 * * * *`) unchanged.
* Harness `main`: `7ccbc43` (live-fix), not pushed.
* The clones are in the session scratchpad only.

## 2026-10-06 — M1.10 "the M1.8 and M1.9 live findings" live (harness `692a639` = the M1.10 merge `20f03a4` + the merge log)

Live check of M1.10 on dummy-agentic (118) only. The operator acted as the human and as maintainer. The checks:
* **C1, end to end.** The dummy's `test` job still had the stricter step `uv run ruff check --select E501
  --line-length 92 src` (left by M1.9). A seeded unit had to hand off green on the L4 gates and red on that step. Then
  the sweep had to send it back to `verifying (repository_ci_failed)` and step 0 had to fail. The fix unit's gates had
  to include `repository-ci:test`, which runs that ruff command. A wrong fix had to be caught by the gate, not only the
  judge, and H2's project CI had to be green.
* **C4, C5 and C7 visible:** the sweep's warning line, the title of a raised question, and the runner tags in
  `setup gitlab`.
* **Cleanup:** after the check the 92-character step was removed from the dummy's `test` job.

The clone is a fresh SSH clone in the session scratchpad. Logs (ANSI and section markers stripped), ledgers, reports
and API snapshots are in [m110/](m110/), with job artefacts under [artifacts/](artifacts/). Labels: [V] seen in a log,
file or API answer; [I] inferred; [U] not checked.

**Token scan** of the saved files (`m110/` and the four new `artifacts/job-*` folders): 93 files, 89 of them committed.
The other 4 are the copied `.l4-out/.gitignore` files, which were dropped after the scan. There was no `glpat-`,
`glcbt-`, `glptt-`, `apikey_`, `sk-`, `mk_agent_` or JWT shape, and no Jev key or its first 8 characters (0 hits). The
scanner was checked first on a planted `glpat-`/`sk-` file (1 file, both patterns found).

**Verdict: PASS on every step that ran, with no harness change** (0 of the 2 allowed live-fixes were used). One
expected branch did not happen live: Codex's first chore attempt fixed the line, so no wrong fix reached the new gate
(F1). The plan's [U] on `uv run` in the gate sandbox is closed: the step ran there and reproduced the CI error (F4).

### dummy-agentic (118)

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 `l4 upgrade` to `692a639`, push [`2eb4d14`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2eb4d145a022fd19fcdbeb411391dccd5db143bd) | [#2942](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2942) / [5642](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5642) | **pass.** `.l4/vendor/`: 2 files added (`ci/failing_step.py`, `implementer/unfreeze.py`) and 34 changed, plus the `harness.commit` pin. `.l4/ci` and `.l4/bin` are unchanged, and there is no marker line (the marker is already registered). Every doctor row at error passes. CI-002 is warn/fail as before, and PRV-001 reports claude-code, codex and opencode-free ready. `plan --sweep` printed 12 `ci: H <sha10> green` lines, then `nothing to do`. Exit 0 | [b1-upgrade-l4-job-5642.txt](m110/b1-upgrade-l4-job-5642.txt) |
| 2 as the human: seed `add-pickup-notice` (`pricing.pickup.pickup_notice()` returns an exact 93-character text, one scenario, a function and not a constant) and the throwaway `add-gift-note` (two scenarios with the same WHEN), [`ec6ab61`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/ec6ab61231eef44b7cca46c62868ec2a9fc01494) | [#2943](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2943) / [5644](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5644) | **pass, exit 11 (allowed).** **C5** [V]: `[l4] openspec:add-gift-note question Q-001 raised (ambiguous): Scenarios "Gift note thanks the buyer" and "Gift note wishes the receiver well" conflict`, and the ledger's `question.raised` has `title` (`source: intake_lint`). The clarifier escalated Q-001 ($0.07), and [MR !30](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/30) became draft with `l4:awaiting_human`. The pickup unit went red → green (lint 110 passes), then judge PASS 1/1. H is [`222e60b`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/222e60b307534173b7a344a8cc609e319d490047) and [MR !31](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/31) is ready. The natural line is 106 characters | [5644](m110/b2-seed-pickup-giftnote-l4-job-5644.txt), [questions.md](m110/b2-add-gift-note-questions-at-1dae9fc.md), [ledger](m110/b2-add-gift-note-ledger-r-20261006T0501Z-be4d.jsonl) |
| 3 H's project CI | [#2955](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2955) / [5647](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5647) | **red, as designed.** `$ uv run ruff check --select E501 --line-length 92 src`, then `E501 Line too long (106 > 92)` at `src/pricing/pickup.py:2:93`, `Found 1 error.` | [b3-h1-test-job-5647.txt](m110/b3-h1-test-job-5647.txt) |
| 4 the `*/30` schedule (05:03Z; its `l4` job waited for 5644 through `resource_group`): sweep, then `l4 run` | [#2950](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2950) / [5646](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5646) | **pass, C1 and C4 end to end** (line by line below the table). Step 0 FAIL, then `ci.step` derived, then reproduced at the chore's base. The chore's must-pass `repository-ci:test` passed after attempt 1. Round 3 ran `repository-ci:test` (pass), and the judge gave PASS 1/1 with 0 findings. H2 is [`939d100`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/939d100f49306898d1f2b1dcc4760a4cce9bb416) | [5646](m110/b4-sweep-reverify-l4-job-5646.txt), [ci.failed ledger](m110/b4-sweep-ci-failed-pending-ledger-r-20261006T0504Z-7f11.jsonl), [run ledger](m110/b4-reverify-run-ledger-r-20261006T0505Z-0bdf.jsonl), [pending ledger](m110/b4-reverify-pending-ledger-r-20261006T0505Z-0bdf.jsonl), [round 2](m110/b4-verification-round2-step0.md), [round 3](m110/b4-verification-round3.md), [fix proposal](m110/b4-fix-unit-1-proposal-at-f6546fc.md), [fix.json](m110/b4-fix-unit-1-fix-json.json), [fix diff](m110/b4-fix-commit-4bee00c-src.diff), [commits](m110/b4-add-pickup-notice-commits.txt), [gate logs](artifacts/job-5646/l4-out/gates/r-20261006T0505Z-0bdf/) |
| 5 H2's project CI | [#2964](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2964) / [5648](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5648) | **pass.** `$ uv run ruff check --select E501 --line-length 92 src` prints `All checks passed!`, and `20 passed` | [b5-h2-test-job-5648.txt](m110/b5-h2-test-job-5648.txt) |
| 6 **C7**: `scripts/forge/mk-l4-setup-gitlab.sh --project 118 --no-pipeline` (cwd: the upgraded clone, so `.l4/bin/l4` is `692a639`) | — | **pass, no changes.** The runner row now ends with the tags [V]: `WARN  runner #12 (instance_type, online) is an instance runner on an internal project: … Prefer a project or group runner; tags: agentic, ai, opencode`. KEPT: token `l4-bot id=63`, variable `L4_FORGE_TOKEN` (scope `l4`, masked) and the schedule. Summary: `3 ok, 0 new, 0 set, 3 kept, 2 warn, 0 fail -> exit 0`. The wrapper passed `--token-command`; nothing answered 401, so it was not called | [c7-setup-gitlab-no-pipeline.txt](m110/c7-setup-gitlab-no-pipeline.txt) |
| 7 as the human, cleanup: MR !30 closed and `l4/openspec/add-gift-note` deleted (it had no lock ref). Then [`78ec73f`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/78ec73fdaa9002260c1892ee6585fa1642eb5e90) restores the `test` job of before M1.9 (`.gitlab-ci.yml` as at `71ec72f^`: the comment and the 92-character step go) and removes `openspec/changes/add-gift-note` | [#2965](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2965) / `test` [5649](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5649), `l4` [5650](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5650) | **pass.** `test` runs `uv run pytest -q` (19 passed) and `uv run ruff check --extend-exclude .l4 .` (`All checks passed!`), and no third step. **Loop safety:** `openspec:add-pickup-notice: ci: H 939d100f49 green`, then `run: nothing to do`. Afterwards the pickup branch is still `939d100` and its lock ref still `5a006b4`. MR !31 is ready with `l4:in_review`, last updated 05:07:04Z | [5650](m110/b6-cleanup-l4-job-5650.txt), [5649](m110/b6-cleanup-test-job-5649.txt), [MR state and notes](m110/b7-mr31-and-mr30-state-and-notes.txt) |

**C1 and C4 in job 5646, line by line** [V]:
* **The sweep (C4).** The sweep printed the warning line once, before the per-unit lines, and printed no `run …
  started` line of its own:
  ```
  [l4] openspec:add-pickup-notice repository CI failed on 222e60b307: test (pipeline 2955); l4 run re-verifies
  openspec:add-pickup-notice: ci: H 222e60b307 red: test (recorded)
  openspec:add-pickup-notice    in_review       1/1    verify  in_review: repository CI failed on 222e60b307: test
  ```
  The pending ledger's `ci.failed.jobs[0].step` is `uv run ruff check --select E501 --line-length 92 src`, next to
  the 40-line `tail`.
* **The edge and step 0.**
  ```
  [l4] openspec:add-pickup-notice phase in_review → verifying (repository_ci_failed: test on 222e60b307)
  [l4] openspec:add-pickup-notice CI job test: failing step derived `uv run ruff check --select E501 --line-length 92 src`
  [l4] openspec:add-pickup-notice verdict FAIL (round 2, 0/0 criteria pass, 1 finding(s))
  ```
  The event is `ci.step{job: test, status: derived, reason: null, source: ".gitlab-ci.yml@222e60b307"}`. Round 2's
  step 0 note is `base main@ec6ab61231 contained; repository CI failed: test`. Steps 1–9 are `not_run` and the judge
  made 0 calls. MR !31 was marked draft at 05:05:14.0Z (API note), before the run's first push at 05:05:17.8Z
  (trace).
* **The fix task.** Its detail starts with the step:
  ```
  F-2aa04fcb (blocker): repository CI failed: test: failing step: `uv run ruff check --select E501 --line-length 92 src` (job `test` at 222e60b307). job `test` (stage test) failed on the hand-off commit 222e60b307 (<forge>/…/jobs/5647). Log ends: ... --select E501 --line-length 92 src E501 Line too long (106 > 92) --> src/pricing/pickup.py:2:93 …
  ```
  `fix.json` has `chores: [F-2aa04fcb]`, and the agent prompt carries the same line.
* **The chore's gates.** First the step runs at the chore's clean base, and it reproduces:
  ```
  [l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] gate repository-ci:test fail (exit 1) — exit code 1
  [l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] CI job test: failing step reproduced `uv run ruff check --select E501 --line-length 92 src`
  [l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] agent single task 1.1 ok (20.1s)
  [l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] gate repository-ci:test pass (exit 0)
  [l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] task 1.1 green ok: all tests passing
  ```
  The gate log [005-repository-ci_test.log](artifacts/job-5646/l4-out/gates/r-20261006T0505Z-0bdf/005-repository-ci_test.log)
  holds the same `E501 Line too long (106 > 92)` and `--> src/pricing/pickup.py:2:93` as the CI log, and the
  [009](artifacts/job-5646/l4-out/gates/r-20261006T0505Z-0bdf/009-repository-ci_test.log) log reads `All checks
  passed!`. Codex split the literal into two adjacent strings
  ([`4bee00c`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/4bee00c16f66aec90c0bcaa4bd2ba68a7f133aaa),
  `L4-TDD: exempt`).
* **Round 3.** It ran `repository-ci:test` as a step-2 gate between `lint` and `test`:
  ```
  [l4] openspec:add-pickup-notice gate repository-ci:test pass (exit 0)
  [l4] openspec:add-pickup-notice verdict PASS (round 3, 1/1 criteria pass, 0 finding(s))
  [l4] openspec:add-pickup-notice commit 939d100f49 docs(add-pickup-notice): hand off to review
  ```
  `verification.md` round 3 has the gate row `| repository-ci:test | pass | \`uv run ruff check --select E501
  --line-length 92 src\` | …/012-repository-ci_test.log |`. `pr.ready.head` is H2, and H2 is a new commit without
  `[skip ci]`.
* **C3, seen in passing.** Round 3's judge prompt has the rubric line about Owner changes and no Owner-changes block,
  because no person changed a file. Its diff has no `openspec/changes/add-pickup-notice/verification.md`, although that
  file has been on the branch since round 1.

### Findings

* **F1, not exercised live** [U]: no wrong fix reached the new gate, because Codex's first attempt was right. The
  path "a wrong fix fails `repository-ci:<job>` and is retried with the error in the prompt" rests on the unit tests
  of build lines 7 and 9.
  * There is evidence that the gate, not only the judge, would have caught M1.9's wrong fix
    ([b8-offline-gate-on-mr29-wrong-fix.txt](m110/b8-offline-gate-on-mr29-wrong-fix.txt), [V offline]). The exact
    gate command, run on MR !29's head `cf11e7a` (B9's literal in parentheses on its own line), exits 1 with `E501
    Line too long (105 > 92)` at `src/pricing/footer.py:3:93`.
  * The same command failed in the live gate sandbox at the chore's base (exit 1).
* **F2, environment, not M1.10** [V]: step 8 (S1) was `unavailable` in rounds 1 and 3 with `the System-One request
  failed (RemoteProtocolError)`.
  * `laya-serve` exited with code `-4` on its first request, and a restarted instance answered the later ones.
  * S1 never decides, and both verdicts came from the judge.
  * M1.10 changed no System-One file (`git diff --stat 8e1c562 20f03a4`). In M1.9's rounds, step 8 was `ok … judged
    by laya-local`, and no saved M1.8/M1.9/hb log has `exit code -4`.
  * Both M1.9 and M1.10 doctor rows read `ENV-006 … laya 0.3.24, checkpoint typed-decisions cached`, so laya itself
    did not change. In M1.9 both `laya-serve` instances stopped with `-15`. The cause is the VM or something under
    laya [I]; which one is not known [U].
* **F3, cosmetic** [V]: the fix proposal's one-line text keeps going after the summary. After `… ERROR: Job failed:
  exit code 1.` it shows the start of the whole tail (`Removing .ruff_cache/ …`), cut at 600 characters.
  * The detail is the summary, then a blank line, then the whole tail (`ci_detail`). The proposal flattens both.
  * The summary itself, which comes first, is right.
* **F4, the plan's `uv run` risk is closed for this runner** [V]: `uv run ruff …` ran in the gate sandbox (default
  `gates.network: allow`): exit 1 at the base, with the CI error lines, and exit 0 after the fix. With the network off
  it is still [U].
* **Not exercised** [U]:
  * C2: no green step asked to change a frozen test;
  * C6: the marker was already registered, so the upgrade printed no marker line;
  * C8: no 401 came within the token's 600 s, so `--token-command` was never called;
  * C9 and C10: the laptop step on sample-consumer was not in this brief;
  * `ci.preexisting`, a skipped `ci.step`, and GitHub.

**Spend** [V, traces]:
* Codex: 3 agent steps (red, green, 1 chore attempt); its weekly window at 4 %.
* Claude: 1 clarifier call and 2 judge calls, $0.21 ($0.0737 + $0.0712 + $0.0606).
* Laya (local) and Jev: S1 and shadow on rounds 1 and 3 (F2).

**Left behind:**
* dummy-agentic:
  * pin `692a639`. The `test` job is back to `pytest` + project-wide ruff, with no 92-character step;
  * MR !31 `add-pickup-notice` ready (`l4:in_review`, H2 `939d100` green), not merged;
  * MR !30 closed and its branch deleted; `openspec/changes/add-gift-note` removed from `main`;
  * MRs !28 and !29 as M1.9 left them; schedule id 1 unchanged.
* Harness `main`: `692a639` plus this evidence commit, not pushed.
* The clone is in the session scratchpad only.

## 2026-10-06 — M1.11 "the sample-consumer wave A findings" live (harness `f4fc2ef` = the `m111` head, not merged; live-fix `28b8cc3`)

**The harness is the `m111` branch, not `main`.** The M1.11 landing stopped before any merge, because the tracked file
`.serena/project.yml` was modified in the harness checkout. So this check vendored the `m111` head `f4fc2ef` into the
dummy. The one live-fix, `28b8cc3`, is on `m111` too, so it lands with the merge. Harness `main` gets only this evidence
commit.

Live check of M1.11 on dummy-agentic (118) only. The operator acted as the human and as the maintainer (GitLab user
2, Owner). The checks:
* **W10:** the time from a new unit's first task start to its first `gate setup pass`, before and after;
* **W1:** a seeded unit whose red tends to fail on an existing test, and the retry prompt that follows;
* **W2:** the halted unit resumed from CI through the `l4:resume` label, first alone and then after a person's fix;
* **W4:** the `main` pipeline of a halting run;
* **W9:** the MR text.

W3 and W5–W8 rest on their unit tests. Below, under Findings, is what was seen of them anyway. The sample-consumer
step (MF-7) and the wrapper step (W11) of the plan's live protocol were not in this brief.

The clone is a fresh SSH clone in the session scratchpad. Logs (ANSI and section markers stripped), API snapshots and
`verification.md` are in [m111/](m111/), and job artefacts are under [artifacts/](artifacts/). Labels: [V] seen in a
log, file or API answer; [I] inferred; [U] not checked.

**Token scan** of the saved files (`m111/` and the three new `artifacts/job-*` folders): 125 files. There was no
`glpat-`, `glcbt-`, `glptt-`, `apikey_`, `sk-`, `mk_agent_` or JWT shape, and no Jev key or its first 8 characters
(0 hits). The 3 copied `.l4-out/.gitignore` files were dropped after the scan, which leaves 122 files committed. The
scanner was checked first on a planted `glpat-`/`sk-` file (1 file, both patterns found).

**Verdict:**
* **W10, W2, W4 and W9 (MR text): PASS.**
* **W1: FAIL at `f4fc2ef`, PASS after live-fix `28b8cc3`** (1 of the 2 allowed live-fixes was used). Red edited an
  existing test in place and added no test id. The retry then said only `tests not collected individually`, with no
  excerpt, and the agent did the same thing again (F1).
* **Suite at `28b8cc3`:**
  * `uv run pytest -q`: 4285 passed, 78 skipped, 1 xfailed (4364 = the 4362 of `f5bc391` + the 2 new tests);
  * `ruff check .` clean;
  * `templatelock --write` gave no diff.

  `tests/unit/implementer` (389 passed) and `ruff format --check` on the two touched files ran before the live-fix
  commit.

### dummy-agentic (118)

| Step | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 `l4 upgrade` to `f4fc2ef`, push [`ad5cdd4`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/ad5cdd40b23110c12a4886e2cb797f2dc4e91d18) | [#3177](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3177) / [5807](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5807) | **pass.** `.l4/vendor/`: 5 files added (`ci/resume_label.py`, `implementer/excerpt.py`, `implementer/uvseed.py`, `sandbox/seed.py`, `templates/single_tests.md`) and 45 changed, plus the pin. **The include changed** [V]: `exit_codes: [10, 11, 12, 13]  # 13: a halt is unit state (label, sticky note, exit_reason), not a failed job`. Every doctor row at error passes, and PRV-001 reads `claude-code ready; codex ready; opencode-free ready`. `plan --sweep`: 12 `ci: H <sha10> green`, then `nothing to do`. Exit 0 | [local upgrade](m111/b1-upgrade-local.txt), [5807](m111/b1-upgrade-l4-job-5807.txt) |
| 2 as the human: seed `add-restock-label` (plain: `inventory.labels.restock_label(sku)` returns `RESTOCK <sku>`) and `change-low-stock-rule` (W1: `is_low(LOW_STOCK_THRESHOLD)` becomes `True`; the task asks to "extend the existing test `test_a_quantity_at_the_threshold_is_not_low` … (keep the test's name)", which contradicts red's rule that an existing test must still pass), [`be27828`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/be278283b9159ea024e69b01e265c1ee594e53f3) | [#3181](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3181) / [5810](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5810) | **W10 pass, W4 pass, W1 FAIL (F1).** `add-restock-label`: the first new unit fills the seed, then red → green → judge PASS 1/1. [MR !33](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/33) is ready (`l4:in_review`). `change-low-stock-rule` copies the seed. Red failed 3 times: `tests not collected individually` twice (excerpt_lines 0), then `red broke existing tests: tests.test_stock::test_a_quantity_at_the_threshold_is_not_low` (excerpt_lines 5, but no attempt 4 to carry it). Then `halted: max_task_attempts (task 1.1)`, `l4 exit 13 (halted)`, `ERROR: Job failed: exit status 13`. Job `failed`, `allow_failure: true`. **Pipeline `success`, `passed with warnings`.** [MR !34](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/34) is draft with `l4:halted`, and the sticky note names the reason and the label | [5810](m111/b2-seeds-l4-job-5810.txt), [pipelines](m111/w4-pipelines-and-skipped-resume-commits.txt), [sticky note](m111/w4-mr34-sticky-at-first-halt.txt), [prompts and gate logs](artifacts/job-5810/l4-out/) |
| 3 live-fix `28b8cc3` on `m111` (below the table), then `l4 upgrade` to it, push [`2ca856e`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2ca856e1c3b27149abc21530bf1ce5add6fcfb9d) | [#3202](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3202) / [5828](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5828) | **pass.** `.l4/vendor/`: 2 files changed (`_commit.py`, `implementer/tdd.py`) and the pin. The planner now gives the W2 reason [V]: `openspec:change-low-stock-rule  halted  0/1  none  halted: a member adds the label l4:resume (or runs l4 resume)`. `run: nothing to do` | [local upgrade](m111/b1-upgrade-local.txt), [5828](m111/b3-livefix-upgrade-l4-job-5828.txt) |
| 4 **W2, label only**: as user 2 (access 50), `PUT merge_requests/34?add_labels=l4:resume` (label event 1532), then an `api` pipeline on `main` | [#3203](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3203) / [5830](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5830) | **W2 pass, W1 pass, W4 pass again.** The sweep resumes the unit and the run restarts 1.1 at red attempt 1 (line by line below the table). Attempt 2's prompt carries the excerpt, and attempt 2 leaves the existing test alone and adds a new one, but fails lint (`I001`). Attempt 3, given the lint excerpt, edits the existing test in place again, and the unit halts again (F2). Pipeline `passed with warnings` | [5830](m111/b4-resume-label-l4-job-5830.txt), [prompts and gate logs](artifacts/job-5830/l4-out/) |
| 5 as the human, the person's fix on the halted branch, [`eb66e39`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/eb66e39a59cf7f448a2e0bee75edeeeecd723ad5): the old rule's test becomes `test_a_quantity_above_the_threshold_is_not_low` (`not is_low(LOW_STOCK_THRESHOLD + 1)`, true under both rules); the task and proposal drop the request to edit it | [#3208](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3208) / [5832](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5832) | **pass (the W2 hint).** The before_script prints `l4: base checkout 2ca856e1c3…`. The sweep prints `[l4] sweeper: openspec:change-low-stock-rule: halted; a person pushed after the halt: add the label l4:resume to resume` once. `run: nothing to do`; the push alone resumes nothing. Event 1532 is not acted on again | [5832](m111/b5-person-push-l4-job-5832.txt) |
| 6 **W2 after the fix**: the label again (event 1538), then an `api` pipeline | [#3209](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3209) / [5834](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5834) | **pass, the unit continues.** `resumed by a member's l4:resume label (event 1538)`, with `unit.resumed{signal: label:1538, by: member}`. Red ok at attempt 1 (`1 new test(s) failing as expected`), then green ok. The base merge brings in `main@2ca856e1c3`. Judge PASS 1/1 with 3 findings, and H is [`cdfacea`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/cdfacea7bc9335618edb1ea836d629e13fc72e08). MR !34 is ready, `l4:in_review`, and its sticky note reads `Nothing is waiting for a human answer.` (the halted section has gone). `verification.md` lists the person's test change under "Test changes made by humans (allowed, L4-SEC-004)". Exit 0 | [5834](m111/b6-resume-after-fix-l4-job-5834.txt), [verification.md](m111/b6-change-low-stock-rule-verification-round1.md), [commits](m111/b6-change-low-stock-rule-commits.txt), [MR !34 labels and note](m111/w2-mr34-after-continue.txt), [artefacts](artifacts/job-5834/l4-out/) |
| 7 loop safety: one more `api` pipeline | [#3221](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3221) / [5837](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5837) | **pass.** 14 `ci: H <sha10> green` lines, including `add-restock-label: ci: H 97bcbc963a green` and `change-low-stock-rule: ci: H cdfacea7bc green`. Both units are `in_review: waiting for merge`. `run: nothing to do` | [5837](m111/b7-loop-safety-l4-job-5837.txt) |

**W10, the first setup of a new unit** [V, traces and `cache.seeded` events]:

| | Task start → first `gate setup pass` | Setup log |
|---|---|---|
| before: M1.10 `add-pickup-notice` (job 5644) | 05:02:10.215 → 05:02:21.568 = **11.4 s** | `Prepared 21 packages in 10.55s`, downloads of ruff, pygments and playwright, `warning: Failed to hardlink files; falling back to full copy` |
| after, the first new unit (fills the seed): `add-restock-label` (job 5810) | 18:50:20.937 → 18:50:29.516 = **8.6 s** | `gate seed pass` at 18:50:27.589. `cache.seeded{cache: uv, seconds: 6.6, bytes: 180255988, via: setup}`, then `{seconds: 0.3, via: copy}`. The [seed log](artifacts/job-5810/l4-out/gates/r-20261006T1849Z-1671/001-seed.log) reads `Prepared 21 packages in 5.74s`; the unit's [setup](artifacts/job-5810/l4-out/gates/r-20261006T1849Z-1671/002-setup.log) reads `Prepared 1 package in 303ms` |
| after, the second new unit (copy only): `change-low-stock-rule` (job 5810) | 18:53:03.936 → 18:53:05.950 = **2.0 s** | `cache.seeded{seconds: 0.8, via: copy}`. [Setup](artifacts/job-5810/l4-out/gates/r-20261006T1849Z-1671/019-setup.log): `Prepared 1 package in 348ms` (the project itself), `Installed 21 packages in 485ms`, no download and no hardlink warning (`UV_LINK_MODE=copy`) |

The dummy's before was already about 11 s: its 21 packages download in about 10 s. So the gain here is the download
and the warning disappearing (11.4 s → 2.0 s), not minutes. The 8–11 minutes of W10 were sample-consumer's 52
packages, and they were not measured here.

**W1 and W2 in jobs 5810 and 5830, line by line** [V]:
* **At `f4fc2ef` (job 5810).** Red attempt 1 edited the existing test in place and added none. The gate (`20 tests: 19
  passed, 1 failed`) shows `E       assert False` / `E        +  where False = is_low(5)` /
  `tests/test_stock.py:12: AssertionError`. The verdict took the `not new` branch first. Attempts 2 and 3 got only
  this ([red-2 prompt](artifacts/job-5810/l4-out/agent/r-20261006T1849Z-1671/1.1-red-2.prompt.md), line 72):
  ```
  # Your previous attempt was rejected
  The harness rejected it for the reason below; do not repeat it.
  <l4:data source="previous attempt">
  tests not collected individually
  </l4:data>
  ```
  The ledger has `task.attempt_failed{attempt: 1, reason: "tests not collected individually", excerpt_lines: 0}` and
  the same for attempt 2. That is wave A's shape: a bare reason, and the agent repeated the step.
* **The resume (job 5830).** First the sweep:
  ```
  [l4] openspec:change-low-stock-rule phase halted → implementing (resumed)
  [l4] openspec:change-low-stock-rule commit 949e32151f chore(change-low-stock-rule): resume [skip ci]
  [l4] sweeper: openspec:change-low-stock-rule: resumed by a member's l4:resume label (event 1532)
  ```
  The ledger records `unit.resumed{reason: "label l4:resume", by: member, signal: "label:1532"}`. The commit carries
  `L4-Unit`, `L4-Run`, `L4-Iteration: 2` and `L4-Phase: implementing`. GitLab recorded its pipelines #3204 and #3205
  as `skipped`. The mirror removed `l4:halted` and `l4:resume` (label events 1534 and 1535, user 61, the bot). Then
  `run r-20261006T1936Z-db1f` started 1.1 at red attempt 1.
* **After the live-fix (job 5830).** Attempt 1 repeated the in-place edit. Its reason now names the test, and the
  attempt-2 prompt carries the excerpt ([red-2 prompt](artifacts/job-5830/l4-out/agent/r-20261006T1936Z-db1f/1.1-red-2.prompt.md)):
  ```
  <l4:data source="previous attempt">
  no new test: existing tests were changed and now fail: tests.test_stock::test_a_quantity_at_the_threshold_is_not_low. A red test is a new test with a new name; a test that passed at the base must still pass

  tests.test_stock::test_a_quantity_at_the_threshold_is_not_low:
    >       assert is_low(LOW_STOCK_THRESHOLD)
    E       assert False
    E        +  where False = is_low(5)
    tests/test_stock.py:12: AssertionError
  </l4:data>
  ```
  The ledger keeps the headline only (`excerpt_lines: 5`).
* **Attempt 2 did not repeat the mistake.** Its gate shows `21 tests: 20 passed, 1 failed`: the failing test is the new
  `test_a_quantity_at_the_threshold_is_low`, and the existing test passes
  ([008-test.log](artifacts/job-5830/l4-out/gates/r-20261006T1936Z-db1f/008-test.log)). It failed lint instead
  (`I001 [*] Import block is un-sorted or un-formatted --> tests/test_stock.py:1:1`). The attempt-3 prompt carries
  that lint output, bounded to 23 lines with the `help:` fix.

### The harness change: `28b8cc3` m1.11(live-fix)

`classify_red` returned `tests not collected individually` whenever red added no test id, before it looked at
regressions. That text was wrong here: every test was collected. It also carried no excerpt. Now, when no module broke
and an existing test that passed at the base fails, the reason is `no new test: existing tests were changed and now
fail: <ids>. A red test is a new test with a new name; a test that passed at the base must still pass`, and it carries
`why(regressed)`, the same excerpt as `red broke existing tests`. Without a regression the old text stays (the
existing tests pin it).

Two new tests were seen failing first, at `f4fc2ef`:
* `tests/unit/implementer/test_tdd_red.py::test_an_existing_test_changed_in_place_is_named_with_its_failure_not_called_uncollected`
  (pure);
* `::test_a_red_that_only_edits_an_existing_test_tells_the_next_attempt_why` (end to end, `run_red` on the bench: the
  excerpt holds `tests/test_pricing.py:2` and the assertion line).

After the change, `tests/unit/implementer` had 389 passed, and `ruff check` and `ruff format --check` on the two files
were clean. No template changed, so the lock did not move.

### Findings

* **F1, fixed by the live-fix** [V]: the W1 gap above. Wave A's case had a new failing test **and** a broken existing
  test, so it reached the `red broke existing tests` branch. This one had the broken test only. The excerpt work of
  M1.11 covered the first case and not this one.
* **F2, the agent, not the harness** [V]: attempt 3 of the resumed run went back to the in-place edit after a lint
  failure. The seed asked for that edit in so many words ("keep the test's name"), so a halt was the expected end. The
  person's fix (step 5) removed the contradiction, and red then passed at attempt 1.
* **F3, environment** [V]: the Mintkey wrapper got `{"code":"mintkey:auth_required"}` (HTTP 401) on `list_services`
  for about 6 minutes (19:12–19:18Z). In that time the local `mintkey-vault-adapter` container restarted (19:09Z). One
  proxy call later answered `HTTP 502`. Both cleared without any change: no key was rotated, copied or edited. This
  is W11's failure mode on `main`'s copy of the wrapper (M1.11's retrying wrapper is on `m111`).
* **F4, concurrent use of the dummy** [V]: another session pushed `free/seeds-2026-10-06`. It upgrades to `4c922c4`
  (a harness `main` docs commit, so without M1.11) and seeds `add-tip-amount`, `add-shelf-code` and `add-reorder-quantity` (pipeline #3197). Its base is `b4ab7f4`, the
  `main` from before this check. Its push ran only `test` (the `l4` job does not run on that branch), so it did not
  touch these units. But a `web`/`api` pipeline on that branch would run `main`'s harness and units: the before_script
  checks out the default branch.
* **F5, cosmetic** [V]: the `summary:` line of job 5834 says `base 4d602c90d7`, the resume commit. Its diff link
  therefore leaves out the person's commit `eb66e39`, which `verification.md` lists correctly.
* **F6, environment, as in M1.10 F2** [V]: `laya-serve` stopped with `exit code -15` and was restarted within the
  rounds. Step 8 was `ok … judged by laya-local` both times.
* **F7, cosmetic** [V]: the two units of job 5810 share one run folder, `agent/r-20261006T1849Z-1671/`. So
  `change-low-stock-rule`'s first red prompt is `1.1-red-1-r2.prompt.md`, while its attempts 2 and 3 are
  `1.1-red-2`/`1.1-red-3` (`add-restock-label` needed only attempt 1).
* **Seen in passing:**
  * W8 [V]: both judge prompts have the rubric line "Files and tests listed under 'Written by the harness this round'
    are not in the diff …". There is no block, because `audit_sample_ratio: 0` writes no audit test.
  * W9, the MR text [V]: the bodies of MRs !33 and !34 read `Any merge method works: the harness detects the merge
    from the merge request and the tree. A merge commit keeps the commits' L4 trailers in the history; a squash drops
    them.`
* **Not exercised** [U]:
  * W9's label half: no question was raised, so `l4:needs-answers` never appeared;
  * W3: no 529;
  * W5: no coverage hold was rejected;
  * W6: the person's test carries no criterion id, so it is not a candidate, and the "pre-existing tests" row only
    lists it;
  * W7: no audit;
  * a refusal: no non-member or Reporter account exists. The refusal rests on the line 7 and 8 tests;
  * the dedupe of a label event that is still on the MR: the mirror removes the label at once, so a later pipeline
    has nothing to act on (job 5832);
  * `l4 resume` without bwrap: the runner has bwrap;
  * sample-consumer MF-7 and W11's ten-GET step: not in this brief.

**Spend** [V, traces]:
* Codex: 10 agent steps (restock red and green; 3 + 3 reds while halting; red and green after the fix), at 4 % of its
  weekly window;
* Claude: 2 judge calls, $0.1303 ($0.0549 + $0.0754);
* Laya (local) and Jev: S1 and shadow in both verification rounds.

**Left behind:**
* dummy-agentic `main` at `2ca856e` (pin `28b8cc3`, the include with `13`), with the two seeds;
* MR !33 `add-restock-label` and MR !34 `change-low-stock-rule`, both ready (`l4:in_review`, H green), not merged, for
  the maintainer;
* MR !29 and the other in-review MRs as before; schedule id 1 unchanged.
* Harness:
  * `m111` is `f4fc2ef` plus the live-fix `28b8cc3`;
  * `main` is this evidence commit on top of `1d5b1cb`. Other sessions added three docs commits to `main` during
    the check (`3e09e07`, `4c922c4`, `1d5b1cb`, wave B and the runner inventory); `main` has no M1.11 code;
  * nothing was pushed, and `.serena/project.yml` was left as it was found.

## 2026-10-07 — magnitude (Mac Qwen3.6-35B-A3B) as the only implementer (harness `84ff7cb`, custom provider `15e26a0`)

Setup: dummy-agentic `main` `75ce93a` (profile `magnitude-qwen`, `availability.probe_timeout: 150s`, seed `add-pallet-count`,
implementer chain `[magnitude-qwen]`). Pipeline 3314, `l4` job 5895. Evidence in [magnitude/](magnitude/).

| Run | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 | #3314 / 5895 | **exit 13 (halted), 127.7 s.** Probe `ok … hello 30.7s`, provider reachable. Red attempts 1 to 3 each ended after 28 to 30 s with `result missing: opencode wrote no result file`: Qwen wrote `agent-tmp/result.json` under `worktrees/` instead of the prompt's `units/` path, 3 of 3 times. No green, no verdict, $0, no provider error (no grammar 400, no 429) | [job log](magnitude/push-75ce93a-l4-job-5895.txt), [transcripts and prompts](magnitude/agent/), [outcome](magnitude/outcome.json), [config diffs](magnitude/config-diffs.txt) |

Afterwards `7935477` restored the implementer chain to `[f-muse, f-mimo, f-nemotron-ultra, f-longcat, codex, claude-code]`
(magnitude-qwen removed; it stays a judge fallback). The push carried `[skip ci]`, so no job ran; `l4 doctor` CFG-002 and
CFG-005 pass locally. Details: [free-resources.md section 11](../free-resources.md). The `l4` job log, the prompts and the
transcripts were scanned for token shapes (glpat, glcbt, sk-, mk_agent_, apikey_, JWT, bearer, `mag-`): none. ANSI
sequences were stripped from the job log.

## 2026-10-07 — M1.13: magnitude (Mac Qwen3.6-35B-A3B) as implementer with the `.l4-result` alias (harness `481057a`)

Setup: dummy-agentic upgraded to `481057a` (`bcca2bb`), implementer `[magnitude-qwen]` only (`e37e125`), halted unit
`add-pallet-count` (MR !36) resumed with the `l4:resume` label. Evidence in [m113/](m113/).

| Run | Pipeline / job | Result | Evidence |
|---|---|---|---|
| 1 | #3413 / 5963 | **exit 11 (awaiting_human), 824.4 s.** Resumed by a member's `l4:resume` label (event 1678). Probe `ok … hello 74.9s`. Red attempts 1 and 2 failed with `result invalid: status: not one of the allowed values` (Qwen wrote `"status": "red"`), attempt 3 ok (118.0 s); green attempt 1 ok (77.3 s). The result was read from the alias every time: no `result missing`. Gates green. Claude judged 2/2 criteria pass, **NEEDS_HUMAN** on 1 major and 2 minor spec gaps (Q-001, MR !36 `l4:awaiting_human`). $0.0945, all Claude | [job log](m113/a-resume-magnitude-implementer-job-5963.txt), [artefacts, transcripts and prompts](m113/a-job-5963-l4-out/), [verification](m113/a-add-pallet-count-verification-round1.md), [questions](m113/a-add-pallet-count-questions.md), [config diff](m113/config-diffs.txt) |

Afterwards dummy `b4f65dc` (`[skip ci]`) restored the free-first implementer chain and put `magnitude-qwen` after
`f-longcat`. sample-consumer (private) was upgraded to `481057a` with magnitude-qwen after codex (`fde6425`), pipeline
3429: `l4` job 5969 `nothing to do`, doctor green; its log is kept local. Details: [free-resources.md section
11.2](../free-resources.md). Token scan (glpat, glcbt, glptt, apikey_, sk-, mk_agent_, JWT, the Jev key, `mag-`): none.
ANSI sequences stripped from the job log.


## 2026-10-08 — Kiro end-to-end SDD, venue H1 (this Mac, local forge; harness `999d991`, live-fixes `3221a94`, `1138eae`)

kiro-cli 2.28.0 authored the `add-bulk-discount` spec headless (v3 spec mode, `--trust-all-tools`) and was the only
implementer through the vendored `l4` CLI on a local clone of dummy-agentic (no GitLab write). Intake, the dry run, the
fallback (G1) and the halt and resume (G2) pass; the implementation halted three times on task 2.1's red step, so
verification, hand-off and the done-gate were not reached. Three harness gaps: two fixed live (K3: an implementer step
runs a harness agent from a private `KIRO_HOME`; red@7: constants are green work), the third open (the red-scope
rebuild of a new module joins its import sections, so the lint gate rejects a lint-clean red step). Full write-up,
per-attempt table and findings:
[kiro-e2e/README.md](kiro-e2e/README.md), evidence in [kiro-e2e/h1/](kiro-e2e/h1/). Token scan (glpat, glcbt, glptt,
apikey_, sk-, mk_agent_, JWT, bearer): none; ANSI sequences stripped; e-mail shapes other than the commit identity
redacted.


## 2026-10-08 — Kiro end-to-end SDD, venue H2 (dummy-agentic live through CI; harness `0e4bcc8`, live-fixes `bf7b63a`, `0e4bcc8`)

**Our SDD approach with Kiro works end to end: yes, with caveats.**

* kiro-cli 2.28.0 authored `add-bulk-discount-h2` headless (2 required leaves, 1 optional).
* Pipeline 3639, `l4` job 6146: kiro-cli (glm-5) was the only implementer, under bubblewrap.
  * The fallback was live: `kiro-badmodel skipped — hello: kiro-cli reported runError (prompt)`, then `kiro ok …
    → selected, fallback #1`.
  * Red and green ran in Kiro's wave order (2.1, then 1.1). One green was retried after a FREE-tier throttle.
  * `verdict PASS (round 1, 6/6 criteria pass, 1 finding(s))`, from magnitude-qwen: Claude is not logged in for
    `gitlab-runner`.
  * MR !37 went ready and `l4:in_review`; `run finished: exit 0 in 856.3s`.
* A human merge (`b85a231`) was swept to `merged` in job 6155, with nothing left to do.
* The runner's kiro-cli went from 2.27.1 to 2.28.0 through `prereqs.sh` (test-first fix `4c9d5bf`: update instead of
  reinstall). That run used 5.42 of the 50 FREE credits.
* Open: the sweep does not run the Kiro done-gate (its merge detector looks only under `openspec/changes`; the
  done-gate passes by hand). Throttling counts as a failed attempt. Claude's runner login is gone.

Write-up: [kiro-e2e/README.md](kiro-e2e/README.md) (section H2), evidence in [kiro-e2e/h2/](kiro-e2e/h2/), artefacts
[artifacts/job-6146/l4-out/](artifacts/job-6146/l4-out/), runner records `runner/prereqs-2026-10-08-kiro-h2-*.txt`.
Token scan (glpat, glcbt, apikey_, sk-, sk-ant-, mk_agent_, JWT, `aoa…`): none. ANSI sequences were stripped, the
runner's `token=` upload fragments redacted, and e-mail shapes other than the commit identity redacted.


## 2026-10-20 — kiro-cli judge in CI (the owner's dummy repository on GitHub; harness snapshot `26332393` = kiro-judge `0a04fef4` on 0.4.18)

**A kiro-cli judge gives verdicts in CI: yes, in both legs; independence holds against a Claude implementer.**

* kiro-cli 2.32.0 on GitHub-hosted ubuntu-24.04, `auth: api_key` on `KIRO_API_KEY` (no `whoami`), an opencode-go
  DeepSeek implementer (`vendor: deepseek`).
* auto (`kiro-auto`, no model), job 118448154776: `auto: anthropic, minimax, zhipu (listed)`, verdict PASS 3/3,
  `verify.judge.credits` 0.206702, line `routed (unverified): kiro-auto routed: anthropic, minimax, zhipu (auto)`.
* pinned (`kiro-sonnet`, `claude-sonnet-5.5`), job 118452164860: PASS 3/3, 0.390773 credits, line `kiro-sonnet
  anthropic (declared)`; a first judge on an id the account does not have was skipped on a `runError (prompt)`.
* negative (claude-code implementer), jobs 118454505419 and 118455637542: both kiro judges vetoed at `constraint`
  (`share the vendor`), `waiting_capacity` (`no independent verifier`), no `verify.judge` event.
* Both streams have the reply shape of design D3, with no `tool_call`, no fallback notice and no model named. The raw
  model listing (job 118446825773) has no status field, and its Active set equals the built-in set.
* Open: the Kiro quota step needs more than the 20 s default probe step timeout (LIVE-001 failed in job
  118447200897; 120 s was set).

Write-up and design §2.3 answers: [kiro-judge/README.md](kiro-judge/README.md), with the redacted streams, the ledger
extracts and the job log extracts. Account-data scan (e-mail shapes, `arn:aws`, `profile_arn`, `accountId`) of every
job log: no hit. The public artifacts were deleted after the scan, and their only hits were `@pytest.mark` decorators.

## Copilot CLI 1.0.102: evidence without a token (2026-10-22)

Archive digests recomputed, the command that extracts the package, the read-only and per-run-link cache layouts, the macOS cache location and the no-credential texts: [copilot-cli/README.md](copilot-cli/README.md), with the texts in `tests/fixtures/recorded/copilot-cli/1.0.102-notoken/`.
