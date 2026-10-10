## Purpose
Pull request and merge request lifecycle, the single hand-off commit, post-merge archive (default) and archive-on-approval (opt-in). Race-safe unit-branch pushes (L4-RACE-001) are specified by `state-vcs-locks` (capability `unit-locks`); the archive paths consume `l4.vcs.push`.

## ADDED Requirements

### Requirement: L4-ARC-008 (part a) Single hand-off commit
At PASS, after the provider `done_gate()` succeeds, the harness MUST make exactly one hand-off commit H on the unit branch containing `verification.md`, the round's evidence index and the folded ledger, with no `[skip ci]`, and mark the PR ready; the verdict, evidence, approval and required checks bind to H. A failing done-gate sends the unit to `implementing` instead.

#### Scenario: SCN-ARC-01 (+) Hand-off then archive on approval
- **GIVEN** (`archive.mode: on_approval`) a PASS verdict
- **WHEN** the harness hands off and a member later approves head H with `l4:approve`
- **THEN** exactly one hand-off commit H (no `[skip ci]`) makes the PR ready and the repository's CI runs on it; phase `in_review` with label `l4:in_review`; after the approval the parent then the fix units are archived (`TZ=UTC` dates) in one `chore(…): archive` commit, a verified tag exists, phase `archived`

#### Scenario: SCN-ARC-02 (−) Done-gate fails despite a PASS
- **GIVEN** phase `verified` and a human added an unchecked task to `tasks.md`
- **WHEN** the harness prepares the hand-off
- **THEN** the done-gate fails, phase `implementing`, the new task is scheduled

### Requirement: L4-ARC-008 (part b) Only listed pushes while the PR is ready
While the PR is ready (`in_review`, `archived`) the only harness pushes to the unit branch MUST be, each as one push: (a) on approval the optional base-merge commit plus the archive commit; (b) on a base move the archive revert, base merge and re-archive; (c) when the unit leaves review the archive revert, pushed after the PR was set back to draft.

#### Scenario: SCN-ARC-21 (−) Any other push to a ready unit branch is refused
- **GIVEN** a unit in `in_review` whose PR is ready
- **WHEN** a code path asks the push guard to push a checkpoint commit to the unit branch
- **THEN** the push is refused with `push.not_allowed_in_review`, nothing reaches the remote and the unit branch head stays H

### Requirement: L4-ARC-008 (part c) Head after a push is a harness commit that runs CI
After every push of type (a) or (b) the PR head MUST be a harness commit without `[skip ci]` (the archive commit), so the required checks run on the head a human merges.

#### Scenario: SCN-ARC-29 (+) Archive commit becomes the head and starts CI
- **GIVEN** (`archive.mode: on_approval`) an approved unit whose base moved
- **WHEN** the harness pushes the base merge and the archive commit
- **THEN** the PR head is the archive commit, it carries `L4-Run` and `L4-Phase: archived`, it has no `[skip ci]`, and the repository's CI pipeline exists for it

### Requirement: L4-ARC-008 (part d) Foreign commits void the approval
Any commit after H that the harness did not make (a commit is the harness's only when its author **and** its committer are the bot identity **and** it carries an `L4-Run` trailer, so an amended, rebased or cherry-picked H is a person's) MUST void the approval and remove `archive.approval_label`; answers or spec edits send the unit to `implementing`, anything else to `verifying` for a new round.

#### Scenario: SCN-ARC-16 (−) A human code push after hand-off voids the approval
- **GIVEN** (`archive.mode: on_approval`) a unit in `in_review` with `l4:approve` set for H, and a human pushes a code change to the branch
- **WHEN** the sweeper runs
- **THEN** the approval is voided and the label removed; the unit goes to `verifying` for a new round; nothing is archived for the old evidence

### Requirement: L4-ARC-008 (part e) Draft first before rewriting PR content
Before the harness rewrites the PR content after H (the archive revert) it MUST set the PR back to draft and the `l4/<unit>` status to `pending`.

#### Scenario: SCN-ARC-22 (+) Draft and pending status precede an archive revert
- **GIVEN** (`archive.mode: on_approval`) an `archived` unit and a human spec edit pushed after H
- **WHEN** the harness reacts
- **THEN** the forge call log shows PR set to draft and status `pending` before the revert commit is pushed

### Requirement: L4-ARC-008 (part f) Post-hand-off ledger events stay off the branch
Ledger events produced after H (`phase.changed`, costs, approvals) MUST be written to the unit's lock-ref commits and never to the unit branch, so the PR head stays H until the harness's next listed push folds them in.

#### Scenario: SCN-CI-18 (−) No `[skip ci]` commit ever becomes the PR head after hand-off
- **GIVEN** a unit in `in_review` that records phase changes and costs after H
- **WHEN** the harness writes those ledger events
- **THEN** they go to the lock-ref commit tree (`ledger-pending/…`), the unit branch head stays H, and required checks on H are unaffected

### Requirement: L4-ARC-001 (part a) Approval is bound to head H
With `archive.mode: on_approval`, approval MUST be `archive.approval_label` set by a member with Developer/Write access, or with `accept_forge_approval` a PR review or MR approval, given for head H; approvals recorded for an older head and approvals by non-members MUST be ignored, and the approval label MUST be removed whenever the unit leaves `in_review`/`archived` for any phase other than `merged`.

#### Scenario: SCN-ARC-15 (−) Approval by a non-member is ignored
- **GIVEN** (`archive.mode: on_approval`) a unit in `in_review` and `l4:approve` set by a user without Developer/Write access
- **WHEN** the sweeper runs
- **THEN** no archive happens; the label is removed with an explanatory comment

#### Scenario: SCN-ARC-18 (−) An approval on an older head is ignored
- **GIVEN** (`archive.mode: on_approval`) `l4:approve` was set while H1 was the head; rework produced a new hand-off H2
- **WHEN** the sweeper evaluates approval
- **THEN** the label was removed when the unit left review; a forge approval recorded for H1 does not count for H2

### Requirement: L4-ARC-001 (part b) Archive steps on approval
On a valid approval the harness MUST merge the current base into the unit branch if it moved and re-run verification steps 0-3 when it did, run the provider `done_gate()`, re-validate strictly, archive the parent first and then its fix units in round order with `TZ=UTC` in a single commit `chore(<unit>): archive` with `L4-Phase: archived` and no `[skip ci]`, push it, and create the annotated tag `l4/<fw>/<name>/verified-<round>-<short-sha>`.

#### Scenario: SCN-ARC-08 (+) Kiro archive on approval
- **GIVEN** (`archive.mode: on_approval`) a Kiro unit in `in_review` with `kiro.archive_dir: .kiro/specs/_archive`
- **WHEN** a member sets `l4:approve`
- **THEN** the folder moves to `_archive/<name>/` with its `questions.md` and `.l4/`; the ledger records `archived`, so after the merge the base branch shows the unit as archived

### Requirement: L4-ARC-001 (part c) Archive failure leaves no partial state
On any archive error the harness MUST restore the worktree to the pre-archive commit, push nothing, move the unit to `escalated` with exit 13 and put the CLI error in the sticky comment.

#### Scenario: SCN-ARC-03 (−) Archive error leaves no partial state
- **GIVEN** an approved unit whose `openspec archive` fails (e.g. a MODIFIED requirement missing in the base spec)
- **WHEN** archiving runs
- **THEN** the worktree is restored to the pre-archive commit, nothing is pushed, phase `escalated`, exit 13, with the CLI error in the sticky comment

### Requirement: L4-ARC-002 (part a) Draft PR with a fixed title
The PR/MR MUST be opened as a draft on the first push of the unit branch with the title `[l4] <name>: <first line of proposal Why / requirements intro>`.

#### Scenario: SCN-ARC-24 (+) Draft MR opened on first push
- **GIVEN** a unit whose proposal Why starts with `Users need a greeting.`
- **WHEN** the first push of branch `l4/openspec/add-greeting` is made
- **THEN** a draft MR exists with title `[l4] add-greeting: Users need a greeting.`, and re-running creates no second MR

### Requirement: L4-ARC-002 (part b) PR body regenerated on every phase change
The PR body MUST be regenerated from `state.json` on every phase change and contain the phase, task progress, questions, the last verdict summary, the base SHA and H the evidence refers to, evidence links, cost, profiles and the hint "approve with `l4:approve` to archive" only in `on_approval` mode.

#### Scenario: SCN-ARC-25 (+) Body is a pure function of state
- **GIVEN** the same `state.json` rendered twice
- **WHEN** the body is rendered and written to the forge
- **THEN** both bodies are byte-identical, the second write is skipped, and a changed phase changes only the phase-dependent parts

### Requirement: L4-ARC-002 (part c) Labels and commit status
The harness MUST maintain exactly one `l4:<phase>` label plus `l4:needs-answers` and `l4:escalated` when applicable, never touching non-`l4:` labels, and the commit status `l4/<unit>` with state `pending|success|failed`.

#### Scenario: SCN-ARC-26 (−) Never two phase labels
- **GIVEN** an MR labelled `bug` and `l4:implementing`
- **WHEN** the unit moves to `awaiting_human` with an open question
- **THEN** the MR labels are exactly `bug`, `l4:awaiting_human` and `l4:needs-answers`

### Requirement: L4-ARC-002 (part d) Repository CI failures on the hand-off head
If the repository's own CI fails on H or on the archive commit, the unit MUST return to `verifying` with a deterministic finding `repository CI failed: <job>`, counted only for jobs that are green on the base head; jobs already red on the base are reported as pre-existing and MUST NOT consume fix rounds.

#### Scenario: SCN-ARC-14 (−) Repository CI red on the hand-off head
- **GIVEN** the hand-off push and the repository's own `integration` job fails on it
- **WHEN** the sweeper sees the failed pipeline
- **THEN** phase `verifying`, with a deterministic finding `repository CI failed: integration` → fix unit

#### Scenario: SCN-ARC-19 (+) A CI job already red on the base does not burn fix rounds
- **GIVEN** the repository's `nightly-lint` job fails on the base head and on H
- **WHEN** CI results are evaluated
- **THEN** it is reported as pre-existing; no finding, no fix unit

### Requirement: L4-ARC-003 (part a) The harness never merges code under human policy
With `merge_policy: human` the harness MUST NOT merge any PR/MR and MUST NOT push to the base branch except through its own archive PR, and the PR body MUST recommend the merge-commit method.

#### Scenario: SCN-ARC-07 (−) The harness never merges under `merge_policy: human`
- **GIVEN** any scenario with the fake forge
- **WHEN** the run completes
- **THEN** the fake forge recorded zero merge calls and zero pushes to the base branch

### Requirement: L4-ARC-003 (part b) Merge detection decides archived-ness from the tree
A merged PR detected by the sweeper MUST move the unit to `merged` and delete its WIP branch and lock ref, and whether it is archived MUST be decided from the tree at the merge commit (change folder still under `openspec/changes/`, or the Kiro ledger phase `archived`), never from commit history.

#### Scenario: SCN-ARC-04 (+) Human merge detected
- **GIVEN** a human merged an `archived` unit's PR with a merge commit
- **WHEN** the sweeper runs
- **THEN** phase `merged`; WIP branch and lock ref deleted; no further runs for the unit

#### Scenario: SCN-ARC-13 (−) Merged before approval
- **GIVEN** a unit in `in_review` (not archived) whose PR a human merges without setting `l4:approve`
- **WHEN** the sweeper runs
- **THEN** phase `merged`, and the sweeper opens the post-merge archive PR for that unit

#### Scenario: SCN-ARC-17 (−) Merge during an archive refresh still gets archived
- **GIVEN** (`archive.mode: on_approval`) an `archived` unit whose archive commit the sweeper has just reverted (PR set to draft first)
- **WHEN** a human nevertheless merges at that moment
- **THEN** the sweeper inspects the merge-commit tree, finds the change folder still under `openspec/changes/`, and opens the post-merge archive PR; the spec is not left unarchived

### Requirement: L4-ARC-004 (part a) Human edits after H revert the archive
Answers or spec edits pushed by a human after H, in `in_review` or `archived`, MUST void the approval, make the harness first push a new `revert` commit of its archive commit if one exists (pushed history is never rewritten), move the unit to `implementing` and return the PR to draft.

#### Scenario: SCN-ARC-05 (+) Spec edits during review
- **GIVEN** phase `in_review` and a human pushes an edit to the unit's `design.md` and a new scenario
- **WHEN** CI runs
- **THEN** the PR returns to draft, phase `implementing`, the new scenario's criterion gets an ID; a **new** change folder pushed by the same human would instead be refused (L4-CFG-004)

#### Scenario: SCN-ARC-31 (−) Revert never rewrites pushed history
- **GIVEN** (`archive.mode: on_approval`) an `archived` unit whose archive commit was pushed and a human pushes a spec edit
- **WHEN** the harness reverts the archive commit
- **THEN** the remote branch gains a new `revert` commit on top of the previous head, the archive commit stays in history and no force push is recorded

### Requirement: L4-ARC-004 (part b) Re-archiving never applies a delta twice
Re-archiving after rework MUST start from the change folders restored by the revert, so that the final archive contains each requirement exactly once.

#### Scenario: SCN-ARC-11 (+) Rework after archive never applies deltas twice
- **GIVEN** (`archive.mode: on_approval`) an `archived` unit and a human pushing a spec edit to the branch
- **WHEN** the harness reacts
- **THEN** a revert of the archive commit is pushed first; the change folder is back under `openspec/changes/`; after re-verification and a new approval the archive contains each requirement exactly once

### Requirement: L4-ARC-005 Closed without merge is abandoned
A PR/MR closed without merging MUST move the unit to `abandoned` (terminal: no runs, lock released, WIP branch kept for 30 days), and reopening it MUST restore the phase recorded before `abandoned`.

#### Scenario: SCN-ARC-06 (−) PR closed without merge
- **GIVEN** a human closes the PR
- **WHEN** the sweeper runs
- **THEN** phase `abandoned`; lock released; no further runs; reopening the PR returns the unit to its previous phase

### Requirement: L4-ARC-006 Base moves after archiving
If the base branch moves while a unit is `archived` and the PR is no longer mergeable or the base changed a file under the unit's capability specs, the sweeper MUST set the PR to draft and the status to `pending`, revert the archive commit, merge the base, re-run steps 0-3, re-archive and mark the PR ready; otherwise it MUST leave the PR alone.

#### Scenario: SCN-ARC-09 (+) Base moves after archiving, re-check needed
- **GIVEN** (`archive.mode: on_approval`) an `archived` unit and a base commit that changes `openspec/specs/auth/spec.md` (the unit's capability)
- **WHEN** the sweeper runs
- **THEN** the archive commit is reverted, the base merged, steps 0–3 re-run and pass, the unit re-archived; phase stays `archived`; the PR body shows the new base SHA

#### Scenario: SCN-ARC-10 (+) Two approved units on the same capability
- **GIVEN** (`archive.mode: on_approval`) units A and B both ADD requirements to capability `auth`; both approved; A is merged first
- **WHEN** the sweeper runs for B
- **THEN** B's archive is recomputed on the new base; the merged `openspec/specs/auth/spec.md` contains both sets of requirements with no textual conflict

#### Scenario: SCN-ARC-27 (−) Unrelated base move leaves the PR alone
- **GIVEN** (`archive.mode: on_approval`) an `archived` unit, a mergeable PR and a base commit touching only `README.md`
- **WHEN** the sweeper runs
- **THEN** no revert, no merge, no push and no forge write happens for that unit

### Requirement: L4-ARC-007 (part a) Default post-merge mode needs no approval
With the default `archive.mode: post_merge_pr`, verified units MUST go to `in_review` without archiving and need no approval label, the human merge of H is the sign-off, and while the code PR is ready the harness MUST push nothing to the unit branch.

#### Scenario: SCN-ARC-12 (+) Default post-merge archive
- **GIVEN** the default `archive.mode: post_merge_pr` and a verified unit in `in_review`
- **WHEN** a human merges the code PR (no approval label needed)
- **THEN** phase `merged`; the sweeper opens one harness PR on the base branch containing only that unit's archive changes, built on the latest base; when that PR merges the ledger records `archive.done`; with `auto_merge_archive_pr: true` the harness merges it itself

### Requirement: L4-ARC-007 (part b) Archive-only PR after the merge
After the merge the sweeper MUST open exactly one harness PR on the base branch containing only that unit's archive changes, for a human to merge, and the unit is `archived` (ledger `archive.done`) only when that PR merges.

#### Scenario: SCN-ARC-28 (−) Archive PR carries nothing but the archive
- **GIVEN** a merged unit whose archive run also modified a source file by mistake
- **WHEN** the sweeper builds the archive PR
- **THEN** the build aborts with an error naming the extra path, no PR is opened, and the unit stays `merged` with a recorded `archive.failed` reason

### Requirement: L4-ARC-007 (part c) Archive PRs are serialised across units
Archive PRs MUST be serialised across units: while one harness archive PR is open no other is created, and a later unit's archive PR MUST be built on the latest base after the earlier one merges.

#### Scenario: SCN-ARC-20 (+) Two units merged close together get serialised archive PRs
- **GIVEN** units A and B both ADD requirements to capability `auth`, merged one after the other
- **WHEN** the sweeper runs
- **THEN** A's archive PR is opened first; B's archive PR is built after A's merges, on the new base; the resulting `openspec/specs/auth/spec.md` contains both sets of requirements with no conflict

### Requirement: L4-ARC-007 (part d) Auto-merge of the archive PR is opt-in
The harness MUST merge its own archive PR only when `archive.auto_merge_archive_pr` is `true`; with the default `false` it MUST record zero merge calls for it.

#### Scenario: SCN-ARC-30 (−) Archive PR is not merged by default
- **GIVEN** `archive.auto_merge_archive_pr: false` and an open archive PR with a green pipeline
- **WHEN** the sweeper runs repeatedly
- **THEN** the fake forge records zero merge calls for the archive PR
