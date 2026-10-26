# A person's last commit to a test file excuses its base-test failures

## Why

A consumer repository's delivery plan stopped with `unit_escalated`: `round 3 failed the same way as round 2: finding
F-2813828d`. The unit is a Go change whose reviewed spec lists two existing tests under "Changed tests" and tells task
1.1 to change them in place. Step 1 of the verifier (L4-VER-038) runs the base's version of every test file the unit
changed against the unit's code, and both tests fail there, as the spec intends. The red step changed them, and nothing
records that it was allowed to [V, ledger `verify.base_tests` rounds 1-3, `allowed: []`]:

- the named-tests rule of L4-IMP-082 reads Python files only, so the Go test names in the task text open nothing;
- each fix chore's edit to the two files is put back by the test-path freeze, as L4-IMP-006 (7) and L4-IMP-081 say,
  and the fix commits change only the task tick [V, commits of fix-1 and fix-2].

L4-IMP-081 names the way out: the note for the next attempt "SHALL say that a person must commit that change on the
unit branch and that an answer cannot unfreeze a file in a fix task". That route does not work here [V, code].
`split_allowed` lists a failing base test as a person's line only when `_by_people` holds for every commit of
`base..head` that changed its file. The harness's red commit changed the file first, so the file is never "only
people's", whatever a person commits after it. L4-IMP-081's instruction and L4-VER-038's rule cannot both hold once a
harness step has touched the file.

For a Go test it fails one step earlier [V, code and ledger]. `split_allowed` reads a test's file with `_file_of`, which
knows pytest ids only (`tests.test_x.TestY::test_z` → `tests/test_x.py`). The failing ids are Go ids
(`<module path>/internal/server::Test<Name>_MissingToken`, from gotestsum's JUnit report), so `_file_of` returns no file and every allowance that reads a file (`task.unfrozen`,
`[test-infra]`, a person's commit) is out of reach: the id is a blocker whoever changed the file.

## What Changes

- Step 1's split of the failing base tests (`split_allowed`): a test whose file was last changed, in `base..head`, by a
  person's commit is a person's line, not a blocker. The line names every commit that changed the file, the harness's
  included, so a judge and the report see who wrote what. A harness commit after the person's makes it a blocker again.
- Step 1 finds the file of a Go test: for an id `<import path>::<name>`, the one `*_test.go` file of the package's
  directory that declares `func <name>(` (a subtest `TestX/case` is its parent's function), the directory found from
  the `module` line of the `go.mod` whose module path is the longest prefix of the import path (a module's path need
  not match where its `go.mod` lies). No file, or more than one, keeps the blocker. It reads git objects only.
- `kept_files` (which support files stay at head for the run) is not changed: a person's last commit excuses a failure
  of the base version; it does not keep the head version in the run.
- `docs/SPEC.md`: L4-VER-038 lists the four ways a failing base test is not a blocker (`tests.superseded`, a
  `task.unfrozen` of the unit, a `[test-infra]` task's commit, a person's last commit), with the person's line naming
  every commit; L4-IMP-081 says that the person's commit is what step 1 reads. A new scenario SCN-VER-239; change-table
  row 76. CHANGELOG 0.4.33 under Fixed.

## Impact

- Code: `l4.verifier.base_tests.split_allowed`, `l4.verifier.base_tests._file_of` (a Go rule after the pytest one)
  and a new helper next to `_by_people` in `l4.verifier.integrity`.
  `_by_people` keeps its meaning for its other callers (the AST checks of `integrity`, `kept_files`).
- Security: the person's line is listed in the verdict and the report (`human_tests`), never silent. Only a commit
  that is not the harness's under the author rule (`is_harness`: the bot identity and an `L4-Run` trailer) counts, and
  only when it is the last to change the file, so the harness cannot add a change after a person's and have it
  excused.
- Consumers: a unit stopped this way continues after a person commits the test files on its branch, `l4 retry --unit`
  and `l4 yolo resume`.
- Out of scope (backlog): the file of a Vitest, Jest or Playwright test id (its class is a path relative to the
  runner's directory) and a report's own source path (`TestCase.source_file`, language packs); the named-tests rule
  (L4-IMP-082) and the red-step pre-existing-test check (L4-IMP-048) for Go and TypeScript test files; a fix chore
  whose every edit was put back still commits its tick.
