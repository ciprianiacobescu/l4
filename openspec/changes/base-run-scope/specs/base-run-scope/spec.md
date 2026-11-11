## MODIFIED Requirements

### Requirement: L4-IMP-003 (amendment, the base run's test files and limit)
In the confirmation by a base run, test files, test support files and harness, spec and documentation paths (evidence
kind `exempt`) SHALL stay as the work tree holds them, except the unit's own test files that L4-IMP-097 puts at the unit
base for the run; the run SHALL be stopped at the limit of L4-IMP-097. Everything else of the base run is unchanged: it
only confirms, a criterion is confirmed only when one of its new tests fails by assertion there, a skipped or
undecided run confirms nothing, and every file touched is put back byte for byte before anything else runs.

#### Scenario: SCN-IMP-532 (+) The work tree is the same after a scoped base run
- **Given** a scoped base run that removed one added test file of the unit and gave a changed one its base content
- **When** the run confirms, is stopped at its limit, or its gate raises
- **Then** both files are back byte for byte (sha256), with the production files, before the next check runs, and no
  `restore failed` is recorded

## ADDED Requirements

### Requirement: L4-IMP-097 The base run runs the step's candidates without the unit's other test files, within its own limit
The tests a base run decides SHALL be the candidate tests it is given that are among the step's new tests (at the
no-new-test call site, every candidate test). For the duration of the run, every file that holds a test of the head
report (its tests and its collection errors, mapped to files with `test_locate.file_of_id`), that the unit added or
changed since the unit base (by commits or in the work tree), that matches `tdd.test_globs` and not
`tdd.test_support_globs`, and that holds none of the decided tests SHALL be put at the unit base: removed when the unit
added it, given its unit-base content when the unit changed it. Test support files and files that hold no reported
test SHALL stay as the work tree holds them. Every such file SHALL be read before the run and put back byte for byte
(sha256 checked) after it, with the production files, before anything else runs. When the file of a decided test
cannot be found, when there is no head report, or when such a file is a link, lies outside the work tree, cannot be
read or is too large to vary, the run SHALL set nothing aside (the run of L4-IMP-003 as it was) and SHALL say why.

The base run SHALL be stopped after twice the wall time of the step's own test gate, at least 300 seconds and at most
`gates.timeout`; when the step's test gate time is unknown, after `gates.timeout`. A run stopped at a limit below
`gates.timeout` SHALL decide nothing, as a timed-out base run does (L4-IMP-060), and its reason SHALL name the limit
(`timed out after <n>s: the base run's own limit, twice the step's test run (at least 300s)`). `GateResult` SHALL carry
the wall time of its command. Each base run SHALL record `base_run.scope{decided, kept, at_base, aside, more,
timeout_s, unscoped}` before its gate runs (paths only, lists of at most 20 and 50 entries, `more` the count left out).

#### Scenario: SCN-IMP-526 (+) An earlier task's test file is set aside, and the step's candidate is confirmed
- **Given** a unit whose earlier task added a test file whose tests cannot finish against the unit base code, and a red
  step whose new test, in another file, passes at head and fails by assertion against the unit base code
- **When** the base run executes
- **Then** the earlier task's file is absent during the run, the step's file and the support files are present, the
  criterion is confirmed `via: base_run`, and `base_run.scope` names the earlier file under `aside`

#### Scenario: SCN-IMP-527 (+) A pre-existing test file the unit changed runs at its base content
- **Given** a unit whose earlier task changed a pre-existing test file that holds no candidate test
- **When** the base run executes
- **Then** that file holds its unit-base content during the run (`at_base`) and its head content after it

#### Scenario: SCN-IMP-528 (+) A file that holds a candidate and earlier tests stays whole
- **Given** a red step that added its candidate test to a test file an earlier task of the unit wrote
- **When** the base run executes
- **Then** that file stays as the work tree holds it, with its earlier tests, and `base_run.scope` lists it under `kept`

#### Scenario: SCN-IMP-529 (+) Support files, fixtures and files without tests stay
- **Given** a unit that added a test support file, a fixture file under a test glob and a `conftest.py`, none of which
  holds a reported test
- **When** the base run executes
- **Then** each stays as the work tree holds it

#### Scenario: SCN-IMP-530 (−) A candidate whose file is not found sets nothing aside
- **Given** a decided test whose id `file_of_id` cannot map to a file of the work tree
- **When** the base run executes
- **Then** every test file stays as the work tree holds it, the run is the run of L4-IMP-003, and `base_run.scope`
  says `unscoped: the file of <id> was not found`

#### Scenario: SCN-IMP-531 (−) The base run stops at its own limit
- **Given** `gates.timeout: 30m` and three red steps whose test gate took 200 s, 10 s and 20 minutes
- **When** each step's base run executes
- **Then** its limit is 400 s, 300 s and 1800 s; a run of the first step that does not finish in 400 s is stopped, its
  reason names `the base run's own limit`, its criteria stay as the zero-value run left them (inconclusive: the task is
  held with a `pre_satisfied` question), and `base_run.scope.timeout_s` is 400
