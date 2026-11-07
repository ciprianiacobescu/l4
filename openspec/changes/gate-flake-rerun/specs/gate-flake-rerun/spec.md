## ADDED Requirements

### Requirement: L4-VER-076 Step 3 runs a gate again when only pre-existing tests failed
When a run of step 3's test gate or e2e gate fails, its report was read and holds no collection error and every id it
must hold, it is not `the test report was altered`, one to five tests failed or errored, and every one of them is
pre-existing, the verifier SHALL run the same gate again, its whole command, as `<gate>-repeat-<n>`, on the tree run 1
started from: before run 1 it SHALL record the untracked paths of the worktree (the ignored ones included, a wholly
untracked directory as one entry) and before each repeat remove every entry that is new since, so that state run 1 left
behind cannot make a failure on a cold tree pass (a file that run 1 added inside a directory that was already untracked
as a whole, the harness's own directories and the gate's reports are not removed; the tool caches are reset at every
gate anyway); when the tree cannot be listed or cleaned there SHALL be no repeat. The test gate SHALL run with the same
`must_contain` and without the coverage environment (step 6 reads the first run's coverage), the e2e gate with a new
serve (the launcher's server does not outlive its gate). A test SHALL be pre-existing when it is not a red test of the
unit, `file_of_id` finds its file among the files of the head tree (preferring a path `base..head` changed when several
match; an id whose file part has a JavaScript or TypeScript extension is looked up among the files of that extension
only, a Playwright path relative to its test directory read as dotted, and no changed file of that extension may match
it), and `git diff <base> <head>` does not name that file; a test whose file is not found is not. The repeats SHALL stop
when every test that failed has passed in one run; after a repeat that is not usable (no report read, a collection
error, a missing `must_contain` id, no test executed, a failed exit code with every test passing, or an `L4Exit` such as
a server that never gets ready) or that fails a test that is not pre-existing; after a repeat whose failing test ids and
failure messages are exactly run 1's (a deterministic failure costs one more run); before a repeat when the armed soft
deadline leaves less than run 1's duration plus a margin (the larger of 60 seconds and a tenth of it); and at the latest
when the gate has run `verifier.flaky_repeats` times in all (default 3, at most 5; 1 makes no repeat). Over the usable
runs, a test that failed in one and passed in another SHALL be the minor finding `a pre-existing test is flaky in the
<gate> gate`, naming it with the runs it failed and passed in, and SHALL NOT fail the step; a pre-existing test that
never passed, and a test that is not pre-existing and failed in any run, SHALL keep the blocker `<gate> gate failed`,
whose detail then reads `` `<command>` failed (<runs> runs); failing: <ids> `` with only those tests. A failure of a
test the unit added, or of a test in a file that `base..head` changed (by any commit, a person's included), SHALL NOT
cause a repeat; new tests SHALL NOT be repeated. The report that step 3 hands on (to step 4, the judge, `tests` and
`e2e_tests`) SHALL be the first run's with each flaky test's case from the first run in which it passed (and a test that
still fails but passed in the first run, because a repeat failed it, with its first failing case), and `failures`
(L4-VER-069) SHALL hold only the tests that still fail. Each repeated gate SHALL be recorded as
`verify.gate_repeat{round, gate, runs, flaky, failing, stopped}` (`stopped`: `passed`, `limit`, `not_pre_existing`,
`unusable`, `same_failures` or `budget`; also with `runs: 1` when no repeat could start), each run as its own
`gate.finished` and row of the Gates table (the first run's row `flaky` when nothing still fails), and the step's note
SHALL name the repeats (`<gate>: <runs> runs (L4-VER-076); flaky: <ids>; still failing: <ids>`); the judge's gate
summary SHALL carry that note and say that rows named `<gate>-repeat-<n>` are repeats of the same gate. A repeat whose
report is altered SHALL add that blocker; a server that never gets ready in a repeat SHALL be an unusable repeat that
keeps run 1's blocker, and only run 1 raises (L4-VER-010). The same-failure set (`failure_set`) SHALL skip the rows of
repeats.

#### Scenario: SCN-VER-288 (+) a pre-existing e2e test that fails once and passes on the repeat is a minor finding
- **WHEN** `flaky_repeats` is 3, the unit changed no file of `e2e/`, and the e2e gate's first run fails only
  `e2e.test_signin::test_form` and its next run passes
- **THEN** the gate runs twice (`e2e`, `e2e-repeat-1`), step 3 is `ok`, the round has the minor finding `a pre-existing
  test is flaky in the e2e gate` naming the test, `verify.gate_repeat{gate: e2e, runs: 2, flaky:
  [e2e.test_signin::test_form], failing: [], stopped: passed}` is recorded, the Gates table has `e2e` `flaky` and
  `e2e-repeat-1` `pass`, `tests` holds the test as `passed`, `failures` does not hold it, and no fix unit is spawned

#### Scenario: SCN-VER-289 (−) a pre-existing test that fails in every run stays a blocker
- **WHEN** `verifier.flaky_repeats: 3` and a pre-existing e2e test that fails in every run, with the same failure
  message each time, or with another one each time
- **THEN** with the same message the gate runs twice (`e2e`, `e2e-repeat-1`: a deterministic failure costs one more run)
  and `verify.gate_repeat` has `stopped: same_failures`; with another message each time it runs three times and no more
  (`e2e`, `e2e-repeat-1`, `e2e-repeat-2`) and has `stopped: limit`; in both the blocker `e2e gate failed` says the
  number of runs and names the test, the test is in `failing`, and the round is FAIL

#### Scenario: SCN-VER-290 (−) a failing test the unit added is not run again
- **WHEN** the e2e gate's first run fails a pre-existing test and a red test of the unit
- **THEN** the gate runs once, no `verify.gate_repeat` is recorded, and the blocker `e2e gate failed` is as before

#### Scenario: SCN-VER-291 (−) a failure in a file the unit changed, or of a test of another language, causes no repeat
- **WHEN** a test gate whose first run fails only `tests.test_cart::test_total`, whose file `tests/test_cart.py` is at
  the base and was changed in `base..head` by a harness commit, or by a person's; or an e2e gate that fails
  `app.spec.ts::home loads` when `e2e/app.spec.ts` was changed (the root `app.py` is not its file), while an unchanged
  `e2e/app.spec.ts` with only `app.py` changed is pre-existing, and a nested `auth/signin.spec.ts::…` id names
  `e2e/auth/signin.spec.ts`
- **THEN** the gate runs once and the blocker `test gate failed` names the test; the TypeScript ids are told from the
  Python file by their extension

#### Scenario: SCN-VER-292 (−) `flaky_repeats: 1`, or too little time left, makes no repeat
- **WHEN** `verifier.flaky_repeats: 1` and the first e2e run of SCN-VER-288; or an armed soft deadline that leaves less
  than the first run's duration plus the larger of 60 seconds and a tenth of it
- **THEN** the gate runs once and the blocker `e2e gate failed` names the test; no `verify.gate_repeat` is recorded for
  `1`, and for the deadline it is recorded with `runs: 1` and `stopped: budget` (before a later repeat as well: the
  repeats made stand and `stopped` is `budget`)

#### Scenario: SCN-VER-293 (+) a pre-existing test that fails only in a repeat is flaky, the unit's own test is not
- **WHEN** the first run fails pre-existing A and the repeat passes A and fails pre-existing B, which passed in the first
  run; or the repeat passes A and fails a red test N of the unit, which passed in the first run
- **THEN** in the first case A and B are flaky, `stopped` is `passed` and step 3 is `ok` after two runs; in the second
  the repeats stop with `stopped: not_pre_existing`, A is flaky, and the blocker names N only

#### Scenario: SCN-VER-294 (−) a repeat with no usable report ends the repeats
- **WHEN** a first run that fails a pre-existing test and a repeat that gives no report, or has a collection error,
  misses a `must_contain` id, fails its exit code with every test passing, or raises an `L4Exit` (its server never gets
  ready, SCN-VER-297); or a repeat whose report is altered; or a tree that cannot be put back
- **THEN** no further repeat is made, `stopped` is `unusable`, the blocker names the first run's test, and an altered
  report adds the blocker `the test report was altered`

#### Scenario: SCN-VER-295 (+) the repeat runs on the tree run 1 started from, without coverage, before the e2e gate
- **WHEN** diff coverage on and a test gate whose first run fails only a pre-existing test that passes on the repeat; or
  an e2e test that fails on a cold tree and writes `var/warm`, which a second run would find
- **THEN** `test-repeat-1` runs with the same `must_contain` and without the coverage environment, the e2e gate runs
  after it, and step 6 reads the first run's coverage; before a repeat the entries the worktree gained since before run
  1 (`var/`) are removed, so the cold-start test fails again, the gate is a blocker and not flaky, and the build output
  of step 2 is still there

#### Scenario: SCN-VER-296 (−) a gate that failed another way, or on more than five tests, is not repeated
- **WHEN** the first run has a collection error, executed no test, is `the test report was altered`, fails six
  pre-existing tests, fails a test whose file `file_of_id` does not find, or misses a `must_contain` id
- **THEN** the gate runs once and is judged as before

#### Scenario: SCN-VER-297 (−) a server that never gets ready in a repeat is an unusable repeat
- **WHEN** an e2e gate whose first run fails a pre-existing test and whose repeat's server never gets ready
- **THEN** the repeat is unusable (`stopped: unusable`), run 1's blocker stands, no finding or row is written for the
  repeat, and the round does not raise (a first run's server that never gets ready still does, exit 1, L4-VER-010)