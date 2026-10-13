## Context

The facts behind each decision were read in the code at harness 0.2.1 (`3e7dc34a`), and the runbook review of
2026-10-13 checked them again. Paths are relative to `src/l4/`.

- `l4 resume` (`state/resume.py`) runs `run_unit_in_worktree` with `resume_reason`. It records `unit.resumed`, takes
  the `resumed` edge back to `previous_phase`, and pushes `chore(<name>): resume [skip ci]`. It starts no run, and
  outside CI `config/preflight.py` → `forge/base.py:require_forge_target` needs `GITHUB_REPOSITORY` or
  `forge.gitlab.{api_url,project}`.
- The sweep (`ci/sweeper.py:_resume_duty`) honours `l4:resume` on halted and escalated units with an open merge request.
  The member rule is in `ci/resume_label.py:resume_signal`. On an escalated unit it adds one fix round or one feedback
  round.
- An escalation records a reason only for the feedback limit (`ctx.shared["escalation"]`) and for three verifier
  errors (`orchestrator.py:_verify`, `_escalate_verifier`). The fix-round causes live only in `verification.md`'s
  `## Fix unit` (`verifier/fixloop.py`).
- A secret in the outgoing commits sets `_push_failed`, so the halt is never pushed (`orchestrator.py:_scan_outgoing`,
  `_block_secret`).
- `planner._after_capacity` re-enters `waiting_capacity` only from `ready`, `intake`, `implementing`, `implemented` and
  `verifying`, and only with a readable `retry_after`.
- `GitHubForge.dispatch_continuation` starts `l4.yml` on a ref. `GitLabForge.dispatch_continuation` is `unsupported`.
- The forge has no call to close a merge request. A deleted unit branch is exit 1
  (`forge/pushfail.py`: "restore the branch or rerun the unit").

## Goals / Non-Goals

**Goals:**
- One command, and one label, for "try again" and one for "start over", in every stuck situation, with no git or
  forge work by hand.
- The cause of every stop is recorded once and shown where people look: `l4 status`, the note and the log.
- Each command decides from recorded state only. No command asks a model.

**Non-Goals:**
- Merge requests are still never merged by the harness.
- No change to how units are found (base branch only), to dependencies, or to the result contract of prompt-contract
  agents. Those are separate proposals.
- No new budgets. `budgets.max_iterations_per_unit` and the other unread budget keys stay unread.

## Decisions

### D1. Two verbs: `retry` continues, `restart` starts over

`retry` keeps the unit's branch and its work, and moves the unit from where it stopped. `restart` keeps the old work
only as a ref, and implements the unit again from the start. `resume` is kept as `retry` restricted to `halted` and
`escalated`, with its `--extend-fix-rounds` and `--extend-feedback-rounds` flags, so every documented command still
works.

*Alternative considered:* one `l4 unstick` command that chooses between continue and start over. Rejected, because
throwing work away must be a person's explicit choice.

### D2. What `retry` does in each phase

| Phase | Retry does | Recorded |
|---|---|---|
| `halted` | back to `previous_phase`, new task attempts | `unit.retried{reason, by, signal}`, `phase.changed{trigger: resumed}` |
| `halted`, `escalated`, after a person changed the unit folder since the stop | to `implementing` | `phase.changed{trigger: spec_edit_since_stop}` |
| `escalated` at the fix-round limit | `budget.extended{fix_rounds: N}`, then back to `verifying` | N is `--rounds`, default 1 |
| `escalated` at the feedback limit | `budget.extended{feedback_rounds: N}`, then back to `verifying` | |
| `escalated` with `same_failure` | back to `verifying` with one more fix round only if the rounds are used up | so a person changed something, or chose to try once more |
| `escalated` for any other cause | back to `verifying` | |
| `waiting_capacity` | `capacity_restored` now, to `previous_phase` | `retry_after` is ignored, as with `l4 run --unit` today |
| `in_review` | to `verifying` | `phase.changed{trigger: retry_requested}`; replaces the empty commit |
| `merged`, archive failed or Kiro done-gate failed | `archive.failed` is cleared and the archive or the done-gate runs at the next sweep | `archive.retried` |
| `awaiting_human`, `clarifying`, `intake`, `ready`, `implementing`, `implemented`, `verifying`, `fixing`, `verified` | refused with exit 2 and what moves the unit instead | |
| `abandoned`, unstarted | refused with exit 2: "use `l4 restart`" | |

A retry never runs an agent, a gate or the sandbox. It records, commits `chore(<name>): retry [skip ci]` and pushes,
like `resume` today. The person's changes since the stop are the commits after the stop commit on the first-parent
chain that `foreign_tail` already finds (`ci/sweeper.py`), restricted to the unit folder outside harness files
(`.l4/`, `verification.md`, the index of `questions.md`).

### D3. A retry starts the run

After the push, `retry` asks the forge to start the harness's CI on the base branch:
- **GitHub:** `dispatch_continuation(base)`, which already returns `already_queued` when a run waits.
- **GitLab:** a new `start_pipeline(ref)`: `POST /projects/:id/pipeline {ref}` with the forge token. The `l4` job's
  rules already accept the source `api`.

A refused or unsupported start is not an error. The command prints the exact command or forge page that starts a run,
and exits 0. `--no-run` skips the start. The `l4:retry` and `l4:restart` labels start nothing: the sweep that reads
them is already in a run, and that run's `l4 run` continues the unit.

*Alternative considered:* a GitLab trigger token. Rejected: it is one more secret, and the forge token can already
start a pipeline.

### D4. `restart` replaces the branch, and only after its head is kept

`l4 restart --unit U --reason TEXT` runs these steps, in this order:

1. **Refuse** an unstarted, `merged` or locked unit, and refuse with no forge token. Any other phase, `abandoned`
   included, is accepted.
2. **Keep the old work.** Push the old branch head to `refs/l4/attempts/<fw>/<name>/<n>`, where `<n>` is one more than
   the highest existing attempt. Move the lock ref `refs/l4/locks/<fw>/<name>` to
   `refs/l4/attempts/<fw>/<name>/<n>-locks`.
3. **Build the new folder.** It starts from the old branch's unit folder:
   - drop `.l4/` and `verification.md`, and the fix-unit folders `<name>-fix-*`;
   - keep `questions.md` and `feedback.md`;
   - set each task box to its state on the base branch, and to `[ ]` for a task the base does not have.
4. **Create the new branch** from the base head. It has one commit, `chore(<name>): restart, attempt <n> [skip ci]`,
   with the folder and a ledger file. The ledger file holds `run.started`,
   `unit.restarted{attempt, previous_head, reason, by, signal}` and `run.finished`.
5. **Replace the branch.** Push the new branch with `--force-with-lease=<branch>:<old head>`, so a person's push since
   step 2 makes the restart fail and change nothing.
6. **Close the old merge request** with a comment that names the attempts ref and the reason.
7. **Start a run** (D3).

The fold reads `unit.restarted` as the first event of the unit: no phase, so the planner says `implement`. This is the
only place the harness replaces a branch. It is allowed because the old head is a ref first, and a person asked for
it.

*Alternative considered:* restart from the spec on the base branch. Rejected: the live case had its correction only on
the unit branch, and a restart that loses a person's spec edit repeats the failure.

### D5. Every stop records its cause

`phase.changed` into `halted` or `escalated` always carries `reason` (a code) and `detail` (the person's text). The fold
stores both. The codes are:

- **halted:** `max_task_attempts`, `unselectable_task`, `baseline_failed`, `secret_in_push`, `fix_records`;
- **escalated:** `fix_rounds_exhausted`, `no_convertible_finding`, `no_fix_units`, `fix_unit_not_created`,
  `feedback_rounds_exhausted`, `same_failure`, `verifier_errors`.

The verifier's fix loop puts its cause in `ctx.shared["escalation"]` for every cause, not only the feedback limit. The
note headline, `exit_reason` and the log line `[l4] run: <unit> escalated: <detail>` use `detail`.

### D6. `l4 status` and `l4 plan` show the cause and the next command

- **The table:** `l4 status` gets a `REASON` column after `PHASE`, cut to 60 characters. It holds:
  - `detail` for `halted` and `escalated`;
  - the open question ids for `awaiting_human`;
  - `until <time>` for `waiting_capacity`;
  - `-` otherwise.
- **One unit:** `l4 status --unit U` prints a block with the phase, the cause in full, the stop's run id, and
  `Next: <command>`. The command is the one D2 or D4 names, or the answer path for a question.
- **The plan:** `l4 plan` uses the recorded `detail` instead of its fixed texts for `halted` and `escalated`.
- **JSON:** `--json` gains `reason` and `next`.

### D7. `same_failure` ends a repeat

After a verification round fails, the fix loop compares its failure with the previous round's. The failure is the
sorted set of:
- the failed gate names;
- for a failed test gate, the failing test ids from its JUnit report;
- for a gate with no report, the gate name and its exit code.

The rule:
- If the set is not empty, equals the previous round's, and no person's commit came between the two rounds, the unit
  escalates with `same_failure`.
- The detail is `round <n> failed the same way as round <n-1>: <set, cut>`.
- Judge findings are not part of the set, because their wording changes between rounds.

### D8. Labels

- **The names:** `<prefix>retry`, `<prefix>restart`, and `<prefix>resume` (which means `retry`).
- **Who may use them:** the member rule of `resume_signal`. Each label event acts once.
- **When the sweep reads them:**
  - `retry` and `resume` on the unit's open merge request, for the phases D2 accepts;
  - `restart` on an open merge request, or on a closed merge request of an `abandoned` unit.
- **Labels the run creates:** the three operator labels, each time it ensures its phase labels, so a member can find
  them.
- **A refusal:** the text names the command that works. For the token owner, that is
  `l4 retry --unit <unit> --reason TEXT`.

### D9. The stops that could not be resumed

- **A secret halt.** The run discards its unpushed commits (they hold the secret) with a hard reset of the worktree to
  `origin/<branch>`. It records `breaker.tripped` and the halted edge, then pushes the ledger alone. A halt in
  `verifying` or at the hand-off takes the halted edge too: new edges `verifying → halted` and `verified → halted` on
  `breaker_or_budget`.
- **`waiting_capacity`.**
  - The park always records `retry_after`. When the cause gives no time, it is now plus
    `availability.default_cooldown`.
  - The planner maps `previous_phase = fixing` to `implement`.
- **A closed merge request.** When the sweep finds a unit's merge request closed without a merge, it records
  `pr.closed` and takes a new edge, `* → abandoned` on `pr_closed`, from every non-terminal phase.
  - The note says `### Abandoned: the merge request was closed without a merge`, and names `l4 restart`.
  - A merge request reopened by a person, before any restart, takes `abandoned → previous_phase` on `pr_reopened`.
- **A deleted unit branch.** The message names `l4 restart --unit <unit> --reason TEXT`. Restart then starts from the
  base and the attempts ref of the last known head, when one exists.
- **A dismissed verdict question.** It is refused. It reads as `open`, the note says
  `Q-NNN: a verdict question cannot be dismissed: start the answer with accept or reject`, and the plan reason says
  the same.

### D10. `l4 run --unit` on a stopped unit has no side effects

On `halted` and `escalated`, `l4 run --unit` exits 13 before the lease, with the cause and `Next: l4 retry …`. It writes
no ledger, pushes nothing and syncs no label.

### D11. The forge target comes from `origin`

When `GITHUB_REPOSITORY` is not set, the GitHub target is the `owner/name` of a github.com `origin`. The parse is in
`forge/base.py:RemoteUrl`.

When `forge.gitlab.api_url` and `forge.gitlab.project` are not set, the GitLab target comes from `origin`:
- the API URL is `https://<host>/api/v4`;
- the project is the path without `.git`.

Configured values always win. A forge type of `auto` with a github.com `origin` is GitHub outside CI too.

### D12. What the fixer sees is what the verifier runs

The test gate of a fix unit's green step runs with the verifier's coverage plugin (`gates/coverage.cov_env`). Its
output goes to the step's private folder, and only the pass or fail is used. A failure that only the measurement causes
then reaches the fixer as an ordinary failed gate, with its log.

## Risks / Trade-offs

- **Restart replaces a branch** → the old head is pushed to the attempts ref first, the push uses a lease, and the
  command refuses a locked unit. A lost attempts ref is the only way to lose work, and refs under `refs/l4/` are never
  deleted by the harness.
- **A retry from a laptop while CI works on the unit** fails its push (non-fast-forward, exit 1) and changes nothing
  remote. The message says to run it again when the run ends.
- **`same_failure` can stop a fix that would have worked in one more round** → a retry gives that round. The detail
  says so.
- **The new `l4 status` column changes the table** → scripts that parse the table must use `--json`. The runbook
  already says so.
- **The GitLab pipeline API may be refused for a project token** → the start falls back to printing the command (D3).

## Migration Plan

- Existing ledgers fold as before. A missing `detail` reads as the old texts.
- `l4 resume` and `l4:resume` keep working, so no workflow changes for them.
- The runbook's procedures become one command each, and its section 11 loses the limits this change removes.
- Adopters get the new labels and messages with the harness version. No `l4 upgrade` is needed, because the workflow
  files do not change.

## Open Questions

- Should `l4 restart` also be allowed on `merged` units, as a re-implementation of a merged change? No for now: a
  merged change gets a follow-up unit (L4-FBK-010).
