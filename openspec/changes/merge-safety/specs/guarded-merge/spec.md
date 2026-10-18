## Purpose

A delivery plan's harness merge lands exactly the hand-off commit H that the hand-off recorded, never a commit someone
added after it, and only when no review edge is pending and the repository's own CI on H allows it. SPEC.md keeps the
full text of each modified requirement; the blocks below state what the requirement says once this change is made.

## MODIFIED Requirements

### Requirement: L4-ARC-008 Hand-off invariant
At PASS the harness SHALL make one hand-off commit H on the unit branch, push it, mark the PR ready and record
`pr.ready{head: H}` on the unit's lock ref; that record SHALL be H from then on, read from the lock ref's pending files only, never from the branch tree. While
the PR is ready, every commit
after the recorded H SHALL be foreign whatever its author, committer or trailers, and a recorded H that is not an
ancestor of the branch head SHALL be rewritten history; both send the unit back. A unit with no recorded H SHALL keep
the identity rule.

#### Scenario: SCN-YOLO-100 (−) A commit after H that claims the bot's identity sends the unit back
- **GIVEN** an active `merge: auto` plan whose current unit is in review with a PASS and `pr.ready{head: H}`, and after
  H a commit that adds `evil.py`, whose author and committer are the bot and which carries an `L4-Run` trailer
- **WHEN** the plan step runs, and then the unit's run
- **THEN** nothing is merged and `evil.py` is not on the target, the commit is listed after the hand-off, the step
  dispatches the unit, and its run takes `commit_after_handoff` to `verifying`

#### Scenario: SCN-YOLO-101 (−) A forged second hand-off commit does not become H
- **GIVEN** the unit of SCN-YOLO-100 with one more commit on top whose subject is the hand-off subject, with
  `L4-Phase: verified` and the bot's identity
- **WHEN** the snapshot is read and the plan step runs
- **THEN** the hand-off commit is the recorded H, both commits are listed after it, the head is not at the hand-off, and
  nothing is merged

#### Scenario: SCN-YOLO-102 (−) A person's commit after H still re-enters review
- **GIVEN** the unit of SCN-YOLO-100 whose commit after H is a person's
- **WHEN** the plan step runs
- **THEN** the commit is listed after the hand-off, nothing is merged, and the step dispatches the unit

#### Scenario: SCN-YOLO-103 (−) A recorded H that is no longer on the branch is rewritten history
- **GIVEN** a unit in review whose branch a person reset to a commit before the recorded H
- **WHEN** the snapshot is read
- **THEN** the review is `lost`, and the review trigger is `commit_after_handoff` with `lost: true`

#### Scenario: SCN-YOLO-104 (+) A unit with no recorded H keeps the identity rule
- **GIVEN** a unit in review whose ledger has no `pr.ready`, a strict harness commit after its hand-off commit, and then
  a person's commit
- **WHEN** the snapshot is read
- **THEN** the hand-off commit is found by its subject, the harness commit is not listed after it, and the person's
  commit is

#### Scenario: SCN-YOLO-125 (−) A pr.ready written into the branch tree is not H
- **GIVEN** a unit in review whose recorded H is on the lock ref, and a commit after H that adds a ledger file with
  `pr.ready{head: X}`, dated far in the future, where X is that commit
- **WHEN** the snapshot is read
- **THEN** the recorded H is still the lock ref's, and the commit after H sends the unit back

### Requirement: L4-YOLO-008 The guarded merge
With `merge: auto` the plan step SHALL merge a unit only when it is in review with a PASS, no open question and no
review edge to take (L4-YOLO-041), the recorded H is the tip of the unit branch on `origin` and the head of the PR
(L4-YOLO-040), the PR is open with the target as base, the target tip is an ancestor of H, and the repository's CI on H
allows it (L4-YOLO-042). It SHALL merge H by the method of `yolo.merge.method`; the other rules of L4-YOLO-008 stay.

#### Scenario: SCN-YOLO-105 (+) A fast-forward merge pushes the recorded H
- **GIVEN** `yolo.merge.method: fast-forward` and a unit in review with a PASS whose recorded H is the branch tip and
  the PR head, with a green CI job on H
- **WHEN** the plan step merges
- **THEN** the target's tip is H, and `unit.merged{head: H, merge_commit: H, ci: green}` is recorded

### Requirement: L4-YOLO-032 The plan merges a unit by squash unless configured to fast-forward
With `yolo.merge.method: squash` the plan step SHALL call the forge's squash merge with `sha` the recorded H, never a
branch tip it read, so a PR whose head moved is refused (`not_ready`). It SHALL compare the landed commit's parent with
the target tip it read and its tree with H's tree, and SHALL record `unit.merged{head, merge_commit, method, raced,
ci, ci_jobs}`, where `head` is H, or the head a person merged the PR at (`raced`). The other rules of L4-YOLO-032 stay.

#### Scenario: SCN-YOLO-106 (+) The squash merge is pinned to the recorded H
- **GIVEN** the unit of SCN-YOLO-105 and the default `squash`
- **WHEN** the plan step merges
- **THEN** the forge's merge call gets `sha` H, the merged PR's head is H, the landed commit's tree is H's tree, and
  `unit.merged{head: H}` names that commit as `merge_commit`

#### Scenario: SCN-YOLO-124 (−) A PR a person merged at another head records that head
- **GIVEN** a squash merge pinned to H, and a person who pushes X and merges the PR at X before the forge answers
- **WHEN** the plan step merges
- **THEN** the forge answers "merged", the merge is `raced`, and `unit.merged` records X as `head` and `ci: unknown`, not H and its verdict

### Requirement: L4-YOLO-013 Stops, waits, cancel and resume
A `merge: auto` plan SHALL wait with `merge_not_ready`, the unit and the detail, recorded once while the detail holds
and starting no run, while its current unit's merge is not ready: no open PR, a PR aimed at another branch, a PR head
that is not the branch tip, no recorded H, a branch head that is not H, or CI on H running, red and not yet recorded,
or unreadable, or not run when `yolo.merge.require_ci` is true. It SHALL go on by itself when the cause is gone; the
other rules of L4-YOLO-013 stay.

#### Scenario: SCN-YOLO-107 (−) A merge that waits for CI is recorded once and chains no run
- **GIVEN** the wait of SCN-YOLO-112 on record
- **WHEN** two more plan steps run while the job still runs
- **THEN** no further `plan.waiting` is written, and neither step starts a run

## ADDED Requirements

### Requirement: L4-YOLO-040 The plan merges the recorded hand-off commit H and nothing after it
The guarded merge SHALL take H from `UnitState.ready_head`. It SHALL be `not_ready` when no H is recorded, naming
`l4 retry --unit <id>`, and when the snapshot's hand-off commit or branch head is not H, naming both shas. Every sha
the merge uses SHALL be H: the `ls-remote` and PR-head checks, the squash `sha`, the fast-forward push, the keep ref and
the leased branch delete.

#### Scenario: SCN-YOLO-108 (−) A head that is not the recorded H is not merged
- **GIVEN** a unit whose recorded H is `H`, whose branch tip on `origin` is a later commit `X`, and a snapshot that
  names `X` as both the hand-off commit and the head
- **WHEN** the guarded merge runs
- **THEN** it is `not_ready` with a detail that names `X` and `H`, nothing is pushed, and no merge call is made

#### Scenario: SCN-YOLO-109 (−) No recorded H, no merge
- **GIVEN** a unit in review with a PASS at its hand-off commit but no `pr.ready` in its ledger
- **WHEN** the guarded merge runs
- **THEN** it is `not_ready` naming `l4 retry --unit openspec:x`, and nothing is pushed

### Requirement: L4-YOLO-041 A review edge comes before the merge
When the plan's current unit is in review with a PASS and the planner gives it work (a commit after H, a spec edit,
rewritten history, or red repository CI recorded on H), the plan step SHALL dispatch the unit and SHALL NOT call the
guarded merge. The guarded merge SHALL itself be `not_ready` when the unit's recorded `ci.failed` is for H.

#### Scenario: SCN-YOLO-110 (−) Red CI recorded on H is verified, not merged
- **GIVEN** an active `merge: auto` plan whose current unit is in review with a PASS, an open PR, and
  `ci.failed{head: H, jobs: [unit-tests]}` recorded
- **WHEN** the plan step runs
- **THEN** no `unit.merge_requested` or `unit.merged` is written, the target does not hold H, and the step dispatches
  the unit (`dispatched openspec:a (in_review)`)

#### Scenario: SCN-YOLO-111 (−) The guarded merge refuses recorded red CI on H
- **GIVEN** the unit of SCN-YOLO-110, given straight to the guarded merge
- **WHEN** it runs
- **THEN** it is `not_ready` with `the repository CI failed on the hand-off commit`, `unit-tests` and `(recorded)`, and
  nothing is pushed

### Requirement: L4-YOLO-042 The merge waits for the repository's CI on H
Before `unit.merge_requested` the guarded merge SHALL read the repository's CI on H as the sweep does (L4-CI-012).
`running`, `failed`, `blocked` (a cancelled or held job), an unreported required check and a read error SHALL be
`not_ready` whatever `yolo.merge.require_ci` says, naming H and the jobs or the check. `green` and `preexisting` SHALL go on, and `not_run` too unless
`yolo.merge.require_ci` is true (L4-YOLO-043). `unit.merged` SHALL record `ci`, and `ci_jobs` for `preexisting`.

#### Scenario: SCN-YOLO-112 (−) CI still running on H holds the merge
- **GIVEN** a unit in review with a PASS at its recorded H, whose job `test` is running on H
- **WHEN** the plan step runs
- **THEN** nothing is merged, and `plan.waiting{merge_not_ready}` says
  `the repository CI is still running on the hand-off commit` with H

#### Scenario: SCN-YOLO-113 (+) The wait ends when H is green
- **GIVEN** the wait of SCN-YOLO-112 and the job now `success`
- **WHEN** the plan step runs
- **THEN** the cause is gone, the unit is merged, and `unit.merged{ci: green}` is recorded

#### Scenario: SCN-YOLO-114 (−) Red CI on H that the sweep has not recorded is not merged
- **GIVEN** a unit in review with a PASS at its recorded H, whose job `test` failed on H and is green on the base,
  with no `ci.failed` recorded
- **WHEN** the plan step runs
- **THEN** nothing is merged, and the wait names `test` and says that the next sweep records it

#### Scenario: SCN-YOLO-115 (+) A job red on H and on the base does not hold the merge
- **GIVEN** a unit in review with a PASS at its recorded H, whose job `lint` failed on H and on the base head
- **WHEN** the plan step runs
- **THEN** the unit is merged, `unit.merged{ci: preexisting, ci_jobs: [lint]}` is recorded, and a warning line names
  `lint`

#### Scenario: SCN-YOLO-116 (−) require_ci true: no CI ran on H, the plan waits and names the fix
- **GIVEN** a unit in review with a PASS at its recorded H, with no job of the project on H and
  `yolo.merge.require_ci: true`
- **WHEN** the plan step runs
- **THEN** nothing is merged, and the wait says that no CI of the repository ran on H and names
  `yolo.merge.require_ci: false`

#### Scenario: SCN-YOLO-117 (−) CI that cannot be read is not green
- **GIVEN** a unit in review with a PASS at its recorded H, and a forge whose CI read fails with HTTP 502
- **WHEN** the plan step runs
- **THEN** nothing is merged, and the wait says that the repository CI of H could not be read

#### Scenario: SCN-YOLO-121 (−) A cancelled job blocks the merge whatever require_ci says
- **GIVEN** a unit in review with a PASS at its recorded H, whose only job `test` was cancelled
- **WHEN** the plan step runs, with `yolo.merge.require_ci` true and false
- **THEN** nothing is merged, no fix round is opened, and the wait names `test` and says to re-run it

#### Scenario: SCN-YOLO-122 (−) CI that is not created yet waits in the window after the hand-off
- **GIVEN** a unit in review with a PASS at its recorded H, no job of the project on H, and `pr.ready` recorded three
  minutes ago
- **WHEN** the plan step runs, and then again ten minutes after the hand-off
- **THEN** the first step merges nothing and starts no run (the CI is still running), and the second merges on record
  with `ci: not_run`

#### Scenario: SCN-YOLO-123 (−) Every project job skipped is not_run
- **GIVEN** a unit in review with a PASS at its recorded H whose only job was skipped, past the window
- **WHEN** the plan step runs with the default configuration
- **THEN** the unit is merged with `ci: not_run`, not `ci: green`; so is a cancelled push job whose pull_request twin
  was skipped, and with `require_ci` true the plan waits

#### Scenario: SCN-YOLO-119 (−) A job recorded as red on the base too, now red on H alone, names the retry
- **GIVEN** a unit in review with a PASS at its recorded H, with `ci.preexisting{head: H, jobs: [lint]}` recorded, and
  `lint` now failed on H and green on the base head
- **WHEN** the plan step runs
- **THEN** nothing is merged, and the wait names `lint` and `l4 retry --unit openspec:a`

### Requirement: L4-YOLO-043 Whether a hand-off commit that no CI ran on is merged is configured
The configuration SHALL have `yolo.merge.require_ci` (default `false`): whether a `not_run` CI on H blocks the merge.
Running, red (new on H) and unreadable CI SHALL block whatever its value. With `false`, `not_run` SHALL NOT block: the
plan step SHALL merge, record `unit.merged{ci: not_run}` and warn in the plan report and on the merged PR or MR. With
`true`, it SHALL be `not_ready`, naming `yolo.merge.require_ci: false`.

#### Scenario: SCN-YOLO-118 (+) By default a hand-off commit that no CI ran on is merged, on record
- **GIVEN** the unit of SCN-YOLO-116 with no `yolo.merge` configuration
- **WHEN** the plan step runs
- **THEN** the unit is merged, `unit.merged{ci: not_run}` is recorded, and a warning line in the plan report names H and
  `yolo.merge.require_ci`

#### Scenario: SCN-YOLO-120 (−) require_ci false still waits for red CI on H
- **GIVEN** `yolo.merge.require_ci: false` and a unit in review with a PASS at its recorded H, whose job `test` failed
  on H and is green on the base, with no `ci.failed` recorded
- **WHEN** the plan step runs
- **THEN** nothing is merged, and the wait names `test`

#### Scenario: SCN-YOLO-126 (−) A required check that H has not reported blocks after the window
- **GIVEN** a base branch that requires `lint`, and a unit in review with a PASS at its recorded H that has not reported
  it, more than ten minutes after the hand-off
- **WHEN** the plan step runs, with `yolo.merge.require_ci` true and false
- **THEN** nothing is merged, and the wait says that the required check `lint` has not reported on H and that GitHub
  will refuse the merge until it does

#### Scenario: SCN-YOLO-127 (+) Required checks that could not be read are said once
- **GIVEN** a forge that answers 403 on every read of the base branch's required checks, and a green CI on H
- **WHEN** the plan step merges
- **THEN** the unit is merged, and the plan report says once that the required checks could not be read

#### Scenario: SCN-YOLO-128 (−) A repository that cannot start any CI does not wait for the window
- **GIVEN** a unit in review with a PASS at its recorded H, handed off a minute ago, in a repository with no workflow
  but `l4.yml`, no required check and no status on H
- **WHEN** the plan step runs
- **THEN** the unit is merged at once with `ci: not_run`

