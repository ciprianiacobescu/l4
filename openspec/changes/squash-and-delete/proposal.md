## Why

A delivery plan with `merge: auto` lands each verified unit by pushing the unit head to the target as a fast-forward
(L4-YOLO-008). On a consumer repository, seven units put about 110 step commits (red, green, "already satisfied",
verification, hand-off, archive) on the target branch. After each merge, the unit branch `l4/<framework>/<name>` and the
archive branch `l4/archive/<framework>/<name>` stay on the forge: twelve branches after six units. The owner asked for
squash merges and for the merged branches to be deleted, and for both to be the default. The owner keeps the fast-forward
as an option: it is the only method whose freshness the git server enforces.

## What Changes

- **Configuration** (L4-YOLO-032, L4-YOLO-033): `yolo.merge.method: squash | fast-forward` (default `squash`) and
  `yolo.merge.delete_branches` (default `true`). They are read from the base branch like all configuration, and apply
  only to the merges the harness makes for an active `merge: auto` plan.
- **Squash merge** (L4-YOLO-032): the plan step merges a verified unit through the forge's own merge call, pinned to the
  verified head: GitHub `PUT /pulls/{n}/merge` with `merge_method: squash` and `sha`, GitLab
  `PUT /merge_requests/:iid/merge` with `squash: true` and `sha`. The forge marks the PR merged. The preconditions of
  L4-YOLO-008 stay, so the target tip is an ancestor of the head and the squash commit's tree is the verified tree.
  The harness writes the commit message (no `[skip ci]`, the L4 trailers). The forge's call has no guard on the
  target, so the harness compares the landed commit's parent and tree with what it read: a person's push in between
  is recorded (`raced`), and the post-merge check of the landed revision decides as for every merge. A forge that
  refuses a squash is `merge_refused` with the forge's message; the runbook names `method: fast-forward`.
- **The landed commit is recorded apart from the head**: `unit.merged{head, merge_commit, method, raced}`. The
  post-merge check, the receipts, the report and the archived stand-in read `merge_commit`; `reviewed_head` stays the head.
- **Branch deletion** (L4-YOLO-033): after the forge reports a unit's PR merged, the harness pushes the keep ref
  `refs/l4/merged/<framework>/<name>` at the verified head, then deletes the unit branch with a lease on that head.
  After `archive.merged` it deletes the archive branch with a lease on its head. A lease that fails (a person pushed)
  keeps the branch and records why. A plan step also cleans the branches of the plan's integrated units that still point
  at their recorded heads, so branches merged before the upgrade go too. The lock ref is never deleted at merge time.
- **The PR body links `verification.md` at the head sha**, so the link holds after the branch is deleted.
- **The archive merge stays a fast-forward**: it is one harness commit cut from the target tip.

## Impact

- `src/l4/config/schema.py` (`YoloMergeCfg`), `src/l4/forge/{base,github,gitlab,local}.py` (`merge_pr`),
  `src/l4/yolo/{merge,cycle,model,state,report}.py`, `src/l4/postmerge.py`, `src/l4/ci/sweeper.py`, `src/l4/archive.py`,
  `src/l4/vcs/push.py` (lease delete).
- `docs/SPEC.md` (§3.2, L4-YOLO-008, L4-YOLO-032, L4-YOLO-033, L4-ARC-003, L4-OPS-009, scenarios, change row),
  `docs/yolo-mode.md`, `docs/runbook.md`, `CHANGELOG.md`.
- Behaviour change on upgrade: a consumer with an active `merge: auto` plan gets squash merges and branch deletion
  unless it sets `yolo.merge.method: fast-forward` and `delete_branches: false`.
