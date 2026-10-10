# 08 — "Understanding Harness Engineering" (@techNmak): what it means for the L4 harness

**Source.** PDF "Understanding Harness Engineering", @techNmak, 48 pp. (Special Topic, Understanding AI Series), references checked October 2026. Google Drive: https://drive.google.com/file/d/1PT-P2PVoiZpfYoe5eWks1_DGt2aSvbDh/view. Sections are cited as §N.

**Basis.** This document is a synthesis of four read-only audits plus one skeptical re-check. The audits are context/tools/provenance, sandbox/credentials/approval, control/recovery/concurrency, and verification/evaluation. The re-check is the "challenge". The harness is at `main` `8ff9fee`; `src/` has not changed since `2a68eff`, the commit the audits used.

- **Re-verified for this document:**
  - `verifier/ladder.py:374`, `:423`, `:954`, `:988`
  - `security/protected.py:23-31`
  - `sandbox/bwrap.py:23-27` and `build_argv`
  - `docs/runner/ci-probe-2026-10-03-pipeline-2525.txt:26`
  - `scripts/forge/gitlab_bot_token.py:97`, `scripts/forge/gitlab_ci_var_from_mintkey.py:55`
  - `orchestrator.py:14-20`, `:838-840`, `:893-897`
  - `outcome.py:39-53`, `:140-166`
  - `exitcodes.py:14-23`
  - `agents/opencode.py:78-96`, `:222-232`; `agents/codex.py:185-197`; `agents/kiro_cli.py:65-77`
  - `forge/gitlab.py:99-117`
  - SPEC L4-VER-009 (`docs/SPEC.md:1603-1617`), L4-VER-010 (`:1619-1620`), `budgets` (`:450-456`)
  - the Claude 2.1.288 recorded `init` events
  - live prompt sizes, template versions and stream greps in `docs/live/artifacts`
  - greps: `permission_denials`, `tool_rejected`, `secret_scan`, `SANDBOX`, `consecutive`, `CI_RUNNER_ID`, `max_turns` (all checked under `src/l4`)
- Every other [V] keeps the file:line citation of the audit or challenge that verified it.

**Labels.**

| Label | Meaning |
|---|---|
| [V] | Verified in code, docs or live data (file:line) |
| [I] | Inferred |
| [U] | Unknown |
| [D] | Taken from a cited source that was not reopened here |

**Basis tags.**

| Tag | Meaning |
|---|---|
| **OBS** | Seen in L4 live data or runner probes |
| **SPEC** | The code does not do what L4's own SPEC requires |
| **HB** | Justified only by the handbook or the vendor posts it cites |

**Lesson ids.** This document uses `HB-n` (adopt now) and `HB-Xn` (experiment). research/07 ids (A1, A2, E1, N1–N8) and adoption-analysis ids (H15, H18, H19, C1–C9) keep their original names.

---

## 0. Verdict

1. **The core of the handbook is already in L4:**
   - Verification is separate from self-report, and the judge can only block (§25–§28).
   - Each step gets fresh context, backed by a durable ledger (§14, §17).
   - Spec data is wrapped as `<l4:data>` (§22).
   - Every git side effect survives a crash (§30).
2. **Three high-damage gaps, each cheap to close:**
   - (a) The runner user is in the `docker` group, and the bwrap sandbox does not hide `/run`. Group: [V]. Socket reachable from inside: [I], the probe has not been run.
   - (b) The harness secrets are unscoped CI variables, so the project's own `test` job can read them. It runs agent-written code [I].
   - (c) The verifier reads its "base" specs from the unit's own worktree. An agent edit to `openspec/specs/**` therefore turns tests that never had a red proof into pass-to-pass evidence. This diverges from SPEC L4-VER-009 [V chain; that an agent actually does it is I].
3. **The largest structural gap is the missing evaluation loop for the harness itself** (§16, §37, §39). Template, CLI and model bumps are never measured before they ship.
4. **Skill-induced and auto-loaded-instruction risk (§13, §40) is real mainly for Codex**, which runs most live implementer steps. It has not been measured, so it is an experiment, not an adopt-now item.
5. **Main risk in this document:** item 2(a) rests on an unrun probe, and 2(b) has three [U] facts about GitLab CE and the runner.

## 1. What the handbook is, and what it is not

- **It is a conceptual systems handbook.** It has 43 sections over 48 pages. It defines an "agent harness" (runtime control around the model) and "harness engineering" (the wider discipline). It says itself: "This is an editorial taxonomy for this handbook, not an industry-standard definition" (orientation, p.2).
- **It is vendor-sourced.** Of its 26 references:

  | Source | Count |
  |---|---|
  | Anthropic engineering posts or docs | 11 |
  | OpenAI | 3 |
  | Microsoft | 2 |
  | Google | 2 |
  | MCP spec | 1 |
  | IETF RFC 9110 | 1 |
  | Academic papers (ReAct, SWE-agent, AgentDojo, τ-bench, ToolSandbox, the skill-failure preprint arXiv:2608.11888) | 6 |

- **It contains no new experiments.** Every number is quoted from a source:
  - the 3 % eval drop from one system-prompt line (§16)
  - the 6-point Terminal-Bench resource effect (§38)
  - 307 skill-induced failures (§13)
  - the $9 vs $200 RetroForge runs (§39)

  It labels its formulas as "conceptual notation" (§24, §37).
- **How it is used here:**
  - As a checklist: the §42 questions, the §40 failure modes and the §41 misconceptions.
  - As a lens for priority: a gap that only the handbook justifies (basis HB) ranks below one seen live (OBS) or one that breaks L4's own SPEC.
- **How it differs from research/07** (arXiv 2609.00006):
  - research/07 surveyed agent-CLI internals. This handbook is one level up: control plane, containment, recovery, evaluation.
  - research/07 items are not repeated. A1 and A1b have landed (`ad69ca9`). A2 (per-step caps) is still open [V `implementer/tdd.py:341-348`: no `max_turns`]. E1 is extended by HB-X1.

## 2. The 15 production questions (§42) answered for L4

These are corrected from the verification audit; the corrections are in section 7.

| # | Question | L4 answer | Evidence | Weak spot |
|---|---|---|---|---|
| 1 | What does the model receive? | Implementer: contract + phase template + `<l4:data>` sources (budget-bounded) + answers + lessons + previous failure + result schema. All redacted, hashed and published. Judge: sources + diff (truncated with a note). | [V `tdd.py:298-339`, `verifier/judge.py:164-174`] | Whatever the CLI auto-loads (repo `AGENTS.md` for Codex [D/I] and Kiro [V research/01]) is neither controlled nor recorded. The judge prompt is not published; only its sha256 is kept [V `ladder.py:954,988`; `agent_judge.py:140` default False] |
| 2 | Who controls the loop? | Deterministic Python: orchestrator, planner, aggregation (architecture P1). Each vendor CLI runs its own inner turn loop. | [V] | No turn, token or cost cap is sent to the implementer CLI (research/07 A2) [V] |
| 3 | What actions are available? | `PermissionPolicy` modes `implement`, `read_only`, `judge`. Claude implementer: 6 tools plus StructuredOutput. OpenCode: an explicit allow-list. Codex: shell inside `workspace-write`. MCP: Serena, Playwright. | [V `base.py:65-70`; `claude_code.py:36,128`; recorded init `red-ok.jsonl`; `opencode.py:82-87`; `codex.py:188`] | The Codex judge has a read-only **shell** [V `codex.py:188-197`]. OpenCode sets no `skill`/`task` key, and both default to allow [D research/02:159] |
| 4 | Where do actions execute? | bwrap on shell runner `l4-runner`: `--ro-bind / /`, tmpfs `/tmp`, PID/IPC namespaces, `--clearenv`, `.git` read-only. Gates run in their own sandbox. | [V `bwrap.py:23-27`, `build_argv`] | Real HOME with a deny-list [V `workbench.py:509`, `sandbox/base.py:96-110`]. Agents always share the host network [V `build_argv`: `network=spec.network or spec.kind == "agent"`]. The runner user is in the `docker` group [V ci-probe:26] |
| 5 | What survives a crash? | The JSONL ledger, committed on the unit branch (in a lock ref while in review); pushed commits with `L4-Step` trailers; local WIP snapshots. | [V `state/reconcile.py:62-73`; `vcs/wip.py:1-5`] | WIP refs are local, so a different runner restarts the step. Control events after the last commit (`budget.cost`, `agent.session`) are dropped [V `reconcile.py:76-90`]. There is no SIGTERM handler [V grep] |
| 6 | Which rules are enforced mechanically? | Protected-path revert; red must fail and green must pass; frozen red tests; vacuity; schema-validated results; judge independence; `max_task_attempts` breaker; fast-forward-only pushes. | [V `protected.py:220`, `loop.py:78-120`, `selection.py:175`] | Not enforced: `budgets.*`, `max_turns`, `panel.pass_k`, `flaky_repeats`, and `secret_scan: gitleaks` (only reference: `config/schema.py:373`) [V grep] |
| 7 | How are errors represented? | `RunResult.status` (10 values). A limit leads to fallback or cool-down; other failures become a `previous_failure` data block. Exit codes 0/1/2/3/10–14. Human escalation through `questions.md`. | [V `base.py:17`, `tdd.py:366-372`, `exitcodes.py:14-23`] | `exit_reason` is set only for a base conflict [V `orchestrator.py:580`]. A refused push becomes exit 1 [V `pushfail.py:55-63`] |
| 8 | Which actions are safe to retry? | Steps are reconciled by the `L4-Step` trailer `<task>/<phase>/<attempt>`. Pushes are fast-forward only. MR: find before create. Labels by diff. Pending ledger and lock-ref retire use a CAS lease. | [V `vcs/trailers.py:23`, `reconcile.py:62-73`, `vcs/push.py:32-42,72-86`, `forge/gitlab.py:183-190`] | `idempotency.step_key` is unused [V grep]. Unit-branch pushes have no lease and no fencing. Forge POSTs are retried blindly on transport errors and 5xx [V `gitlab.py:99-117`] |
| 9 | How does the agent get ground truth? | It runs the gate command in its sandbox. The harness re-runs the gates and JUnit after every step and returns failures in the retry prompt. | [V `loop.py`, `tdd.py:298-311`] | The e2e trace wiring (`verifier/e2e_trace.py`) is [U] |
| 10 | What proves completion? | A deterministic aggregate over harness-run gates, red-before-green history, discriminating traceability, a judge that can only block (`fail` becomes `needs_human`) and human verdicts. A human merges. | [V `aggregate.py:12-15,77-87`] | The traceability baseline can be moved by the agent (HB-3) |
| 11 | How does the run stop if it never succeeds? | `max_task_attempts` 3 → breaker → exit 13; `max_fix_rounds` → escalated. Agent timeout 1800 s, stall 600 s, judge `--max-turns 3`, judge `MAX_CALLS`, CI job 180 min. | [V `loop.py:117-119`, `fixloop.py:403-415`, `base.py:152`, `tdd.py:65`, `l4.gitlab-ci.yml:17`] | No implementer turn, token or cost cap. No cross-run breaker, although SPEC L4-VER-010 requires one [V grep `consecutive`: none] |
| 12 | What happens after interruption? | Level-triggered re-entry. If the trailer exists, the step is finished; otherwise the WIP snapshot is restored; otherwise the step re-runs (L4-STA-003). The simulate scenario `crash-mid-task-resume` is ready. | [V `reconcile.py`, `sim/builtin/scenarios/crash-mid-task-resume.yaml`] | Same runner only. A cancel or timeout kills the job without `close()` |
| 13 | Can untrusted observations carry instructions? | Mitigated: `<l4:data>` + defuse + `_require_wrapped`; "only this prompt instructs you"; guidance files protected; tool-less judge calls start in an empty cwd for Claude, Codex and OpenCode. | [V `prompt.py:72-89`, `contract.md:4`, `protected.py:23-31`, `test_judge_cwd.py`] | The Kiro judge runs in the worktree [V `kiro_cli.py:72-76`]. What each CLI auto-loads (repo `AGENTS.md`, skill directories) is [U] per pin. Serena's `initial_prompt` embeds lessons unwrapped (0 live exposure) |
| 14 | How are subagents coordinated? | No fan-out: one task per invocation (AD-06). Units run sequentially within a run; across runs, `resource_group: l4` plus a per-runner `flock`. | [V `orchestrator.py:893-897`, `l4.gitlab-ci.yml:15`, `vcs/locks.py:31-63`] | The remote lease is M2 [V `locks.py:1-6`]. One unit's exception stops later units [V `orchestrator.py:838-840`]. In-CLI subagents: Claude blocked; OpenCode `task` default allow [D]; Codex collab [U] |
| 15 | How is the harness evaluated? | About 3,121 unit and contract tests; `l4 simulate` (5 of 21 scenarios ready); single-trial live protocols graded by read-only acceptance code; a real evaluation loop for S1 only (`l4 s1 …`). | [V `sim/builtin/manifest.py`; `src/l4/s1/*`] | No implementer, judge or clarifier eval set; no repeated trials; no ablations; no harness CI [V] |

## 3. The 13 failure modes (§40) mapped to L4 detection

| Failure mode (§40) | Where L4 detects it | Status | Fix |
|---|---|---|---|
| Tool selection | Raw streams are published but nothing classifies them. Codex `--json` omits denied calls (SPEC §8.3) | **Invisible** [V] | HB-6 (Codex `Rejected(` lines) |
| Tool contract | OpenCode **blocking** denials become `permission_blocked` with the tools named in `detail`, and reach the retry reason [V `opencode.py:229-232`]. Claude `permission_denials` and non-blocking denials are parsed and dropped. `agent.tool_rejected` is never emitted [V grep] | **Partial** | HB-6 |
| Observation | Inside the CLI: invisible. For the harness's own feedback: only after the fact, from repeated `task.attempt_failed.reason` and then `breaker.tripped` (live job 5498, fixed in `ba54759`) | **Indirect** [V] | HB-X5 |
| Context | `prompt.rendered` logs sources, lessons and answers, but not truncation. The live `a1a0ca3` 600-character cut dropped a human decision and was seen only because Codex reported `blocked` | **Indirect** [V] | note (truncation field) |
| State | `state.json` is a pure fold over the ledger [V `state/fold.py:1,214`]; `l4 status --rebuild`; doctor STATE-001. The live `69ef5b4` dropped reject was found in a rehearsal | **Observable** | — |
| Environment | Doctor ENV-*, PRV-*; `exit_reason`. The live `12cc820` "Committer identity unknown" showed as exit 1 `internal_error`. No SANDBOX-001 check exists [V grep]. Runner resources are not recorded | **Partly observable** | HB-10, HB-15 |
| Verification | Red/green gates, the ladder, `verdict.json`, `verification.md` | **Observable**, strong [V]; one bypass | HB-3 |
| Authorization | `guard.violation`, `guard.test_tamper`, `permission_blocked`, exit 12 when nothing usable remains. Over-authority (docker group, real HOME) has no detector | **Partial** | HB-1, HB-15, HB-16 |
| Recovery | `step.started` without `step.finished` → `reconcile`; trailers; `lock.stolen`. Duplicate forge POSTs go undetected | **Observable** except the forge | HB-12 |
| Coordination | `base.merged`, `base.conflict` (M1.7); lock events. No harness subagents | **Observable** / N/A | HB-7 |
| Budget | `breaker.tripped{max_task_attempts}`, exit 13, timeout and stall statuses; `budget.cost` recorded but not enforced | **Observable, not enforced** | research/07 A2, HB-9 |
| Provenance / injection | Guard reverts of planted guidance files; `<l4:data>`; recorded fixture `red-injection-in-spec-ignored.jsonl`. A model that obeys an injection without touching a protected path is invisible | **Partial** | HB-3, HB-13, HB-X1 |
| Skill-induced | Lesson ids in `prompt.rendered.lessons` [V `tdd.py:320`] allow attribution. Repository skills loaded by the CLI are neither recorded nor measured | **Attributable for lessons; invisible for repo skills** | HB-X1, HB-X3 |

## 4. Ranked lessons to apply

Only the items that survived the challenge are listed here. Ranking is by risk reduction divided by cost.

### 4.1 Adopt now

**HB-1. Remove the container-daemon path (§19, §21).** OBS.
- **Status: GAP.**
  - The CI job runs with `groups=…,999(docker)` [V `docs/runner/ci-probe-2026-10-03-pipeline-2525.txt:26`].
  - bwrap uses `--ro-bind / /` with no `/run` mask [V `bwrap.py:23-27`].
  - A read-only bind does not block `connect()` on a unix socket, so `/var/run/docker.sock` is reachable [I].
  - From there, `docker run -v /:/host` gives root on the runner. Root can read all logins, `/proc/<harness>/environ` and `/etc/gitlab-runner/config.toml` [I].
  - `docs/runner/README.md:143-145` ("never mounts the docker socket") and PRQ-16 (`prereqs.sh:230`) are literally true but miss this.
- **Change:**
  - Human: `sudo gpasswd -d gitlab-runner docker`, then restart the gitlab-runner service. The running service keeps its groups until restarted.
  - Fix the README and PRQ-16 wording.
  - Later and separately (defense in depth): `--tmpfs /run` plus `--ro-bind-try /run/systemd/resolve …` in `base_flags`. The resolver rebind is needed because Ubuntu's `resolv.conf` points into `/run`. Mirror the change in `scripts/runner/sandbox-probe.sh`.
- **SPEC:** L4-SEC-005; SCN-SPK-02 asserts the socket is absent but nothing checks it.
- **Validate:** live and read-only, inside the exact gate argv: open `AF_UNIX` to `/var/run/docker.sock` and send `GET /_ping`. Also run it under `--unshare-net`. Expect success before the fix [I] and ENOENT or EACCES after.

**HB-2. Scope the harness secrets to the `l4` job (§21).** OBS.
- **Status: GAP.**
  - `L4_FORGE_TOKEN` and `TYPESAFE_API_KEY` are created `masked: True, protected: False` with no environment scope [V `gitlab_bot_token.py:97`, `gitlab_ci_var_from_mintkey.py:55`].
  - The hand-off commit runs the project's own `test` job [V `docs/live/README.md:16`]. That job has both variables in its environment [I: GitLab variable semantics].
  - Making them `protected` would not help: it would expose them to every job on protected `l4/*` branches.
- **Change:**
  - `environment: {name: l4, action: prepare}` on the `l4` job in `src/l4/ci/templates/l4.gitlab-ci.yml`.
  - `environment_scope: "l4"` in both scripts.
  - A doctor CI check that the scope is not `*`.
  - Set `run_untagged: false` on runner 12 [U current value].
  - Rotate `L4_FORGE_TOKEN` (the existing README:148-152 item).
- **SPEC:** extend L4-SEC-001 to cover "no other CI job of the project". New scenario: SCN-SEC "project test job cannot read harness secrets".
- **Validate:** live on dummy-agentic, a presence-only probe job on `l4/**`: `[ -n "$L4_FORGE_TOKEN" ] && echo PRESENT || echo ABSENT`. Expect PRESENT before, ABSENT after. The `l4` job still passes CI-001 and pushes.
- **Unknowns:**
  - Whether CE 17.5 offers environment scopes [U]. Check in the Variables UI, not through the variables API, which returns values.
  - Which runner executes the hand-off `test` job [U].

**HB-3. Read the verifier baseline from the base tree, and protect the whole spec root (§25, §22).** SPEC.
- **Status: GAP. The chain:**
  1. `archived = base_criteria(wb.worktree / "openspec" / "specs")` [V `ladder.py:374`]. The verifier worktree is at unit head [I, strongly implied: the same ladder computes `scope_evidence(wb, base_sha, result.head_sha, …)` at `:423`].
  2. Unit and base criteria hash to the same ids [V `specs/criteria.py:93,215`].
  3. An unchanged criterion is accepted as `PASS_TO_PASS` [V `traceability.py:54-57,99`].
  4. `openspec/specs/**` and `openspec/changes/archive/**` are not protected [V `protected.py:23-31`].
  5. Agent edits are committed with `add -A` [V `tdd.py:557`].
  6. The scope check exempts `**/*.md` [V `config/defaults.py:22`, `evidence/scope.py:228`].
  7. New passing tests in green are allowed [V `tdd.py:178-198`].
  - **Result:** copy the delta into the main specs (OpenSpec `sync` or `archive`, or by hand), add a tagged test in green with no red proof, and the criterion leaves the audit pool as pass-to-pass.
  - SPEC L4-VER-009 defines the baseline as "the unit's base tree — the merge-base for a parent unit" and accepts pass-to-pass only for "text unchanged from the base specs" [V `SPEC.md:1603-1614`].
- **Change:**
  - (a) Read base criteria from the base tree (`show_blob` at `base_sha`; for a fix unit, the parent head) in `verifier/ladder.py:374`.
  - (b) Add the spec root as `ProtectedSet` globs (`openspec/**` minus the unit's run-ledger exception, and `.kiro/specs/**`). This also covers adoption H18 (new sibling change directories) and the archive directory.
- **SPEC:** L4-VER-009, L4-SEC-004, L4-IMP-006(1), L4-IMP-004 contract bullet.
- **Validate:**
  - Unit test: a criterion that exists only at head is not pass-to-pass; plus a protection-match test.
  - Simulate: a fake implementer copies its delta into `openspec/specs` and adds a tagged test in green. Expect `guard.violation`, and the test ignored as "no proof".
- **Land this before onboarding sample-consumer** (section 6).

**HB-4. Scan every outgoing diff for secrets before push (§21).** SPEC.
- **Status: GAP.**
  - `secret_scan: gitleaks` is configured, but `config/schema.py:373` is its only reference [V grep].
  - gitleaks is missing on the runner [V `inspect-2026-10-03-before.txt:66`].
  - Checkpoints are pushed before verification [V `docs/live/README.md:16`].
- **Change:** before every push, run the existing `Redactor` (known values plus `TOKEN_SHAPES` covering `glpat-`, `sk-ant-` and JWT [V `redact.py:11-26`]) over `git diff <remote>..HEAD` in `vcs/git.py` push or the forge hook. On a hit, block the push and emit `guard.secret` with the path and kind, never the value.
- **SPEC:** a new L4-SEC requirement. SCN-SEC-04 moves from verifier step 1 to pre-push.
- **Validate:**
  - Unit: a committed `sk-ant-…` string blocks the push.
  - Simulate: the fake agent writes a token-shaped value.

**HB-5. Publish the judge and audit-writer prompts (§34, §42 Q1).** OBS.
- **Status: GAP.** `ladder.py:954,988` call `workbench_request_factory` without `publish_prompts`, which defaults to False [V `agent_judge.py:140`]. The clarifier passes True [V `clarifier.py:399`]. The M1.4 notes had to infer what the judge saw.
- **Change:** pass `publish_prompts=True` at both call sites. The prompt is already redacted [V `verifier/judge.py:185`]. This is a prerequisite for judge replay (HB-X8).
- **Validate:** unit test that the written `.prompt.md` sha256 equals `verdict.json` `prompt_sha256`; then check the next live job's artifacts.

**HB-6. Record tool denials (§36, §40 tool-contract).** SPEC.
- **Status: PARTIAL.**
  - `permission_denials` are parsed [V `claude_code.py:252-253`, `opencode.py:217`] and used nowhere outside `agents/` [V grep].
  - `agent.tool_rejected`, required by L4-STA-001 and §8.3, is never emitted [V grep].
  - OpenCode blocking denials already reach `detail` [V `opencode.py:229-232`].
- **Change:**
  - Add `denials: [tool]` and a count to `agent.finished` (`tdd.py:359-362`).
  - Parse Codex stderr `Rejected(` lines into `agent.tool_rejected` (SPEC §8.3).
  - A retry-prompt line is only a note: the model already saw the denial within its own turn.
- **Validate:** contract test replaying `tests/fixtures/recorded/claude-code/2.1.288/perm-dontask-denials.jsonl`.

**HB-7. One failing unit must not stop the run (§32).** SPEC.
- **Status: GAP.**
  - `run_unit_in_worktree` re-raises [V `orchestrator.py:838-840`].
  - Units run in one list comprehension [V `:893-897`].
  - `run_guarded` returns `CommandResult(code)` with no units, so `outcome.json` loses the units that finished [V `outcome.py:140-166`].
- **Change:** catch per unit, `classify_exception`, set `exit_reason`, continue, then `most_severe`.
- **SPEC:** L4-CLI-001, L4-CLI-002.
- **Validate:** simulate two units where the first raises. The second still runs and `outcome.json` lists both.

**HB-8. Say why the run stopped (§23).** SPEC + HB.
- **Status: PARTIAL, smaller than the control audit said.**
  - `phase_after` already separates halted, escalated and awaiting [V `outcome.py:39-53`].
  - The halt reason is logged but not exported: `exit_reason` is set only for a base conflict [V `orchestrator.py:580`].
  - Lock-busy returns 0 [V `:774-777`]. A refused push is exit 1 [V `pushfail.py:55-63`].
- **Change:** set `exit_reason` in `_halt`, on escalation, in `_busy`, and for `PushFailed(refused)`. Correct the hint for a human push (`pushfail.py:49-54`): "a human pushed; the next run continues from it".
- **Validate:** unit test of `outcome.json` for each halt cause.

**HB-9. Implement the L4-VER-010 breaker (§24).** SPEC.
- **Status: GAP.** The SPEC says 3 consecutive internal verifier errors lead to `escalated` [V `SPEC.md:1619-1620`]. No counter exists [V grep `consecutive`].
- **Change:** count from the unit's committed ledger, `verifying` phase only, as the SPEC says. Extending it to every phase (e.g. push-refused) is an experiment: GitLab push rules are a Premium feature, so a refused push on CE is unlikely [I].
- **Validate:** simulate a verifier that raises in 3 runs in a row. Expect `escalated` and no 4th judge call.

**HB-10. Minimal environment record (§38).** SPEC.
- **Status: GAP.**
  - `run.started` has no runner id, which L4-STA-001 requires [V `SPEC.md:1867`; `CI_RUNNER_ID` appears nowhere in `src/l4`].
  - `agent.finished.model` is null on every live Codex and OpenCode step [V].
  - `verdict.json` lacks the judge template and the harness commit [V `verifier/report.py:225-262`].
- **Change:**
  - Add `CI_RUNNER_ID`/description and the bwrap, git, Python and selected CLI versions to `run.started` (`state/ledger.py:174`).
  - Add `template` and `harness_commit` to `verdict.json`.
  - The full CPU, memory and cgroup block is a note: there is one runner.
- **SPEC:** L4-STA-001, L4-VER-005.
- **Validate:** unit test, then the next live `run.started`.

**HB-11. Template lock (§16, §35).** HB (§16 case study).
- **Status: GAP.**
  - The `version:` line is bumped by hand [V `implementer/prompt.py:28`].
  - Tests assert only version strings [V `tests/unit/implementer/test_prompt.py:44-50`, `tests/unit/clarifier/test_context.py:143`, `tests/unit/verifier/test_prompt.py:45`].
  - The harness has no CI and no hooks [V].
  - Templates churned quickly: contract went from version 1 to 5 and red from 1 to 4 within about 35 hours [V git history].
- **Change:** `tests/unit/test_template_lock.py` plus `src/l4/templates.lock.json` pinning the body sha256 to the version, for the implementer templates and the judge and clarifier `PROMPT_VERSION` plus their system text. Add an `eval:` field only once HB-X8 exists.
- **SPEC:** §20, a new item.
- **Validate:** unit test that edits a temp copy without a version bump and expects failure.

**HB-12. Make forge POST retries read before they retry (§31).** HB. Low impact.
- **Status: GAP.** POST is retried on any `TransportError` and on 5xx, exactly like GET [V `gitlab.py:99-117`, `github.py:122-138`]. A lost response then yields a duplicate sticky note that nothing removes [V `gitlab.py:232-252`]. A duplicate MR is refused by the server [I].
- **Change:** retry a POST blindly only on connect errors or 429. On a read timeout or 5xx, re-read first (`find_pr`, list notes by marker, `get_pr`).
- **SPEC:** L4-ARC-002 clause.
- **Validate:** `MockTransport` that creates the note and then raises `ReadTimeout`; assert exactly one note.

**HB-13. Kiro judge in an empty directory (§22).** HB. Low impact.
- **Status: GAP, never run live.** The Kiro judge runs in `req.cwd` [V `kiro_cli.py:65-77`]. It is missing from `tests/unit/agents/test_judge_cwd.py`. It can be configured as judge [V `factory.py:167`].
- **Change:** use `judge_workdir` and `wrap_command` as Codex does.
- **Validate:** add kiro to `test_judge_cwd.py`.

**HB-14. Fix documentation that claims guarantees the code does not give (§34).** OBS.
- **Status: drift [V].**
  - `docs/architecture.md:260-262` and `:565` describe the step key, the CAS lease and fencing as current. They are M2 [V `vcs/locks.py:1-6`, `vcs/trailers.py:23`].
  - `docs/architecture.md:649` (R9) says SANDBOX-001 "fails closed", but it is not registered [V grep].
  - `docs/research/07…:81` says ENV-009 is checked, but it is not registered [V grep].
  - The `docs/eval-framework.md` status line is stale: it still says M0+M1.1.
  - eval-framework §3.2 omits the unread keys `ci.time_budget`, `ci.soft_deadline_margin`, `ci.max_parallel_units`, `ci.continuation` and `locks.lease` [V challenge].
  - `docs/runner/README.md:143-145` (see HB-1).
- **Change:** mark these as M2 or not built, and fix the claims.
- **Validate:** read-through.

**HB-15. SANDBOX-001 with real canaries (§19, §20). Adopt after HB-1.** SPEC.
- **Status: GAP, already planned** (sandbox-security tasks 1.12–1.13). No M0 canary evidence exists in `docs/runner` or `docs/live` [V].
- **Change:**
  - First, add to `scripts/runner/sandbox-probe.sh`: a container-socket connect check, a planted home file outside `CREDENTIAL_PATHS`, origin URL userinfo, the hidden runner `.tmp`, and a TCP connect under `gates.network: none`. Run it live.
  - Then build `src/l4/sandbox/probe.py` and `src/l4/doctor/checks_sandbox.py`, failing closed with exit 3.
- **Validate:** a live probe log saved in `docs/runner`; unit tests with a fake runner.

**HB-16. Empty HOME for both sandbox kinds (§18, §21). Planned (M).** SPEC.
- **Status: PARTIAL.** Gates use the real HOME with a deny-list [V `workbench.py:509`, `sandbox/base.py:96-110`]. The agent sandbox sees the same home with network on. Fixing gates alone therefore gains little; this corrects the sandbox audit's C5.
- **Change:** `--tmpfs $HOME` first in the argv, then explicit binds for the tools, as SPEC L4-SEC-005 says. Depends on sandbox-security 1.8 (PATH-derived binds).
- **Validate:** SCN-SEC-06 extended with a `~/.l4-canary` file; the dummy-agentic gates stay green.

**HB-17. Warn on an unrecorded CLI version (§39).** SPEC. Low.
- **Status: GAP.** ENV-004 checks only the version floor [V `doctor/checks_env.py:106-124`]. SCN-FAC-07 and SCN-FAC-14 are not built.
- **Change:** package `recorded_versions.json` generated from `tests/fixtures/recorded/*/`. Emit a `LIVE-*` warning and `availability.unrecorded_version`.
- **Validate:** unit test; live, OpenCode 1.18.34 against the recorded 1.18.33 must warn.

### 4.2 Experiment

| Id | § | Experiment | Why not adopt now | Validate |
|---|---|---|---|---|
| HB-X1 | §12, §13, §22 | Zero-cost canary probes per adapter at the pins, in implementer and judge modes. Extends research/07 E1 with canary markers in `.claude/skills`, `.agents/skills`, `.opencode/skills`, `.hermes/skills` and repo `AGENTS.md`. | Codex 0.160 skill and `AGENTS.md` loading is [U]. OpenCode 1.18.34 skill discovery under `isolation_env` is [U]. Whether Claude `--safe-mode` drops `--mcp-config` servers (Serena) is [U]: every recorded fixture has `mcp_servers: []` [V] | `opencode debug skill`; `opencode debug agent build`; `claude -p --safe-mode --mcp-config … "hi"`, then read `init.mcp_servers`; a Codex canary skill. If Codex has no switch, a bwrap tmpfs over the skill directories covers every adapter |
| HB-X2 | §8, §33 | OpenCode `"skill": "deny"` and `"task": "deny"` (or `ask` for `opencode/` free models) in `opencode.py:82-87`. Codex collab off, once its config key is known. | 0 task or skill calls in 76 live streams [V challenge]. Whether a denied tool gives a 403 on free models is [U] | Contract test on the config JSON; one free-model hello |
| HB-X3 | §13, §40 skill-induced | Measure skill-induced cost on dummy-agentic: OpenSpec skill set plus an `AGENTS.md` with a spec-sync rule committed, k ≥ 3, with and without the adoption H15 contract line. | Never run live; justified by HB and the adoption analysis (C1, C8) | Attempts per task, `guard.violation`, `openspec` commands in the stream, tokens |
| HB-X4 | §7, §8, §39 | Serena off vs on (or with `excluded_tools`). | 0 MCP or Serena calls in 76 live streams, including 3 jobs where Serena ran [V]; 21 tool schemas [D research/05:197] | Tokens and attempts per task |
| HB-X5 | §10, §28 | Emit `task.feedback_repeated{reason_sha}` on the second identical failure reason (observability only). | SPEC `same_error_repeats: 3` equals `max_task_attempts: 3` at the defaults [V `SPEC.md:455`], so the SPEC breaker adds nothing there. Jobs 5498 and 5465 repeated an identical reason 3 times [D audits] | Simulate a scripted agent that fails the same way twice |
| HB-X6 | §23, §29 | SIGTERM/SIGINT handler that sets `RunRequest.interrupt` and lets `close()` run (L4-IMP-012). | How gitlab-runner 19.4 cancels a shell job (grace period?) is [U]. No handler today [V grep] | Cancel a dummy job running `trap … TERM; sleep`, then cancel a real step |
| HB-X7 | §18, §20 | `gates.network: none` default for test, lint and e2e; `setup` keeps network (`config/schema.py:156`, default `"allow"` [V]). | Playwright works under `--unshare-net` [V `docs/runner/README.md:86`], but one dummy run is needed first | Dummy suites stay green; a TCP connect from a red test fails |
| HB-X8 | §16, §25, §27, §37, §39 | **Built in M1.14 (tier I and J, k and ablations still open): `l4 eval`, `l4 eval --compare`, exit 15, doctor EVAL-001; see [../eval.md](../eval.md).** Original plan: `l4 eval run --set <dir> --k 3` on the runner through a probe branch. Tier J: judge and clarifier replay of human-labelled live units plus one seeded must-catch. Tier I: implementer end to end with hidden held-out acceptance tests. Then doctor EVAL-001 and a judge-versus-human agreement report reusing `s1/stats.py`. Ablation flags last. | Real cost and maintainer work for hidden oracles. With n = 12 trials it only catches large regressions | First runs: tier I `add-item-count` (the `red@4` target) and tier J for `judge@3` and `clarifier@4` |
| HB-X9 | §21 | (a) Plant `~/.claude/settings.json` with `env.ANTHROPIC_BASE_URL=http://127.0.0.1:9`, run the judge argv with `--safe-mode`. If it is honoured, read-write `~/.claude` is a cross-job injection surface, and a per-unit `CLAUDE_CONFIG_DIR` plus `CLAUDE_CODE_OAUTH_TOKEN` (sandbox audit C8) becomes adopt now. (b) An egress proxy for agents (M2). | [U]. An allow-listed provider domain still allows exfiltration to an attacker's own account on that provider (§22) | As stated |

### 4.3 Note

- Post-commit control events (`budget.cost`, `agent.session`) should go to a harness-only file in `$L4_CACHE` or the lock ref and be folded in on recovery (§30). Fold this into budgets work (implementer 1.24).
- L4-RACE-001 (rebase own unpushed commits after a human push, then retry) stays M2 (§32).
- Resource caps per gate (`prlimit --nproc/--as`) on a 3.8 GB VM (§18) [V `docs/runner/README.md:62`].
- Prompt-source truncation order puts the deltas last, and the marker names no path (§9). Implementer prompts never come near the budget (section 7).
- The `PreSatisfied.message` names criteria but not tests. The retry block does not say the failed attempt's changes were discarded (§10).
- The availability probe cache key excludes the binary version [V `availability/fallback.py:44-55`].

### 4.4 Risks in this section

| Item | What is not yet proven |
|---|---|
| HB-1 | Its whole value rests on an unrun probe. That `connect()` works through the read-only recursive bind is [I] |
| HB-2 | Three [U]: CE environment scopes, the runner that executes `test`, and the `run_untagged` value |
| HB-3 | Its only remaining [I] is agent behaviour: no live run has edited `openspec/specs`. an adopted project's skills and AGENTS.md rules can make this edit likely (section 6) |
| Versions | CLI help facts come from local Claude 2.1.289 and OpenCode 1.18.33, one patch from the pins. The Claude tool and skill facts are pinned by the 2.1.288 recordings. Codex 0.160 was not available locally |

## 5. Already done (do not rebuild), and the principle index

### 5.1 Done, with evidence

- **§25 Verification ≠ self-report.**
  - Red must fail and green must pass on harness-run gates.
  - The verifier re-runs the gates.
  - PASS is a deterministic aggregate [V `aggregate.py:12-15,77-87`].
  - Live: the `add-vat` defect was caught by the judge and parked as NEEDS_HUMAN. In M1.7, Codex's self-reported red was rejected 3 times by the vacuity check.
- **§26 Deterministic over judgment.** A judge `fail` becomes `needs_human` [V `aggregate.py:84-87`]. Protected paths are reverted in code [V `protected.py:220`]. The config is strict (`extra="forbid"`).
- **§27 Separate evaluator.** `assess_independence` [V `selection.py:175`]. The served-model vendor is re-checked after the call (`model_mismatch`) [V `ladder.py:823-829`].
- **§10 / §28 Errors as observations.**
  - The retry reason goes back as a `previous attempt` data block [V `prompt.py:134-138`].
  - The vacuity message was rewritten after live job 5498 (3 misreads, breaker). Job 5504 then passed on attempt 2 [V `discrimination.py:113-131`; ledgers].
- **§14 Durable history ≠ active context.** A fresh session per step, no resume in `agent_step` [V `tdd.py:341-348`]. Ledger, raw events and prompts are kept [V `tdd.py:339,353`].
- **§17 Structured working state** (no audit covered this).
  - The harness owns `tasks.md` ticking [V `implementer/tasks.py:1,119`].
  - The ledger is the truth and `state.json` a pure fold [V `state/fold.py:1,214`].
  - `L4-Step` trailers carry step identity [V `reconcile.py:62-73`].
  - `questions.md` is level-triggered human state [V `orchestrator.py:14-20`].
- **§11 MCP is not the loop.** L4 owns scheduling, context, completion, retries and sandboxing. A Serena failure is non-fatal [V `workbench.py:408-434`; SPEC L4-MEM-004].
- **§13 Lessons by progressive disclosure.** Lessons are scoped by path and kind [V `lessons.py:219-230`, `inject.py:48-52`], redacted, wrapped and ledgered [V `inject.py:39-45,104-105`].
- **§22 Provenance.**
  - `<l4:data>` + defuse + `_require_wrapped` [V `prompt.py:72-89`].
  - The agent's `blocking_tasks` are not trusted [V `loop.py:34-35`].
  - Guidance files are protected (research/07 A1, landed) [V `protected.py:26-28`].
  - Tool-less judge calls start in an empty cwd for Claude, Codex and OpenCode (research/07 A1b, landed) [V `test_judge_cwd.py`].
- **§19 Control plane outside the sandbox.**
  - The harness runs from the default-branch head, never the pushed branch [V `l4.gitlab-ci.yml:31`].
  - `.git` is read-only [V `bwrap.py` `build_argv`].
  - The ledger is restored after each gate [V `workbench.py:229-240`].
  - Credentials reach git through a helper, never argv [V `forge/gitlab.py:289-298`].
  - The harness secrets are kept out of the sandbox env and `/proc` [V `sandbox/env.py:28-37`; `--clearenv`; `--unshare-pid`].
- **§20 Approval side.** No per-action prompts. Humans approve by merging; the harness never pushes to the default branch [V `l4.gitlab-ci.yml:8-9`].
- **§30 / §31 Git side effects across a crash.**
  - Pushes are never forced [V `vcs/push.py:32-42`].
  - The hand-off commit is deduplicated [V `archive.py:261`].
  - MR: find before create [V `gitlab.py:183-190`].
  - Labels by diff [V `gitlab.py:271-283`].
  - Archive MR repair [V `postmerge.py:177-184`].
  - Pending ledger under a lease [V `state/pending.py:77-83,151-186`].
- **§33 Subagents.** None at harness level (AD-06). The Claude implementer has no Task or Skill tool [V recorded `red-ok.jsonl` init: Bash, Edit, Glob, Grep, Read, StructuredOutput, Write].
- **§36 Operator observability (largely).** `availability.selected` records per-profile binary version, auth, quota and hello time [V `fallback.py:154-180`]. Tokens are in `agent.finished`; `budget.cost`; `verdict.json` step timings.

### 5.2 Principle index (§1–§43)

| § | Principle (one line) | L4 status | Where |
|---|---|---|---|
| 1–4 | Model call ≠ agent; minimal loop; what the harness controls; model/harness/session/tool/sandbox split | N/A (definitional; L4's orchestrator, CLIs and bwrap match the split) | — |
| 5 | Agent-computer interface: the capability must be usable | DONE (delegated to the CLIs; permissions from one policy) | 5.1 |
| 6 | Affordance / contract / observation / feedback | DONE | 5.1 |
| 7 | Tool schemas are model input | PARTIAL (21 Serena schemas, 0 calls) | HB-X4 |
| 8 | More tools make the choice harder | PARTIAL | HB-X2, HB-X4 |
| 9 | High-signal results | DONE (truncation order is a note) | 4.3 |
| 10 | Errors are observations | DONE (live proof) | HB-6, HB-X5 |
| 11 | MCP is not the agent | DONE | 5.1 |
| 12 | Active context is a harness decision | PARTIAL (the CLI's own auto-load is not controlled) | HB-X1 |
| 13 | Progressive disclosure; skills | PARTIAL (lessons DONE; repo skills [U] for Codex and OpenCode) | HB-X1, HB-X3, section 6 |
| 14 | Durable history ≠ active context | DONE | 5.1 |
| 15 | Compaction is lossy | N/A (compaction happens inside the CLIs; steps are short; full logs are kept) | — |
| 16 | Harness changes alter quality | GAP | HB-11, HB-X8 |
| 17 | Structured working state | DONE | 5.1 |
| 18 | Execution environment is architecture | PARTIAL | HB-1, HB-16, HB-X7, 4.3 |
| 19 | Sandbox is a boundary, not the orchestrator | DONE in design; no proof check | HB-15 |
| 20 | Approval ≠ containment | approval DONE; containment PARTIAL | HB-1, HB-16, HB-X7 |
| 21 | Credentials out of untrusted execution | PARTIAL | HB-1, HB-2, HB-4, HB-X9 |
| 22 | Observations have provenance | PARTIAL | HB-3, HB-13, HB-X1 |
| 23 | Stopping conditions are distinct | PARTIAL | HB-8, HB-X6 |
| 24 | Budgets limit autonomy | PARTIAL | research/07 A2, HB-9 |
| 25 | Verification ≠ self-report | DONE (one bypass) | 5.1, HB-3 |
| 26 | Deterministic enforcement vs judgment | DONE | 5.1 |
| 27 | Generator ≠ evaluator | separation DONE; evaluator reliability unmeasured | HB-X8 |
| 28 | Feedback loops with external evidence | DONE | HB-X5 |
| 29 | Long-running durability | PARTIAL (WIP local; no cancel handling) | HB-X6 |
| 30 | Recovery reconciles control and world state | DONE for git; PARTIAL for post-commit events | 4.3 |
| 31 | Idempotent retries | DONE except forge POST | HB-12 |
| 32 | Concurrency consistency | PARTIAL | HB-7, HB-14, 4.3 |
| 33 | Subagents are a harness choice | DONE at harness level; in-CLI subagents open | HB-X2 |
| 34 | Agent legibility | PARTIAL | HB-5, HB-14 |
| 35 | Mechanisms beat prose | PARTIAL | HB-11, HB-17, section 6 |
| 36 | Observability for operators and agents | PARTIAL | HB-6, HB-10 |
| 37 | Agent harness vs evaluation harness | GAP (S1 only) | HB-X8 |
| 38 | Environment changes the score | PARTIAL | HB-10 |
| 39 | Harness assumptions expire | GAP | HB-17, HB-X4, HB-X8 |
| 40 | Failure modes | mixed | section 3 |
| 41 | Misconceptions | mostly DONE; "newer model keeps old scaffolding useful" is never re-tested | HB-X8 |
| 42 | Production questions | — | section 2 |
| 43 | Complete mental model | N/A (summary) | — |

## 6. Implications for the sample-consumer adoption

Kept in the git-ignored adoption notes: the consumer repository is private.

## 7. Removed or downgraded, and why

**Removed or downgraded proposals:**
- **`--disable-slash-commands` for Claude (context audit N2) → note.** The 2.1.288 implementer streams have no Skill tool, and safe-mode leaves only built-in skills [V recorded init events]. Redundant, though harmless.
- **Drop Serena's `embed_memory('harness/lessons')` (N5) → note; fix the SPEC text instead.**
  - SPEC L4-MEM-004 mandates the embed [V `SPEC.md:1983-1990`].
  - It reaches the model only through `initial_instructions`, and live exposure is 0.
  - The real defect is that L4-MEM-003 ("always wrapped") contradicts L4-MEM-004.
  - Removing the embed would also touch the M1.7 byte-identical seed fix.
- **`agent.context` event (N7) → low.** Claude's `init` is already in the published raw stream. A worktree guidance-file inventory has no value until HB-X1 shows that a CLI loads those files.
- **N6 contract line → merged into adoption H15 and H18.** It is not new [V `analysis.md:694,697`]. HB-3(b) supersedes H18.
- **`stop_kind` enum → note.** `phase_after` already separates the stop states; only the reason is missing (HB-8).
- **Doctor EVAL-001 → experiment.** It has nothing to check before the HB-X8 eval set exists.
- **Gate-only empty HOME and gate-only `network: none` as adopt-now (sandbox audit C5, C6) → planned / experiment.** The agent sandbox already sees the home, with network on. HB-16 covers both kinds.
- **Mount vs hide split, and the Kiro credential path (C7) → note.** Kiro is not logged in [V `prereqs-2026-10-05…:20`]; the OpenCode config dir is low risk.
- **Codex judge's read-only shell (C10) → note.** Judge output is redacted by token shape.
- **"Same-error" breaker from SPEC → observability only (HB-X5).** At the defaults it equals `max_task_attempts`.
- **Exit-1 breaker for every phase → limited to L4-VER-010's scope (HB-9).** Push rules are Premium; a refused push on CE is unlikely [I].
- **"Not single-tenant, so rotate the token" as new evidence → [I], not [V].** `docs/runner/README.md:82` says "another user", most likely the maintainer's own admin user. Rotation is still owed under README:148-152.
- **`prompt.rendered.truncated` field and §9 truncation order → note.** The implementer budget never binds (sizes below).

**Corrections to the inputs, found in this pass:**
- **Prompt sizes.** n = 52 published live prompts (46 tracked, 6 in untracked M1.5 jobs); median 6,300 B. Implementer prompts top out at 8,431 B (job 5528 `1.1-red-2`). The 9,485 B (job 5451) and 18,558 B (job 5531) maxima are **clarifier** prompts. That explains why the two audits disagreed (9,485 vs 8.4 KB max) [V `wc -c`].
- **`clarifier@4` has run live once.** Job 5531 (untracked): `clarifier.result` status `ok`, kind `technical`, confidence high, **not** auto-accepted because three citation S1 probabilities were 0.65–0.77, below 0.80 [V ledger]. The verification audit and the challenge both said 0.
- **`red@4` has run live 3 times** (jobs 5522 and 5528, untracked) [V `template_version: contract@5+red@4`]. The verification audit said 0.
- **15-question errors in the verification audit, fixed in section 2:**
  - Q3: "judge has no tools" is false for Codex (read-only shell) and Kiro (runs in the worktree).
  - Q5: WIP snapshots are local refs.
  - Q8: `idempotency.step_key` is unused; the trailer key is `<task>/<phase>/<attempt>`; no lease or fencing on unit-branch pushes.
  - Q13: the empty judge cwd holds for 3 of 4 adapters.
  - Q14: `flock` plus `resource_group`, not a CAS lock ref.
- **Failure-mode table:**
  - The Environment row cited SANDBOX-001, which is not registered [V grep].
  - "Tool contract: invisible" was too strong. OpenCode's blocking denials surface [V `opencode.py:229-232`].
- **Control audit:** "exit 13 merges five causes". `phase_after` separates halted from escalated [V `outcome.py:39-53`]; only the reason inside `halted` is lost.
