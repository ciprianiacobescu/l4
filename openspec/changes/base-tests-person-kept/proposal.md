# A file a person changed last stays at head for the base-test run

## Why

0.4.33 (`base-tests-person-commit`) let a person's last commit to a test file excuse that file's failing base tests,
the way out L4-IMP-081 names for a test file a fix chore may not change. In a consumer repository's delivery plan the
route worked for the file's own tests and still left the unit stopped [V, verification rounds 1-2 and the fix units'
questions]:

- a Go unit's reviewed spec changes which answers of a remote service count as a refusal; the unit's red step changed
  an existing test in `pkg/q/compact_test.go` to the new answer, and a person's commit then became the last change to
  the file;
- step 1 (L4-VER-038) excused that test (a person's line), but it still ran the gate with the file at its base
  version, because `kept_files` keeps a changed file at head only when people's commits alone changed it (0.4.33's
  design D3 left `kept_files` on `_by_people`);
- an acceptance test the unit did not change, `tests/acceptance/test_q.py::test_q_unit_tests_pass`, runs the
  package's Go tests. It ran the base version of the person's file, failed,
  and has no allowance: the unit did not change its file, so nobody's commit can excuse it. The fix unit escalated,
  and the only ways out offered were a person's commit to an unrelated test file or relaxing the spec.

0.4.33's own reason for reading the last commit, that the last commit set the content the run judges, holds for which
version of the file the run uses as much as for whether its failure is excused. Two rules for one file make the
person's commit excuse a failure and still run the content the person replaced.

## What Changes

- `kept_files` (which of the unit's changed test and support files stay at head for step 1's run of the base tests):
  a file whose last change in `base..head` is not the harness's (the author rule, `is_harness`) stays at head, listed
  as a person's line that names every commit of `base..head` that changed it, the harness's included: `<path> kept at
  head for the run (people changed it last (<sha>, <sha>))`. A harness commit after the person's puts it back, as
  before. The existing reasons keep their order and text (only people's commits; a `[test-infra]` task; a
  `task.unfrozen`); the new one is checked after them.
- `docs/SPEC.md`: L4-VER-038's last sentence names the file a person changed last; a new scenario SCN-VER-241; change
  table row 80. CHANGELOG 0.4.36 under Fixed.

## Impact

- Code: `l4.verifier.base_tests.kept_files`. `_by_people` keeps its meaning for the AST checks of `integrity`.
- Security: a kept file is listed in the verdict and the report (`human_tests`), never silent, with every commit that
  changed it. A support file the harness poisoned (a conftest that skips the base tests) and a person then committed is
  kept at head, but the base tests it skips are `not run`, and a test that does not run is a blocker unless its own
  file has an allowance: the tests the unit did not change have none. A test file the harness weakened and a person
  then committed was already excused by 0.4.33 (a person's line); running its head version changes the line's kind,
  not what is accepted. Step 1's AST checks of pre-existing tests (L4-VER-030, L4-VER-031) are unchanged.
- Consumers: a unit stopped this way continues after `l4 retry --unit` or its fix unit's next run; nobody commits again.
- Out of scope: the test-path freeze (L4-IMP-006 (7)) and L4-IMP-081's note are unchanged.
