# Free OpenCode models in real L4 roles, 2026-10-06 (harness `4c922c4`, runner `l4-runner`)

This page measures the OpenCode Zen free models from the free inventory
([../../runner/free-inventory-2026-10-06.txt](../../runner/free-inventory-2026-10-06.txt)) in two real L4 roles: as
the only implementer (red and green, the gates, then Claude Code as judge), and as the only judge of two units whose
Claude verdicts are already known. Labels: [V] seen in a log, file or ledger; [I] inferred; [U] not checked.

## Verdict

* **Implementer.** 6 of the 8 models that answered the hello took a unit from red to green on the first attempt.
  Claude Code passed all 6 (PASS, 2/2 criteria, only minor findings): Space Bunny, Big Pickle, MiMo, Nemotron 3 Ultra,
  LongCat and Muse Spark. Nemotron 3.5 Lightning halted after 3 red attempts (two broke the result schema, one had
  untraced tests; 27 min). Ling 3.1 Flash got an HTTP 429 in its first red step [V].
* **Judge.** All 6 of the same 6 models agree with Claude on both known units:
  * `add-pickup-notice`: PASS with 0 findings, as Claude gave.
  * `add-shipping-fee` (the implementation ignores the subtotal): NEEDS_HUMAN, naming both missing behaviours that
    Claude raised as majors, each at major or blocker.

  Nemotron 3.5 Lightning returned schema-invalid output twice on each unit, so the harness discarded its replies and
  held the unit. Every judge got a byte-identical prompt per unit (same `prompt_sha256` as Claude's) [V].
* **No other free CLI needs no new login.** Gemini, Qwen, Cursor, Copilot and Kiro all need a login (see the
  inventory), and Jev free cannot be wired in without a harness change. Fledge Alpha (geo-blocked 403) and Ling 3.0
  Flash Fin (400 "Endpoint is unavailable") failed the hello and were not retried. Ling Fin shares the upstream that
  gave the 429 [I].
* **Free calls cost $0.** Claude cost $0.5614 for 8 judge calls [V, traces].

## Deviation from the plan: local forge on the runner, not dummy CI

At 18:47–18:54Z the M1.11 live check was active on dummy-agentic (118): jobs 5807 and 5810, MR !34 `l4:halted`, and
the pin `f4fc2ef`. A seed or config push to `main` would have made that session's `l4` job implement these units with
Codex (first in `main`'s implementer chain), and its runs would have used any implementer chain pushed to `main`.
Instead:
* The seeds sit on the **non-actionable** branch `free/seeds-2026-10-06` of 118 (`54e8e5b`, parent `b4ab7f4`, which is
  `main` before M1.11).
  * The branch also upgrades the vendored harness to `4c922c4` (3 vendored files and the pin).
  * Its push pipeline #3197 ran only `test` (job 5819, 20 passed, ruff clean) and no `l4` job
    ([seeds/seed-branch-test-job-5819.txt](seeds/seed-branch-test-job-5819.txt)).
* Every run ran on the runner as `gitlab-runner`, outside CI. The setup per run:
  * a fresh clone of a local bare mirror (made from a git bundle of that branch);
  * the scratch config [tools/cfg.tmpl.yaml](tools/cfg.tmpl.yaml) with `forge.type: local` and `ci.platform: local`,
    passed with `--config`;
  * `L4_CACHE` set to a private cache.

  The roles' code paths are the CI ones: the adapter, bubblewrap, the gates (setup, baseline, lint, test, e2e), the
  ladder, independence and the ledger. Only the forge is the in-memory `LocalForge`, so no MR is opened on GitLab.
* `main` of 118, its config and its schedule were not touched, so there is nothing to put back. After all runs, `git
  ls-remote` on 118 matched the pre-run refs [V]:
  * `l4/openspec/add-pickup-notice` `939d100` and its lock ref `5a006b4`;
  * `l4/openspec/add-shipping-fee` `390aa7e` and its lock ref `ac1fcc3`;
  * no branch for `add-shelf-code`, `add-tip-amount` or `add-reorder-quantity`.

  `main` itself moved during the runs, by the M1.11 session's pushes, not by these runs.
  * The branch `free/seeds-2026-10-06` stays as the record and can be deleted.
  * The CI build directory was not touched.
* The driver started each run only when the runner had no CI job, then logged any CI job that started during the run
  (`ci-overlap.txt`). CI overlapped 3 implementer runs:
  * Space Bunny for 1 min;
  * Ling during its 429;
  * Nemotron Lightning at two moments.

  Their wall times include that contention [V].

Scratch config differences from the dummy's `.l4/config.yaml`:
* System One off (`s1_judge: []`, `verifier.s1.enabled: false`, no shadow);
* `verifier.max_fix_rounds: 0`, so a non-PASS stays a verdict and spawns no free-model fix unit;
* `clarifier.s1_standin: none`;
* the role chains per run (below).

Vendors of the free models are operator-declared, so independence reads `declared (unverified)`:
* stealth models: `undisclosed-big-pickle`, `undisclosed-space-bunny`;
* inferred from the names: `meituan`, `xiaomi`, `inclusionai`;
* from the docs: `meta`, `nvidia`.

The dummy is a toy pricing library with no private code. The Muse Spark (training) and Nemotron (logged) terms
therefore do not block it here.

## Implementer: one unit per model, Claude Code as judge

Three seeds ([seeds/](seeds/)), each a single task with two scenarios and distinct WHENs:
* `add-shelf-code`: `inventory.shelf.shelf_code(3, 7) == "A03-S07"`, and `ValueError` for aisle 0;
* `add-tip-amount`: `pricing.tips.tip_cents(1000, 15) == 150`, and a half cent rounds up, `tip_cents(1005, 10) == 101`;
* `add-reorder-quantity`: `reorder_quantity(4, 10) == 6`, `reorder_quantity(12, 10) == 0`.

Chains: `implementer: [<free model>]`, `judges: [claude-code]`, `clarifier: [claude-code]`,
`verifier_agent: [claude-code]`.

| Model (profile) | Unit | Result | Red attempts | Green attempts | Halt | Wall | Agent steps (s) | Agent tokens in/out | Claude verdict | Findings | Claude judge cost | Run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Space Bunny (`f-space-bunny`) | shelf-code | **PASS** | 1 ok | 1 ok | – | 107 s | 22.5 / 25.1 | 22,203 / 2,456 | PASS 2/2 | 3 minor | $0.0733 | [r-20261006T1933Z-124c](runs/impl-space-bunny-shelf/) |
| Ling 3.1 Flash (`f-ling`) | shelf-code | **429** | 1, `rate_limited` | – | `waiting_capacity` (exit 12) | 272 s | 246.8 | 32,862 / 1,260 | – | – | – | [r-20261006T1935Z-1f7a](runs/impl-ling-shelf/) |
| Nemotron 3.5 Lightning (`f-nemotron-lightning`) | shelf-code | **halted** | 3 failed | – | `max_task_attempts` (exit 13) | 1,625 s | 153.0 / 499.3 / 935.9 | 231,892 / 8,569 | – | – | – | [r-20261006T1943Z-0b38](runs/impl-nemotron-lightning-shelf/) |
| Big Pickle (`f-big-pickle`) | tip-amount | **PASS** | 1 ok | 1 ok | – | 143 s | 29.8 / 58.9 | 31,642 / 1,868 | PASS 2/2 | 2 minor | $0.0741 | [r-20261006T2010Z-de51](runs/impl-big-pickle-tip/) |
| MiMo V2.6 Flash (`f-mimo`) | tip-amount | **PASS** | 1 ok | 1 ok | – | 127 s | 38.8 / 45.7 | 20,241 / 1,582 | PASS 2/2 | 2 minor | $0.0667 | [r-20261006T2015Z-faa5](runs/impl-mimo-tip/) |
| Nemotron 3 Ultra (`f-nemotron-ultra`) | tip-amount | **PASS** | 1 ok | 1 ok | – | 246 s | 125.0 / 79.3 | 186,912 / 1,806 | PASS 2/2 | 1 minor | $0.0608 | [r-20261006T2017Z-09fe](runs/impl-nemotron-ultra-tip/) |
| LongCat 2.5 Preview (`f-longcat`) | reorder-quantity | **PASS** | 1 ok | 1 ok | – | 227 s | 133.6 / 43.4 | 44,110 / 2,550 | PASS 2/2 | 3 minor | $0.0715 | [r-20261006T2021Z-f04e](runs/impl-longcat-reorder/) |
| Muse Spark 1.3 (`f-muse`) | reorder-quantity | **PASS** | 1 ok | 1 ok | – | 107 s | 34.6 / 24.6 | 36,508 / 2,660 | PASS 2/2 | 3 minor | $0.0746 | [r-20261006T2025Z-d345](runs/impl-muse-reorder/) |

Details [V]:
* **Six PASS runs.**
  * All 6 handed off locally (`in_review`). Each `src-tests.diff` holds the stub-free implementation and two tests
    tagged `@pytest.mark.l4("C-…")`.
  * All three tip implementations round half up correctly for positive inputs: Big Pickle with `Decimal`
    `ROUND_HALF_UP`, MiMo and Nemotron Ultra with integer `(x + 50) // 100` forms. Claude's minors on them are spec
    gaps (negative or very large inputs).
  * Space Bunny's minors include "the implementer's note contradicts the committed code": its green note described
    the red state.
* **Ling 3.1 Flash, the 429.**
  * The red step ran 7 model steps and 16 tool calls (2 writes). Then Zen answered `statusCode: 429`, `isRetryable:
    true`, body `Error from provider (Console): Upstream request failed: Endpoint is unavailable.`, URL
    `https://opencode.ai/zen/v1/chat/completions`.
  * The harness classified it `rate_limit` and cooled `f-ling` until 20:09Z. The unit went to `waiting_capacity`
    (exit 12).
  * I read the brief's "stop on a 429" per model: Ling got **no further call**, and both of its judge runs were
    skipped. A 429 on a second model would have stopped the whole queue. Read strictly, the experiment would have
    ended after 2 of 24 runs. The body
    names an unavailable upstream, the same text Ling 3.0 Fin returned with a 400 in the inventory. It is not a Zen
    quota message, and no other model hit a 429 [V].
* **Nemotron 3.5 Lightning halted.**
  * Attempt 1: `result invalid: summary: required`. The result file had no `summary` and `status: "failed"` for a red
    step that had in fact succeeded.
  * Attempt 2: `no new test traces C-7dc9fae5, C-fa2e5d61`. The tests lacked the `@pytest.mark.l4` tags.
  * Attempt 3: `summary: required` again, after 936 s.
  * During attempt 3 it ran ruff in a way that wrote `.l4/vendor/.ruff_cache`. The guard removed 9 files.
  * 232k tokens in, and the slowest by far: its hello alone took 42 s in the judge runs.

## Judge: two known units, the free model as the only judge

Scratch re-verification: in each run's mirror, the unit branch was set to the codex green commit, before Claude's
round 1, with no lock ref, and `l4 run --unit` was left to verify it. The unit branches:
* `add-pickup-notice` at `e339928` (M1.10, MR !31; Claude round 1: **PASS 1/1, 0 findings**,
  [baseline](baseline/add-pickup-notice-round1-claude-at-b467820.md));
* `add-shipping-fee` at `231f341` (M1.3, MR !15; Claude round 1: **NEEDS_HUMAN**, majors "free shipping at
  subtotal >= 50.00 not implemented" and "negative subtotal does not raise ValueError", plus 1 minor,
  [baseline](baseline/add-shipping-fee-round1-claude-at-6d4fee0.md)).

Each run first merged `main@54e8e5b` into the branch at step 0, with no conflict: 7 commits for pickup, 47 for
shipping fee. Then it ran the gates. All passed,
including e2e 2/2. Chains: `judges: [<model>]`, `verifier_agent: [<model>]`, `clarifier: []` (disabled),
`generate_missing_tests: false`. The verifier agent is named only because Playwright on needs one (finding H4). No UI
path changed, so it was never called. Claude was re-run in the same setup as the baseline. MR !29's wrong fix was not
used:
* its FAIL rested on the 92-character CI step, which `main` no longer has;
* a ledger from before M1.10 has no `ci.step`.

The known non-PASS used instead is add-shipping-fee round 1. There the judge, not a gate, caught requirement text that
the tests do not cover.

| Judge | pickup verdict (Claude: PASS, 0) | shipping-fee verdict (Claude: NEEDS_HUMAN) | Both known defects found | Severity given | Agrees with Claude | Run wall, gates included (pickup / shipfee) | Judge calls, tokens in/out | Failure |
|---|---|---|---|---|---|---|---|---|
| Claude Code, rerun (`claude-code`) | PASS, 0 | NEEDS_HUMAN, 2 major + 1 minor | 2/2 | major, major | baseline (same as history) | 33 s / 36 s | 1+1, $0.0481 + $0.0923 | – |
| Space Bunny | PASS, 0 | NEEDS_HUMAN, 2 major + 3 minor | 2/2 | major, major | **yes / yes** | 31 s / 34 s | 1+1, 6.5k/0.7k, 7.0k/1.9k | – |
| Big Pickle | PASS, 0 | NEEDS_HUMAN, 1 major + 1 minor | 2/2 in one finding | major | **yes / yes** | 35 s / 53 s | 1+1, 6.3k/0.4k, 6.9k/1.1k | – |
| MiMo V2.6 Flash | PASS, 0 | NEEDS_HUMAN, 1 blocker + 1 major | 2/2 | blocker, major (both tagged "spec gap") | **yes / yes** | 34 s / 45 s | 1+1, 6.3k/0.5k, 6.9k/1.2k | – |
| Nemotron 3 Ultra | PASS, 0 | NEEDS_HUMAN, 2 major | 2/2 | major, major (both tagged "spec gap") | **yes / yes** | 50 s / 211 s | 1+1, 6.7k/0.4k, 7.4k/1.2k | – |
| LongCat 2.5 Preview | PASS, 0 | NEEDS_HUMAN, 2 major | 2/2 | major, major (both tagged "spec gap") | **yes / yes** | 45 s / 90 s | 1+1, 6.3k/0.4k, 6.9k/1.2k | – |
| Muse Spark 1.3 | PASS, 0 | NEEDS_HUMAN, 2 major + 1 minor | 2/2 | major, major | **yes / yes** | 29 s / 74 s | 1+1, 6.5k/0.3k, 7.1k/1.0k | – |
| Nemotron 3.5 Lightning | **schema_invalid** → hold, NEEDS_HUMAN 0/1 | **schema_invalid** → hold, NEEDS_HUMAN 0/2 | (discarded) | – | **no verdict** | 240 s / 390 s | 2+2 (repair retry), 13.4k/0.7k, 14.8k/1.7k | `structured output missing` (broken JSON on the retry); `criteria[*].counterexample: expected object` |
| Ling 3.1 Flash | not run | not run | – | – | – | – | 0 | blocked after its 429 |

Notes [V]:
* **Identical prompts.** The judge prompt `sha256` is `342c7502…` for every pickup run and `870c68e6…` for every
  shipping-fee run, Claude's included.
* **The same finding id is not a leak.** Three free judges produced `F-a0fac71a` ("Negative subtotal does not raise
  ValueError"), the id of Claude's M1.3 finding. The id is a hash of the title and the criterion
  (`verifier/types.py:finding_id`), and the prompt holds no earlier finding: its only mention of the behaviour is the
  requirement text.
* **Nemotron 3.5 Lightning's discarded replies.**
  * Shipping fee: the first reply passed both criteria with no finding. The repair reply listed both defects, as
    **minor** only.
  * Pickup: the first reply parsed as JSON and passed the criterion, but failed the harness's schema check; the ledger
    records only the final reason. The repair reply was malformed JSON.
  * Even schema-valid, it would have under-graded the known defects [V, raw events].
* **"Spec gap" tags.** MiMo, Nemotron Ultra and LongCat tagged the two requirement-text defects "(spec gap)"; Claude,
  Space Bunny, Big Pickle and Muse did not. Whether the tag changes routing (fix task vs question) was not checked
  [U].

## Failures by kind

| Kind | Where | Count |
|---|---|---|
| HTTP 429 | Ling 3.1 Flash, implementer red (`Upstream request failed: Endpoint is unavailable`) | 1 |
| Result or verdict schema | Nemotron 3.5 Lightning: implementer `summary: required` ×2, judge `schema_invalid` ×2 runs (4 calls) | 4 steps |
| Traceability (no `@pytest.mark.l4`) | Nemotron 3.5 Lightning, red attempt 2 | 1 |
| Timeout | none (longest step 936 s, under the harness's agent timeout; no `timeout` status) | 0 |
| `permission_blocked` (judge `read`/`bash: ask`) | none: no free judge reached for a tool | 0 |
| Geo-block / unavailable (inventory, not re-tried) | Fledge Alpha 403, Ling 3.0 Flash Fin 400 | – |

## Harness findings (none fixed)

* **H1** [V] A checkout under `/tmp` breaks the gate sandbox. Bubblewrap mounts a tmpfs on `/tmp`, so the vendored
  pytest plugin `l4_trace` is invisible (`ModuleNotFoundError: No module named 'l4_trace'`). The gate then reports
  `baseline fail — report missing: .l4-out/junit.xml`, which hides the cause. CI is not affected: builds live under
  `$HOME`. The first smoke run hit this and was redone under `/home/gitlab-runner/l4-free-20261006`.
* **H2** [V] The runner cache keys worktrees by unit name across repositories
  (`~/.cache/l4/worktrees/openspec/<unit>`).
  * A second checkout of the same project is refused with `… is a checkout of another repository; refusing to delete
    it (two projects share a change name on this runner)`. Two projects with the same change name are refused too.
  * A private `L4_CACHE` per checkout works around it. Chromium had to be copied into it (658 MB), because
    `shared/ms-playwright` lives under the cache root.
  * The stale `add-shelf-code` worktree that the `/tmp` smoke left in the runner's default cache was removed.
* **H3** [V] A 429 whose body reads "Endpoint is unavailable" is an upstream outage, not a quota. The harness treats
  it as `rate_limit` (30-min cooldown, `waiting_capacity`), which is right by status. The text suggests the
  inclusionAI upstream is down, not a Zen per-user limit [I].
* **H4** [V] `gates.e2e` plus Playwright on requires a non-empty `roles.verifier_agent`
  (`cli: gates.e2e.command is set and Playwright is on: roles.verifier_agent is empty`), even when nothing under
  `ui_paths` changed. On the first pass all 16 judge runs exited 2 in 1 s on this. All were re-run with the judge also named as verifier agent.
* **H5** [V] A verify-only `l4 run`, on a unit whose tasks are all done, still selects the implementer role. Codex
  got 2 hellos; the other 14 selections were cached.
* **H6** [V] Through OpenCode `run` mode the served model is `model unknown`, so free-model independence is
  `declared (unverified)` on every run. For the two stealth models the declared vendor is a placeholder.

## Calls made

* **OpenCode Zen free models:**
  * 22 runs reached a model:
    * 8 implementer runs, 16 agent steps: 2 per PASS run, 1 Ling, 3 Nemotron Lightning;
    * 14 judge runs, 16 judge calls.
  * Availability hellos: 16 sent (15 in these runs plus 1 in the aborted `/tmp` smoke), and 7 more answered from
    the 15-min probe cache.
  * One 429 (Ling). After it, Ling got no further call.
* **Claude Code:** 8 judge calls (the 6 implementer runs that reached verification, plus 2 baselines), $0.5614.
  Availability hellos: 3 sent, 5 cached. No clarifier or verifier-agent call.
* **Codex:** 2 availability hellos and quota reads in the judge runs (H5), no agent step; weekly window at 4 %.
* **GitLab:**
  * 1 branch push (`free/seeds-2026-10-06`), which ran test job 5819;
  * API reads only: jobs, pipelines and files, via `scripts/dev/mk-gitlab-api.sh`.
* **No install, no login, no credential file touched.** The runner work directory `/home/gitlab-runner/l4-free-20261006`
  was removed after the fetch (see the end of this page).

## Files

* [runs/](runs/), one folder per run:
  * `meta.txt`, `run.log` (ANSI stripped), `status.txt`, `cfg.yaml`, `ci-overlap.txt`, `ratelimit.txt`;
  * `branch-commits.txt` and `src-tests.diff`;
  * `unit/`, the unit folder at the branch head: `verification.md`, the ledger and the evidence.
* `../artifacts/free-<run label>/l4-out/`: the run's `.l4-out`, with the agent prompts and raw event streams, the
  gate logs, the log mirror and `outcome.json`. These runs have no CI job id, so the folder is keyed by the run label;
  the run id is in each row above.
* [baseline/](baseline/): Claude's historical round-1 reports for the two judge units.
* [seeds/](seeds/): the three seeds and the seed branch's test job.
* [tools/](tools/): the driver, queue, config template, setup, fetch, summary, copy and scanning scripts.
  `driver.sh` is the final version. It changed twice during the session:
  * a private `L4_CACHE` after the `/tmp` smoke (H1, H2);
  * the per-model block after the 429; before that, a 429 stopped the whole queue.
* **Gap:** the runner work directory, with the driver's own `driver.log`, was deleted after the fetch and that log
  was not saved. Its "waiting: a CI job runs" and "skip judge-ling-*: model blocked after a 429" lines exist only in
  the session console. The timeline is in each run's `meta.txt` START/END stamps. The Ling skip shows as the missing
  `runs/judge-ling-*` folders.

**Token scan** of the 813 saved files (`free/` and the 24 `artifacts/free-*` folders) with
[tools/tokscan.py](tools/tokscan.py): no `glpat-`, `glcbt-`, `glptt-`, `apikey_`, `sk-`, `mk_agent_`, bearer or JWT shape
(0 hits). The scanner was checked first on a planted `glpat-`/`sk-` file (1 file, both patterns found). The runs had no
`TYPESAFE_API_KEY` or `L4_FORGE_TOKEN` in their environment (System One off, local forge), so no Jev or forge key
could reach these files. The copied `.l4-out/.gitignore` files were left out.
