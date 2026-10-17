## Purpose

A delivery plan's harness merge lands one squash commit by default, and the merged unit and archive branches are
deleted; the fast-forward and keeping the branches stay options.

## ADDED Requirements

### Requirement: L4-YOLO-032 The plan merges a unit by squash unless configured to fast-forward
The configuration SHALL have `yolo.merge.method` (`squash` or `fast-forward`, default `squash`). With `squash`, after
every precondition of L4-YOLO-008 and `unit.merge_requested`, the plan step SHALL merge the unit's PR through the
forge's merge call with the squash method, pinned to the verified head, with a message the harness writes: the PR title
without `[skip ci]` and with ` (#<pr>)`, and the trailers `L4-Unit`, `L4-Verified-Head` and `L4-Run`. A forge answer
that the head moved SHALL be `not_ready`; any other refusal SHALL stop the plan with `merge_refused` and the forge's
message. After the merge the harness SHALL compare the landed commit's parent with the target tip it read and its tree
with the head's tree, and SHALL record `unit.merged{head, merge_commit, method, raced}` with `raced: true` when either
differs. The post-merge check SHALL run on the landed commit. With `fast-forward` the merge SHALL stay the push of
L4-YOLO-008, recorded with `merge_commit` equal to the head.

#### Scenario: SCN-YOLO-76 (+) A verified unit is squash-merged by default
- **GIVEN** an active `merge: auto` plan whose current unit is `in_review` with a PASS, the target tip in its head, and
  no `yolo.merge` configuration
- **WHEN** the plan step runs
- **THEN** the forge's squash merge is called with the head as `sha`, the target's tip is one new commit whose parent is
  the old tip and whose tree is the head's tree, its message has no `[skip ci]` and has `L4-Verified-Head: <head>`, the
  PR is merged, and `unit.merged{merge_commit: <that commit>, method: squash, raced: false}` is recorded

#### Scenario: SCN-YOLO-77 (+) The post-merge check runs on the landed commit
- **GIVEN** the squash merge of SCN-YOLO-76
- **WHEN** the unit is integrated
- **THEN** `unit.postcheck` and `unit.integrated` name the squash commit, and the receipt has `merge_commit` the squash
  commit and `reviewed_head` the head

#### Scenario: SCN-YOLO-78 (+) Fast-forward stays an option
- **GIVEN** the unit of SCN-YOLO-76 and `yolo.merge.method: fast-forward`
- **WHEN** the plan step runs
- **THEN** no merge call is made, the target's tip is the head, and `unit.merged{merge_commit: <head>, method:
  fast-forward}` is recorded

#### Scenario: SCN-YOLO-79 (−) A forge that refuses a squash stops the plan
- **GIVEN** a forge whose merge call answers that squash merging is not allowed
- **WHEN** the plan step merges
- **THEN** `plan.stopped{merge_refused}` carries the forge's message, nothing is deleted, and no later unit is dispatched

#### Scenario: SCN-YOLO-80 (−) A head that moved is not merged
- **GIVEN** a forge whose merge call answers that the PR head is not the given sha
- **WHEN** the plan step merges
- **THEN** nothing is merged, the unit waits `merge_not_ready`, and the plan stays active

#### Scenario: SCN-YOLO-81 (−) A target that moved during the merge is recorded
- **GIVEN** a person's commit that lands on the target after the step read the tip and before the forge squashes
- **WHEN** the squash merge completes
- **THEN** `unit.merged` has `raced: true`, the step prints a warning, and the post-merge check of the landed commit
  decides whether the unit is integrated

### Requirement: L4-YOLO-033 Merged branches are deleted unless configured to stay
The configuration SHALL have `yolo.merge.delete_branches` (default `true`). When it is true, after the forge reports a
plan unit's PR merged, the harness SHALL push `refs/l4/merged/<framework>/<name>` at the verified head and then delete
the unit branch with a lease on that head; after `archive.merged` it SHALL delete the archive branch with a lease on the
archive head. A lease that fails SHALL keep the branch and record `unit.branch_kept{branch, reason}`; a deleted branch
SHALL be recorded as `unit.branch_deleted{branch, head}`. Neither SHALL stop the plan. A plan step SHALL also delete, at
most five per step, the unit and archive branches of the plan's integrated units whose PR is merged and whose tip is
still the recorded head. The lock ref SHALL NOT be deleted at merge time. A branch of a PR the forge does not show
merged SHALL NOT be deleted.

#### Scenario: SCN-YOLO-82 (+) The unit branch is deleted after the merge and its head is kept
- **GIVEN** the squash merge of SCN-YOLO-76 and no `yolo.merge` configuration
- **WHEN** the merge completes
- **THEN** `refs/l4/merged/openspec/<name>` points at the head, `refs/heads/l4/openspec/<name>` is gone on origin, and
  `unit.branch_deleted` is recorded

#### Scenario: SCN-YOLO-83 (−) A branch a person pushed to after the merge stays
- **GIVEN** a merged unit whose branch got a person's commit after the merge
- **WHEN** the harness deletes it
- **THEN** the lease fails, the branch stays with the person's commit, and `unit.branch_kept` names the reason

#### Scenario: SCN-YOLO-84 (+) Branches of units merged before the upgrade are cleaned
- **GIVEN** two integrated units of an active plan whose unit and archive branches still point at their recorded heads
  and whose PRs are merged
- **WHEN** a plan step runs with `delete_branches` on
- **THEN** the four branches are deleted, each unit head has its `refs/l4/merged/…` ref, and a third unit whose branch
  moved after its merge keeps it

#### Scenario: SCN-YOLO-85 (+) Keeping the branches stays an option
- **GIVEN** the merge of SCN-YOLO-76 and `yolo.merge.delete_branches: false`
- **WHEN** the merge and the archive merge complete
- **THEN** both branches stay and no `refs/l4/merged/…` ref is pushed
