## Purpose

Guarantee that only one run mutates a unit at a time: a local flock lease and in-process push mutex for the walking
skeleton, then the remote git lease with fenced atomic pushes, and safe handling of concurrent human pushes.

## ADDED Requirements

### Requirement: L4-LCK-001 (part a) Acquire a remote git lease
Before mutating a unit the harness SHALL create a lock commit whose message is JSON `{unit, run_id, holder, acquired_at, expires_at, nonce}` plus `[skip ci]` and an `L4-Run` trailer, and push it to `refs/l4/locks/<fw>/<name>` with an empty expected value, so the ref must not already exist.

#### Scenario: SCN-LCK-N11 (+) Acquire creates the lock ref
- **GIVEN** no lock ref for the unit on the remote
- **WHEN** the harness acquires the lease
- **THEN** the push used `--force-with-lease=refs/l4/locks/<fw>/<name>:`, the ref points at a commit whose first message line is the payload JSON, and `lock.acquired` is in the ledger.

#### Scenario: SCN-LCK-N12 (−) A held lock ref makes acquire fail as busy
- **GIVEN** the lock ref already exists with an unexpired lease
- **WHEN** another run tries to acquire
- **THEN** the push is rejected by the lease, the holder is read from the lock commit, and the result is `Busy(holder)`.

### Requirement: L4-LCK-001 (part b) Never a forced refspec
Every harness push SHALL omit a leading `+` on any refspec and SHALL NOT use `--force`; every push that touches a lock ref MUST carry `--force-with-lease=<ref>:<expected>`. The push builder MUST refuse a violating call before starting git.

#### Scenario: SCN-LCK-04 (−) Never a forced refspec
- **GIVEN** any lock operation
- **WHEN** git commands are recorded
- **THEN** no push refspec starts with `+` and every lock push carries `--force-with-lease=<ref>:<expected>`.

### Requirement: L4-LCK-001 (part c) One in-process writer
All pushes of a run (unit branch, WIP branch, heartbeats) SHALL go through a single in-process mutex that owns the current lock commit, so a heartbeat never races a branch push of the same run.

#### Scenario: SCN-LCK-07 (+) Heartbeats never race the run's own pushes
- **GIVEN** a heartbeat due at the same moment as a task-commit push of the same run
- **WHEN** both execute
- **THEN** they are serialised by the in-process mutex; both succeed; no `lock.stolen`.

### Requirement: L4-LCK-001 (part d) Fenced atomic pushes
Every push to the unit branch and to the WIP branch SHALL be one `git push --atomic` that also advances the lock ref from the holder's current lock commit to a new heartbeat commit with `--force-with-lease=<lock-ref>:<current>`, so a former holder can write neither branch nor WIP.

#### Scenario: SCN-LCK-05 (−) A former lease holder cannot push
- **GIVEN** run A's lease was taken over by run B
- **WHEN** run A attempts an atomic push of the unit branch plus its lock heartbeat
- **THEN** the whole push is rejected by the lease on the lock ref; the unit branch is unchanged; A writes WIP only and exits 1.

### Requirement: L4-LCK-001 (part e) Classify a rejected atomic push
After a rejected atomic push the harness SHALL `git ls-remote` the lock ref and the branch: lock ref changed means lease lost (`lock.stolen`, exit 1); lock ref unchanged and branch moved means a human push; neither moved means a forge rejection, retried once, then `push.rejected` with the server message and exit 1.

#### Scenario: SCN-LCK-02 (−) Lease lost mid-run
- **GIVEN** run A's lease expired and run B took it over
- **WHEN** run A attempts its next fenced push (unit branch or WIP)
- **THEN** the atomic push is rejected; `ls-remote` shows the lock ref moved; A logs `lock.stolen` and exits 1 without writing anything to the remote.

#### Scenario: SCN-LCK-08 (+) A human push is told apart from a lost lease
- **GIVEN** an atomic push rejected because a human pushed to the unit branch (lock ref unchanged)
- **WHEN** the rejection is classified
- **THEN** it is handled as a human push: fetch, rebase the harness's unpushed commits, re-run guards, push again.

#### Scenario: SCN-LCK-10 (−) A push rejected by the forge itself
- **GIVEN** an atomic push rejected while neither the lock ref nor the branch moved (e.g. a protected-branch rule)
- **WHEN** the rejection is classified
- **THEN** the harness retries once, then exits 1 with `push.rejected` and the server's message.

### Requirement: L4-LCK-001 (part f) Renew, take over, release
The holder SHALL renew with a heartbeat push every `locks.lease / 3` through the mutex, MAY take over an expired lease with `--force-with-lease=<ref>:<old-sha>`, and SHALL release by deleting the lock ref with a lease on the current commit.

#### Scenario: SCN-LCK-N13 (+) Heartbeat and takeover
- **GIVEN** `locks.lease: 30m`, a held lease, and later an expired lease of another run
- **WHEN** the holder runs for 25 minutes and a new run starts after the old lease expired
- **THEN** the holder pushed heartbeats at 10 and 20 minutes, and the new run takes over with the old SHA as expected value and records `lock.acquired`.

#### Scenario: SCN-LCK-N14 (−) A stale release is rejected
- **GIVEN** run A's lease was taken over by run B
- **WHEN** run A tries to release its lease
- **THEN** the delete is rejected by the lease and B's lock ref is unchanged.

### Requirement: L4-LCK-001 (part g) A busy unit is skipped
When a live holder has the lease, the run SHALL log `lock.busy{holder}`, skip the unit without touching it, and exit 0 for that unit.

#### Scenario: SCN-LCK-01 (−) Two runs, one unit
- **GIVEN** two jobs start `l4 run --unit X` simultaneously
- **WHEN** both try to acquire the lease
- **THEN** exactly one succeeds; the other logs `lock.busy{holder}` and exits 0 without touching the unit.

### Requirement: L4-LCK-001 (part h) Local flock on shared runners
On shared shell runners the harness SHALL additionally hold an exclusive non-blocking `flock` on `$L4_CACHE/locks/<key>/<fw>/<name>.lock` (`<key>`: the repository key of L4-WTR-001) for the whole mutation, taken before the unit's worktree is prepared or removed. In the walking skeleton this flock plus the in-process mutex is the lease.

#### Scenario: SCN-LCK-N15 (+) Flock excludes a second process
- **GIVEN** process A holds the flock for unit X
- **WHEN** process B on the same runner tries to acquire it
- **THEN** B gets `Busy` without any remote git call, and after A exits (even by SIGKILL) a new acquire succeeds.

#### Scenario: SCN-LCK-N16 (−) Different units do not block each other
- **GIVEN** process A holds the flock for unit X
- **WHEN** process B acquires the lock for unit Y
- **THEN** B succeeds.

### Requirement: L4-LCK-001 (part i) WIP restore only under a valid lease
Every fenced WIP push SHALL record the WIP commit SHA as `wip_sha` in the lock commit it advances, and a new holder SHALL restore a WIP snapshot only if its SHA equals the `wip_sha` of the last lock commit of a lease valid when pushed.

#### Scenario: SCN-LCK-09 (−) A fenced-out holder's WIP is never restored
- **GIVEN** a former holder tries to push a WIP snapshot after losing the lease
- **WHEN** the new holder resumes
- **THEN** that push was rejected by the lease; only WIP snapshots pushed under a valid lease are restored.

### Requirement: L4-LCK-002 (part a) Branch-lock fallback
If the forge rejects custom refs (doctor FORGE-005), the harness SHALL use the branch `l4-lock/<fw>/<name>` with the same lease protocol, and its commits MUST carry `[skip ci]` and the `L4-Run` trailer so they never start pipelines.

#### Scenario: SCN-LCK-03 (−) Forge rejects custom refs
- **GIVEN** the forge refuses `refs/l4/locks/*`
- **WHEN** doctor and run execute
- **THEN** FORGE-005 warns; locks use `l4-lock/<fw>/<name>` branches with the same lease protocol.

### Requirement: L4-LCK-002 (part b) Degraded mode without atomic pushes
If the forge does not support atomic pushes (doctor FORGE-006), fencing SHALL degrade to verifying the lease and then pushing, with a warning in every run's log, and `ci.max_parallel_units` MUST be treated as 1.

#### Scenario: SCN-LCK-06 (−) No atomic push support
- **GIVEN** a forge that rejects `--atomic`
- **WHEN** doctor and run execute
- **THEN** FORGE-006 warns; runs log the degraded fencing; `ci.max_parallel_units` is treated as 1.

### Requirement: L4-RACE-001 (part a) Fast-forward pushes only
Every harness push to a unit branch SHALL be a fast-forward of the remote branch and MUST NOT be a force push, with or without a lease.

#### Scenario: SCN-RACE-N1 (−) A non-fast-forward push is never forced
- **GIVEN** a remote unit branch that has a commit the harness lacks
- **WHEN** the harness pushes its commit
- **THEN** git rejects it as non-fast-forward and no recorded command contains `--force`, `-f` or a `+` refspec.

### Requirement: L4-RACE-001 (part b) Recover from a concurrent human push
On a rejection classified as a human push the harness SHALL fetch, rebase only its own unpushed commits onto the remote head, re-run the post-step guards and affected gates, and push again, at most 3 attempts, then exit 1.

#### Scenario: SCN-RACE-N2 (+) Rebase own commits and push again
- **GIVEN** a human pushed a commit to `questions.md` while the harness held two unpushed commits
- **WHEN** the harness push is rejected
- **THEN** the two commits are rebased onto the human's head, guards re-run, and the next push succeeds as a fast-forward.

#### Scenario: SCN-RACE-N3 (−) A fourth attempt is not made
- **GIVEN** a human who pushes again after each of the harness's three attempts
- **WHEN** the third retry is rejected
- **THEN** the harness exits 1 and the unit branch contains only the human commits.

#### Scenario: SCN-IMP-22 (−) Human pushes to the unit branch while the harness runs
- **GIVEN** a human pushes an answer to `questions.md` while the harness is in a green phase
- **WHEN** the harness pushes its commit
- **THEN** the push is rejected (non-fast-forward); the harness fetches, rebases its own commits onto the human's, re-runs the guards, pushes; if the human changed `tasks.md` or spec files, the harness finishes the current commit, then re-plans from the new state on the next step

### Requirement: L4-RACE-001 (part c) Re-plan after a remote change to harness inputs
If a concurrent remote change touched `tasks.md`, spec files or `questions.md`, the harness SHALL complete its current commit and re-plan from the new state before the next step.

#### Scenario: SCN-RACE-N4 (+) Level-triggered re-plan
- **GIVEN** a human push that changed `tasks.md` while the harness was in a green phase
- **WHEN** the harness has pushed its commit after the rebase
- **THEN** the current commit is complete and the next step starts from a re-read of the task list.
