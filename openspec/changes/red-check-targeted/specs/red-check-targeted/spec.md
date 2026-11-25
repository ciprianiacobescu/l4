## Purpose

A red step of a configuration that sets `gates.test.red_check: targeted` runs only the test files it added, when
it only added test modules and the run is complete, and judges them against the base report with their results
added. Anything else runs the whole suite as before, and the ledger says which and why. A regression that a targeted
red let through is seen at green, recorded, and ends the unit's targeted reds.

## ADDED Requirements

### Requirement: L4-CFG-007 A red step's test run is chosen by `gates.test.red_check`.
The key `gates.test.red_check` SHALL be `full` (the default) or `targeted`. With `full`, `gates.test.targeted` SHALL
not be read: a configuration that sets it and omits `red_check` loads as before. With `targeted`, loading
`.l4/config.yaml` MUST fail with a configuration error (exit 2 in every command, `l4 doctor` included) unless
`gates.test.targeted` splits into words as a shell would (`shlex`), holds exactly one word equal to `{files}`, and
holds no other word that contains `{files}` or `{grep}`. The message SHALL name `gates.test.red_check` and
`gates.test.targeted`, say which rule failed and how to fix it, and SHALL NOT contain the command. `{grep}` is not
supported. A harness that predates the key refuses it as an unknown key, so a consumer moves its pin before it sets
the key and removes the key before it moves the pin back.

#### Scenario: SCN-CFG-08 (+) A targeted red check with a command that holds {files} loads
- **Given** `gates.test.red_check: targeted` and `gates.test.targeted: npx vitest run --reporter=junit
  --outputFile=.l4-out/junit.xml {files}`
- **When** `l4 doctor` loads the configuration
- **Then** it loads, and with `red_check` omitted the key is `full`

#### Scenario: SCN-CFG-09 (−) A targeted red check with no command does not load
- **Given** `gates.test.red_check: targeted` and `gates.test.targeted` empty or unset
- **When** `l4 doctor` and `l4 run` load the configuration
- **Then** both exit 2 naming `gates.test.red_check` and `gates.test.targeted` and the fix, and no check runs

#### Scenario: SCN-CFG-10 (−) `{files}` must be one word of its own, once, and `{grep}` is refused
- **Given** `red_check: targeted` and, one per configuration, a command with `--include={files}`, one with `{files}`
  twice, one with `{grep}`, one with no placeholder, and one with an unbalanced quote
- **When** each configuration loads
- **Then** each exits 2 with a message that names the keys and the broken rule and does not contain the command

#### Scenario: SCN-CFG-11 (+) `full` does not read the targeted command
- **Given** a 0.4.60 configuration with `gates.test.targeted: "pytest {grep}"` and no `red_check`, and another with
  `red_check: full` and an unbalanced quote in `targeted`
- **When** each loads
- **Then** both load, and red runs the whole suite as before with no `task.red_check_full` and no new key in
  `task.red_ok`

#### Scenario: SCN-CFG-12 (+) Quoted words around the one `{files}` word load
- **Given** `red_check: targeted` and `targeted: uv run pytest -k 'slow or fast' --junitxml=.l4-out/junit.xml {files}`
- **When** the configuration loads
- **Then** it loads: `{files}` is the one word that equals the placeholder, and a quoted word with spaces is one word

### Requirement: L4-GAT-007 A targeted test run replaces `{files}` with the new test files and nothing else.
The targeted command SHALL be `gates.test.targeted` split with `shlex`, with the one word `{files}` replaced by the
files as separate words and the words joined again, so that each path is one argument and no shell reads it (the gate
runner runs no shell). The files SHALL be repository-relative POSIX paths as git lists them, with no `./`, sorted by
their text. It SHALL run as the gate `test-targeted`, in the unit's work tree and the gate sandbox, with the environment
of the gate `test` and the limit `gates.timeout`. It SHALL write the reports that `gates.test.reports` lists, in
`gates.test.format`: the runner removes them before the run and fails the run with `report missing: <path>` when one is
not there afterwards, as for every test gate, and merges several reports into one. Its report SHALL not be published or
kept. The gate SHALL not count toward L4-IMP-099's longest run, which counts only `baseline` and `test`. A command SHALL
never be built for more than 50 files, for paths that together hold more than 8,000 bytes, or for a path that starts
with `-` or `@` (pytest reads `@file` as an argument file) or holds a control character (L4-IMP-117).

#### Scenario: SCN-GAT-12 (+) The command holds the new files as separate arguments, in order
- **Given** `targeted: npx vitest run --reporter=junit --outputFile=.l4-out/junit.xml {files}` and new files
  `test/b.test.ts` and `test/a dir/a.test.ts`
- **When** the targeted command is built
- **Then** the argv ends `test/a dir/a.test.ts`, `test/b.test.ts` as two items, in that order, and no shell ran

#### Scenario: SCN-GAT-13 (+) The targeted run is its own gate with the gate's reports
- **Given** an eligible red step whose command writes `.l4-out/junit.xml`
- **When** the step runs
- **Then** `gate.finished{name: test-targeted}` is recorded, no `test` gate ran in the step, the report is read from
  `gates.test.reports`, and L4-IMP-099's longest run is unchanged

### Requirement: L4-GAT-008 The report the red checks judge holds the base report with the targeted results added.
`with_targeted(base, targeted)` SHALL give a report whose tests are the tests of the base report and the tests of the
targeted report (the two share no id, L4-GAT-009), whose collection errors are none, and which is local to the red
step. The base report of the step, the measured baseline, SHALL stay unchanged and be the one `RedOutcome.base_report`
carries.

#### Scenario: SCN-GAT-14 (+) The report of the red checks is the baseline with the new failing tests added
- **Given** a base report of 300 passing tests and 2 failing ones, and a targeted report of 3 new failing tests
- **When** `with_targeted` builds the report
- **Then** it holds 305 tests with the base statuses and the 3 new failing cases, has no collection error, and the
  base report object is unchanged

### Requirement: L4-GAT-009 A targeted run is used only when it is complete; otherwise the same step runs the whole suite.
A targeted run SHALL be usable only when all of these hold, tested in this order: a report was read (`no_report`); the
report has no collection error (`collection_errors`); no test id of it is a test id of the base report
(`existing_tests_ran`); every listed file owns at least one id and every id belongs to a listed file, found by
`file_of_id` among the tracked paths and the listed files, the listed files preferred (`file_without_tests`,
`id_without_file`); and every id has the status `failed` or `error` (`new_test_not_failing`: a new test that passes or
is skipped needs the proofs of L4-IMP-003, whose variant runs take the whole report). When the run is not usable and
did not time out, the step SHALL put the tree back as `tree_before` took it (a failed put-back does not stop the run),
run the gate `test` as a step with `full` does, go on with that report, and record `task.red_check_full` (L4-IMP-120).
A targeted run that timed out SHALL fail the attempt with the reason of a gate that produced no readable report, with
no fallback: a new test that hangs is the step's to fix. The step's guard after a gate run SHALL run after each of the
two runs.

#### Scenario: SCN-GAT-15 (−) A targeted run with no report, or a collection error, runs the whole suite
- **Given** an eligible step whose targeted command writes no report (`report missing`), and another whose report has
  a collection error
- **When** each step runs
- **Then** each runs the gate `test` in the same step and records `task.red_check_full{why: no_report}`, respectively
  `why: collection_errors`, and the step's verdict is the one a `full` step gives

#### Scenario: SCN-GAT-16 (−) A targeted run that ran an old test, or ran nothing of a file, runs the whole suite
- **Given** a targeted report with one id of the base report (a filter that matched an old file), another that holds
  no id for one of two listed files, and another with an id that no listed file owns
- **When** each step runs
- **Then** each runs the gate `test` in the same step with `why: existing_tests_ran`, `file_without_tests` and
  `id_without_file`, and none of the three targeted reports is judged

#### Scenario: SCN-GAT-17 (−) A new test that passes or is skipped runs the whole suite
- **Given** a targeted report in which a new test passes and another in which one is skipped
- **When** each step runs
- **Then** each runs the gate `test` with `why: new_test_not_failing`, so the pre-satisfied checks see the whole
  report, and `confirmed_by_base_run` gets the whole run's duration

#### Scenario: SCN-GAT-18 (−) A targeted run that times out fails the attempt with no whole run
- **Given** a targeted command that runs past `gates.timeout`
- **When** the step runs
- **Then** the attempt fails with `the test gate produced no readable report (timed out after <n>s)`, no gate `test`
  ran and no `task.red_check_full` is recorded

#### Scenario: SCN-GAT-19 (+) The step's guard runs after the targeted run and after the whole run
- **Given** a targeted run whose test wrote a production file, and a fallback whose whole run did
- **When** each step runs
- **Then** each production file is put back and the attempt fails with `test code changed production files while a
  gate ran`, as after any gate

#### Scenario: SCN-GAT-20 (+) The fallback starts on the tree the step had before the targeted run
- **Given** a targeted run that left an untracked file, then a fallback
- **When** the fallback starts
- **Then** the file is removed before the gate `test` runs; when the tree cannot be put back the gate `test` runs
  anyway

### Requirement: L4-IMP-117 Each red step chooses its check from rules that hold for that step.
With `gates.test.red_check: targeted`, a red step SHALL run the targeted check (L4-IMP-118) only when all of these hold,
tested in this order, and SHALL otherwise run the whole suite exactly as with `full` and record
`task.red_check_full{why}` (L4-IMP-120): the unit's ledger holds no `task.red_check_disabled` (`unit_switched`,
L4-IMP-121); the task names no existing test that red may change (`named_tests`) and is no reopened task with stale
tests (`stale_tests`); the base report has no collection error (`base_collection_errors`: `baseline` refuses one, so
this never fires today); the step added no stub (`stubs`: `RedScope.stub_files` and `stubs` are empty); red scope put
nothing back (`restored`: `RedScope.restored` is empty); every path the step changed, less the run's ledger and the
tool-cache and bytecode entries that the production guard ignores, did not exist at the base (`existing_file_changed`);
each of them is a test module (`not_a_test_module`: it matches `tdd.test_globs` and no glob of `tdd.test_support_globs`
or `tdd.runner_config_files`, and the verifier's support rule, `is_support_file`, applied to the file in the work tree,
does not call it a support file); at least one is left (`no_test_file`); there are at most 50 of them and 8,000 bytes of
paths, counted in bytes of UTF-8 (`too_many_files`); and none starts with `-` or `@` (pytest reads `@file` as an
argument file) or holds a control character (`odd_path`). The choice SHALL be made for each step from these rules only:
no model output and no clock. With `full`, the rules SHALL not run and nothing SHALL be recorded. A Python repository
SHALL get the same rules and no others: a step that adds a stub is not eligible, and since L4-IMP-002 keeps additive
stubs in production `.py` files, most Python red steps run the whole suite. [V, in one TypeScript consumer plan of seven
units 66 red-step runs of the whole suite took about 4.9 minutes each, about 320 minutes in all, and 8 red steps failed
with `red broke existing tests` on end-to-end stack or journey tests, probably flakes (inferred); 27 of 45 clean-tree
baseline runs of the same plan had failing tests]

#### Scenario: SCN-IMP-626 (+) A red step that adds only test modules runs only those
- **Given** `red_check: targeted` and a red step that adds `test/pricing.test.ts` and `test/cart.test.ts`, whose tests
  all fail by assertion
- **When** the step runs
- **Then** it runs `test-targeted` once with the two files, no `test` gate, commits red, and `task.red_ok` has `check:
  targeted` and `files: [test/cart.test.ts, test/pricing.test.ts]`

#### Scenario: SCN-IMP-627 (+) With `full` nothing is recorded and nothing changes
- **Given** the step of SCN-IMP-626 with `red_check: full`, and a 0.4.60 configuration
- **When** the step runs
- **Then** it runs the gate `test` once, records no `task.red_check_full`, and `task.red_ok` has no `check` and no
  `files`

#### Scenario: SCN-IMP-628 (−) A step that changes an existing file runs the whole suite
- **Given** a step that adds `test/new.test.ts` and appends a test to the existing `test/old.test.ts`, and another
  that deletes an old test file
- **When** each step runs
- **Then** each runs the gate `test` with `task.red_check_full{why: existing_file_changed}`

#### Scenario: SCN-IMP-629 (−) A support file, a helper, a stub or a restored production file runs the whole suite
- **Given** a step that adds `test/new.test.ts` and `test/helpers/db.ts`; one that adds `tests/conftest.py`; one that
  adds a Python stub; one whose production file red scope put back; and one that adds `test/data.ts` (no test module)
- **When** each step runs
- **Then** each runs the gate `test` with `why: not_a_test_module`, `not_a_test_module`, `stubs`, `restored` and
  `not_a_test_module`

#### Scenario: SCN-IMP-630 (−) A task that names a test, or a reopened task, runs the whole suite
- **Given** a task whose reviewed text names an existing test, and a reopened task with stale tests, each with an
  otherwise eligible step
- **When** each step runs
- **Then** each runs the gate `test` with `why: named_tests`, respectively `stale_tests`

#### Scenario: SCN-IMP-631 (−) A step with no new file, 51 files or an odd path runs the whole suite
- **Given** a step that changes only the run's ledger, one with 51 new test files, one with six new files whose
  paths hold fewer than 8,000 characters and more than 8,000 bytes, and one with a new file named `-x.test.ts` and
  one named `@list.test.ts` (pytest reads `@file` as an argument file)
- **When** each step runs
- **Then** each runs the gate `test` with `why: no_test_file`, `too_many_files`, `too_many_files` and `odd_path`, and
  no command is built

#### Scenario: SCN-IMP-632 (+) A Python step that adds only a test module is eligible by the same rules
- **Given** a Python repository with `red_check: targeted` and `targeted: uv run pytest --junitxml=.l4-out/junit.xml
  {files}`, and a red step that adds `tests/test_pricing.py` and no stub
- **When** the step runs
- **Then** it runs `test-targeted` with that file; the same step with a stub in `src/pricing.py` runs the whole suite

### Requirement: L4-IMP-118 A targeted red step runs its new test files, then judges as it does today.
An eligible step SHALL run the gate `test-targeted` (L4-GAT-007) in the place of the gate `test`, after red scope and
the production guard are set, then the step's tamper check, then the usability test of L4-GAT-009. When the run is
usable, the step SHALL bind its report to the base report with the targeted results added (L4-GAT-008) and judge it
with every check it has today and in the same order: the new tests and their failure kinds, the criteria and their
caps, the static gates, the zero-value variant runs, the verdict (`classify_red`) and the commit with `task.red_ok`. A
usable run holds only failing new tests, so the pre-satisfied confirmation, a base run and the already-satisfied
commit are not reached with it: a step with a new test that passes runs the whole suite (L4-GAT-009). When the run is
not usable, the step SHALL continue as a step that never tried the targeted check. The soft deadline SHALL stop the
targeted run as it stops any gate. The step's duration is the sum of its runs, and `deadline.cap_s` is unchanged.

#### Scenario: SCN-IMP-633 (+) A flaky old test cannot fail a targeted red
- **Given** a baseline in which `tests.test_stack::test_ready` passes, and an eligible step whose whole suite would
  fail that test once
- **When** the step runs with `targeted`
- **Then** the step is judged on its new tests alone and commits red; no `red broke existing tests` and no
  `test-recheck` arise

#### Scenario: SCN-IMP-634 (−) Every other red verdict is the one a whole run gives
- **Given** eligible steps whose new tests fail by an error that is no assertion, whose new tests cite no criterion of
  the task, or whose test code writes a production file
- **When** each step runs
- **Then** each attempt fails with the reason a `full` step gives for it, word for word

#### Scenario: SCN-IMP-637 (+) The variant runs judge against the overlay and run the whole command
- **Given** an eligible Python step with no stub of its own and a stub of an earlier task at HEAD, whose new tests
  fail
- **When** the vacuity check runs
- **Then** it runs the whole command with the HEAD stubs zeroed and compares the new tests with the report that holds
  the base tests and the new ones

### Requirement: L4-IMP-119 A targeted red changes what no later reader of the red step sees.
`RedOutcome.base_report` SHALL stay the measured baseline, so green judges with it as before (`green_failures` against
the baseline, the red ids from `new_ids`). A targeted red SHALL NOT change what these read: the near-pass carry; the
next task's baseline, which is green's report and never red's; and verification, which reads `task.red_ok` (`tests`,
`frozen`, `criteria`, `notes`) and the red commit and runs its steps 1 and 3 on the whole suite. Inside red, a test that
the targeted run did not run SHALL be judged by its base status: `red broke existing tests` and `no new test: existing
tests were changed` cannot fire for it, and the checks that read passing old tests (`passing_now`, `unchanged_on_base`,
the proofs of earlier reds) read base statuses. The duration of the targeted run SHALL never bound a whole-suite run.
`resume_red` runs at the start of every execution of a task (after a deadline, a retry, a resume or an answered
question), so it SHALL measure the base of a targeted red as the red step measured its own: with the red's files absent.
When `task.red_ok` has `check: targeted` and `files`, `resume_red` SHALL remove those files from the work tree for its
one whole run, run the whole suite, and put each back byte for byte with its mode before it returns; a targeted red only
adds new files, so the tree without them is the red commit's parent, and an old test that the red files break passes in
that base and is in green's regressed set (L4-IMP-121). It SHALL do so only when each file is a regular file of the work
tree with the red commit's own bytes, did not exist at the red commit's parent, and no other path of the red commit is
anything but the unit's own folder or a tool cache. When any of that fails, or a file is not back exactly (git then
restores it from the red commit), `resume_red` SHALL fall back to a whole run at the red commit, as for a whole red, and
SHALL record `task.red_check_disabled` with `why` `resume_files` or `resume_put_back` (L4-IMP-121). The tamper guards and the test freeze are unchanged: the freeze reads the red commit, and the files are back before
green starts. A run killed inside the files-absent run leaves them removed; `resume_red` then puts each listed file
that the red commit holds and the work tree lacks back from the red commit before it returns, so the freeze does
not report it as tampering. A red
that was not targeted is measured at the red commit as before.

#### Scenario: SCN-IMP-635 (+) Green judges with the baseline after a targeted red
- **Given** a task whose red was targeted
- **When** green runs
- **Then** `RedOutcome.base_report` is the measured baseline, green's whole run is judged against it, and `red tests
  still failing` and `new failing tests added in green` are as after a full red

#### Scenario: SCN-IMP-646 (+) Verification still runs the whole suite on a unit with targeted reds
- **Given** a unit whose red steps were all targeted and whose green steps passed
- **When** verification runs its steps 1 and 3
- **Then** both run the whole suite with the same commands as for a unit of 0.4.60, and an old test that fails at head
  is a finding as it is today

#### Scenario: SCN-IMP-648 (+) A resumed targeted red measures its base without its files, and green sees the old test
- **Given** a run killed after a targeted red commit whose new test file breaks `tests.test_db::test_rows` only when
  the whole suite runs, and a next run (a deadline, a retry or an answered question starts one) that resumes at green
- **When** `resume_red` measures the base
- **Then** the whole run happens with the red's files absent from the work tree and the files are back, with their
  bytes and mode, before it returns; the base report holds `tests.test_db::test_rows` as passing and none of the new
  tests; green's whole run then fails the test after its re-run, records `task.red_check_disabled{why: regressed}`, and
  the reason ends with the suffix of L4-IMP-122; verification's whole-suite steps report the test as they do today

#### Scenario: SCN-IMP-649 (−) A record the red commit does not match, or files that do not come back exactly, fall back and record the switch
- **Given** a resumed targeted red whose `task.red_ok` names a file that the red commit does not hold, a file that the
  red commit's parent already had, a path that leaves the work tree or no list of files, or whose red commit changed a
  file that the record does not name; and one whose files cannot be written back exactly
- **When** `resume_red` measures the base
- **Then** no file is left removed, the base is measured with a whole run at the red commit as for a whole red, and
  `task.red_check_disabled{attempt: 0, why: resume_files | resume_put_back}` is recorded once for the unit

### Requirement: L4-IMP-120 The ledger names the red check that ran and why the whole suite ran.
The gate of a targeted run is `gate.finished{name: "test-targeted"}`. `task.red_ok` of a step of a `targeted`
configuration SHALL carry `check` (`targeted` or `full`) and, for `targeted`, `files` (sorted, at most 50). A step of a
`targeted` configuration that ran the whole suite SHALL record `task.red_check_full{task, attempt, why, detail}`: `why`
is a word of L4-IMP-117 or L4-GAT-009 or `unit_switched`, and `detail` is at most 300 characters and names at most five
paths or ids. A red step of a `full` configuration SHALL write none of these keys and events, so a unit that never ran a
targeted red has the ledger of 0.4.60; `task.red_check_disabled` is written by green and by `resume_red` from the unit's
ledger, whatever the configuration says at that moment (L4-IMP-121). A reader SHALL treat a missing `check` as `full`
and a missing event as none: a ledger written by 0.4.60 folds unchanged, and a harness that does not know the keys and
events ignores them, as the fold ignores a type it does not know. `resume_red` SHALL set `RedOutcome.check` and
`RedOutcome.files` from the `task.red_ok` it reads, so that green decides from the red commit's own record also in a
later job.

#### Scenario: SCN-IMP-636 (+) A resumed red reads its check from its record
- **Given** a run that died after a targeted red commit, and a 0.4.60 red commit
- **When** the next run resumes at green
- **Then** `RedOutcome.check` is `targeted`, respectively `full`, read from `task.red_ok` (with `RedOutcome.files` for
  `targeted`); the base report of a 0.4.60 red commit is measured with a whole run at the red commit, as before, and
  that of a targeted one with the red's files absent (SCN-IMP-648)

#### Scenario: SCN-IMP-638 (+) The ledger shows the gate, the check and the fallback reasons
- **Given** a `targeted` configuration, one step that ran targeted and one that fell back
- **When** the run finishes
- **Then** `gate.finished` has `test-targeted` for both, `task.red_ok` has `check` and `files` for the first and
  `check: full` for the second, and the second has `task.red_check_full{why, detail}` with at most 300 characters

#### Scenario: SCN-IMP-639 (+) A 0.4.60 ledger folds and an older harness ignores the new records
- **Given** a unit whose ledger is of 0.4.60 and a unit whose ledger holds the new records
- **When** the first is read by this harness and the second by 0.4.60
- **Then** the first folds with every `check` read as `full` and no switch; the second folds in 0.4.60, which ignores
  the keys and events

### Requirement: L4-IMP-121 A regression after a targeted red switches the unit back to full red runs.
The step SHALL record `task.red_check_disabled{task, attempt, why, tests, red_sha}` once for the unit, in each of these
cases: (a) `regressed`: green's whole-suite run in a unit whose ledger holds a `task.red_ok` with `check: targeted` (of
any task, fix units included) still holds, after green's own re-run (L4-IMP-105), a regressed test (a test that was not
new and passed in the red step's base report: `GreenWhy.regressed`); and, when the green is of a task whose own red was
targeted (`RedOutcome.check` is `targeted`), a frozen red file may be the cause of a failure that green cannot fix: (b)
`ids_missing`: it fails `red tests still failing` for a red test that is missing from the run's report; (c)
`green_collection`: the run's report has a collection error that names a file of that red (`RedOutcome.files`, by path
or dotted module); (d) `green_no_report`: the run has no readable report or timed out. `tests` holds at most 20 ids (the
files, for (c); none, for (d)) and `red_sha` is the task's red commit. `resume_red` SHALL record it too, with `attempt`
0 and `why` `resume_files` or `resume_put_back`, when it cannot measure a targeted red's base without its files
(L4-IMP-119). Every later red step of the unit and of its fix units SHALL then run the whole suite and record
`task.red_check_full{why: unit_switched}`. The switch SHALL last as long as the unit's ledger: `l4 retry` and `l4
resume` keep it, and `l4 restart`, which starts a new ledger, reads the key again. The record is driven by the unit's
ledger and never by the configuration: a unit whose key was set back to `full` after a targeted red still records it.
The record SHALL be made also when green's own code broke the test: both causes call for the same safe action. The
unit-wide trigger of (a) is on purpose: an interaction that depends on order or on a shared port can first show in a
later task's green. Green and verification stay whole-suite in every case. [I, a new test file can break an old test by
interaction (a shared database, a port, a module-level mock, a snapshot directory) that only a whole run shows; no
ledger of a consumer shows one yet]

#### Scenario: SCN-IMP-641 (+) A regression that passes on green's re-run records nothing
- **Given** the green of SCN-IMP-640 whose re-run passes the test
- **When** green judges its gate
- **Then** `task.tests_rechecked{stopped: passed}` is recorded, the task is committed, and there is no
  `task.red_check_disabled`

#### Scenario: SCN-IMP-642 (+) After the switch every red step of the unit runs the whole suite
- **Given** a unit with `task.red_check_disabled`, a later task and a fix unit, and an eligible step of each
- **When** each step runs, and then `l4 retry` and a new run, and then `l4 restart`
- **Then** each step before the restart runs the gate `test` with `task.red_check_full{why: unit_switched}`; after `l4
  restart` the new ledger has no record, so the key is read again

#### Scenario: SCN-IMP-643 (−) A red test missing from green's report records the switch and names the command
- **Given** a task whose red was targeted, whose red id `test/a.test.ts::x` is not in green's whole report (the runner
  names it otherwise), and no failing base test
- **When** green judges its gate
- **Then** the attempt fails with `red tests still failing: test/a.test.ts::x` and the suffix of L4-IMP-122 for a
  missing id (the targeted command names the tests differently; a person fixes `gates.test.targeted` and runs `l4
  restart`), and `task.red_check_disabled{why: ids_missing}` is recorded

#### Scenario: SCN-IMP-644 (+) A regression in a later task whose own red ran whole still records the switch
- **Given** a unit whose task 1.1 has `task.red_ok{check: targeted}`, and a task 1.2 whose red ran the whole suite
  (`task.red_ok{check: full}`) and whose green has the failure of SCN-IMP-640
- **When** green of task 1.2 judges its gate
- **Then** `task.red_check_disabled{task: 1.2, why: regressed}` is recorded and the reason has no suffix of
  L4-IMP-122, since the red of task 1.2 was not targeted

#### Scenario: SCN-IMP-645 (+) The switch is recorded once
- **Given** a unit with `task.red_check_disabled` and a green that fails again after a regression
- **When** green judges its gate
- **Then** no second `task.red_check_disabled` is recorded

#### Scenario: SCN-IMP-651 (−) A whole run with no readable report or a timeout, after a targeted red, records the switch
- **Given** a task whose red was targeted, and a green whose whole run wrote no report, or hit `gates.timeout`
- **When** green judges its gate
- **Then** the attempt fails with the reason of any gate that produced no readable report, with no suffix, and
  `task.red_check_disabled{why: green_no_report, tests: []}` is recorded once; after a whole red nothing is recorded

#### Scenario: SCN-IMP-652 (+) The switch is read from the ledger, whatever the key says now
- **Given** a unit with a targeted red whose key `gates.test.red_check` was then set back to `full`, and a green with
  the failure of SCN-IMP-640
- **When** green judges its gate, and later a red step of the `full` configuration runs
- **Then** `task.red_check_disabled` is recorded and the reason has the suffix of L4-IMP-122; the red step runs the
  whole suite and writes neither `check` nor `task.red_check_full`

#### Scenario: SCN-IMP-647 (−) A unit with no targeted red records no switch
- **Given** a unit whose `task.red_ok` events have no `check` (a unit of 0.4.60) or `check: full`, in a `targeted`
  configuration, and a green with the failure of SCN-IMP-640
- **When** green judges its gate
- **Then** no `task.red_check_disabled` is recorded and the reason has no suffix of L4-IMP-122

### Requirement: L4-IMP-122 Green says that a targeted red may be the cause.
An attempt of a task whose own red was targeted that fails with a regressed set SHALL end its reason with `; the red
step of this task ran only its new test files (L4-IMP-122): if no change of the code can make these tests pass, report
status blocked with a question that names the test file`. One that fails with `red tests still failing` for a red test
that is missing from the report SHALL end it with `; the red step of this task ran only its new test files (L4-IMP-122):
the whole suite reports these tests under other ids than the targeted command did, so no change of the code can make
them pass: report status blocked and say so; a person fixes gates.test.targeted and runs l4 restart`. One that fails
with a collection error that names a file of that red SHALL end it with `; the red step of this task ran only its new
test files (L4-IMP-122): if no change of the code can make this file collect, report status blocked with a question that
names the test file`. A failure with no readable report or a timeout gets no suffix. The suffix follows any suffix of
L4-IMP-105. The attempt fails as it does today, so the loss is bounded by `implementer.max_task_attempts` and the unit's
escalation, and the cause is named in the reason, the escalation and `task.red_check_disabled`. A task whose own red was
not targeted gets no suffix, whatever the unit's other tasks did. The structured marker of L4-IMP-105 SHALL NOT be read
from the text.

#### Scenario: SCN-IMP-640 (−) A regression in green after a targeted red records the switch and says why
- **Given** a task whose red was targeted and a green whose whole run fails `tests.test_db::test_rows` (it passed in
  the base report and its file is no file of the unit) on the run and on the re-run
- **When** green judges its gate
- **Then** `task.red_check_disabled{why: regressed, tests: [tests.test_db::test_rows]}` is recorded, and the attempt
  fails with the reason of 0.4.60, the suffix of L4-IMP-105 and `; the red step of this task ran only its new test
  files (L4-IMP-122): if no change of the code can make these tests pass, report status blocked with a question that
  names the test file`

#### Scenario: SCN-IMP-650 (−) A collection error that names a file of the targeted red records the switch and says why
- **Given** a task whose red was targeted, and a green whose whole run has a collection error for `tests/test_new.py`,
  a file of that red
- **When** green judges its gate
- **Then** the attempt fails with `tests not collected: tests/test_new.py` and the collection suffix of L4-IMP-122,
  and `task.red_check_disabled{why: green_collection, tests: [tests/test_new.py]}` is recorded; a collection error that
  names another file, or one after a whole red, records nothing and has no suffix
