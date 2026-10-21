# Kiro end-to-end SDD validation (plan: [../../plan/kiro-e2e.md](../../plan/kiro-e2e.md))

Labels: **[V]** seen in a log, stream, ledger or file; **[I]** inferred; **[U]** not checked; **[D]** from Kiro's docs.

**Current verdict (H3, 2026-10-08): our SDD approach with Kiro works end to end: yes, with fewer caveats** (section
H3 below). The four H2 follow-ups (KF1 to KF4, harness `9bcfb9c`) hold live in CI. The sweep ran the Kiro done-gate on
the merged H2 unit and on a fresh 3-leaf unit, and recorded `archive.done` once for each. Two FREE-tier throttles cooled
the profile without a failed attempt. A leaf whose behaviour an earlier leaf already provided was confirmed already
satisfied on its first attempt, with no production change. Credits are recorded with their source. Caveats left:

* Claude is still logged out on the runner, so a Qwen model on the Mac judged.
* The lock ref and the unit branch of a merged Kiro unit are kept by design, not retired.
* With a one-profile chain, a throttle ends the job and the unit waits for the next pipeline (no retry in the run).
* The progress log says an already-satisfied leaf is "failing as expected".
* Steering is still masked under bwrap (K10).
* The FREE plan's `/usage` reads about half of the stream-metered credits.

H2 (below) was the first CI pass, with caveats; H1, the first attempt, halted in red.

## H1: this Mac, local forge (2026-10-07/08, harness `999d991` → `3221a94` → `1138eae`)

**Verdict: the approach does not work end to end yet.** Kiro authors a spec headless that the harness accepts after
one formatting fix, intake and planning respect Kiro's waves, fallback and halt/resume work, and Kiro runs cleanly
under a harness agent. The implementation never got past task 2.1's red step: 13 kiro-cli red attempts in 5 runs
(plus G2's 3 deliberate exit-4 attempts), three halts. The first blocker is kiro-cli behaviour on its default agent (trusted tools denied, cause not isolated) that the
harness now avoids with its own agent (live-fix K3); the second and third are harness gaps: constants in red (fixed,
live-fix red@7) and the red-scope rebuild breaking import grouping, so the lint gate rejects a correct red step
(diagnosed, reproduced outside the run, **not fixed**: the two live-fixes this task allows were used). D, E and F could not run
on a finished unit.

| Step | Result |
|---|---|
| 0 merge of `kiro-e2e` (K1, K2, K4, K7, K17) | **PASS** |
| A authoring by Kiro | **PASS** (A1b; one formatting change: the graph's task ids) |
| B1 doctor, B2 plan, B3 dry run with probes | **PASS** |
| B4 clarifier | not exercised (no question raised) |
| G1 fallback | **PASS** |
| G2 halt and resume | **PASS** |
| C implementation by kiro-cli only | **FAIL**: halted three times on 2.1 red |
| D verification | not reached |
| E hand-off, done-gate, merge | not reached; `l4 archive` on the halted unit is refused (`only a merged unit can be archived`, exit 2), so the done-gate itself was not exercised |
| F Kiro checks | F1, F2, F3, F6, F7 hold on what ran; F4 not reached; F5 differs from the plan (steering is loaded) |

### Setup [V]

* `dummy-agentic` `main` at `7f4f454` (GitLab 118), pulled into the session's SSH clone, then `git clone --bare` to a
  local origin and a fresh clone `h1` from it. `h1` has no GitLab remote, so no push could reach GitLab; nothing was
  pushed to GitLab. Identity CiprianSpot.
* The vendored harness was upgraded with `l4 upgrade --harness <harness>`, committed in `h1` each time: `6b8500b`
  (`999d991`), `a538d1b` (`3221a94`, live-fix 1), then `1138eae` (live-fix 2; it also carries the M1.14 eval merge that
  another workflow landed on `main` meanwhile). Every command is the vendored `.l4/bin/l4` in `h1`, with
  `--config <scratch>/h1-cfg.yaml` and a private `L4_CACHE`.
* Scratch config = the dummy's config with `forge.type: local`, `ci.platform: local`, `sandbox: {mode: none,
  allow_none: true}` (macOS has no bubblewrap: agents and gates run as this user, a recorded risk acceptance; every
  run logs `SANDBOX DISABLED (accepted risk)` and the ledger `sandbox.disabled`), no e2e gate, Playwright off, System
  One off, Serena off, `max_fix_rounds: 0`, `audit_sample_ratio: 0`; `judges: [claude-code]`, `verifier_agent:
  [claude-code]`, `clarifier: [f-longcat, claude-code]`. Kiro profiles pin a model and declare its vendor (K6):
  `kiro-qwen {qwen3-coder-next, alibaba}`, `kiro-glm {glm-5, zhipu}`, `kiro-unavail` (`min_version: 99.0.0`),
  `kiro-halt` (`options.agent: l4-does-not-exist`).
* kiro-cli 2.28.0, KIRO PRO. Credits for all of H1, probes included: **48.57** (`/usage` 0.19 before, 48.76 after)
  [V]. Authoring ~1.40 (A1) and ~0.81 (A1b); the red attempts 22.3 metered in their streams (the interrupted
  default-agent attempts carry no metering event; the `/usage` total implies about 18 more [I]); probes ~5.3.

### A: Kiro authors the spec

* **A1** `kiro-cli chat --no-interactive --v3 --mode spec --model claude-sonnet-4.5 --trust-tools=read,write
  --output-format stream-json "Quick Spec. <brief>"`: exit 0, engine `v3`, three files. But every native `Write File`
  was **denied**; the files were written by shell heredocs (`cat > … << 'EOF'`, `mkdir -p`) that ran only because the
  user's `~/.kiro/settings/permissions.yaml` auto-approves `cat *` and `mkdir *`. The model also `tool_load`ed the
  user's `filesystem` MCP server and tried its `write_file` (outside that server's root). On a host without that file
  A1 writes nothing [I]. [stream](h1/A/A1.stream.jsonl), [spec](h1/A/A1-authored/)
* **A1b** the same with `--trust-all-tools` in a throwaway clone: exit 0, 1 read and 3 native writes, 0 denials, no
  other file touched, no `.config.kiro` or `tasks.meta.json`. **This spec is the one used**, copied into `h1` as a
  human commit (`18ed817`, bytes as written). [stream](h1/A/A1b.stream.jsonl), [spec as written](h1/A/A1b-authored/)
* Review against Kiro's conventions [V]: `# Requirements Document`, `### Requirement N`, `**User Story:**`,
  `#### Acceptance Criteria` with EARS `WHEN … THEN the system SHALL …` (K11 needs nothing); 8 required leaves
  (`1.1`–`1.3`, `2.1`–`2.5`) each with `_Requirements: …_`; one optional `- [ ]* 2.6`; no `**Validates:**` form (K12
  needs nothing); `## Task Dependency Graph` with task 2 in wave 0.
* **The one change the harness required**: the graph JSON listed task ids as JSON **numbers** (`[2.1, 2.2, …]`). The
  harness reads strings (as Kiro's own generator writes them), so on the raw spec `l4 plan` warned `invalid Task
  Dependency Graph (wave 0 has no list of task ids); using document order` and `l4 doctor` failed SPEC-002. The ids
  were quoted in a separate human commit `f3df2b4`; nothing else changed. Then the steering seed `a197d13`
  (`.kiro/steering/pricing-rules.md`). [raw plan](h1/A/raw-spec-plan.stderr.txt), [raw doctor](h1/A/raw-spec-doctor.txt)
* A2 not needed; A3 (the maintainer in the TUI) cannot be done from an agent session.

### B and G

* **B1** `l4 doctor --unit kiro:add-bulk-discount`: `SPEC-001 pass openspec, kiro`, `SPEC-002 pass 1 Kiro unit(s)
  validate`, `SPEC-004 pass … every leaf cites a requirement`, `PRV-001 … kiro-qwen kiro-cli ready`, exit 0.
  [B1](h1/B/B1-doctor.txt)
* **B2** `l4 plan --json`: `next_action: implement`, `tasks {done 0, total 10}`. [B2](h1/B/B2-plan.json)
* **B3** `l4 run --dry-run --probe`: `implementer: kiro-qwen ok (binary 2.28.0 · auth subscription · quota 0.3% used
  (credits) · hello 12.8s) → selected` (K1 live: the flat `whoami`; quota from `/usage`; hello from `finalText`), then
  `task=2.1 (red)`: wave 0 first, not 1.1 (F3). [B3](h1/B/B3-dry-run.txt), [probe](h1/B/probe-kiro.json)
* **G1** implementer `[kiro-unavail, kiro-qwen]`, dry run: `kiro-unavail skipped — binary: version 2.28.0 <
  min_version 99.0.0`, `kiro-qwen ok … → selected, fallback #1`; no agent call. [G1](h1/G/G1-fallback-dry-run.txt)
* **G2** implementer `[kiro-halt]`: intake `none → intake → ready → implementing`, three red attempts each
  `kiro-cli exited with code 4 (runError at init)` in 4–11 s, 0 credits, `breaker.tripped {max_task_attempts}`,
  `implementing → halted`, **exit 13**, ledger committed and pushed to the local origin. `l4 resume --reason …`:
  `unit.resumed`, `halted → implementing (resumed)`, exit 0. [run](h1/G/G2-halt-run.txt),
  [resume](h1/G/G2-resume.txt), [ledgers](h1/runs/ledger/)

### C: every implementer attempt (task 2.1, red)

"Denied" counts the `[denied]` lines kiro-cli printed on stderr, one per refused tool call; MCP tools are never
trusted, so a few are expected on the default agent. Raw streams, prompts and stderr of every attempt: [runs/agent/](h1/runs/agent/); per-stream summary:
[stream-summary.txt](h1/C/stream-summary.txt).

| Run | Harness / agent / model | # | Denied (MCP used) | Outcome |
|---|---|---|---|---|
| `…2116Z-3014` | `999d991`, default agent, `--trust-tools=fs_read,fs_write,execute_bash`, qwen3-coder-next | 1 | 122, 118 of them `shell`; `filesystem`; 0 tools completed in 9 min | operator killed kiro-cli |
| | | 2 | 118; 0 completed | operator SIGINT to `l4 run`: exit 1, unit stayed `implementing` |
| `…2134Z-057d` | same | 1 | 4 (MCP only); read, shell, pytest, ruff completed | rejected: constants (finding 2) |
| | | 2 | 73 (`write` ×43, `shell`) | operator SIGINT: exit 1, unit stayed `implementing` |
| `…2217Z-50ce` | `3221a94` **K3 harness agent**, qwen3-coder-next | 1, 2 | **0**, none | rejected: constants |
| | | 3 | 0, none | rejected: `no new test traces C-…` (12 failing tests, none tagged) → **halted, exit 13** |
| `…2224Z-c2ee` | K3, glm-5 (after `l4 resume`) | 1, 2 | 0, none | rejected: constants |
| | | 3 | 0, none | rejected: lint `I001` in `src/pricing/__init__.py` → **halted, exit 13** |
| `…2241Z-d505` | `1138eae` K3 + **red@7**, glm-5 (after `l4 resume`) | 1, 2, 3 | 0, none | red itself correct (9–14 new tests fail by `NotImplementedError`, the zero-value run fails as required, **no red-scope violation**), each rejected: lint `I001` in `src/pricing/bulk_discount.py` → **halted, exit 13** (finding 3) |

**Finding 1, trust denials on the default agent (live-fix 1, K3, `15e7788` red, `3221a94` green).** In 3 of 4
harness-spawned steps on the default agent, kiro-cli denied every `write` and `shell` call although the trust list
named them (`Permission request failed: … tool permission approval is not supported in non-interactive mode`); one step
honoured the list. **The cause is not isolated.** The same argv, binary, 14 KB prompt, harness worktree as cwd,
harness environment (13 variables; the copied `PATH` was cut at a space, so not byte-exact), TMPDIR, a cold uv cache,
the vendored Python as parent and GNU `timeout` all passed when started by hand; a session poisoned by an earlier
`--agent l4-does-not-exist`, a `todo_list` call and parallel denied MCP calls were each ruled out
([replays](h1/C/probes/replays/)). Caveat: `cat` and `ls` are auto-approved by the user's `permissions.yaml`, so only
the `truncate` probes tested the trust list. The fix: an implementer step without `options.agent` runs `--agent
l4-implement-<random> --trust-all-tools`, with `KIRO_HOME` set to a directory in the step's private directory that
holds only that agent (tools `read, write, shell, glob, grep`, no MCP server, no resources). `KIRO_HOME` moves
`~/.kiro` (agents, settings and MCP config [V: the agent was found there, no MCP server started]; `permissions.yaml`
and skills [I]) but not the login, which stays in the CLI data store [V: logged in under it]. Result: 9 of 9 K3 steps with 0 denials and no MCP server [V]. This verifies the
mechanism over 9 steps, not that the default-agent denials can never recur elsewhere.

**Finding 2, constants in red (live-fix 2, red@7, `75d7cc6` red, `1138eae` green).** Task 2.1 is "Create
pricing/bulk_discount.py module with constants", the design lists `BULK_QUANTITY_THRESHOLD` and
`BULK_DISCOUNT_PERCENT`, and the steering rule says new constants go in `__all__`. In 4 of the 6 K3 attempts before
the fix, the model wrote correct stubs plus the two constants and exported them in `__init__.py`. The red-scope guard
dropped the assignments (`the statement at line N was not applied`) but kept the `__init__.py` import, so nothing
collected and the attempt read `tests not collected individually`. The red template now says that constants named by
the design or a steering file are green work and must not be defined or imported in red. After it, 0 red-scope
violations in 3 of 3 attempts [V]. Not checked with `l4 eval --compare`.

**Finding 3, the red rebuild breaks import grouping (NOT fixed).** `classify_red_changes` rebuilds a new production
module as its admissible parts: the new imports are joined with no blank line between isort sections and the module
docstring is dropped (no "restored" note says so). Kiro's `bulk_discount.py` (`from __future__ import annotations`,
blank, `from decimal import Decimal`, blank, `from pricing.cart import LineItem`, two stubs) passed `ruff check` in
Kiro's own run (`All checks passed!` in the stream); the harness's rebuilt file fails `I001`, and the lint gate rejects
the attempt as the agent's fault. Reproduced outside the run with the harness function and ruff
([agent's file](h1/C/i001-repro/agent-written.py), [rebuilt](h1/C/i001-repro/harness-rebuilt.py)) [V]. Every red step
that creates a module importing from two isort sections should hit this, whatever the agent [I: one repro]. Fix sketch: keep the agent's
import block text (or separate the sections with blank lines) and the module docstring when rebuilding a new module,
plus a test that rebuilt files pass the project's lint for the agent's lint-clean input. Then resume and re-run C.

**Finding 4, steering reaches the K3 agent [V].** A probe agent with `resources: []` in a scratch dir whose
`.kiro/steering/reply.md` (`inclusion: always`) says "End every reply with the single word PINEAPPLE" answered
`L4-OK PINEAPPLE`; the control without the file answered `L4-OK`; no tool call in either
([with](h1/F/steering-probe-with-steering.stream.jsonl), [control](h1/F/steering-probe-control.stream.jsonl)). Kiro's
docs say a custom agent loads steering only through `resources` [D]; 2.28.0 loads workspace steering anyway. In the
unit, glm-5 wrote `Updated __init__.py to export new constants per steering rules` and ended docstrings with
`(Req 1.1, …)`. So F5 on H1: the steering rule **is** followed; under bwrap (H2) `.kiro/steering` is masked, so H2
should differ (K10).

Other findings [V]:
* K20: a Kiro unit's implementer prompt says `OpenSpec does not link tasks to scenarios, so all of them are listed` and
  shows the leaf without its `_Requirements:_` line, so task 2.1 (`_Requirements: 1.1, 1.2, 1.3, 1.4_`) got all 8
  criteria and the models wrote cart tests for Requirement 2 in a task-2 step.
* A resume starts a new attempt 1 without the previous rejection text, so the first attempt after a resume repeats
  the mistake that halted the unit (runs `…2224Z-c2ee` and `…2241Z-d505`).
* The availability hello does not pass `options.agent`: `kiro-halt` probed `ok`, then exited 4 in the run (G2).
* The dry-run prompt has no prompt-contract Output section (it reads "schema enforced"); the real Kiro prompt says
  `Write your result object to .l4-result/result.json`.
* kiro-cli writes an empty `.kiro/agents/` into the worktree on start (no guard violation: git does not track it).
* qwen3-coder-next and glm-5 both ran pytest and ruff themselves inside the K3 agent; glm-5 also read the steering
  rule's intent into its docstrings.

### F checks on what ran ([F-checks-halted.txt](h1/F/F-checks-halted.txt), [F7](h1/F/F7-tool-names.txt))

* F1 markers: `tasks.md` on the unit branch is byte-identical to its base (1313 bytes, 0 differing offsets): no marker
  was written, because no task finished. No `-` or `~` (K9 stays). Vacuous, not a pass of the `x` path.
* F2 optional: `- [ ]* 2.6` untouched; no step ran for it.
* F3 waves: every run started task 2.1 (wave 0); 1.1 comes first in the document. **Holds.**
* F4 traceability: not reached (no `task.red_ok`).
* F5 steering: followed on H1 (finding 4), contrary to the plan's K3 expectation.
* F6 protected: `git diff a197d13..l4/kiro/add-bulk-discount` touches only the 9 ledger files; spec files and steering
  unchanged; the 10 `guard.violation` events are all `red scope` on `src/pricing/bulk_discount.py` (finding 2), none
  on a protected path. **Holds.**
* F7 isolation: K3 runs used only `read`, `write`, `shell`, `glob` and no MCP server; the default-agent runs used the
  user's `filesystem` MCP tools (`list_directory`, `read_text_file`, `read_multiple_files`, `write_file`) and
  `todo_list`. **Holds under K3**; the default agent leaks.

### Operator interventions

* Run `…2116Z-3014`: kiro-cli killed (SIGTERM) during attempt 1, then SIGINT to `l4 run` during attempt 2.
* Run `…2134Z-057d` (`C-run2-diag.txt`: a diagnostic wrapper was put on `PATH`, but the harness resolved the real
  binary first, so the run is a plain default-agent run): SIGINT during attempt 2.
* `l4 resume` three times (`C-resume-glm.txt`, `C-resume-glm2.txt`, and G2), each a ledger `unit.resumed`.
* Notes: [C-attempt1-killed-by-operator.txt](h1/C/C-attempt1-killed-by-operator.txt).

### What H2 needs from this

Finding 3 fixed and C re-run to the end on H1 first. H2 should then expect: K3 unchanged under bwrap if the step's
private directory (where `KIRO_HOME` lives) is bound read-write inside the sandbox [I: it holds the result file, so it
is]; steering masked (F5 differs by venue); the FREE plan's 50 credits cover few units at the glm-5 cost measured here
(2.0–4.4 credits per red attempt; qwen3-coder-next 0.65–1.07), so prefer `deepseek-3.2` or `qwen3-coder-next` there.

## H2: dummy-agentic live through CI (2026-10-08; harness `0e4bcc8` vendored at dummy `6543c31`)

**Verdict: our SDD approach with Kiro works end to end: yes, with caveats.** kiro-cli authored a small spec headless.
In CI, as the only implementer and under bubblewrap, it implemented both required leaves in Kiro's wave order. The
independent judge passed all 6 criteria, the MR was handed off ready, I merged it as the human, and the sweep recorded
`merged` with nothing left to do. The `tasks.md` markers were changed at exactly the 4 expected bytes [V]. The
caveats, most important first:

1. **Two harness live-fixes were needed first, and both were checked live.**
   * H1 finding 3: the red rebuild of a new module now keeps its import sections and docstring (`3e1d56d` test,
     `bf7b63a` fix).
   * K20: a Kiro leaf's prompt now shows its `_Requirements:_` line and lists only the criteria that line names
     (`8b9be4c` test, `0e4bcc8` fix). The full suite then found a dry-run prompt-hash test that needed the same refs
     (`821fd7b`, not vendored on the dummy: the CI job runs no dry run).
2. **The judge was not Claude.** `claude` is not logged in for `gitlab-runner` (PRQ-15 `auth: claude — not logged
   in`; job 6146 `judges: claude-code skipped — auth: claude is not logged in`). The chain fell back to
   `magnitude-qwen`, the Qwen model on this Mac (`independence: declared (unverified): magnitude-qwen alibaba
   (declared), kiro zhipu (declared)`). The maintainer has to log in again. The login must never be copied.
3. **The sweep does not run the Kiro done-gate after a merge.** The merge detector only looks for
   `openspec/changes/<name>` (`ci/sweeper.py:670`, `postmerge.py` `MergeDetector`). A Kiro unit therefore reads as "the
   merged tree holds no change folder" and stops at `merged` without an archive step. The ledger never records
   `archived`, and the unit branch and lock ref are not retired. I ran the done-gate by hand on the merged tree with
   the vendored harness: it passes, and a copy with 1.1 reset is refused (below). Open (not fixed: no live-fix left).
4. **The spec is small on purpose.** The brief asked for 2 required leaves so the run fits the FREE plan. On H1's
   8-leaf spec shape (implementation leaves followed by test-only leaves), glm-5 still halts on the already-satisfied
   path: H1 re-run, task 2.2, three times.
5. **The model matters.** qwen3-coder-next (the cheapest) failed 2.1 red 3 times on H1 with live-fix 1 in, before
   K20. glm-5 passed, on the first attempt, every red step of a leaf that was not already implemented: H1 2.1, then
   2.1 and 1.1 in both the rehearsal and CI.
6. **FREE-tier throttling counts as a failed attempt.** 1.1 green attempt 1 ended `kiro-cli exited with code 1
   (runError at prompt)` with the stream reading `The request was throttled by the service`. The retry passed. A
   third throttle on the same step would have halted the unit, not cooled the profile (K7: throttling is not yet
   classified as a rate limit).
7. **The credit counts disagree.** The CI streams metered 10.72 credits. `/usage` as `gitlab-runner` went from 0.00 to
   **5.42 of 50**. On the PRO rehearsal the two matched (11.47 both). Cause [U]: a FREE-plan rate factor is possible
   [I].

| Step (task) | Result | Ids and quoted lines |
|---|---|---|
| 1 prereqs, kiro pin | **PASS** after a test-first `prereqs.sh` fix | Before: `[PRQ-12] MISSING Kiro CLI — kiro-cli 2.27.1 (pinned 2.28.0)` (the only MISSING row). First `--apply`: `[PRQ-12] FAILED … Do you want to replace it? (y/N): main: line 545: /dev/tty: No such device or address`: the installer prompts when a binary exists. Fix `d5e830a` (test) and `4c9d5bf`: an installed CLI runs `kiro-cli update --non-interactive`. Second `--apply`: `[PRQ-12] FIXED Kiro CLI — kiro-cli 2.27.1 (pinned 2.28.0) → kiro-cli 2.28.0`; check after: `summary: mode=check missing=0 failed=0 warnings=2` ([before](../../runner/prereqs-2026-10-08-kiro-h2-check-before.txt), [apply 1](../../runner/prereqs-2026-10-08-kiro-h2-apply.txt), [apply 2](../../runner/prereqs-2026-10-08-kiro-h2-apply-2.txt), [after](../../runner/prereqs-2026-10-08-kiro-h2-check-after.txt)) |
| 2 login as gitlab-runner | **PASS**, no wait | `whoami accountType: BuilderId`, `KIRO FREE`, `Credits (0.00 of 50 covered in plan)` before and after the update; PRQ-15 `auth: kiro-cli — logged in` ([before](h2/runner/kiro-state-before.txt), [after](h2/runner/kiro-state-after-apply.txt)). Only the account type was read: the e-mail was never printed |
| 3 push and CI | **PASS** | Push `7f4f454..6543c31` (seed `563d0d1`, steering `5a5e8f4`, config `dfe70cf`, upgrade `6543c31`), pipeline 3639, `l4` job **6146**: `implementer: kiro-badmodel skipped — hello: kiro-cli reported runError (prompt)`, `implementer: kiro ok (binary 2.28.0 · auth subscription · quota 0% used (credits) · hello 5.3s) → selected, fallback #1`, `task 2.1 red ok: 9 new test(s) failing as expected`, `task 2.1 green ok`, `task 1.1 red ok: 5 new test(s) failing as expected`, `1.1: green attempt 1 failed: … kiro-cli exited with code 1 (runError at prompt)`, `task 1.1 green ok`, `verdict PASS (round 1, 6/6 criteria pass, 1 finding(s))`, `MR !37 labels: l4:in_review`, `run finished: exit 0 in 856.3s`, `Job succeeded`. MR !37: `draft = False`, `detailed_merge_status = mergeable`, head pipeline 3654 success ([log](h2/ci/job-6146.log), [artefacts](../artifacts/job-6146/l4-out/)) |
| 4 human merge, done-gate | **PASS with a gap** | `PUT …/merge_requests/37/merge` → `state merged`, merge commit `b85a231`. Pipeline 3657, `l4` job **6155**: `sweeper: kiro:add-bulk-discount-h2: MR !37 merged`, plan row `kiro:add-bulk-discount-h2 merged 4/4 none merged`, `run: nothing to do`. Local `l4 plan --json` after: `'next_action': 'none', 'phase': 'merged'`, not actionable. No archive MR was opened, so there was no archive loop. The next sweep (job **6161**) logged `sweeper: kiro:add-bulk-discount-h2: kiro:add-bulk-discount-h2 is no longer under openspec/changes on the base branch` and `run: nothing to do`. Every later sweep repeats that one no-op line; it opens nothing and records nothing. The done-gate itself was not run by the sweep (caveat 3); by hand on `b85a231`: `done_gate passed: True`, and with 1.1 reset: `refused: … task 1.1 is not done` ([E](h2/ci/E-done-gate.txt), [6155](h2/ci/job-6155.log), [6161](h2/ci/job-6161.log)) |
| 5 failure path | **PASS**, 0 credits | Inside run 3: the chain `[kiro-badmodel, kiro]`, where `kiro-badmodel` pins a model kiro-cli refuses (rehearsed on the Mac first: [dry run](h2/prep/badmodel-dry-run.txt)). Its hello fails and the chain falls back to `kiro`. A `min_version` profile was not used because `doctor --ci --fix` would run the Kiro installer for an unmet floor (M1.2). Unplanned, but live: the throttle retry in caveat 6 |
| 6 restore | **PASS** | `b85a231..18ccc89 18ccc89 -> main` (06:27Z, after `l4_idle.py` reported idle); `[skip ci]`: pipeline 3712 `skipped`. `implementer: [f-muse, f-mimo, f-nemotron-ultra, f-longcat, magnitude-qwen, kiro, codex, claude-code]`; `l4 doctor` on it: `CFG-002 pass`. Free-first chain plus `kiro` after `magnitude-qwen`, before `codex`; `kiro-badmodel` dropped ([free-resources section 14](../../free-resources.md), [doctor](h2/push/restore-doctor.txt)) |

### Before the push: authoring, H1 re-run, Mac rehearsal

* **A, fresh spec** [V]. `kiro-cli chat --no-interactive --v3 --mode spec --model claude-sonnet-4.5 --trust-all-tools`
  with a brief that asks for 2 requirements, 2 required leaves, an optional `- [ ]* 2.2` and string task ids
  ([brief](h2/A/brief.txt)). Result: exit 0, `Create spec directory` plus 3 `Write File`, 0 denials, no MCP, nothing
  else touched. Kiro wrote the ids as strings when the brief said so (H1 needed a human fix). Kiro's own variants were
  accepted: `### Requirement 1: Bulk Discount Rule` and `1.1.` with a trailing dot. `l4 doctor`: `SPEC-002 pass` and
  `SPEC-004 pass`. The stream metered 0.00 credits (the v3 engine may not report it [I]). Seeded as a human commit
  with the bytes as written ([authored](h2/A/authored/)).
* **H1 re-run with live-fix 1 (`bf7b63a`)** on the halted `add-bulk-discount` ([prep/h1-rerun](h2/prep/h1-rerun/)):
  * kiro-qwen failed all 3 red attempts, each on a red check before the lint gate ran. Attempt 1: `new tests passed
    before implementation` (cart tests in a Requirement 1 task). Attempt 2: `no new test traces C-ab74596f` (Req 2.4).
    Attempt 3: `vacuous: C-4284227d` (a zero-value answer). Attempts 1 and 2 are K20. Cost: 1.85 credits.
  * After `l4 resume`, kiro-glm passed 2.1 red on its first attempt: `gate lint pass (exit 0)`, then `task 2.1 red
    ok: 13 new test(s) failing as expected`. The red commit `1222af5` keeps the module docstring and all three import
    sections, so finding 3 is verified in the real loop. `2.1 green ok` followed.
  * glm then halted on 2.2 ("Implement qualifies_for_bulk_discount()"), which 2.1's green had already implemented.
    Attempts 1 and 3: `tests not collected individually`. The real condition is no new test id with changed test
    files, so the message is misleading. Attempt 2: `test code changed production files while a gate ran …
    src/pricing/cart.py: added or changed by a gate run (pre-satisfied confirmation)`; this looks like a harness defect
    on the already-satisfied path [I, not investigated]. Attempt 2 alone cost 10.98 credits; the glm run cost 21.88.
    The 2.1 red also stubbed `cart.py` (K20), which shows how an over-reaching earlier leaf leads to this trap.
* **Mac rehearsal of the fresh spec** (harness `0e4bcc8`, kiro-glm, local bare origin, `sandbox: none`;
  [prep/rehearsal](h2/prep/rehearsal/)) [V]: `2.1 red ok`, `2.1 green ok`, `1.1 red ok`, `1.1 green ok`, each on the
  first attempt; Claude judge `verdict PASS (round 1, 6/6 criteria pass, 2 finding(s))`; `in_review`; `exit 0 in
  688.3s`; 11.47 credits (stream sum = `/usage` delta). The 2.1 prompt read `_Requirements: 1.1, 1.2, 1.3_` and
  listed only Req 1.x (K20 live). `tasks.md`: 4 offsets `' '→'x'`.
* Harness checks: the full suite at `0e4bcc8` gave 4873 passed, 80 skipped, 1 xfailed and **1 failed**
  (`test_kiro_dry_run_prompt_hash_equals_the_real_red_prompt_hash`, fixed by `821fd7b`; the parity and sim tests
  pass after it). The full suite at `821fd7b` (HEAD, with another workflow's `f0c703c`): 4879 passed, 80 skipped, 1 xfailed, 0 failed. `l4 simulate --all`: 5 pass, 0 fail, 16 pending, as before.

### F checks on H2 (base `6543c31`, merge `b85a231`; [F-checks.txt](h2/ci/F-checks.txt))

| Check | Result |
|---|---|
| F1 markers | **holds** [V]: `tasks.md` is 612 bytes before and after, and the only differing offsets are `(26, ' ', 'x'), (75, ' ', 'x'), (169, ' ', 'x'), (223, ' ', 'x')` (leaves 1.1 and 2.1 and both parents). No `-` or `~` was written (K9 open) |
| F2 optional | **holds**: `- [ ]* 2.2` is untouched, and no step or ledger event names 2.2 |
| F3 waves | **holds**: `task.started` order `['2.1', '1.1']`, while 1.1 comes first in the document |
| F4 traceability | **holds** (K20 live): `red_ok 2.1 cites ['Req 1.1', 'Req 1.2', 'Req 1.3']` and `red_ok 1.1 cites ['Req 2.1', 'Req 2.2', 'Req 2.3']`; `verification.md` 6/6 `pass`, each with a discriminating test |
| F5 steering | **masked under bwrap, as designed** [V]. In CI, no `(Req …)` docstring endings and no `__init__.py` change. On the sandbox-less rehearsal, the docstring ended `(Req 1.1, 1.2, 1.3)` and `calculate_bulk_discount` was exported in `__all__`. K10 (inject steering into the prompt) stays open, so the venue still decides whether steering applies |
| F6 protected | **holds**: `git diff 6543c31..b85a231 -- .kiro/steering …/requirements.md …/design.md` is empty; `guard.violation: []` |
| F7 isolation | **holds**: tool calls `{'read': 18, 'glob': 6, 'write': 11, 'shell': 18}`, MCP servers `[]`, 0 `[denied]` lines in 5 Kiro steps. K3 (`KIRO_HOME` in the step's private directory) and the K2 token-store bind worked under bwrap: the login was used inside the sandbox [V]. That another adapter's sandbox cannot read the token was not probed live [U; unit-tested] |

### Findings (new on H2)

* **Merge detector OpenSpec-only** (caveat 3) [V code + live]. Fix sketch: classify a Kiro unit by its own folder
  (`.kiro/specs/<name>` on the merged tree), run `KiroProvider.archive` (the done-gate) in the sweep, and record
  `archived` without an archive MR while `kiro.archive_dir` is null, then retire the lock ref.
* **Throttling is an attempt failure** (caveat 6) [V]: `runError` with `throttled by the service` should map to the
  rate-limit class (cool down, fall back) like a 429.
* **The runner's Claude login is gone** (caveat 2) [V]. A human must log in as `gitlab-runner`; it is never copied.
* `/usage` and the stream-metered credits disagree on FREE (caveat 7) [V both numbers].
* The installer's replace prompt needs a TTY (fixed in `prereqs.sh`, step 1).
* The H1 already-satisfied path: a misleading message and a suspicious pre-satisfied gate check (H1 re-run above)
  [V symptoms, I cause].
* The ledger records `step.finished … "task": "1.1", "phase": "green", "attempt": 1, "status": "ok"` for the attempt
  whose agent failed (`task.attempt_failed` is also there) [V]. That status means the step ended normally, not that
  it succeeded [I].

### Credits (Kiro FREE on the runner, 50/month)

`/usage` 0.00 before, **5.42** after job 6146; streams 10.72 (2.1 red 2.01, 2.1 green 1.52, 1.1 red 2.87, 1.1 green
1.45 throttled + 2.86). The Mac (PRO) went from 73.26 to 84.73 on the rehearsal, and from 48.76 to 73.26 across the H1
re-run (23.73 metered), the bad-model dry run and the authoring of the fresh spec.

## H3: the kiro-fu re-check, dummy-agentic live through CI (2026-10-08; harness `9bcfb9c` vendored at dummy `06b2366`)

**Verdict: our SDD approach with Kiro works end to end: yes, with fewer caveats than H2.** The four H2 follow-ups
(KF1 to KF4, merged as `6b5e17e`) behaved live as their tests say:

* **KF1:** the next sweep after the upgrade ran the done-gate on the H2 unit that had already merged. The merge sweep of
  a fresh unit ran merge detection and the done-gate together. Each recorded `archive.done` once, and later sweeps only
  say it is recorded.
* **KF2:** two FREE-tier throttles cooled `kiro` for 2 minutes and consumed no attempt.
* **KF3:** a leaf whose behaviour the previous leaf already provided was confirmed `already satisfied` on its first
  attempt, under bubblewrap, with no production change.
* **KF4:** the ledger carries `credits_source` on both readings and adds neither to `usd`.

What is still open, most important first:

1. **The lock ref and the unit branch are kept, not retired** [V]. This is by design (the kiro-fu merge log in
   [../../plan/parallel-ownership.md](../../plan/parallel-ownership.md), "Deviation from the brief"): the folder's own
   ledger ends at `in_review`, so the pending ledger on the lock ref is the only record that the unit merged. After the
   run, `refs/l4/locks/kiro/add-bulk-discount-h2` is at `27358c4` and `…/add-small-order-surcharge` at `5280f33`.
   There is no `refs/l4/archived/kiro/*`, and both `l4/kiro/*` branches still exist
   ([refs](h3/lockrefs-after-6222.txt), [branches](h3/unit-branches-after-merge.txt)).
2. **A throttle with a one-profile chain ends the job, and the run does not retry** [V]. The KF2 brief asked to "retry
   within the run if cheap". The harness instead stops with `waiting_capacity` (exit 12, an allowed failure) and leaves
   the step to the next pipeline. Here those were the 10:03 schedule (job 6213) and an API pipeline that I started as
   the human after the cool-down (job 6217); otherwise the wait is up to 30 minutes for a 2-minute cool-down. Falling
   through to a next implementer was not exercised live: the chain was `[kiro]` only, and `baf0820` covers it in tests.
   Fix sketch: when every cooling profile's `retry_after` is a few minutes away and the job's time budget allows, wait
   in the run and retry.
3. **The progress log misreads an already-satisfied leaf** [V log, V code]. Job 6213 printed `task 2.2 red ok: 1 new
   test(s) failing as expected` and `task 2.2 green ok: all tests passing`, but the test passed and no green step ran.
   The ledger is right (`criterion.pre_satisfied`, `proof: pre_satisfied`, `task.done{tdd: already-satisfied}`). The
   cause: `progress.py` `_red_ok` and `_done` ignore the proof and `tdd` fields.
4. **The judge was not Claude** [V]. The runner prereqs check said `[PRQ-15] INFO auth: claude — not logged in`, and job
   6217 said `judges: claude-code skipped — auth: claude is not logged in`, then `judges: magnitude-qwen ok (… hello
   29.0s) → selected, fallback #1`. The recorded independence is `declared (unverified): magnitude-qwen alibaba
   (declared), kiro zhipu (declared)`. A human must log in as `gitlab-runner`; the login is never copied.
5. **Throttling is frequent on FREE** [V]: 2 of 7 Kiro implementer steps (H2: 1 of 5). One throttle came mid-stream,
   after 11 tool calls, in 1.1 green, and that stream metered 0 credits. The next run started the green again (`red
   already committed: resuming at green`).
6. **`/usage` and the streams still disagree, by a steady factor** [V numbers, I cause]. Per job, `/usage` grew by 0.51,
   0.46 and 0.44 of the stream-metered credits; H2's ratio was 0.51. On the PRO Mac rehearsal (H2) the two matched.
   Both readings are now recorded with their source and never summed.
7. **The authoring brief matters** [V]. My first brief named the criteria `1.1`, `1.2`, …, and Kiro then wrote them as
   paragraphs `1.1. WHEN …` instead of a list `1.`. The harness then found no criterion, and doctor reported `SPEC-002
   … task 1.1 cites _Requirements: 2.1_, which no criterion has`. A second brief that asked for a numbered list fixed
   it, with no human edit ([A1](h3/A/A1/), [A1 doctor](h3/A/A1/raw-doctor.txt)). Kiro's own list form is `1.` [I], so
   this is a brief artefact more than a harness gap.

| Step | Result | Ids and quoted lines |
|---|---|---|
| 0 upgrade the vendored harness | **PASS** | Fresh SSH clone of `main` at `f285903`. `l4 upgrade --harness <harness at 9bcfb9c>`: `changed .l4/vendor/ (1 added, 36 changed, 0 removed) to the harness at 9bcfb9c8ccf3`. Local doctor exit 0, and `l4 plan --json` showed no actionable unit. Commit `06b2366` by CiprianSpot, pushed `f285903..06b2366` after `l4_idle.py` said `idle` ([upgrade](h3/upgrade-dummy.txt), [push](h3/push-upgrade.txt)) |
| 1 KF1 on the merged H2 unit (MR !37, `b85a231`) | **PASS** (done recorded); **lock ref not retired** (by design, caveat 1) | Pipeline 3727, `l4` job **6209**: `[l4] sweeper: kiro:add-bulk-discount-h2: the done-gate passed on 06b2366369; no archive MR (Kiro has no archive folder)`. The lock ref moved `48ab638` → `27358c4`, and its new pending ledger `r-20261008T0937Z-7fcd` holds `archive.done {'via': 'done_gate', 'base': '06b23663690060b04f0e97efbe27221ccace816c'}`. The phase stays `merged` and `run: nothing to do`. The H2 no-op line (`… is no longer under openspec/changes on the base branch`) is gone. Jobs 6211, 6213, 6217, 6220 and 6222 each logged `sweeper: kiro:add-bulk-discount-h2: the done-gate passed earlier (archive.done is recorded)` and wrote nothing (the ref stayed at `27358c4`) ([6209](h3/ci/job-6209.log), [pending ledger](h3/kf1/pending-r-20261008T0937Z-7fcd.jsonl), [refs before](h3/lockrefs-before-upgrade.txt) / [after](h3/lockrefs-after-upgrade.txt)) |
| 2a authoring by kiro-cli on the Mac | **PASS** on the second brief | `kiro-cli chat --no-interactive --v3 --mode spec --model claude-sonnet-4.5 --trust-all-tools --output-format stream-json "<brief>"` in a throwaway clone: exit 0, `{'Write File': 3}`, 0 `[denied]`, `runFinished success end_turn`. Unit `kiro:add-small-order-surcharge`: 2 requirements (3 + 2 EARS criteria), leaves 1.1, 2.1, **2.2** (`_Requirements: 1.3_`, 19.99 gives 2.00, which 2.1's rule "below 20.00 gives 2.00" already provides) and an optional `- [ ]* 2.3`, and the graph `{"waves": [{"id": 0, "tasks": ["2.1", "2.2", "2.3"]}, {"id": 1, "tasks": ["1.1"]}]}` with string ids. Raw doctor: `SPEC-002 pass 1 Kiro unit(s) validate`, `SPEC-004 pass … every leaf cites a requirement`. Seeded with the bytes as written as the human commit `f07721f`. The streams metered 0.00 credits; the Mac PRO `/usage` went from 84.73 to 86.09 for both briefs ([brief](h3/A/brief.txt), [stream](h3/A/A.stream.jsonl), [spec](h3/A/authored/)) |
| 2b config and push | **PASS** | `d4ee83a`: `roles.implementer: [kiro]` (`kiro`: `model: glm-5`, `vendor: zhipu`, unchanged since H2); judges unchanged (`[claude-code, magnitude-qwen, f-longcat, f-muse, codex]`). Before the push: doctor `CFG-002 pass`, and plan showed `kiro:add-small-order-surcharge` as the only actionable unit. The runner's `/usage` read **5.42 of 50**. Pushed `06b2366..d4ee83a` once `idle` ([plan](h3/prepush-plan.json), [doctor](h3/prepush-doctor.txt), [runner before](h3/runner/kiro-state-before.txt)) |
| 2c run to MR ready | **PASS** (3 jobs, 2 throttles) | Pipeline 3728, job **6211**: `implementer: kiro ok (binary 2.28.0 · auth subscription · quota 10.8% used (credits) · hello 17.5s) → selected`, `task 2.1 red ok: 4 new test(s) failing as expected`, `task 2.1 green ok`, `agent red task 2.2 rate_limited (106.1s): kiro-cli was throttled by the service (runError at prompt)`, `implementer: kiro skipped — cooling until 2026-10-08T10:01Z (rate_limit); no probe sent`, `waiting_capacity …`, `run finished: exit 12`. Scheduled pipeline 3735, job **6213**: `task 2.2 red ok: 1 new test(s) failing as expected` (caveat 3), `commit fe79e2ad5e test(add-small-order-surcharge): 2.2 already satisfied [skip ci]`, `task 1.1 red ok: 4 new test(s) failing as expected`, `agent green task 1.1 rate_limited (149.6s)`, exit 12. API pipeline 3743 (I started it after the cool-down), job **6217**: `task 1.1 red already committed: resuming at green`, `task 1.1 green ok`, `judges: magnitude-qwen ok … → selected, fallback #1`, `verdict PASS (round 1, 5/5 criteria pass, 0 finding(s))`, `MR !38 labels: l4:in_review`, `run finished: exit 0 in 380.9s`. MR !38: `draft False`, `detailed_merge_status mergeable`, head pipeline 3748 `success` ([6211](h3/ci/job-6211.log), [6213](h3/ci/job-6213.log), [6217](h3/ci/job-6217.log), [MR](h3/ci/mr38-before-merge.json), [verification.md](h3/ci/verification.md), artefacts [6211](../artifacts/job-6211/l4-out/), [6213](../artifacts/job-6213/l4-out/), [6217](../artifacts/job-6217/l4-out/)) |
| 2d KF2 live | **PASS** (cool-down, no attempt consumed); in-run retry **not done** (caveat 2) | In the unit's ledgers: `availability.limit {kind: rate_limit, source: kiro.run_error, excerpt: "… The request was throttled by the service (request_id: …)"}`, `availability.cooldown {profile: kiro, until: 2026-10-08T10:01:45Z, kind: rate_limit}` (2 min, the default; the message had no retry hint), and `phase.changed implementing → waiting_capacity (exit 12)`, then `waiting_capacity → implementing (capacity_restored)`. Over all three runs: no `task.attempt_failed` and no `breaker.tripped`; every retried step is attempt 1 ([ledgers](h3/ci/ledger/), [F-checks](h3/ci/F-checks.txt)) |
| 2e KF3 live | **PASS** | Run `r-20261008T1003Z-64eb`: `criterion.pre_satisfied {task: 2.2, criterion: C-ff8c6d6a, tests: [tests.test_surcharge.TestSmallOrderSurchargeBelowThreshold::test_subtotal_19_99_at_threshold_boundary_returns_2_00]}`, `task.red_ok … proof: pre_satisfied`, `task.done {tdd: already-satisfied}`. Commit `fe79e2a` (`L4-TDD: already-satisfied`) changes only `tests/test_surcharge.py` (+6, one new tagged test) and 2 bytes of `tasks.md`, plus its ledger: no production file. It ran under bubblewrap 0.6.1 on the first attempt. Neither H1 message was seen (`tests not collected individually`, `… changed production files while a gate ran … (pre-satisfied confirmation)`). The H1 trigger, a module reachable under two cases on APFS, cannot occur on the Linux runner [I], so that path was checked on the H1 state only ([commit](h3/ci/2.2-already-satisfied-commit.txt)) |
| 2f KF4 live | **PASS** | `budget.cost {credits: 4.364764, credits_source: kiro.stream, profile: kiro, task: 2.1}` and four more (sum 13.54, no `usd`). Probes: `availability.selected … probes.kiro {credits_used: 5.42 → 8.97 → 11.33, credits_included: 50.0, credits_source: kiro.usage}`. `verification.md`: `Cost: $0.0000`. The runner's `/usage` after the run: **11.99 of 50** (+6.57 against the streams' 13.54) ([runner after](h3/runner/kiro-state-after.txt), [streams](h3/ci/stream-summary.txt)) |
| 3 human merge, done-gate | **PASS** (done recorded); **lock ref and branch not retired** (by design) | `PUT …/merge_requests/38/merge` → `state merged`, merge commit `001c236`. Pipeline 3749, job **6220**: `[l4] sweeper: kiro:add-small-order-surcharge: MR !38 merged`, `[l4] sweeper: kiro:add-small-order-surcharge: the done-gate passed on 001c236fb7; no archive MR (Kiro has no archive folder)`, `run: nothing to do`. Pending ledger `r-20261008T1024Z-3001`: `phase.changed in_review → merged (pr_merged)`, `archive.done {'via': 'done_gate', 'base': '001c236fb702da33cb507465be0439811d4f1050'}`. No MR note was needed, because the gate passed. The scheduled job **6222** logged `the done-gate passed earlier (archive.done is recorded)` for both units and moved no ref. Local plan: `kiro:add-small-order-surcharge merged, tasks 5/5, not actionable` ([6220](h3/ci/job-6220.log), [6222](h3/ci/job-6222.log), [pending](h3/kf1/pending-add-small-order-surcharge.txt), [plan](h3/ci/plan-after-merge.json)) |
| 4 restore | **PASS** | `c120b9e` puts back the free-first `roles.implementer` line. `.l4/config.yaml` is byte-identical to the pre-H3 config (`cmp`), and doctor reports `CFG-002 pass`. Pushed `001c236..c120b9e` after `idle`; it is `[skip ci]`, so pipeline 3751 was `skipped` ([doctor](h3/restore-doctor.txt), [push](h3/restore-push.txt)) |

### F checks on H3 (base `d4ee83a`, merge `001c236`; [F-checks.txt](h3/ci/F-checks.txt))

| Check | Result |
|---|---|
| F1 markers | **holds** [V]: `tasks.md` is 693 bytes before and after, and the only differing offsets are `(26, ' ', 'x'), (69, ' ', 'x'), (175, ' ', 'x'), (218, ' ', 'x'), (338, ' ', 'x')`: the leaves 1.1, 2.1 and 2.2 and both parents. Parent 2 is closed while the optional 2.3 stays open, as in Kiro |
| F2 optional | **holds**: `- [ ]* 2.3` is untouched, and no ledger event names 2.3 |
| F3 waves | **holds**: `task.started` order `['2.1', '2.2', '2.2', '1.1', '1.1']` (each repeat is the resume after a throttle); 1.1 comes first in the document |
| F4 traceability | **holds**: proofs `2.1 {zero_value ×2}`, `2.2 {pre_satisfied}`, `1.1 {zero_value ×2}`; `verification.md` says `traceability: 5/5 criteria covered by a discriminating test` |
| F5 steering | **masked under bwrap, as in H2** [V]: `surcharge.py`'s docstring has no `(Req …)` ending, and `src/pricing/__init__.py` is not among the changed files (K10 open) |
| F6 protected | **holds**: `git diff d4ee83a 001c236 -- .kiro/steering …/requirements.md …/design.md` is empty; `guard.violation: []` |
| F7 isolation | **holds**: tool calls `{'read': 30, 'glob': 5, 'shell': 27, 'write': 15, 'grep': 1}`, MCP servers `[]`, 0 `[denied]` in 7 Kiro implementer streams |

### Credits (Kiro FREE on the runner, 50/month)

`/usage` 5.42 before, 8.97 after job 6211, 11.33 after job 6213 (the probe readings in the ledger) and **11.99** after the
run. The streams metered 13.54: 2.1 red 4.36, 2.1 green 2.54, 2.2 red 0.00 (throttled at the prompt) then 1.68, 1.1 red
3.45, and 1.1 green 0.00 (throttled after 11 tool calls) then 1.51. The authoring on the Mac (PRO) cost 1.36
(84.73 → 86.09) for two briefs. Runner checks before the run: `[PRQ-12] OK Kiro CLI — kiro-cli 2.28.0 (pinned 2.28.0)`
and `summary: mode=check missing=0 failed=0 warnings=2` ([prereqs](h3/runner/prereqs-check-before.txt)). Evidence
was collected with [h3collect.py](h3/h3collect.py) (ANSI stripped, e-mails redacted, token shapes refused: 0 found).
