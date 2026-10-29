## 1. Classify and retry (L4-LCK-001)

- [x] 1.1 Write the tests first, in `tests/unit/vcs/` (grep `is_lost_lease` for the module that tests `vcs/push.py`).
  Then add `is_transient_push_failure` to `l4.vcs.push`, and move `_DENIED` and `is_permission_failure` there (design
  D2). `l4.forge.pushfail` imports both back, so `from l4.forge.pushfail import is_permission_failure` still works.
  Cases:
  - each marker of D2;
  - GitHub's real stderr: `remote: fatal error in commit_refs_rules` + `To https://github.com/o/r` +
    ` ! [remote rejected] HEAD -> l4/openspec/x (failure)`;
  - a 503 together with `permission denied` is not transient;
  - a push rule's text (`remote: GitLab: Push rule: commit message does not follow the pattern` +
    `pre-receive hook declined`) is not transient;
  - a non-fast-forward is not transient.
  Result: `is_transient_push_failure` and `is_permission_failure` (with `_DENIED`) are in `l4.vcs.push`, and
  `l4.forge.pushfail` imports `is_permission_failure` back (nothing imported `_DENIED` from it). The new tests in
  `tests/unit/vcs/test_push.py` failed at collection (`ImportError: cannot import name 'is_permission_failure'`) before
  the change and pass now.
  Result (1.3, review): an HTTP 4xx answer (`returned error: 4dd`, `rpc failed; http 4dd`) wins over the transient
  markers like a permission marker does, so a 413 or 400, which git follows with "the remote end hung up unexpectedly",
  is not retried; `explain_push_failure` gives it no transient hint. The new tests failed before the change.
  Result (1.3, review): the marker is `fatal error in commit_refs` (GitHub's older message has no `_rules`) and
  `internal api unreachable` is added (GitLab's "Failed to authorize your Git request" before "pre-receive hook
  declined"); the new tests failed before the change.
- [x] 1.2 Write the tests first, then the loop of design D3 in `Git._push`, with `_landed` and the sleep and clock
  seam. Use a real bare remote in a tmp dir (as the existing push tests do) with a `pre-receive` hook. The hook prints
  `fatal error in commit_refs_rules` to stderr and exits 1 on the first N calls, counted in a file, and then accepts.
  - SCN-LCK-11: one failure, then success. The branch holds HEAD, `sleep` was called once with 5.0, and one warning
    was logged.
  - Three failures: the error is raised after 3 tries, and the waits were 5.0 and then 15.0.
  - The budget: a fake clock past 60 s after the first try means no new try.
  - SCN-LCK-10: a hook that prints a push rule's text runs once, with no sleep.
  - SCN-LCK-12: wrap `Git.run` so that the first `push` really runs and then raises a transient `GitError`. `_landed`
    finds the ref at HEAD, there is no second push, and `push_branch`'s lease is not refused. Cover `push_branch`
    (lease), `push` (plain refspec) and `push_delete` (absent after delete).
  - An `ls-remote` that fails counts as not landed.
  - `cancel.check()` runs before a retry.
  - A `PushRejected` (non-fast-forward) on the first try is raised at once.
  Result: `Git._push` runs the loop of D3 (`PUSH_TRIES`, `PUSH_WAITS`, `PUSH_BUDGET`), `Git._landed` reads the refspecs
  after `--` and compares one `ls-remote` with `rev_parse(src)` (an empty `src` = absent), and `Git` takes `sleep` and
  `monotonic` as keyword arguments (`at()` passes them on). The retry is logged with `log.warning` on `l4.git`. The 19
  tests of `tests/unit/vcs/test_push_retry.py` (real bare remote with a counting `pre-receive` hook; `Git.run` wrapped
  for SCN-LCK-12) failed before the change on the missing `sleep`/`monotonic` keywords; with `_landed` forced to False
  8 of them fail. Noted while testing: git itself treats a lease on a ref that already holds the pushed value as
  "Everything up-to-date", so a plain `git` client rarely hits the lease refusal after a landed push; the
  moved-after-transient route is tested with a scripted refusal.

## 2. Explain (L4-LCK-001)
  Result (1.3, review): `GitError.tries` (1 by default) is set by `_push` on the error it raises, `PushRejected`
  included; the tests of `test_push_retry.py` and `test_git.py` for it failed before the change.
  Result (1.3, review): the plan ledger's push no longer calls `git.run("push", ...)` itself: `Git.push_plan` (args
  from `build_plan_push_args`: `refs/l4/plans/` only, atomic, leased, never `+`) goes through `Git._push` with
  `is_lost_lease`, and `PlanStore._push` maps `PushRejected` to `PlanMoved` and any other `GitError` to
  `explain_push_failure`. `yolo/go.py`'s push is left alone (it runs the person's hooks). The store tests (a server
  error then success lands the plan ref, one that remains is `transient` and not `PlanMoved`, a lost lease is
  `PlanMoved` with no wait) and the argument tests failed or could not be collected before the change.
  Result (1.3, review): when the last try, or the budget, ends a loop of transient failures, `_landed` is asked once
  before the error is raised; the budget is read again after the wait and the check, before a new try. The new tests
  (a push that lands on the 3rd try, one that landed when the budget forbade another, a check that ended past the
  budget) failed before the change; the clocks of two older tests now give the extra reading.
- [x] 2.1 Write the tests first, in the tests of `forge/pushfail.py`. Then, in `explain_push_failure`, read a
  transient failure before the hook check and return `PushFailed(transient=True)` with the D4 text. In
  `orchestrator._failed_unit`, write `push failed on the forge's side: …` for it. Cases:
  - GitHub's real stderr → transient, not `refused`, exit 1, and the hint as D4 says;
  - a push rule → `refused` as today;
  - a permission failure → exit 3 as today;
  - `sweeper.definitive_reason` of a transient `PushFailed` is None.
  Result: `explain_push_failure` reads a transient failure after the `PushRejected` checks and before the hook check, and
  returns `PushFailed(ExitCode.INTERNAL_ERROR, ..., transient=True)` with the D4 text; `PushFailed` has a `transient`
  flag (False by default); `_failed_unit` writes `push failed on the forge's side: ...` for it. The 6 new tests of
  `tests/unit/forge/test_pushfail.py` and the one of `tests/unit/orchestrator/test_exit_reasons.py` failed before the
  change (no `transient` attribute, the unit's line said nothing about the forge) and pass now.
  Result (2.2, review): the hint says "the harness tried N times" only when `exc.tries > 1`, and ends with "a later
  push should work" (it serves `l4 yolo go` and the questions CLI too); the new tests failed before the change.

## 3. Checks

- [x] 3.1 Run `tests/unit/vcs`, `tests/unit/forge`, `tests/unit/ci` and the orchestrator's unit tests once, with
  pytest, never in a loop, and wait for them to finish. Run ruff check and ruff format on the changed files.
  Result: `tests/unit/vcs tests/unit/forge tests/unit/ci tests/unit/orchestrator`: 1650 passed in 2098 s (one run, `-x`,
  machine loaded). `ruff check` and `ruff format --check` pass on the 8 changed Python files. Existing tests that fake a
  failure through `Git` with a message that is now transient were looked for (`Could not resolve host` in
  `tests/unit/state/test_status_branch.py` is a fetch, which is not retried); none goes through `Git._push`.

## 4. Docs (one pass at the end of the release)

- [ ] 4.1 In L4-LCK-001, amend the sentence "Neither moved → rejected by the forge itself (…): retry once …" to say
  what the requirement above says (design D5: no `push.rejected` event). Amend SCN-LCK-10, and add SCN-LCK-11 to
  SCN-LCK-13 after it. Add change-table row 86 `push-transient-retry`, and a CHANGELOG 0.4.39 entry under Fixed.
