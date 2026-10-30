## Purpose

A person may answer a unit's questions while a run works on the unit. The run merges those answers and pushes; it no
longer fails, loses its commits or leaves its run open for ever.

## ADDED Requirements

### Requirement: L4-RACE-002 A run whose final push fails still ends on the forge
When the push of the unit branch failed during a run, or the final push in `close()` fails, the run SHALL publish its
ledger file to the lock ref's pending ledger (as a run does after the hand-off; kept on disk for the next run when that
publish fails too), so the run's `run.finished` and its events, delegate costs included, reach the forge. Events that
name commits which never reached the branch SHALL NOT break the fold or any reader of the ledger.

#### Scenario: SCN-RACE-08 (+) A failed final push still ends the run on the forge
- **GIVEN** the run's push was refused and could not be recovered
- **WHEN** the run closes
- **THEN** its ledger, with `run.finished`, is in the lock ref's pending ledger, and the next run's status shows no open
  run for it

### Requirement: L4-QMD-011 An answer during a run says which run takes it
`l4 questions answer`, `accept` and `dismiss` SHALL print an info line when the unit branch's ledger shows an `l4 run`
that started and has no end and the liveness rule (age against its job timeout plus grace, then the forge's state of
its CI run; the age alone when the forge cannot be asked) does not call it ended:
`[l4] questions: run <id> works on <unit> (started <n> min ago): it takes this answer at its next push, or the next run does`.
The write and the exit code SHALL be unchanged.

#### Scenario: SCN-QMD-31 (+) An answer during a run names the run
- **GIVEN** the unit branch's ledger has `run.started` of run R 7 minutes ago with a CI link the forge calls running
- **WHEN** `l4 questions answer Q-003 --unit A --text …` runs
- **THEN** the answer is written and pushed, exit 0, and the info line names run R and "started 7 min ago"; with no
  open run, or one older than its job timeout, there is no line

## MODIFIED Requirements

### Requirement: L4-RACE-001 (amendment, concurrent pushes of a person)
Every harness push of the unit branch MUST be a fast-forward under a lease (never a force push). A refused lease SHALL be
classified with `git ls-remote` against the lease value: the branch is gone, it moved forward (the lease value is an
ancestor of the remote head), or it was rewritten. When it moved forward and every path the new commits change is a
`questions.md` of the unit's folder or of one of its fix-unit folders, the harness SHALL fetch the remote head, merge it
into its HEAD with a harness merge commit (a `questions.md` conflict resolved per question, a person's answer winning
over the delegate's), scan the outgoing commits again and push with the lease on the fetched head; at most 3 tries in
all, 5 s and then 15 s apart, then exit 1. Commits that change any other path SHALL NOT be merged: exit 1 with a message
naming the paths and saying that the next run starts from the forge's branch, without `l4 restart` advice. A rewritten
branch SHALL exit 1 and name `l4 restart` as a person's decision; a gone branch keeps W-D2. After a merge, the next
step reads `questions.md` from the worktree. The ledger records `push.merged{remote, commits, paths}`.

#### Scenario: SCN-IMP-22 (amended) A person answers while the harness works
- **GIVEN** a run pushed the unit branch at `A`, then a person pushes an answer to the unit's `questions.md` (`A..P`)
- **WHEN** the run pushes its next commits
- **THEN** the lease is refused, the remote moved forward with answer files only, the harness merges `P`, pushes, and
  the next step reads the answer from the worktree; the ledger has `push.merged{commits: 1}`

#### Scenario: SCN-RACE-03 (−) A person's code commit is not merged
- **WHEN** the new remote commits change `src/app.py` besides `questions.md`
- **THEN** nothing is merged, exit 1, the message names `src/app.py` and the next run, and not `l4 restart`

#### Scenario: SCN-RACE-05 (−) Answers that keep arriving stop after three tries
- **WHEN** a new answer lands before each of three pushes
- **THEN** the run tried 3 times (5 s, 15 s apart) and exits 1 "the unit branch keeps moving"

#### Scenario: SCN-RACE-06 (+) A fix unit's questions are answers too
- **WHEN** the remote commits change only `questions.md` of a fix-unit folder on the branch
- **THEN** they are merged

#### Scenario: SCN-RACE-07 (−) A secret in the outgoing commits stops the push after a merge
- **WHEN** the scan after the merge finds a secret in the run's commits
- **THEN** no push, `guard.secret`, as before the merge

### Requirement: L4-LCK-001 (amendment, classifying a rejected push)
The classification by the lock ref (an atomic push that also advances the lock ref) SHALL be replaced by L4-RACE-001's: the
unit lease is the runner's file lock, and the unit branch's lease value is compared with `git ls-remote`.

#### Scenario: SCN-LCK-08 (amended) A person's push is told apart from a deleted or rewritten branch
- **WHEN** a lease is refused and `ls-remote` shows no branch, a branch whose head contains the lease value, or one
  whose head does not
- **THEN** it is classified gone, moved or rewritten, with the D4 message of each

#### Scenario: SCN-RACE-04 (−) A rewritten branch is not merged
- **WHEN** the remote head does not contain the lease value
- **THEN** exit 1 with the rewritten message naming `l4 restart` as a person's decision

### Requirement: questions merge precedence (amendment of state-vcs-locks 4.6)
In `merge_questions`, a human answer is an answered question whose status is not `answered-by-clarifier` and which has
no delegate `**Answered by:**` line; a delegate's answer or escalation SHALL lose to a person's answer of the same
question.

#### Scenario: SCN-RACE-02 (+) The delegate's accept loses to a person's answer
- **GIVEN** the run's delegate accepted Q-010 and escalated Q-011 (local commits), and a person answered Q-010 and Q-011
  on the forge, earlier in time
- **WHEN** the run merges the forge's head
- **THEN** both questions carry the person's answers; questions only one side changed keep that side
