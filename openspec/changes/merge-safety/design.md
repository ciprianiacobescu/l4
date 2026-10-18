## Context

The code as read at 0.4.14 (the line numbers are from that source):

- `yolo/merge.py` `merge_guarded` (227) refuses only a `review.reentry` (248). `_unit_head` (204) returns
  `snapshot.review.head`, which is the branch tip. That tip is what the `ls-remote` and PR-head checks compare, what
  `squash_merge` passes as `sha` (173) and what the fast-forward pushes. Nothing compares it with H.
- `state/review.py` `after_handoff` (53) finds H with `vcs/authorship.handoff_commit`: the newest first-parent commit
  whose subject is the hand-off subject and whose author and committer are the bot. A commit after H is foreign only
  when it is not `is_harness_strict`, so identity text decides. `state/status.py` (218) and `orchestrator._review` call
  it, and the sweep's CI duty and the planner read its result.
- `archive.handoff_hook` (402) writes `pr.ready{url, number, head: H}` after H is pushed. That event therefore goes to
  the lock-ref pending ledger (`_publish_pending`), never into the branch tree. `state/fold.py` has no handler for it.
- `yolo/cycle.py` `_live` (1125) calls `_merge` for an in-review current unit. `_merge` (1392) never asks the planner
  (`_unit_action`), and `merge_guarded._readiness` reads no CI. `_dispatch` and `_merge_wait_gone` do treat an
  actionable in-review unit as having work.
- `ci/sweeper.py` `_ci_duty` (832): `ci_green`, `ci_waiting` and `ci_not_run` write nothing, and
  `if not jobs and platform == "github"` (851) tests the list before the `l4` job is dropped.
- `forge/github.py` `list_pipeline_jobs` (397) keys `newest` by `run["name"]` alone, across check suites.
  `forge/gitlab.py` (294) keeps one job per name, newest pipeline first.

## Decisions

### D1 H is the recorded `pr.ready{head}`

`UnitState.ready_head: str | None = None` is the `head` of the latest `pr.ready` in fold order among the lock ref's
pending files (D10, F4: `recorded_ready`, set by the reader; `fold` ignores `pr.ready`). It is never cleared. A
re-entry hands off again and records a new `pr.ready` (`[h1, h2]` in `test_handoff_reentry.py`). A PR that is closed and
reopened goes back to `in_review` with its H. `pr.ready{head}` has been written since the first public commit, so every
unit in review today has it.

Why a branch push cannot move it: a commit cannot contain its own sha. A `pr.ready` that someone writes into the branch
files can therefore never name the tip that carries it, and the merge needs tip == `ready_head` (D3). To make the record
name a commit of their own, a writer has to push the lock ref `refs/l4/locks/<fw>/<name>` instead. The harness alone
writes that ref (leased plumbing commits, L4-LCK-001), and it is not the branch people push answers and feedback to.

Residual risk, stated plainly: anyone with push access to the repository can also push the lock ref, and neither GitHub
nor GitLab protects a ref outside `refs/heads`/`refs/tags` [inferred]. This change closes the forgery that a branch push
alone can do. It does not close one that also forges the harness's hidden ref. Signed harness commits are an open
question.

### D2 The review after the hand-off counts from the recorded H

The new signature is `after_handoff(git, head, name, unit_rel, *, recorded: str | None = None) -> AfterHandoff`.

- When `recorded` is given and is an ancestor of `head` (`git merge-base --is-ancestor`): `handoff = recorded`. Every
  first-parent commit in `recorded..head` is a `ForeignCommit`, whatever its author, committer or trailers. With
  `archive.mode: post_merge_pr` (the only mode built) the harness pushes nothing to the unit branch while the PR is ready
  (L4-ARC-007), and `l4 retry` records `unit.retried` and its edge before its one commit, so that commit already shows
  the unit out of review [verified: `Orchestrator.resume`]. `spec_edit` is the diff of `recorded..head` as today.
- When `recorded` is given and is not an ancestor of `head`, or is unknown to the clone: the result is
  `AfterHandoff(recorded, head_sha, lost=True)`, which is rewritten history.
- When `recorded` is None: today's subject-and-identity rule, unchanged. This is the fallback for a unit with no
  `pr.ready`.

The callers pass `recorded=state.ready_head`: `status.load_snapshot` and `Orchestrator._review`
(`self.state.ready_head`). Because the sweep's CI duty and the planner read `snapshot.review`, a forged second H no
longer misleads them either. A forged commit after H is a re-entry like a person's commit (planner `verify`, run edge
`commit_after_handoff`). The verifier sees it, as it would see a person's push. There is no silent merge and no stuck
wait.

### D3 The merge lands exactly the recorded H (`yolo/merge.py`)

`_unit_head` is replaced by `_recorded_head(snapshot) -> tuple[str | None, str | None]` (the H, or the `not_ready`
detail). In `merge_guarded`, after `_readiness` and the re-entry check, the checks run in this order:

1. `ready_head is None` → `not_ready`:
   `no hand-off commit H is recorded for <unit> (no pr.ready): l4 retry --unit <unit> hands it off again`.
2. `review is None` → `not_ready`: `the unit branch head is not known`. When `review.handoff != ready_head` or
   `review.head != ready_head` → `not_ready`: `the unit branch head <review.head[:10]> is not its recorded hand-off
   commit H <H10>: the next run verifies the new head`. With D2 in place, step 2 is reached only by a snapshot that was
   built another way (the re-entry check before it takes every commit after H). It is the belt.
3. Recorded red on H (D4).
4. Then the existing checks, all with `head = ready_head`: the PR is open with the target as base, the `ls-remote` tip of
   the unit branch is H, and the PR head sha is H (with its re-read).
5. The CI gate (D5).
6. `guarded_push`: the target tip is an ancestor of H, then `before_push`.

The re-entry detail becomes `the branch changed after the hand-off commit H (<shas>): the unit is verified again`. It no
longer says "a person": the identity is not known.

Which sha is merged and verified:

- **With `squash`:** `squash_merge(..., head=H, ...)` calls `merge_pr(number, sha=H)`. GitHub and GitLab refuse a PR
  whose head is not `sha` (409 → `head_moved` → `not_ready`), so the forge squashes exactly H's tree. The landed commit S
  is then checked as today: its parent is the tip that was read, and its tree is H's tree (else `raced`).
  `unit.merged{head: H, merge_commit: S}` is recorded. The post-merge check runs on S, `refs/l4/merged/...` is pushed at
  H, and the leased delete is leased on H.
- **With `fast-forward`:** the step pushes `H:refs/heads/<target>`, and the landed commit is H.

### D4 A review edge comes before the merge

- `cycle._merge`: right after the PASS check and before `unit_blocker`,
  `if self._unit_action(snap) in _ACTIONABLE: return None`. `_merge_not_ready` is left alone, so `_dispatch` dispatches
  the unit (its `actionable` branch comes first) and the run takes `repository_ci_failed`, `commit_after_handoff` or
  `spec_edit_after_handoff`. This is the guard that `_dispatch` and `_merge_wait_gone` already use.
- `merge_guarded`, as belt and braces, for direct callers and the wait probe: if `state.ci_failure` is not None and
  `state.ci_failure.head == ready_head` → `not_ready`:
  `the repository CI failed on the hand-off commit <H10>: <recorded job names> (recorded): the unit is verified again`.

### D5 The merge reads the repository's CI on H through the sweep's reader

There is a new module, `src/l4/ci/handoff_ci.py`:

- `HandoffCi(status: Literal["running", "green", "failed", "preexisting", "not_run"], head: str, reason: str = "",
  failed: tuple[JobResult, ...] = (), preexisting: tuple[JobResult, ...] = ())`.
- `read_handoff_ci(forge, head, base, platform) -> HandoffCi` takes the order of today's `_ci_duty`:
  - `list_pipeline_jobs(head)`;
  - `unfinished` → `running`;
  - no job left after `DEFAULT_IGNORE` → `not_run` with the D7 reason;
  - no red job → `green`;
  - otherwise `evaluate_ci` against `list_pipeline_jobs(base, settled=True)`, where `running` gets the reason
    `the base is`.
- Forge errors propagate. Both callers pass `forge_platform(cfg, environ, origin_url(repo, environ))` and
  `base = git.rev_parse("refs/remotes/origin/<forge.base_branch>")`.

`Sweeper._ci_duty` keeps its early returns (no H, not at H, already recorded, no open MR) and its action words. It maps
`read_handoff_ci` as follows:

- `running` → `ci_waiting` (`H <short> running`, plus ` (the base is)`);
- `not_run` → `ci_not_run` (`H <short>: <reason>`);
- `green` → `ci_green`;
- `failed` and `preexisting` → `ci.failed` and `ci.preexisting` recorded as today.

`merge_guarded` calls the reader at step 5 of D3, through `_ci_gate(app, cfg, git, forge, snapshot, head)`. The table
says what each status does, what the plan records and what the person sees in `l4 yolo status`. Each detail is fixed
text plus shas and job names, so it holds while nothing changes, and `_merge_wait_gone` wakes the plan when it changes.

| CI on H | merge | recorded, and what the person sees |
|---|---|---|
| read error (`ForgeError`, `ForgeUnavailable`) | `not_ready` | `plan.waiting{merge_not_ready}`: `the repository CI of the hand-off commit <H10> could not be read: <first line, redacted>` |
| `running` | `not_ready` | `the repository CI is still running on the hand-off commit <H10>: the plan merges when it is green` |
| `failed`, nothing recorded for H | `not_ready` | `the repository CI failed on the hand-off commit <H10>: <keys>: the next sweep records it and the unit is verified again`. The sweep runs first in every `l4` job, records `ci.failed`, and D4 then dispatches the unit. |
| `failed`, `ci_heads[H] == "preexisting"` | `not_ready` | `... <keys>, red on the base too when the sweep recorded it and not red there now: l4 retry --unit <unit> verifies the unit again`. The sweep acts once per H, so only a person's retry ends this wait. |
| `preexisting` | merge | `unit.merged{ci: preexisting, ci_jobs: [keys]}`, and the line `warning: <unit>: the repository CI on <H10> is red as on the base: <keys>` |
| `green` | merge | `unit.merged{ci: green}` |
| `not_run`, `yolo.merge.require_ci: true` | `not_ready` | `no CI of the repository ran on the hand-off commit <H10> (<reason>): run the repository's CI on the unit branch or its pull request, or set yolo.merge.require_ci: false` |
| `not_run`, `require_ci: false` (default) | merge | `unit.merged{ci: not_run}`, and the line `warning: <unit>: no CI of the repository ran on <H10>; merged because yolo.merge.require_ci is false`, in the plan report and as a note on the merged PR or MR (`upsert_sticky_note`, best effort) |

`<keys>` is `", ".join(sorted(j.key for j in ci.failed))`. `MergeOutcome` gains `ci: str | None = None` and
`ci_jobs: tuple[str, ...] = ()`. `merge_guarded` sets them on a `merged` outcome with `dataclasses.replace`, and
`cycle._merge` writes them into `unit.merged`: `ci` always, `ci_jobs` only when it is not empty. `YoloMergeCfg` gains `require_ci: bool = False`: it decides only whether `not_run` blocks. Running, red (new on H) and unreadable CI block whatever the key. A wait chains no run
(`_wait_merge`), so a plan waiting for CI goes on at the next trigger (the schedule, a push, a command).

### D6 GitHub check-run identity (`forge/github.py`, `forge/base.py`, `ci/repo_ci.py`)

- `JobResult` gains `workflow: str = ""` and `event: str = ""`. The property
  `key -> f"{workflow} / {name}" if workflow else name` is the name a job has across commits.
- `GitHubForge.list_pipeline_jobs(sha, settled)` reads the check runs as today. If any check run has `app.slug ==
  "github-actions"`, it also calls `_workflow_suites(sha) -> dict[int, tuple[str, str]]`, which maps check suite id to
  (workflow file, event):
  - `GET /repos/{repo}/actions/runs?head_sha=<sha>` (pages, key `workflow_runs`; `head_sha`, `path`, `event`,
    `check_suite_id` and `run_attempt` are in GitHub's schema [verified, docs.github.com/en/rest/actions/workflow-runs]);
  - and, for a run with `run_attempt > 1`, `GET /repos/{repo}/actions/runs/{id}/attempts/{n}` for each earlier attempt,
    for its `check_suite_id`;
  - the workflow file is `path` without `.github/workflows/` and without anything from `@` on;
  - a 403 or 404 on the listing gives `{}` and one warning (`the workflow runs of <sha10> could not be read: check runs
    are told apart by check suite`); a 403 or 404 on an attempt read drops only that attempt's suite, whose check runs
    then take the `suite-<id>` key (fail closed); other errors propagate.

  Each check run then gets its identity:
  - an Actions check run takes `suites[check_suite.id]`, or `(f"suite-{id}", "")` when the suite is not found;
  - another app's check run takes `(app.slug, "")`;
  - a check run with no `app` (the old fakes) takes `("", "")`.

  `newest` is keyed by `(workflow, event, name)`, with today's rule (the highest check-run id; `settled`: the newest
  finished one).
- **Re-runs collapse:** every attempt of a workflow run maps to the same workflow file and event, whether GitHub gives
  the attempt a new check suite or not. That is unknown [docs silent], and the attempts read covers both cases.
- **Push and pull_request runs of one workflow stay two jobs:** a red `pull_request` run (it builds the merge ref) is not
  hidden by a green `push` run.
- **Fail closed:** an Actions check run whose workflow is not found keeps its own key and cannot hide another, and its
  `suite-<id>` key matches nothing on the base, so its red counts as new.
- **`evaluate_ci` compares by `key`, not by `name`,** in `named`, the base filter, `base_red` and the failed/preexisting
  split. The base head's jobs come from the base's own workflow runs, so `tests.yml / build` on H meets `tests.yml / build` on
  the base, whatever the event. The ignore list stays by bare `name`, so `l4` of `l4.yml` is still ignored.
- **The sweep records the key:** `ci.failed.jobs[].name` and `ci.preexisting.jobs[]` are `j.key`. A GitHub job also
  records `workflow` and `event`.
- **`LocalForge.script_jobs`** accepts `workflow` and `event` in the extra dict, and its `settled` dedup keys by
  `(workflow, event, name)`.

### D7 No job of the project on H is `not_run`, on every forge

`read_handoff_ci` returns `not_run` when `[j for j in jobs if j.name not in DEFAULT_IGNORE]` is empty. There are three
reason texts:

- GitHub with no check run at all: `NO_CHECK_RUN`, today's text, moved to `handoff_ci.py` and re-exported by
  `sweeper.py`;
- GitHub with only ignored jobs: `ONLY_HARNESS_JOB = "no workflow of the repository ran on the hand-off commit: its
  only check run is the harness's own l4 job"`. It does not name `GITHUB_TOKEN`: a token that starts runs got this far.
- Any other platform: `NO_PIPELINE_JOB = "no pipeline of the project has a job on the hand-off commit"`.

### D8 GitLab parity

What changes on GitLab:

- a hand-off commit with no pipeline job is `ci_not_run` in the sweep, where it was `ci_green` (only the printed line
  changes, nothing was recorded for it), and it blocks a merge only with `require_ci: true`. GitLab creates a pipeline
  some seconds after a push, and "none yet" must not read as green for a merge;
- the merge gate, H binding and review edge rules are the same as on GitHub (`merge_pr` with `sha` refuses a moved head
  with 409).

Job keying does not change. Every pipeline of a commit runs the project's one `.gitlab-ci.yml`, and job names are unique
within it, so a name is one job definition. The newest pipeline's job of a name is its newest attempt (a retried job is
listed in its newest attempt only). Keying GitLab jobs by pipeline would keep a stale red alive after a green re-run.
`JobResult.workflow` stays `""`, so the GitLab names in the ledger do not change.

### D9 Test worlds

- `tests/unit/yolo/yolo_cycle_world.CycleWorld.in_review(name, head, **state)` defaults `ready_head=head` (task 2.1). It
  also scripts one green job on `head`, `ci=(("test", "success"),)`, where `ci=None` scripts nothing (task 6.1).
- The snapshot builders of `test_yolo_merge_guard.py` and `test_yolo_merge_squash.py` set `ready_head` to the hand-off
  commit, and their `FakeForge` classes answer `list_pipeline_jobs` with one green job.
- `tests/unit/forge/_github_helpers.FakeGitHub` gains `add_workflow_run(sha, path, event, *, suite, run_id=None,
  attempts=())` (where `attempts` are the earlier attempts' suite ids) and `add_check_run(..., app=None)`. It also gains
  the routes `/repos/{REPO}/actions/runs` (filtered by `head_sha`, paged, key `workflow_runs`) and
  `/repos/{REPO}/actions/runs/{id}/attempts/{n}`, and `workflow_runs_status` (an int that makes the listing answer that
  status).

### D10 The review's findings F1-F7 (applied after the adversarial review)

- **F1, a job that did not pass (L4-CI-013).** `_CHECK_CONCLUSIONS` passes success, neutral and skipped; failure,
  timed_out, startup_failure, action_required and stale are `failed` (red); `cancelled` stays `canceled`. `repo_ci`
  gets `blocked_jobs` (canceled, and manual with `allow_failure` false) and `all_skipped`. `read_handoff_ci` returns
  `blocked` when the verdict is green or pre-existing and a job is blocked, with `HandoffCi.blocked`; a red job comes
  first (the unit is verified again). The gate is `not_ready` whatever `require_ci` says, naming the jobs and "re-run
  it"; the sweep says `ci_blocked` and records nothing. Every project job skipped is `not_run`. GitLab keeps its status
  words: canceled blocks, a manual job that may not fail blocks, skipped passes.
- **F2, CI not created yet (L4-CI-014).** `list_pipeline_jobs` always reads the workflow runs of the commit, and a run
  that is not `completed` (not the harness's `l4.yml`) is a running job `(workflow run)`. `required_checks(branch)`
  reads `rules/branches/<base>`, else the classic protection (403/404 give nothing); a required name H has not
  reported is `running`. A GitLab pipeline in created, pending, running, waiting_for_resource, preparing or scheduled
  with no project job is a running job `(pipeline <id>)`. `not_run` (no job, all skipped, a required check never
  reported) is final only when `now - ready_at >= WINDOW` (10 minutes); before that it is `running`. `ready_at` is the
  `ts` of the recorded `pr.ready`; an unknown time means no window. The wait chains no run.
- **F3.** The lock-ref residual stays accepted: the CHANGELOG, `docs/yolo-mode.md` and L4-ARC-008 say so.
- **F4, H from the lock ref only.** `fold` no longer handles `pr.ready`. `recorded_ready(pending_events)` returns the
  latest `(head, ts)` among the pending files' events, and `load_snapshot` and the orchestrator's `_refold` set
  `UnitState.ready_head` and `ready_at` (excluded from state.json). A `pr.ready` in the branch tree records nothing.
- **F5, commit statuses (L4-CI-015).** The combined status of the commit is read: failure and error are `failed`,
  pending is `pending`, success is `success`; the harness's own `l4/*` contexts are left out. A status is a job of the
  workflow `status`.
- **F6, same-name runs of one suite.** For each workflow run that has check runs, `jobs?filter=latest` and `filter=all`
  are read: an id in `all` but not in `latest` is a superseded execution and is dropped; an id in neither is no job of
  the run (a reporter's check run) and is keyed by its id, so it never hides or is hidden. A run whose jobs cannot be
  listed keeps the older rule (newest of a name).
- **F7.** Only `l4` of the workflow `l4.yml` (or of no workflow, GitLab and old fakes) is the harness's own job.
- **The merged head.** A squash that comes back `raced` reads the merged PR's head; if a person merged it at another
  head, `unit.merged.head` is that head, not H.

## Risks

- **The lock ref is writable by anyone who can push** (D1). This change raises the bar from "push a commit with copied
  identity text" to "forge a commit on the harness's hidden lock ref"; it does not make it impossible.
- **Merge latency.** A plan that waits for CI on H goes on at the next trigger. On GitHub and GitLab that is the
  30-minute schedule unless something else pushes, so a unit can take up to about 30 minutes longer to merge.
- **Consumers whose hand-off push starts no CI** (GitHub with `GITHUB_TOKEN`) merge as before after the upgrade, on
  record (`ci: not_run`) with a warning. A repository that wants its CI to gate the merge gives the push a token that
  starts runs and sets `require_ci: true`. The CHANGELOG and the runbook say so.
- **`preexisting` merges.** A new failure inside a job that is already red on the base is not seen.
- **GitLab merged-results pipelines** run on a merge ref with another sha. A project that runs only those has no job on
  H, which is `not_run`.
- **Statuses, rules and jobs add calls:** a status listing, a required-checks read (two at most) and two job listings per
  workflow run with check runs, on top of the next item.
- **More forge calls.** There is one extra GitHub listing per job read, plus one per earlier attempt, and a CI read in
  each merge and each wait probe.
- **An unforeseen harness push after H** (none is known in `post_merge_pr`) would cost one more verification round, not
  a wrong merge.
- **Fold order is by `(ts, run_id, seq)`.** A hand-off run on a runner whose clock is far ahead leaves a `pr.ready` that
  outranks a later hand-off's record, so the later H reads as a commit after the recorded H and the unit re-enters
  review until its budgets stop it. The order was already clock-based; `ready_head` makes a skew a loop, not only a
  stale display.

## Owner decisions

1. **`yolo.merge.require_ci` defaults to `false`.** It decides only whether "no CI ran on H" blocks the merge. CI that is
   red on H (and not red on the base), running or unreadable always blocks with `merge_not_ready`. With the default, a
   merge with no CI run on H goes ahead, `unit.merged` records `ci: not_run`, and a warning line goes to the plan report
   and the PR or MR note. With `true`, `not_run` waits.
2. **Red on H that is also red on the base merges,** recorded `ci: preexisting` (L4-ARC-002), as designed.
3. **A commit forged after H goes back to verification** (D2), like a person's push, as designed.
4. **Push and `pull_request` runs of one workflow stay two jobs** (D6), as designed.

## Follow-ups (not in this change)

- Wake the plan when CI on H finishes: a `workflow_run: completed` trigger in the GitHub template and a pipeline event
  on GitLab, instead of the next schedule.
- Sign the harness's commits, or keep H in a ref only the bot can write, to close the lock-ref residual of D1.
- GitLab child pipelines whose job reuses the name of a parent job: key those by the child pipeline's trigger job.
- Ledger fold order under clock skew: order `pr.ready` by the run's position in the lock-ref chain instead of `ts`.
- A live GitHub check, run by the orchestrator: whether a re-run gets a new check suite, and what `path` a reusable or
  dynamic workflow run has.
