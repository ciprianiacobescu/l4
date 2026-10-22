## Context

Read with `proposal.md`. The red step's guard against changing tests that existed before it is
`preexisting_test_changes` (`src/l4/implementer/tdd.py:978`, L4-IMP-048): it compares, per test on the AST
(`tamper.compare`, kinds `changed`, `rebound`, `deleted`, `unparsable`), every test file red changed, and exempts a
`[test-infra]` task and the stale tests of a reopened task (`StaleTests`, L4-OPS-015). A stale test that red replaced is
recorded as `tests.superseded {task, tests, criteria}` (`record_superseded`, `tdd.py:1274`), and the verifier allows a
change to a test that event lists (`integrity._superseded`, `ladder._red_green`, `base_tests`). The reviewed text of a
task is `named_task_text(wb, task)` (`tdd.py:1822`): `(source, block)` with source `plan:<id>@<digest>` (the unit folder
at HEAD has the digest an active plan froze) or `base:<sha10>` (the same block on the fetched base), else None.
`named_by_task` (`unfreeze.py:80`) opens the support files that block names for green, append-only (`opened.py`
rules 1 and 2, plus rule 3, no monkeypatching of the unit's modules).

## Goals / Non-Goals

Goals: the nine questions of the proposal do not happen when the reviewed text names the test; a named helper red
stubbed can be finished by green; a vacuous rejection says what to stub.
Non-goals: no change for a test the text does not name (it stays a person's question); no non-Python tests (the AST
comparison is Python only); no change to green's freeze of red's tests; no new config key.

## Decisions

### D1 Which existing tests the reviewed text names (`src/l4/implementer/named_tests.py`, new)

```python
MAX_NAMED_TESTS = 5

@dataclass(frozen=True)
class NamedTests:
    source: str | None = None                      # the source of named_task_text, None: nothing reviewed
    tests: tuple[tuple[str, str], ...] = ()        # (path, name), name as tamper.facts_of keys it (`Class.test_x` or `test_x`)
    kept: tuple[tuple[str, str], ...] = ()         # (token as written, why it opens nothing)

    def ids(self) -> tuple[str, ...]: ...          # the test ids `module.dotted::function` (names_test_id form)

def named_tests(wb: Workbench, task: Task, base: str) -> NamedTests: ...
def find_named(texts: Sequence[str], files: Mapping[str, str]) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]: ...
```

- Texts: the task's block from `named_task_text`; when it is None, `NamedTests()` (nothing is named). Also the text
  (`alias` and `text`) of each criterion the task cites EXPLICITLY (the ids of its `_Requirements:_` line, or the
  framework's equivalent; a task that cites none adds no criterion text, so an OpenSpec task without such a line uses
  its own block only), and only when the source is `plan:` or the unit folder's digest at HEAD equals its digest on
  `refs/remotes/origin/<base_branch>` (`unit_digest`): a criterion's text is then as reviewed as the task's.
- Files: the regular Python files tracked at `base` (the red step's base commit) that match `tdd.test_globs`, read at
  `base`; their tests are the keys of `tamper.facts_of(text)` whose `Facts.test` is true.
- A test is named by a token of a text, in this order:
  1. `<path>::<name>` or `<path>::<Class>::<name>` (an optional `[...]` parametrisation suffix is ignored), where
     `<path>` is one of the files and the name a test of it;
  2. a bare identifier that is a test's last name part (`test_x`, or `TestX` for a test class), bounded like a word and
     optionally in backticks, defined as a test in exactly one of the files. Defined in two or more files, it names
     none, and is kept with `named in <n> test files: write <path>::<name>`.
  A token that matches nothing is ignored (it is not listed).
- At most `MAX_NAMED_TESTS`, the first ones in (path, name) order; each further one is kept with
  `more than 5 existing tests named`.
- `find_named` is the pure part (texts, `{path: source at base}`); `named_tests` reads git and the provider.

### D2 Red may change the named tests (`tdd.py`)

- `preexisting_test_changes(wb, task, base, stale, named)` takes `NamedTests`: a `Tampered` of kind `changed` whose
  `(path, name)` is one of `named.tests` is exempt. `deleted`, `rebound` and `unparsable` stay rejected for a named test
  too: a named test is changed in place, never removed.
- `classify_red` (`tdd.py:~400-455`) does not count a named test red changed among the existing tests red broke
  (`regressed`): it may fail after red, as a red test does (`red broke existing tests` and the `no new test: existing
  tests were changed and now fail` reason leave it out). A named test is no new test: the criteria still need their new
  tests, and a step whose only change is a named test is still `no new test` unless every cited criterion is
  pre-satisfied as today.
- After green, a named test red changed must pass like every red test (it is in the red commit, so it is frozen for
  green and the green gate holds it to passing).
- After a red attempt is accepted (where `record_superseded` runs), the harness emits, once, for the named tests red
  actually changed (`compare` reported `changed`):
  `tests.superseded {task, tests: [<ids>], criteria: [], reason: "named_by_task", source: <NamedTests.source>}`.
  The stale-test event keeps its current fields and gets `reason: "stale"`. The verifier reads `tests` only, so its
  allowance and listing (`Outcome.allowed_tests`) cover the named tests without other change; the integrity listing
  shows them as `<id> (named by the task text, <source>)` where it lists superseded tests.
- The red prompt (`templates/red.md`, version 13) gets, only when `named.tests` is not empty, a section rendered by
  `prompt.py`:

  ```
  # Existing tests this task changes in place
  The task's text or one of its criteria names these existing tests. Change each one in place so that it asserts what
  the task asks; do not delete or rename one, and still write the new tests the criteria need:
  - <path>::<name>
  ```

  and the rule line in `red.md` that forbids editing an existing test becomes: `Leave every other existing test as it
  is: a test listed under "Existing tests this task changes in place" is the one exception.` `_PREEXISTING_ADVICE`
  (`tdd.py:970`) ends with: `A test that the task's text or a criterion names (path::name) may be changed in place; name
  it there if it must change.`
- Green: a file red changed is already frozen for green (`kind: "test"`, `in_red`), so a named test red rewrote is a red
  test like any other; nothing changes for green.

### D3 A helper red created that the task line names stays open for green (`guards.py`, `unfreeze.py`, `opened.py`)

- `FrozenFile` gains `added: bool = False` (the path is in `git diff --diff-filter=A base red`).
- In `named_by_task`, a manifest file with `kind == "test"` is opened (grant reason `named_by_task`, with
  `helper=True` on the `Grant`, default False) instead of kept when all hold: `in_red` and `added`; it ends in `.py`; it
  is a regular file at the red commit; the task block names it (`names_path(..., dot_slash=True)`); and
  `tamper.facts_of` of its red version finds no test. Otherwise the existing reasons apply (`a red test of this task`).
  It counts against `MAX_PATHS_PER_QUESTION` like the other opened paths.
- The check for such a file after green (`_check_opened`) is `check_filled_helper(before, after, unit_modules=...)` in
  `opened.py` instead of rules 1 and 2: every module-level `def`, `async def` and `class` of `before` is still defined at
  module level in `after`, with the same kind and, for a function, the same parameters (`ast.arguments` names, kinds and
  the number of defaults; annotations and default values may change); `after` defines no test (`facts_of`); and rule 3.
  Texts: `drops <name>`, `changes the signature of <name>`, `adds a test <name>`, then rule 3's text. A failure puts the
  file back and records `guard.violation{rule: "opened file"}` as today.

### D4 The zero-value run zeroes HEAD's stubs too (`tdd.py:1423`)

`zeroed = sorted({*scope.stub_files, *head_stub_modules(wb, tests)})` whenever there are open criteria, where `tests` are
the open criteria's tests (today HEAD's stubs are used only when red added none). `head_stub_modules`' docstring drops
"red added none of its own". `no_assertion_failure` stays the path when both are empty.

### D5 The vacuity remedy names the error (`discrimination.py`)

- `Vacuity` gains `errors: dict[str, str]` (criterion -> the remedy text for it, only for a vacuous criterion all of
  whose tests ERRORED in the zero-value run, none failed by assertion and none passed).
- The error of a test is read from the zero run's report (the JUnit `error`/`failure` message and text the gate kept).
  The first matching rule gives the remedy:
  1. `ModuleNotFoundError: No module named '<m>'` or `ImportError: cannot import name '<n>' from '<m>'`, where `<m>`
     resolves to a path inside the worktree (or would: its first part is a package directory of the worktree):
     `its tests cannot import <m>: create it in this red step with signature-only stubs (a body that is only
     raise NotImplementedError), and the harness answers them with zero values`.
  2. `NotImplementedError` raised from a file of the worktree: `its tests stop with NotImplementedError at
     <path>:<line>: that body is not a stub the zero-value run answers; make it one (only raise NotImplementedError)
     or stub what the tests call in this red step`.
  3. `AttributeError: ... has no attribute '<a>'`: `its tests stop with AttributeError (<a>): add <a> as a
     signature-only stub in this red step`.
  Other errors keep today's text.
- `Vacuity.message` puts the remedy for such a criterion in place of the generic "a test must fail by assertion on the
  answer (...)" sentence; the zero-answer remedy (`_zero_answer_remedy`) is not added for it.

### D6 The clarifier reads signatures and keep-rules (`src/l4/clarifier/context.py`)

- `SYSTEM` gains two rules, after the `kind:` rule:
  - `- Before you suggest a call, read the function's signature in the excerpts: pass by keyword every argument that
    follows a parameter with a default, and never assume a positional order the excerpt does not show. If no excerpt
    shows the signature, say so instead of guessing.`
  - `- When the specification says that tests or other items are kept, are not deleted, or are rewritten in place,
    never suggest deleting, skipping or renaming one: suggest the change in place.`
- The excerpts: for each name the question calls (`<name>(` in its text, at most 3 names, identifiers of at least 4
  characters), the first definition `def <name>(` / `async def <name>(` found by `git grep -n -E` in tracked source
  files (`is_no_evidence` filters as today) is included as an excerpt from that line, at most 12 lines, unless an
  excerpt already covers that line. They count against the code budget like the other excerpts.
- `PROMPT_VERSION = 6`.

## Contracts (texts, exact)

- Kept reasons (D1): `named in <n> test files: write <path>::<name>`, `more than 5 existing tests named`.
- Prompt section heading (D2): `# Existing tests this task changes in place`.
- Integrity listing (D2): `<id> (named by the task text, <source>)`.
- Opened-helper texts (D3): `drops <name>`, `changes the signature of <name>`, `adds a test <name>`.
- Remedies (D5): as written above, `<m>`, `<n>`, `<path>:<line>`, `<a>` filled in.
- Template versions: `red.md` 13. Clarifier `PROMPT_VERSION` 6.

## Risks / Trade-offs

- A named test could be weakened in place by red. Mitigation: only reviewed text names it, at most five, every change
  is recorded and listed in the verdict, and the judge sees the diff as today; the test must still pass after green.
- A bare test name could match the wrong test. Mitigation: only a name defined in exactly one test file counts.
- Opening a helper lets green shape the fake the red tests use. Mitigation: only a file red added, that defines no test
  and that the task line names; red's names and signatures stay fixed.
