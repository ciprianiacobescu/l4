## ADDED Requirements

### Requirement: L4-VER-076 Step 3 runs a gate again when only pre-existing tests failed
When a run of step 3's test gate or e2e gate fails, its report was read and holds no collection error and every id it
must hold, it is not `the test report was altered`, one to five tests failed or errored, and every one of them is
pre-existing, the verifier SHALL run the same gate again, its whole command, as `<gate>-repeat-<n>`: the test gate with
the same `must_contain` and without the coverage environment (step 6 reads the first run's coverage), the e2e gate with
a new serve (the launcher's server does not outlive its gate). A test SHALL be pre-existing when it is not a red test of
the unit, `file_of_id` finds its file among the files of the head tree (preferring a path `base..head` changed when
several match), and `git diff <base> <head>` does not name that file; a test whose file is not found is not. The repeats
SHALL stop when every test that failed has passed in one run, after a repeat that is not usable (no report read, a
collection error, a missing `must_contain` id, no test executed, or a failed exit code with every test passing) or that
fails a test that is not pre-existing, and at the latest when the gate has run `verifier.flaky_repeats` times in all
(default 3; 1 makes no repeat). Over the usable runs, a test that failed in one and passed in another SHALL be the minor
finding `a pre-existing test is flaky in the <gate> gate`, naming it with the runs it failed and passed in, and SHALL
NOT fail the step; a pre-existing test that never passed, and a test that is not pre-existing and failed in any run,
SHALL keep the blocker `<gate> gate failed`, whose detail then reads
`` `<command>` failed (<runs> runs); failing: <ids> `` with only those tests. A test the unit added, and a test in a file that `base..head` changed (by any commit, a
person's included), SHALL NOT be run again; new tests SHALL NOT be repeated. The report that step 3 hands on (to step 4,
the judge, `tests` and `e2e_tests`) SHALL be the first run's with each flaky test's case from the first run in which it
passed, and `failures` (L4-VER-069) SHALL hold only the tests that still fail. Each repeated gate SHALL be recorded as
`verify.gate_repeat{round, gate, runs, flaky, failing, stopped}` (`stopped`: `passed`, `limit`, `not_pre_existing` or
`unusable`), each run as its own `gate.finished` and row of the Gates table (the first run's row `flaky` when nothing
still fails), and the step's note SHALL name the repeats (`<gate>: <runs> runs (L4-VER-076); flaky: <ids>; still
failing: <ids>`). A repeat whose report is altered SHALL add that blocker; a server that never gets ready in a repeat
SHALL raise as in the first run (L4-VER-010). The same-failure set (`failure_set`) SHALL skip the rows of repeats.

#### Scenario: SCN-VER-288 (+) a pre-existing e2e test that fails once and passes on the repeat is a minor finding
- **WHEN** `flaky_repeats` is 3, the unit changed no file of `e2e/`, and the e2e gate's first run fails only
  `e2e.test_signin::test_form` and its next run passes
- **THEN** the gate runs twice (`e2e`, `e2e-repeat-1`), step 3 is `ok`, the round has the minor finding `a pre-existing
  test is flaky in the e2e gate` naming the test, `verify.gate_repeat{gate: e2e, runs: 2, flaky:
  [e2e.test_signin::test_form], failing: [], stopped: passed}` is recorded, the Gates table has `e2e` `flaky` and
  `e2e-repeat-1` `pass`, `tests` holds the test as `passed`, `failures` does not hold it, and no fix unit is spawned

#### Scenario: SCN-VER-289 (−) a pre-existing test that fails in every run stays a blocker after flaky_repeats runs
- **WHEN** `flaky_repeats` is 3 and a pre-existing e2e test fails in every run
- **THEN** the gate runs three times and no more (`e2e`, `e2e-repeat-1`, `e2e-repeat-2`), the blocker `e2e gate failed`
  says `(3 runs)` and names the test, `verify.gate_repeat` has `stopped: limit` and the test in `failing`, and the
  round is FAIL

#### Scenario: SCN-VER-290 (−) a failing test the unit added is not run again
- **WHEN** the e2e gate's first run fails a pre-existing test and a red test of the unit
- **THEN** the gate runs once, no `verify.gate_repeat` is recorded, and the blocker `e2e gate failed` is as before

#### Scenario: SCN-VER-291 (−) a failing test in a file the unit changed is not run again
- **WHEN** the test gate's first run fails only `tests.test_cart::test_total`, whose file `tests/test_cart.py` is at the
  base and was changed in `base..head` by a harness commit, or by a person's
- **THEN** the gate runs once and the blocker `test gate failed` names the test

#### Scenario: SCN-VER-292 (−) flaky_repeats 1 makes no repeat
- **WHEN** `flaky_repeats` is 1 and the e2e gate's first run is that of SCN-VER-288
- **THEN** the gate runs once, the blocker `e2e gate failed` names the test, and no `verify.gate_repeat` is recorded

#### Scenario: SCN-VER-293 (+) a pre-existing test that fails only in a repeat is flaky, the unit's own test is not
- **WHEN** the first run fails pre-existing A and the repeat passes A and fails pre-existing B, which passed in the first
  run; or the repeat passes A and fails a red test N of the unit, which passed in the first run
- **THEN** in the first case A and B are flaky, `stopped` is `passed` and step 3 is `ok` after two runs; in the second
  the repeats stop with `stopped: not_pre_existing`, A is flaky, and the blocker names N only

#### Scenario: SCN-VER-294 (−) a repeat with no usable report ends the repeats
- **WHEN** the first run fails a pre-existing test and the repeat gives no report, or has a collection error, misses a
  `must_contain` id, or fails its exit code with every test passing; or the repeat's report is altered
- **THEN** no further repeat is made, `stopped` is `unusable`, the blocker names the first run's test, and an altered
  report adds the blocker `the test report was altered`

#### Scenario: SCN-VER-295 (+) the test gate's repeat runs without coverage, before the e2e gate
- **WHEN** diff coverage is on and the test gate's first run fails only a pre-existing test that passes on the repeat
- **THEN** `test-repeat-1` runs with the same `must_contain` and without the coverage environment, the e2e gate runs
  after it, and step 6 reads the first run's coverage

#### Scenario: SCN-VER-296 (−) a gate that failed another way, or on more than five tests, is not repeated
- **WHEN** the first run has a collection error, executed no test, is `the test report was altered`, fails six
  pre-existing tests, fails a test whose file `file_of_id` does not find, or misses a `must_contain` id
- **THEN** the gate runs once and is judged as before

#### Scenario: SCN-VER-297 (−) a server that never gets ready in a repeat is an internal error
- **WHEN** the e2e gate's first run fails a pre-existing test and the repeat's server never gets ready
- **THEN** `ServerNotReady` is raised (exit 1) as in a first run, and no finding is written for the repeat
