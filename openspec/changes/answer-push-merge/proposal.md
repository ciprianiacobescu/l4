# A person's answers pushed during a run are merged, not lost

## Why

On a consumer (2026-10-30, harness 0.4.40) a person's agent answered 29 questions with
`l4 questions answer` while a run worked on the unit. The answers arrived after the run's `run.started` and after its
first push of the unit branch, about one every 4 s. The run then made 25 commits of its own (the delegate: 1 accept, 24
escalations) and pushed again: the push was refused (`! [rejected] … (stale info)`), the run ended `internal_error`,
its commits and its final ledger never reached the forge, and the ledger file on the branch kept a `run.started` with
no end, so the run looks open for ever [V, the run's log and ledger].

L4-RACE-001 promises that the harness fetches, rebases its own unpushed commits onto a person's push and pushes again.
That path was never built [V]: `Git.push_branch` leases on the tracking ref, a moved branch fails with `stale info`,
`explain_push_failure` turns it into exit 1 with advice to `l4 restart`, and nothing fetches or retries. The
classification of L4-LCK-001 (an atomic push that also advances the lock ref) was not built either: the unit lease is a
file lock on one machine. The openspec tasks for it are open (state-vcs-locks 3.1-3.3, implementer-tdd-loop 2.40,
forge-and-ci 2.57/2.58).

Answering during a run is by design (`unit_refusal`: "the next run takes the answer, also while the unit runs other
tasks"), so today any answer that lands while a run is working breaks that run's next push.

## What changes

- A refused lease on the unit branch is classified by `git ls-remote` against the lease value: the branch is gone
  (today's error, W-D2), it moved forward, or it was rewritten.
- Moved forward, and every path the new commits change is a `questions.md` of the unit's folder or of one of its
  fix-unit folders (what `l4 questions` writes): the harness fetches the remote head, merges it into the run's HEAD
  (`merge --no-ff`, a harness commit; a `questions.md` conflict is resolved per question, a person's answer winning
  over the delegate's), scans the outgoing commits again, and pushes with the lease on the fetched head. At most 3
  tries, 5 s and then 15 s apart; then exit 1, "the unit branch keeps moving".
- Moved forward with any other path, or rewritten: exit 1 with a message that says what happened and that the next
  run starts from the forge's branch; no `l4 restart` advice for a branch that only moved forward.
- A run whose final push of the unit branch fails publishes its ledger to the lock ref's pending ledger, as a run does
  after the hand-off, so the run ends (`run.finished`) and its costs count.
- `l4 questions answer` (and `accept`, `dismiss`) prints an info line when the unit branch's ledger shows an open run
  that has not ended: the run takes the answer at its next push or the next run. Nothing is refused for it.

## Impact

- Code: `l4.vcs.git` (`push_branch`), `l4.vcs.push`, `l4.forge.pushfail`, `l4.orchestrator` (`push`, `close`),
  `l4.vcs.merge` (a merge of the remote unit head), `l4.specs.questions_merge` (precedence), `l4.specs.questions_cli`
  (info line), a liveness helper shared with `l4.yolo.commands._ended_why`.
- Spec: L4-RACE-001 and the classification paragraph of L4-LCK-001 amended; L4-RACE-002 and L4-QMD-011 added;
  SCN-IMP-22 and SCN-LCK-08 amended; SCN-RACE-02 to SCN-RACE-08, SCN-QMD-31 added; change-table row 98.
- Not in this change: a person's push of other files during a run still ends that run (exit 1, now with the right
  message); the run's own commits then stay on the runner. A scripted answer loop faster than the three tries can still
  defeat the merge (then the ledger tail reaches the lock ref and the run's commits stay on the runner).
