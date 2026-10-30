# Design: answer-push-merge

## Context (verified on fix-0444 = v0.4.43, read-only analysis of 2026-10-30)

- `Orchestrator.push` (src/l4/orchestrator.py ~353) → `_scan_outgoing` → `Git.push_branch` (src/l4/vcs/git.py ~246):
  lease `--force-with-lease=refs/heads/<b>:<expected>` with `expected` = the tracking ref or what this object pushed
  last; a local pre-check refuses when HEAD does not contain `expected`; `_push(argv, config, is_lost_lease)`; after a
  push the tracking ref is moved by hand (`update-ref`), because no fetch refspec covers the branch.
- `is_lost_lease` / `LEASE_LOST` (src/l4/vcs/push.py ~33, ~68) make `stale info` a `PushRejected`;
  `explain_push_failure` (src/l4/forge/pushfail.py ~67) gives exit 1 "deleted or moved … `l4 restart`". The second
  hint ("a human pushed; the next run continues") is reachable only from the local pre-check.
- `Orchestrator.close()` (~1440): after a failed branch push (`_push_failed`) the final ledger is not pushed; only the
  hand-off path calls `_publish_pending` (lock ref pending ledger, with `keep_unpublished` as fallback).
- Unit branches already carry harness merge commits: `merge_base_into` (src/l4/vcs/merge.py ~151, `merge --no-ff
  --no-commit`, resolvers per path, `MERGE_CONFIG`, harness identity). Walkers use `--first-parent`
  (state/review.py, vcs/authorship.py, verifier/evidence.py — a merge that brings no code is not a new subject).
- `questions.md` is read from the worktree at every use (`Orchestrator._questions`, `implementer/loop.py` ~187), so
  a file merged into the worktree is what the next step reads (level-triggered, P2).
- `merge_questions` (src/l4/specs/questions_merge.py) resolves per question; `_human` uses `answered_by()`, which
  returns `"human"` for every status but `answered-by-clarifier`, so a delegate's accept counts as a person's and the
  newer side wins: the delegate's (made without seeing the person's) would beat the person's. The delegate's answers
  carry the harness-owned `**Answered by:**` line (`Question.answered_by`), its escalations `**Escalated by:**`.
- `unit_refusal` (src/l4/specs/questions_cli.py ~931, R6) refuses only on the lock ref's pending ledger, which a run
  writes only at its end; `status._activity` derives the open run of the branch ledger; `yolo.commands._ended_why`
  decides "ended" by age against the job timeout and `forge.ci_run_state`.

## D1 Classification of a refused lease

In `Git.push_branch`, a `PushRejected` from `is_lost_lease` is followed by `git ls-remote <remote> refs/heads/<b>`:
- no ref → `BranchGone` (today's message, W-D2: never recreated);
- remote head `R` with `expected` an ancestor of `R` (needs `R` locally: fetch it first, D2) → `BranchMoved(R)`;
- otherwise → `BranchRewritten(R)`.
The local pre-check (HEAD does not contain `expected`) is unchanged. The lock-ref comparison of L4-LCK-001 is dropped
from the spec: there is no atomic fencing push; the unit lease is the local file lock.

## D2 Merge of answer-only commits

On `BranchMoved(R)`: `git fetch <remote> +refs/heads/<b>:refs/l4/tmp/remote-head` (a private ref, removed after),
then `git diff --name-only expected R`. When every path is an answer file — the `questions.md` of the unit's folder or
of one of its fix-unit folders on this branch (resolve the fix-unit folders the way `questions_cli` does,
`_holds_fix_folder`) — merge `R` into HEAD:
- reuse `merge_base_into`'s machinery (factor out the shared part; keep `merge_base_into`'s behaviour): `merge --no-ff
  --no-commit`, the open run ledger may be dirty (`keep_dirty`), harness identity, trailers that make it a strict
  harness commit (the same trailers as a base merge, with a message `merge <n> answer commit(s) from the forge`);
- a conflict in a `questions.md` is resolved by `merge_questions` with the remote side as `theirs` (D3); any other
  conflict, or an `Escalate`, aborts the merge → exit 1 as D4;
- then `_scan_outgoing` again (the person's commits are on the forge, so the scan covers the run's commits and the
  merge commit), set the tracking ref to `R`, and push with the lease on `R`.
Up to 3 tries in all (the first push included), 5 s and then 15 s apart, as `push-transient-retry`; each try repeats
D1-D2 from the new remote head. After the third: exit 1 "the unit branch keeps moving on the forge (a person's
answers arrive faster than the run can merge them)". The answers stay on the forge; the next run takes them.

Commits that are not answer files are never merged: a person's code commit merged on the second parent would hide from
the first-parent walkers that tell harness commits from foreign ones.

Mid-run, a merge needs no extra step: the next step reads `questions.md` from the worktree. The ledger records
`push.merged{remote: R, commits: n, paths: [...]}` (new event type, data only; no fold change).

## D3 Precedence in `questions.md`

`questions_merge._human(q)` = answered, status not `answered-by-clarifier`, and no delegate `Answered by:` line
(`q.answered_by == ""`). So for a question both sides changed, a person's answer beats the delegate's accept or answer
and the delegate's escalation (an open question). `answered_by()` keeps its meaning (unfreeze and held read the
recorded digests of the ledger, not this function's word). This also applies to base merges, where it is right for the
same reason.

## D4 Messages (`explain_push_failure`)

- gone: today's text (W-D2, `l4 restart` named) — unchanged;
- moved forward with other paths: "a person pushed <n> commit(s) to <b> during this run that change <first paths>; the
  harness merges only answers to `questions.md`, so this run's work since its last push is not pushed. The next run
  starts from the forge's branch." exit 1, no `l4 restart`;
- rewritten: "<b> was rewritten on the forge (its head no longer contains this run's last push); the harness never
  forces. A person decides: restore the branch, or `l4 restart --unit …`." exit 1;
- keeps moving: D2's text, exit 1.

## D5 The ledger tail of a failed final push (L4-RACE-002)

In `close()`, when the unit branch's push failed in this run (`_push_failed`) or the final `push()` raises, the run
publishes a reduced copy of its ledger file to the lock ref's pending ledger (`_publish_failed_tail`, kept on disk for
the next run when that publish fails too), so the run has its `run.finished` and its costs count. The commits the run
made after its last successful push never reached the branch, so the events that describe them must not be published
as facts: a `delegate.result{answered}` would make `due_questions` (`is_final`) drop a question that is still open on
the branch, and a `task.done` or a phase change would move the fold ahead of the branch. `failed_push_tail(local,
pushed, reason)` (`l4.state.pending`) keeps:
- the lines the branch has (the run's file at `refs/remotes/origin/<branch>`, as of the last successful push; none if the
  run never pushed), unchanged;
- every `budget.cost` (money spent is a fact) and `lock.released`;
- `run.finished`, with `reason: "the push of the unit branch failed: <why>"` added.
Line numbers are kept (a gap is fine: a seq only has to grow). The fold, `due_questions`, `delegate_cost`, unfreeze and
held therefore see the branch's state plus the cost and the end; the readers match digests against the file as it is
now and never look a commit up, which tests pin.

## D6 The info line (L4-QMD-011)

`l4 questions answer|accept|dismiss` reads the unit branch's ledger (`folder_events`, already read for R11) and the
open run (`status._activity`). When there is one and the shared helper (lifted from `yolo.commands._ended_why` to a
module both import; same rules: age against the job timeout plus grace, then `ci_run_state`) does not call it ended,
the command prints, after its own line:
`[l4] questions: run <id> works on <unit> (started <n> min ago): it takes this answer at its next push, or the next run does`.
Exit code and the write are unchanged. When the forge cannot be asked, the age rule alone decides; a failure to read
is silent (info only).

## Tests

`tests/unit/vcs/test_race.py` (new, SCN-IMP-22, SCN-LCK-08, SCN-RACE-02..07) with real git repositories (a bare
remote and two clones, as the other vcs tests do); `test_push_branch_guard.py::test_a_branch_a_person_moved_is_not_forced`
flips for the answer-only case and keeps the other-files case; `test_pushfail.py` gets separate gone / moved /
rewritten / keeps-moving cases; `test_questions_merge*.py` gets the delegate-vs-person cases; `test_questions_cli.py`
the info line (SCN-QMD-31); an orchestrator test for D5 (SCN-RACE-08).

## Residual risks

- A burst of answers faster than 5 s + 15 s defeats the three tries; the answers stay on the forge, the run's commits
  stay on the runner, and its ledger reaches the lock ref (D5).
- A person's push of other files during a run still loses that run's commits since its last push (now said plainly).
