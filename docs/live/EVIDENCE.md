# Where to see the evidence (plain language)

## What one run is, in five sentences

1. A push to `example-group/dummy-agentic` starts a GitLab pipeline; its job `l4` (older runs: `l4-run`) runs on
   **l4-runner** and calls the vendored harness `.l4/bin/l4`.
2. `l4 plan` looks at the OpenSpec changes and decides which unit has work; `l4 run` then works on it.
3. For each task the harness asks **Codex** (in a bubblewrap sandbox) to write failing tests (**red**), runs the
   tests itself, commits; then asks Codex to implement (**green**), runs the tests again, commits.
4. The harness then **verifies**: it runs the gates (lint, tests) itself and asks an independent judge (**Claude**)
   to check every acceptance criterion; the result is `verification.md`.
5. It pushes the branch `l4/openspec/<unit>` as the bot `l4-bot` and opens or updates a **merge request**; a human merges.

## Click here

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| `add-discount-codes`: red→green ×2 by Codex, judged PASS by Claude (M0) | [pipeline 2530](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2530) / [job 5424](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5424) | [!1 (merged)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/1) | [commits with L4-TDD trailers](https://gitlab.example.com/example-group/dummy-agentic/-/commits/main?ref_type=heads) (merged into main), [verification.md](2026-10-04-add-discount-codes-verification.md) | [job-5424/](artifacts/job-5424/l4-out/) |
| `add-vat` (M0): Codex said "VAT rates are a business decision" → questions.md | [pipeline 2543](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2543) / [job 5428](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5428) | [!2 (closed later)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/2) | [questions.md](2026-10-04-add-vat-questions.md) | [job-5428/](artifacts/job-5428/l4-out/) |
| merge of !1 → archive MR | [pipeline 2551](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2551) | [!3 archive](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/3) | [archive branch](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/archive/openspec/add-discount-codes) | log: [m11/p2-job-5434.txt](m11/p2-job-5434.txt) |
| `add-vat` resumed from a human answer, red→green ×2, judge found a real spec gap → NEEDS_HUMAN | [pipeline 2564](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2564) / [job 5439](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5439) | [!5](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5) | [branch commits](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/openspec/add-vat), [verification.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-vat/openspec/changes/add-vat/verification.md) | [job-5439/](artifacts/job-5439/l4-out/) |
| `add-average-price`: clarifier suggestion accepted by a human → red→green → PASS | [pipeline 2577](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2577) / [job 5441](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5441) | [!4 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/4) | [branch commits](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/openspec/add-average-price), [verification.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-average-price/openspec/changes/add-average-price/verification.md) | [job-5441/](artifacts/job-5441/l4-out/) |
| `add-is-empty`: question raised at intake, **clarifier answered it automatically**, red→green → PASS | [pipeline 2601](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2601) / [job 5451](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5451) | [!8 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/8) | [branch commits](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/openspec/add-is-empty), [questions.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-is-empty/openspec/changes/add-is-empty/questions.md) | [job-5451/](artifacts/job-5451/l4-out/) |

GitLab keeps job artefacts for one week, so copies of the five most important ones are in [artifacts/](artifacts/).

## What is inside a job's artefacts (`.l4-out/`) — example: job 5451

| File | What it proves |
|---|---|
| `agent/<run>/1.1-red-1.prompt.md` | the exact instructions Codex got for the red step (incl. the clarifier's answer as `<l4:data kind="answer" by="clarifier">`) |
| `agent/<run>/1.1-red-1.jsonl` | Codex's raw event stream: the commands it ran and the file it changed (`tests/test_cart.py` only) |
| `gates/<run>/005-test.log` | the harness ran the tests after red: **2 failed, 15 passed** (the new tests fail, as TDD requires) |
| `gates/<run>/010-test.log` | after green: **17 passed** |
| `agent/<run>/clarify-1.*`, `s1-*.*` | the clarifier's question/answer and the S1 checks of each citation |
| `agent/<run>/verify-judge-r1-1.jsonl` | the Claude judge's verdict for each criterion |
| `outcome.json` | the summary: `verdict: PASS`, `phase_after: in_review`, cost $0.18, MR link |

The branch itself carries the same story as commits: `test(<unit>): red for 1.1` → `feat(<unit>): 1.1 …` →
`docs(<unit>): verification round 1` → `docs(<unit>): hand off to review`, each with `L4-*` trailers
(`git log --format='%h %s%n%(trailers)'`), plus the ledger `openspec/changes/<unit>/.l4/ledger/*.jsonl` (every event).

## Why the job log looked empty

Until now `l4 run` printed almost nothing to the console: all the evidence went to artefacts, commits and the
ledger. That is being fixed: `l4 run` will print a one-line-per-step trace (agent selected, red ok, green ok,
gates, verdict, MR link) straight into the job log.

## The code changes of job 5424 (`add-discount-codes`), commit by commit

Whole change in one view: [MR !1 → Changes](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/1/diffs) or
[compare e1db758…e1a556d](https://gitlab.example.com/example-group/dummy-agentic/-/compare/e1db758cc78aaf7f2884de0a24e2230a6be893f4...e1a556dd7827d9f8c3acc4f20a7654d58c5baeec)
(base = `main` when the job started, head = the unit branch when it ended). Merged into `main` as merge commit
[ada2b422](https://gitlab.example.com/example-group/dummy-agentic/-/commit/ada2b422).

| Commit | Author | What |
|---|---|---|
| [b49deae](https://gitlab.example.com/example-group/dummy-agentic/-/commit/b49deaebcf3d76876de1e1bc88b2bb7a7ffbefea) | l4-bot | **red 1.1** — Codex's failing tests for the discount registry (`tests/test_discounts.py`) |
| [700f764](https://gitlab.example.com/example-group/dummy-agentic/-/commit/700f7649182c4ecc70d47ea351114d35f9bd9006) | l4-bot | **green 1.1** — `src/pricing/discounts.py` (PercentOff, AmountOff, DiscountRegistry, UnknownDiscountCode) |
| [c197adb](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c197adbcbf7ddb7974c80526c74669ce6c67f1a3) | l4-bot | **red 1.2** — failing tests for `Cart.apply_code` / `Cart.total` |
| [bca8385](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bca83856e61ac840c2370e49350afcbd5bfa3904) | l4-bot | **green 1.2** — `Cart.apply_code`, `Cart.total`, exports |
| [57c260d](https://gitlab.example.com/example-group/dummy-agentic/-/commit/57c260d2b0c99dbab142fce16cd0e6ea4e9a74c6) | l4-bot | verification round 1 (`verification.md`, evidence) |
| [eca914d](https://gitlab.example.com/example-group/dummy-agentic/-/commit/eca914de5f21edbd8b8620eb4077602a4958af64) | l4-bot | hand-off to review (the commit the project's CI ran on) |
| [e1a556d](https://gitlab.example.com/example-group/dummy-agentic/-/commit/e1a556dd7827d9f8c3acc4f20a7654d58c5baeec) | l4-bot | ledger (M0 only; since M1.1 this tail goes to `refs/l4/locks/…`, not the branch) |

Every commit carries trailers (`L4-Unit`, `L4-Run`, `L4-Task`, `L4-TDD: red|green`, `L4-Agent: codex/gpt-6-luna`,
`L4-Step`): open a commit and look at the end of its message.

## M1.2: when an agent is out of quota, the harness picks the next one (2026-10-04)

Plain story: the config lists, for each role, a chain of agents in order of preference. Before a role runs, the harness
checks each agent cheapest-first (is the program there, is it logged in, how much quota is left, does it answer
"hello") and takes the first that passes, printing one `[l4] <role>: <agent> …` line per decision. An agent that is out
of quota gets a cool-down (remembered on the runner until its quota window resets) and is not asked again until then.
Full step table: [README.md, M1.2 section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| P1: Codex implements `add-money-format`; the first judge (`claude-judge`) is refused, the judge falls back to **OpenCode `big-pickle`** (`fallback #1`), verdict PASS with `independence: declared (unverified)` | [pipeline 2624](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2624) / [job 5462](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5462) ([log](m12/s1c-retry-job-5462.txt)) | [!10 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/10) | [branch commits](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/openspec/add-money-format) ([trailers](m12/s1c-add-money-format-commits.txt)), [verification.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-money-format/openspec/changes/add-money-format/verification.md) | [job-5462/](artifacts/job-5462/l4-out/) |
| P1 first try: the plan's way of refusing `claude-judge` (an impossible `min_version`) stops the whole job at `l4 doctor` (exit 3) | [pipeline 2614](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2614) / [job 5458](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5458) ([log](m12/s1a-doctor-fail-job-5458.txt)) | — | — | (none: failed before artefacts) |
| P2 first try: Codex is forced "exhausted" (100 % reserve) → **skipped, cool-down recorded**; Kiro **skipped, not logged in**; OpenCode selected (`fallback #2`) but its result file was rejected 3× → exit 13 (harness bug, fixed in `0fa4ad1`) | [pipeline 2632](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2632) / [job 5465](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5465) ([log](m12/s3a-halted-job-5465.txt)) | !11 (closed by the reset) | [ledger: cool-down + skips](m12/s3a-add-split-amount-availability-events.jsonl) | [job-5465/](artifacts/job-5465/l4-out/) — `agent/*/1.1-red-1.jsonl` shows the result it wrote |
| P2 re-run: Codex still cooling (no request sent), Kiro skipped, **OpenCode `big-pickle` writes red → green**, Claude judges PASS | [pipeline 2635](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2635) / [job 5467](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5467) ([log](m12/s3b-rerun-job-5467.txt)) | [!12 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/12) | [branch commits](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/openspec/add-split-amount) with `L4-Agent: opencode-free/opencode/big-pickle` and `L4-Fallback-From: codex` ([trailers](m12/s3b-add-split-amount-commits.txt)), [verification.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-split-amount/openspec/changes/add-split-amount/verification.md) | [job-5467/](artifacts/job-5467/l4-out/) (`outcome.json`: `profiles.fallback_from: codex`) |
| P3: the only implementer (Codex) is cooling → the unit waits for capacity, **exit 12**, nothing pushed | [pipeline 2643](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2643) / [job 5470](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5470) ([log](m12/s5-exit12-job-5470.txt)) | none (by design) | none (by design) | [job-5470/](artifacts/job-5470/l4-out/) (`outcome.json`: `waiting_capacity`, `retry_after`) |
| P4: config cleaned up, `nothing to do`; then `l4 probe --no-cache codex` **clears the cool-down** | [pipeline 2644](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2644) / [job 5472](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5472) ([log](m12/s6-cleanup-job-5472.txt)) | — | — | probes: [codex re-probe](m12/s6-probe-nocache-codex.json), [final probe](m12/s6b-probe-all.json) |

The lines to look for in a job log (job 5465, then 5467):

```
[l4] implementer: codex skipped — quota: weekly window 3% used, 97% remaining < 100% (profile reserve) (resets 2026-10-10T12:52Z); cool-down recorded
[l4] implementer: kiro skipped — auth: kiro-cli installed, not authenticated
[l4] implementer: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello 6.2s · cached) → selected, fallback #2
[l4] implementer: codex skipped — cooling until 2026-10-10T12:52Z (usage_limit); no probe sent
[l4] judges: claude-code ok (binary 2.1.288 · auth subscription · quota 2% used (weekly (all models)) · hello 4.1s) → selected
```

and in `verification.md`: `- independence: declared (unverified): claude-code anthropic (served claude-opus-5-5),
opencode-free zhipu (declared)` — "declared" because OpenCode's free models do not say who serves them, so the vendor
(`zhipu`) is the operator's word, and the verdict says so.

## M1.4: a Kiro spec, a dry run that predicts the real run, and `doctor --fix` (2026-10-04)

Plain story: besides OpenSpec changes, the harness now drives **Kiro specs** (`.kiro/specs/<name>/` with
`requirements.md`, `design.md` and a `tasks.md` whose JSON "waves" can reorder tasks, and whose `[ ]*` tasks are
optional). First a **probe pipeline** on a side branch (`probe/m14`) ran the read-only tools:
* `l4 plan` (exit 10 = there is work);
* `l4 run --dry-run`, which prints what the real run would do, spends nothing and pushes nothing;
* `l4 simulate`, which runs the harness against fake agents;
* `l4 doctor --fix`, run twice into a throw-away home. The first run installed OpenSpec; the second had nothing left
  to do.

Then the same commit went to `main`, and the real `l4` job implemented the spec. Codex did the tasks in **wave order**
(2.1 before 1.1, although 1.1 comes first in the file) and **skipped the optional 1.2**. The harness ticked the parent
tasks itself and changed only the four checkbox bytes of `tasks.md`. Claude judged all four acceptance criteria PASS.
The merge request is ready for a human. Full step table: [README.md, M1.4 section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| P1 probe on `probe/m14`: plan exit 10, the dry run predicts "Kiro unit, task 2.1, red, codex", simulate passes, `doctor --fix` installs OpenSpec into a scratch home and then has nothing to do; refs unchanged, `sudo` never called | [pipeline 2645](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2645) / [job 5473](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5473) ([log](m14/s2-probe-job-5473.txt)) | none (by design) | none (by design; the branch was deleted afterwards) | [job-5473/](artifacts/job-5473/l4-out/): [summary](artifacts/job-5473/l4-out/probe/summary.txt), [dry run](artifacts/job-5473/l4-out/probe/dryrun.out), [plan](artifacts/job-5473/l4-out/probe/plan.out), [fix1](artifacts/job-5473/l4-out/probe/fix1.out), [fix2](artifacts/job-5473/l4-out/probe/fix2.out) |
| P2 on `main`: Codex implements `kiro:add-loyalty-points` in wave order (2.1 then 1.1), skips the optional 1.2, Claude judges PASS 4/4 | [pipeline 2646](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2646) / [job 5475](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5475) ([log](m14/s3-p2-job-5475.txt)) | [!13 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/13) | [branch commits](https://gitlab.example.com/example-group/dummy-agentic/-/commits/l4/kiro/add-loyalty-points) ([trailers](m14/s3-add-loyalty-points-commits.txt)), [tasks.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/kiro/add-loyalty-points/.kiro/specs/add-loyalty-points/tasks.md) ([the four changed bytes](m14/s3-add-loyalty-points-tasks-md.txt)), [verification.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/kiro/add-loyalty-points/.kiro/specs/add-loyalty-points/verification.md) | [job-5475/](artifacts/job-5475/l4-out/) ([outcome.json](artifacts/job-5475/l4-out/outcome.json), [l4.env](artifacts/job-5475/l4-out/l4.env), [JSONL log](artifacts/job-5475/l4-out/logs/r-20261004T1741Z-3ebb.jsonl)) |
| the hand-off commit's own pipeline: only the project's `test` job, no `l4` job | [pipeline 2657](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2657) / [job 5476](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5476) | [!13](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/13) | [hand-off commit 940c6ff](https://gitlab.example.com/example-group/dummy-agentic/-/commit/940c6ff5ebdcf0849eb978a8692a6c7d84a19ca1) | — |

The commits of the run, in order:

| Commit | What |
|---|---|
| [b0b384d](https://gitlab.example.com/example-group/dummy-agentic/-/commit/b0b384ddaf81a69cd4754150af7ccfaf36c6f21e) | C1 by the operator: harness pinned at `c9e2c0d`, `spec.frameworks: auto`, the Kiro seed |
| [f47cc09](https://gitlab.example.com/example-group/dummy-agentic/-/commit/f47cc09abc954a37353902e9ee291f8ac9586971) | **red 2.1**: failing tests for `points_for` (wave 0) |
| [1866c91](https://gitlab.example.com/example-group/dummy-agentic/-/commit/1866c9116077dd161293f33dd9100c0e97473d90) | **green 2.1**: `src/pricing/loyalty.py`; ticks `2.1` and its parent `2.` |
| [dc36746](https://gitlab.example.com/example-group/dummy-agentic/-/commit/dc367463ec2be4415c507aa44ad4a1674b363d1d) | **red 1.1**: failing tests for `Cart.loyalty_points()` (wave 1) |
| [3f14b18](https://gitlab.example.com/example-group/dummy-agentic/-/commit/3f14b181552079ab52ac1a2c43db9a43dfa36bbe) | **green 1.1**: `Cart.loyalty_points()`; ticks `1.1` and its parent `1.` (the optional `1.2` stays `[ ]*`) |
| [c42ec28](https://gitlab.example.com/example-group/dummy-agentic/-/commit/c42ec284fd9790cde94cd0cbad6db5a7fb69020c) | verification round 1 (`verification.md`, PASS 4/4) |
| [940c6ff](https://gitlab.example.com/example-group/dummy-agentic/-/commit/940c6ff5ebdcf0849eb978a8692a6c7d84a19ca1) | hand-off to review (no `[skip ci]`; the commit the project's CI ran on) |

Whole change: [compare b0b384d…940c6ff](https://gitlab.example.com/example-group/dummy-agentic/-/compare/b0b384ddaf81a69cd4754150af7ccfaf36c6f21e...940c6ff5ebdcf0849eb978a8692a6c7d84a19ca1).

The lines to look for, first in the probe's dry run (job 5473), then in the real run (job 5475):

```
kiro:add-loyalty-points  phase=none  next=implement  task=2.1 (red)
would exit 0
[l4] implementer: codex ok (binary 0.160.0 · auth subscription · quota 3% used (weekly window) · hello 3.8s) → selected
[l4] kiro:add-loyalty-points task 2.1 started: 2.1 Add `src/pricing/loyalty.py` with `points_for(subtotal: Decimal) -> int` …
[l4] kiro:add-loyalty-points task 1.1 started: 1.1 Add `Cart.loyalty_points()` returning `points_for` of the cart's subtotal …
[l4] kiro:add-loyalty-points verdict PASS (round 1, 4/4 criteria pass, 3 finding(s))
[l4] kiro:add-loyalty-points MR https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/13 marked ready for review
[l4] kiro:add-loyalty-points run finished: exit 0 in 192.9s, cost $0.1038
```

The read-only acceptance test (`tests/live/test_m1_4_acceptance.py`) passes 7/7 after its own fix
([`6eaee92`](README.md): it read the timestamped GitLab log wrongly) — [output](m14/g7-fixed-6eaee92.txt).

## M1.3: a verifier that asks a human, and turns the answer into a fix (2026-10-04)

Plain story: the verifier now checks that every acceptance criterion is traced to a test that really looks at the
answer: a test that fails when the code is replaced by "zero" values, or an extra **audit test** that a separate Claude
writes without seeing the implementer's tests. When the judge finds a serious problem that no test confirms, the
harness does not decide alone: it asks the human a **verdict question** in `questions.md`. The human answers
`accept` or `reject: WHEN … THEN …`. A reject becomes a small **fix unit**, a new OpenSpec change
`add-shipping-fee-fix-1` holding the human's scenario word for word. The harness implements it red → green in the same
job, verifies the whole family again, and hands the merge request to review.

The first try stopped early. Codex was asked to write failing tests for behaviour the code already had, and it asked
a question instead. Two harness bugs were fixed (`e9735ff`, `f0f6524`), the unit was reset, and the second try went all
the way. Full step table: [README.md, M1.3 section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| P1 on `main`: red → green, round 1 PASS 2/2 with an audit test, a fix unit from three minor findings, then Codex blocked on the fix task ("RED test for existing behavior") | [pipeline 2658](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2658) / [job 5478](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5478) ([log](m13/s1-p1-job-5478.txt)) | [!14 (closed by the retry rule)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/14) | [fix unit commit 7a079a4](https://gitlab.example.com/example-group/dummy-agentic/-/commit/7a079a498ef3fa2a9615732c3d980663de93f31c), [verification round 1](m13/s1-p1-verification-round-1.md), [fix unit files](m13/s1-p1-fix-unit-and-code.txt) | [job-5478/](artifacts/job-5478/l4-out/) ([Codex's blocked reply](artifacts/job-5478/l4-out/agent/r-20261004T1934Z-f30b/1.1-red-1-r2.jsonl)) |
| retry on `main` (harness `f0f6524`): red → green, round 1 NEEDS_HUMAN, two verdict questions | [pipeline 2672](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2672) / [job 5480](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5480) ([log](m13/s1-p1r-job-5480.txt)) | [!15](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/15) (then a draft waiting for answers) | [questions.md as asked](m13/s1-p1r-questions-at-46b01dc.md), [verification round 1](m13/s1-p1r-verification-round-1.md) | [job-5480/](artifacts/job-5480/l4-out/) |
| the human's answer: reject both, with a WHEN/THEN each | [pipeline 2681](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2681) / [job 5482](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5482) ([log](m13/s2-p2-job-5482.txt)) | [!15 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/15) | [answer commit 748cf82](https://gitlab.example.com/example-group/dummy-agentic/-/commit/748cf82c9ff9b71e7b14571802298521ff7ada00), [fix unit spec](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-shipping-fee/openspec/changes/add-shipping-fee-fix-1/specs/shipping/spec.md), [final verification.md](https://gitlab.example.com/example-group/dummy-agentic/-/blob/l4/openspec/add-shipping-fee/openspec/changes/add-shipping-fee/verification.md) ([copy](m13/s2-p2-verification-round-3.md)) | [job-5482/](artifacts/job-5482/l4-out/) ([outcome.json](artifacts/job-5482/l4-out/outcome.json), [l4.env](artifacts/job-5482/l4-out/l4.env)) |
| the hand-off commit's own pipeline: only the project's `test` job, no `l4` job | [pipeline 2692](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2692) / [job 5483](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5483) | [!15](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/15) | [hand-off commit 390aa7e](https://gitlab.example.com/example-group/dummy-agentic/-/commit/390aa7eacae3abc10b0b3d676b29132c5ef60254) | — |

The commits of the successful run, in order:

| Commit | What |
|---|---|
| [8ff4f03](https://gitlab.example.com/example-group/dummy-agentic/-/commit/8ff4f030617b06e39a905172d9db608ea46ee1bb) | the operator: harness upgraded to `f0f6524` (the two live-fixes), `[skip ci]` |
| [3319cb2](https://gitlab.example.com/example-group/dummy-agentic/-/commit/3319cb24a7d5ee0b7c7fc82196d83570ef21729c) | **red 1.1**: failing tests tagged `@pytest.mark.l4("C-…")`, stubs only |
| [231f341](https://gitlab.example.com/example-group/dummy-agentic/-/commit/231f3413ed0e7e66cb466075e51d5bbfcac20705) | **green 1.1**: `src/pricing/shipping.py` (only the two scenarios' behaviour) |
| [2e06216](https://gitlab.example.com/example-group/dummy-agentic/-/commit/2e06216d43e7506aa5c8bf4b5648b6b281d0f312) | the verifier's audit test for `C-1b1fbe16` (round 1) |
| [6d4fee0](https://gitlab.example.com/example-group/dummy-agentic/-/commit/6d4fee00b34282a25f24c6ab9e8a7d3ee80d3041) | verification round 1: NEEDS_HUMAN, verdict questions Q-001 and Q-002 |
| [748cf82](https://gitlab.example.com/example-group/dummy-agentic/-/commit/748cf82c9ff9b71e7b14571802298521ff7ada00) | **the human**: `reject: WHEN … 50.00 … THEN the shipping fee is 0.00`, `reject: WHEN … -1.00 … THEN a ValueError is raised` |
| [0de4ab2](https://gitlab.example.com/example-group/dummy-agentic/-/commit/0de4ab24f50ea094fca43a221e63f4d0f36a0133) | verification round 2: steps 0–9 reused (no new judge call), FAIL on the two rejected findings |
| [6adf550](https://gitlab.example.com/example-group/dummy-agentic/-/commit/6adf550ed1e3997d22625ce37cf4727488a82a02) | the fix unit `add-shipping-fee-fix-1`: both scenarios under `Shipping fee — regression 1` |
| [0051b41](https://gitlab.example.com/example-group/dummy-agentic/-/commit/0051b41a314af202d97310792598221a4dc86742) | **red** of the fix task |
| [6080880](https://gitlab.example.com/example-group/dummy-agentic/-/commit/60808804393113223dbbf2f642e8f2eaec1368ce) | **green** of the fix task: free shipping from 50.00, `ValueError` for a negative subtotal |
| [bf7fb30](https://gitlab.example.com/example-group/dummy-agentic/-/commit/bf7fb30f5a1b9ba9f66b9e9e30be4df4fec55659) | the verifier's audit test for `C-e25f06d8` (round 3) |
| [3ee494b](https://gitlab.example.com/example-group/dummy-agentic/-/commit/3ee494b0b250af46900386e43516842fea49697a) | verification round 3: PASS 4/4 |
| [390aa7e](https://gitlab.example.com/example-group/dummy-agentic/-/commit/390aa7eacae3abc10b0b3d676b29132c5ef60254) | hand-off to review (no `[skip ci]`; the commit the project's CI ran on) |

Whole change: [compare 8ff4f03…390aa7e](https://gitlab.example.com/example-group/dummy-agentic/-/compare/8ff4f030617b06e39a905172d9db608ea46ee1bb...390aa7eacae3abc10b0b3d676b29132c5ef60254).

The lines to look for (jobs 5480, then 5482):

```
[l4] openspec:add-shipping-fee verdict NEEDS_HUMAN (round 1, 2/2 criteria pass, 3 finding(s))
openspec:add-shipping-fee    awaiting_human  1/1    verify  verdicts answered: Q-001, Q-002
[l4] openspec:add-shipping-fee phase awaiting_human → verifying (verdicts_answered)
[l4] openspec:add-shipping-fee verdict FAIL (round 2, 2/2 criteria pass, 3 finding(s))
[l4] openspec:add-shipping-fee commit 6adf550ed1 docs(add-shipping-fee): fix unit 1 [skip ci]
[l4] openspec:add-shipping-fee phase verifying → fixing (verify_fail_fix)
[l4] openspec:add-shipping-fee [add-shipping-fee-fix-1] task 1.1 red ok: 3 new test(s) failing as expected
[l4] openspec:add-shipping-fee phase fixing → verifying (fix_unit_done)
[l4] openspec:add-shipping-fee verdict PASS (round 3, 4/4 criteria pass, 3 finding(s))
[l4] openspec:add-shipping-fee MR https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/15 marked ready for review
[l4] openspec:add-shipping-fee run finished: exit 0 in 223.9s, cost $0.2040
```

The read-only acceptance test (`tests/live/test_m1_3_acceptance.py`) passes 7, skips 2 (branch 1A did not happen;
the optional merge was not done) after its own fixes (`ce43a4b`, `e40e797`) — [output](m13/g6-after-step4-fixed.txt).

### add-vat finished through the legacy-round path (2026-10-05)

Plain story: `add-vat` had been waiting since M1.1 for a human answer to a question that was never asked. Its judge
had found a real gap (VAT ignored the discount code), but that older harness wrote no verdict question. After the
upgrade, the first pipeline asked it (Q-002) and made no agent call. The human answered `reject` with the expected
number, and merged `main` into the branch in the same push: the verifier needs it, and the harness does not do it yet.
The harness turned the reject into a fix unit, `add-vat-fix-1`.

Codex first asked a question, because the fix unit's proposal had cut off the human's decision (fixed since, in
`a1a0ca3`). After the human's answer, Codex fixed the code red → green. The human then accepted three original
criteria whose older tests carry no criterion tags. Round 4 passed and the merge request went to review. One more
harness bug was found in a local rehearsal and fixed before going live (`69ef5b4`): without it, the human's reject
would have been lost when the judge reworded the finding. Full step table: [README.md, "add-vat (legacy round)"](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| upgrade on `main`: the legacy round raises its verdict question Q-002, no agent call, exit 11 | [pipeline 2693](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2693) / [job 5485](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5485) ([log](m13/addvat-s1-job-5485.txt)) | [!5](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5) (draft, `l4:awaiting_human`, `l4:needs-answers`) | [questions commit 7a7d156](https://gitlab.example.com/example-group/dummy-agentic/-/commit/7a7d1563dd34df68c5697cee3a0d871881e46c32), [questions.md as asked](m13/addvat-s1-questions-at-65bce24.md) | [job-5485/](artifacts/job-5485/l4-out/) |
| the human: merge `main` in, `reject: WHEN a 10 % discount code … THEN total_with_vat is 108.90` → round 2 FAIL → fix unit → Codex asks "VAT base for discounted carts" | [pipeline 2696](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2696) / [job 5487](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5487) ([log](m13/addvat-s2-job-5487.txt)) | [!5](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5) | [answer 9e778f6](https://gitlab.example.com/example-group/dummy-agentic/-/commit/9e778f64271c4438b0e02ec0c5c442640684d1ef), [fix unit 501e83e](https://gitlab.example.com/example-group/dummy-agentic/-/commit/501e83e50aaa89ef1a48d14b386ab4d8c11d3eb7), [verification round 2](m13/addvat-s2-verification-round-2.md) | [job-5487/](artifacts/job-5487/l4-out/) ([the blocked red prompt](artifacts/job-5487/l4-out/agent/r-20261005T0003Z-3ffd/1.1-red-1.prompt.md)) |
| the human answers Codex → red → green → round 3 NEEDS_HUMAN on the three untagged original criteria | [pipeline 2705](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2705) / [job 5489](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5489) ([log](m13/addvat-s3-job-5489.txt)) | [!5](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5) | [red ed5732a](https://gitlab.example.com/example-group/dummy-agentic/-/commit/ed5732ad6400113d96eec21262c42971c8efcf7e), [green a6f7e24](https://gitlab.example.com/example-group/dummy-agentic/-/commit/a6f7e241599d6cdcf005e929c82117052ea13623), [verification round 3](m13/addvat-s3-verification-round-3.md) | [job-5489/](artifacts/job-5489/l4-out/) |
| the human accepts the three criteria → round 4 PASS (reused, no judge call) → hand-off | [pipeline 2714](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2714) / [job 5491](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5491) ([log](m13/addvat-s4-job-5491.txt)) | [!5 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5), `l4:in_review` | [answers 7c2ceb7](https://gitlab.example.com/example-group/dummy-agentic/-/commit/7c2ceb7f01f87d1130a39b1fba0ef5e4f9000b5b), [hand-off 30ccf6a](https://gitlab.example.com/example-group/dummy-agentic/-/commit/30ccf6a281e044fc3e49686f78462699325d44f4), [verification round 4](m13/addvat-s4-verification-round-4.md) | [job-5491/](artifacts/job-5491/l4-out/) |
| the hand-off commit's own pipeline: only `test` | [pipeline 2717](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2717) | [!5](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5) | [loop safety](m13/addvat-loop-safety.txt) | — |

The lines to look for (jobs 5485, 5487, 5489, 5491):

```
openspec:add-vat             awaiting_human  2/2    verify  legacy round 1: NEEDS_HUMAN without verdict questions, the run raises them
[l4] run: openspec:add-vat: round 1 ended NEEDS_HUMAN without verdict questions (an earlier harness); raised Q-002
[l4] openspec:add-vat phase awaiting_human → verifying (verdicts_answered)
[l4] openspec:add-vat verdict FAIL (round 2, 0/3 criteria pass, 3 finding(s))
[l4] openspec:add-vat commit 501e83e50a docs(add-vat): fix unit 1 [skip ci]
[l4] openspec:add-vat [add-vat-fix-1] question Q-001 raised (ambiguous): VAT base for discounted carts
[l4] openspec:add-vat [add-vat-fix-1] task 1.1 red ok: 1 new test(s) failing as expected
[l4] openspec:add-vat verdict NEEDS_HUMAN (round 3, 1/4 criteria pass, 3 finding(s))
[l4] openspec:add-vat verdict PASS (round 4, 4/4 criteria pass, 3 finding(s))
[l4] openspec:add-vat MR https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/5 marked ready for review
[l4] openspec:add-vat run finished: exit 0 in 13.7s
```

## M1.7: the harness merges `main` into a unit branch at verification step 0 (2026-10-05)

When `main` has moved on, the verifier now merges it into the unit branch itself, as its first step. Before M1.7 a
human had to do that by hand. Two new units show the three cases:
* `add-item-count`: a clean merge.
* `add-cart-clear`, first try: a real code conflict, where the harness stops and asks a human (red job, exit 1, a note
  on the merge request).
* `add-cart-clear`, after `main` undid its change: a conflict only in `questions.md`, which the harness settles on
  its own, keeping the newer human answer.

Each merge commit is `[skip ci]`, and GitLab skipped its pipeline. Then the full verification ran on the merged code, the
judge said PASS, and both merge requests went to review. Two harness bugs were found on the way and fixed:
* `12cc820`: git refused to merge without a committer identity on the runner.
* `ba54759`: Codex could not act on a red-gate message.

Full step table: [README.md, M1.7 section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| seeds and the upgrade on `main`: Q-001 raised for both units, exit 11 | [pipeline 2718](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2718) / [job 5494](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5494) ([log](m17/s1-job-5494.txt)) | [!16](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/16), [!17 (closed, attempt 1)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/17) | — | [job-5494/](artifacts/job-5494/l4-out/) |
| `add-item-count` attempt 1: Codex's red tests rejected three times as vacuous, unit halted (bug, fixed in `ba54759`) | [pipeline 2724](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2724) / [job 5498](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5498) ([log](m17/s3-attempt1-job-5498.txt)) | [!17 (closed)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/17) | [reset](m17/s3-reset.txt) | [job-5498/](artifacts/job-5498/l4-out/) ([Codex attempt 3](artifacts/job-5498/l4-out/agent/r-20261005T0403Z-de9e/1.1-red-3.jsonl)) |
| `add-item-count` attempt 2: red → green, then step 0's merge stopped on "Committer identity unknown" (bug, fixed in `12cc820`) | [pipeline 2731](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2731) / [job 5504](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5504) ([log](m17/s3-job-5504.txt)) | [!18](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/18) | [red a89030b](https://gitlab.example.com/example-group/dummy-agentic/-/commit/a89030b64c40d7ab7de0b588b25d66f50052d8c7), [green 08f3efb](https://gitlab.example.com/example-group/dummy-agentic/-/commit/08f3efb9fd6e770c7c4072c464458a36b94e7566) | [job-5504/](artifacts/job-5504/l4-out/) |
| **clean merge**: `main` merged as [`dc05253`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/dc05253b41ea26c5a8ab2ec706cf4c97863d9503) (pipeline skipped), full verification, PASS, hand-off | [pipeline 2738](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2738) / [job 5506](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5506) ([log](m17/s3-verify-job-5506.txt)) | [!18 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/18) | [checks](m17/s3-checks.txt), [verification.md](m17/s3-verification-add-item-count-round-1.md) | [job-5506/](artifacts/job-5506/l4-out/) |
| **code conflict**: `add-cart-clear` red → green, then step 0 found `src/pricing/cart.py` in conflict, exit 1, note "Base merge needed" | [pipeline 2746](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2746) / [job 5513](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5513) ([log](m17/s5-job-5513.txt)) | [!16](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/16) | [checks](m17/s5-checks.txt) | [job-5513/](artifacts/job-5513/l4-out/) |
| **questions.md settled by the harness**: `main` reverted its helpers, merged as [`46cfa14`](https://gitlab.example.com/example-group/dummy-agentic/-/commit/46cfa14b88814a730520a8f4fb232a84ac20b257), the branch's answer kept byte for byte, PASS, hand-off, note cleared | [pipeline 2753](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2753) / [job 5515](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5515) ([log](m17/s6-job-5515.txt)) | [!16 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/16) | [checks](m17/s6-checks.txt), [dry run before the job](m17/s6-dryrun-add-cart-clear.txt), [verification.md](m17/s6-verification-add-cart-clear-round-1.md) | [job-5515/](artifacts/job-5515/l4-out/) |
| loop safety: no `l4` job on a bot commit, every `[skip ci]` pipeline skipped | pipelines 2718–2759 | — | [loop-safety.txt](m17/loop-safety.txt) | — |

The lines to look for (jobs 5506, 5513 and 5515):

```
[l4] openspec:add-item-count commit dc05253b41 chore(add-item-count): merge main@0c43167896 into the unit branch [skip ci]
[l4] openspec:add-item-count base merged: main@0c43167896 into l4/openspec/add-item-count as dc05253b41 (2 commits)
[l4] openspec:add-item-count verdict PASS (round 1, 2/2 criteria pass, 3 finding(s))
[l4] openspec:add-cart-clear base merge conflict with main@c647207a96: src/pricing/cart.py; merge it by hand and push (exit 1)
[l4] openspec:add-cart-clear commit 46cfa14b88 chore(add-cart-clear): merge main@703a7768d6 into the unit branch [skip ci]
[l4] openspec:add-cart-clear base merged: main@703a7768d6 into l4/openspec/add-cart-clear as 46cfa14b88 (7 commits; resolved openspec/changes/add-cart-clear/questions.md)
[l4] openspec:add-cart-clear verdict PASS (round 1, 2/2 criteria pass, 2 finding(s))
```

## M1.5: lessons, Serena, Playwright, and System One with Jev and Laya (2026-10-05)

Plain story: the first unit adds an item count to a small cart web page. Codex writes only a unit test. The verifier
sees that a criterion about the page has no browser test, generates one, and proves it: it fails on the old page and
passes on the new one. Because of that, the harness writes a lesson, "UI criteria need an end-to-end test", into the
repository's memory file. After the human merge, the second unit (the subtotal) gets that lesson in Codex's prompt,
and this time Codex writes the browser test itself.

System One answers on the side. Jev (the hosted TypeSafe API) gives a probability per criterion, and Jev and a Laya
server started on the runner both answer the same record-only questions. Neither decides anything. A third unit shows
the clarifier with Jev: Claude answered a technical question correctly, but Jev was not sure enough that the cited
lines prove the answer, so the question went to a human. Full step table: [README.md, M1.5 section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| archive MR !3 (M1.1) merged first, so a new archive MR can open | [pipeline 2760](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2760) / [job 5520](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5520) ([log](m15/s0b-archive3-job-5520.txt)) | [!3 (merged)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/3) | — | [job-5520/](artifacts/job-5520/l4-out/) |
| **P1** `show-item-count`: Serena ready, Codex red → green, the verifier generates `e2e/test_l4_c_de7f2d3f.py` (base fail, head pass), Jev p 0.95, Laya and Jev in the shadow, judge PASS, **lesson L-09421538 created** | [pipeline 2761](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2761) / [job 5522](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5522) ([log](m15/s2-p1-job-5522.txt)) | [!19 (merged)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/19) | [generated test 174a758](https://gitlab.example.com/example-group/dummy-agentic/-/commit/174a75844f32be180d72a86b8ea945a61ca10da6), [lesson af0f196](https://gitlab.example.com/example-group/dummy-agentic/-/commit/af0f1961f00aa7be2c4c1f851910189a258b896f), [commits](m15/s2-show-item-count-commits.txt), [verification.md](m15/s2-show-item-count-verification.md), [lessons.md](m15/s2-lessons-md-on-branch.md) | [job-5522/](artifacts/job-5522/l4-out/) ([S1 rows](artifacts/job-5522/l4-out/s1/r-20261005T0802Z-90e5.jsonl), [System-One log](artifacts/job-5522/l4-out/logs/system-one.jsonl), [laya-serve log](artifacts/job-5522/l4-out/logs/laya-serve.log)) |
| **P2** the human merges !19: archive MR !20 opens, `main` now has the lesson and the generated test | [pipeline 2771](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2771) / [job 5525](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5525) ([log](m15/s3-p2-merge-job-5525.txt)) | [!20 archive](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/20) | lessons.md on main (maintainer's local notes, not published), [e2e test on main](https://gitlab.example.com/example-group/dummy-agentic/-/blob/main/e2e/test_l4_c_de7f2d3f.py) | [job-5525/](artifacts/job-5525/l4-out/) |
| **P3** `show-subtotal`: **the lesson is in Codex's prompt**, Codex writes `e2e/test_l4_c_68f2e098.py` itself (second red attempt), Jev p 0.96, PASS | [pipeline 2773](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2773) / [job 5528](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5528) ([log](m15/s4-p3-job-5528.txt)) | [!21 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/21) | [red fb32018](https://gitlab.example.com/example-group/dummy-agentic/-/commit/fb3201874ba0f601dcbcafdf8a913af8adc6cb4a), [commits](m15/s4-show-subtotal-commits.txt), [verification.md](m15/s4-show-subtotal-verification.md) | [job-5528/](artifacts/job-5528/l4-out/) ([red prompt with the lesson](artifacts/job-5528/l4-out/agent/r-20261005T0815Z-5946/1.1-red-1.prompt.md)) |
| **Jev in the clarifier** `add-cent-rounding`: Claude answers "use `Decimal`" (right), and Jev's "the citation establishes it" is 0.65–0.77 < 0.80, so the question goes to a human | [pipeline 2781](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2781) / [job 5531](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5531) ([log](m15/s6-jev-clarifier-job-5531.txt)) | [!22 draft, awaiting a human](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/22) | [questions.md](m15/s6-add-cent-rounding-questions.md) | [job-5531/](artifacts/job-5531/l4-out/) ([Jev requests and answers](artifacts/job-5531/l4-out/logs/system-one.jsonl)) |
| cleanup: archive MR !20 merged, the sweeper retires show-item-count's lock ref | [pipeline 2786](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2786) / [job 5533](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5533) ([log](m15/s7-archive20-job-5533.txt)) | [!20 (merged)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/20) | — | [job-5533/](artifacts/job-5533/l4-out/) |
| loop safety: no `l4` job on a bot commit, every `[skip ci]` pipeline skipped | pipelines 2760–2785 | — | [P1–P3](m15/s5-loop-safety.txt), [step 6](m15/s6-loop-safety.txt) | — |
| acceptance test (`tests/live/test_m1_5_acceptance.py`, `L4_LIVE=1`): 13 passed | — | — | [result](m15/acceptance-final.txt), [ids](m15/acceptance-ids.json) | — |

The lines to look for (jobs 5522, 5528, 5531):

```
[l4] openspec:show-item-count gate e2e-base fail (exit 1, 2 tests: 1 passed, 1 failed) — exit code 1
[l4] openspec:show-item-count gate e2e-head pass (exit 0, 2 tests: 2 passed, 0 failed)
[l4] openspec:show-item-count s1_judge: jev ok → selected
[l4] system_one: laya-serve started: pid 135889, port 58763, model typed-decisions, laya 0.3.24
[l4] system_one: laya-serve stopped: pid 135889, exit code -15
[l4] openspec:show-item-count commit af0f1961f0 chore(memory): lesson L-09421538 created [skip ci]
[l4] openspec:show-subtotal gate e2e pass (exit 0, 3 tests: 3 passed, 0 failed)
[l4] openspec:add-cent-rounding clarifier Q-001: escalated to a human (citation src/pricing/cart.py#L38-L39: S1 p(the cited text establishes the answe…
```

## M1.6: the verifier checks scope, test coverage and the test run, and Laya is tuned on the answers (2026-10-05)

A human push to a unit branch changed a file in another module (`src/inventory/stock.py`) and added a 77-line receipt
formatter that no test runs. The verifier found both on its own: the inventory file is out of scope, only 7.9 % of the
changed lines ran, and both became questions for the human. The human rejected the inventory change and accepted the
receipt helper; the rejection became a ground-truth label. On the Mac, those labels plus 1380 generated examples
trained Laya. The tuned Laya is much better than the base overall, but worse on code that did run, so the gate
**failed** and it was not deployed. Jev answered the same questions on the side, scored only. One harness bug was fixed
on the way (the red guard broke a common Python import pattern). Full step table: [README.md, M1.6 section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof on the branch | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| **P1** `add-bulk-discount`: the open question in `design.md` goes to a human (Q-001) | [pipeline 2787](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2787) / [job 5535](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5535) ([log](m16/s1-p1-job-5535.txt)) | [!23 (closed in the reset)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/23) | [questions.md](m16/s1-p1-questions-at-b3f9a0c.md) | [job-5535/](artifacts/job-5535/l4-out/) |
| **P2, first try: halted by a harness bug.** Codex imported a type under `if TYPE_CHECKING:`; the red guard dropped the block and kept the import, so lint failed three times | [pipeline 2792](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2792) / [job 5537](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5537) ([log](m16/s2-p2-halted-job-5537.txt)) | !23 | [ledger](m16/s2-p2-halted-ledger-r-20261005T0853Z-adaa.jsonl) | [job-5537/](artifacts/job-5537/l4-out/) ([lint log](artifacts/job-5537/l4-out/gates/r-20261005T0853Z-adaa/015-lint.log)) |
| live-fix `7c7d7c9` in the harness, unit reset, **P1 again** | [pipeline 2795](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2795) / [job 5539](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5539) ([log](m16/s1b-p1-rerun-job-5539.txt)) | [!24](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/24) | — | [job-5539/](artifacts/job-5539/l4-out/) |
| **P2** the human answers Q-001 and pushes the two seeded edits: Codex red → green, then **scope hold** on `src/inventory/stock.py`, **coverage hold** on the receipt functions (7.9 %), all 22 tests ran, Laya (on the runner) and Jev answer 12 shadow items each, NEEDS_HUMAN | [pipeline 2800](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2800) / [job 5541](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5541) ([log](m16/s2b-p2-job-5541.txt)) | !24 | [verification.md with the Evidence section](m16/s2b-add-bulk-discount-verification.md), [evidence.json](m16/s2b-evidence-round-1.json), [questions](m16/s2b-questions-at-a8000ac.md) | [job-5541/](artifacts/job-5541/l4-out/) ([S1 items and answers](artifacts/job-5541/l4-out/s1/r-20261005T0921Z-1804.jsonl)) |
| **P3** the human rejects the scope hold and accepts the coverage hold: **one label `out_of_scope` from `human:verdict`**, none for the coverage hold; the unit stays with the human | [pipeline 2809](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2809) / [job 5543](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5543) ([log](m16/s3-p3-job-5543.txt)) | !24 (closed after the checks) | [questions](m16/s3-questions-at-ad2000c.md), [round 2](m16/s3-add-bulk-discount-verification-round-2.md) | [label record](artifacts/job-5543/l4-out/s1/r-20261005T0930Z-1874.jsonl) |
| **Mac:** canary (1380 items), export (1239 rows, 0 from an engine), one fine-tune (35 min), **gate FAILED**, three-way comparison | — | — | [compare](../s1/compare-2026-10-05-live.md), [real vs synthetic](../s1/slices-2026-10-05-live.md), [gate](../s1/gate-2026-10-05-live.json), [train record](../s1/train-2026-10-05-live.json) | — |
| cleanup: the abandoned unit retired from `main`, nothing to do | [pipeline 2814](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2814) / [job 5545](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5545) ([log](m16/s8-cleanup-job-5545.txt)) | — | — | — |
| loop safety and runner: 22 `[skip ci]` pipelines skipped, no `laya-serve` left | pipelines 2787–2814 | — | [loop safety](m16/s7-loop-safety.txt), [runner after](m16/s7-runner-after.txt), [memory](../runner/memsample-2026-10-05-m16-live.txt) | — |
| acceptance test (`tests/live/test_m1_6_acceptance.py`, `L4_LIVE=1`): 8 passed, 2 skipped (P4 needs a passed gate) | — | — | [result](m16/acceptance-final.txt), [ids](m16/acceptance-ids.json) | — |

The lines to look for (jobs 5537, 5541):

```
[l4] openspec:add-bulk-discount guard violation: red scope on src/pricing/discounts.py → restored
[l4] openspec:add-bulk-discount task 1.1 red attempt 3 failed: lint gate … F401 [*] `typing.TYPE_CHECKING` imported but unused
[l4] system_one: laya-serve started: pid 157171, port 55311, model typed-decisions, laya 0.3.24
[l4] system_one: laya-serve stopped: pid 157171, exit code -15
[l4] openspec:add-bulk-discount verdict NEEDS_HUMAN (round 1, 2/2 criteria pass, 5 finding(s))
verification.md: 0 preconditions ok "base main@b98d1d06de contained"; 1 integrity "scope: 8 changed file(s), 1 held"; 6 quality "7.9% of the changed executable lines ran"
```

## Handbook fixes live: safer secrets, sandbox sockets, published judge prompts (2026-10-05)

This run checked the handbook fixes on the live project while the runner's Claude login was dead.
* **Judge fallback.** The judge chain skipped Claude at its login check ("claude is not logged in") and used the free
  OpenCode model instead. The independence is labelled "declared (unverified)".
* **Sandbox.** Inside the sandbox no container-daemon socket can be reached; outside it the docker daemon answers.
* **Secrets.** The two harness secrets now reach only the `l4` job. The bot token was rotated on the way.
* **Judge prompt.** It is now published next to the judge's output, and its file hashes to the value in
  `verdict.json`. That was true only after one harness fix: the free OpenCode judge gets a schema instruction
  appended, and the first run published it inside the file.

Full step table: [README.md, "Handbook fixes live" section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| upgrade to harness `1aa6f36`; the `l4` job now runs in environment `l4`; doctor `SANDBOX-002 pass` | [pipeline 2815](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2815) / [job 5547](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5547) ([log](hb/s1-upgrade-job-5547.txt)) | — | — | [job-5547/](artifacts/job-5547/l4-out/) |
| sandbox probe on the runner: codex and opencode PASS, every canary clean; outside the sandbox docker answers `200 OK` | — (mk-ssh) | — | [probe + control](../runner/sandbox-probe-2026-10-05-hb.txt) | — |
| secrets scoped to environment `l4`: a job without the environment sees **ABSENT**, the `l4` one **PRESENT** | [pipeline 2816](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2816) (before), [pipeline 2817](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2817) (after) | — | [variable record](hb/s3-ci-variables.txt), [after: plain job](hb/s3-probe-after-plain-job-5550.txt), [after: l4 job](hb/s3-probe-after-l4env-job-5551.txt) | — |
| `add-cart-is-free`, first try: Codex red → green, Claude skipped, OpenCode judged PASS, MR ready. The published judge prompt did **not** hash to `verdict.json` (harness bug) | [pipeline 2818](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2818) / [job 5553](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5553) ([log](hb/s4-unit-job-5553.txt)) | [!25 (closed in the reset)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/25) | [verification.md](hb/s4a-add-cart-is-free-verification.md), [verdict.json](hb/s4a-add-cart-is-free-verdict.json) | [job-5553/](artifacts/job-5553/l4-out/) |
| live-fix `89a51ae`, unit reset, **second try: PASS**, the prompt file hashes to `verdict.json` | [pipeline 2826](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2826) / [job 5556](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5556) ([log](hb/s4b-unit-rerun-job-5556.txt)) | [!26 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/26) | [verification.md](hb/s4b-add-cart-is-free-verification.md), [verdict.json](hb/s4b-add-cart-is-free-verdict.json), [commits](hb/s4b-add-cart-is-free-commits.txt), [sandbox argv seen on the runner](hb/s4b-argv-sample-job-5556.jsonl) | [job-5556/](artifacts/job-5556/l4-out/) |
| loop safety and runner: 12 bot `[skip ci]` pipelines skipped, hand-offs ran only `test`, no runner process left | pipelines 2815–2833 | — | [loop safety](hb/s5-loop-safety.txt), [runner processes](hb/s5-runner-processes.txt) | — |

The lines to look for (job 5556 and its artefacts):

```
SANDBOX-002  error     pass    no container-daemon socket is reachable from the agent or the gate sandbox
[l4] judges: claude-code skipped — auth: claude is not logged in
[l4] judges: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello 5.9s) → selected, fallback #1
[l4] openspec:add-cart-is-free verdict PASS (round 1, 2/2 criteria pass, 4 finding(s))
verification.md: - independence: declared (unverified): opencode-free zhipu (declared), codex openai (tool)
sha256(agent/r-20261005T1615Z-a459/verify-judge-r1-1.prompt.md) = verdict.json prompt_sha256 = d28539ae226638db88e6a1975f610e4e8b783ab7fe52d0b1e555dfded427e02a
run.started: "runner": {"id": "12", "description": "l4-runner"}, "tools": {"python": "3.13.16", "git": "2.34.1", "bwrap": "0.6.1"}
codex argv (runner /proc): ... --ignore-user-config --ignore-rules -c project_doc_max_bytes=0 ...
```

## M1.9: the harness looks again after the hand-off (2026-10-06)

Before M1.9, a unit in review was never looked at again: a person's commit on its branch, or the project's own CI going
red on the hand-off commit, left it "waiting for merge". Now:
* **A person's commit after the hand-off** sends the unit back to verification. A forbidden path the person changed
  (here `.gitlab-ci.yml`) is listed, not held against the unit. This was checked on sample-consumer MR !1; that
  evidence is private, so only counts are in the README.
* **The project's own CI red on the hand-off commit**: the sweep records it. The next run fails verification at step
  0 with `repository CI failed: <job>`, a fix unit repairs it, and the harness hands off again. This was checked on the
  dummy: the human made its `test` job stricter (lines of at most 92 characters in `src`) than the L4 lint gate (110).
* **Links in committed ledgers** read `<forge>/…` instead of the server's name.

One harness bug was found live and fixed in `7ccbc43`: the fix task got the GitLab runner's cleanup lines instead of
the job's error.

Full step table: [README.md, "M1.9" section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| upgrade to `fce8a68`; the l4 pytest marker is registered; 11 units in review checked: `ci: H … green`, nothing written | [pipeline 2860](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2860) / [job 5594](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5594) ([log](m19/b1-upgrade-l4-job-5594.txt)) | — | — | [job-5594/](artifacts/job-5594/l4-out/) |
| first seed (`add-return-policy`): my spec error and a frozen red test, then reset | [5597](m19/b2-seed-l4-job-5597.txt), [5599](m19/b3-implement-l4-job-5599.txt), [5601](m19/b3b-implement-l4-job-5601.txt) | [!27 (closed)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/27) | [questions.md](m19/b3-add-return-policy-questions-at-cf6c2f7.md) | [job-5597/](artifacts/job-5597/l4-out/), [job-5599/](artifacts/job-5599/l4-out/), [job-5601/](artifacts/job-5601/l4-out/) |
| `add-return-notice`: green on the L4 gates, PASS, MR ready | [pipeline 2887](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2887) / [job 5603](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5603) ([log](m19/b4-implement-l4-job-5603.txt)) | [!28](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/28) | base `test` green: [5602](m19/b4-base-test-job-5602.txt) | [job-5603/](artifacts/job-5603/l4-out/) |
| the project's `test` job is **red** on the hand-off commit (`E501 Line too long (108 > 92)`) | [pipeline 2894](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2894) / [job 5604](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5604) ([log](m19/b5-h1-test-job-5604.txt)) | !28 | — | — |
| the schedule's sweep records `ci.failed`; the run goes `in_review → verifying (repository_ci_failed)`, step 0 FAIL with no judge call, a chore fix unit, a full round PASS and a new hand-off | [pipeline 2895](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2895) / [job 5606](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5606) ([log](m19/b6-sweep-reverify-l4-job-5606.txt)) | [!28 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/28) | [ci.failed](m19/b6-sweep-ci-failed-pending-ledger-r-20261006T0003Z-d2b3.jsonl), [run ledger](m19/b6-reverify-pending-ledger-r-20261006T0003Z-a64f.jsonl), [round 2 (step 0)](m19/b6-verification-round2-step0.md), [round 3](m19/b6-verification-round3.md), [fix proposal](m19/b6-fix-unit-1-proposal-at-4cc06e6.md), [MR notes](m19/b6-mr28-notes-from-0000.txt) | [job-5606/](artifacts/job-5606/l4-out/) |
| the project's `test` job is **green** on the new hand-off commit | [pipeline 2904](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2904) / [job 5607](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5607) ([log](m19/b7-h2-test-job-5607.txt)) | !28 | — | — |
| live-fix `7ccbc43`: the log tail without the runner's lines (offline on job 5604's real log, then live) | [pipeline 2914](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2914) / [job 5614](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5614) ([log](m19/b9-livefix-sweep-reverify-l4-job-5614.txt)) | [!29 (escalated)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/29) | [before/after](m19/b8-livefix-tail-of-job-5604.txt), [clean ci.failed](m19/b9-livefix-sweep-ci-failed-pending-ledger.jsonl), [fix proposal with the error](m19/b9-fix-unit-1-proposal-at-b5a130a.md), [judge caught a wrong fix](m19/b9-verification-round3-needs-human.md), [escalated](m19/b10-verification-round4-escalated.md) | [job-5611/](artifacts/job-5611/l4-out/), [job-5614/](artifacts/job-5614/l4-out/), [job-5616/](artifacts/job-5616/l4-out/) |

The lines to look for (job 5606):

```
openspec:add-return-notice: ci: H 2320b4e3d2 red: test (recorded)
openspec:add-return-notice  in_review       1/1    verify  in_review: repository CI failed on 2320b4e3d2: test
[l4] openspec:add-return-notice phase in_review → verifying (repository_ci_failed: test on 2320b4e3d2)
[l4] openspec:add-return-notice verdict FAIL (round 2, 0/0 criteria pass, 1 finding(s))
[l4] openspec:add-return-notice [add-return-notice-fix-1] task 1.1 started: 1.1 repository CI failed: test (F-2aa04fcb)
[l4] openspec:add-return-notice verdict PASS (round 3, 1/1 criteria pass, 2 finding(s))
[l4] openspec:add-return-notice commit c8dfcd9560 docs(add-return-notice): hand off to review
verification.md round 2: | 0 | preconditions | failed | 0.4 | base main@f2274d4cac contained; repository CI failed: test |
```

## M1.10: the failing project CI step becomes a gate of the fix (2026-10-06)

In M1.9 a fix for "the project's own CI is red on the hand-off commit" was checked only by the judge, and in one run a
wrong fix got through every L4 gate. M1.10 re-runs the project job's failing step as an extra gate,
`repository-ci:<job>`. It runs first at the fix's base (to see that it fails the same way), then after the fix, where
it must pass. It also runs in the verification round that follows. On the dummy:
* the hand-off commit was red on `uv run ruff check --select E501 --line-length 92 src` (106 > 92);
* the sweep printed `repository CI failed on 222e60b307: test (pipeline 2955); l4 run re-verifies`;
* step 0 failed and named that command;
* the fix unit ran it at its base (`fail`, `reproduced`), then after Codex's fix (`pass`);
* round 3 ran it again (`pass`) and handed off; the new hand-off commit's `test` job is green.

Also visible: the title of a raised question in the log (C5) and the runner's tags in `l4 setup gitlab` (C7).
Afterwards the 92-character step was removed from the dummy's `test` job. No harness change was needed.

Full step table: [README.md, "M1.10" section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| upgrade to `692a639`; 12 units in review checked: `ci: H … green`, nothing written | [pipeline 2942](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2942) / [job 5642](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5642) ([log](m110/b1-upgrade-l4-job-5642.txt)) | — | — | [job-5642/](artifacts/job-5642/l4-out/) |
| seeds: `add-pickup-notice` goes red → green → PASS; the throwaway `add-gift-note` raises `question Q-001 raised (ambiguous): Scenarios "…" and "…" conflict` (C5) | [pipeline 2943](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2943) / [job 5644](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5644) ([log](m110/b2-seed-pickup-giftnote-l4-job-5644.txt)) | [!31](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/31), [!30 (closed)](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/30) | [questions.md](m110/b2-add-gift-note-questions-at-1dae9fc.md), [ledger with the title](m110/b2-add-gift-note-ledger-r-20261006T0501Z-be4d.jsonl) | [job-5644/](artifacts/job-5644/l4-out/) |
| the project's `test` job is **red** on the hand-off commit (`E501 Line too long (106 > 92)`) | [pipeline 2955](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2955) / [job 5647](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5647) ([log](m110/b3-h1-test-job-5647.txt)) | !31 | — | — |
| the schedule's sweep warns; step 0 FAIL derives the step; the fix unit reproduces it with `gate repository-ci:test fail`, fixes it (`pass`); round 3 runs it again; PASS and a new hand-off | [pipeline 2950](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2950) / [job 5646](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5646) ([log](m110/b4-sweep-reverify-l4-job-5646.txt)) | [!31 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/31) | [ci.failed with `step`](m110/b4-sweep-ci-failed-pending-ledger-r-20261006T0504Z-7f11.jsonl), [run ledger with `ci.step`](m110/b4-reverify-run-ledger-r-20261006T0505Z-0bdf.jsonl), [round 2 (step 0)](m110/b4-verification-round2-step0.md), [round 3 with the gate row](m110/b4-verification-round3.md), [fix proposal](m110/b4-fix-unit-1-proposal-at-f6546fc.md), [fix diff](m110/b4-fix-commit-4bee00c-src.diff), [gate logs](artifacts/job-5646/l4-out/gates/r-20261006T0505Z-0bdf/) | [job-5646/](artifacts/job-5646/l4-out/) |
| the project's `test` job is **green** on the new hand-off commit | [pipeline 2964](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2964) / [job 5648](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5648) ([log](m110/b5-h2-test-job-5648.txt)) | !31 | — | — |
| `l4 setup gitlab --no-pipeline` (Mintkey wrapper): the runner row ends `tags: agentic, ai, opencode` (C7), nothing changed | — | — | [output](m110/c7-setup-gitlab-no-pipeline.txt) | — |
| cleanup: the 92-character step removed from `test`, the throwaway seed removed; the next sweep reads `ci: H 939d100f49 green` and does nothing | [pipeline 2965](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/2965) / [job 5650](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5650) ([log](m110/b6-cleanup-l4-job-5650.txt)) | !31, !30 | [test job](m110/b6-cleanup-test-job-5649.txt), [MR notes](m110/b7-mr31-and-mr30-state-and-notes.txt) | [job-5650/](artifacts/job-5650/l4-out/) |
| offline: M1.9's wrong fix (MR !29) fails the same gate command (`E501 … (105 > 92)`) | — | [!29](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/29) | [b8-offline-gate-on-mr29-wrong-fix.txt](m110/b8-offline-gate-on-mr29-wrong-fix.txt) | — |

The lines to look for (job 5646):

```
[l4] openspec:add-pickup-notice repository CI failed on 222e60b307: test (pipeline 2955); l4 run re-verifies
[l4] openspec:add-pickup-notice phase in_review → verifying (repository_ci_failed: test on 222e60b307)
[l4] openspec:add-pickup-notice CI job test: failing step derived `uv run ruff check --select E501 --line-length 92 src`
[l4] openspec:add-pickup-notice verdict FAIL (round 2, 0/0 criteria pass, 1 finding(s))
[l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] gate repository-ci:test fail (exit 1) — exit code 1
[l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] CI job test: failing step reproduced `uv run ruff check --select E501 --line-length 92 src`
[l4] openspec:add-pickup-notice [add-pickup-notice-fix-1] gate repository-ci:test pass (exit 0)
[l4] openspec:add-pickup-notice gate repository-ci:test pass (exit 0)
[l4] openspec:add-pickup-notice verdict PASS (round 3, 1/1 criteria pass, 0 finding(s))
[l4] openspec:add-pickup-notice commit 939d100f49 docs(add-pickup-notice): hand off to review
```

## M1.11: retry prompts with the error, resume from CI, a halt is a warning, a seeded uv cache (2026-10-06)

M1.11 fixes the wave A findings of sample-consumer. This check ran its branch head (`f4fc2ef`, not yet merged
into the harness `main`) on the dummy. On the dummy:
* **A new unit's first setup** took 2.0 s instead of 11.4 s. It copies a per-project uv cache seed, so it downloads
  nothing and prints no hardlink warning. The first new unit filled the seed in 6.6 s.
* **A halt no longer turns `main` red.** The run that halted exited 13, and its pipeline reads `passed with
  warnings`. The MR got `l4:halted` and a note that names the reason and the label `l4:resume`.
* **The `l4:resume` label resumes a halted unit from CI.** The maintainer added it, and the next pipeline resumed the
  unit and retried its task from attempt 1. A person's push alone only prints a hint. After the person's fix and the
  label again, the unit went red → green → PASS and is in review.
* **The retry prompt carries the error.** Here the agent changed an existing test instead of adding one. At first the
  retry said only `tests not collected individually`, and the agent did the same again. The live-fix `28b8cc3` names
  the test and puts its `E` lines into the next prompt. The next attempt then left the existing test alone.
* **The MR text** says that any merge method works.

Full step table: [README.md, "M1.11" section](README.md).

| What happened | Pipeline / job (job log) | Merge request | Proof | Saved job artefacts (in this repo) |
|---|---|---|---|---|
| upgrade to `f4fc2ef`: the CI include allows exit 13; nothing to do | [pipeline 3177](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3177) / [job 5807](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5807) ([log](m111/b1-upgrade-l4-job-5807.txt)) | — | [include diff](m111/b1-upgrade-local.txt) | — |
| seeds: `add-restock-label` fills the uv seed and passes; `change-low-stock-rule` copies it (setup 2.0 s), fails red 3 times on an existing test and halts; job `failed (allowed)`, pipeline **passed with warnings** | [pipeline 3181](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3181) / [job 5810](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5810) ([log](m111/b2-seeds-l4-job-5810.txt)) | [!33](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/33), [!34](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/34) | [pipeline statuses](m111/w4-pipelines-and-skipped-resume-commits.txt), [halted note](m111/w4-mr34-sticky-at-first-halt.txt), [seed log](artifacts/job-5810/l4-out/gates/r-20261006T1849Z-1671/001-seed.log), [bare retry prompt](artifacts/job-5810/l4-out/agent/r-20261006T1849Z-1671/1.1-red-2.prompt.md), [MR !33 text](m111/w9-mr33.txt) | [job-5810/](artifacts/job-5810/l4-out/) |
| live-fix `28b8cc3` vendored; the planner says how to resume | [pipeline 3202](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3202) / [job 5828](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5828) ([log](m111/b3-livefix-upgrade-l4-job-5828.txt)) | !34 | — | — |
| the maintainer adds `l4:resume`; the sweep resumes the unit (event 1532); the retry prompt now holds the `E` lines; the unit halts again (lint, then the same edit) | [pipeline 3203](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3203) / [job 5830](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5830) ([log](m111/b4-resume-label-l4-job-5830.txt)) | !34 | [retry prompt with the excerpt](artifacts/job-5830/l4-out/agent/r-20261006T1936Z-db1f/1.1-red-2.prompt.md) | [job-5830/](artifacts/job-5830/l4-out/) |
| the person's fix on the halted branch: the sweep says "add the label l4:resume to resume", nothing runs | [pipeline 3208](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3208) / [job 5832](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5832) ([log](m111/b5-person-push-l4-job-5832.txt)) | !34 | [commits](m111/b6-change-low-stock-rule-commits.txt) | — |
| the label again (event 1538): resumed, red → green → PASS, MR ready | [pipeline 3209](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3209) / [job 5834](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5834) ([log](m111/b6-resume-after-fix-l4-job-5834.txt)) | [!34 ready](https://gitlab.example.com/example-group/dummy-agentic/-/merge_requests/34) | [verification.md](m111/b6-change-low-stock-rule-verification-round1.md), [labels and note](m111/w2-mr34-after-continue.txt) | [job-5834/](artifacts/job-5834/l4-out/) |
| loop safety: every H green, nothing to do | [pipeline 3221](https://gitlab.example.com/example-group/dummy-agentic/-/pipelines/3221) / [job 5837](https://gitlab.example.com/example-group/dummy-agentic/-/jobs/5837) ([log](m111/b7-loop-safety-l4-job-5837.txt)) | !33, !34 | — | — |

The lines to look for:

```
job 5810:  [l4] openspec:change-low-stock-rule gate setup pass (exit 0)          (2.0 s after `task 1.1 started`)
job 5810:  l4 exit 13 (halted): halted: task 1.1: max_task_attempts (3) reached in red; …
job 5810:  ERROR: Job failed: exit status 13                                      (pipeline 3181: passed with warnings)
job 5830:  [l4] sweeper: openspec:change-low-stock-rule: resumed by a member's l4:resume label (event 1532)
job 5830:  [l4] openspec:change-low-stock-rule commit 949e32151f chore(change-low-stock-rule): resume [skip ci]
job 5832:  [l4] sweeper: openspec:change-low-stock-rule: halted; a person pushed after the halt: add the label l4:resume to resume
job 5834:  [l4] openspec:change-low-stock-rule verdict PASS (round 1, 1/1 criteria pass, 3 finding(s))
```
