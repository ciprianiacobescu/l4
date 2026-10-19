## Purpose

A recorded review is always a review of what origin holds. A person who asks CI to review is told when their own
commits are not part of what CI reads.

## ADDED Requirements

### Requirement: L4-YOLO-069 --record records only a review of origin/<base>
`l4 yolo review PLAN --worktree --record` SHALL fetch `origin/<base>` and, before any judge call, MUST refuse with
exit 2 and record nothing when HEAD is not `origin/<base>`. The refusal MUST name both short shas, the number of
commits HEAD is ahead and behind, the plan paths that differ, and "push, then review" (or the pull), and its `Fix:`
line MUST hold the exact commands. It MUST also refuse when CI reads a unit of the plan on its branch on origin and
that branch holds another spec digest than HEAD. The refusal MUST name the unit, the branch, both digests and the
changed files. When HEAD is `origin/<base>`, it SHALL record the review with `target_rev` equal to HEAD. Its last line
SHALL be `Next: a person runs l4 yolo activate <plan> --reason TEXT` when every subject is READY or accepted, else
`Next: l4 yolo findings <plan>`. The dry run (`--worktree` without `--record`) SHALL keep reading the working tree
whatever HEAD is.

#### Scenario: SCN-YOLO-185 (−) A record with HEAD ahead of origin is refused before any judge call
- **GIVEN** the plan file and the unit folders committed and not pushed: HEAD is 2 commits ahead of `origin/main`
- **WHEN** `l4 yolo review p1 --worktree --record` runs
- **THEN** it exits 2 with `review: --record records what CI and l4 yolo activate read, origin/main, and HEAD is not
  that commit:`, the line `origin/main (<o7>) is 2 commits behind HEAD (<h7>); they differ in .l4/plans/p1.json,
  …: push, then review` and `Fix: git push origin HEAD:main, then l4 yolo review p1 --worktree --record`; no judge
  is called and no event is recorded

#### Scenario: SCN-YOLO-186 (−) A record with HEAD behind or diverged names the pull
- **GIVEN** HEAD 1 commit behind `origin/main`, and in a second case 1 commit only on HEAD and 1 only on origin
- **WHEN** `l4 yolo review p1 --worktree --record` runs
- **THEN** the first exits 2 with `origin/main (<o7>) is 1 commit ahead of HEAD (<h7>): pull, then review` and
  `Fix: git pull --ff-only, then l4 yolo review p1 --worktree --record`; the second with `have diverged: 1 commit only
  on HEAD, 1 only on origin/main` and `Fix: git pull --rebase, then git push origin HEAD:main, then l4 yolo review p1
  --worktree --record`

#### Scenario: SCN-YOLO-187 (−) A unit whose branch holds another spec is refused
- **GIVEN** HEAD equal to `origin/main`, and `origin/l4/openspec/add-greeting` whose `tasks.md` text differs from
  HEAD's
- **WHEN** `l4 yolo review p1 --worktree --record` runs
- **THEN** it exits 2 with `review: --record: CI reads openspec:add-greeting on its branch l4/openspec/add-greeting
  (<sha7>), where its spec digest is <d8>; HEAD has <d8'>; changed: openspec/changes/add-greeting/tasks.md` and
  `Fix: change the spec on l4/openspec/add-greeting (runbook 7.14), or let CI review: l4 yolo review p1`; a branch
  whose folder differs from HEAD only in check marks or harness files is not refused

#### Scenario: SCN-YOLO-188 (+) A record at origin names the next step
- **GIVEN** the plan file and the unit folders pushed, HEAD equal to `origin/main`, and a judge that finds every
  subject READY
- **WHEN** `l4 yolo review p1 --worktree --record` runs
- **THEN** it records `plan.admitted` and `plan.reviewed{target_rev: <HEAD sha>, unit_revs}` and its last line is
  `Next: a person runs l4 yolo activate p1 --reason TEXT`; when a subject is NEEDS_REVISION and not accepted, the last
  line is `Next: l4 yolo findings p1`

#### Scenario: SCN-YOLO-189 (+) The dry run still reads the working tree before the push
- **GIVEN** an unpushed commit and an uncommitted edit of a unit folder
- **WHEN** `l4 yolo review p1 --worktree` runs without `--record`
- **THEN** it reviews the working tree and is not refused; its last line, when every subject is clear, is
  `Next: commit and push the plan file and the unit folders, then l4 yolo review p1 --worktree --record (it records
  the review of origin/main; it judges again whatever the ledger does not hold)`

### Requirement: L4-YOLO-070 The CI review warns about unpushed plan commits
`l4 yolo review PLAN`, without `--worktree` and with or without `--local`, SHALL print one warning before anything
else it prints when HEAD is ahead of `origin/<base>` and HEAD and `origin/<base>` differ in the plan file or a unit
folder of the plan. The warning names both short shas, the count and the paths, and says that the review reads
`origin/<base>`, not the local commits: push, then review. It MUST NOT change the exit code. There MUST be no warning
when the unpushed commits change none of these paths, or when HEAD is only behind.

#### Scenario: SCN-YOLO-190 (+) Unpushed plan commits are named before the review is asked
- **GIVEN** a pushed plan `p1` and a local, unpushed commit that changes `openspec/changes/add-greeting/proposal.md`
- **WHEN** `l4 yolo review p1` and `l4 yolo review p1 --local` run
- **THEN** each prints first `warning: origin/main (<o7>) is 1 commit behind HEAD (<h7>); they differ in
  openspec/changes/add-greeting: CI reviews origin/main, not your commits: push, then review` (`--local reviews
  origin/main, …` for `--local`), and the exit code is the one without the warning

#### Scenario: SCN-YOLO-191 (−) Unrelated or no unpushed commits give no warning
- **GIVEN** a pushed plan `p1`, and in one case an unpushed commit that changes only `README.md`, in another HEAD 1
  commit behind `origin/main`
- **WHEN** `l4 yolo review p1` runs
- **THEN** no line starts with `warning:`
