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

## D4. The file of a Go test

`_file_of(ctx, test_id)` gives the file the allowances read. It knew pytest ids only, so for a Go id every allowance
that reads a file was out of reach. gotestsum's JUnit report names a Go test `<import path>::<TestName>` and a
subtest `<import path>::<TestName>/<case>`. The import path does not name the directory: a module's path is the
`module` line of its `go.mod`, which need not match where the `go.mod` lies (`module example.com/services/x` in
`apps/x/go.mod`). When the pytest rule finds no file, `_file_of` tries, at head and then at the base:

1. the `go.mod` files of the tree (`git ls-tree -r --name-only <rev>`), each read for its `module` line; the module
   whose path is the longest prefix of the id's class (equal to it, or followed by `/`) gives the package directory,
   the `go.mod`'s directory joined with the rest of the class;
2. the `*_test.go` files directly in that directory (not in a directory below it), read for a line that declares
   `func <Name>(`, where Name is the id's name up to the first `/`;
3. exactly one file declares it: that file. None, or more than one: the next revision, and then no file, so the id
   stays a blocker unless `tests.superseded` names it.

It reads git objects only: no `go` toolchain, nothing runs. An id without `::`, or whose class no module path starts,
gets no file, as before. A report's own source path (`TestCase.source_file`, language packs) can replace the rule later.

## D5. Retry

A person's commit outside the unit folder is no spec edit (`spec_edit_since_harness`), so `l4 retry --unit` on an
escalated unit goes back to `verifying`, and `repeated_failure` does not call the next round a repeat because a
person's commit lies between the previous round's head and the new one.
