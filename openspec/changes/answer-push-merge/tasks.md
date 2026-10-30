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
- [x] 1.2 Write the tests first (`tests/unit/specs/test_questions_merge*.py`, find the file): SCN-RACE-02 and the
  precedence rule (design D3) for a delegate answer, a delegate accept and a delegate escalation against a person's
  answer, both orders of time; a base merge case keeps its old result where no delegate line is involved. Then change
  `questions_merge._human`. Do not change `answered_by()`.

  Result: `_human` is now answered, not `answered-by-clarifier`, and `question.answered_by == ""`; `answered_by()` is
  untouched. Five new tests (eight cases) in `tests/unit/specs/test_questions_merge.py` (SCN-RACE-02 in both orders of time, the
  delegate answer against a person's on either side, the escalation against a person's answer on either side, two
  persons' and two delegates' answers still by time, the clarifier's suggestion still no human answer). Before the
  change `test_a_persons_answer_beats_the_delegates_accept_and_escalation_in_either_order_of_time[True]` failed
  (Q-001 read `''`: the delegate's accept won as the newer side) and
  `test_a_delegates_answer_loses_to_a_persons_also_when_the_person_is_on_the_unit_side[False]` failed (the delegate's
  answer replaced the unit side's person answer); the other ten cases of the file, old and new, passed before and pass
  after (12 in the file; 30 with `tests/unit/vcs/test_merge.py`). A base merge without a delegate line decides as before. No
  deviation (the module docstring says the rule).

## 2. Messages and the run (L4-RACE-002)

- [x] 2.1 Write the tests first (`tests/unit/forge/test_pushfail.py`): the four D4 messages (gone unchanged, moved with
  other paths, rewritten, keeps moving), exit codes, and that only gone and rewritten name `l4 restart`. Then implement
  them in `l4.forge.pushfail.explain_push_failure` (the classification travels on the exception).

  Result: `explain_push_failure` asks `_lease_hint` first: `BranchGone` gives today's text word for word (the same
  `_gone_hint`; an unclassified `stale info` still gets it), `BranchMoved` names the commit count and the first five
  paths ("a person pushed n commits to <b> during this run that change <paths>; the harness merges only answers to
  `questions.md`, so this run's work since its last push is not pushed. The next run starts from the forge's branch."),
  `BranchRewritten` says it was rewritten (or, with no lease value, that it exists where none was expected), never
  forces and leaves `l4 restart --unit ...` to a person, `BranchKeepsMoving` gives D2's text with the tries and says the
  answers stay on the forge. All exit 1, one redacted line, and only gone, rewritten and the unclassified case name
  `l4 restart`. Before the change eight of the ten new tests in `tests/unit/forge/test_pushfail.py` failed (the classified
  exceptions all read as the old "deleted or moved ... l4 restart" text); 38 pass now. Deviation: a fifth message
  for a merge the resolvers could not settle (`BranchMoved.conflicts`, from 1.1), worded like the moved one and naming
  the conflicting files; D4 has four.
- [x] 2.2 Write the tests first (an orchestrator test next to the existing close/push tests; find them with
  `grep -rln "_push_failed\|_publish_pending" tests/unit`): SCN-RACE-07 (a secret after the merge: no push), SCN-RACE-08
  (a failed final push publishes the ledger to the lock ref's pending ledger with `run.finished`; `status` then shows no
  open run). Then implement design D5 in `Orchestrator.close()` and wire `push.merged` into `Orchestrator.push`.
  Verify, and pin with a test, that a pending ledger whose events name commits not on the branch (a delegate accept of
  a question whose text on the branch differs) folds without error and that unfreeze/held do not act on it.

  Result: `Orchestrator.push` passes `answers=self._answer_merge()` to `Git.push_branch`: the unit folder, the trailers
  of a strict harness commit (unit, run, iteration, current phase; the ledger checkpoint's shape), the base merge's
  `harness_resolvers`, `_scan_outgoing` as the rescan, `_record_merged` (`push.merged{remote, commits, paths}`), the run's
  open ledger as `keep_dirty` and the unit's `excludes` file (`basemerge.excludes_file`, lifted from `_excludes`) for
  the dirty check. `close()` publishes the run's ledger file to the lock ref's pending ledger
  (`_publish_pending(failing=True)`) when the branch push already failed in the run and when the final push raises,
  before the error is re-raised. New `tests/unit/orchestrator/test_answer_push_merge.py` (through `l4 run`, a step's
  `on_start` makes the person's push while the run works): SCN-IMP-22 (merge commit, `push.merged`, answer on the
  branch, exit 0, `run.finished` on the branch), SCN-RACE-07 (the scan after the merge fires: exit 13, no merge on the
  forge), SCN-RACE-08 (a person's code push: exit 1, README.md named, no `l4 restart`, the run's file with
  `run.finished` in the pending ledger, `live_run` None). Against the old `orchestrator.py` all three failed (the
  push was refused as `BranchMoved` with the answer-only path; no merge; no pending file). The pin
  `test_pending_unpushed_events.py` (5, passing before and after, since the fold and the readers never look a commit
  up): the fold, `delegate_cost`, `live_run` and `merge_ledgers` (a pending file longer than the branch's copy of the
  same run) read events naming an unpushed commit; `unfrozen` gives nothing for a delegate accept of a text that is not
  the branch's, and `answer_actor` believes the delegate's record only while the file has that exact text (digest).
  The held reader (`accepted_overrides`) keys the same way, `(question, digest)` of the file as it is, and is pinned
  by `test_held_accept.py::test_m1_*`, which I did not change. Deviations: (1) nine test fakes of `Git.push_branch`
  (archive, orchestrator) took `(remote, branch, *, config=())` and now also `answers=None`; (2) the SCN-RACE-07 test
  patches `l4.orchestrator.outgoing_secrets` so that the scan fires on a merge head, because the real scan skips merge
  commits (`--no-merges`) and the run's own commits were already read by the scan before the push, so a real secret
  cannot first appear after the merge.

## 3. The info line (L4-QMD-011)

- [x] 3.1 Write the tests first (`tests/unit/specs/test_questions_cli.py`): SCN-QMD-31 (open run with a running CI run →
  line; no open run → none; older than its job timeout → none; forge cannot be asked → the age decides; the forge says
  completed → none). Then lift `yolo.commands._ended_why` (and `END_GRACE_S`, `DEFAULT_JOB_TIMEOUT_S`) into a module both
  import (for example `l4.state.liveness`), keep `l4 yolo status` behaviour (its tests pass unchanged), and print the
  line from `l4 questions answer|accept|dismiss` after the command's own line. SCN-QMD-20 (the lock ref rule) is
  unchanged.

  Result: new `l4.state.liveness` holds `END_GRACE_S`, `DEFAULT_JOB_TIMEOUT_S`, `APPROVAL_WAIT`, `LazyForge` (the forge
  built when first needed) and `ended_why(cfg, run, forge, at)`, the rules of `yolo.commands._ended_why` word for word.
  `yolo.commands` keeps `_ended_why(ctx, run, forge)` as a one-line call with its own `_now()`, and `_Forge(ctx)` as a
  `LazyForge` that looks `make_forge` up in that module, so the tests that patch `cmd._now` and `cmd.make_forge` still
  reach it; `tests/unit/yolo/test_yolo_status_open_run.py`, `test_yolo_status_activity.py`, `test_yolo_commands_manage.py`
  and `tests/unit/agents/test_activity_contract.py` pass unchanged (98). `questions_cli.write_edit` adds, right after
  its own `pushed ...` line, `[l4] questions: run <id> works on <unit> (started <n> min ago): it takes this answer at
  its next push, or the next run does` when `_working_run_line` finds an open `l4 run` in `folder_events` (the branch
  ledger with the lock ref's pending ledger) that `ended_why` does not call ended; a failure to read gives no line, a
  dry run (`--no-push`) none. Nine new tests in `tests/unit/specs/test_questions_cli.py` (SCN-QMD-31; accept; no open
  run or a finished one; older than the job timeout, forge not asked; forge unavailable, age decides; forge says
  completed; forge raises; dry run; SCN-QMD-20 refusal unchanged): before the change they failed because
  `questions_cli` had no clock or forge seam and printed nothing; 102 pass in the file now. Deviations: (1) there is no
  `l4 questions dismiss` command in this tree (only `answer` and `accept`), so the line is in the one write path both
  share and any later form gets it; (2) `parse_time` for the liveness rule is imported from `l4.yolo.state` (no copy);
  (3) a run without a CI link is never called ended by the rule (as in `l4 yolo status`), so its line stays until its
  `run.finished`.

## 4. Openspec bookkeeping and checks

- [x] 4.1 Mark the old open tasks this change builds or replaces with a one-line note pointing here:
  `openspec/changes/state-vcs-locks/tasks.md` 3.1-3.3, `openspec/changes/implementer-tdd-loop/tasks.md` 2.40,
  `openspec/changes/forge-and-ci/tasks.md` 2.57/2.58 (read each first; tick only what this change does, note the rest
  as superseded by L4-RACE-001's amended text).

  Result: a note was added to the end of each line, and one box ticked. state-vcs-locks 3.2 (three attempts, then exit
  1 with only the person's commits on the branch) is built by 1.1 and ticked. 3.1 (rebase, gate re-run,
  `recover_from_human_push`) and 3.3 (`replan_required`) are not what was built: the notes say superseded by
  L4-RACE-001's amended text and leave them open. implementer-tdd-loop 2.40 and forge-and-ci 2.58 (both on
  `replan_required`) are noted as superseded and left open. forge-and-ci 2.57 (archive and hand-off pushes through the
  coordinator) is noted as not built: this change covers the run's push of the unit branch only. No deviation.
- [x] 4.2 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you changed or added plus the test files that import a module you changed (`grep -rl` for the module name under tests/unit), in one pytest invocation; not whole directories (a combined run follows after the merge). Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass does that).

  Result: ruff check and ruff format --check are clean on the 26 Python files this change touched. pytest: the 26 changed
  or added test files plus every test file under `tests/unit` that names `l4.vcs.push`, `l4.vcs.merge`, `l4.vcs.race`,
  `l4.forge.pushfail`, `l4.specs.questions_merge`, `l4.specs.questions_cli`, `l4.state.liveness`, `l4.yolo.commands`,
  `l4.verifier.basemerge`, `l4.orchestrator`, `push_branch` or `harness_merge` (96 files in all; `l4.vcs.git` alone was
  left out as a pattern because nearly every test names it, `push_branch` covers its changed method). 1583 passed, 0
  failed, 0 skipped. Deviation: not one invocation but five sequential foreground or auto-backgrounded ones (176 + 329 +
  445 + 633 = 1583 over 8 + 24 + 24 + 40 files), because a single run of 96 files takes over an hour and the tool's
  foreground limit is ten minutes; never two at once, none in a loop.
