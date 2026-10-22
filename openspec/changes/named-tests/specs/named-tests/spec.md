## Purpose

When the reviewed text of a task names an existing test that has to change, the red step changes it in place instead
of a person being asked; a helper module red stubbed for the task can be finished by green; a vacuous red attempt is
told what to stub; and the clarifier does not suggest an answer the signature or the requirement rules out.

## ADDED Requirements

### Requirement: L4-IMP-082 Red changes in place the existing tests the reviewed text names
A red step SHALL be allowed to change the body, decorators or parametrisation of a Python test that existed at its base
when the task's reviewed text (`named_task_text`) or the text of a criterion the task cites explicitly (its
`_Requirements:_` line) names it, by
`<path>::<name>` (or `<path>::<Class>::<name>`) or by a test name that exactly one test file at the base defines. A
criterion's text counts only when the source is an activated plan's digest or the unit folder is the same on the base
branch. At most 5 tests SHALL be named per task. A named test MUST NOT be deleted, bound again or left unparsable by red
(the step is rejected as today). The red prompt SHALL list the named tests under `# Existing tests this task changes in
place`. When the attempt is accepted, the harness SHALL record the named tests red changed as `tests.superseded` with
`reason: "named_by_task"` and the source, and the verifier SHALL allow and list them as it does stale tests; a named
test an earlier red step added stays among the tests the verifier expects. Every other existing test MUST stay
protected. The red template's version SHALL be 13.

#### Scenario: SCN-IMP-400 (+) A task that names an existing test changes it in red without a question
- **GIVEN** an activated plan's unit whose task text says ``update `tests/test_registry.py::test_registry_lists_all`
  with the two new tools``, and that test exists at the base
- **WHEN** the red step changes that test's expected set and adds new failing tests for the criteria
- **THEN** the attempt is accepted; the prompt listed `tests/test_registry.py::test_registry_lists_all` under
  `# Existing tests this task changes in place`; the ledger has `tests.superseded` with `tests:
  ["tests.test_registry::test_registry_lists_all"]`, `reason: "named_by_task"` and `source: "plan:<id>@<digest>"`;
  and the integrity check allows and lists the change

#### Scenario: SCN-IMP-401 (+) A criterion's text names the test by its name alone
- **GIVEN** a task citing criterion R1.2 whose text says the guard tests `test_read_guard_a` and
  `test_read_guard_b` are rewritten in place and none is deleted; each name is defined in one test file
- **WHEN** red rewrites both in place
- **THEN** the attempt is accepted and both are recorded as `tests.superseded` with `reason: "named_by_task"`

#### Scenario: SCN-IMP-402 (−) A named test may not be deleted, and an unnamed one stays protected
- **GIVEN** the task of SCN-IMP-400
- **WHEN** red deletes `test_registry_lists_all`, and in turn changes `tests/test_registry.py::test_other` that no
  text names
- **THEN** each attempt is rejected with `red changed tests that existed before this step` naming the test, and
  nothing is recorded as superseded

#### Scenario: SCN-IMP-403 (−) An ambiguous or unreviewed name opens nothing
- **GIVEN** a task text that names `test_roundtrip`, which two test files define; and in turn a fix unit (no reviewed
  text) whose text names `tests/test_a.py::test_x`
- **WHEN** the named tests are computed
- **THEN** the first opens nothing and is kept with `named in 2 test files: write <path>::test_roundtrip`; the second
  names nothing; and the red prompt has no `# Existing tests this task changes in place` section

#### Scenario: SCN-IMP-404 (−) At most five tests are named
- **GIVEN** a task text that names seven existing tests by node id
- **WHEN** the named tests are computed
- **THEN** the first five in path and name order are named and the other two are kept with
  `more than 5 existing tests named`

### Requirement: L4-IMP-083 A helper red creates and the task line names is finished by green
A Python file that the red step added, that the task's reviewed text names and that defines no test SHALL be opened for
that task's green with reason `named_by_task`. Green MAY change its bodies; every module-level function and class red
wrote MUST stay defined with the same kind and, for a function, the same parameters, and the file MUST NOT gain a test
or monkeypatch the unit's modules. A file that breaks a rule SHALL be put back to its red version and recorded as
`guard.violation{rule: "opened file"}` with `drops <name>`, `changes the signature of <name>`, `adds a test <name>` or
the monkeypatch text.

#### Scenario: SCN-IMP-405 (+) Green fills in a helper red stubbed
- **GIVEN** a task line that names `tests/fakes_store.py`, and a red step that added it with signature-only stubs and no
  test, and red tests that use it
- **WHEN** green implements the stub bodies
- **THEN** the file is opened (`task.unfrozen` with `reason: "named_by_task"`), its changes are kept, and the task
  completes

#### Scenario: SCN-IMP-406 (−) Green may not change the helper's interface or add a test to it
- **GIVEN** the helper of SCN-IMP-405
- **WHEN** green renames one of its functions, and in turn adds `def test_fake():` to it
- **THEN** the file is put back to its red version with `guard.violation{rule: "opened file"}` and `drops <name>`,
  respectively `adds a test test_fake`

#### Scenario: SCN-IMP-407 (−) A red file with tests, or a changed file, stays frozen
- **GIVEN** a task line that names `tests/test_new.py`, which red added with tests, and `tests/helpers.py`, which
  existed at the base and red changed
- **WHEN** the files green may change are computed
- **THEN** neither is opened: `a red test of this task`, respectively the existing reason

### Requirement: L4-IMP-084 The zero-value run zeroes the stubs HEAD holds with red's own
When a red step has open criteria, its zero-value run SHALL zero both the stubs red added and the modules the tests
import that hold a `raise NotImplementedError` stub at HEAD.

#### Scenario: SCN-IMP-408 (+) An earlier task's stub is zeroed although red added its own
- **GIVEN** a module `copy.py` whose function `copy_rows` is only `raise NotImplementedError("arrives in a later task")`
  from an earlier task, and a red step that adds a stub in `rules.py` and tests that call both
- **WHEN** the zero-value run is made
- **THEN** both `rules.py` and `copy.py` are zeroed, and a test that asserts on `copy_rows`'s answer fails by
  assertion, so the criterion is proved

### Requirement: L4-IMP-085 A vacuous criterion whose tests only error is told what to stub
For a vacuous criterion all of whose tests errored in the zero-value run, the red failure text SHALL name the error and
the remedy instead of the generic sentence: a module the tests cannot import (`create it in this red step with
signature-only stubs …`), a `NotImplementedError` raised at a worktree file and line (`… make it one (only raise
NotImplementedError) or stub what the tests call in this red step`), or an `AttributeError` for a missing attribute
(`add <a> as a signature-only stub in this red step`). Other errors SHALL keep the current text.

#### Scenario: SCN-IMP-409 (−) A missing helper module is named
- **GIVEN** a red step whose tests import `tests.fakes_store`, which does not exist, and error in the zero-value run
- **WHEN** the attempt is judged
- **THEN** it fails with `its tests cannot import tests.fakes_store: create it in this red step with signature-only stubs
  (a body that is only raise NotImplementedError), and the harness answers them with zero values`

#### Scenario: SCN-IMP-410 (−) A NotImplementedError from project code is named with its place
- **GIVEN** a red step whose tests stop with `NotImplementedError` raised at `src/app/copy.py:40` in the zero-value
  run
- **WHEN** the attempt is judged
- **THEN** the failure names `src/app/copy.py:40` and the remedy of L4-IMP-085

### Requirement: L4-CLR-007 The clarifier reads signatures and keep-rules before it suggests an answer
The clarifier's system text SHALL tell it to read a function's signature before suggesting a call (keyword arguments
after a defaulted parameter, no assumed positional order, say so when no excerpt shows the signature) and never to
suggest deleting, skipping or renaming an item the specification says is kept, not deleted or rewritten in place. Its
excerpts SHALL include the definition line of up to three functions the question calls, when found. Its prompt version
SHALL be 6.

#### Scenario: SCN-CLR-001 (+) The clarifier's prompt carries the rules and the signature
- **GIVEN** a question that says `the test calls list_items(store, tenant_id)` and a repository where
  `def list_items(store, limit=50, tenant_id=None):` is defined in `src/app/items.py`
- **WHEN** the clarifier's prompt is built
- **THEN** its system text holds both rules, its excerpts include `src/app/items.py` from the `def list_items(` line,
  and its version is 6
