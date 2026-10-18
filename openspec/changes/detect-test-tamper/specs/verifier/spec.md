## ADDED Requirements

### Requirement: L4-VER-030 Step 1 blocks a pre-existing test that a harness commit changed or deleted
Step 1 SHALL compare every test that exists at the base in each changed test file with head (L4-IMP-045..047). A test
changed, rebound or unparsable SHALL be the blocker `a pre-existing test was changed` and a deleted test that did not
move the blocker `a pre-existing test was deleted`, each naming `<path>::<name>` and why, when a harness commit
introduced it and no allowance of L4-VER-031 holds. A test that the skip check blocks SHALL not be reported again.

#### Scenario: SCN-VER-100 (−) A harness commit that weakens a pre-existing test is a blocker
- **GIVEN** a base with `tests/test_pricing.py::test_total_adds_prices` asserting `== 3.75`, and a harness commit that
  rewrites the assertion to `is not None`
- **WHEN** the integrity check `pre-existing tests` runs
- **THEN** it SHALL raise the blocker `a pre-existing test was changed` with
  `tests/test_pricing.py::test_total_adds_prices (its body, decorators or parametrisation changed)`

#### Scenario: SCN-VER-101 (−) With the red guard bypassed, step 1 stops the false PASS
- **GIVEN** the verifier-2 reproduction (red weakens the pre-existing test, green makes `total()` return `999.0`) with the
  red check of L4-IMP-048 bypassed, so the weakened test reaches the branch
- **WHEN** the unit is verified
- **THEN** step 1 SHALL fail with `a pre-existing test was changed` and the verdict SHALL be FAIL, not PASS

#### Scenario: SCN-VER-102 (−) A rebinding, a changed helper and an unparsable file are changes
- **GIVEN** three harness commits on three base test files: one appends a second `def` of a test name, one weakens a
  helper the test calls, one leaves the file with a syntax error
- **WHEN** the check runs
- **THEN** each test SHALL be in the blocker `a pre-existing test was changed` with its own why

#### Scenario: SCN-VER-103 (−) A deleted test masked by a same-named test elsewhere is still deleted
- **GIVEN** a harness commit that deletes `tests/test_cart.py::test_empty` and appends `def test_empty(): assert True`
  to the changed `tests/test_orders.py`
- **WHEN** the check runs
- **THEN** it SHALL raise the blocker `a pre-existing test was deleted` naming `tests/test_cart.py::test_empty`

#### Scenario: SCN-VER-105 (+) A test moved unchanged to another changed file is not deleted
- **GIVEN** a harness commit that moves `test_one` with the same definition from `tests/test_a.py` to `tests/test_b.py`
- **WHEN** the check runs
- **THEN** it SHALL raise no finding, and after a later commit that deletes `tests/test_b.py` it SHALL raise the deletion

#### Scenario: SCN-VER-109 (+) An added skip marker is reported once
- **GIVEN** a harness commit that adds `pytest.skip('no')` to the body of a pre-existing test and `pytestmark =
  pytest.mark.skip` to its file
- **WHEN** the check runs
- **THEN** the only finding SHALL be `a skip or xfail marker was added`

### Requirement: L4-VER-031 A pre-existing test change with an allowance or by a person is listed
Step 1 SHALL list, never block, a change of L4-VER-030 that only people's commits introduced (`Test changes made by
humans`), that a `tests.superseded` event records, or whose every harness commit belongs to a `[test-infra]` task or
changes a path that a `task.unfrozen` of the same unit and task names (`Pre-existing tests changed with an allowance`).
A harness commit without an `L4-Task`, or one no allowance covers, SHALL keep the blocker.

#### Scenario: SCN-VER-104 (+) A person's deletion masked by a same-named test is listed
- **GIVEN** the change of SCN-VER-103 made by a person's commit
- **WHEN** the check runs
- **THEN** it SHALL raise no finding and list `tests/test_cart.py::test_empty deleted by <sha10>`

#### Scenario: SCN-VER-106 (+) A person's change is listed, a harness change on top still blocks
- **GIVEN** a person's commit that rewrites a pre-existing test, then a harness commit that changes it again
- **WHEN** the check runs after each commit
- **THEN** after the first it SHALL list `<path>::<name> changed by <sha10>` and raise no finding; after the second it
  SHALL raise `a pre-existing test was changed`

#### Scenario: SCN-VER-107 (+) Superseded, `[test-infra]` and unfrozen changes are allowed and listed
- **GIVEN** a changed pre-existing test that a `tests.superseded` event names, one changed by a commit of a task tagged
  `[test-infra]`, and one changed by a green commit of task 1.1 whose file a `task.unfrozen` of task 1.1 names
- **WHEN** the check runs
- **THEN** it SHALL raise no finding, note the superseded one as today, and list the other two with `(task <t>:
  [test-infra])` and `(task 1.1: unfrozen by <source>)`

#### Scenario: SCN-VER-108 (−) A `task.unfrozen` of another task allows nothing
- **GIVEN** a green commit of task 1.2 that changes a pre-existing test whose file only a `task.unfrozen` of task 1.1
  names
- **WHEN** the check runs
- **THEN** it SHALL raise `a pre-existing test was changed`

### Requirement: L4-VER-032 Step 1 blocks a red commit that changed a test an earlier step wrote
For each harness commit with `L4-TDD: red` or `already-satisfied` of a task without `[test-infra]`, step 1 SHALL compare
the test files it changed with its first parent (L4-IMP-045..047). A test that existed at the parent, not at the base,
that the commit changed, rebound or deleted, and that no `tests.superseded` event names, SHALL be the blocker `a red step
changed a test that an earlier step wrote`, naming the test, the task and the commit.

#### Scenario: SCN-VER-110 (−) A later red that weakens an earlier red's test is a blocker
- **GIVEN** the red commit of task 1.1 that adds `tests/test_discount.py::test_known_code`, and the red commit of task
  1.2 that weakens it
- **WHEN** the check runs
- **THEN** it SHALL raise `a red step changed a test that an earlier step wrote` with
  `tests/test_discount.py::test_known_code (task 1.2, red commit <sha10>: …)`

#### Scenario: SCN-VER-111 (+) Appending to an earlier red's file is no change
- **GIVEN** the red commit of task 1.2 that appends new tests to `tests/test_discount.py`, which task 1.1's red wrote
- **WHEN** the check runs
- **THEN** it SHALL raise no finding

### Requirement: L4-VER-033 Audit tests run without the unit's test and support files
Step 4a SHALL run each audit test and its zero-value run with every test and support file the unit added, changed or
deleted at its base version (an added one set aside; added data under `fixtures/`, `mocks/`, `__mocks__/`, `testdata/`
kept), collecting only the audit file, written where the test command collects. Each file SHALL be restored byte for
byte after, also after an error. Runner configuration stays.

#### Scenario: SCN-VER-112 (−) The broken code is held when the unit's conftest is set aside
- **GIVEN** the verifier-6 reproduction written so that step 1's AST rule (L4-VER-037) does not see it (the autouse
  fixture patches through `vars()`): red adds `tests/conftest.py` with an autouse fixture that swaps `apply_discount`
  for a correct one while `CODES` is not empty, and green ships `return amount`
- **WHEN** the unit is verified with `audit_sample_ratio: 0.5`
- **THEN** the audit record SHALL be `failed` with `support: "base"`, its criterion SHALL be held, and the verdict SHALL
  not be PASS

#### Scenario: SCN-VER-113 (+) An honest unit's audit test is accepted with its support files at the base
- **GIVEN** the honest red and green of the reproduction's control, and a red that also adds a harmless
  `tests/conftest.py`
- **WHEN** the unit is verified
- **THEN** the audit record SHALL be `accepted` with `support: "base"` and the verdict PASS

#### Scenario: SCN-VER-114 (+) Support files go to the base for the run and come back byte for byte
- **GIVEN** a unit that added `tests/conftest.py`, changed `tests/fixtures/data.json` and deleted
  `tests/helpers/old.py`, one of them a symbolic link at head
- **WHEN** a run happens inside the revert, once normally and once raising
- **THEN** inside, the first SHALL be absent and the others SHALL have their base bytes; after, every path SHALL have its
  head content, mode and link target, and `git status` SHALL be as before

#### Scenario: SCN-VER-115 (+) A unit test that needs the unit's helper does not stop the audit run
- **GIVEN** a unit whose test file imports `tests/helpers/builders.py`, which the unit added, and an audit test that
  needs nothing of it
- **WHEN** step 4a runs
- **THEN** the audit test SHALL be judged from the run with the support files at the base, despite the other file's
  collection error; with `gates.test.command` narrowed to `tests/unit` the audit file SHALL be written under
  `tests/unit/` and collected

#### Scenario: SCN-VER-118 (+) The zero-value run uses the same support files as the head run
- **GIVEN** an audit test that passes at head with the support files at the base
- **WHEN** its zero-value confirmation runs
- **THEN** that run SHALL also have the support files at the base

#### Scenario: SCN-VER-133 (−) An import-time patch in the unit's own new test module does not reach the audit
- **GIVEN** the verifier-6 patch moved into the unit's own new `tests/test_discount.py` (code at import that swaps
  `apply_discount` while `CODES` is set), and green ships `return amount`
- **WHEN** the unit is verified with `audit_sample_ratio: 0.5`
- **THEN** `tests/test_discount.py` SHALL be set aside and not collected for the audit run, the record SHALL be `failed`
  with `support: "base"`, the criterion SHALL be held, and the verdict SHALL not be PASS

### Requirement: L4-VER-034 An audit test that does not run without the unit's files holds its criterion
An audit test SHALL never run with the unit's test or support files in place. One whose collection fails in a
production module, whose cause the log does not show, or that leaves no report SHALL hold its criterion (L4-VER-012). One
whose own import fails SHALL get the writer's one retry and be a minor rejection when it fails again; so SHALL one the
test command never collects (the reason names the command). Every record SHALL carry `support` `base` or `unchanged`.

#### Scenario: SCN-VER-116 (−) An audit test that needs a fixture only the unit defines is held
- **GIVEN** an audit test that requests a fixture only the unit's `tests/conftest.py` defines, and a step-1 content scan
  with status `ok`
- **WHEN** step 4a runs
- **THEN** the record SHALL be `failed` with `support: "base"` (the fixture is missing at setup), the criterion SHALL be
  held, and no run SHALL have the unit's `tests/conftest.py` in place

#### Scenario: SCN-VER-117 (−) An audit test whose own import fails twice is a minor rejection
- **GIVEN** a writer whose audit test imports a name that `pytdd.pricing` does not define, and whose retry does the same
- **WHEN** step 4a runs
- **THEN** the writer SHALL be asked once more with the collection error, and the second failure SHALL be the minor
  finding `an audit test was rejected` with `support: "base"`

#### Scenario: SCN-VER-132 (−) A production module that imports only with the unit's conftest holds the criterion
- **GIVEN** the handshake reproduction: the unit's `tests/conftest.py` sets `PYTDD_SUPPORT` in `os.environ`, the green
  `src/pytdd/pricing.py` reads it at import and returns `amount`, and step 1's run of L4-VER-038 is bypassed
- **WHEN** step 4a runs, with step 1's content scan `ok` and again with it `skipped`
- **THEN** each time the record SHALL be `failed` with a reason that starts with `a production module fails to import
  without the unit's test and support files: src/pytdd/pricing.py`, the criterion SHALL be held, and the verdict SHALL
  not be PASS

#### Scenario: SCN-VER-136 (+) The writer's collection retry is kept and the label is never empty
- **GIVEN** a unit with a harmless `tests/conftest.py` and a `tests/helpers/setup.ts`, a writer whose first audit test
  does not import and whose retry is correct
- **WHEN** step 4a runs
- **THEN** the second request SHALL carry the collection error, the record SHALL be `accepted` with `support: "base"`,
  and no `verify.audit` of the round SHALL have an empty `support`

### Requirement: L4-VER-035 A generated UI test's head run follows the same rule
Step 5 SHALL run a generated UI test at head with the e2e runner's own support files the unit changed at their base
versions (a test-glob file with no test included), never added app data, collecting only the generated file. One that
does not run so, or whose server does not start, SHALL be `uncollectable` and held, naming the files; no run SHALL
have the unit's files in place. `verify.generated` SHALL carry `support`.

#### Scenario: SCN-VER-119 (−) A generated UI test's head run uses the base support files
- **GIVEN** a UI unit that added `e2e/conftest.py` with an autouse fixture that makes every page check pass, and a
  generated test that fails at head without it
- **WHEN** step 5 judges the test
- **THEN** the head run SHALL have `e2e/conftest.py` set aside, the outcome SHALL be `fails_at_head` with
  `support: "base"`, and the file SHALL be back after the run; the same SHALL hold when the liar is a helper named
  `e2e/test_utils.py` that defines no test and the conftest imports

#### Scenario: SCN-VER-122 (+) An honest UI unit's generated test is accepted with the base support files
- **GIVEN** a UI unit that added a harmless `e2e/conftest.py`, and a generated test that fails at the merge base and
  passes at head without it
- **WHEN** step 5 judges the test
- **THEN** the outcome SHALL be `accepted` with `support: "base"`

#### Scenario: SCN-VER-134 (+) An honest UI unit's app data under `fixtures/` stays for the head run
- **GIVEN** a UI unit whose app serves the page from `fixtures/cart.html`, which the unit added, and a generated test
  that fails at the merge base and passes at head
- **WHEN** step 5 judges the test with a clean content scan
- **THEN** `fixtures/cart.html` SHALL stay in place for the head run and the outcome SHALL be `accepted`

#### Scenario: SCN-VER-135 (−) A server that does not start without the unit's runner support holds the criterion
- **GIVEN** a head app that starts only while the unit's `e2e/conftest.py` is present, and another that imports a code
  file the unit added under `fixtures/` (`fixtures/seed.py`) next to a conftest that makes every page check pass
- **WHEN** step 5 judges a generated test, once with step 1's content scan `ok` and once `skipped`
- **THEN** no exception SHALL leave step 5, and each time the outcome SHALL be `uncollectable` with a reason that starts
  with `the app does not start without the unit's test and support files` and names the reverted files (and, from the
  server's log, the file and error that stopped it); no run SHALL have the unit's files in place

### Requirement: L4-VER-036 A person sees how each verifier test ran
`verify.audit` SHALL carry `support` and `support_files`, and verification.md's Audit table a `Support` column.
`verify.base_tests` SHALL carry the counts, the base source and the reverted files of L4-VER-038, shown in the row
`pre-existing tests still pass`. verification.md SHALL list the changes L4-VER-031 allowed and the fixtures of
L4-VER-037 that patch the unit's code on request.

#### Scenario: SCN-VER-120 (+) verification.md says how each audit test ran and lists the allowed changes
- **GIVEN** a round with one audit test run at the base support, one that fell back, and one allowed `[test-infra]`
  change of a pre-existing test
- **WHEN** verification.md is written
- **THEN** the Audit table SHALL show `base` and `head` in its `Support` column, and the allowance section SHALL list the
  change with its task

#### Scenario: SCN-VER-123 (−) A rejected audit test says why it did not run at the base
- **GIVEN** the rejection of SCN-VER-117
- **WHEN** verification.md is written
- **THEN** `## Rejected audit tests` SHALL list the criterion with the reason that starts with `it does not run with the
  unit's support files at the base` and names the content scan's note

### Requirement: L4-VER-037 Step 1 blocks a support file that patches the unit's code for every test
Step 1 SHALL check every changed Python test-support file, not only an opened one, for a new patch or assignment of a
symbol of a production module the unit changed (L4-IMP-016 rule 3). One that runs for every test, or whose use is
unknown, SHALL be a content-scan blocker; one inside a fixture that a test requests by name SHALL be listed. A person's
commit and a `[test-infra]` task SHALL be handled as for every other content-scan hit.

#### Scenario: SCN-VER-124 (−) An autouse fixture that patches the unit's code is a blocker
- **GIVEN** a unit that changed `src/pytdd/pricing.py` and added `tests/conftest.py` with an autouse fixture that
  swaps `pytdd.pricing.apply_discount` (the verifier-6 reproduction as the reviewer wrote it)
- **WHEN** step 1 runs
- **THEN** the content scan SHALL fail with `tests/conftest.py: patches pytdd.pricing.apply_discount.__code__, which the
  unit changed, for every test`, and the ladder SHALL stop before step 2

#### Scenario: SCN-VER-125 (+) A fixture a test requests by name is listed
- **GIVEN** the same unit with `tests/conftest.py` holding a plain `@pytest.fixture` that monkeypatches
  `pytdd.pricing.apply_discount`, which no autouse fixture requests
- **WHEN** step 1 runs
- **THEN** it SHALL raise no finding and list `tests/conftest.py: patches pytdd.pricing.apply_discount in a fixture a
  test requests` under `Fixtures that patch the unit's code when a test requests them`; module-level code, a fixture
  an autouse fixture requests and a plain function SHALL block like an autouse fixture

### Requirement: L4-VER-038 Step 1 runs the base's tests on the unit's code
Step 1 SHALL run the test gate at head with every test and support file the unit added or changed at its base version
and SHALL require each test that passed at the base to pass. One that fails twice, does not run or no longer collects
SHALL be a blocker, unless `tests.superseded` names it. A support file only people changed, a `[test-infra]` task
changed or a `task.unfrozen` frees SHALL stay at head for the run, listed.

#### Scenario: SCN-VER-126 (−) A `__code__` swap in the test file fails the run alone
- **GIVEN** the red of the B1 reproduction that appends `test_total_adds_prices.__code__ = (lambda: None).__code__` to
  `tests/test_pricing.py`, a green that makes `total()` return `999.0`, and both text signals bypassed (the red check of
  L4-IMP-048 and step 1's `pre-existing tests` row)
- **WHEN** the unit is verified
- **THEN** step 1 SHALL fail with `a pre-existing test fails on the unit's code` naming
  `tests.test_pricing::test_total_adds_prices`, and the verdict SHALL be FAIL

#### Scenario: SCN-VER-127 (−) A weakened helper module under `tests/` fails step 1
- **GIVEN** a base whose `tests/test_pricing.py` calls `assert_total` from `tests/checks.py`, a red that makes
  `assert_total` return without asserting, and a green that breaks `total()`
- **WHEN** the unit is verified
- **THEN** step 1 SHALL fail with `a pre-existing test fails on the unit's code` naming
  `tests.test_pricing::test_total_adds_prices`, and the content scan SHALL have read `tests/checks.py`

#### Scenario: SCN-VER-128 (−) A weakened conftest fixture fails step 1
- **GIVEN** a base fixture `check_total` in `tests/conftest.py` that `test_total_adds_prices` requests, a red that makes
  it return a check that asserts nothing, and a green that breaks `total()`
- **WHEN** the unit is verified
- **THEN** step 1 SHALL fail with `a pre-existing test fails on the unit's code` and the verdict SHALL be FAIL

#### Scenario: SCN-VER-131 (−) A production module that imports only with the unit's conftest fails step 1
- **GIVEN** the handshake reproduction (the unit's conftest sets `PYTDD_SUPPORT`, the green module reads it at import)
- **WHEN** the unit is verified
- **THEN** step 1 SHALL fail with `a pre-existing test no longer runs on the unit's code` naming
  `tests/test_pricing.py` and the `KeyError`, and the ladder SHALL stop before step 2

#### Scenario: SCN-VER-137 (−) A weakened Go or TypeScript test fails step 1
- **GIVEN** a base with `cart/cart_test.go` and `web/cart.test.ts` that check `3.75`, a test command that writes a
  JUnit report for both, and a harness red commit that weakens both
- **WHEN** step 1 runs
- **THEN** the run SHALL fail both tests with `a pre-existing test fails on the unit's code`, and the row `pre-existing
  tests` SHALL say `no Python test file changed; 2 other test file(s) are checked by the run of pre-existing tests`

#### Scenario: SCN-VER-138 (+) An honest unit passes, and allowed or people's files are listed
- **GIVEN** an honest unit that adds tests and a conftest fixture; four base tests that fail with the base versions of
  their files because of a `tests.superseded` event, a `task.unfrozen`, a `[test-infra]` task and a person's commit; and
  a base test parametrised over production data whose case `[OLD]` the unit's data replaced with `[NEW]`
- **WHEN** step 1 runs, with a `[test-infra]` task having changed `tests/conftest.py` and a person having changed
  `tests/fixtures/expected.json`
- **THEN** it SHALL raise no finding for the four, list them with their reasons, and record `verify.base_tests` with the
  counts; the vanished case `[OLD]` SHALL be the blocker `a pre-existing test no longer runs on the unit's code` unless
  a `tests.superseded` event names it, and then it SHALL be listed too; the two support files SHALL stay at head for the
  run and be listed, and only the other changed test files SHALL be reverted

#### Scenario: SCN-VER-139 (+) The base reference is reused, and a flaky test is a minor finding
- **GIVEN** a round whose run with the base files has one failure that passes on the repeat, and an earlier round's
  stored result (`integrity.base_tests` of its `verdict.json`) for the same base sha and command
- **WHEN** step 1 runs
- **THEN** no merge-base worktree SHALL be made (`base_source: "evidence"`), the test SHALL be the minor finding `a
  pre-existing test is flaky on the unit's code`, and the row SHALL be `ok`

### Requirement: L4-VER-039 The content scan reads helper modules and flags test-call replacement
Step 1's content scan SHALL read a changed Python file of `tdd.test_globs` that defines no test as a support file, and
flag in support files a `pytest_pyfunc_call` hook, a non-wrapper `pytest_runtest_call` or `pytest_runtest_setup`, and an
assignment to `.obj` or `.runtest`. A production-diff line naming `.l4-out`, a report path, `L4_*` or `PYTEST_*`
SHALL be a blocker; a test for pytest in production code SHALL be listed for the judge.

#### Scenario: SCN-VER-129 (−) Hooks that replace a test's call are content-scan hits
- **GIVEN** changed support files holding a `pytest_pyfunc_call` that returns `True`, a plain `pytest_runtest_call`, a
  plain `pytest_runtest_setup`, `item.obj = lambda: None` in `pytest_collection_modifyitems`, and `item.runtest = …`;
  and a `tests/checks.py` with no test that holds a `pytest_runtest_setup`
- **WHEN** the content scan runs
- **THEN** each SHALL be a hit of the blocker `a construct that can change what the tests report`, and a wrapper
  `pytest_runtest_call` already flagged SHALL keep its text

- **GIVEN** also a production file that tests `PYTEST_ADDOPTS` to return the right answer only while the base-tests run
  is going, and one that rewrites `.l4-out/junit.xml` from an `atexit` hook
- **WHEN** the content scan runs
- **THEN** each SHALL be the blocker `production code reacts to the test run` naming `file:line`, and the unit SHALL end
  FAIL at step 1; a production line with `import pytest` SHALL only be listed

#### Scenario: SCN-VER-130 (−) A conftest hook that neuters a pre-existing test fails the run alone
- **GIVEN** the B2 reproductions: a red that adds a `tests/conftest.py` with `pytest_pyfunc_call` returning `True` for
  `test_total_adds_prices`, or with `pytest_collection_modifyitems` setting its `item.obj`, a green that breaks
  `total()`, and step 1's `content scan` row bypassed
- **WHEN** the unit is verified
- **THEN** step 1 SHALL fail in the run of L4-VER-038 (the conftest is set aside), and the verdict SHALL be FAIL

## MODIFIED Requirements

### Requirement: L4-VER-002 Ladder
Steps run in order; a hard failure in steps 0–3 stops the ladder with `FAIL` (evidence collected so far is still
written). Each step is resumable (L4-VER-011). In the step table of docs/SPEC.md §10.2 the cells below SHALL read as
given here, and every other cell stays as it is.

Row 1 (integrity), the pre-existing-tests clause: "no pre-existing test deleted, skipped, changed or bound again by a
harness commit, and no test an earlier step of the unit wrote changed by a later red commit, compared per test on the AST
by file and qualified name (L4-VER-030..032; people's changes and allowed ones are listed); and **every test that passed
at the base still passes on the unit's code** when the gate runs at head with every test and support file the unit added
or changed at its base version (L4-VER-038; any language with a JUnit report)".

Row 1, the content-scan clause on support files: "the rule is checked for opened files (L4-IMP-016) and for every
changed Python test-support file, a test-glob file with no test included (L4-VER-037, L4-VER-039), and stays [U] for
other languages"; and its list of result-manipulating constructs gains `pytest_pyfunc_call`, a non-wrapper
`pytest_runtest_call` or `pytest_runtest_setup`, and an assignment to `.obj` or `.runtest` (L4-VER-039).

Row 4a, the last sentence: "Audit tests, and their zero-value run, run with every test and support file the unit added,
changed or deleted at its base version (added data under `fixtures/`, `mocks/`, `__mocks__/`, `testdata/` excepted),
collecting only the audit file when the gate is pytest (L4-VER-033); they never run with the unit's files in place; an
audit test whose import fails in a production module, or that gives no readable result, holds its criterion, and one
whose own import fails twice is rejected (L4-VER-034); each record says `support` (L4-VER-036)".

Row 5: after "**pass on head**" add "(the head run with the e2e runner's own support files the unit changed at their base
versions, never added app data; when it cannot run that way or its server does not start, uncollectable and held, never
run in place, L4-VER-035)".

#### Scenario: SCN-VER-121 (−) The weakened pre-existing test of the verifier-2 reproduction fails step 1
- **GIVEN** a unit branch whose harness red commit rewrote `assert total([1.25, 2.5]) == 3.75` to `is not None`
- **WHEN** the ladder runs
- **THEN** step 1 SHALL be `failed` with `a pre-existing test was changed`, and the ladder SHALL stop with FAIL before
  step 2
