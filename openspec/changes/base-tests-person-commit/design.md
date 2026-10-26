# Design: a person's last commit to a test file

## D1. Last, not only

`_introducers(ctx, file, changed)` gives the commits of `base..head` that changed the file, oldest first. The new
helper `_last_by_people(commits)` is true when the list is not empty and its last commit is not the harness's
(`is_harness`). `split_allowed` uses it in place of `_by_people` for its person's branch. The order of the other
allowances is unchanged (`tests.superseded`, then `task.unfrozen`, then `[test-infra]`, then the person's commit).

Why the last commit: the content the base-test run judges was set by that commit. A person who commits the test file
after the harness has decided what it says, which is what L4-IMP-081 asks of them. A harness commit after the person's
means the harness's version is what runs, so it is judged as the harness's.

## D2. Nothing hidden

The person's line keeps its form, `<test id> fails with the base version of its files (changed by <sha>, …)`, and
lists every introducer, the harness's commits included. It lands in `human_tests` of the verdict and in the report's
list, as today.

## D3. What stays

- `_by_people` keeps its meaning for its other callers: the AST checks of `integrity` and `kept_files`. A support file
  stays at head for the run only when people alone changed it.
- The test-path freeze (L4-IMP-006 (7)) and L4-IMP-081's note are unchanged: a fix chore still may not change a test
  file, and an answer still cannot unfreeze one in a fix task.

## D4. Retry

A person's commit outside the unit folder is no spec edit (`spec_edit_since_harness`), so `l4 retry --unit` on an
escalated unit goes back to `verifying`, and `repeated_failure` does not call the next round a repeat because a
person's commit lies between the previous round's head and the new one.
