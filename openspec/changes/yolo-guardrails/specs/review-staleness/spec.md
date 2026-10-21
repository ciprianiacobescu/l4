## Purpose

A delivery plan's commands say what differs and what to run when a review no longer fits what origin holds: which file,
which spec, which commit, and the exact next command, instead of "is for other inputs".

## ADDED Requirements

### Requirement: L4-YOLO-068 A stale review names what differs and the next command
When the latest review of a plan is not for what `origin/<base>` holds, `l4 yolo activate` SHALL refuse with exit 2,
`l4 yolo status` SHALL show it (text and `--json` `review.stale`), and `l4 yolo review` SHALL print it before it asks
CI, each with one line per cause: a review prompt change (both versions); the plan file (its digest at the review and
now, with the short sha of `origin/<base>`); each unit whose spec digest changed (both digests, the ref it is read on
now, `origin/<base>` or its branch, with its short sha, and the files whose content changed when the review recorded
its revisions); each subject the review did not judge; and, when the local HEAD is ahead of `origin/<base>` and they
differ in the plan file or a unit folder, both short shas, the commit counts and those paths, with "push, then review".
The refusal MUST end with a `Fix:` line that holds the exact command. Every `plan.reviewed` event SHALL record
`target_rev` (the sha of `origin/<base>` the review read) and `unit_revs` (per unit, the sha of the revision its folder
was read on). A review without them MUST still give every line except the changed files. A refusal for a plan file that
is not on `origin/<base>` MUST name the sha and, when HEAD or the working tree holds the file, how to push it. A plan
stopped with `inputs_changed` MUST record in its stop detail the frozen and the current digest, where the unit is read,
and the changed files when known. Commit shas MUST be shown as 7 characters and digests as 8.

#### Scenario: SCN-YOLO-177 (−) A spec changed after the review is named with its digests and files
- **GIVEN** plan `p1` reviewed at `origin/main` commit C1, then a pushed commit that changes
  `openspec/changes/add-greeting/tasks.md` (not only a check mark)
- **WHEN** a person runs `l4 yolo activate p1 --reason go`
- **THEN** it exits 2 with `activate: the review of p1 is stale against origin/main (<sha7>):`, a line
  `openspec:add-greeting: spec digest <d8> at the review, <d8'> now on origin/main (<sha7>); changed:
  openspec/changes/add-greeting/tasks.md`, and `Fix: l4 yolo review p1`, and records nothing

#### Scenario: SCN-YOLO-178 (−) A plan file changed after the review is named with both digests
- **GIVEN** plan `p1` reviewed, then a pushed edit of `.l4/plans/p1.json`
- **WHEN** `l4 yolo activate p1 --reason go` runs
- **THEN** the refusal holds `plan file .l4/plans/p1.json: digest <d8> at the review, <d8'> now on origin/main
  (<sha7>)`

#### Scenario: SCN-YOLO-179 (−) An unpushed commit is named, with the push
- **GIVEN** plan `p1` reviewed; then, in a clone at `origin/main`, a commit that changes
  `openspec/changes/add-greeting/proposal.md` is pushed, and a second commit that changes it again is not pushed
- **WHEN** `l4 yolo activate p1 --reason go` runs
- **THEN** the refusal holds `local: origin/main (<o7>) is 1 commit behind HEAD (<h7>); they differ in
  openspec/changes/add-greeting: push, then review` and ends with `Fix: git push origin HEAD:main, then l4 yolo
  review p1`

#### Scenario: SCN-YOLO-180 (+) The status shows the same causes
- **GIVEN** the plan of SCN-YOLO-177
- **WHEN** `l4 yolo status p1` and `l4 yolo status p1 --json` run
- **THEN** the text shows `review: stale` followed by the same cause lines, indented four spaces, and the JSON has
  `review.state == "stale"` and `review.stale` holding the same lines; a current review has no `review.stale` key

#### Scenario: SCN-YOLO-181 (−) A review prompt change names both versions
- **GIVEN** plan `p1` whose latest review was made with review prompt 3 and a harness whose prompt version is 4
- **WHEN** `l4 yolo activate p1 --reason go` runs
- **THEN** the refusal holds `review prompt 3 at the review, 4 in this harness: every subject is judged again` and
  `Fix: l4 yolo review p1`

#### Scenario: SCN-YOLO-182 (−) A plan file that is only in HEAD says to push it
- **GIVEN** `.l4/plans/p1.json` committed locally and not pushed
- **WHEN** `l4 yolo check p1` runs
- **THEN** it exits 2 with `check: no plan file .l4/plans/p1.json on origin/main (<sha7>)` and `Fix: git push origin
  HEAD:main, then run the command again`; with the file only in the working tree the fix is `commit and push
  .l4/plans/p1.json, then run the command again`

#### Scenario: SCN-YOLO-183 (+) Every review records what it read
- **GIVEN** a plan reviewed by the CI step, by `l4 yolo review p1 --local` and by `l4 yolo review p1 --worktree
  --record`
- **WHEN** the three `plan.reviewed` events are read
- **THEN** each holds `target_rev`, the full sha of `origin/main` it read, and `unit_revs` with one full sha per unit;
  for a ledger whose `plan.reviewed` has neither key, a stale refusal still names the digests and names no file

#### Scenario: SCN-YOLO-184 (−) A spec change that stops an active plan is named in the stop detail
- **GIVEN** an active plan `p1` whose review recorded `unit_revs`, and a pushed change of a pending unit's `spec.md`
- **WHEN** the next CI run steps the plan
- **THEN** `plan.stopped{reason: inputs_changed}` has the detail `the spec of <unit> changed after the activation:
  spec digest <d8> frozen at the activation, <d8'> now on origin/main (<sha7>); changed: <path of spec.md>`, and
  `l4 yolo status p1` prints it
