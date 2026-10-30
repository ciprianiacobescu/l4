## 1. Classification and merge (L4-RACE-001, L4-LCK-001)

- [x] 1.1 Write the tests first in a new `tests/unit/vcs/test_race.py` (real git: a bare remote and clones, as the other
  `tests/unit/vcs` tests build them): SCN-LCK-08 (gone / moved / rewritten), SCN-IMP-22, SCN-RACE-03, -04, -05 (patch the
  sleep; three tries; 5 s then 15 s), -06. Then implement design D1 and D2 in `l4.vcs.git.push_branch` (or a function it
  calls in `l4.vcs.push` / a new `l4.vcs.race`), factoring the merge machinery out of `l4.vcs.merge.merge_base_into`
  without changing its behaviour. The tracking ref is set to the fetched head before the next lease; the private fetch
  ref is removed afterwards. Record `push.merged` through the caller (the orchestrator owns the ledger). Flip
  `tests/unit/vcs/test_push_branch_guard.py::test_a_branch_a_person_moved_is_not_forced` for the answer-only case and
  keep an other-files case that is still not forced. Report each test failing before and passing after.

  Result: new `l4.vcs.race` (`AnswerMerge`, `push_merging`, `is_answer_file`); `Git.push_branch(..., answers=None)` is now
  `push_branch_once` (one leased push whose refused lease goes through `classify_lease`: `ls-remote`, then a private
  fetch to `refs/l4/tmp/remote-head`, removed again) and, with `answers`, the loop of `push_merging` (answers only:
  wait 5 s / 15 s, look again, merge with the new `merge_commit_into`, call the caller's `rescan`, push under a lease on
  the merged head; 3 pushes in all). `merge_base_into` is a thin wrapper of `merge_commit_into` (same checks and
  results; only the refusal texts take a label). The typed refusals are `BranchGone`, `BranchMoved`, `BranchKeepsMoving`,
  `BranchRewritten` in `l4.vcs.push`, all `PushRejected`. The tests were written together with the code, not before it:
  against the old `src` (stashed) `test_race.py` fails at collection (`BranchGone` is not in `l4.vcs.push`), so the
  failing-first run is only that; the 24 cases pass now, with `test_push_branch_guard` (the other-files case now
  asserts `BranchMoved.paths == ("h.txt",)`; a new answers-only case merges and pushes) and `test_merge`.
  Deviations: (1) `git fetch` of the remote head uses `--refmap=` because a named remote's configured refspec would
  otherwise move the tracking ref, which is the lease value (found by the rewritten-branch test); (2) a merge the
  resolvers cannot settle raises `BranchMoved` with `conflicts` (a fifth case for 2.1 to word, beside D4's four); (3)
  `tests/unit/vcs/test_push_retry.py::test_a_lease_refusal_without_an_earlier_server_error_is_not_looked_up` said
  "no `ls-remote`"; the classification is now that one look, so it asserts exactly one; (4) the caller passes the merge
  commit's trailers, resolvers, `rescan`, `merged` hook, dirty paths and `-c` pairs in `AnswerMerge` (the orchestrator
  wires it in 2.2); (5) a lease refused while the remote still holds the lease value stays an unclassified
  `PushRejected`, and so does a refusal when `ls-remote` or the fetch fails.
- [ ] 1.2 Write the tests first (`tests/unit/specs/test_questions_merge*.py`, find the file): SCN-RACE-02 and the
  precedence rule (design D3) for a delegate answer, a delegate accept and a delegate escalation against a person's
  answer, both orders of time; a base merge case keeps its old result where no delegate line is involved. Then change
  `questions_merge._human`. Do not change `answered_by()`.

## 2. Messages and the run (L4-RACE-002)

- [ ] 2.1 Write the tests first (`tests/unit/forge/test_pushfail.py`): the four D4 messages (gone unchanged, moved with
  other paths, rewritten, keeps moving), exit codes, and that only gone and rewritten name `l4 restart`. Then implement
  them in `l4.forge.pushfail.explain_push_failure` (the classification travels on the exception).
- [ ] 2.2 Write the tests first (an orchestrator test next to the existing close/push tests; find them with
  `grep -rln "_push_failed\|_publish_pending" tests/unit`): SCN-RACE-07 (a secret after the merge: no push), SCN-RACE-08
  (a failed final push publishes the ledger to the lock ref's pending ledger with `run.finished`; `status` then shows no
  open run). Then implement design D5 in `Orchestrator.close()` and wire `push.merged` into `Orchestrator.push`.
  Verify, and pin with a test, that a pending ledger whose events name commits not on the branch (a delegate accept of
  a question whose text on the branch differs) folds without error and that unfreeze/held do not act on it.

## 3. The info line (L4-QMD-011)

- [ ] 3.1 Write the tests first (`tests/unit/specs/test_questions_cli.py`): SCN-QMD-31 (open run with a running CI run →
  line; no open run → none; older than its job timeout → none; forge cannot be asked → the age decides; the forge says
  completed → none). Then lift `yolo.commands._ended_why` (and `END_GRACE_S`, `DEFAULT_JOB_TIMEOUT_S`) into a module both
  import (for example `l4.state.liveness`), keep `l4 yolo status` behaviour (its tests pass unchanged), and print the
  line from `l4 questions answer|accept|dismiss` after the command's own line. SCN-QMD-20 (the lock ref rule) is
  unchanged.

## 4. Openspec bookkeeping and checks

- [ ] 4.1 Mark the old open tasks this change builds or replaces with a one-line note pointing here:
  `openspec/changes/state-vcs-locks/tasks.md` 3.1-3.3, `openspec/changes/implementer-tdd-loop/tasks.md` 2.40,
  `openspec/changes/forge-and-ci/tasks.md` 2.57/2.58 (read each first; tick only what this change does, note the rest
  as superseded by L4-RACE-001's amended text).
- [ ] 4.2 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you changed or added plus the test files that import a module you changed (`grep -rl` for the module name under tests/unit), in one pytest invocation; not whole directories (a combined run follows after the merge). Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass does that).
