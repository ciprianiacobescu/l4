# 06 — CI orchestration for a portable Level-4 agentic development harness

Research date 2026-10-03. Labels: **[V]** verified in a primary source (URL cited), **[V-local]** reproduced locally (git 2.48.1), **[V~]** primary page read through a summarizer only, **[D]** secondary source, **[I]** inferred, **[U]** unverified.

**How this was produced.** Six parallel research passes, one per topic area, are reproduced in full in Parts 1–6 below. The orchestrator then spot-checked the 13 load-bearing claims against primary sources or by reproducing them; see the Appendix. Where the sub-reports disagreed, the resolution is stated in §0.6.

---

## 0. Synthesis and recommendations

### 0.1 Verdict

1. **Nothing on the market runs our whole loop** (spec → implement → ask → resume → adversarial verify → fix-spec → archive) in a portable, CI-native way [I, from Parts 1–2]. Each product covers one hop, usually "event → agent → PR".
2. **The two best designs to copy** are GitHub Agentic Workflows (**gh-aw**, MIT) and **bmad-loop** (MIT):
   - From gh-aw: the read-only agent job with writes through separate "safe-outputs" jobs, staged mode as a dry run, `doctor`/`status`/`audit`, turn/credit caps, and `stop-after` [V](https://github.github.com/gh-aw/reference/safe-outputs/).
   - From bmad-loop: a deterministic Python loop with "No LLM in the control loop", plus `validate`/`run --dry-run`/`resume`/`resolve`, a run journal and worktrees [V](https://github.com/bmad-code-org/bmad-loop).
   - Neither can be the core: gh-aw is GitHub-only, and bmad-loop is local/tmux and tied to the BMAD format [V].
3. **Implementer backends to integrate behind one adapter** [V, Part 1/2]. All run non-interactively, return exit codes, emit JSON, and mostly support resume:
   - `claude -p --bare`
   - `codex exec`
   - `kiro-cli chat --no-interactive`
   - `droid exec --auto <level>`
   - `openhands --headless`
4. **Integrate OpenSpec as the primary spec format, with guards** [V](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md). Two traps, both orchestrator-verified in source:
   - `openspec archive --yes` archives even when tasks are incomplete; it only prints a warning.
   - `status --json` `isComplete` means planning is complete, not that the tasks are done.
5. **Both platforms provide the same loop guard** [V+I]:
   - **GitHub:** pushes made with `GITHUB_TOKEN` create no workflow runs [V](https://docs.github.com/en/actions/concepts/security/github_token).
   - **GitLab:** pushes made with `CI_JOB_TOKEN` trigger no pipelines. This went GA in 18.4 and must be enabled per project [V](https://docs.gitlab.com/ci/jobs/ci_job_token/).
   - **Our design:** harness writes never trigger CI. Continuation is always an explicit, counted dispatch or trigger. Human commits trigger the pipeline naturally.

### 0.2 What "Level 4" means for this harness

Full survey in Part 3. SAE-modelled frameworks that put "no code review by humans" at L4:
- **Sourcegraph** (2023-10-04): "humans are no longer expected to review the final code output" [V](https://sourcegraph.com/blog/levels-of-code-ai). At L3 the human "still should perform a high-level review of the final code output".
- **Dan Shapiro** (2026-01-23): L4 is "a robotaxi… while it's driving, you can do something else" [V](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/).
- **Feng, McDonald, Zhang**: L4 is the "approver" level. The user is involved only when there is a blocker or a consequential sign-off [V](https://arxiv.org/abs/2506.12469).
- **Gartner** (2026-05-26): L4 is "Act Autonomously… within defined guardrails, with humans reviewing exceptions, audit logs and aggregated outcomes" [V](https://gartner.com/en/newsroom/press-releases/2026-05-26-gartner-says-applying-uniform-governance-across-ai-agents-will-lead-to-enterprise-ai-agent-failure).

Other frameworks use "L4" to mean parallelism (Osmani) or initiative (Swarmia) [V]. Any claim about our level must therefore name the framework [I].

**Working definition [I].** Inside a declared **operational design domain (ODD)**, the harness takes an approved spec to a merge-ready change with no human reviewing intermediate steps or diffs. It handles its own fallback: verify → fix-spec → retry, within budgets. When it cannot continue, it reaches a **minimal-risk condition** and escalates:
- nothing has been written to protected branches;
- work is checkpointed on an isolated branch;
- `questions.md` holds one precise question;
- the lock is released.

Humans do four things:
1. approve the spec;
2. answer escalated questions asynchronously;
3. sign off at pre-declared gates (merge/archive) **on the evidence package, not by reading the diff**;
4. audit exceptions.

If a human must read the diffs, the harness is L3. If there is no merge gate at all, it is L5.

The SAE rule "will not operate unless all required conditions are met" becomes an **intake check** that rejects out-of-ODD specs before any spend [I, from SAE chart [V]].

### 0.3 Recommended state and status-tracking design

**Principle: level-triggered and deterministic [I].** Every run re-derives "what to do next" from the repository state on the spec branch. It never trusts CI payloads, transcripts, or mirrors. This is the stateless re-entry pattern of the Ralph loop and of Anthropic's long-running harness:
- Ralph: [V](https://ghuntley.com/ralph/)
- Anthropic, 2025-11-26 (initializer agent, `claude-progress.txt`, JSON feature list, git commits as checkpoints): [V](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

Transcript resume (`claude --resume`, `codex exec resume`) is an optional warm-start optimization, never the truth. Claude transcripts live machine-locally under `~/.claude/projects/`, their format is internal, and `--max-budget-usd` does not count cost restored on resume [V](https://code.claude.com/docs/en/cli-reference).

| Layer | Mechanism | Role |
|---|---|---|
| **Truth** | On branch `harness/<spec-id>`: `tasks.md` checkboxes (only `[x]`/`[X]` count as done, as in OpenSpec's parser [V~]); `questions.md` (open escalation; answers committed in place or as `answers.md`); `.harness/<spec-id>/ledger/<run-id>-<attempt>.jsonl` (append-only, one file per run, so merges never conflict); `state.json` derived as a fold over the ledger with a single writer | Survives squash merges as content, appears in the PR diff, travels with clones [I] |
| **Audit index** | Trailers `Harness-Spec`, `Harness-Task`, `Harness-Run`, `Harness-Iteration`, `Harness-State` on every harness commit (`git commit --trailer`, `git interpret-trailers --if-exists replace`) [V](https://git-scm.com/docs/git-interpret-trailers) | Provenance. Squash merges drop them: local squash indents them [V-local]; GitLab's default template is `%{title}` [V](https://docs.gitlab.com/user/project/merge_requests/commit_templates/). So **the harness performs the merge** and writes the squash message, using GitHub's merge API with `sha` as a compare-and-swap that returns 409 on mismatch [V](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request) |
| **Single writer** | GitHub `concurrency: harness-spec-<id>` / GitLab `resource_group: harness-<id>` as the primary guard. Portable backup: a lease in `state.json`, or a CAS lock ref `refs/harness/locks/<id>` pushed with `--force-with-lease=<ref>:<expected>` (empty `<expected>` means the ref must not exist) | **Never** prefix the refspec with `+`: it silently overrides the lease [V-local, re-verified by orchestrator]. Lock payloads need a nonce and an absolute expiry [V-local] |
| **Milestones** | Immutable annotated tags such as `harness/<id>/verified-<n>` [V](https://git-scm.com/docs/git-tag) | Pins the pre-squash commit |
| **UI mirrors** | Commit status `harness/<spec-id>` (GitHub: `statuses: write`, limit 1000 per sha+context [V](https://docs.github.com/en/rest/commits/statuses); GitLab: `POST /projects/:id/statuses/:sha` [V](https://docs.gitlab.com/api/commits/#set-commit-pipeline-status)), labels (`harness:needs-human`, `harness:verifying`, …), sticky PR/MR comment, job summary | Always recomputed from the ledger, and `doctor` repairs drift. Precedence on disagreement: ledger > trailers > tags > labels |
| **Off** | git notes | Not fetched by default, lost on host-side rebase/squash, and not displayed by GitHub since 2014 [V](https://github.blog/news-insights/the-library/git-notes-display/) |
| **Ephemeral** | CI artifacts (transcripts, Playwright traces, verifier report), caches (warm `~/.claude`) | Evidence and speed only. Caches are evictable after 7 days [V](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching). GitLab "artifact by ref" only returns successful pipelines [V](https://docs.gitlab.com/api/job_artifacts/#download-job-artifacts-by-reference-name) |

**Spec state machine [I]:**

`intake → (rejected_out_of_odd | ready) → implementing ⇄ awaiting_human → verifying → (fix_spawned → child spec … | verified) → merge_gate → archived`

plus `halted` when the circuit breaker trips.

**Ledger events [I]:**
- `run.started` (with run id, attempt, base/head SHA, input hash, backend, model);
- `task.started`, `task.done`;
- `question.raised`, `answer.detected`;
- `verify.started`, `verify.result` (deterministic and LLM parts kept separate);
- `fix.spawned` (child spec id, generation);
- `breaker.tripped` (reason);
- `cost` (cumulative USD and tokens);
- `archive.done`.

**Idempotency.** Each step is keyed by `(spec-id, task-id, sha256(spec files, base SHA, prompt version, model))` [I]. A `step.started` event with no matching `step.finished` is reconciled against trailers and the worktree diff. Steps that are not safe to repeat are marked **paused** rather than re-run, the same rule as Kiro Crew [V](https://kiro.dev/docs/crew/features/task-runner.md).

**Exit-code contract [I]**, Terraform-style [V](https://developer.hashicorp.com/terraform/cli/commands/plan):

| Code | Meaning |
|---|---|
| 0 | done / no-op |
| 1 | infrastructure error (retryable) |
| 2 | progress made, continue |
| 3 | awaiting human |
| 4 | breaker tripped / halted |
| 5 | out of ODD |

CI maps these to the commit-status state and decides whether to self-dispatch.

### 0.4 Recommended CI trigger design

**Common shape [I]:**
1. A cheap **router** decides per spec. It parses `tasks.md`, `questions.md` and the ledger; it does not use path filters as truth.
2. The router fans out **one serialized run per spec**.
3. The run checkpoints and pushes with the built-in token (no self-trigger).
4. Continuation goes through an explicit, counted dispatch.
5. Humans resume by committing answers to the spec branch (a normal push, which does trigger) or by a `/harness resume` comment.
6. A scheduled **sweeper** re-dispatches specs whose lease has gone stale.

#### GitHub Actions

| Concern | Recommendation | Basis |
|---|---|---|
| Router triggers | `push` with `paths: [openspec/changes/**, .kiro/specs/**]` on base and `harness/**` branches; `workflow_dispatch`; `issue_comment` (`/harness …`, filtered by `github.event.issue.pull_request` and `author_association`); `schedule` every 15–30 min as a best-effort sweeper | Event semantics [V](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows). Schedules may be delayed or dropped, and are disabled after 60 days of inactivity in public repos [V] |
| Path-filter caveats | Push with more than 1,000 commits or a diff timeout → **always runs**. Diff over 3,000 files with matches outside the first 3,000 → **does not run**. So the router must re-scan the repo itself | [V](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) |
| Fan-out | Router calls `workflow_dispatch` on `harness-run.yml` with `inputs.spec_id`, `mode` and `iteration`. Dispatch always creates runs, even with `GITHUB_TOKEN`. Since 2026-02-19 it can return the run id (`return_run_details`). Do not use `workflow_run` chains, which stop at 3 levels | [V](https://github.blog/changelog/2026-02-19-workflow-dispatch-api-now-returns-run-ids); [V](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) |
| Serialization | Workflow-level `concurrency: {group: harness-spec-${{ inputs.spec_id }}, cancel-in-progress: false}`. The implementer and verifier share the group string. Keep the default `queue: single` (one pending run, replaced by newer ones): runs are level-triggered, so coalescing is correct. Use `queue: max` (≤100 pending, FIFO not guaranteed) only if a run carries a payload that must not be dropped | [V](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues) (re-verified by orchestrator); [V](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) |
| Pushes | Checkpoint commits use `GITHUB_TOKEN` (`contents: write`), so they create no new runs. The final "ready for review" push and the PR creation use a **GitHub App token** minted right before the push (it expires after 1 h), so the repo's normal PR CI runs. As of 2026-06-11, PR events caused by `GITHUB_TOKEN` create runs that need a human to click approve | [V](https://docs.github.com/en/actions/concepts/security/github_token); [V](https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/); [V](https://github.com/actions/create-github-app-token) |
| Loop guards | (a) built-in token pushes don't trigger; (b) a `Harness-Iteration` trailer plus a ledger counter with a hard max per spec; (c) job `if:` that ignores pushes by the harness App bot; (d) no `[skip ci]` on harness commits, because skipped required checks stay Pending forever and block merges | [V](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs) + [I] |
| 6 h job cap | Run the agent step with `timeout-minutes` ≈300 and a soft deadline that sends **SIGINT** (SIGTERM exits 143 with the turn unfinished). Then an `if: always()` step commits WIP and the ledger, and self-dispatches the next iteration. Whether `always()` steps run after the 6 h hard kill is undocumented: test it. Optionally use the new `background: true` steps for a heartbeat or checkpointer | Limits [V](https://docs.github.com/en/actions/reference/limits); SIGTERM/SIGINT [V](https://code.claude.com/docs/en/headless); background steps [D](https://github.blog/changelog/2026-06-25-actions-steps-can-now-be-run-in-parallel) |
| Status | Commit status `harness/<spec-id>`, or a check run (`checks: write`). Pin the required check to the harness App to stop spoofing. Use an environment with required reviewers as the merge or expensive-run gate. On private repos this needs Enterprise; on Free/Pro/Team it is public repos only | [V](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) |
| Security | Agent job: read-only token, `persist-credentials: false`, egress allowlist. A separate writer job validates the diff (protected paths such as `.github/workflows/**`, size caps) and pushes. This is gh-aw's safe-outputs split. Never `pull_request_target` with a PR checkout; no fork PRs. OIDC to Bedrock/Vertex needs a credential lifetime at least as long as the job: AWS `role-duration-seconds` defaults to 1 h; GCP caps at 1 h unless org policy allows 12 h | [V](https://github.github.com/gh-aw/reference/safe-outputs/); PromptPwnd [V](https://www.aikido.dev/blog/promptpwnd-github-actions-ai-agents); [V](https://github.com/aws-actions/configure-aws-credentials) |

#### GitLab CI

| Concern | Recommendation | Basis |
|---|---|---|
| Packaging | Ship as a **CI/CD component**: templates `harness-detect`, `-implement`, `-verify`, with `spec:inputs` such as `spec_globs`, `agent_cmd`, `max_iterations`, `job_timeout`, `runner_tags`, `push_mode`. Keep `workflow:` out of the component; ship a documented `workflow:rules` snippet instead | [V](https://docs.gitlab.com/ci/components/) |
| Detection | `rules:changes` is unreliable as a trigger: it "always evaluates to true" for new branches and for non-push pipelines, and branch pipelines diff against `HEAD~`. Run a cheap `detect` job on `push`/`web`/`api`/`trigger`/`schedule` that scans the repo | [V](https://docs.gitlab.com/ci/yaml/#ruleschanges) |
| Fan-out | `detect` writes `child.yml`, launched with `trigger:include:artifact` and `strategy: mirror`. Variables are not allowed in a dynamic child's `include`, so write the literal component version. Child pipelines nest at most 2 levels; ≤1000 downstream pipelines per hierarchy | [V](https://docs.gitlab.com/ci/pipelines/downstream_pipelines/#dynamic-child-pipelines) |
| Serialization | `resource_group: harness-<spec_id>`; variables are allowed. The default process mode is `unordered`; switching to `oldest_first` is API-only. Level-triggered idempotent runs make `unordered` safe. Never set the same group in both parent and child (deadlock) | [V](https://docs.gitlab.com/ci/resource_groups/) |
| Pushes | **Mode A (recommended):** `CI_JOB_TOKEN` push. GA in 18.4, opt-in per project. It triggers **no pipelines** and carries the permissions of the user who started the job. Continue via the trigger API with a **trigger token** (not chained `CI_JOB_TOKEN` triggers, which count toward the hierarchy cap). **Mode B:** a project access token (Premium on GitLab.com) plus `[skip ci]`. `ci.skip` push options do not affect MR pipelines | [V](https://docs.gitlab.com/ci/jobs/ci_job_token/) (re-verified by orchestrator); [V](https://docs.gitlab.com/topics/git/commit/#push-options-for-gitlab-cicd) |
| Status | `CI_JOB_TOKEN` **cannot** set commit statuses, post MR notes, or edit labels. Those need a project or group access token with `api` scope | [V](https://docs.gitlab.com/ci/jobs/ci_job_token/) |
| Timeouts | **GitLab.com hosted runners: 3 h hard cap**, regardless of project setting (orchestrator-verified). Project default is 60 min. Jobs are dropped after 1 h with no output, so stream a heartbeat. `after_script` does **not** run on timeout by default; set `RUNNER_SCRIPT_TIMEOUT` + `RUNNER_AFTER_SCRIPT_TIMEOUT` ≤ job timeout so the WIP commit happens | [V](https://docs.gitlab.com/ci/runners/hosted_runners/); [V](https://docs.gitlab.com/ci/yaml/#after_script) |
| Human resume | A human pushing answers to the spec branch creates a normal push pipeline, and `detect` resumes. MR comments do not create pipelines natively: use a note-event webhook that calls the trigger API, or a manual "Run pipeline". Pipeline variables are restricted by default on new GitLab.com projects (since 17.7), so pass `inputs` | [V](https://docs.gitlab.com/ci/variables/#restrict-pipeline-variables); [V](https://docs.gitlab.com/ci/inputs/) |
| Cancellation | Implementer `interruptible: false`, so a human push cannot kill it mid-commit. `detect` is interruptible | [V](https://docs.gitlab.com/ci/yaml/#interruptible) |

#### Minimal GitHub skeleton (illustrative) [I]

```yaml
# .github/workflows/harness-run.yml
on:
  workflow_dispatch:
    inputs:
      spec_id:   {type: string, required: true}
      mode:      {type: choice, options: [implement, verify, archive, plan], default: implement}
      iteration: {type: number, default: 0}
concurrency:
  group: harness-spec-${{ inputs.spec_id }}
  cancel-in-progress: false            # queue: single (default) = coalesce pending
permissions: {contents: write, statuses: write, actions: write}
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 345
    steps:
      - uses: actions/checkout@<pinned-sha>
        with: {ref: harness/${{ inputs.spec_id }}, fetch-depth: 0, persist-credentials: false}
      - run: harness doctor --ci --spec "${{ inputs.spec_id }}"    # read-only preflight
      - id: step
        timeout-minutes: 300
        run: harness step --spec "${{ inputs.spec_id }}" --mode "${{ inputs.mode }}" --iteration "${{ inputs.iteration }}" --soft-deadline 280m
      - if: always()
        run: harness checkpoint --push --dispatch-next   # commits ledger/WIP with GITHUB_TOKEN; self-dispatches if exit==2 and iteration<max
```

### 0.5 Loop-safety defaults [I, grounded in Part 6 + Part 2]

| Guard | Default | Precedent |
|---|---|---|
| Intake ODD check | Reject a spec with no testable acceptance criteria, out-of-scope paths (migrations/auth/infra unless allowed), or no runnable test oracle | SAE "will not operate unless…" [V] |
| Max iterations per spec | 10 implement runs | Ralph plugin: "Always use `--max-iterations`" [V](https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum) |
| Max fix-spec generations | 3 (fix-of-fix depth), then `halted` + escalate | Kiro Crew `MAX_REPLAN=2` [V](https://kiro.dev/docs/crew/features/task-runner.md); BMAD review loop >5 → `blocked` [V~] |
| No-progress breaker | 3 iterations with an unchanged cumulative-diff hash or no newly checked task | frankbria `CB_NO_PROGRESS_THRESHOLD=3` [V](https://github.com/frankbria/ralph-claude-code) |
| Same-error breaker | 3 identical normalized failure fingerprints (test id + error class) | Kiro Crew: 3× same error = "Loop detected" [V]; frankbria uses 5 [V] |
| Oscillation | Diff hash returns to an earlier value (A→B→A) | [I] |
| Cost | Cumulative USD and tokens tracked **by the harness**, because `--max-budget-usd` does not count restored totals on `--resume`. Per-invocation `--max-turns` and `--max-budget-usd` as an inner cap | [V](https://code.claude.com/docs/en/cli-reference) |
| Test tampering | Fail verification if tests were deleted or weakened in the diff | Anthropic: "It is unacceptable to remove or edit tests" [V](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) |
| Verifier fails closed | A verifier crash or timeout means FAIL, never pass. Kiro Crew does the opposite ("Review exceptions are non-fatal (returns 'passed')"); do not copy that | [V](https://kiro.dev/docs/crew/features/task-runner.md) |
| Done gate | The agent's claim **and** all of `tasks.md` `[x]` (via `openspec list --json` `completedTasks==totalTasks`) **and** a recorded verifier pass, before `openspec archive --yes` | frankbria dual-condition exit [V]; OpenSpec archive trap [V] |
| Questions | At most 3 open questions per escalation. Escalation = `questions.md` + `awaiting_human` + release lock + exit 3 (not a failure) | Spec Kit caps `[NEEDS CLARIFICATION]` at 3 [V](https://github.com/github/spec-kit/blob/main/templates/commands/specify.md) |
| Separate evaluator | Verifier runs in a fresh session with a skeptical prompt, re-runs tests and Playwright itself, and reads the diff rather than the implementer transcript | Anthropic 2026-03-24: tuning a standalone skeptical evaluator is "far more tractable" [V](https://www.anthropic.com/engineering/harness-design-long-running-apps) |

**Dry run and doctor [I]:**
- **`harness plan`** is read-only. It prints the per-spec decision (dispatch, skip, awaiting human, halted) and uses Terraform-style exit codes: 0 no-op, 2 work pending.
- **`harness step --dry-run`** runs the agent in a scratch worktree but never pushes, the equivalent of gh-aw's "staged mode" preview in the step summary.
- **`harness doctor`** is read-only, with `--fix` repairing only mirrors. It checks:
  - CLI versions and auth;
  - token scopes;
  - whether the GitLab job-token push setting is enabled;
  - concurrency config;
  - `openspec validate --all --strict --json`;
  - ledger ↔ trailers ↔ labels drift;
  - stale leases;
  - breaker states.

  Precedents: gh-aw `doctor` [V](https://github.github.com/gh-aw/setup/cli/), bmad-loop `validate` [V], `openspec doctor --json` [V].

### 0.6 Where the sub-reports disagreed, and how it was resolved

1. **`queue: max` vs the default `queue: single`.** Part 6 suggested `queue: max`; Part 4 suggested `single`. **Resolved: `single`.** Runs are level-triggered (they re-read branch state), so a newer pending run replacing an older one loses nothing [I].
2. **gh-aw `max-daily-ai-credits`.** Part 6 said 5000; Part 1 said off. The orchestrator fetched the frontmatter reference: "disabled by default when omitted" [V](https://github.github.com/gh-aw/reference/frontmatter/). Treat 5000 as an example value [U]. Pin the gh-aw version either way: it releases every few days, and v0.83.3–<0.85.4 were withdrawn for a security issue [V, Part 1].
3. **Old 300-file vs current 3,000-file path-filter limit.** The current docs say 3,000 [V]; no changelog was found for the change [U].
4. **Kiro task markers `[-]`/`[~]`.** These are not in Kiro's public docs [V]. Parse only `[x]` as done.
5. **Anthropic Ralph plugin license.** `anthropics/claude-code` is "All rights reserved"; `anthropics/claude-plugins-official/plugins/ralph-loop` is Apache-2.0 [V, Part 2]. Borrow the pattern, not the code, unless taking it from the Apache copy.

### 0.7 Highest-risk open items: verify empirically before building

1. Whether `if: always()` steps run after GitHub's 6 h hard kill [U]. The design depends on the soft-deadline SIGINT finishing **before** the hard limit, not on `always()`.
2. Whether `openspec validate --strict` tolerates extra files (`questions.md`, `.harness/`) inside a change folder [U]. If it does not, keep the harness state outside the change folder at `.harness/<spec-id>/`, which this design already does, and put `questions.md` beside it.
3. GitHub multi-commit squash and custom trailers [U]. The design avoids depending on this by having the harness write the squash message.
4. 2026-era features: GitHub `queue: max`, background steps, approval-required runs for PRs created with `GITHUB_TOKEN`; GitLab 19.x Duo flow triggers. Confirm availability on the user's plan, and on GHES or self-managed versions if those are used.
5. Proprietary pieces (Copilot cloud agent 59-min cap, Duo Agent Platform Premium/Ultimate, Factory Missions, Devin, Jules, Cursor) are optional backends only. The harness core must not depend on them.

---

# Part 1 — Prior art A: CI-integrated agents


**Verdict up front.** Nothing on this list implements the whole spec-driven loop: detect unimplemented tasks, implement, ask questions, resume, verify adversarially, open a fix spec, archive. Each one covers a single hop, usually "event → agent → PR/comment".
- **gh-aw** (GitHub Agentic Workflows) is the most useful to copy. Its design maps onto most of our harness: read-only agent job, writes through separate "safe-outputs" jobs, staged (dry-run) mode, a `doctor` command, status/logs/audit commands, turn and credit caps, and git-branch memory. It only runs on GitHub, so it can't be our portable core. [I]
- **Implementer backends worth wrapping behind one adapter interface:** `claude -p`, `codex exec`, OpenHands CLI `--headless`, `mini`, and `aider --message`. All five are non-interactive, exit with a status code, and most emit JSON and support resume. [V, cited below]
- **Three platform facts that could break our resume loop if ignored:**
  1. GitHub does not start workflows from commits pushed with the default `GITHUB_TOKEN` ([V](https://code.claude.com/docs/en/github-actions)). PRs created by gh-aw safe-outputs also don't trigger CI by default ([V](https://github.github.com/gh-aw/reference/safe-outputs-pull-requests/)). So "agent commits questions.md → human commits answer → pipeline resumes" needs an App token or PAT, or an explicit dispatch.
  2. claude-code-action rejects bot actors unless they are listed in `allowed_bots`, which is there to prevent loops ([V](https://code.claude.com/docs/en/github-actions)).
  3. On Copilot PRs, workflows don't run until a write-access user clicks "Approve and run workflows" ([V](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations)).

Labels: [V] verified on a primary source, with URL; [D] secondary source; [I] my inference; [U] unverified. Release dates and licenses come from the GitHub REST API (`api.github.com/repos/<repo>` and `/releases`), queried 2026-10-03.

---

### 1. anthropics/claude-code-action, `claude -p`, the Agent SDK, and GitLab

**What it is.** A GitHub Action that runs Claude Code inside a workflow. It can answer questions, implement changes, review code and open PRs ([V](https://github.com/anthropics/claude-code-action)). v1 shipped 2025-08-26. The latest tag is v1.0.240, published 2026-10-02 ([V](https://api.github.com/repos/anthropics/claude-code-action/releases)). It is built on the Claude Agent SDK ([V](https://code.claude.com/docs/en/github-actions)).

**Triggers** ([V](https://raw.githubusercontent.com/anthropics/claude-code-action/main/action.yml), [V](https://code.claude.com/docs/en/github-actions)):
- **Interactive mode** applies when the workflow sets no `prompt`. It responds to `trigger_phrase` (default `@claude`) in comments, reviews, or a new issue's title or body. `label_trigger` defaults to `claude`; `assignee_trigger` is optional.
- **Automation mode** applies when `prompt` is set (plain text or `/skill`). It runs on any event, including `schedule`.
- **Gating:** the triggering user needs write access unless listed in `allowed_non_write_users`. Bot actors are rejected unless listed in `allowed_bots`.

**State tracking:**
- In interactive mode, Claude posts a comment on the issue or PR and keeps updating it as it works. `track_progress` forces tracking comments, and `use_sticky_comment` keeps everything in one comment ([V](https://raw.githubusercontent.com/anthropics/claude-code-action/main/action.yml)).
- Outputs: `session_id` (described as usable with `--resume`), `execution_file`, `branch_name`, `conclusion`, and `structured_output` when `--json-schema` is passed ([V](https://raw.githubusercontent.com/anthropics/claude-code-action/main/action.yml)).
- `branch_prefix` defaults to `claude/` ([V](https://raw.githubusercontent.com/anthropics/claude-code-action/main/action.yml)).

**Limits.** There is no separate input for limits. They go in `claude_args`, for example `--max-turns`, and the docs also recommend workflow timeouts and concurrency groups ([V](https://code.claude.com/docs/en/github-actions)).

**Auth.** API key, OAuth token, OIDC workload-identity federation, Bedrock, Vertex/Agent Platform, or Foundry ([V](https://code.claude.com/docs/en/github-actions)).

**Headless CLI (the Agent SDK CLI)** ([V](https://code.claude.com/docs/en/headless), [V](https://code.claude.com/docs/en/cli-reference)):
- **Run and output:** `claude -p` exits 0 on success and non-zero on failure. `--output-format json` returns `session_id` and `total_cost_usd`. `--json-schema` returns a validated `structured_output`.
- **Limits:** `--max-turns` errors out when reached and has no limit by default. `--max-budget-usd` counts subagent spend too.
- **Permissions:** `--permission-mode dontAsk|acceptEdits|auto` and `--permission-prompts none` (v2.1.259+) cover unattended runs.
- **CI isolation:** `--bare` skips hooks, plugins, MCP servers and CLAUDE.md. The docs recommend it for CI and say it will become the default for `-p`.
- **Sessions and worktrees:** `--resume <id>` or a transcript path, `--session-id <uuid>`, `--fork-session`, `--no-session-persistence`, and `-w/--worktree`.
- **Signals:** SIGTERM exits with code 143, and the interrupted turn stays unfinished.

**Agent SDK sessions** ([V](https://code.claude.com/docs/en/agent-sdk/sessions)):
- Sessions are local `.jsonl` files under `~/.claude/projects/`.
- To resume on a different CI host you have to move that file or use a `SessionStore` adapter.
- The docs also suggest skipping session resume altogether: save the results you need as application state and start a fresh session with them. That is direct support for keeping our state in git (questions.md plus task checkboxes) rather than in sessions. [I]
- Result subtypes `error_max_turns` and `error_max_budget_usd` exist, and the documented fix is to resume with a higher limit.

**GitLab.** There is an official "Claude Code GitLab CI/CD" integration. It is **in beta and maintained by GitLab, not Anthropic** ([V](https://code.claude.com/docs/en/gitlab-ci-cd)).
- It is a plain `.gitlab-ci.yml` job that runs `claude -p`.
- Mention triggers need your own webhook listener that calls the pipeline trigger API, passing `AI_FLOW_INPUT`, `AI_FLOW_CONTEXT` and `AI_FLOW_EVENT`.
- Recommended limits are `--max-turns` plus the job `timeout:` keyword.

**Reuse.** Use `claude -p --bare` as an **implementer/verifier backend** on both CI systems. claude-code-action is optional, for GitHub auth and comment UX only. Copy the sticky progress comment and the bot-actor guard. [I]

**License.** MIT ([V](https://raw.githubusercontent.com/anthropics/claude-code-action/main/LICENSE)). The Claude Code CLI itself is proprietary [U].

### 2. openai/codex-action, `codex exec`, and Codex cloud on GitHub

**What it is.** codex-action installs the Codex CLI, starts a Responses-API proxy so the key isn't exposed, and runs `codex exec` ([V](https://github.com/openai/codex-action), [V](https://learn.chatgpt.com/docs/github-action)). The latest tag is v1.12 ([V](https://api.github.com/repos/openai/codex-action/tags)). The latest stable Codex CLI is rust-v0.160.0, released 2026-10-01 ([V](https://api.github.com/repos/openai/codex/releases/latest)).

**Inputs** ([V](https://raw.githubusercontent.com/openai/codex-action/main/action.yml)):
- `prompt` or `prompt-file`, `codex-args`, `model`, `effort`, `output-file`.
- `permission-profile` (`:read-only` / `:workspace`). `sandbox` is the legacy equivalent.
- `safety-strategy`: `drop-sudo` (default), `unprivileged-user`, `read-only`, or `unsafe`.
- `allow-users` and `allow-bots`.

**Triggers.** Ordinary workflow events only. There is no mention or label handling built in. [V/I]

**State.** One output, `final-message`. Posting a comment is up to you, for example with github-script ([V](https://learn.chatgpt.com/docs/github-action)).

**`codex exec`** ([V](https://learn.chatgpt.com/docs/non-interactive-mode)):
- Flags: `--json` (JSONL events), `-o/--output-last-message`, `--output-schema`, `--sandbox workspace-write`, `--ephemeral`, `--skip-git-repo-check`, `--ignore-user-config`.
- Resume: `codex exec resume --last` or `codex exec resume <SESSION_ID>`.
- CI auth: `CODEX_API_KEY`.
- I found no documented turn or budget cap [U]. Use job timeouts instead.

**Codex cloud on GitHub.** `@codex review` comments, optional automatic reviews that flag P0/P1 issues only, review rules in `AGENTS.md`, and `@codex fix …` to start a cloud task that pushes to the PR ([V](https://learn.chatgpt.com/docs/third-party/github.md)).

**Reuse.** Use `codex exec` as an **implementer backend**, and `--output-schema` for a structured status of done / blocked / questions. Copy the privilege-drop strategy for runner hardening. [I]

**License.** Apache-2.0 for both codex-action and codex ([V](https://api.github.com/repos/openai/codex-action)).

### 3. GitHub Copilot cloud agent (formerly "coding agent") and Agent HQ

**What it is.** It was renamed from "Copilot coding agent" to "Copilot cloud agent" in 2026 ([D](https://github.blog/changelog/month/04-2026/)). Each task runs in an ephemeral GitHub Actions environment, works on one branch, and opens **one** PR ([V](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)).

**Triggers** ([V](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent), [V](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-from-cli)):
- Assign an issue to Copilot.
- Mention `@copilot` in a PR comment.
- Use the Agents panel, or set up automations (schedule or events).
- From the CLI: `gh agent-task create` (gh v2.80.0 or later), plus `list`, `view`, `--follow`, `--log`.

**State.**
- Draft PR on a `copilot/` branch.
- Session logs, and each commit message links to them.
- Audit-log events ([V](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations)).

**Limits.**
- 59-minute hard cap, and changes only in the starting repository ([V](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)).
- Internet access goes through a firewall.
- The person who requested the PR can't approve it.
- Workflows wait for "Approve and run workflows" ([V](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations)).

**`copilot-setup-steps.yml`.**
- Lives at `.github/workflows/copilot-setup-steps.yml`, and the job must be named `copilot-setup-steps`.
- Only these keys are honoured: `steps`, `permissions`, `runs-on`, `services`, `snapshot`, `timeout-minutes` (max 59).
- Self-hosted (ARC) runners require turning off the built-in firewall ([V](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-environment)).

**Agent HQ.** Claude and Codex became available as GitHub coding agents in public preview on 2026-02-04, for Copilot Pro+ and Enterprise. They can be started from issues, PRs, the Agents tab, or VS Code. During the preview each session cost one premium request ([V](https://github.blog/changelog/2026-02-04-claude-and-codex-are-now-available-in-public-preview-on-github/)). Third-party agents use Actions minutes and AI credits ([V](https://docs.github.com/en/copilot/concepts/agents/about-third-party-agents)). "Mission control" is the dashboard for tracking agents ([D](https://thenewstack.io/github-agent-hq/)).

**Reuse.** Don't use it as the core: it is GitHub-only and proprietary, with one PR per task and a 59-minute cap. Do copy two patterns:
- An environment-setup file the harness reads, which would be our "doctor" target.
- Commit trailers that link to the session log.

It can optionally be a dispatch target through gh-aw's `assign-to-agent`. [I]

**License.** Proprietary service. [I]

### 4. GitHub Agentic Workflows (`github/gh-aw`), covered in most detail

**What it is and its status.**
- Technical preview from 2026-02-13 ([V](https://github.blog/changelog/2026-02-13-github-agentic-workflows-are-now-in-technical-preview/)); **public preview since 2026-06-11** ([V](https://github.blog/changelog/2026-06-11-github-agentic-workflows-is-now-in-public-preview)).
- Repo is `github/gh-aw`; `githubnext/gh-aw` redirects there. Latest release is v0.90.3, published 2026-10-03, and the project releases very often ([V](https://api.github.com/repos/github/gh-aw/releases)).
- Releases from v0.83.3 up to (not including) v0.85.4 were withdrawn for a security vulnerability ([V](https://github.com/github/gh-aw)).
- You write Markdown with YAML frontmatter. `gh aw compile` validates it and generates a `.lock.yml`, which is the file Actions actually runs ([V](https://github.com/github/gh-aw)). Compilation also SHA-pins actions and runs actionlint, zizmor and poutine ([V](https://github.github.com/gh-aw/introduction/architecture/)).

**Job pipeline** ([V](https://github.github.com/gh-aw/introduction/architecture/)): pre-activation (role checks) → activation (input sanitisation) → **agent job (read-only; writes are buffered as artifacts)** → **detection job (an AI threat scan of the proposed output)** → **safe-output jobs (scoped write tokens)** → conclusion. Network isolation works like this:
- The Agent Workflow Firewall (AWF) runs the agent in a container.
- It forces HTTP(S) through a Squid proxy using a domain allowlist.
- MCP servers run in separate per-server containers behind a gateway.

**Triggers** ([V](https://github.github.com/gh-aw/reference/triggers/)):
- Any Actions event.
- `slash_command:` for `/cmd` in comments.
- `label_command:`, which **removes the label after triggering so it can be re-applied**.
- Fuzzy schedules such as "daily around 14:00".
- `reaction:`, `skip-if-match` / `skip-if-no-match` (GitHub search queries), `manual-approval:` (environment gate).
- `stop-after: "+25h"`.
- `roles:` (default admin/maintainer/write) and `bots:`.

**Engines** ([V](https://github.github.com/gh-aw/reference/engines/)):
- Supported: `copilot` (the default), `claude`, `codex`, `gemini`, `pi`, each with `model`, `version`, `args`, `env`, `max-turns`.
- Aider, OpenCode, Crush, Cursor and **Kiro** have only unsupported "sample" integrations.

**Limits and costs** ([V](https://github.github.com/gh-aw/reference/frontmatter/)):

| Setting | Default |
|---|---|
| `max-turns` | 500 |
| `timeout-minutes` | 20 for the agentic step, 60 for the agent job |
| `max-ai-credits` | 1000 |
| `max-daily-ai-credits` | off |
| `user-rate-limit` | per-user windows |
| `strict` | true; non-strict workflows can't run on public repos |

**Safe outputs** ([V](https://github.github.com/gh-aw/reference/safe-outputs/)):
- How it works: the agent writes JSON intents, and a separate job validates them and applies them with per-type `max` limits.
- Available types include `create-issue`, `add-comment`, `create-pull-request`, `push-to-pull-request-branch`, `add-labels`, `create-check-run`, `dispatch-workflow` (max 3), `assign-to-agent`, `create-agent-session`, `noop`, `missing-tool`, and `missing-data`.
- **Staged mode** writes previews to the step summary instead of calling the API. That is exactly a dry-run.

**PR safe outputs** ([V](https://github.github.com/gh-aw/reference/safe-outputs-pull-requests/)):
- Commits travel as a **git bundle artifact**, with format-patch as a fallback.
- `draft: true` is enforced by default.
- Other options: `max-patch-size` (2048 KB), `max-patch-files` (300), `protected-files` / `allowed-files`, `if-no-changes`, `fallback-as-issue`, `stacked`.
- No CI runs on the PR unless `github-token-for-extra-empty-commit` is set.

**State and memory** ([V](https://github.github.com/gh-aw/patterns/memory-ops/)):
- `cache-memory` uses the Actions cache with 7-day retention.
- `repo-memory` uses a git branch such as `memory/<workflow>` for long-lived state.
- The documented pattern is a `{todo, done, errors, last_run}` JSON file "so the workflow can resume if interrupted".
- A `tracker-id` hidden marker tags everything a workflow creates ([V](https://github.github.com/gh-aw/reference/frontmatter/)).

**CLI** ([V](https://github.github.com/gh-aw/setup/cli/)):
- `doctor`, `compile`/`validate`/`lint`, and `trial` (runs in a temporary private repo).
- `run`, `status`, `logs`, `audit`, `health`, `outcomes`, `forecast` (projects credit spend).
- `fix` (codemods, dry-run by default), and `add`/`update` (3-way merge from `source:`).

**Reuse.** **Copy the patterns heavily:**
- The trust split: the agent job is read-only and a separate job holds the write token.
- Staged mode as our dry-run, and `doctor` / `status` / `audit` as our doctor and job-status commands.
- Git-branch memory for job status.
- Re-arming label commands.
- `stop-after` and the turn/credit caps.
- Protected files and patch-size caps.
- A separate threat-detection pass before writes.

On GitHub, optionally **emit gh-aw workflows as the harness's GitHub front-end**. It can't be the core, because it doesn't run on GitLab. [I]

**License.** MIT ([V](https://api.github.com/repos/github/gh-aw)).

### 5. GitLab Duo Agent Platform

**Status.** Foundational flows became GA in GitLab 18.8 and **custom flows GA in 19.2**, so the platform is now on 19.x, not 18.x ([V](https://docs.gitlab.com/user/duo_agent_platform/flows/), [V](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/)). Custom flows started as an experiment in 18.4 ([V](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/)).

**Foundational flows** ([V](https://docs.gitlab.com/user/duo_agent_platform/flows/foundational_flows/)): Developer (issue to MR), Software Development, Fix CI/CD Pipeline, Convert to GitLab CI/CD, Code Review, SAST False Positive Detection, SAST Vulnerability Resolution.

**Developer flow** ([V](https://docs.gitlab.com/user/project/merge_requests/developer/)):
- History: beta in 18.3, GA in 18.8, mention triggers added in 18.11.
- Triggers: `@duo-developer-<namespace>` mention, assigning the service account and clicking **Implement**, or Agentic Chat.
- Progress: the **AI > Sessions** page, plus a session link in the reply.
- The docs warn that large tasks "hit iteration limits".

**Custom flows** ([V](https://docs.gitlab.com/user/duo_agent_platform/flows/custom_flows_schema/), [V](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/)):
- YAML keys: `version: v1`, `environment: ambient`, `components` (e.g. `AgentComponent`, `OneOffComponent`), `routers`, `flow.entry_point`.
- The VS Code builder lists Agent, Tool (deterministic), AI Task, and **Human Input**, which "pauses the flow and waits for user input or approval". That is the closest native equivalent to our questions.md.
- Triggers: mention / assign / review-request of the service account, pipeline events (18.9), MR ready / approved / conflict, work item created (19.1), work item **status changed** (19.2), MR created (19.4).

**Execution** ([V](https://docs.gitlab.com/user/duo_agent_platform/flows/execution/)):
- Runs on CI runners that must carry the `gitlab--duo` tag and use a Docker or Kubernetes executor.
- The runner downloads the Duo CLI and connects to the Duo Workflow Service over WebSocket.
- Setup goes in `.gitlab/duo/agent-config.yml`, read from the default branch only, with `image`, `setup_script` and `cache`.
- The Anthropic Sandbox Runtime is optional and needs privileged runners.

**External CLI agents** ([V](https://docs.gitlab.com/user/duo_agent_platform/agents/external/), [V](https://docs.gitlab.com/user/duo_agent_platform/agents/external_examples/)):
- GitLab manages Claude Code and Codex agents, which have been on Self-Managed since 18.6.
- Configured in the AI Catalog as YAML with `image`, `commands`, `variables`, `injectGatewayToken: true`, and the `AI_FLOW_*` variables.
- Premium/Ultimate only.
- **Prompt-injection scanning does not cover external agents.**

**Reuse.** On GitLab, **copy** the patterns: a setup-config file read only from the default branch, the session page, status-change triggers, and a Human Input step. Optionally **integrate** by registering our implementer as an external agent. The portable path is plain `.gitlab-ci.yml` + `claude -p` / `codex exec`. [I]

**License.** Proprietary (Premium/Ultimate features). [I]

### 6. OpenHands, SWE-agent, mini-swe-agent

**OpenHands.**
- The repo is now `OpenHands/OpenHands`, v1.24.0 (2026-09-25), MIT ([V](https://api.github.com/repos/OpenHands/OpenHands), [V](https://raw.githubusercontent.com/OpenHands/OpenHands/main/LICENSE)). It now describes itself as a "self-hosted developer control center" (Agent Canvas) that drives ACP-compatible agents, including Claude Code, Codex and Gemini ([V](https://github.com/OpenHands/OpenHands)).
- **The old resolver GitHub Action is gone.** It used the `fix-me` label or `@openhands-agent`: a draft PR on success, a pushed branch on failure, and a result comment ([D](https://docs.all-hands.dev/usage/how-to/github-action)). The standalone `All-Hands-AI/openhands-resolver` repo is archived ([V](https://api.github.com/repos/All-Hands-AI/openhands-resolver)). The resolver workflow path returns 404 on `main`, and so does its docs page ([V], raw.githubusercontent and docs.openhands.dev checked 2026-10-03).
- Replacements:
  - Cloud "event automations" on GitHub events with JMESPath filters ([V](https://docs.openhands.dev/openhands/usage/automations/event-automations.md)).
  - SDK-based workflows, e.g. PR review triggered by the `review-this` label or by requesting `openhands-agent` as reviewer ([V](https://docs.openhands.dev/sdk/guides/github-workflows/pr-review.md)).
- **CLI** ([V](https://docs.openhands.dev/openhands/usage/cli/headless), [V](https://docs.openhands.dev/openhands/usage/cli/command-reference.md)):
  - `openhands --headless -t|-f`, which **always auto-approves**.
  - `--json` for JSONL output, `--resume [id]` / `--last`.
  - Exit codes: 0 success, 1 failure, 2 bad arguments.
  - Repo `OpenHands/OpenHands-CLI`, MIT, latest 1.16.0 ([V](https://api.github.com/repos/OpenHands/openhands-cli)).

**SWE-agent** is in **maintenance mode** and says to "use mini-SWE-agent instead" ([V](https://github.com/SWE-agent/SWE-agent)). Its issue command is `sweagent run --env.repo.github_url … --problem_statement.github_url … --agent.model.per_instance_cost_limit=2.00` ([V](https://swe-agent.com/latest/usage/hello_world/)). MIT; last release v1.1.0 (2025-05) ([V](https://api.github.com/repos/SWE-agent/SWE-agent)).

**mini-swe-agent** ([V](https://github.com/SWE-agent/mini-swe-agent), [V](https://mini-swe-agent.com/latest/usage/mini/)):
- An agent class of about 100 lines that only uses bash, keeps a linear history, and runs each step with `subprocess.run`.
- Flags: `mini -t <task> -y --exit-immediately -o traj.json --cost-limit`.
- Defaults: `cost_limit: 3.0`, `step_limit: 0` (unlimited).
- Latest v2.4.6 (2026-07), MIT ([V](https://api.github.com/repos/SWE-agent/mini-swe-agent)).

**Reuse.**
- **Copy** the old resolver's outcome contract: draft PR on success, branch plus comment on failure.
- Optional **backends**: OpenHands CLI and `mini`, whose trajectory files are good for audits.
- **Ignore** SWE-agent.

[I]

### 7. Aider in CI

**Scripting** ([V](https://aider.chat/docs/scripting.html)):
- `aider --message/-m` or `--message-file` applies one instruction and exits. Combine with `--yes-always`.
- `--auto-commits` is on by default, and `--dry-run` is available.
- The Python `Coder.create(...).run()` API is "not officially supported".

**Lint/test loop** ([V](https://aider.chat/docs/usage/lint-test.html)):
- Auto-lint is on by default (`--lint-cmd`).
- `--test-cmd` + `--auto-test` is off by default. A non-zero exit code makes aider try to fix the failure.
- The retry loop is capped by `max_reflections = 3` ("Only 3 reflections allowed, stopping") ([V](https://raw.githubusercontent.com/Aider-AI/aider/main/aider/coders/base_coder.py)).

**Momentum is low.** The last release was v0.86.0 on 2025-08-09, `main` is at 0.86.3.dev, and the last push was 2026-05-22 ([V](https://api.github.com/repos/Aider-AI/aider)). gh-aw lists Aider only as an unsupported sample ([V](https://github.github.com/gh-aw/reference/engines/)). It has no sessions or resume beyond chat history files [U].

**Reuse.** **Copy** the deterministic "implement → lint/test → feed failures back, capped at N" loop for our implementer step. As a backend it is low priority. [I]

**License.** Apache-2.0 ([V](https://raw.githubusercontent.com/Aider-AI/aider/main/LICENSE.txt)).

---

### Summary table

| Name | Trigger model | State tracking | Reuse recommendation | License |
|---|---|---|---|---|
| claude-code-action / `claude -p` | `@claude`, label `claude`, assignee, or `prompt` on any event / cron; CLI anywhere | Sticky progress comment; `session_id`, `conclusion`, `structured_output`; JSON with cost | **Integrate as implementer/verifier backend** (CLI `--bare`); action optional on GitHub | MIT (action) [V] |
| Claude Code GitLab CI/CD | Manual / MR / pipeline trigger API with `AI_FLOW_*` (webhook listener is DIY) | Job log, MR | Copy the job template for the GitLab path | Docs only; beta, GitLab-maintained [V] |
| codex-action / `codex exec` | Any workflow event; cloud: `@codex review` / `@codex fix` | `final-message`; JSONL; `exec resume <id>` | **Integrate as implementer backend**; copy privilege-drop | Apache-2.0 [V] |
| Copilot cloud agent / Agent HQ | Assign issue, `@copilot`, Agents tab, `gh agent-task create` | Draft PR on `copilot/*`, session logs, commit links | Copy patterns (setup-steps file, firewall, approval gate); don't use as core | Proprietary [I] |
| gh-aw | All events + `slash_command`, re-arming `label_command`, fuzzy cron, `stop-after` | Lock files, safe-output artifacts, repo/cache memory, `status`/`logs`/`audit` | **Copy patterns (top priority)**; optional GitHub front-end | MIT [V] |
| GitLab Duo Agent Platform | Mention / assign / review-request of service account; pipeline, MR, work-item events | AI > Sessions; Human Input pause | Copy patterns; optional external-agent registration | Proprietary [I] |
| OpenHands (CLI, automations) | Old: `fix-me` label / `@openhands-agent` (removed); now Cloud event automations, SDK workflows | Draft PR or branch + comment (old); JSONL; `--resume` | Copy outcome contract; optional backend | MIT [V] |
| SWE-agent / mini-swe-agent | CLI with issue URL / `-t` task | Trajectory files | SWE-agent: ignore; mini: optional backend | MIT / MIT [V] |
| Aider | CLI `--message --yes-always` | Git auto-commits | Copy capped lint/test loop; low-priority backend | Apache-2.0 [V] |

### Risks and caveats
- **Highest-impact claims, re-checked against primary sources:**
  - The `GITHUB_TOKEN` no-trigger rule.
  - The 59-minute Copilot cap.
  - gh-aw's read-only agent / safe-output split, and that it is GitHub-only.
  - Session files being machine-local.
- Several doc pages were read through a summarising fetcher. Exact defaults are lower-confidence than the URL-level facts and should be re-checked before being written into code: gh-aw's 1000 AI credits and 500 turns, and its per-type `max` values. [I]
- gh-aw releases roughly every few days, so pin the version.
- OpenHands' GitHub automation now depends on OpenHands Cloud, not a self-contained Action.
- GitLab Duo flows are Premium/Ultimate only and tied to the Duo Workflow Service, so they can't be our portable core.

All of the above is in this message; no files were written.

---

# Part 2 — Prior art B: spec frameworks, loops, hosted agents


**How to read the labels.** Research date is 2026-10-03. **[V]** means I read the primary text myself (raw file, curl or grep). **[V~]** means a primary page read only through a summarizer and not raw-checked. **[D]** means a secondary source. **[I]** means inferred, and **[U]** means unverified. The summarizer invented facts twice, and the raw docs corrected both: the Kiro task-marker meanings and the Devin status enum. So weight **[V~]** below **[V]**.

**Bottom line.** The closest prior art to our harness is **bmad-loop** (MIT). It is a deterministic Python orchestrator with worktrees, `validate`/`--dry-run`/`resume`/`resolve`, and run state in `state.json` + `journal.jsonl`. The next closest are **Kiro Crew Task Runner** (proprietary) and **Factory Missions** (proprietary), which validate each milestone and turn what fails into follow-up work. The main formats to integrate are OpenSpec and Kiro specs. Four OpenSpec traps matter for the harness:
- `status --json` `isComplete` refers to the planning documents, not the tasks.
- `archive --yes` archives even when tasks are unfinished; it only prints a warning.
- Only `[x]` or `[X]` counts as done.
- Without a terminal and without `--yes`, `archive` exits 1.

---

### 1. The Ralph loop family

**Huntley's original** ([ghuntley.com/ralph](https://ghuntley.com/ralph/), 14 July 2025) [V~]
- The loop is `while :; do cat PROMPT.md | claude-code ; done`.
- Files: `fix_plan.md` (a priority list the agent rewrites each loop), `specs/` and `AGENT.md` (build and run notes the agent learns into).
- Rules: one task per loop; tests and static analysis act as "backpressure".
- Stopping is manual: the operator watches, "adds signs" to the prompt, or runs `git reset --hard`. There is no channel for questions.

**"The Ralph Playbook"** ([github.com/ghuntley/how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum)) [V]
- It has two modes, `PROMPT_plan.md` and `PROMPT_build.md`. `IMPLEMENTATION_PLAN.md` on disk is the shared state between iterations, and each iteration starts with fresh context.
- `loop.sh [plan] [max_iterations]` runs `claude -p --dangerously-skip-permissions --output-format=stream-json` and then `git push` after every iteration.
- There is no LICENSE file: `LICENSE`, `LICENSE.md` and `LICENSE.txt` all return 404 [V]. Borrow the ideas only.

**Anthropic's official plugin** is published in two places:
- `anthropics/claude-code/plugins/ralph-wiggum`. That repo's license reads "© Anthropic PBC. All rights reserved" ([LICENSE.md](https://github.com/anthropics/claude-code/blob/main/LICENSE.md)) [V].
- `anthropics/claude-plugins-official/plugins/ralph-loop`, which has its own Apache-2.0 LICENSE [V].

How the plugin's Stop hook works ([stop-hook.sh](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/ralph-loop/hooks/stop-hook.sh)) [V~]:
- Usage is `/ralph-loop "<prompt>" --max-iterations N --completion-promise TEXT`, plus `/cancel-ralph`.
- State lives in `.claude/ralph-loop.local.md` as YAML frontmatter: `iteration`, `max_iterations`, `completion_promise`, `session_id`.
- On each stop, the hook takes the last assistant message from the transcript JSONL and pulls out the text inside `<promise>…</promise>`. It must match the promise exactly.
- If there is no match, the hook returns `{"decision":"block","reason":<prompt>,"systemMessage":…}`, which feeds the same prompt back in.
- It deletes the state file when it hits max iterations, when the promise matches, or when the state is corrupt.
- The README warns that exact matching is fragile, so always set `--max-iterations` [V~].
- Unlike Huntley's loop, this runs inside one session, so context piles up.

**frankbria/ralph-claude-code** v0.11.5, MIT ([README](https://github.com/frankbria/ralph-claude-code)) [V]
- Files live in `.ralph/` (`PROMPT.md`, `fix_plan.md`, `AGENT.md`, `specs/`), with settings in `.ralphrc` and machine-readable state in `.ralph/status.json`.
- **Exit needs both** `completion_indicators >= 2` (pattern heuristics) **and** an explicit `EXIT_SIGNAL: true` in a `RALPH_STATUS` block. If `EXIT_SIGNAL` is missing, it counts as false.
- Other ways it exits:
  - every `fix_plan.md` item is checked (except optional sections);
  - `MAX_CONSECUTIVE_DONE_SIGNALS=2`;
  - `MAX_CONSECUTIVE_TEST_LOOPS=3`;
  - the API's 5-hour limit is reached.
- **Circuit breaker:**
  - `CB_NO_PROGRESS_THRESHOLD=3` (loops with no file changes);
  - `CB_SAME_ERROR_THRESHOLD=5`;
  - `CB_OUTPUT_DECLINE_THRESHOLD=70`%;
  - states go OPEN → HALF_OPEN → CLOSED after `CB_COOLDOWN_MINUTES=30`;
  - controls: `--reset-circuit`, `--circuit-status`.
- It also rate-limits to 100 calls/hour, halts when a command permission is denied, and expires sessions after 24 h.

**snarktank/ralph** (MIT) [V~]
- `prd.json` stories carry a `passes` boolean, and `progress.txt` is an append-only learnings log.
- `ralph.sh` runs 10 iterations by default and stops on `<promise>COMPLETE</promise>`.

**Taskmaster** now ships a Ralph-style `task-master loop` ([CHANGELOG](https://github.com/eyaltoledano/claude-task-master/blob/main/CHANGELOG.md)) [V]. It runs `claude -p --dangerously-skip-permissions`, with Docker available through `--sandbox`.

**What to reuse: borrow, don't integrate.**
- Fresh context per iteration, the disk as the state store, and one task per iteration.
- A done gate that needs both conditions. For us: the agent's claim **and** all of `tasks.md` checked **and** the verifier passing.
- A no-progress breaker based on `git diff`, a breaker keyed on a hash of the error, and max iterations.
- The Stop-hook approach only suits interactive sessions. CI should run an outer loop.

### 2. OpenSpec (Fission-AI/OpenSpec)

**Version and license.** v1.14.0, published 2026-09-30T22:54Z ([npm](https://registry.npmjs.org/@fission-ai/openspec)) [V]. MIT, "Copyright (c) 2024 OpenSpec Contributors" ([LICENSE](https://github.com/Fission-AI/OpenSpec/blob/main/LICENSE)) [V].

**Layout** ([concepts.md](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md) [V~]; [cli.md](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md) [V])
- Main specs: `openspec/specs/<capability>/spec.md`.
- Each change: `openspec/changes/<id>/{proposal.md, design.md, tasks.md, specs/<cap>/spec.md}`, where the specs are deltas. A change can also carry `.openspec.yaml` with `schema:`, `skip_specs: true` and `retire_capabilities: true`.
- Delta sections are `## ADDED|MODIFIED|REMOVED Requirements`, each containing `### Requirement:` with SHALL/MUST and `#### Scenario:` blocks.
- The default `spec-driven` schema has a dependency graph: proposal → (specs, design) → tasks.

**Automation commands** ([cli.md](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)) [V]
- `list --json`
- `show <id> --json --no-interactive`
- `validate --all --strict --json --no-interactive`
- `validate --archived` exits non-zero if any archived change still has unchecked tasks.
- `status --change X --json`
- `instructions apply --change X --json`
- `instructions archive --change X --json` is read-only.
- `new change <id> --json`
- `archive <id> --yes [--skip-specs] [--no-validate]`
- `templates`/`schemas --json`, `openspec doctor --json`
- OPSX slash commands: `/opsx:propose`, `/opsx:apply`, `/opsx:verify`, `/opsx:archive`, `/opsx:bulk-archive` [V~].

**Gotchas for our harness:**
- `status --json`'s `isComplete` is just another name for `isPlanningComplete`. It means the planning documents exist, **not that the tasks are done** [V].
- Task progress comes from `list --json`. Each change has `completedTasks`, `totalTasks`, and `status` ∈ `no-tasks|in-progress|complete` (src/core/list.ts) [V~].
- Task-line regex in src/utils/task-progress.ts [V~]:
  `/^\s*(?:[-*+]|\d{1,9}[.)])\s*\[(?:\s*([^\]\s]?)\s*\](?![([])|\s+\])\s*(.*)/`
  Only `x` or `X` counts as done, so Kiro-style `[-]` or `[~]` counts as not done.
- `archive` without a terminal and without `--yes` exits 1 and prints the command to rerun. **With `--yes`, unfinished tasks only produce "Warning… Continuing due to --yes flag"** (src/core/archive.ts, lines ~1606–1641) [V]. The harness must check `completedTasks==totalTasks` and a verifier pass before it archives.

**What to reuse: integrate.** It is the main input format, and fix loops map naturally to `openspec new change fix-<id>-rN --json`. [U] whether `validate --strict` tolerates an extra `questions.md` in a change folder; test this.

### 3. Kiro (AWS)

**Specs** ([docs/specs.md](https://kiro.dev/docs/specs.md), [feature-specs.md](https://kiro.dev/docs/specs/feature-specs.md)) [V]
- Files: `.kiro/specs/<name>/requirements.md` (in EARS notation) or `bugfix.md`, plus `design.md` and `tasks.md`.
- Spec types: Feature (requirements-first or design-first), Bugfix, and Quick Spec (no approval gates).
- CLI commands: `/spec new <name>`, `/spec run <name>` (a full-screen execution view) and `/spec <name>` to resume.
- "Run all tasks" runs them in dependency waves [V~].
- **Task marker meanings are not in the public docs.** I grepped the raw pages and found no `[-]` or `[~]`; a summarizer's claim otherwise was invented. Your local `kiro-spec-implement` skill uses `[ ]→[~]→[-]→[x]`, which I'd treat as observed behaviour [U]. Parse only `[x]` as done.

**Headless CLI** ([headless.md](https://kiro.dev/docs/cli/headless.md), [exit-codes.md](https://kiro.dev/docs/reference/exit-codes.md)) [V]
- The command is `kiro-cli chat --no-interactive [--trust-all-tools | --trust-tools=read,grep,write] [--agent <name>] [--output-format stream-json] [--require-mcp-startup] "<prompt>"`.
- Auth is `KIRO_API_KEY`, and it cannot take input mid-run.
- Exit codes: 0 success, 1 failure, 3 MCP startup failure.
- [U] whether `/spec run` works headless.

**`/goal`** ([goal.md](https://kiro.dev/docs/cli/chat/goal.md)) [V]
- It loops plan → implement → verify, 5 iterations by default (`--max N`); `/goal clear` cancels it.
- It stops on a "repeated failure pattern" or when context runs out.

**Kiro Crew Task Runner** ([task-runner.md](https://kiro.dev/docs/crew/features/task-runner.md)) [V]
- Command: `kirocrew run TASK.md [--fresh|--timeout|--no-test]`.
- Each step:
  - runs in a fresh session;
  - is committed with git if its tests pass;
  - then gets an independent reviewer session that reads `git diff HEAD~1`;
  - is undone with `git reset --hard HEAD~1` and retried if the review fails.
- Limits:
  - `MAX_RETRIES=3`, `MAX_RECOVERIES=2`, `MAX_REPLAN=2`, `MAX_TOTAL_TASKS=50`;
  - the same error twice gives a warning, three times marks the step FAILED as a "Loop detected";
  - a stall watchdog warns at 60 min and resets at 2 h;
  - at most 3 runs at once.
- Isolation and recovery:
  - each task gets a worktree on `kirocrew/task/<id>` and resumes from checkpoints;
  - after a crash, runs that aren't safe to repeat reopen as **Paused**;
  - `force_approval: true` blocks a step even in YOLO mode.
- **One behaviour to avoid:** "Review exceptions are non-fatal (returns 'passed')", meaning a crashing reviewer counts as a pass.

**Autonomous agent** (announced 2 Dec 2025, [blog](https://kiro.dev/blog/introducing-kiro-autonomous-agent/) [V~]; [autonomous-mode.md](https://kiro.dev/docs/web/autonomous-mode.md) [V])
- It is now an "Autonomous" toggle in Kiro web. It works in a sandbox clone: plan → sub-agents → PR or MR.
- On GitHub you assign work with the `kiro` label or a `/kiro` comment; `/kiro all` and `/kiro fix` address review comments.
- When it needs clarification, the task moves to **"Needs attention"** and waits.
- At launch it was a preview for Pro, Pro+ and Power subscribers [V~].
- License: proprietary [I]. The CLI's source license: [U].

**What to reuse:** integrate the spec reader and `kiro-cli` as an implementer backend. Borrow the Task Runner's caps, its review-from-diff step and its crash-recovery rules.

### 4. GitHub Spec Kit

**Version and license.** v1.1.0, released 2026-10-02 ([releases](https://github.com/github/spec-kit/releases)) [V~]. MIT, "Copyright GitHub, Inc." [V].

**Commands** are now skills ([README](https://github.com/github/spec-kit), [quickstart](https://github.com/github/spec-kit/blob/main/docs/quickstart.md)) [V]: `/speckit-constitution`, `-specify`, `-clarify`, `-checklist`, `-plan`, `-tasks`, `-analyze`, `-implement`, `-converge`, plus the bug and assess extensions. `taskstoissues` moved into a bundled `github` extension in 1.0.13 [V~].

**Layout and formats**
- Feature folders are `specs/NNN-<name>/`, with the active one tracked in `.specify/feature.json` [V]. Each holds `spec.md`, `plan.md` and `tasks.md` [V].
- A task line looks like `- [ ] T012 [P] [US1] Create model in src/models/x.py` [V~].
- `spec.md` uses `[NEEDS CLARIFICATION: …]` markers, **capped at 3** ([specify.md](https://github.com/github/spec-kit/blob/main/templates/commands/specify.md)) [V].

**The converge loop.** `/speckit-converge` "assess[es] the current codebase against the feature's spec, plan, and tasks, then append[s] any remaining unbuilt work as new tasks to tasks.md". The documented loop is implement → converge until it reports "Converged" [V].

**Workflows engine** ([workflows.html](https://github.github.com/spec-kit/reference/workflows.html)) [V~]
- Steps are defined in YAML: `command|prompt|shell|gate|if|switch|while|do-while|fan-out|fan-in`.
- Run state is kept in `.specify/workflows/runs/<run_id>/{state.json, inputs.json, log.jsonl}`.
- Commands: `specify workflow run <src> -i k=v --json`, `resume <run_id>`, `status`.
- Run states: created, running, completed, paused, failed, aborted.
- The docs warn that shell steps insert values without escaping, so they can be injected.

**What to reuse:**
- Borrow converge as an alternative to spinning up a separate fix change.
- Borrow the cap on clarification questions.
- Borrow the run-state layout and gate steps.
- Optionally add Spec Kit as a third spec-format adapter.

### 5. Task and agent frameworks

**Taskmaster**
- Latest is task-master-ai 0.43.1 (2026-03-31; the last release was six months ago) [V npm]. License is **MIT WITH Commons-Clause**: you may not sell it or offer it as a hosted service ([LICENSE](https://github.com/eyaltoledano/claude-task-master/blob/main/LICENSE)) [V].
- Tasks live in `.taskmaster/tasks/tasks.json` [V~]. Statuses are `pending, done, in-progress, review, deferred, cancelled` (src/constants/task-status.js) [V].
- How `next` picks a task (find-next-task.js) [V~]:
  - eligible tasks are pending or in-progress with every dependency done;
  - subtasks of an in-progress parent come first;
  - then it sorts by priority (high > medium > low), then fewer dependencies, then ID.
- It also has `validate-dependencies` and `fix-dependencies`.
- **Borrow the selection algorithm only; do not vendor the code.**

**Ruflo (formerly claude-flow)**
- github.com/ruvnet/claude-flow returns a 301 redirect to ruvnet/ruflo, and the README says "Claude Flow is now Ruflo" [V]. Both npm names are at 3.51.1, MIT [V].
- It offers swarm and hive-mind modes, AgentDB vector memory and "100+ agents" [V~].
- **Ignore:** its control plane is driven by LLMs, which is the opposite of what we want.

**Agent OS**
- v3.0.0 (2026-01-20) [V] cut the implementation and orchestration phases and refocused on `/discover-standards` and `/inject-standards`. It now leaves spec writing to Claude Code's plan mode [V~].
- MIT, CasJam Media LLC [V].
- **Borrow** only the idea of injecting coding standards into the implementer's context.

**BMAD-METHOD**
- v6.12.0 (2026-09-04) [V]. MIT, plus trademark notices on the "BMad" names [V].
- Its `bmad-build-auto` skill (formerly `bmad-dev-auto`, which arrived in v6.10.0) does **one unattended iteration** per call ([docs](https://docs.bmad-method.org/build/autonomous-development-loops/)) [V~].
  - It tracks status in plan frontmatter: `status` ∈ `draft|ready-for-dev|in-progress|in-review|built|done|blocked`, with `blocked_at`, `blocked_reason`, `warnings`, `deferred` and `baseline_revision`.
  - Orchestrators should read `status` and `blocked_reason`, not the chat output.
  - A review repair loop that runs past 5 rounds becomes `blocked`.
- Sprint-status story states are `backlog|ready-for-dev|in-progress|review|done` [D [tessl](https://tessl.io/registry/skills/github/bmad-code-org/BMAD-METHOD/bmad-sprint-status)].

**bmad-loop** ([repo](https://github.com/bmad-code-org/bmad-loop)) v0.13.1 (2026-10-01), MIT [V]. This is the closest match to our harness.
- "No LLM in the control loop." Story selection, retry budgets, gates and completion checks are plain code.
- Coding-agent hooks (Stop, SessionStart, SessionEnd, PreCompact) write event files, and skills write `result.json`, so there is no screen scraping.
- After each session it checks the files on disk:
  - the frontmatter status;
  - the baseline commit;
  - that the diff is not empty;
  - the user's own test and lint commands.
- Each stage gets fresh context. Optional `[scm] isolation="worktree"` gives each story its own worktree and branch.
- Commands: `init`, `validate` (a preflight check, much like our doctor), `run --dry-run/--max-stories`, `resume`, `resolve` (for a CRITICAL escalation, it opens an interactive session that fixes only the spec, then resumes), `sweep` (works through the deferred-work ledger), `diagnose` and `clean` [V].
- Run state lives in `.bmad-loop/runs/<id>/{state.json, journal.jsonl, deferred-work.md, ATTENTION}`. It enforces token budgets and nudges stalled sessions [V~].
- Adapters: Claude, Codex, Gemini, Copilot, OpenCode [V~].
- **Limitation:** it runs locally on tmux and is tied to the BMAD format, so it is not CI-native [V].
- **Borrow its architecture heavily. Don't integrate it.**

### 6. Hosted autonomous agents

**Factory `droid exec`** ([docs](https://docs.factory.com/cli/droid-exec/overview.md)) [V]. This has the autonomy-level flags you asked about.
- By default it is read-only ("spec mode").
- The autonomy ladder:
  - `--auto low`: edits project files;
  - `--auto medium`: adds installs, builds, tests and `git commit`/`checkout`/`pull`, but no push or sudo;
  - `--auto high`: adds push, deploys and migrations;
  - `--skip-permissions-unsafe`: cannot be combined with `--auto`, and command blocks still apply.
- **It fails fast.** If an action needs a higher level, it stops, exits non-zero, and makes "no partial changes".
- Other flags:
  - output: `-o text|json|stream-json|stream-jsonrpc`; the JSON result includes `is_error`, `num_turns` and `session_id`;
  - sessions: `-s/--session-id`, `--fork`;
  - input and models: `-f` (prompt from a file), `-m`, `-r`, `--use-spec`;
  - workspace: `-w/--worktree [name]`, `--cwd`;
  - tools: `--restrict-tools`;
  - auth: `FACTORY_API_KEY`.
- `droid rules check --command '…' --json` lets you test a command against the policy.
- `Factory-AI/droid-action` supports `@droid review/fill/security` [V~]; its license is [U].
- **Missions** ([news](https://factory.com/news/missions)) [V~]:
  - It starts with `/enter-mission`, which includes clarifying questions while scoping.
  - An orchestrator splits the project into milestones, and **each milestone ends with a validation phase**.
  - When validation finds issues, the orchestrator creates follow-up work.
  - Workers hand off through git, with a fresh session per feature.
  - Available on Enterprise and Max plans.
  - The page says `datePublished` is 2025-02-26 [V], which looks like a CMS error [I].
- License: proprietary.

**Devin** ([v3 get-session](https://docs.devin.ai/api-reference/v3/sessions/get-organizations-session.md)) [V]
- Session `status` ∈ `new|claimed|running|exit|error|suspended|resuming`. A separate `status_detail` ∈ `working|waiting_for_user|waiting_for_approval|finished`, plus suspension reasons such as `usage_limit_exceeded` and `out_of_credits`.
- A session can return a `structured_output` object, and sending a message resumes a suspended session [V].
- Devin CLI: `devin -p` with `--permission-mode normal|accept-edits|smart|dangerous`. CI also needs `--respect-workspace-trust false`, and `--export` writes the transcript ([commands](https://docs.devin.ai/cli/reference/commands.md)) [V].
- License: proprietary.

**Google Jules** ([API reference](https://developers.google.com/jules/api/reference/rest/v1alpha/sessions)) [V]
- The API is at `jules.googleapis.com/v1alpha`. Session states: `QUEUED, PLANNING, AWAITING_PLAN_APPROVAL, AWAITING_USER_FEEDBACK, IN_PROGRESS, PAUSED, FAILED, COMPLETED`.
- Session options: `requirePlanApproval`, `automationMode: AUTO_CREATE_PR`. Actions: `:sendMessage`, `:approvePlan` [V~].
- Jules Tools CLI: `jules remote new --repo <org/repo> --session "<prompt>"` [D [Google blog](https://developers.googleblog.com/en/meet-jules-tools-a-command-line-companion-for-googles-async-coding-agent)]. The npm package `@google/jules` is at 0.1.42 (2025-12-16) [V].
- `google-labs-code/jules-action` is MIT, with inputs `prompt`, `jules_api_key` and `starting_branch` [V~].
- License: the service is proprietary.

**Sweep**
- It pivoted. The README says "We're now building an AI coding assistant for JetBrains" [V~].
- Its LICENSE is the **"Sweep Enterprise Edition (EE)" license**: commercial use needs a subscription [V~]. **Ignore.**

**Cursor** ([CLI headless](https://cursor.com/docs/cli/headless.md), [Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints.md)) [V]
- CLI: `agent -p [--force|--yolo] --output-format text|json|stream-json`, auth `CURSOR_API_KEY`.
- Cloud API: `POST https://api.cursor.com/v1/agents` takes `prompt.text`, `repos[].url/startingRef`, `autoCreatePR` and `workOnCurrentBranch`.
- Agent status is `ACTIVE|IDLE|ARCHIVED`. Run status is `CREATING|RUNNING|FINISHED|ERROR|CANCELLED|EXPIRED`.
- Only one active run per agent is allowed (otherwise `409 agent_busy`). Follow-ups go to `POST /v1/agents/{id}/runs`.
- Bugbot reads `.cursor/BUGBOT.md` rules, and its Autofix starts a cloud agent [V~].
- License: proprietary.

### Summary table

| Name | What to borrow | Integrate? | License |
|---|---|---|---|
| Ralph (Huntley / Playbook) | Fresh context per loop, disk as state, plan vs build modes, backpressure | No (pattern only) | None found (Playbook) [V] |
| Anthropic ralph-loop / ralph-wiggum | Stop-hook re-feed, promise tag, max iterations | No (interactive only) | Apache-2.0 (plugins-official) / All rights reserved (claude-code) [V] |
| frankbria/ralph-claude-code | Two-condition exit, circuit breaker thresholds, status.json | No | MIT [V] |
| OpenSpec 1.14.0 | Change folder layout, `--json` CLI, delta archive | **Yes, main format** (beware the four traps above) | MIT [V] |
| Kiro specs + kiro-cli | `.kiro/specs` format, headless flags, exit codes | **Yes** (format and implementer backend) | Proprietary [I] |
| Kiro Crew Task Runner / autonomous agent | Retry/replan caps, cycle detection, review-from-diff, Paused-on-uncertain-recovery, "Needs attention" | No | Proprietary [I] |
| Spec Kit 1.1.0 | Converge, max-3 clarification markers, `runs/<id>/state.json+log.jsonl`, gates | Optional adapter | MIT [V] |
| Taskmaster | `next` algorithm, dependency validation | No (Commons Clause) | MIT + Commons Clause [V] |
| Ruflo (claude-flow) | Nothing essential | No | MIT [V] |
| Agent OS v3 | Inject standards into implementer context | No | MIT [V] |
| BMAD build-auto | Frontmatter status machine, `blocked_reason` | No | MIT + trademarks [V] |
| **bmad-loop** | Whole architecture: deterministic loop, validate, dry-run, resume, resolve, journal, ATTENTION, worktrees | No (tmux, BMAD-specific); copy the design | MIT [V] |
| Factory droid exec / Missions | **Autonomy ladder**, fail-fast exit, `--worktree`, validate each milestone → follow-up work | Optional backend | Proprietary |
| Devin | Two-level status (`status` + `status_detail` incl. `waiting_for_user`) | Optional backend (API) | Proprietary |
| Jules | `AWAITING_USER_FEEDBACK` / `AWAITING_PLAN_APPROVAL` states | Optional backend (API, GitHub Action) | Proprietary (action MIT [V~]) |
| Cursor CLI / Cloud Agents / Bugbot | Run vs agent status split, single active run lock | Optional backend | Proprietary |
| Sweep | Nothing | No | Sweep EE license [V~] |

### Design implications for the harness (all [I])

1. **Keep the LLM out of the control loop.** bmad-loop, Kiro Task Runner and Factory Missions all arrived at the same design: a deterministic orchestrator, fresh sessions per stage, and verification against the diff and test results rather than the agent's own report.
2. **"Done" needs both the agent's claim and a deterministic check.** The verifier must fail closed, unlike Kiro's review exceptions, which count as "passed".
3. **Default breaker settings:**
   - no progress after 3 iterations;
   - the same error hash seen 3 times;
   - 3 retries per task and 2 replans;
   - a hard cap on total tasks;
   - a stall watchdog;
   - an iteration cap.
4. **Model the human-question state explicitly.** Jules, Devin, Kiro and BMAD all have one. Write `questions.md`, set `status=awaiting_human` with a reason, and cap open questions at about 3, as Spec Kit does.
5. **Use Factory's ladder as our harness-level `autonomy` setting,** mapped onto each CLI's flags: Kiro `--trust-tools`, Devin `--permission-mode`, Cursor `--force`, Claude `--permission-mode`.
6. **Put run state in `.harness/runs/<id>/`:**
   - `state.json`;
   - `journal.jsonl`;
   - `ATTENTION`;
   - commands `validate` (doctor), `run --dry-run`, `resume` and `resolve`.
7. **Never call `openspec archive --yes` without checking first.** Read `list --json` and require `completedTasks==totalTasks` and a recorded verifier pass before archiving.

No files were written apart from temporary downloads in the session scratchpad.


---

# Part 3 — Autonomy levels: what L4 means


**Verdict:** No shared standard for coding agents exists, and frameworks use "L4" for different things. Most of the frameworks that are explicitly modelled on SAE J3016 do agree on one point. **At L4 the human no longer reviews the code, and the system handles its own fallback inside a declared domain.** The human sets intent, answers blocking questions and signs off at a few pre-declared gates. If our merge gate means a human reads the diff, the harness is L3 in those frameworks. It is L4 only if the merge gate approves *evidence* (verifier report, tests, conformance to the spec) rather than the code itself.

Labels: [V] verified from the primary source, [D] secondary source, [I] my inference, [U] unverified.

### Comparison table

| Source | Date | Levels | L4 (or equivalent) | Human role at L4 | URL |
|---|---|---|---|---|---|
| **SAE J3016** chart [V]; definitions [D] | 2021 (J3016_202104) | L0–L5 driving | "These features can drive the vehicle under limited conditions and will not operate unless all required conditions are met"; "will not require you to take over driving" | Not a fallback. At L3, by contrast, "When the feature requests, you must drive" | [chart](https://media.whichcar.com.au/uploads/2022/03/781682df-sae-j3016-visual-chart_5.3.21.pdf), [sae.org](https://www.sae.org/standards/content/j3016_202104) |
| **Sourcegraph**, Quinn Slack [V] | 2023-10-04 | 0 none, 1 completion, 2 creation, 3 supervised automation, 4 full automation, 5 AI-led autonomy (explicitly SAE-modelled) | "humans are no longer expected to review the final code output" | Gives the goal, like a CEO or PM. At L3 the human still "should perform a high-level review of the final code output", may answer clarifying questions, and is the fallback, like SAE L3 | [link](https://sourcegraph.com/blog/levels-of-code-ai) |
| **Dan Shapiro**, "Five Levels" [V] | 2026-01-23 | 0 to 5: spicy autocomplete through to the dark factory (NHTSA-modelled) | "a robotaxi… you're a PM. You write a spec. You argue with it about the spec… You review plans. Then you leave for 12 hours, and check to see if the tests pass." | Writes and approves the spec, checks outcomes. L3 is "the human in the loop… Your life is diffs." L5 is "a black box that turns specs into software" | [link](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/) |
| **Feng, McDonald, Zhang** (UW / Knight Institute) [V] | arXiv v1 2025-06-14, v2 2025-07-28 | L1 operator, L2 collaborator, L3 consultant, L4 approver, L5 observer | User "only required to interact with the agent when the agent encounters a blocker it cannot resolve on its own": a failure state, missing credentials, or "signing off on consequential actions" | Sets approval conditions *before* the run. The plan is shown "for transparency" and the agent does not ask for feedback on it. At L5 the only control is "an emergency off-switch" | [arXiv](https://arxiv.org/abs/2506.12469), [Knight](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents-1) |
| **Google DeepMind**, "Levels of AGI" [V] | 2023-11, v5 2025-09 | Autonomy 0–5: tool, consultant, collaborator, expert, agent | L4 "AI as an Expert": "AI drives interaction; human provides guidance & feedback or performs subtasks" | Guidance. L5 is "fully autonomous" but "knows when to consult humans" | [link](https://arxiv.org/html/2311.02462v5) |
| **Gartner** press release [V] | 2026-05-26 | L1 Observe, L2 Advise, L3 Act with Approval, L4 Act Autonomously (four levels, so L4 is the top) | "Execute actions independently within defined guardrails, with humans reviewing exceptions, audit logs and aggregated outcomes" | On the loop. Governance requires "continuous monitoring, enforced guardrails, rapid rollback mechanisms, circuit breakers" | [link](https://gartner.com/en/newsroom/press-releases/2026-05-26-gartner-says-applying-uniform-governance-across-ai-agents-will-lead-to-enterprise-ai-agent-failure) |
| **Addy Osmani** [V] | 2026-07-02 | 0 assist, 1 supervised action, 2 scoped delegation, 3 goal-driven, 4 parallel delegation, 5 managed-by-exception | L4 is about **parallelism**: "Each agent works on an isolated slice." L5: a manager agent dispatches workers, verifies, retries and escalates | On the loop from L4 ("management by exception"). Also: "The autonomy level should follow the verification process, not the task name" | [link](https://addyosmani.com/blog/agentic-autonomy-levels/) |
| **Swarmia** [V] | 2026-03-19 | 1 assistive, 2 conversational, 3 task agent, 4 autonomous teammate, 5 agentic avalanche | L4 is about **initiative**: "picks work items on its own… without a human initiating each task" | Quality gate on PRs. L3 is "hand off a task and come back to a pull request" | [link](https://www.swarmia.com/blog/five-levels-ai-agent-autonomy/) |
| **"Oversight Ladder"** (Dominik, ddd.consulting) [V] | 2026-07-25 | 1 Assist, 2 Review, 3 Checkpoint, 4 Orchestrate, 5 Autonomous (SAE-inspired) | "Several agents work in parallel under a senior person who directs and reviews. Agents cannot merge their own work." | Directs and reviews. L5: "A person reviews the batch afterward" | [link](https://dev.to/dominik_ddd/the-oversight-ladder-the-five-levels-of-ai-coding-autonomy-1d94) |
| **Steve Yegge**, "Welcome to Gas Town" [D] (Medium blocked me) | 2026-01 | 8 stages, from "Zero or Near-Zero AI" to "Building your own orchestrator" | A tooling-maturity scale, not an oversight scale. Stage 4 is "In IDE, wide agent" | n/a | [primary](https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04), [via](https://notes.dsebastien.net/30+Areas/33+Permanent+notes/33.02+Content/AI+Coding+Maturity+Levels) |
| **Factory Droid** docs [V] | current | Off / Low / Medium / High | Permissions per action: "sets the highest-risk work Droid can run without pausing for approval". Not end-to-end autonomy | For CI: "choose the lowest `droid exec --auto` level that allows the workflow to complete"; read-only is the default | [link](https://docs.factory.com/cli/user-guides/auto-run) |
| **Microsoft Azure SRE Agent** [V] | doc 2026-06 | Review / Autonomous, set per response plan | Autonomous: "executes immediately and reports what it did" | "Start with review mode… two to four weeks… switch those specific triggers to Autonomous." The page contradicts itself on which mode is the default | [link](https://learn.microsoft.com/en-us/azure/sre-agent/run-modes) |
| **GitHub Copilot cloud agent** [V] | 2025–26 | No numbered levels. Blog frames it as "pair to peer" | Structurally L3: the agent "cannot approve or merge a pull request", the person who asked for the PR cannot approve it, and the agent pushes only to `copilot/` branches | Mandatory independent human review | [docs](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations), [blog](https://github.blog/news-insights/product-news/from-pair-to-peer-programmer-our-vision-for-agentic-workflows-in-github-copilot/) |
| **Sheridan & Verplank** levels (via MIT 16.422 slides) [D] | 1978 | 10 levels of decision and action selection | Approve: L5 "executes that suggestion if the human approves". Veto: L6 "allows the human a restricted time to veto". Inform: L7 "executes automatically, then necessarily informs humans" | Ranges from approving each action to being informed afterwards | [slides](https://ocw.iti.hr/courses/aeronautics-and-astronautics/16-422-human-supervisory-control-of-automated-systems-spring-2004/lecture-notes/020504hmancenter.pdf) |

**Other sources checked**
- **Anthropic** (2026-02-18) [V] defines no levels. Its data shows that on complex tasks "Claude Code asks for clarification more than twice as often as humans interrupt it." Experienced users auto-approve more than 40% of the time. It also warns that rules requiring humans "to approve every action, will create friction without necessarily producing safety benefits." [link](https://www.anthropic.com/research/measuring-agent-autonomy)
- **Swyx / Latent Space** [U]: I found no levels framework authored by swyx. The "Anatomy of Autonomy" post only reproduces the SAE levels [V]. [link](https://www.latent.space/p/agents)
- **Latent Space "harness-eng" episode** (2026-04-07) [V], with OpenAI's Ryan Lopopolo: a 1M-line codebase with 0% human-written code and no human review before merge. Review agents merge unless an issue is flagged P0. Humans write specs and context and sample the code after merge. [link](https://www.latent.space/p/harness-eng)
- **StrongDM** [D]: rules are "Code must not be written by humans / reviewed by humans", and success is judged on holdout "scenarios". This is Shapiro's L5 in practice. [link](https://simonwillison.net/2026/Feb/7/software-factory/)
- **Two newer arXiv papers** [V]:
  - Zheng et al. (2026-07) separate "Allowed Autonomy Levels" from "Autonomous Capability Levels". [link](https://arxiv.org/abs/2607.23438)
  - Bui & Evangelopoulos (2026-05) treat *proactivity* (Reactive, Scheduled, Situation-Aware) as a separate axis from autonomy. [link](https://arxiv.org/abs/2605.06717)
- **Thoughtworks** (Böckeler, 2025-08) [D]: concluded that a supervising human "remains essential". [link](https://www.martinfowler.com/articles/pushing-ai-autonomy.html)
- **Not found** [U]: Cognition, Amp, or a Dohmke-authored levels framework.

### Where the frameworks disagree

1. **The level numbers don't line up.**
   - Sourcegraph and Shapiro both put "human reviews every diff" at L3 and "no code review" at L4 [V].
   - The Oversight Ladder's L4 still has a human reviewing and agents unable to merge. That is Sourcegraph's L3 [I].
   - DeepMind's L4 ("human provides guidance & feedback") is close to Feng's L3 [I].
   - For Gartner, L4 is the highest level there is [V].
2. **They measure different things.**
   - Addy (L4 = parallel agents) and Yegge measure *orchestration*.
   - Swarmia measures *initiative* (who starts the work).
   - Factory measures *permission per action*.
   - SAE, Sourcegraph, Shapiro and Feng measure *who carries the fallback and the review* [I].
   - Parasuraman's model already said that automation level varies by function: acquiring information, analysing it, choosing an action, carrying it out [D]. So the harness can sit at different levels for different stages [I].
3. **When "on the loop" begins.**
   - Addy: L4 [V].
   - Feng: the user becomes "more passive" at L4 [V].
   - SAE: at L3 the human is already not driving but must stay ready to take over [V].
4. **Human-started vs self-started work.** Our harness starts from a spec a human writes. That is L4 under SAE, Feng, Sourcegraph and Shapiro, but only L3 under Swarmia [I].
5. **Approving the spec.** Shapiro's L4 explicitly includes arguing about the spec and reviewing plans [V]. Feng's L4 shows the plan without asking for feedback on it [V]. My read is that approving a spec is like setting a robotaxi's destination: it sets intent and does not lower the level [I].

### Working definition of L4 for the harness [I]

> **L4:** Inside a declared **operational design domain (ODD)**, the harness takes an **approved spec** to a **merge-ready change**. No human reviews intermediate steps or diffs. The harness runs its **own fallback**: verifier finds a failure, the spec is fixed, the work is retried within a set limit. When it cannot continue inside the ODD, it reaches a defined **minimal-risk condition** and escalates. It never needs a human to take over the work mid-run.
>
> **Humans do four things:**
> - (a) approve the spec, which sets intent;
> - (b) answer escalated *blocking* questions about intent, credentials or consequential actions, asynchronously, with the system already in a safe state;
> - (c) sign off at pre-declared gates (merge to a protected branch, archive) **based on the evidence package, not on reading the diff**;
> - (d) audit exceptions and aggregated outcomes, as in Gartner's L4.
>
> If a human must read diffs, it is L3. If there is no merge gate at all, it is L5 (StrongDM, OpenAI's harness, Feng's observer).

**What the ODD means for us** [I], adapting SAE's definition [D]. SAE's ODD covers "environmental, geographical, and time-of-day restrictions, and/or the requisite presence or absence of certain traffic or roadway characteristics" ([statute quoting J3016](https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2024RS/L1ICWYW-1.pdf)). For the harness, the ODD would be:
- which repos and paths it may touch, and which languages;
- which task classes are in scope (for example excluding schema migrations, auth, infra and dependency bumps);
- minimum spec quality: acceptance criteria that can be tested;
- a test or verification oracle that exists and covers the change;
- a ceiling on tool and command risk, using Factory-style tiers;
- token, time and retry budgets.

Following SAE's "will not operate unless all required conditions are met" [V], an intake check should **reject specs that fall outside the ODD** before any work starts, rather than letting them fail partway through.

**Minimal-risk condition.** J3016 defines it as "a stable, stopped condition… when a given trip cannot or should not be continued" [D]. What separates L3 from L4 is whether the *system*, not the human, gets to that condition [D] ([Stanford CIS](https://cyberlaw.stanford.edu/blog/2022/01/deep-weeds-levels-driving-automation-lurks-ambiguous-minimal-risk-condition)). Walker Smith warns that the definition is ambiguous: stopping in a live traffic lane could technically count [D].

So the harness must spell out what the *expected* safe state is [I]:
- nothing written to protected branches, and no partial merge;
- work kept on an isolated branch or worktree, with state checkpointed so it can resume cleanly;
- failing evidence attached;
- an escalation filed with one precise question;
- budgets released.

The harness version of the "car stopped in a live lane" failure is a PR that looks green but isn't right.

Two further design rules:
- Autonomy is a **design decision separate from capability** (Feng [V]; Zheng et al.'s allowed vs. capable [V]). Declare the allowed level for each slice of the ODD and raise it only on evidence, such as Microsoft's 2–4 weeks in Review mode [V] and Addy's "follow the verification process" [V].
- Copy GitHub's structural controls [V]: the implementer agent cannot approve or merge its own work, and the person who requested a change cannot be the one who approves it.

### Risks
- **Saying "L4" will be misread.** Every claim we make about our level should name the framework, e.g. "L4 in the Sourcegraph/Shapiro/Feng sense" [I].
- **Some sources are secondary.** The SAE definitions come from a statute that transcribes J3016, and the Yegge stages come from a secondary site [D]. The full J3016 standard is behind a paywall, so I could not quote it first-hand.

---

# Part 4 — GitHub Actions mechanics for agent loops


Researched 2026-10-03. Most pages were pulled as raw markdown from the docs.github.com article API, plus action READMEs and github.blog changelogs.

**Labels:** [V] = verified in a primary source (docs.github.com, the github.blog changelog, or the official action's own README). [D] = secondary source (community posts, third-party sites). [I] = my inference. [U] = unverified.

**Source key** (cited by tag below):
- EVT https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- SYN https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- CONC https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
- TRIG https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
- TOK https://docs.github.com/en/actions/concepts/security/github_token
- SKIP https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs
- CMD https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands
- LIM https://docs.github.com/en/actions/reference/limits
- CANCEL https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation
- CTX https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
- CHK https://docs.github.com/en/rest/checks/runs
- STAT https://docs.github.com/en/rest/commits/statuses
- ENV https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- CACHE https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching
- ART https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts
- UA https://github.com/actions/upload-artifact (README)
- DA https://github.com/actions/download-artifact (README)
- SHREF https://docs.github.com/en/actions/reference/runners/self-hosted-runners
- SECUSE https://docs.github.com/en/actions/reference/security/secure-use
- ARC https://docs.github.com/en/actions/concepts/runners/actions-runner-controller
- LARGER https://docs.github.com/en/actions/concepts/runners/larger-runners
- SEC https://docs.github.com/en/actions/concepts/security/secrets
- USESEC https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- OIDC https://docs.github.com/en/actions/concepts/security/openid-connect
- RS https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- RULES https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- APPTOK https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app
- CGAT https://github.com/actions/create-github-app-token (README)
- APPROVE https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks
- CL-Q https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues
- CL-BOT https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/
- CL-RUNID https://github.blog/changelog/2026-02-19-workflow-dispatch-api-now-returns-run-ids
- CL-25 https://github.blog/changelog/2025-12-04-actions-workflow-dispatch-workflows-now-support-25-inputs/
- CL-CACHE https://github.blog/changelog/2025-11-20-github-actions-cache-size-can-now-exceed-10-gb-per-repository/

### 1. Triggers

**`push`**
- No event is created "if more than 5,000 branches are pushed at once", and none for tags "when more than three tags are pushed at once". [V EVT#push]
- The event fires for workflow files on any branch, "including workflows that are not merged into the default branch". [V EVT#push]
- `paths` and `paths-ignore` cannot be combined for the same event, and "Path filters are not evaluated for pushes of tags". [V SYN#onpushpull_requestpull_request_targetpathspaths-ignore]
- Diff rules: pushes to an existing branch use a two-dot diff of the before and after SHAs; pull requests use a three-dot diff. [V SYN, "Git diff comparisons"]
- Limits, quoted [V SYN]:
  - "If a push contains more than 1,000 commits, the workflow will **always** run."
  - "If generating the diff times out, the workflow will **always** run."
  - "If the generated diff contains more than 3,000 files and the files the workflow filter matches are not in the first 3,000 returned by the filter, the workflow will **not** run."
- Older docs and community threads say 300 files. The current docs say 3,000. I found no changelog for the change. [U on when it changed]
- `branches` and `branches-ignore` cannot be combined. A later `!pattern` excludes a ref. [V SYN]
- An agent commit that edits `tasks.md` matches a `paths: openspec/**` filter. So a push made with any token that is allowed to trigger workflows will re-trigger the harness. [I]

**`pull_request`**
- Default activity types are `opened`, `synchronize` and `reopened`. `labeled` and `unlabeled` must be listed explicitly in `types`. [V EVT#pull_request]
- "Workflows will not run on `pull_request` activity if the pull request has a merge conflict." [V EVT]
- With fork PRs, secrets are not passed (except `GITHUB_TOKEN`), and `GITHUB_TOKEN` is read-only. [V EVT, "Workflows in forked repositories"]

**`pull_request_target`**
- It runs in the context of the base repository's default branch, and it runs even when the PR has a merge conflict. [V EVT#pull_request_target]
- Warning: running untrusted code on it can lead to "cache poisoning and granting unintended access to write privileges or secrets." Docs: "Avoid using this event if you need to build or run code from the pull request." [V EVT]

**`issues` / `issue_comment`**
- Both only trigger if the workflow file exists on the default branch. `GITHUB_SHA` and `GITHUB_REF` are the default branch, so the workflow must check out the PR branch itself. [V EVT#issue_comment]
- `issue_comment` fires for both issues and PRs. Docs: "use the `github.event.issue.pull_request` property in a conditional" to tell them apart. [V EVT]
- Use `github.event.comment.author_association` to decide whether a commenter is authorized. [I]

**`workflow_dispatch`**
- Input types are `boolean`, `choice`, `number`, `environment` and `string`. [V SYN]
- At most 25 top-level inputs and a 65,535-character payload. [V EVT; the limit went from 10 to 25 on 2025-12-04 per CL-25]
- `GITHUB_REF` is the "Branch or tag that received dispatch". [V EVT]
- Docs: "Once a workflow has run at least once, you can dispatch it against any branch or tag via the GitHub API or GitHub CLI." [V EVT]
- Since 2026-02-19, the dispatch API accepts `return_run_details` and returns 200 with `workflow_run_id`, `run_url` and `html_url`. GitHub CLI 2.87.0+ returns the run URL. [V CL-RUNID]

**`repository_dispatch`**
- `event_type` is limited to 100 characters. `client_payload` allows at most 10 top-level properties and 65,535 characters. [V EVT]
- It only triggers from the default branch's workflow file, and `GITHUB_REF` is the default branch. [V EVT]

**`schedule`**
- "The shortest interval … is once every 5 minutes." [V EVT#schedule]
- Runs "can be delayed during periods of high loads … If the load is sufficiently high enough, some queued jobs may be dropped." [V EVT]
- It runs on the default branch only. [V EVT]
- "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days." [V EVT]
- An IANA `timezone` option now exists. [V EVT]

**`workflow_run`**
- Docs: "You can't use `workflow_run` to chain together more than three levels of workflows". In A→B→…→F, E and F do not run. [V EVT#workflow_run]
- It uses the default-branch workflow file only. It "is able to access secrets and write tokens, even if the previous workflow was not", which is a security risk. [V EVT]

**Label-based triggers**
- These are `pull_request` or `issues` with `types: [labeled]`. [V EVT]
- Labels added with `GITHUB_TOKEN` create no run (see §3). [V TOK]

### 2. Concurrency

- **Contexts allowed in the group expression.** At workflow level, only `github`, `inputs` and `vars`. At job level, also `needs`, `strategy` and `matrix`. [V SYN#concurrency, CONC]
  - So a spec ID taken from the changed files cannot be a workflow-level group on `push`. You need a router job plus a matrix or dispatch. [I]
- **Default semantics:** "at most one running job or workflow in a concurrency group … By default, any existing `pending` job or workflow in the same concurrency group will be canceled and the new queued job or workflow will take its place." `cancel-in-progress: true` also kills the running one. [V CONC]
- **New queueing option** (changelog 2026-05-07):
  - `queue: single` is the default.
  - `queue: max` allows "Up to 100 jobs or workflow runs can be `pending` … When the queue is full, any additional jobs or workflow runs are canceled."
  - "The combination of `queue: max` and `cancel-in-progress: true` is not allowed" and causes a validation error. [V CONC, SYN, CL-Q]
  - LIM lists a "Concurrency group queue: 100 workflow runs / concurrency group". [V LIM]
- **Ordering** is FIFO "according to the time each one started waiting … ordering is not guaranteed." [V CONC]
- **Scope:** group names are case-insensitive and apply repo-wide across workflows. Docs: "concurrency group names must be unique across workflows to avoid canceling in-progress jobs or runs from other workflows." [V CONC]
  - The same rule lets you deliberately share one per-spec group between the implementer and verifier workflows to get a mutex. [I]

### 3. GITHUB_TOKEN recursion rule, chaining and loop guards

- **Quote** [V TOK; same text in TRIG]: "When you use the repository's `GITHUB_TOKEN` to perform tasks, events triggered by the `GITHUB_TOKEN` will not create a new workflow run, with the following exceptions:
  * `workflow_dispatch` and `repository_dispatch` events always create workflow runs.
  * `pull_request` events with the `opened`, `synchronize`, or `reopened` activity types: … create workflow runs in an **approval-required** state … Other `pull_request` activity types (such as `labeled`, `edited`, or `closed`) do not create workflow runs."
- **Example from the docs:** "if a workflow run pushes code using the repository's `GITHUB_TOKEN`, a new workflow will not run". [V TOK]
- **Approval-required behaviour is new:** changelog 2026-06-11. A user with write access must click "Approve workflows to run". [V CL-BOT, TOK]
- **Deliberate chaining:** "use a GitHub App installation access token or a personal access token instead of `GITHUB_TOKEN`". This also lets `pull_request` runs start without approval. [V TRIG]
- **App installation tokens:**
  - They "expire after 1 hour". [V APPTOK]
  - With `actions/create-github-app-token@v3`, current inputs are `client-id` and `private-key`, with optional `permission-*`, `owner` and `repositories`. [V CGAT]
  - The token is revoked in the action's post step unless `skip-token-revoke: true`, so it "cannot be passed to another job". [V CGAT]
  - The README shows how to commit as `<app-slug>[bot] <id+slug[bot]@users.noreply.github.com>`. [V CGAT]
- **Fine-grained PATs** are limited to a single resource owner. Org approval may be required. GitHub auto-removes PATs unused for a year. [V https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens]
- **Actor contexts:** `github.actor` is "The username of the user that triggered the initial workflow run". `github.triggering_actor` is the user who initiated the run, and differs from `actor` on re-runs. Re-runs use the privileges of `github.actor`. [V CTX]
  - App pushes show as `slug[bot]`. [I]
- **Loop-guard options:**
  - `branches-ignore: ['harness/**']`, which prevents the run from being created at all. [I from V SYN filters]
  - Job-level `if: github.actor != 'x[bot]'`. A run is still created but skipped, so it is noisy. [I]
  - A commit trailer check on `github.event.head_commit.message`, such as `Harness-Run: <run_id>`. [I]
  - An attempt budget stored in a state file. [I]
- **GitHub does not protect against `workflow_dispatch` self-loops.** Dispatches always create runs. [V TOK] No documented depth limit for dispatch chains was found. [U]
- **Rate limits:** 1,500 trigger events per 10 seconds per repo, and 500 runs queued per 10 seconds. [V LIM]

### 4. Skip instructions

- `[skip ci]`, `[ci skip]`, `[no ci]`, `[skip actions]` and `[actions skip]` work in "the commit message in a push, or the HEAD commit of a pull request". [V SKIP]
- The alternative is a final trailer `skip-checks:true` or `skip-checks: true`, preceded by two empty lines. Use `git commit --cleanup=verbatim` so Git keeps the blank lines. [V SKIP]
- "Skip instructions only apply to the `push` and `pull_request` events", for example not `pull_request_target`. [V SKIP] They do not stop dispatch, schedule or comment triggers. [I]
- **Side effect:** checks of skipped workflows "remain in a 'Pending' state", and PRs that require them are blocked from merging. [V SKIP]

### 5. Outputs and summaries

- **Job outputs:** "a maximum of 1 MB per job. The total of all outputs in a workflow run can be a maximum of 50 MB. Size is approximated based on UTF-16 encoding." [V SYN#jobsjob_idoutputs]
  - They are evaluated on the runner at job end. Outputs containing secrets are redacted and not sent. [V SYN]
  - Downstream jobs read them through `needs.<job>.outputs`. [V SYN]
- **Step outputs** are written to `$GITHUB_OUTPUT`; multiline values use a `name<<DELIM` block. [V CMD]
- **Job summaries** (`$GITHUB_STEP_SUMMARY`): "each step is restricted to a maximum size of 1MiB … A maximum of 20 job summaries from steps are displayed per job". An oversized upload creates an error annotation but does not fail the step. [V CMD, "Step isolation and limits"]
- **Implication:** outputs are not a state store. Put state in git and use artifacts for transcripts. [I]

### 6. Per-spec status reporting

- **Checks API**
  - Docs: "Write permission … is only available to GitHub Apps. OAuth apps and authenticated users can view … but they are not able to create them." [V CHK]
  - `GITHUB_TOKEN` is an App installation token [V TOK], and "`checks: write` permits an action to create a check run". [V SYN#permissions]
  - Limits:
    - 1,000 check runs with the same name per suite; older ones are auto-deleted. [V CHK]
    - 50,000 check runs per suite. [V LIM]
    - At most 3 `actions` buttons per check run. [V CHK]
    - Annotations are capped at 50 per request. [V CHK]
  - The `check_run` event "does not trigger workflows if the check run's check suite was created by GitHub Actions". So "Resume" buttons on a check run need your own App or webhook to handle them. [V EVT#check_run; I]
  - Check runs created with `GITHUB_TOKEN` may attach to an arbitrary Actions check suite in the UI. [U]
- **Commit statuses**
  - `context` is a free-form label, so `harness/spec/<id>` works. States are `error`, `failure`, `pending` and `success`. [V STAT]
  - "There is a limit of 1000 statuses per sha and context". [V STAT]
  - The combined status is failure if any context fails, and pending if any context is pending. [V STAT]
  - `GITHUB_TOKEN` needs `statuses: write`. [I]
- **Required checks** can pin "an app as the expected source of status updates", which prevents spoofing. [V RULES#require-status-checks-to-pass-before-merging]
- **Environments as a human gate**
  - Up to 6 required reviewers, one approval suffices, and there is an optional "prevent self-reviews". [V ENV]
  - A job can wait up to 30 days for approval ("Gate approval time"). The wait timer is 1–43,200 minutes. [V LIM, ENV]
  - Environment secrets are unavailable until the job is approved. [V ENV]
  - **Plan caveat:** on Free, Pro and Team, required reviewers and wait timers "are only available for public repositories". [V ENV]
  - Fork-PR runs awaiting approval expire after 30 days. [V APPROVE]

### 7. Artifacts and caches

- **Artifacts**
  - Retention defaults to 90 days, settable 1–90, and can be changed in repository settings. [V UA]
  - Docs: "Artifacts created by upload-artifact@v4 are immutable". Several jobs uploading to the same artifact is not supported. `overwrite: true` replaces the artifact with a new ID. [V UA]
  - Limit of 500 artifacts per job. [V UA] The README examples now use `@v7`. [V UA]
  - Cross-run or cross-repo download needs `github-token` (with `actions: read`), `repository` and `run-id`. [V DA]
  - Deleting a run deletes its artifacts. [V ART]
  - Storage quotas: 500 MB on Free, 1 GB on Pro, 2 GB on Team, 50 GB on Enterprise Cloud. [V LIM]
  - No per-artifact maximum size is documented. [U]
- **Caches**
  - Default limit is 10 GB per repo. It can be raised pay-as-you-go: up to 10 TB for user-owned repos, otherwise up to the org or enterprise cap. A 2025-11-20 changelog added configurable size and retention policies. [V CACHE, CL-CACHE]
  - Entries not accessed in more than 7 days are evicted by default. Eviction is least-recently-accessed first. [V CACHE]
  - Docs: "You cannot change the contents of an existing cache." [V CACHE]
  - Scope: a run can restore from its own branch, the default branch, and (for a PR) the base branch, but not from sibling or child branches. [V CACHE]
  - Rate limits: 200 uploads per minute and 1,500 downloads per minute per repo. [V LIM]
  - **New trust rule:** only `push`, `workflow_dispatch`, `repository_dispatch`, `delete`, `registry_package`, `page_build` and `schedule` can write default-branch-scoped caches. Runs from `issue_comment`, `pull_request_target`, `workflow_run` and similar get read-only access unless `cache-mode: write` is set (values: `read`, `write`, `write-only`, `none`). [V CACHE]
  - Do not store secrets in caches. [V CACHE]
- **Verdict:** caches are best-effort (evictable, immutable keys, branch-scoped), so they are unfit as authoritative resume state. Artifacts are immutable per run, which suits logs and transcripts. Git commits are the right state store. [I]

### 8. Timeouts and cancellation

- **Hard limits** [V LIM]:
  - GitHub-hosted job: 6 hours. "the job is terminated and fails". This applies to larger runners too.
  - Self-hosted job: 5 days.
  - Workflow run: 35 days, including waiting and approval time.
  - Self-hosted job queue: 24 hours.
  - Re-runs: 50 per run.
  - Matrix: 256 jobs.
- **`timeout-minutes`:** the job default is 360. A step-level `timeout-minutes` has a "Maximum: 360". [V SYN]
- **`GITHUB_TOKEN` lifetime:** "expires when the job finishes or after a maximum of 24 hours". On GitHub-hosted runners that means at most 6 hours. On self-hosted runners it "can only be refreshed for up to 24 hours". [V TOK, SYN]
- **Cancellation sequence:**
  1. The server re-evaluates job and step `if:` conditions; `always()` jobs and steps keep running.
  2. The step process receives SIGINT, then SIGTERM after 7.5 seconds, then 2.5 seconds later the process tree is killed.
  3. After 5 minutes everything is forcibly terminated. [V CANCEL]
- Whether `if: always()` cleanup steps run after the 6-hour hard limit is not documented. [U] A step-level timeout fails only that step, so later `always()` steps run. [I]
- **New background steps:** `background: true` with `wait`, `wait-all` and `cancel`, at most 10 concurrent per job. A failure surfaces at the next `wait`. [V SYN#jobsjob_idstepsbackground] This can host a periodic checkpoint or heartbeat process running beside the agent. [I]

### 9. Self-hosted runners

- `--ephemeral` gives one job per runner. JIT runners are created via the REST API. Docs: "autoscaling with persistent self-hosted runners is not recommended". [V SHREF, SECUSE]
- ARC runs ephemeral, container-based runner scale sets on Kubernetes using JIT registration. [V ARC]
- Docs: self-hosted runners "should almost never be used for public repositories". [V SECUSE#hardening-for-self-hosted-runners]
- Environment secrets on self-hosted runners are not isolated. [V ENV]
- Persistent runners "Don't need to have a clean instance for every job", which allows worktrees that survive across jobs. The trade-off is security and stale state. [V https://docs.github.com/en/actions/concepts/runners/self-hosted-runners; I]
- Larger runners offer more CPU, RAM and disk, static IPs and runner groups, with the same 6-hour limit. [V LARGER, LIM]

### 10. Secrets and OIDC

- Repo, org and environment secrets exist. "With the exception of `GITHUB_TOKEN`, secrets are not passed to the runner when a workflow is triggered from a forked repository." [V USESEC, EVT]
- Redaction "is not guaranteed". Use `::add-mask::` for derived values. Secrets larger than 48 KB need a gpg workaround. [V SEC, USESEC]
- OIDC needs `id-token: write`. It yields short-lived cloud credentials valid for the job. [V OIDC, SYN#permissions]
- Repos created after July 15, 2026 get an immutable default `sub` claim that includes the owner and repo IDs, so update cloud trust policies. [V OIDC]
- **AWS:** `configure-aws-credentials` `role-duration-seconds` defaults to 1 hour and allows 900–43,200 seconds. [V for the action README, AWS https://github.com/aws-actions/configure-aws-credentials] The IAM role's MaxSessionDuration must also allow the longer session. [I]
- **GCP:** an `access_token_lifetime` default of 1 hour, with a 1-hour maximum unless an org policy raises it to 12 hours. [V for the action README, https://github.com/google-github-actions/auth]
- **Risk:** a multi-hour Bedrock or Vertex agent run will fail at the 1-hour default unless the credential lifetime is raised. [I]

### 11. Branch protection and rulesets

- Bypass actors can be roles, teams or GitHub Apps. For push rulesets, bypass applies across the fork network. [V RULES, RS]
- Limit of 75 rulesets per repo. Rulesets and branch protection layer, and the most restrictive rule wins. [V RS]
- `github-actions[bot]` (`GITHUB_TOKEN`) is not selectable as a bypass actor. Use a dedicated App and its token. [D https://github.com/orgs/community/discussions/136531]
- Required status checks come in strict and loose forms, with an optional expected source App. [V RULES]

---

### Design implications for the harness

1. **Two-tier triggering.**
   - A cheap router workflow runs on `push` (spec paths, `branches-ignore: harness/**`) and on `workflow_dispatch`. It diffs `before..after`, finds specs with unchecked tasks, and dispatches `harness-run.yml` once per spec with `inputs.spec_id`, using `GITHUB_TOKEN` and `actions: write`.
   - Dispatch is exempt from the recursion rule. Each spec then gets its own run, a 35-day budget, a run ID (`return_run_details`), and workflow-level concurrency.
   - Do not chain with `workflow_run`: it stops after 3 levels.
2. **Concurrency per spec.**
   - Use `group: harness-spec-${{ inputs.spec_id }}` with `cancel-in-progress: false` (never true, because cancellation kills the agent within about 10 seconds).
   - If runs re-read repo state each time (level-triggered), keep the default `queue: single`: coalescing pending runs is what you want. Use `queue: max` only if each run carries a unique, non-replaceable payload.
   - Implementer and verifier should share the same group string so one spec has one writer.
3. **Choose the push token on purpose.**
   - **State or checkpoint commits:** push with `GITHUB_TOKEN`. That creates no recursion for free, and the harness continues by explicit self-dispatch.
   - **Commits that must trigger PR CI or bypass rulesets:** push with an App token. Mint it in a step right before the push, because it expires after 1 hour; never mint it at checkout before a long agent run.
   - Add loop guards for App pushes: branch filters, an actor check, and a `Harness-Run:` trailer.
4. **Avoid `[skip ci]` on harness commits.** It leaves required checks Pending forever and only covers `push` and `pull_request`.
5. **Plan around the 6-hour limit.**
   - Set step `timeout-minutes: ~300` on the agent and job `timeout-minutes: ~345`.
   - Add an `if: always()` step that commits WIP, writes the state file, and self-dispatches to continue.
   - Optionally run a background heartbeat step that pushes checkpoints every N minutes.
   - State lives in git: `tasks.md` checkboxes plus `.harness/<spec>/state.json` holding the attempt count, last run ID and a lease.
6. **Self-imposed loop budget is mandatory.** For example, stop after K continuations with no newly checked task. Then write `questions.md`, set status `harness/spec/<id>` to `error` with "awaiting answers", and stop.
7. **Human answers.**
   - Path 1: a push of `answers.md` to `harness/**` from a non-bot actor (a separate trigger with paths and an actor check).
   - Path 2: `issue_comment` with `/harness` on the PR. Check `github.event.issue.pull_request` and `author_association`, check out the PR head explicitly (runs default to the default branch), and remember cache is read-only by default.
   - Either path then dispatches the spec run.
8. **Status reporting.** Use a commit status (`harness/spec/<id>`) or a check run via `GITHUB_TOKEN` (`checks: write`). Protect merges with a required check pinned to the harness App. Use an environment with required reviewers for merge or expensive-run gates; on private repos this needs Enterprise Cloud.
9. **Credentials.** Use OIDC to Bedrock or Vertex with a lifetime of at least the job length: AWS `role-duration-seconds` ≤ 43,200; GCP needs the org policy to go beyond 1 hour. Never run the harness on fork PRs or via `pull_request_target` with a PR checkout.
10. **Recovery sweeper.** A `schedule` job every 15–30 minutes (off the top of the hour) re-dispatches specs whose lease is stale. It is best-effort: delays or drops are possible, and it is auto-disabled after 60 days of inactivity in public repos.
11. **Beyond 6 hours or persistent worktrees** requires private-repo self-hosted ephemeral runners via ARC or JIT. Their `GITHUB_TOKEN` caps at 24 hours, so mint App tokens per push.

**Highest-risk items to re-check before building:**
- `queue: max` and the `GITHUB_TOKEN` PR-approval behaviour are 2026 features; confirm on the user's plan and on GHES if used.
- The 3,000-file paths limit has no changelog.
- Whether `always()` steps run after the 6-hour hard kill is undocumented; test it empirically.


---

# Part 5 — GitLab CI mechanics for agent loops


**How I checked this.** I read the raw Markdown source of the GitLab docs from `gitlab-org/gitlab@master` (docs.gitlab.com is built from it), and opened GitLab source files where the docs were silent. The latest release is **19.4.1** (tag dated 2026-09-22). Features marked "19.5" are not yet in a self-managed release. Labels: [V] verified from a primary source, [D] secondary source, [I] inferred, [U] unverified.

### 1. Triggering: `rules:changes`, `rules:exists`, `rules:if`, `workflow`
- **`rules:changes` is always true in some cases** [V]. It "always evaluates to true" for new-branch pipelines and for any pipeline with no Git push event (tag, scheduled, manual). It stays true when a branch is created even if you skip `compare_to`. MR pipelines compare against the target branch. Branch pipelines compare against the previous commit. Source: https://docs.gitlab.com/ci/yaml/#ruleschanges
- **Branch pipelines without an MR** [V]. The diff is "equivalent to `git diff HEAD~`". Scheduled pipelines treat every file as changed. Source: https://docs.gitlab.com/ci/jobs/job_troubleshooting/#jobs-or-pipelines-run-unexpectedly-when-using-changes
- **`compare_to`** [V]. Takes a branch, tag or SHA, must be used together with `paths`, and accepts variables since 17.2. It gives unexpected results with merged-results pipelines and forks. Source: https://docs.gitlab.com/ci/yaml/#ruleschangescompare_to
- **`changes` limits** [V]. At most 50 patterns per section. After 50,000 checks, globs always match. `rules:changes:regexp` was added in 19.2. Same page.
- **`rules:exists`** [V]. At most 50 patterns. The check limit rose from 10k to 50k in 17.7. Patterns combine with OR. It searches the pipeline's project and ref and cannot see artifacts. `exists:project`/`ref` became GA in 17.0. Source: https://docs.gitlab.com/ci/yaml/#rulesexists
  - So `exists` can detect that a `tasks.md` file is present, but not whether it has unchecked boxes [I].
- **Dotenv variables cannot be used in `rules`** [V]. Source: https://docs.gitlab.com/ci/variables/dotenv_variables/
- **`CI_PIPELINE_SOURCE` values** [V]: `api`, `chat`, `external`, `external_pull_request_event`, `merge_request_event`, `ondemand_dast_scan`, `ondemand_dast_validation`, `parent_pipeline`, `pipeline`, `push`, `schedule`, `security_orchestration_policy`, `trigger`, `web`, `webide`. Source: https://docs.gitlab.com/ci/jobs/job_rules/#ci_pipeline_source-predefined-variable
- **Variables usable in rules** [V]. `CI_COMMIT_AUTHOR`, `CI_COMMIT_TITLE` and `CI_COMMIT_MESSAGE` are "Pre-pipeline". `GITLAB_USER_LOGIN` is available at the "Pipeline" phase, so job `rules` can use it. Job-only variables cannot be used in `workflow` or `rules`. Source: https://docs.gitlab.com/ci/variables/predefined_variables/#variable-availability
- **Avoiding duplicate branch + MR pipelines** [V]. The documented pattern is:
  - `if: $CI_PIPELINE_SOURCE == "merge_request_event"`
  - `if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS && $CI_PIPELINE_SOURCE == "push"` → `when: never`
  - `if: $CI_COMMIT_BRANCH`

  The `== "push"` clause keeps the rule from blocking `trigger`/`pipeline`-sourced pipelines. Source: https://docs.gitlab.com/ci/yaml/workflow/#switch-between-branch-pipelines-and-merge-request-pipelines
- **New "Skip branch pipelines for merge requests" setting** [V]. It is a beta project setting added in 19.2, with REST API support in 19.4. It affects only push-triggered pipelines, and the first push that creates the MR still gets a branch pipeline. Source: https://docs.gitlab.com/ci/pipelines/settings/#skip-branch-pipelines-for-merge-requests
- **`workflow:auto_cancel`** [V].
  - `on_new_commit` takes `conservative` (the default), `interruptible` or `none`.
  - `on_job_failure` takes `all` or `none`.
  - `workflow:rules:auto_cancel` overrides these per rule.

  Source: https://docs.gitlab.com/ci/yaml/#workflowauto_cancelon_new_commit
- **`workflow:name`** [V]. Supports variables, and `CI_PIPELINE_NAME` exposes the result. Source: https://docs.gitlab.com/ci/yaml/#workflowname

### 2. `resource_group` (serialization)
- **What it does** [V]. Jobs in the same group are "mutually exclusive across different pipelines for the same project". There is one resource per group. Source: https://docs.gitlab.com/ci/yaml/#resource_group
- **Group names** [V]. Allowed characters are letters, digits, `-`, `_`, `/`, `$`, `{`, `}`, `.` and spaces, and a name cannot start or end with `/`. **CI/CD variables are supported**, expanded by GitLab rather than the runner, except persisted variables and `CI_ENVIRONMENT_URL`. Sources: https://docs.gitlab.com/ci/yaml/#resource_group and https://docs.gitlab.com/ci/variables/where_variables_can_be_used/#gitlab-ciyml-file
  - `resource_group: harness-$SPEC_ID` works when `SPEC_ID` is a YAML or matrix variable. It probably does not work with a dotenv variable [I].
- **Process modes** [V]: `unordered` (the default), `oldest_first`, `newest_first` and `newest_ready_first` (faster than `newest_first`; jobs must be idempotent). Source: https://docs.gitlab.com/ci/resource_groups/#process-modes
- **Changing the mode** [V]. Only via the API: `PUT /projects/:id/resource_groups/:key` with `process_mode`. Read-only helpers are `GET …/current_job` and `…/upcoming_jobs`. Source: https://docs.gitlab.com/api/resource_groups/#update-a-resource-group
  - Groups created dynamically per spec therefore start as `unordered`, and you must PUT after the group first appears [I].
- **Pipeline-level lock** [V]. Put `resource_group` on the trigger job together with `strategy: mirror`. The docs say you "must define `trigger:strategy` to ensure the lock isn't released until the downstream pipeline finishes."
- **Deadlock risk** [V]. With `oldest_first`, a deadlock occurs if both parent and child pipelines need the same group. The fix is to put the group on the parent's trigger job.
- **Race condition** [V]. A known race exists in busy or multi-child pipelines (issue 436988). Source: https://docs.gitlab.com/ci/resource_groups/
- **Wait timeout** [U]. No timeout for `waiting_for_resource` is documented.

### 3. Pushing back to the repo from CI
- **`CI_JOB_TOKEN` push** [V].
  - The setting is **"Allow Git push requests to the repository"**, under Settings > CI/CD > Job token permissions. The API parameter is `ci_push_repository_for_job_token_allowed`.
  - It was introduced in 17.2 behind feature flag `allow_push_repository_for_job_token`, enabled on GitLab.com in 18.3, and **GA in 18.4** with the flag removed.
  - It is off by default and needs Maintainer to turn on. Only job tokens from the project's own pipelines can push.
  - **"When you use a job token to push to the project, no CI/CD pipelines are triggered."**
  - The token has the permissions of the user who started the job.
  - Do not enable it on pull mirrors.
  - Cross-project push from allowlisted projects was added in 19.0 and became GA in 19.1.

  Source: https://docs.gitlab.com/ci/jobs/ci_job_token/#allow-git-push-requests-to-your-project-repository
- **Long-running jobs and JWT job tokens** [V]. On GitLab 18.8 and earlier, a job could fail with `403` if it ran about 6 minutes without console output. Fixed in 18.9. Same page, troubleshooting section.
- **Job token API scope** [V]. It can `GET` MRs and MR notes and `POST /projects/:id/trigger/pipeline`. It **cannot** post notes, set commit statuses or edit MR labels, because those endpoints are not on its list. Same page, "Job token access".
- **Project access tokens** [V]. Git over HTTPS works with any non-blank username. On GitLab.com they need **Premium or Ultimate**; on self-managed, any license. Each token creates a bot user `project_{id}_bot_…`. Default and maximum expiry is 365 days (400 behind a feature flag). Source: https://docs.gitlab.com/user/project/settings/project_access_tokens/
- **Group access tokens** [V]. Premium or Ultimate on GitLab.com. Source: https://docs.gitlab.com/user/group/settings/group_access_tokens/
- **Deploy keys** [V]. A read-write key's push **does trigger pipelines**, and the key creator must have access to CI resources and the protected branch. Source: https://docs.gitlab.com/user/project/deploy_keys/#permissions
- **Pushes with project or group access tokens trigger pipelines like any normal push** [I]. Only the job token is documented as an exception.

### 4. Skipping pipelines and push options
- **`[ci skip]` / `[skip ci]`** [V]. Any capitalization works. An empty pipeline with status `skipped` is still created. Source: https://docs.gitlab.com/ci/pipelines/#skip-a-pipeline
  - The matching regex is `/\[(ci[ _-]skip|skip[ _-]ci)\]/i` [V]. Source: https://gitlab.com/gitlab-org/gitlab/-/blob/master/lib/gitlab/ci/pipeline/chain/skip.rb
- **Which sources honor a skip** [V, from source code]. Pipelines created via **web, api, trigger, pipeline (job-token trigger) and schedule pass `ignore_skip_ci: true`**. Push and `merge_request_event` pipelines **honor** the skip. Sources: `app/controllers/projects/pipelines_controller.rb`, `lib/api/ci/pipelines.rb`, `app/services/ci/pipeline_trigger_service.rb`, `app/workers/run_pipeline_schedule_worker.rb`.
  - Merged-results pipelines run on a merge commit GitLab creates, so a `[skip ci]` in the source commit may not apply to them [U].
- **MR-title skip** [V]. `[skip ci]` in an MR title skips MR pipelines. Added in 19.5 behind flag `ci_skip_pipeline_from_mr_title`, enabled by default.
- **Push options** [V].
  - `ci.skip` affects branch pipelines only, **not MR pipelines**.
  - `ci.variable="K=V"` and `ci.input='name=value'` set variables or inputs.
  - `ci.no_pipeline` is listed in the docs.

  Source: https://docs.gitlab.com/topics/git/commit/#push-options-for-gitlab-cicd
  - The `ci.no_pipeline` feature flag file shows milestone 18.11, type `gitlab_com_derisk`, `default_enabled: false`, so it is not dependable [V]. Source: https://gitlab.com/gitlab-org/gitlab/-/blob/master/config/feature_flags/gitlab_com_derisk/ci_no_pipeline_push_option.yml
- **Pipeline variables are restricted** [V]. On GitLab.com, new projects in new namespaces have defaulted to `ci_pipeline_variables_minimum_override_role = no_one_allowed` since 17.7. That breaks `ci.variable`, `variables[...]` on the trigger API, and the like. Parent-child trigger jobs are not restricted. Source: https://docs.gitlab.com/ci/variables/#restrict-pipeline-variables
  - **Use pipeline inputs instead** [V]. Up to 20 inputs per pipeline, defined only in the main `.gitlab-ci.yml`. They must have defaults, or automatic pipelines fail. Source: https://docs.gitlab.com/ci/inputs/#for-a-pipeline
- **Who the pipeline runs as** [V]. A trigger token "impersonates a user's project access and permissions". Source: https://docs.gitlab.com/ci/triggers/#create-a-pipeline-trigger-token

### 5. Triggers and downstream pipelines
- **Trigger API** [V]. `POST /projects/:id/trigger/pipeline` takes `token` (a trigger token **or** `CI_JOB_TOKEN`), `ref`, `variables`, and `inputs` (GA in 18.1). Source: https://docs.gitlab.com/api/pipeline_triggers/#trigger-a-pipeline-with-a-token
  - With a job token, the result is a multi-project pipeline (source `pipeline`) linked to the upstream pipeline.
  - With a trigger token, "the job is not associated with the upstream pipeline" (source `trigger`).
  - There is a webhook form, `…/ref/<ref>/trigger/pipeline?token=`, which exposes `TRIGGER_PAYLOAD`. Source: https://docs.gitlab.com/ci/triggers/
- **Keywords allowed in trigger jobs** [V]: `rules`, `needs` (not `needs:project`), `parallel`, `resource_group`, `environment`, `variables`, and `when` (including `manual`). `when: manual` trigger jobs cannot be started via the API, and `needs:pipeline:job` is not allowed in a trigger job. Source: https://docs.gitlab.com/ci/yaml/#trigger
- **Dynamic child pipelines** [V]. Use `trigger:include: [{artifact: generated.yml, job: generate-config}]`.
  - **You cannot use CI/CD variables in an `include` inside a dynamic child config.**
  - The artifact must be within size limits.
  - A child pipeline can take at most 3 config files.

  Source: https://docs.gitlab.com/ci/pipelines/downstream_pipelines/#dynamic-child-pipelines
- **Child pipeline inputs** [V]. `trigger:include:inputs` exists since 17.11.
- **`trigger:strategy`** [V]. `mirror` (added 18.2) mirrors the downstream status exactly; `depend` is "not recommended". Source: https://docs.gitlab.com/ci/yaml/#triggerstrategy
- **`trigger:forward`** [V]. `yaml_variables` defaults to true and `pipeline_variables` to false.
- **Child pipeline behavior** [V]. Children run on the same project, ref and SHA as the parent. `CI_PIPELINE_SOURCE` is always `parent_pipeline`, so use `$CI_MERGE_REQUEST_ID` to detect MR context. Children are auto-cancelled together with the parent when jobs are interruptible.
- **Depth and size limits** [V].
  - **Max depth is two levels of child pipelines.**
  - A hierarchy can hold at most **1000 downstream pipelines** (error: "downstream pipeline tree is too large").
  - Multi-project pipelines have "no nesting limits".

  Sources: https://docs.gitlab.com/ci/pipelines/downstream_pipelines/#nested-child-pipelines and https://docs.gitlab.com/administration/cicd/limits/#limit-pipeline-hierarchy-size
- **`needs:pipeline:job`** [V]. A child can pull artifacts from its parent or a sibling in the same hierarchy, typically via `PARENT_PIPELINE_ID: $CI_PIPELINE_ID`. The source job must have succeeded. An `optional` flag arrives in 19.5. Source: https://docs.gitlab.com/ci/yaml/#needspipelinejob
- **`parallel:matrix`** [V]. At most 200 permutations, and it can be used with trigger jobs ("Run a matrix of triggered parallel jobs"). Source: https://docs.gitlab.com/ci/yaml/#parallelmatrix
- **GitLab.com limits** [V].
  - Max jobs per pipeline: 500 (Free), 1500 (Premium), 2000 (Ultimate).
  - Downstream trigger rate: 350 per minute.
  - **Pipeline creation: 25 per minute per project, commit and user.**

  Source: https://docs.gitlab.com/user/gitlab_com/#cicd

### 6. Artifacts, dotenv and cache
- **`expire_in`** [V]. Latest artifacts are kept unless "keep latest" is disabled. GitLab.com defaults to 30 days, with a 1 GB maximum artifact size. Sources: https://docs.gitlab.com/ci/yaml/#artifactsexpire_in and https://docs.gitlab.com/user/gitlab_com/#cicd
- **Dotenv reports** [V]. Pass variables to later jobs and downstream pipelines. Self-managed defaults are a **5 KB** file and **20 variables**. GitLab.com allows 50, 100 or 150 variables by tier. Do not put secrets in them. Sources: https://docs.gitlab.com/ci/variables/dotenv_variables/ and https://docs.gitlab.com/administration/cicd/limits/#limit-dotenv-variables
- **Cache** [V]. `cache:key` accepts variables but not `/`. Options include `cache:fallback_keys` and the global `CACHE_FALLBACK_KEY`. Protected and unprotected branches get separate caches (`-protected` / `-non_protected` suffixes). Cache lives on the runner. Source: https://docs.gitlab.com/ci/caching/
- **Downloading artifacts by ref** [V]. `GET /projects/:id/jobs/artifacts/:ref_name/download?job=name` returns artifacts from the **latest successful pipeline only**.
  - `search_recent_successful_pipelines=true` searches up to 100 recent pipelines (18.7, flag removed in 18.10).
  - For MR pipelines use `refs/merge-requests/:iid/head`. Use `--location` on GitLab.com.

  Source: https://docs.gitlab.com/api/job_artifacts/#download-job-artifacts-by-reference-name
  - Artifacts from a failed or stuck agent run cannot be fetched this way, so keep loop state in git [I].

### 7. Interruptible, timeouts and `after_script`
- **`interruptible`** [V].
  - In `conservative` mode, once any `interruptible: false` job starts, the pipeline can no longer be cancelled.
  - The keyword has no effect unless the project setting "Auto-cancel redundant pipelines" is on.
  - A trigger job's `interruptible` never affects its downstream pipeline.

  Sources: https://docs.gitlab.com/ci/yaml/#interruptible and https://docs.gitlab.com/ci/pipelines/settings/#auto-cancel-redundant-pipelines
- **Timeouts** [V].
  - A job's `timeout` can exceed the project timeout but not the runner's `maximum_timeout`.
  - The project default is **60 minutes**, with a 10-minute minimum and a maximum under one month.
  - When both project and runner timeouts are set, the lower one wins.
  - Timed-out jobs are marked failed. Pending jobs are dropped after 24 hours.
  - **"Jobs without an output for one hour are dropped regardless of the timeout."**
  - `timeout` is not allowed in `default`.

  Sources: https://docs.gitlab.com/ci/pipelines/settings/#set-a-limit-for-how-long-jobs-can-run, https://docs.gitlab.com/ci/yaml/#timeout and https://docs.gitlab.com/ci/runners/configure_runners/#set-the-maximum-job-timeout
- **GitLab.com hosted runners** [V]. They **time out after 3 hours regardless of project timeout**, and the hosted runner timeout cannot be overridden. Source: https://docs.gitlab.com/ci/runners/hosted_runners/
- **`after_script`** [V].
  - It runs on cancel (introduced 17.0, GA 17.3, needs Runner 16.11.1 or later). The job shows `canceling` and `CI_JOB_STATUS=canceled` meanwhile.
  - It runs on `script_failure` only, not other failure types.
  - It has a separate 5-minute timeout (`RUNNER_AFTER_SCRIPT_TIMEOUT`).
  - **It does not run on job timeout by default.** Set `RUNNER_SCRIPT_TIMEOUT` + `RUNNER_AFTER_SCRIPT_TIMEOUT` to no more than the job timeout so it does.
  - It runs before artifact and cache upload.

  Sources: https://docs.gitlab.com/ci/yaml/#after_script, https://docs.gitlab.com/ci/runners/configure_runners/#set-script-and-after_script-timeouts and https://docs.gitlab.com/ci/yaml/script/#skip-after_script-commands-if-a-job-is-canceled

### 8. Status reporting and human gates
- **Commit status API** [V]. `POST /projects/:id/statuses/:sha` takes `state` (pending, running, success, failed, canceled, skipped), plus `name`/`context`, `target_url`, `description` (255 characters max) and `pipeline_id`. If no pipeline exists, it creates one with source `external`. It returns `409` on concurrent updates. Source: https://docs.gitlab.com/api/commits/#set-commit-pipeline-status
- **MR notes** [V]. `POST /projects/:id/merge_requests/:iid/notes` with an optional `internal` flag. Source: https://docs.gitlab.com/api/notes/#merge-requests
- **MR labels** [V]. Update an MR with `add_labels`/`remove_labels` (https://docs.gitlab.com/api/merge_requests/). Rules can read `CI_MERGE_REQUEST_LABELS`. The push option `merge_request.label=` also works.
- **Manual jobs** [V]. A plain `when: manual` job defaults to `allow_failure: true`, so it does not block. `rules:when: manual` defaults to false, so it blocks. `manual_confirmation` was added in 17.1. GitLab.com allows 3 manual runs per minute per job. Sources: https://docs.gitlab.com/ci/yaml/#when and https://docs.gitlab.com/user/gitlab_com/#cicd
- **Deployment approvals** [V]. Premium or Ultimate, on protected environments. The job does not need to be manual, but after approval it must be run manually. Self-approval is off by default. Source: https://docs.gitlab.com/ci/environments/deployment_approvals/

### 9. GitLab agent features
- **Duo Agent Platform flows run as CI jobs** [V].
  - They are configured in `.gitlab/duo/agent-config.yml` (`setup_script`, `cache`, image, ID tokens), which is read **only from the default branch**.
  - Self-hosted runners need the tag `gitlab--duo`.
  - Since 19.4 the executor is a precompiled binary.

  Source: https://docs.gitlab.com/user/duo_agent_platform/flows/execution/
- **Duo flow triggers** [V]. Premium or Ultimate.
  - Event types: Mention, Assign, Assign reviewer, Pipeline events (Running/Passed/Failed/Canceled), Merge request (Approved, Created, Marked ready, Merge conflict), and Work item.
  - They run as a service-account composite identity.
  - A custom flow file at a configuration path such as `.gitlab/duo/flows/claude.yaml` requires flag `ai_catalog_create_third_party_flows`, which is **disabled by default**.

  Source: https://docs.gitlab.com/user/duo_agent_platform/triggers/
- **External agents** [V]. Premium or Ultimate, flag-gated "for verified customers" (contact support to enable).
  - Claude Code Agent and Codex Agent use GitLab-managed credentials (GitLab.com since 18.8).
  - Context variables are `AI_FLOW_CONTEXT`, `AI_FLOW_INPUT` and `AI_FLOW_EVENT`.
  - `AI_FLOW_GITLAB_TOKEN` is OAuth limited to the `ai_workflows` scope.
  - `id_tokens` work in agent config since 19.2.
  - **No prompt-injection scanning** is applied to external agents.

  Sources: https://docs.gitlab.com/user/duo_agent_platform/agents/external/ and https://docs.gitlab.com/user/duo_agent_platform/agents/external_examples/
- **Anthropic's "Claude Code GitLab CI/CD" page** [V, Anthropic primary]. It is in **beta and maintained by GitLab** (issue 573776).
  - The example job uses `rules` on `web`/`merge_request_event` and runs `claude -p … --permission-mode acceptEdits`.
  - It recommends `CI_JOB_TOKEN` or a project access token with `api` scope.
  - Mention-driven runs need your own note webhook that calls the trigger API with `AI_FLOW_INPUT`.

  Source: https://code.claude.com/docs/en/gitlab-ci-cd
- **CI/CD components** [V].
  - Include with `include: component: $CI_SERVER_FQDN/<path>/<name>@<version>`. Components live under `templates/`, with at most 100 per project (since 18.5).
  - Publishing to the Catalog needs semver tags. `~latest` and partial versions are allowed.
  - **Avoid global keywords** such as `workflow` and `default` in a component, because they affect the whole pipeline.
  - `spec:component` context is GA in 18.7. `spec:include` is not allowed in components.

  Source: https://docs.gitlab.com/ci/components/
- **`spec:inputs`** [V]. Supports `type`, `default`, `options`, `regex` and `rules` (18.7). An interpolation block's contents are limited to 1 KB. Sources: https://docs.gitlab.com/ci/yaml/#specinputs and https://docs.gitlab.com/ci/inputs/
- **Job-level `inputs`** [V]. A new keyword in 18.10. Source: https://docs.gitlab.com/ci/yaml/#inputs

### 10. Secrets
- **Masked variables** [V]. Values must be at least 8 characters on a single line with no spaces. New variables default to Masked since 18.3, and a "Masked and hidden" option exists. Masking is "not a guaranteed way" to protect a secret. Source: https://docs.gitlab.com/ci/variables/#mask-a-cicd-variable
- **Protected variables** [V]. Available only on protected branches and tags; MR pipelines can optionally get them. Source: https://docs.gitlab.com/ci/variables/#protect-a-cicd-variable
- **Edit access to `.gitlab-ci.yml` defeats masking and protection** [V]. Anyone who can change the CI file can exfiltrate masked and protected values. Source: https://docs.gitlab.com/ci/variables/#cicd-variable-security
- **`id_tokens`** [V].
  - `aud` is required.
  - `sub` defaults to `project_path:…:ref_type:…:ref:…`.
  - Claims include `ref_protected`, `pipeline_source` and `user_login`.
  - Tokens are RS256-signed, and **`exp` equals the job timeout**, or 5 minutes if none is set.

  Source: https://docs.gitlab.com/ci/secrets/id_token_authentication/
- **`secrets:` keyword** [V]. Premium or Ultimate. Providers: Vault, GCP Secret Manager, Azure Key Vault, AWS Secrets Manager, and GitLab Secrets Manager (19.0, needs Runner 19.0). Sources: https://docs.gitlab.com/ci/yaml/#secrets and https://docs.gitlab.com/ci/secrets/

### Design implications for the harness
- **Package it as a CI/CD component project** [I] with templates such as `harness-detect`, `harness-implement` and `harness-verify`.
  - Inputs: `spec_globs`, `agent_image`, `agent_cmd`, `max_iterations`, `job_timeout`, `runner_tags`, `push_mode`, `bot_author_regex`.
  - Keep `workflow:` out of the component. Ship a documented `workflow:rules` snippet for the consumer's `.gitlab-ci.yml` instead.
- **Detect work from repository state, not `rules:changes`** [I]. `changes` is always true on new branches and diffs only against `HEAD~` on branches.
  - Run a cheap `detect` job on `push`, `web`, `api` and `trigger`.
  - It should parse `tasks.md` for `[ ]`, skip specs that have an unanswered `questions.md`, and write `child.yml`.
- **Fan out with a dynamic child pipeline** [I]. Use `trigger:include:artifact` plus `strategy: mirror`, with one implementer job per spec.
  - Because variables are not allowed in a dynamic child's `include`, the generator must write the literal component FQDN and version, or inline the jobs.
  - Two levels of nesting is enough.
- **Serialize per spec** [I]. Put `resource_group: harness-<spec_id>` on each per-spec implementer job, or on per-spec trigger jobs with `strategy: mirror` so the lock covers the whole child pipeline.
  - Never set the same group in both parent and child (deadlock).
  - Make each run idempotent: re-read the branch HEAD and the task state at start. Then the default `unordered` mode is safe; otherwise call `PUT …/resource_groups/:key process_mode=oldest_first` once the group exists.
- **Push mode A: job token** [V/I]. Use `git push "https://gitlab-ci-token:${CI_JOB_TOKEN}@…"` (GA 18.4, per-project opt-in).
  - It **triggers no pipeline**, so it cannot loop.
  - Continuation must be explicit: either a later stage in the same pipeline (verifier `needs` implementer), or the trigger API.
  - Status, notes and labels still need a project access token.
- **Push mode B: project access token** [I]. Use a bot token (Premium on GitLab.com) and commit progress with `[skip ci]`, which suppresses both push and MR pipelines.
  - Then start the verifier or next iteration with a **trigger token**: it ignores `[skip ci]`, is not chained into the hierarchy, and passes `inputs[...]` rather than variables.
  - Avoid self-chaining via `CI_JOB_TOKEN` triggers. Each one becomes part of the hierarchy, which caps at 1000 downstream pipelines.
- **Loop guards**:
  - In `workflow:rules`, add `when: never` for `$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_AUTHOR =~ /harness-bot/` [I].
  - Write an iteration trailer (`Harness-Iteration: N`) into commits, and stop at `max_iterations` [I].
  - Treat "`questions.md` present and unanswered" as an exit-0 terminal state with status `needs-human` [I].
  - The platform backstop on GitLab.com is 25 pipeline creations per minute per project, commit and user [V].
- **Cancellation** [I]. Make the implementer `interruptible: false` so a human push cannot cancel it mid-commit. Alternatively use `on_new_commit: interruptible` with only `detect` marked interruptible.
- **Long runs** [V/I].
  - Stream a heartbeat to the job log: jobs are dropped after 1 hour without output, and JWT job tokens on 18.8 and earlier fail with 403 after about 6 silent minutes.
  - On GitLab.com hosted runners, plan for a 3-hour hard cap or use self-hosted runners.
  - Set `RUNNER_SCRIPT_TIMEOUT` below the job timeout so `after_script` can commit WIP or questions on timeout.
  - Checkpoint-commit after each task.
- **Keep state in git, not artifacts** [I]. Use `tasks.md`, `questions.md` and `.harness/state.json`. Artifact lookup by ref only finds successful pipelines, and artifacts expire.
- **Human resume** [V/I].
  - Committing answers to `questions.md` creates a push pipeline by a human author, and `detect` resumes.
  - MR comments do not create pipelines natively. Options: a note-event webhook calling the trigger API, the Duo "Mention" trigger (Premium/Ultimate, behind flags), or a manual "Run pipeline". The job token can read MR notes, so a resumed run can collect comment answers.
- **Reporting** [V]. Post commit statuses named `harness/<spec>` (needs a project access token with `api` scope), MR notes, and `harness::needs-human` labels. Set `workflow:name: "harness $HARNESS_SPEC"`. A protected-environment approval can act as a human merge or apply gate (Premium).
- **Secrets** [V/I]. Use `id_tokens` for Bedrock or Vertex, with trust restricted on `sub`/`ref_protected`. Store `ANTHROPIC_API_KEY` as "Masked and hidden".
  - If it is also protected, spec branches must be protected, for example with a wildcard `spec/*` [I]; otherwise the key is unavailable.
  - Remember that anyone who can push CI config can exfiltrate it.


---

# Part 6 — State & restartability patterns; loop safety

## State & restartability patterns

**Labels:** [V] means verified against a primary source (URL given). [V-local] means I reproduced it on git 2.48.1 with local bare repos. [D] is a secondary source. [I] is my inference. [U] is unverified. Research date: 2026-10-03.

**Bottom line.** Keep the source of truth in **files committed on the change branch**: per-run JSONL ledger files plus tasks.md and questions.md. These travel with every clone, show up in the PR diff and survive a squash merge as content. Every other mechanism (trailers, tags, labels, notes) can be lost, isn't fetched by default, or is overwritten by the last writer. Treat them as indexes or mirrors that `doctor` can rebuild from the ledger.

### 1. git notes: not a safe source of truth
- `--ref <ref>` takes precedence over `GIT_NOTES_REF` and `core.notesRef`. The default ref is `refs/notes/commits`. [V] https://git-scm.com/docs/git-notes
- **Notes don't travel by default.** The default fetch refspec is `+refs/heads/*:refs/remotes/origin/*` [V] (https://git-scm.com/book/en/v2/Git-Internals-The-Refspec). A plain push and a plain clone/fetch moved no notes; only `git push origin 'refs/notes/*'` and `git fetch origin 'refs/notes/*:refs/notes/*'` did [V-local].
- **CI checkouts don't bring notes either.**
  - actions/checkout (v7.0.1) fetches 1 commit by default. Its refspecs only ever cover heads, tags and pull refs, never notes [V] (https://github.com/actions/checkout/blob/main/src/ref-helper.ts).
  - GitLab runners fetch with internal `$REFSPECS` and a default depth of 20 [V] (https://docs.gitlab.com/ci/runners/configure_runners/). I don't believe notes are included [I].
- **Merging concurrent notes.** Strategies are `manual` (default), `ours`, `theirs`, `union` and `cat_sort_uniq`. They can be set as defaults with `notes.mergeStrategy` or per ref with `notes.<name>.mergeStrategy` [V]. Concurrent pushes to a single notes ref will reject as non-fast-forward, so each writer needs a fetch, notes-merge and retry loop [I].
- **Rewrites lose notes.**
  - Notes are copied on amend/rebase only when `notes.rewriteRef` is set, and it has no default [V].
  - Without it, a rebase dropped the notes; with `-c notes.rewriteRef=refs/notes/harness` they followed the commits [V-local].
  - GitHub's rebase merge always creates new SHAs [V] (https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges). So host-side rebase or squash merges orphan the notes [I]. A local squash commit had no note [V-local].
- **Not visible in host UIs.**
  - GitHub: "Displaying Git notes on GitHub is no longer supported" since August 14, 2014 [V] (https://github.blog/news-insights/the-library/git-notes-display/).
  - GitLab: the feature request to show notes is still an open issue [D] (https://gitlab.com/gitlab-org/gitlab-foss/-/issues/38027).
  - Gitea: shows only `refs/notes/commits` [D].

### 2. Commit trailers: good audit index, fragile on squash
- `git interpret-trailers` supports `--parse` (shorthand for `--only-trailers --only-input --unfold`), `--trailer`, `--if-exists addIfDifferentNeighbor|addIfDifferent|add|replace|doNothing` (default `addIfDifferentNeighbor`) and `--if-missing`. The trailer block must sit at the end of the message after a blank line, and keys are alphanumeric or `-` [V] (https://git-scm.com/docs/git-interpret-trailers).
- `%(trailers:key=X,valueonly)` matches keys case-insensitively [V] (https://git-scm.com/docs/pretty-formats). Each value comes out with a trailing newline, so add `separator=%x2C` for parseable output [V-local].
- `git commit --trailer "Harness-Task: 1.2"` works. `--if-exists replace` correctly overwrote `Harness-Run` [V-local].
- **Squash behaviour by host:**
  - **Local:** `git merge --squash` indents the original messages, so `--parse` then finds **no trailers** [V-local].
  - **GitHub:** the default squash message is "the commit title and message if the pull request contains only 1 commit, or the pull request title and list of commits" [V] (https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/configuring-commit-squashing-for-pull-requests). GitHub adds `Co-authored-by` for every commit author [V] (https://github.blog/changelog/2019-12-19-improved-attribution-when-squashing-commits/). Whether custom trailers in a multi-commit list still parse is [U].
  - **GitLab:** the default squash template is just `%{title}`, so custom trailers are dropped. `%{all_commits}` and `%{co_authored_by}` exist [V] (https://docs.gitlab.com/user/project/merge_requests/commit_templates/).
- **Mitigation:** have the harness perform the merge and write the squash message itself, with consolidated `Harness-*` trailers. GitHub's merge API takes `commit_title`, `commit_message`, `merge_method` and `sha`. `sha` is a compare-and-swap on the PR head and returns 409 on mismatch [V] (https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request).
- Trailers are only readable for commits you actually fetched. A depth-1 checkout can't reconstruct history from trailers [I].

### 3. In-repo state files
- `merge=union` takes lines from both sides, "tends to leave the added lines in the resulting file in random order… Do not use this if you do not understand the implications" [V] (https://git-scm.com/docs/gitattributes).
- Host web merges have historically ignored it; GitLab's issue says "GitLab's interface doesn't support it" [D] (https://gitlab.com/gitlab-org/gitlab-foss/-/issues/17325). Current GitHub behaviour is [U].
- **Design:** don't depend on union merge.
  - Write **one ledger file per run** (`ledger/<run-id>-<attempt>.jsonl`, append-only, events carry ULIDs) so merges can't conflict.
  - Derive `state.json` as a fold over the ledger, written by one writer only [I].

### 4. Branches, worktrees, merge-back, tags
- **Worktrees.**
  - `git worktree add -b harness/<spec> <path>` creates the branch. `--lock --reason` locks the worktree atomically, with no race between add and lock [V].
  - A branch already checked out in another worktree is refused unless `--force` [V].
  - `prune` and `gc.worktreePruneExpire` clean up stale admin files, and `repair` fixes moved paths [V].
  - Refs are shared across worktrees except `refs/bisect`, `refs/worktree` and `refs/rewritten` [V] (https://git-scm.com/docs/git-worktree).
  - The worktree lock is local only, so it does nothing across CI runners [I].
- **Merge-back.** Rebase gives new SHAs (notes lost, trailers kept). Squash collapses commits (trailers lost unless the harness writes the message). A merge commit preserves everything [I from the cited docs]. Anthropic's 16-agent C-compiler run had agents pull, merge and push themselves: "merge conflicts are frequent, but Claude is smart enough to figure that out" [V] (https://www.anthropic.com/engineering/building-c-compiler).
- **Tags.** "Annotated tags are meant for release while lightweight tags are meant for private or temporary object labels"; `git describe` ignores lightweight tags; don't move published tags [V] (https://git-scm.com/docs/git-tag). Use immutable annotated milestone tags such as `harness/<spec>/verified-<n>`. A tag also keeps pre-squash commits reachable [I].

### 5. Locks (one runner per change)
- **GitHub Actions concurrency:**
  - At most one running job per group. By default a newer pending run **cancels** the older pending one [V].
  - New: `queue: max` allows up to 100 pending runs in FIFO order, and can't be combined with `cancel-in-progress: true` [V].
  - Job `timeout-minutes` defaults to 360 [V] (https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
- **GitLab** `resource_group` supports `process_mode` of `unordered`, `oldest_first`, `newest_first` or `newest_ready_first` [V] (https://docs.gitlab.com/ci/resource_groups/).
- **Portable git lock ref** (`refs/harness/locks/<spec>`):
  - `--force-with-lease=<ref>:<expect>` with an empty `<expect>` means the ref must not exist yet [V] (https://git-scm.com/docs/git-push).
  - The server re-validates that each ref "hasn't changed… (the obj-id is still the same as the old-id)", so this is a true server-side compare-and-swap [V] (https://git-scm.com/docs/gitprotocol-pack).
  - `--atomic` gives all-or-nothing updates across refs [V].
  - Tested: acquire, contended acquire (rejected "stale info"), CAS-steal of an expired lease, rejected stale release, and an atomic "push branch + release lock" all behaved correctly [V-local].
- **Two traps found while testing:**
  - (a) **A leading `+` on the refspec silently overrides the lease.** A second runner "acquired" a held lock with a forced update. The docs say `--force`/`+` "disables these checks" [V-local + V].
  - (b) **Identical lock payloads written in the same second produce the same SHA**, so CAS can't tell two holders apart. Always include a nonce, the run URL and an absolute UTC expiry [V-local].
  - Minor scripting gotcha: zsh reads `"$sha:refs/…"` as the `:r` modifier, so write `"${sha}:refs/…"` [V-local].
- GitHub rulesets probably don't protect custom ref namespaces, so anyone with write access can delete a lock [U]. Hosts generally accept custom refs [D].
- Anthropic's C-compiler agents locked tasks by committing files to `current_tasks/`, and "git's synchronization forces the second agent to pick a different one" [V] (https://www.anthropic.com/engineering/building-c-compiler).

### 6. Checkpoint and resume of agent sessions
- **Claude Code flags:**
  - `-c`/`--continue` and `-r`/`--resume <id|name|absolute .jsonl path>`.
  - `--fork-session`, and `--session-id <uuid>` to set the ID up front.
  - `--no-session-persistence` [V] (https://code.claude.com/docs/en/cli-reference).
- **Claude Code transcripts:**
  - Stored at `~/.claude/projects/<project>/<session-id>.jsonl`, with 30-day retention.
  - Can be relocated with `CLAUDE_CONFIG_DIR` and `CLAUDE_CODE_PROJECT_DIR_NAME`.
  - The entry format "is internal… changes between versions", so don't parse it [V] (https://code.claude.com/docs/en/sessions).
  - On ephemeral CI runners, persist the config dir as an artifact or cache to allow a warm resume [I].
- **Claude Code crash and timeout behaviour:**
  - A tool call cut off by a crash isn't re-run on resume; Claude is told to check whether it took effect [V].
  - SIGTERM exits with code 143 and leaves the turn unfinished. SIGINT ends the turn cleanly [V] (https://code.claude.com/docs/en/headless). So send SIGINT on a soft deadline well before the CI timeout [I].
  - `session_id` is available from `--output-format json` [V].
- **Codex:**
  - `codex exec resume --last` or `codex exec resume <SESSION_ID>`; `--ephemeral` skips persistence.
  - `--json` emits `thread.started{thread_id}`.
  - `exec` defaults to a read-only sandbox [V] (https://learn.chatgpt.com/docs/non-interactive-mode, redirected from developers.openai.com/codex/noninteractive).
  - Sessions live under `~/.codex/sessions/` [D].
- **OpenHands:** `openhands --resume [<id>|--last]`, with state in `~/.openhands/conversations/` [V] (https://docs.openhands.dev/openhands/usage/run-openhands/cli/resume).
- **LangGraph:** checkpointers persist thread state keyed by `thread_id` (InMemorySaver, SqliteSaver, PostgresSaver) [V] (https://docs.langchain.com/oss/python/langgraph/persistence).
- **Temporal + OpenAI Agents SDK** (preview 2025-07-30): "every agent invocation is executed through a Temporal Activity", which gives retries and resume-after-crash [V] (https://temporal.io/blog/announcing-openai-agents-sdk-integration).
- **Stateless re-entry** (Ralph: `while :; do cat PROMPT.md | claude-code ; done`, one task per loop, tests as backpressure) [V] (https://ghuntley.com/ralph/).
- **Anthropic, "Effective harnesses for long-running agents"** (Justin Young, 2025-11-26) [V] (https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents):
  - An **initializer agent** writes `init.sh`, `claude-progress.txt`, an initial git commit, and a JSON feature list (200+ items with `"passes": false`). The reason given: "the model is less likely to inappropriately change or overwrite JSON files compared to Markdown".
  - A **coding agent** starts every session with `pwd`, reads the progress file and git log, picks the highest-priority failing feature, and runs a basic test first.
  - It works on one feature at a time and ends each session with a descriptive commit plus a progress update. Features are marked passing only after end-to-end browser testing.
  - "It is unacceptable to remove or edit tests".
  - Both "agents" share the same system prompt, tools and harness; only the initial user prompt differs.
- **Later Anthropic posts:**
  - Generator and evaluator agree a "sprint contract" before coding. Each criterion has a hard threshold that fails the sprint. "tuning a standalone evaluator to be skeptical turns out to be far more tractable than making a generator critical of its own work". Agents hand off through files [V] (https://www.anthropic.com/engineering/harness-design-long-running-apps, 2026-03-24).
  - Progress files should record "failed approaches and why they didn't work"; commit and push after every meaningful unit of work [V] (https://www.anthropic.com/research/long-running-Claude).
- **Assessment:** make stateless re-entry from repo state the guaranteed path, and treat transcript resume as an optimization [I].

### 7. Idempotency, dry-run, doctor
- Run identity:
  - On GitHub, `GITHUB_RUN_ID` stays the same on re-run and `GITHUB_RUN_ATTEMPT` increments [V] (https://docs.github.com/en/actions/reference/workflows-and-actions/variables).
  - On GitLab, `CI_PIPELINE_ID` and `CI_JOB_ID` identify the run [V].
- Step key: `(spec-id, task-id, sha256(spec files, base SHA, prompt version, model))`. Write `step.started` and `step.finished` events. A step that started but never finished gets reconciled against `Harness-Run` trailers and the worktree diff [I].
- Dry-run analog: Terraform's `-detailed-exitcode` returns 0 for no changes, 1 for error, 2 for changes, and a saved `-out` plan is applied exactly [V] (https://developer.hashicorp.com/terraform/cli/commands/plan). Mirror this with `harness plan` [I].
- Doctor precedents:
  - `claude doctor` gives read-only diagnostics [V].
  - `openspec validate [--all|--changes|--strict|--json|--archived]`, where `--archived` exits non-zero if an archived change has unticked tasks. `openspec store doctor` "never clones, syncs, or repairs". `archive` without a TTY exits 1 unless `--yes` is passed [V] (https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md, v1.14.0).

## Loop safety

### Hard caps by tool

| Tool | Limits | Status |
|---|---|---|
| Claude Code `-p` | `--max-turns` exits with an error at the limit (no limit by default) | [V] |
| Claude Code `-p` | `--max-budget-usd` includes subagent spend, but **totals restored on `--resume` don't count toward the cap**, so the harness must track cumulative cost itself | [V] (https://code.claude.com/docs/en/cli-reference) |
| Claude Code `-p` | Result subtypes `error_max_turns`, `error_max_budget_usd`, `error_during_execution`; result includes `total_cost_usd` and `num_turns` | [V] (https://code.claude.com/docs/en/agent-sdk/typescript) |
| Claude Code Stop hooks | Overridden after **8 consecutive blocks without progress** (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`) | [V] (https://code.claude.com/docs/en/hooks-guide) |
| Claude Code `/goal` | Stops when there's "no tool use for several turns in a row". Its evaluator "doesn't run commands or read files", so it judges only the transcript. Not a verifier. | [V] (https://code.claude.com/docs/en/goal) |
| Codex | No turn cap. Experimental `features.rollout_budget.limit_tokens`. Wall-clock limits are the real cap. | [V] (https://learn.chatgpt.com/docs/config-file/config-reference) |
| gh-aw | `max-turns` default 500; `timeout-minutes` default 20; `max-ai-credits` default 1000; `max-daily-ai-credits` 5000; `stop-after`; per-user rate limits; read-only agent | [V as of today, fast-moving] (https://github.github.com/gh-aw/reference/engines/, …/rate-limiting-controls/) |
| GitHub Actions | 6 h per job on hosted runners, 5 days self-hosted, 35 days per run | [V] (https://docs.github.com/en/actions/reference/limits) |
| GitHub Actions | Events triggered by `GITHUB_TOKEN` don't start new workflow runs, except `workflow_dispatch` and `repository_dispatch` | [V] (https://docs.github.com/en/actions/concepts/security/github_token) |

The `GITHUB_TOKEN` rule is built-in loop protection. It also means resume chaining must use `workflow_dispatch` or a human's commit [I].

### Stop guidance and circuit breakers
- **Anthropic** (2024-12-19): "common to include stopping conditions (such as a maximum number of iterations)"; agents "pause for human feedback at checkpoints or when encountering blockers"; get "ground truth from the environment at each step" [V] (https://www.anthropic.com/engineering/building-effective-agents).
- **OpenAI:** a run loops until a final-output tool, no tool calls, an error, or "a maximum number of turns" (p.14). Escalate on "Exceeding failure thresholds" and "High-risk actions" (p.31) [V] (https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf).
- **frankbria/ralph-claude-code** [V] (https://github.com/frankbria/ralph-claude-code):
  - `CB_NO_PROGRESS_THRESHOLD=3` (loops with no file changes), `CB_SAME_ERROR_THRESHOLD=5`, `CB_OUTPUT_DECLINE_THRESHOLD=70`%.
  - States CLOSED, HALF_OPEN, OPEN, with a 30-minute cooldown.
  - Exit needs both `EXIT_SIGNAL: true` and at least 2 completion indicators.
  - `MAX_CALLS_PER_HOUR=100`, a 15-minute per-loop timeout, and session expiry after 24 h.
- **Anthropic's Ralph plugin:** "Always use `--max-iterations` as a safety net" [V] (https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum).
- **Stuck signals to compute deterministically** [I]:
  - Hash of the cumulative diff unchanged for N iterations.
  - Diff hash returning to an earlier value (A→B→A oscillation).
  - Same normalized failure fingerprint (test ID plus error class) repeated K times.
  - Passing-test count and ticked tasks.md boxes both flat.
  - Tests deleted or modified (a red flag the Anthropic post forbids).
  - Cost per ticked task rising.
- **Escalation:** write `questions.md`, set the ledger state to `blocked`, release the lock and exit 0 with a distinct status. Never keep spinning [I].
- **Independent verification:** "it is easy to see tests pass and assume the job is done, when this is rarely the case" [V] (Carlini). The verifier must run tests and Playwright itself, not just read the implementer's transcript [I].

### Prompt injection in CI
- **PromptPwnd** (Aikido, 2025-12-04) [V] (https://www.aikido.dev/blog/promptpwnd-github-actions-ai-agents):
  - Pattern: untrusted issue, PR or commit text goes into the prompt, and the agent holds privileged tools or tokens.
  - Affected Gemini CLI, Claude Code Actions, Codex Actions and GitHub AI Inference.
  - Fixes: restrict tools, don't interpolate untrusted input, treat agent output as untrusted, limit token blast radius.
- **claude-code-action, fixed in v1.0.94** (GMO Flatt, 2026-06-01) [V] (https://flatt.tech/research/posts/poisoning-claude-code-one-github-issue-to-break-the-supply-chain/):
  - The permission check let any GitHub App through.
  - An injected issue then exfiltrated `ACTIONS_ID_TOKEN_REQUEST_*`, which could be exchanged for a write-scoped installation token.
- **The action's security doc:** `allowed_non_write_users` is "a significant security risk"; restrict tools via `--allowedTools`; content sanitizing "may" be bypassed [V] (https://github.com/anthropics/claude-code-action/blob/main/docs/security.md).
- **GitLost** (Noma, July 2026): gh-aw plus cross-repo read plus a public comment output leaked private repositories [D] (https://siliconangle.com/2026/07/07/gitlost-vulnerability-let-githubs-ai-workflows-leak-private-repositories/). Safe outputs don't help if the allowed output is a public channel [I].
- **Mitigations:**
  - gh-aw's **safe-outputs**: the agent runs read-only and emits structured requests; a separate, permissioned job applies them with sanitization and `max` limits [V] (https://github.github.com/gh-aw/reference/safe-outputs/).
  - **AWF network firewall** with domain allowlists [V] (https://github.github.com/gh-aw/reference/network/).
  - Meta's **Agents Rule of Two**: at most two of (untrustworthy input, sensitive access, state change/external communication) in one session [V] (https://ai.meta.com/blog/practical-ai-agent-security/).
  - actions/checkout persists the token for later git commands by default; set `persist-credentials: false` in the agent job [V] (checkout README).
  - Codex: "Never expose `OPENAI_API_KEY` at job level" [V].
  - Run the implementer with read-only `GITHUB_TOKEN` scopes, no secrets beyond the model key and egress allowlisted. Have a separate push/merge job validate the diff (paths, no `.github/workflows` edits) and push. Treat questions and answers from non-maintainers as untrusted [I].

## Recommendation: source of truth vs mirrors

1. **Truth:** the change folder on branch `harness/<spec-id>`. That's `tasks.md` checkboxes, `questions.md`/`answers.md`, and `harness/ledger/<run-id>-<attempt>.jsonl` (one file per run, append-only). It carries a derived `state.json` (rebuildable, single writer). It survives squash merges, shows up in PR diffs and travels with clones [I].
2. **Audit index:** `Harness-Spec`, `Harness-Task`, `Harness-Run` and `Harness-State` trailers on every commit, re-stamped onto the squash commit by the harness through the merge API.
3. **Concurrency:** the CI concurrency group `harness-${spec}` with `queue: max` is primary. An optional CAS lock ref provides cross-CI portability (nonce, expiry, never `+`).
4. **Milestones:** immutable annotated tags.
5. **UI mirrors:** labels, check runs, job summaries and PR comments, always recomputed from the ledger.
6. **Notes:** off by default. If used, only for rich per-commit verifier reports under `refs/notes/harness/*` with `cat_sort_uniq`.
7. **On disagreement, precedence is ledger > trailers > tags > labels.** `doctor` reports drift and repairs mirrors only.

| Mechanism | Survives squash | Visible in UI | Needs push perms | Conflict risk | Best use |
|---|---|---|---|---|---|
| Per-run ledger files + tasks.md in branch | Yes, as content | Yes (PR diff) | contents:write | ~None with one file per run; high for one shared file | **Source of truth** |
| Commit trailers | Only if the harness writes the squash message (GitHub multi-commit [U], GitLab default drops them); yes on rebase | As commit text | Same as the commit | None (immutable) | Audit and provenance index |
| git notes (custom ref) | No (new SHAs; host merges don't rewrite notes) | No (GitHub since 2014; GitLab; Gitea only default ref) | contents:write + explicit refspec | High on a shared ref (non-fast-forward, needs notes merge) | Optional annotations |
| Annotated tags | Pin pre-squash commit; don't follow the squash | Yes | contents:write (may hit tag rulesets) | Low if unique, never moved | Milestones |
| Lock ref `refs/harness/locks/*` | n/a | No | contents:write | Server-side CAS | Cross-CI mutual exclusion |
| CI concurrency / resource_group | n/a | Yes | None | None | Primary single-runner guard |
| Labels / checks / summaries | n/a | Best | issues/PR/checks write | Last writer wins | UI mirror only |
| Agent transcripts (`~/.claude`, `~/.codex`) | n/a (outside git) | No | Artifact upload | n/a | Warm-resume optimization; never truth |

**Highest-risk claims.**
- The lock-ref design hinges on the [V-local] finding that a `+` refspec defeats the lease. It matches the documented `--force` semantics.
- I did not test GitHub's handling of trailers in multi-commit squashes or of `merge=union` [U]. The recommendation avoids depending on either.
- The gh-aw default values change frequently; re-check them before relying on them.

---

# Appendix: orchestrator spot-check log

These are independent re-checks of the load-bearing claims, done after the sub-reports arrived.

| # | Claim | Result | Source |
|---|---|---|---|
| 1 | Events triggered by `GITHUB_TOKEN` create no new workflow runs, except `workflow_dispatch`/`repository_dispatch`; PR opened/synchronize/reopened events create approval-required runs | Confirmed [V] | https://docs.github.com/en/actions/concepts/security/github_token |
| 2 | GitLab `CI_JOB_TOKEN` push: introduced 17.2, enabled on GitLab.com 18.3, GA 18.4 (flag removed); "no CI/CD pipelines are triggered"; off by default; do not enable on pull mirrors | Confirmed [V] | https://docs.gitlab.com/ci/jobs/ci_job_token/ |
| 3 | GitHub `concurrency` `queue: max`: up to 100 pending; only valid when `cancel-in-progress` is false or unset (2026-05-07) | Confirmed [V] | https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues ; workflow-syntax page |
| 4 | GitHub step-level `background: true`, `wait`/`wait-all`/`cancel` (2026-06-25) | Found via search and the changelog URL; the workflow-syntax page fetch did not show it (possible truncation). Treat as [D] | https://github.blog/changelog/2026-06-25-actions-steps-can-now-be-run-in-parallel |
| 5 | Sourcegraph L3 vs L4: L3 "still should perform a high-level review of the final code output"; L4 "humans are no longer expected to review the final code output" (Quinn Slack, 2023-10-04) | Confirmed [V] | https://sourcegraph.com/blog/levels-of-code-ai |
| 6 | Dan Shapiro "Five Levels" (2026-01-23): L4 robotaxi, L5 "black box that turns specs into software" | Confirmed [V] | https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/ |
| 7 | gh-aw safe outputs: "agents run read-only and request actions via structured output, while separate permission-controlled jobs execute those requests"; staged mode makes no HTTP request; `dispatch-workflow` max 3, same-repo only | Confirmed [V] | https://github.github.com/gh-aw/reference/safe-outputs/ |
| 8 | gh-aw defaults: `max-turns` 500; `timeout-minutes` falls back to 20; `max-ai-credits` 1000; `max-daily-ai-credits` disabled by default; `strict` true | Confirmed [V] (contradicts the "5000" in Part 6) | https://github.github.com/gh-aw/reference/frontmatter/ |
| 9 | OpenSpec `archive`: JSON mode with `--yes` proceeds silently with incomplete tasks; human mode with `--yes` prints "Warning: N incomplete task(s) found. Continuing due to --yes flag." | Confirmed [V] (source) | https://raw.githubusercontent.com/Fission-AI/OpenSpec/main/src/core/archive.ts |
| 10 | bmad-loop exists, MIT, "No LLM in the control loop"; commands init/validate/run/resume/resolve/sweep/tui; state in `.bmad-loop/runs/<run-id>/` | Confirmed [V] | https://github.com/bmad-code-org/bmad-loop |
| 11 | GitLab.com hosted runners "time out after 3 hours, regardless of the timeout configured in a project" | Confirmed [V] | https://docs.gitlab.com/ci/runners/hosted_runners/ |
| 12 | GitLab `after_script` does not run on job timeout by default; set `RUNNER_SCRIPT_TIMEOUT`/`RUNNER_AFTER_SCRIPT_TIMEOUT` | Confirmed [V] | https://docs.gitlab.com/ci/yaml/#after_script |
| 13 | Lock ref compare-and-swap: `--force-with-lease=<ref>:` (empty expected value) rejects when the ref exists; a `+` refspec prefix **overrides the lease** (forced update succeeded) | Reproduced [V-local], git 2.48.1, local bare repo | scratchpad/locktest |
| 14 | Anthropic "Effective harnesses for long-running agents" (Justin Young, 2025-11-26): initializer creates `claude-progress.txt`, feature-list JSON, `init.sh`; JSON chosen because "the model is less likely to inappropriately change or overwrite JSON files compared to Markdown files" | Confirmed [V] | https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents |

Not independently re-checked by the orchestrator: licenses and versions obtained from the GitHub REST API (the orchestrator's unauthenticated API calls were rate-limited), GitLab 19.x Duo Agent Platform details, and the Copilot cloud agent's 59-minute cap. These carry the sub-report's label only.
