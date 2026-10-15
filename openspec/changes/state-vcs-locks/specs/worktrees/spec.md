## Purpose

One isolated, resumable git worktree per unit, so that any runner can recreate a unit's workspace from the remote.
The hardened git runner, the trailer model and the WIP snapshot primitive are code of this change (`l4.vcs.git`,
`l4.vcs.trailers`, `l4.vcs.wip`), but their requirements are owned by `sandbox-security` (L4-SEC-006) and
`implementer-tdd-loop` (L4-IMP-007, L4-IMP-011).

## ADDED Requirements

### Requirement: L4-WTR-001 (part a) Worktree location
Worktrees SHALL live in `$L4_CACHE/worktrees/<key>/<fw>/<name>`, outside the repository working tree. `<key>` is the repository key (a slug of the last path segment of the `origin` URL and a short hash of its normalised `host/path`, or a hash of the git common dir without an origin): the same for every clone and build directory of one project, different between projects. A checkout found at the path is replaced when its repository has the same key or its clone no longer exists (an orphan); one of another key is refused and never deleted.

#### Scenario: SCN-WTR-N1 (+) Worktree path is outside the repository
- **GIVEN** unit `openspec:add-login` and `L4_CACHE=/var/l4`
- **WHEN** the worktree is ensured
- **THEN** it exists at `/var/l4/worktrees/<key>/openspec/add-login`, `git worktree list` shows it, and `git status` of the main checkout is clean.

### Requirement: L4-WTR-001 (part b) Create from the remote branch or base
A missing worktree SHALL be created with `git worktree add` from the remote unit branch, or, when that branch does not exist, as a new unit branch from the remote base branch.

#### Scenario: SCN-WTR-N2 (+) Created from the existing remote branch
- **GIVEN** `origin/l4/openspec/add-login` exists with two commits and no local worktree
- **WHEN** the worktree is ensured
- **THEN** its HEAD equals the remote branch head.

#### Scenario: SCN-WTR-N3 (+) Created from base when the branch is absent
- **GIVEN** no remote unit branch
- **WHEN** the worktree is ensured
- **THEN** a local branch `l4/openspec/add-login` exists at the head of `origin/<base_branch>`.

### Requirement: L4-WTR-001 (part c) Reuse only after verification
An existing worktree SHALL be reused only after `git fetch` and a check that its HEAD equals the remote unit branch head or the verified WIP snapshot; otherwise it MUST be moved aside and recreated.

#### Scenario: SCN-WTR-N4 (+) A matching worktree is reused
- **GIVEN** a worktree whose HEAD equals the fetched remote branch head
- **WHEN** the worktree is ensured again
- **THEN** the same directory is returned and no `git worktree add` is run.

#### Scenario: SCN-WTR-N5 (−) A diverged worktree is moved aside
- **GIVEN** a worktree whose HEAD matches neither the remote branch nor a WIP snapshot
- **WHEN** the worktree is ensured
- **THEN** the old directory is renamed to `<name>.stale-<run-id>` and a fresh worktree at the remote head is created.

### Requirement: L4-WTR-001 (part d) Pruning
`doctor --fix` SHALL prune stale worktrees and orphaned worktree registrations under `$L4_CACHE` (check GIT-001) and WIP branches of merged or closed units (GIT-003).

#### Scenario: SCN-WTR-N6 (+) Doctor prunes stale worktrees
- **GIVEN** a `<name>.stale-<run-id>` directory older than 7 days and a registration whose directory was deleted
- **WHEN** `l4 doctor --fix` runs
- **THEN** GIT-001 reports both before the fix, the directory is removed and `git worktree prune` has run.

### Requirement: L4-WTR-001 (part e) Base arrives by merge
The base branch SHALL be brought into a unit branch by merge; pushed history MUST never be rebased or rewritten.

#### Scenario: SCN-WTR-N7 (+) Base merged into the unit branch
- **GIVEN** the base branch gained a commit touching a file the unit did not change
- **WHEN** the harness updates the unit branch
- **THEN** a merge commit is created, previously pushed commits keep their SHAs, and the push is a fast-forward.

#### Scenario: SCN-WTR-N8 (−) Pushed history is never rewritten
- **GIVEN** a unit branch with pushed commits and a moved base
- **WHEN** the update runs
- **THEN** no recorded git command is `rebase`, `reset --hard` of pushed commits, `commit --amend` or a push with force.

### Requirement: L4-WTR-001 (part f) Ledger and state.json conflicts
Ledger files SHALL never conflict because each run writes its own file; a conflicted `state.json` SHALL be resolved by re-folding the merged ledger, never by textual merge.

#### Scenario: SCN-WTR-N9 (+) state.json is re-folded after a merge
- **GIVEN** base and unit branch both changed `state.json` through different ledger files
- **WHEN** the merge is resolved
- **THEN** `state.json` equals the fold of all ledger files of both sides.

### Requirement: L4-WTR-001 (part g) tasks.md conflicts
A conflicted `tasks.md` SHALL resolve to the union of done markers when every task text is identical on both sides; if any task text differs the harness MUST escalate.

#### Scenario: SCN-WTR-N10 (+) Union of done markers
- **GIVEN** the same tasks with `[x]` on 1.1 on one side and 1.2 on the other
- **WHEN** the conflict is resolved
- **THEN** both 1.1 and 1.2 are `[x]` and no other byte changed.

#### Scenario: SCN-WTR-N11 (−) Differing task text escalates
- **GIVEN** a task reworded on one side
- **WHEN** the conflict is resolved
- **THEN** the unit is escalated (`escalated`) and the file is left unmerged.

### Requirement: L4-WTR-001 (part h) questions.md conflicts and archive commits
A conflicted `questions.md` SHALL be merged per question ID, keeping the newer human answer text, and archive commits MUST be reverted before the base is merged (L4-ARC-006).

#### Scenario: SCN-WTR-N12 (+) Newer human answer wins per question
- **GIVEN** `Q-001` answered on both sides with different text and `Q-002` raised only on the unit branch
- **WHEN** the conflict is resolved
- **THEN** `Q-001` has the newer human answer and `Q-002` is kept.

### Requirement: L4-WTR-001 (part i) Other conflicts become a conflict task
A conflict in any other file SHALL become an internal harness step "resolve merge conflicts with base", run by the implementer, TDD-exempt with the reason recorded, and SHALL escalate after `max_task_attempts` failures.

#### Scenario: SCN-WTR-N13 (+) Source conflict creates a TDD-exempt task
- **GIVEN** base and unit changed the same lines of a source file
- **WHEN** the merge is attempted
- **THEN** a conflict task is created with `tdd_exempt_reason: merge-conflict` and verification restarts after it.

#### Scenario: SCN-WTR-N14 (−) Repeated conflict failure escalates
- **GIVEN** the conflict task failed `max_task_attempts` times
- **WHEN** the next attempt would start
- **THEN** the unit goes to `escalated` instead.
