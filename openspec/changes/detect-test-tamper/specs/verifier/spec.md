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

### Requirement: L4-VER-033 Audit tests run with the unit's support files at the base
Step 4a SHALL run each audit test, and the zero-value run that judges it, with every test-support file
(`tdd.test_support_globs`) the unit added, changed or deleted put at its base version (an added one set aside), and
SHALL restore each byte for byte afterwards, also after an error. The run SHALL go on past a collection error of another
file. Runner configuration files SHALL not be reverted. With no support change the run is as before.

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
  collection error

#### Scenario: SCN-VER-118 (+) The zero-value run uses the same support files as the head run
- **GIVEN** an audit test that passes at head with the support files at the base
- **WHEN** its zero-value confirmation runs
- **THEN** that run SHALL also have the support files at the base

### Requirement: L4-VER-034 An audit test that does not run at the base support falls back only after a clean scan
An audit test that has no test in the run of L4-VER-033, a test with a setup error, or a collection error of its own
SHALL be run again with the unit's support files in place only when step 1's `content scan` check is `ok`, recorded
`support: "head"`. Otherwise it SHALL be rejected as a minor finding whose reason names the cause and the scan's note.

#### Scenario: SCN-VER-116 (+) An audit test that needs the unit's fixture falls back after a clean scan
- **GIVEN** an audit test that requests a fixture only the unit's `tests/conftest.py` defines, and a step-1 content scan
  with status `ok`
- **WHEN** step 4a runs
- **THEN** the test SHALL be judged from a second run with the support files in place, recorded `support: "head"`

#### Scenario: SCN-VER-117 (−) No fallback when step 1 could not read the support files
- **GIVEN** the audit test of SCN-VER-116 and a step-1 content scan with status `skipped` because the unit changed a
  `tests/helpers/setup.ts` it cannot read
- **WHEN** step 4a runs
- **THEN** the test SHALL be rejected with a minor finding `an audit test was rejected` whose reason starts with `it does
  not run with the unit's support files at the base` and names the scan's note

### Requirement: L4-VER-035 A generated UI test's head run follows the same rule
Step 5 SHALL run a generated UI test at head with the unit's changed support files at their base versions (L4-VER-033),
fall back to them in place only as L4-VER-034 says, and else record the test `uncollectable` with that reason. The run
at the merge base SHALL be unchanged, and `verify.generated` SHALL carry `support`.

#### Scenario: SCN-VER-119 (−) A generated UI test's head run uses the base support files
- **GIVEN** a UI unit that added `e2e/conftest.py` with an autouse fixture that makes every page check pass, and a
  generated test that fails at head without it
- **WHEN** step 5 judges the test
- **THEN** the head run SHALL have `e2e/conftest.py` set aside, the outcome SHALL be `fails_at_head` with
  `support: "base"`, and the file SHALL be back after the run

#### Scenario: SCN-VER-122 (+) An honest UI unit's generated test is accepted with the base support files
- **GIVEN** a UI unit that added a harmless `e2e/conftest.py`, and a generated test that fails at the merge base and
  passes at head without it
- **WHEN** step 5 judges the test
- **THEN** the outcome SHALL be `accepted` with `support: "base"`

### Requirement: L4-VER-036 A person sees how each verifier test ran
`verify.audit` SHALL carry `support` (`base`, `head` or `unchanged`) and `support_files`, and verification.md's Audit
table SHALL show a `Support` column. verification.md SHALL list the pre-existing test changes that L4-VER-031 allowed
under `## Pre-existing tests changed with an allowance (L4-VER-031)` and the fixtures of L4-VER-037 that patch the
unit's code on request.

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

## MODIFIED Requirements

### Requirement: L4-VER-002 Ladder
Steps run in order; a hard failure in steps 0–3 stops the ladder with `FAIL` (evidence collected so far is still
written). Each step is resumable (L4-VER-011). In the step table of docs/SPEC.md §10.2 three cells change (and one clause of row 1's content scan, below) and every
other cell stays as it is. Row 1 (integrity): the clause "no deleted/skipped/weakened pre-existing tests (diff
analysis)" SHALL read "no pre-existing test deleted, skipped, changed or bound again by a harness commit, and no test an
earlier step of the unit wrote changed by a later red commit, compared per test on the AST by file and qualified name
(L4-VER-030..032; people's changes and allowed ones are listed)". Row 1, content scan: "the rule is checked for opened files (L4-IMP-016) and stays [U] for other support changes" SHALL read
"the rule is checked for opened files (L4-IMP-016) and for every changed Python test-support file (L4-VER-037) and stays
[U] for other languages". Row 4a: the sentence "Audit and generated tests run with
the unit's added or changed support files reverted to their base versions where they still collect; otherwise with them,
provided the step-1 content scan of those files is clean" SHALL read "Audit tests, and their zero-value run, run with the
unit's added, changed or deleted test-support files at their base versions, past other files' collection errors
(L4-VER-033); a test that does not run that way runs with them in place only when step 1's content scan is `ok`, else it
is rejected (L4-VER-034); each record says which (`support`, L4-VER-036)". Row 5: after "**pass on head**" add "(the head
run with the unit's support files at their base versions, L4-VER-035)".

#### Scenario: SCN-VER-121 (−) The weakened pre-existing test of the verifier-2 reproduction fails step 1
- **GIVEN** a unit branch whose harness red commit rewrote `assert total([1.25, 2.5]) == 3.75` to `is not None`
- **WHEN** the ladder runs
- **THEN** step 1 SHALL be `failed` with `a pre-existing test was changed`, and the ladder SHALL stop with FAIL before
  step 2
