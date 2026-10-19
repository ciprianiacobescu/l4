# Delivery plans (yolo mode)

A delivery plan lets you hand L4 a group of spec units, the order between them and the limits. You review the plan once
and activate it once. L4 then runs the units in dependency order. With the second opt-in, L4 also merges each verified
unit into the integration branch and goes on to the next one. It stops by itself, and says why, when anything is not
right.

This page is for the person who operates a plan. The commands for a stopped plan are in the
[runbook, section 12](runbook.md#12-delivery-plans). The normative text is in [SPEC 12.5](SPEC.md) (L4-YOLO-001..020).

## What it does, and what it does not do

- It runs units in order. A unit starts only when the units it needs are merged into the target and have passed their
  acceptance check.
- It runs one unit at a time.
- With `merge: auto` it merges the PR of each verified unit into the target. Nobody has to be present between units.
- It never promotes. It does not push, open a PR or merge to your production branch (`main`). You do that by hand.
- It does not deploy and it does not roll back.
- By default it merges through the forge's merge call (one squash commit); with `yolo.merge.method: fast-forward` it
  pushes to the target instead and does not work with a target that requires a pull request.

## The plan file

The plan is the file `.l4/plans/<plan-id>.json` on the base branch. The name of the file is the plan id plus `.json`.
The id uses lowercase letters, digits and `-`, and starts with a letter or a digit.

```json
{
  "schema": "l4/delivery-plan@1",
  "plan_id": "checkout-v2",
  "target": "l4/main",
  "merge": "auto",
  "promotion": {"mode": "manual", "target_branch": "main"},
  "limits": {"max_cost_usd": 40, "max_unit_attempts": 2, "max_runs": 60, "deadline": "2026-10-20T18:00:00Z"},
  "external_dependencies": [],
  "exclude": [
    {"id": "kiro:legacy-import", "reason": "in review before the plan"}
  ],
  "batches": [
    {"id": "backend", "depends_on": [], "acceptance_profile": "all", "units": [
      {"id": "openspec:data-contract", "depends_on": [], "acceptance_profile": "all"},
      {"id": "openspec:service-api", "depends_on": ["openspec:data-contract"]}
    ]},
    {"id": "client", "depends_on": ["backend"], "units": [
      {"id": "kiro:client-flow", "depends_on": ["openspec:service-api"]}
    ]}
  ]
}
```

| Field | Meaning |
|---|---|
| `schema` | Always `l4/delivery-plan@1`. |
| `plan_id` | The id of the plan. It must match the file name. |
| `target` | The integration branch. It must be the same as `forge.base_branch`. There is no fallback to another branch. |
| `merge` | `human` or `auto`. See below. |
| `promotion` | Optional note for the hand-off. Only `mode: manual` is valid. L4 never promotes. |
| `limits` | Optional. A missing limit is unlimited, except `max_unit_attempts`, which is 2. |
| `external_dependencies` | Must be empty in this version. Units already delivered on the target (archived OpenSpec changes, merged or archived units) are shown to the readiness judge as satisfied dependencies, so a plan built after another plan needs no entry for them. |
| `batches` | A batch is a group of units. A batch can depend on other batches. |
| `exclude` | Optional. A list of `{"id", "reason"}`: units that this plan deliberately does not deliver. The reason is text of 1 to 200 characters. See below. |
| `units[].depends_on` | Unit ids in the same plan. |
| `acceptance_profile` | A profile of `yolo.profiles` in `.l4/config.yaml`, or `all` (every configured gate), or `none`. A unit has `all` by default. A batch has `none` by default (no batch check). |

An unknown field makes the plan invalid. A unit waits for the units in its `depends_on` and for every unit of the
batches that its batch depends on.

### Exclusions

Every spec of the repository should be in a plan or in a plan's `exclude`. An excluded unit is **not held** by the plan:
while no plan is active on the target (the plan waits for its review or activation, or it completed) it runs as it would
without a plan. While a plan is active it gets no new agent work, like every unit outside the active plan.
`l4 yolo status` lists it under `excluded` with its reason. The exclusions are part of the plan
file, so an edit of them after the activation stops the plan (`inputs_changed`). Admission refuses a unit that is both
planned and excluded (`excluded_and_planned`), a unit excluded twice (`duplicate_id`) and an excluded id that no spec
provider knows (`unknown_unit`).

A derived unit (`<parent>-fix-<n>`, `<parent>-followup-<n>`) is covered when its parent is listed, so that feedback on a
planned unit does not make the repository uncovered.

Profiles are defined in `.l4/config.yaml`:

```yaml
yolo:
  profiles:
    smoke: [build, test]
    full: [build, lint, typecheck, test, e2e]
```

The gate kinds are `setup`, `build`, `lint`, `typecheck`, `test`, `e2e` and `extra:<name>`. A profile passes only when at
least one required gate other than `setup` ran and passed. A profile with no such gate is an error, never a pass. When `gates.setup` is configured and a profile does not list `setup`, `setup` runs first by
itself, because the check runs on a fresh worktree; it never counts toward a pass, and a failed setup fails the check. `none`
is valid for a batch only.

`all` leaves out the `e2e` gates that need an app server (`gates.e2e.serve`), and the result says so. A profile that
names `e2e` while `serve` is set is refused at admission (`unsupported_profile`). The limits are checked too:
`max_unit_attempts` and `max_runs` at least 1, `max_cost_usd` at least 0, and a `deadline` with a time zone.

## Make or change a plan

Do not write the file from nothing. Let L4 list the specs, then add the order yourself (or ask an agent with the skill).

1. `l4 yolo draft <plan-id> [--target BRANCH] [--merge human|auto]` writes `.l4/plans/<plan-id>.json` in the working
   tree. It lists every spec that no plan lists in one batch `unplanned` with no dependencies, and puts a finished spec
   into `exclude` with the reason `already <phase>` (for example `already merged`). It first fetches the base branch and the unit refs, so that a fresh clone reads the
   real phases (without an `origin`, or when the fetch fails, it says the phases may be old). It commits and pushes nothing,
   calls no model, and refuses an existing file. It never adds a dependency: an order is a claim about the specs, and you must make it.
2. Edit the file: move units into batches, add `depends_on` only where a spec uses something that another spec
   introduces or changes, and give each exclusion a reason that a person can check.
3. Run `l4 yolo check <plan-id> --worktree`. It reads the plan files and the units from the working tree, so it runs before
   the push: the schema, the graph, open questions, intake, finished units, profiles, the target and the merge policy,
   and the coverage across all plan files (`uncovered`, `covered_twice`). It prints the findings, the dispatch order and
   the budget warnings, and writes nothing. Without the harness installed, the standalone validator does most of it:
   `scripts/validate_plan.py` (the same file is in the skill, `plugins/l4/skills/l4/scripts/`); it needs only Python and
   also prints the waves. A wave is what could run together; the plan still runs one unit at a time. CI runs the same
   admission and the review.
4. Commit and push the plan file. When the specs it lists are new (not on the target yet), commit them in the same
   commit as the plan file, or push the plan file first: a spec that lands without a plan that holds it runs at once.
   Only an edit of an existing unit's spec stays out of the plan commit. Then run `l4 yolo check <plan-id>` (on the target now), and review
   and activate (below).
5. To add a spec later, run `l4 yolo draft <plan-id> --update`. It appends the new specs to `unplanned` (or to `exclude`),
   keeps every other edit, and reports a unit that is gone as `gone: <id>` without removing it. It warns when the plan is
   active or waiting, because the edit stops it. A unit that the plan has integrated stays in the file and counts as
   done. An edit stops the plan (`inputs_changed`) and needs a new review and activation.

The skill reference `references/plan.md` teaches an agent these steps. The agent never activates, resumes or cancels a
plan (and raises no limit, unless `yolo.extend_by_agents` is true), never writes `refs/l4/plans/*`, and sets `merge: auto` only when you ask and `forge.merge_policy` is `auto`.

## The two merge modes

**`merge: human`.** L4 only orders the work. Each unit gets its PR as usual. A person merges it into the target. At the
next run, L4 sees the merge, runs the acceptance profile of the unit on the merged target, and then lets the next unit
start. Only a merge into the target counts. A merge into another branch does not. This mode needs no extra opt-in.

**`merge: auto`.** L4 merges a verified unit with the method in `yolo.merge.method` (`.l4/config.yaml`):

- `squash` (the default). L4 calls the forge's merge for the PR, pinned to the recorded hand-off commit H: the forge
  refuses if the PR head is not that commit. The target gets one new commit with the PR title and ` (#<pr>)`, no `[skip ci]`, and the
  trailers `L4-Unit`, `L4-Verified-Head` and `L4-Run`. The forge's call has no guard on the target, so L4 then checks
  that the new commit sits on the tip it read and has the head's tree. If a person's commit landed in between, the unit
  is recorded with `raced: true`, the step prints a warning, and the acceptance profile on the landed commit decides
  whether the unit is accepted. The merge cannot be undone. The forge's token must be allowed to merge PRs; a forge
  that has squash merging off, or a rule that blocks the merge, stops the plan with `merge_refused` and the forge's text.
  Set `yolo.merge.method: fast-forward` in that case.
- `fast-forward`. L4 pushes H to the target, without force. The git server accepts the push only if the
  target tip is still part of the head. So a target that moved in the meantime is refused by git, not by a check that
  could be out of date. L4 does not rebase.

The merge lands the hand-off commit H that the hand-off recorded (`pr.ready{head}`), never a commit someone added
after it. It happens only when all of this is true:

1. The unit is `in_review`, its last verdict is PASS, and it has no open question and no open feedback.
2. No commit was made after H, whatever its author, committer or trailers. Such a commit sends the unit back to
   verification, like a person's push. So does a red CI that the sweep recorded on H. H is read from the lock ref's
   pending files only, never from the branch tree. Anyone who can push the lock ref can forge `pr.ready{head}`; that
   residual is accepted, and closing it needs signed harness commits or a ref only the harness can write.
3. H is recorded, and it is the tip of the unit branch on `origin` and the head of the PR. A commit that arrives after
   the check stops the merge.
4. The PR is open, and its base is the target.
5. The target tip is contained in H.
6. The repository's own CI on H (check runs, workflow runs, commit statuses and the base branch's required checks on
   GitHub; pipelines on GitLab) is not running, not red, has no cancelled or held job (re-run it) and is readable. CI
   that is not created yet counts as running for ten minutes after the hand-off; only after that is "no CI" final (a
   repository with no workflow but `l4.yml`, no required check and no status has no such wait). A required check of the base
   branch that H has not reported blocks the merge, whatever `yolo.merge.require_ci` says. A job that is red on H and on the base does not
   block: the unit records `ci: preexisting`. If no CI ran on H at all, the merge goes ahead and `unit.merged` records
   `ci: not_run`, with a warning line in the plan report and a note on the merged PR; with `yolo.merge.require_ci:
   true` the plan waits for a CI instead. On GitHub a push made with the workflow's `GITHUB_TOKEN` starts no run, so a
   repository that wants its CI to gate the merge needs a token that starts runs (a GitHub App) and `require_ci: true`.

L4 records the request, with the lease of the plan ref, before it pushes. It reads the plan again first: a plan that is
cancelled or stopped does not merge.

With `fast-forward`, if the target moved, L4 sends the unit to `verifying`. The verifier merges the new base in and
checks again. If this happens twice for the same attempt, or if the push or the merge call is refused for another reason
(for example a protected branch), the plan stops with `merge_refused`. With `squash`, a PR head that moved makes the
unit wait (`merge_not_ready`) until the next run reads it again. After the merge, L4 runs the acceptance profile of the unit on the merged revision. A
fail or an error stops the plan with `postcheck_failed`. The archive PR of an OpenSpec unit is merged by L4 in the same
way, but only at the head that `archive.opened` recorded when L4 pushed it: a head that a person (or anyone) pushed later is not
merged (`archive.failed`), and a person merges that PR. After `merge_refused`, `l4 yolo resume` resets the count of stale merges, and the next step tries the merge once more.

**Merged branches.** With `yolo.merge.delete_branches: true` (the default), L4 deletes a merged unit's branch and, after
the archive PR merges, its archive branch. It first keeps the verified head at `refs/l4/merged/<framework>/<name>`
(created once, never moved), so receipts and the knowledge graph still reach the commit, and it deletes only when the
forge shows the PR merged and the branch is still at the merged head (a lease): a branch a person pushed to after the
merge stays, and the plan records `unit.branch_kept` with the reason. A deleted branch is `unit.branch_deleted`. The lock
ref stays: the sweep retires it later. Each plan step also cleans up to five branches of earlier merges of the plan's
integrated units, so a plan that was merged before the upgrade is tidied too. Set `delete_branches: false` to keep every
branch. The evidence link in a PR body names the head commit, so it opens after the branch is gone.

L4 does not merge any unit that is not in an active plan with `merge: auto`. This is true whatever `forge.merge_policy`
says. A unit that a person removed from the plan file is not merged by the plan, even if it was the current unit before
the edit.

A unit that is already in review when the plan reaches it is adopted: the plan records it as dispatched, and then
merges it (`merge: auto`) or waits for its merge (`merge: human`). It does not wait for a run that will never come.

## The two opt-ins

Automatic merge needs two separate decisions:

1. **In the configuration:** `forge.merge_policy: auto` in `.l4/config.yaml`. Without a plan, this key does nothing, and
   `l4 doctor` warns about it.
2. **In the plan:** `"merge": "auto"`, and a person runs `l4 yolo activate`.

A plan with `merge: auto` while `forge.merge_policy` is `human` is refused at admission and at activation.

## Review in CI, then activate

1. Push the plan file to the base branch.
2. `l4 yolo check <plan>` (before the push: `l4 yolo check <plan> --worktree`) runs the deterministic checks and prints the order of the units. The checks are: unique ids, known
   units, no cycle, known profiles, `target` equal to the base branch, no open question, the intake checks, and no unit
   that is already merged. It exits 0 or 2. It changes nothing.
3. A CI run reviews the plan. Run `l4 yolo review <plan>` to ask for it now. A judge agent reads each unit, and each
   batch with more than one unit, and gives READY, NEEDS_REVISION or BLOCKED with findings. An answer that is empty or
   not valid is BLOCKED. A blocking finding is never READY. The reviewer never answers a product question.
4. Read the review with `l4 yolo status <plan>`.
5. `l4 yolo activate <plan> --reason "<why>"` is a person's decision. It is refused unless the plan is admitted, the
   review is for the current plan and unit specs and was made with the current review prompt, every unit and batch
   is READY or accepted by a person (see "The review"), `merge` and `forge.merge_policy` agree,
   the target exists on `origin`, and no other plan is active on that target. It freezes a digest of each unit's spec and
   the limits, and starts a run on the target.

Nothing runs from a plan before the activation. The activation freezes the digest of each unit and the digest of the
plan file. If a person changes the spec of a unit afterward (the harness's own task ticks and `verification.md` do not
count), or edits the plan file, the plan stops with `inputs_changed`. A later review changes only the review, not what
the activation froze. If the judge fails or times out, L4 records no review and the next run tries again.
A review made with an older review prompt does not allow an activation. After a harness upgrade, CI reviews again (and
charges for) every plan that is not yet activated and every plan stopped with `inputs_changed`. An active plan is not
reviewed again.

## The review

The runbook has the procedure (section 12.2a). These are the rules.

- **Findings.** `l4 yolo findings <plan>` shows each subject that is not READY with every blocking and major finding in
  full: an id, the criterion, the text and a `Resolve:` line. It also shows the change since the previous judgement and
  the criteria that keep coming back. `l4 yolo status` and the activation refusal show the most severe finding of each
  item and name this command.
- **Incremental.** The judge is asked only about a subject whose material has no recorded verdict. The material is the
  unit folder (check marks included), its plan entry, its prerequisites as the judge sees them and the review prompt
  version. An unchanged unit keeps its verdict at no cost. A change to a prerequisite judges its dependents again. A
  review that did not happen (`schema`, `unit_missing`, `completeness`) is never reused.
- **Budgets.** `yolo.review.max_file_chars`, `max_folder_chars` and `max_dependency_chars` (20,000, 80,000, 20,000)
  limit what the judge reads. A prerequisite folder is shown in this order: proposal, requirements, `specs/**/spec.md`,
  bugfix, design, other files, then `tasks.md`. A cut of a prerequisite does not block: it is listed in the unit's
  `missing`. A cut of the unit's own folder is a blocking `material` finding with the file, its size, the budget, the key
  and the fix. `l4 yolo check --worktree` and `validate_plan.py` print the same overruns before the push; `l4 yolo check` prints them after it, from the target.
- **Check marks.** The judge sees `tasks.md` as the file has it. A ticked task is delivered, and is not a reason for a
  `feasibility` or `duplicate_scope` finding. The unit digest still ignores the marks.
- **Verdict rules.** A NEEDS_REVISION with minor findings only is READY, with the findings kept. A NEEDS_REVISION with no
  finding gets one (criterion `verdict`) that shows the judge's `missing` list. A `batch_acceptance` finding on a unit is
  an assumption.
- **Before the push.** `l4 yolo review <plan> --worktree` reviews the working tree with the same rules. It is a dry run
  with a local cache. Without `bwrap`, outside CI, a tool-less judge (`claude-code`, `opencode`) runs unsandboxed and
  says so.
- **Recording a review.** `--record` records a review of what CI and `l4 yolo activate` read, `origin/<base>`:
  commit, push, then `--record`. It fetches first and refuses before any judge call when HEAD is not `origin/<base>` (the
  refusal names both short shas, the commit counts, the paths that differ and the command), and when a unit's branch on
  origin holds another spec than HEAD. CI then does not review again. The recorded event carries `target_rev` and
  `unit_revs`, the revisions the review read.
- **A stale review.** When the latest review is not for what `origin/<base>` holds, `l4 yolo activate` refuses, and
  `l4 yolo status` and `l4 yolo review` show, one line per cause: the review prompt (both versions), the plan file (both
  digests), each unit whose spec digest changed (both digests, where it is read, the files that changed), a subject the
  review did not judge and unpushed commits, then a `Fix:` line. `l4 yolo review` and `--local` also print a `warning:`
  when HEAD is ahead of `origin/<base>` in the plan file or a unit folder.
- **The override.** `l4 yolo accept <plan> <subject> --reason "<text>"` accepts the remaining findings of a subject on
  record. It needs at least `yolo.review.accept_after_rounds` (2) versions of the subject's text judged not READY. It is
  never allowed for BLOCKED, a blocking finding or a cut of the subject's own folder. An agent may accept only when
  `yolo.review.accept_by_agents` is true in the configuration on the base branch. The acceptance holds while the
  material and the findings stay the same. The activation lists every acceptance.
- **Where an accepted finding goes.** The unit folder gets `.l4/review-accepted.json`. The implementer's prompt holds
  the findings and the reason. The verifier's judge answers for each finding whether the work addressed it. With
  `merge: auto`, a unit with a PASS whose accepted finding is not addressed is not merged: the plan waits with
  `accepted_finding_open`.
- **The waiver.** `l4 yolo waive <plan> <F-id> --reason "<text>"` records, for an active plan, that a person decided an
  accepted finding needs no handling. The merge guard then counts it as answered and the harness merges the unit
  itself. The same rules as accept decide who may waive. The report shows who waived a finding and why. A new
  activation clears the waivers.

## What runs in each CI run

A CI run makes at most one plan step. The step is the first of these that applies. [control-loop.md](control-loop.md)
shows where the plan step sits in a run, and where the plan events are stored (`refs/l4/plans/<plan-id>`).

1. Review a plan that has no current review.
2. For the active plan: stop (a frozen spec changed, a limit is reached, the current unit is `halted`, `escalated`,
   `abandoned` or `rejected`); wait (the current unit needs an answer or capacity); merge a verified unit (`merge:
   auto`) and check it; check a merged unit; check a finished batch; or dispatch the next unit whose prerequisites are
   integrated.
3. Complete the plan and write the report.

After a step that leaves work, the run starts the next run on the target. A plan of N units takes about 3N runs. Units that
are not in the plan get no new agent work while the plan is active, but the sweep still records their merges and
closed PRs. `l4 run --unit <unit>` exits 13 for a unit that is not the current one.

A plan step that fails for a reason that L4 did not expect (for example a network error while it reads the plan ref) does
not fail the run of any other unit. The units of the plan stay held, and the next run tries the step again.

A unit that is in a plan file on the target stays held while the file is there. This is true in every status of the
plan, a cancelled plan included. To release the unit, remove it from the file, or remove the file. A plan file that is
not valid still holds the units that L4 can read in its JSON. A file that is not JSON holds nothing, and `l4 plan` and
`l4 yolo status` report it. A unit that is in two plan files is a finding (`held_by_other_plan`) for the second file.
L4 post-checks every merged unit of the plan that is not integrated, not only the current one.
## Stops and waits

A plan **waits** when the current unit needs a person's answer or has no agent available. The plan continues by itself
when the cause is gone. `l4 yolo resume` also wakes it. A plan that waits for an answer continues at the run that reads
the answer: `l4 questions answer` pushes the answer and starts that run, so no resume is needed. Once the answer is
pushed, `l4 yolo status` says that the next run reads it, and `l4 yolo resume` starts that run at once; while a question
is open, a resume is refused.

A plan with `merge: auto` also waits when the merge of the current unit is not ready, for example when the unit has no
open PR, or the PR is aimed at another branch than the target, when no hand-off commit H is recorded (`l4 retry --unit
<id>` hands the unit off again), when the branch head is not H, when the repository's CI on H is still running, is red
and the sweep has not recorded it yet, cannot be read, or did not run and `yolo.merge.require_ci` is true. The reason is
`merge_not_ready`. The detail is recorded
once and `l4 yolo status` shows it. The plan continues by itself when the merge is ready. If the PR shows an old head
after a push, the step reads the PR again, three times, five seconds apart, before it calls the merge not ready. It does
so in the run that records the wait, not in a preview and not in later runs while the wait for that head stands.

A plan also waits, with the reason `run_not_started`, when the last run of its current unit ended before the unit
started: a usage error, a worktree or lease failure, a missing CLI. The harness records the exit and the reason of that
run (`l4 yolo status` shows them) and starts no next run, so a unit that cannot start does not loop. The next trigger,
a cron run or a push, runs the unit once more, and only once; a run that starts the unit clears the wait. A run that
skipped the unit because another run holds its lease is not a failure of the unit and is not recorded. The reason
`unit_not_started` is a different wait: the unit is eligible but has nothing to run (no task, an unreadable ledger).

A plan **stops** on a fault: `unit_halted`, `unit_escalated`, `unit_abandoned`, `unit_rejected`, `merge_refused`,
`postcheck_failed`, `batch_failed`, `limit_cost`, `limit_runs`, `limit_attempts`, `limit_deadline`, `inputs_changed`,
`capacity_needs_fix` (the unit parked twice in `waiting_capacity` for the same profiles with none cooling: renew the
secret or install the binary, then `l4 yolo resume`), `setup_failed` (the unit's run began and ended with exit 3, a failed `gates.setup` or no usable sandbox: fix it, then
`l4 yolo resume`), `target_missing` and `unit_missing` (the current unit is no longer among the units of the target; the plan continues
when it is back). A merged unit whose folder moved to the archive is not missing: it is integrated. A stopped plan dispatches and merges nothing, including units that do not depend on the failed one. The
cause of each stop and the command that clears it are in [runbook 12.3](runbook.md#123-procedure-a-plan-is-stopped).
`l4 yolo cancel` stops the plan for good.

**`unit_rejected`.** The harness refused the current unit (its spec, or the configuration: an empty `gates.test.command`
is one cause). `l4 retry` never moves a rejected unit, so the plan does not ask for one. Fix the cause. For a spec:
correct it (on the unit branch, or on the target when the unit has no branch) and push. The next run stops the plan with
`inputs_changed`, CI reviews it, and a person runs `l4 yolo activate`. The activation freezes the corrected spec. For the
configuration: set it, then a person runs `l4 yolo activate` (there is nothing to review). The plan then dispatches the
unit, and the next run of the unit reads the corrected spec or configuration. No `l4 restart` is needed. A resume cannot clear this stop: it would only stop the plan again with `inputs_changed`. If the
unit is rejected again after that run, the plan stops again with `unit_rejected`.

**A deleted plan file.** If the file of an active plan is deleted, the plan stops with `inputs_changed` (subject
`plan`). Restore the file, then review and activate again.

## Limits

`limits` has `max_cost_usd`, `max_unit_attempts` (default 2), `max_runs` and `deadline`. L4 charges the usage in the plan
ledger, per attempt of a unit, and checks it before each dispatch and each merge. The figures include the cost of the
attempt that stopped the plan. A restart starts a new attempt and counts as one. The attempts of a unit count from the
activation: restarts before the plan do not count. The cost of the earlier attempts stays in the total, and so does the cost of the review. The usage is never reset:
not by a restart of a unit, not by a resume. A resume without `--extend-…` is refused while the limit is still reached. To allow more, use `l4 yolo resume --extend-cost`, `--extend-runs`, `--extend-attempts` or `--extend-deadline`.
On an **active** plan the same option raises the limit before it is reached: L4 records `plan.extended` (limits before
and after, who, why) and changes nothing else; the plan is not resumed and no run starts. `l4 yolo status` lists the
extensions. Raising a limit is a person's decision: an agent is refused unless `yolo.extend_by_agents` is `true` in
`.l4/config.yaml` on the base branch (default `false`).

## The report and the receipts

When the plan completes, and at each stop, L4 writes `report.md` into the plan ref and into `.l4-out/yolo/`. It states
the repository, the target and its revision, each unit with its PR, merge commit, post-merge result and usage, each batch
result, and the stop reason if any. It always says `Promotion to <branch> was not performed`. Read it with `l4 yolo
report <plan>`. Each integrated unit also gets one receipt, `receipts/<unit-name>.json`, in the plan ref.

## Protected targets

The merge is a push to the target. A target whose protection requires a pull request, or refuses the token of the job,
refuses the push. The plan then stops with `merge_refused` and the message of the forge. Merge through the forge API is
not in this version. Use a target that the job may push to, or use `merge: human`.

## Promotion is manual

When the plan completes, the target holds the integrated units. Review it, then promote it to `main` yourself, for
example with a PR. You can squash there. L4 never does it.

## Known limits

- One unit at a time. One active plan on a target.
- The target gets the commits of the unit branch as they are (no squash).
- GitLab is not validated live for plans. The design uses only git and forge calls that exist on both.
- A unit branch runs the harness version that it pins. The plan step runs in the checkout of the target, so the plan
  logic is always the target's version.
- Receipts of earlier plans are not imported (`external_dependencies` must be empty).

## Commands

| Command | What it does |
|---|---|
| `l4 yolo draft <plan> [--target B] [--merge human\|auto] [--update]` | Writes or updates the plan file in the working tree from the specs that no plan lists. Commits nothing. |
| `l4 yolo check <plan> [--worktree]` | Checks the plan and prints the order. `--worktree`: the working tree's plan, before the push. Changes nothing. |
| `l4 yolo review <plan> [--local]` | Reviews the plan in CI now, or here with `--local`. |
| `l4 yolo review <plan> --worktree [--record] [--fresh <subject>]` | Reviews the working tree before the push (a dry run); `--record` records the review of `origin/<base>` (commit, push, then `--record`; refused while HEAD is another commit). |
| `l4 yolo findings <plan> [<subject>] [--all] [--json]` | Shows the findings of the latest review with how to resolve each. Changes nothing. |
| `l4 yolo accept <plan> <subject> --reason <text> [--withdraw]` | A person accepts the remaining findings of a subject, on record. |
| `l4 yolo activate <plan> --reason <text>` | Freezes the inputs and starts the plan. |
| `l4 yolo status [<plan>] [--json]` | Shows the state, the units, the usage and `Next:`. |
| `l4 yolo cancel <plan> --reason <text>` | Stops the plan for good. |
| `l4 yolo resume <plan> --reason <text> [--extend-…]` | Continues a stopped or waiting plan when the cause is gone; on an active plan, an `--extend-…` raises the limit and resumes nothing. An `--extend-…` is a person's (`yolo.extend_by_agents`). |
| `l4 yolo report <plan>` | Prints the report. |
