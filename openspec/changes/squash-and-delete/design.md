## Context

`yolo/merge.py` merges by `push_fast_forward` after `guarded_push` checked the target tip is an ancestor of the head;
`cycle._merge` records `unit.merged{head, pr, merge_commit=head}` and `_integrate(via_merge=head)` runs the acceptance
profile at the head. `confirm_merged` checks the head is in the target. Nothing deletes a branch after a merge: the WIP
"branch" is a local ref, and the sweeper moves the lock ref to `refs/l4/archived/…` after the archive merge.

## Decisions

### D1 Configuration under `yolo.merge`
`YoloMergeCfg(_Strict)`: `method: Literal["squash", "fast-forward"] = "squash"`, `delete_branches: bool = True`. Under
`yolo` because only plan merges use them (a person merging with `merge: human` uses the forge's own options).

### D2 Squash through the forge's merge call
New protocol method `Forge.merge_pr(number, *, sha, title, message) -> MergeCall` with
`MergeCall{status: "merged" | "head_moved" | "refused", sha: str | None, detail: str}`:
- GitHub `PUT /repos/{o}/{r}/pulls/{n}/merge` `{merge_method: "squash", sha, commit_title, commit_message}`: 200 with
  `merged: true` → `merged`, `sha` the squash commit; 409 (head is not `sha`) → `head_moved`; 405 and 422 (not
  mergeable, squash not allowed, a rule) → `refused` with the forge's message, redacted.
- GitLab `PUT /projects/:id/merge_requests/:iid/merge` `{squash: true, sha, squash_commit_message, merge_commit_message,
  should_remove_source_branch: false}`: 200 → `merged`, `sha` = `squash_commit_sha` or else `merge_commit_sha`;
  409 → `head_moved`; 405, 406, 422 → `refused`. `_pr` reads `squash_commit_sha` when `merge_commit_sha` is empty.
- `LocalForge.merge_pr`: a commit with the head's tree whose parent is the target tip, the target ref moved to it, the
  PR marked merged with that `merge_commit_sha`; counted in `WRITE_CALLS` as `merge`.
A locally built squash commit pushed to the target is rejected: the PR would stay open, and closing it makes the unit
`abandoned`.

### D3 The guard
`merge_guarded` keeps every precondition and `before_push` (R5). With `squash` it then calls `merge_pr(pr, sha=head)`
instead of the push: `head_moved` → `not_ready` (the next run reads again), `refused` → `refused`. After `merged` it
fetches the landed sha and checks: parent == `target_before` and tree == the head's tree. Otherwise
`MergeOutcome.raced = True` with a warning line: a person's push landed between the read and the merge. The merge is
done and cannot be undone; the post-merge check (L4-YOLO-009) of the landed revision decides. With `fast-forward`
nothing changes.

### D4 Records
`MergeOutcome` gains `landed: str | None` (the sha on the target: the head for a fast-forward, the squash commit for a
squash) and `raced: bool`. `unit.merged{unit, head, pr, merge_commit=landed, method, raced}`. `confirm_merged` checks
`landed` is the target tip or an ancestor of it. `_integrate(via_merge=landed)`. `_archived` already reads
`merge_commit` through `state.merged`. Receipts: `merge_commit` = landed, `reviewed_head` = head.

### D5 The squash commit message
Title: the PR title, `[skip ci]` and `[ci skip]` removed, then ` (#<pr>)`. Body: `Squash of <unit id>: <n> commits,
verified head <head>.`, a blank line, the trailers `L4-Unit: <unit id>`, `L4-Verified-Head: <head>`, `L4-Run: <run id>`.
No `[skip ci]`: the target's own CI should see the change (a push made with the workflow's `GITHUB_TOKEN` starts no
workflow anyway, GitHub's rule, so this matches today's fast-forward).

### D6 Deleting a branch with a lease
`vcs/push.py`: `delete_branch(git, branch, expect, config)` = `git push --force-with-lease=refs/heads/<b>:<expect>
origin :refs/heads/<b>`; a stale lease is `kept`, a missing branch is `gone` (nothing to do). `keep_ref(git, ref, sha,
config)` pushes `<sha>:<ref>` with `--force-with-lease=<ref>:` (create only; an existing ref with the same sha is fine).
Order for a unit: forge says merged (the merge call's answer, or `get_pr().state == "merged"` for a fast-forward), then
keep ref `refs/l4/merged/<fw>/<name>` = head, then the delete. A fast-forward whose PR the forge does not show merged
yet keeps the branch until a later step (D7): deleting the head branch of an open PR closes it on GitHub.
Events in the plan ledger: `unit.branch_deleted{unit, branch, head}` or `unit.branch_kept{unit, branch, reason}`;
neither stops the plan.

### D7 Cleanup of earlier merges
When `delete_branches` is on, each plan step lists `refs/heads/<branch_prefix>*` once (one `ls-remote`) and, for every
integrated unit of the plan: a unit branch whose tip equals its recorded `unit.merged` head and whose PR the forge shows
merged gets D6; an archive branch whose PR is merged and whose tip equals that PR's head gets the delete. At most five
deletes per step. Units merged before the upgrade are covered.

### D8 The archive branch
The archive merge stays `guarded_push` (one strict harness commit on the tip). After `archive.merged{head}` the sweeper
deletes the archive branch with a lease on `head` when `delete_branches` is on (the sweeper reads the base's config).

### D9 Links that outlive the branch
`archive.py` links `verification.md` with the head sha instead of the branch name.

## Risks

- The squash call has no guard on the target: D3 detects a race and the post-check decides. `fast-forward` keeps the
  exact guard (the owner's choice, 2026-10-17).
- A forge with squash disabled stops the plan with `merge_refused` and the forge's text; the fix is configuration.
- `refs/l4/merged/*` adds one hidden ref per unit; it keeps the verified commits reachable for receipts, verdict shas and
  the knowledge graph.
