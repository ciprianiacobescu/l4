## ADDED Requirements

### Requirement: L4-IMP-045 A pre-existing test is compared per test on the AST
The harness SHALL identify a Python test by its file and qualified name (`test_x`, or `Class.test_x` for a method a
module-level class defines or inherits from a class of the same file), never by bare name. Its definition SHALL be every
statement binding the name in its defining scope, dumped without positions, docstrings normalised, so decorators,
parametrisation, requested fixtures and body count and layout does not. A second binding SHALL be a change.

#### Scenario: SCN-IMP-260 (−) A weakened assertion is a changed test
- **GIVEN** `tests/test_pricing.py` at the step's base with `assert total([1.25, 2.5]) == 3.75` in
  `test_total_adds_prices`, and a red step that rewrites it to `assert True`
- **WHEN** the comparison runs
- **THEN** it SHALL report `tests/test_pricing.py::test_total_adds_prices` as `changed` with `its body, decorators or
  parametrisation changed`

#### Scenario: SCN-IMP-261 (−) A second definition of a pre-existing test is a rebinding
- **GIVEN** the base file of SCN-IMP-260, unchanged, followed by `def test_total_adds_prices(): pass`
- **WHEN** the comparison runs
- **THEN** it SHALL report the test as `rebound` with `its name is bound again at line <n>, which replaces it`

#### Scenario: SCN-IMP-262 (−) An assignment or an import that rebinds a test name is a rebinding
- **GIVEN** the base file followed by `test_total_adds_prices = lambda: None`, or by
  `from helpers import test_total_adds_prices`
- **WHEN** the comparison runs
- **THEN** it SHALL report the test as `rebound` in both cases

#### Scenario: SCN-IMP-263 (−) A changed parametrisation, mark or requested fixture is a change
- **GIVEN** a pre-existing test whose `@pytest.mark.parametrize` list loses a case, one that gains a decorator, and one
  whose parameter (a fixture it requests) is renamed
- **WHEN** the comparison runs
- **THEN** each SHALL be reported as `changed`

#### Scenario: SCN-IMP-266 (+) New tests, a widened import, locals and a re-indented docstring change nothing
- **GIVEN** a red step that appends two new tests to a pre-existing test file, changes `from pytdd import total` to
  `from pytdd import apply_discount, total`, adds a second `import pytest`, edits a comment, re-indents a docstring
  (equal after `inspect.cleandoc` and right-stripping), adds a module constant `p` and a fixture `code` while an old test
  uses `p` as a generator variable and `code` as a lambda parameter, and adds a trailing newline
- **WHEN** the comparison runs
- **THEN** it SHALL report nothing for the file

#### Scenario: SCN-IMP-268 (−) A file that no longer parses changes every test in it
- **GIVEN** a pre-existing test file that a step leaves with a syntax error
- **WHEN** the comparison runs
- **THEN** every test of the base file SHALL be reported as `unparsable` with `the file does not parse`

#### Scenario: SCN-IMP-279 (−) A subclass that overrides an inherited test changes it
- **GIVEN** `TestBase.test_x` asserting `sum([1, 2]) == 3` and `class TestChild(TestBase): pass`, and a step that gives
  `TestChild` its own `def test_x(self): pass`
- **WHEN** the comparison runs
- **THEN** `TestChild.test_x` SHALL be reported as `changed`, and a subclass that keeps inheriting it SHALL change
  nothing

### Requirement: L4-IMP-046 What a test uses in its own file is part of it
The comparison SHALL include every binding of the file a pre-existing test reaches: the module names it reads (a local,
a nested parameter or a comprehension variable is none), the fixtures it requests or names in `usefixtures`,
transitively; every autouse fixture, `pytestmark`, module setup and `pytest_*` name; for a method, its class's
decorators, bases and non-test members. An import SHALL count as its source, so a widened import line is no change.

#### Scenario: SCN-IMP-264 (−) A helper, a constant or a fixture the test uses in its file is part of it
- **GIVEN** a pre-existing test that calls the helper `_check` and compares with the constant `EXPECTED`, and a step that
  makes `_check` return without asserting, or sets `EXPECTED` to another value
- **WHEN** the comparison runs
- **THEN** the test SHALL be reported as `changed` with `what it uses in this file changed: _check` (or `EXPECTED`)

#### Scenario: SCN-IMP-265 (−) A new autouse fixture or module mark reaches every test of the file
- **GIVEN** a step that appends an autouse fixture, or a `pytestmark` assignment, to a pre-existing test file
- **WHEN** the comparison runs
- **THEN** every pre-existing test of the file SHALL be reported as `changed`, naming the fixture or `pytestmark`

#### Scenario: SCN-IMP-267 (−) A method's class is part of it
- **GIVEN** a pre-existing `TestCart.test_empty`, and a step that changes `TestCart.setup_method`, or adds a class
  decorator, but not the method
- **WHEN** the comparison runs
- **THEN** `TestCart.test_empty` SHALL be reported as `changed`; a new test method added to `TestCart` SHALL change
  nothing

### Requirement: L4-IMP-047 A moved test is the same definition in a new place
A test gone from its file SHALL count as moved only when a test that did not exist under that file and name before has
the same definition and the same closure (L4-IMP-046) at the later revision in a changed file; each such test SHALL
stand for at most one gone test. Every other gone test SHALL be deleted.

#### Scenario: SCN-IMP-269 (+) A test moved unchanged to another file is moved
- **GIVEN** `test_one` deleted from `tests/test_a.py` and the same definition added to the new `tests/test_b.py`
- **WHEN** the comparison and the move rule run
- **THEN** `tests/test_a.py::test_one` SHALL be moved, not deleted

#### Scenario: SCN-IMP-270 (−) A same-named test with another body, or with a weakened helper, is no move
- **GIVEN** `test_empty` (`assert compute([]) == 0`) deleted from `tests/test_cart.py`, and `def test_empty(): assert
  True` appended to the changed `tests/test_orders.py`; or `test_one` moved unchanged from `tests/test_a.py` to
  `tests/test_b.py` next to a `_check` helper that no longer asserts
- **WHEN** the move rule runs
- **THEN** `tests/test_cart.py::test_empty` and `tests/test_a.py::test_one` SHALL be deleted

### Requirement: L4-IMP-049 A statement that is not a plain definition reaches every test of its scope
Each top-level statement of a test file that is not a plain definition (`guards._defines_only`, where a fixture that is
not autouse also counts as plain) SHALL be a part of the pseudo-name `<module>`, which every test of the file reaches;
each such statement of a class body SHALL be a part of `<Class>`, which every test of the class reaches. An attribute,
`globals()` or `vars()` assignment, a `setattr` call or a class attribute that replaces a test SHALL be a change.

#### Scenario: SCN-IMP-278 (−) A statement that replaces a test without binding its name is a change
- **GIVEN** the base `tests/test_pricing.py` followed by one of `test_total_adds_prices.__code__ = (lambda:
  None).__code__`, `globals()["test_total_adds_prices"] = lambda: None`, `vars()[…] = …`,
  `setattr(sys.modules[__name__], "test_total_adds_prices", lambda: None)` or `test_total_adds_prices.pytestmark =
  [pytest.mark.skip]`; and a `TestCart` file followed by `TestCart.test_empty = lambda self: None`
- **WHEN** the comparison runs, and when a red step makes the first of these changes
- **THEN** every pre-existing test of the file SHALL be reported as `changed` with `what it uses in this file changed:
  <module>`, and the red attempt SHALL fail naming `test_total_adds_prices`

### Requirement: L4-IMP-048 A red step may not change a test that existed before it
After `classify_red` accepts a red step, the harness SHALL compare every test that existed at the step's base in each
test file the step changed (L4-IMP-045..047). A changed, rebound, unparsable or deleted one SHALL fail the attempt with
`guard.test_tamper{phase: "red", rule: "pre-existing test", action: "rejected"}`, nothing committed, and a reason and
excerpt that name each test and say what to do. A `[test-infra]` task and the task's stale tests SHALL be exempt.

#### Scenario: SCN-IMP-271 (+) A reopened task's red may replace its stale test
- **GIVEN** a reopened task whose stale tests (L4-OPS-015) include `tests/test_long.py::test_long`, and a red step that
  rewrites that test for the new criterion text
- **WHEN** the red check runs
- **THEN** the attempt SHALL not fail for that test, and a change to another pre-existing test of the same file SHALL
  still fail it

#### Scenario: SCN-IMP-272 (+) A `[test-infra]` task's red may change existing tests
- **GIVEN** a task titled `2.1 [test-infra] Share the cart fixture` whose red step changes two pre-existing tests
- **WHEN** the red check runs
- **THEN** no `guard.test_tamper` with `rule: "pre-existing test"` SHALL be recorded and the step goes on

#### Scenario: SCN-IMP-273 (−) A later task's red may not change an earlier task's red test
- **GIVEN** task 1.1 committed with its red test `tests/test_discount.py::test_known_code`, and the red step of task 1.2
  that weakens it
- **WHEN** the red check runs
- **THEN** the attempt SHALL fail naming `tests/test_discount.py::test_known_code`

#### Scenario: SCN-IMP-274 (+) The weakened test never reaches the branch and the honest retry passes
- **GIVEN** the bench of the verifier-2 reproduction whose first red attempt also weakens
  `tests/test_pricing.py::test_total_adds_prices`, and a second, honest red attempt
- **WHEN** the unit runs through `l4 run`
- **THEN** the first attempt SHALL fail with `red changed tests that existed before this step:
  tests/test_pricing.py::test_total_adds_prices`, the second attempt's prompt SHALL carry that reason and the advice,
  and the unit SHALL pass with `tests/test_pricing.py` equal to its base content

#### Scenario: SCN-IMP-275 (+) A red that breaks an existing test keeps today's reason
- **GIVEN** a red step that rewrites `test_total_adds_prices` to `assert False`
- **WHEN** red runs
- **THEN** the reason SHALL still start with `red broke existing tests: tests.test_pricing::test_total_adds_prices`,
  with the failure excerpt

## MODIFIED Requirements

### Requirement: L4-IMP-006 Post-step guards
After each agent step the harness MUST: (1) revert protected-path changes (P4, `odd.forbidden_paths` and the contract
list, which includes the whole spec root `openspec/**` and `.kiro/specs/**` except the run's own ledger, so a criterion
an agent copied into the archived specs or a sibling change never stays) and record `guard.violation`; (2) compare every
test that existed before the step with its state after it (L4-IMP-045..047): in red, a test changed, bound again,
unparsable or deleted, or a fixture, helper, constant or mark it uses in its file changed, fails the attempt with
`guard.test_tamper{phase: "red", rule: "pre-existing test", action: "rejected"}` (L4-IMP-048); green and a fix chore keep
the test-path freeze (7), a test chore keeps `appended_only`, and the verifier checks the comparison on the commits
(L4-VER-030..032); an added skip marker (`.skip`/`xit`/`@pytest.mark.skip`/`t.Skip`) stays a step-1 blocker; (3) revert
changes to gate configuration — files matching `tdd.gate_config_globs` and the gate sections of manifests (pyproject
`[tool.mypy*]`/`[tool.ruff*]`/`[tool.pylint*]`, package.json `eslintConfig`) — unless the task carries a human-written
`[config]` or `[test-infra]` tag; (4) run the redaction filter over every file the harness itself writes; (5) detect test
tamper per test on the AST, by file and qualified name, never by bare name: every binding of the test's name with its
decorators, parametrisation and requested fixtures, what it uses in its own file, and every statement of its file or class that is not a plain definition (L4-IMP-045,
L4-IMP-046, L4-IMP-049); comments,
layout and a trailing newline are not tamper [V, spikes/02]; other languages are not compared [U]; (6) treat adapter
permission rules as no freeze: shell redirects write files under `Edit(./**)` [V, spikes/01], so the hash freeze and
revert are mandatory for every adapter; (7) **test-path freeze:** a step that may not write tests, `green` (`L4-TDD:
green`) and a fix chore of kind `fix` (`L4-TDD: exempt`), may not add, change, delete or rename any path that matches
`tdd.test_globs` or `tdd.test_support_globs` (both include their `extra_*` lists), whatever the language: after the step
the harness puts each such path back (a changed or deleted file is restored from the step's base, a new one removed) and
records one `guard.test_tamper` with `rule: "test path freeze"` and `action` `restored` or `removed`, which the next
attempt's prompt carries. Three exceptions: the paths a `task.unfrozen` event names for that unit and task (a human answer
freed them, L4-IMP-002, or the task's own reviewed text named them, L4-IMP-014); the files a test chore (`kind=tests`)
keeps (`task.tests_added.files`), whose own review is unchanged; and every path of a task whose title carries the human
`[test-infra]` tag. The steps that write tests stay free: `red`, `already-satisfied` and the test chore, within (2). The
`[test-infra]` tag lifts this freeze only; it does not lift the red-to-green freeze of L4-IMP-002. The verifier checks
the same rule on the commits (§10.2 step 1). `--disallowedTools "Edit(./tests/**)"` in green MAY be added as defence in
depth [I]. The paragraphs of L4-IMP-006 that follow in docs/SPEC.md (the run ledger's restore and the guard notes of the
next attempt) are unchanged, except that a `guard.test_tamper` with `action: "rejected"` is not a guard note: the failed
attempt's reason and excerpt already carry it.

#### Scenario: SCN-IMP-276 (−) A weakened assertion fails the red attempt
- **GIVEN** the red step of the implementer-4 reproduction that writes the new `tests/test_discount.py` and the stub, and
  rewrites the pre-existing `assert total([1.25, 2.5]) == 3.75` to `assert True`
- **WHEN** `run_red` runs
- **THEN** the outcome SHALL be `failed`, one `guard.test_tamper{phase: "red", path: "tests/test_pricing.py", rule:
  "pre-existing test", action: "rejected", tests: ["test_total_adds_prices"]}` SHALL be recorded, and no red commit
  SHALL be made

#### Scenario: SCN-IMP-277 (−) A rebinding fails the red attempt
- **GIVEN** the rebound form of the implementer-4 reproduction (`def test_total_adds_prices(): pass` appended)
- **WHEN** `run_red` runs
- **THEN** the outcome SHALL be `failed` with `its name is bound again` in the reason, and no red commit SHALL be made
