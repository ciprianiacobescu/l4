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
- [ ] 1.2 Write the tests first, then the loop of design D3 in `Git._push`, with `_landed` and the sleep and clock
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

## 2. Explain (L4-LCK-001)

- [ ] 2.1 Write the tests first, in the tests of `forge/pushfail.py`. Then, in `explain_push_failure`, read a
  transient failure before the hook check and return `PushFailed(transient=True)` with the D4 text. In
  `orchestrator._failed_unit`, write `push failed on the forge's side: …` for it. Cases:
  - GitHub's real stderr → transient, not `refused`, exit 1, and the hint as D4 says;
  - a push rule → `refused` as today;
  - a permission failure → exit 3 as today;
  - `sweeper.definitive_reason` of a transient `PushFailed` is None.

## 3. Checks

- [ ] 3.1 Run `tests/unit/vcs`, `tests/unit/forge`, `tests/unit/ci` and the orchestrator's unit tests once, with
  pytest, never in a loop, and wait for them to finish. Run ruff check and ruff format on the changed files.

## 4. Docs (one pass at the end of the release)

- [ ] 4.1 In L4-LCK-001, amend the sentence "Neither moved → rejected by the forge itself (…): retry once …" to say
  what the requirement above says (design D5: no `push.rejected` event). Amend SCN-LCK-10, and add SCN-LCK-11 to
  SCN-LCK-13 after it. Add change-table row 86 `push-transient-retry`, and a CHANGELOG 0.4.39 entry under Fixed.
