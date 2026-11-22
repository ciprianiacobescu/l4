## Purpose

Audit sampling runs for a unit's Python code and never because a changed Python file is a test of another language's
unit, its test goes where the test command collects it, and a call of the verifier agent that one profile cannot answer
is asked of the next profile of the chain in the same run.

## ADDED Requirements

### Requirement: L4-VER-089 Audit sampling audits Python code, not the Python tests of another language's unit
Step 4a SHALL decide from the unit's changed files outside the exempt paths (`changed_unit_files`). Its *source files*
are those that `tdd.test_globs` does not match (kind `code` or `root`), whose suffix is a source suffix
(`CODE_SUFFIXES`) and that match no `tdd.test_support_globs` glob; its *Python test files* are the changed `.py` files
that `tdd.test_globs` or `tdd.test_support_globs` matches. The step SHALL run when the unit changed no file outside the
exempt paths, or when a source file is a `.py` file. When the unit's source files are all of another language, the step
SHALL be `not_run` with the note `audit sampling writes pytest tests only; changed code is not python`, followed, when
it has Python test files, by ` (the changed Python files are tests or test support: <files>)`. When the unit changed no
source file and has Python test files, the step SHALL run when step 3's unit-gate report holds a test of one of those
files (`evidence.testsran.file_of_test`), or when step 3 left no report; else it SHALL be `not_run` with that note and
its parenthesis. A unit with no `.py` file at all keeps the note of 0.4.59 word for word. A `not_run` step SHALL ask no
writer, write no file and raise no finding.

#### Scenario: SCN-VER-356 (−) A TypeScript unit with a changed Python browser test does not audit
- **Given** a unit that changes `web/src/layout.ts` and `e2e/test_layout.py`, and a unit-gate report of Node test ids
- **When** the verifier reaches step 4a
- **Then** the step is `not_run` with `audit sampling writes pytest tests only; changed code is not python (the changed
  Python files are tests or test support: e2e/test_layout.py)`, no writer is asked and no file is written

#### Scenario: SCN-VER-357 (+) A Python unit that changes only tests still audits
- **Given** a unit that changes only `tests/test_pricing.py`, whose test `tests.test_pricing::test_total` is in step 3's
  report, and a covered new criterion
- **When** the verifier reaches step 4a
- **Then** the writer is asked for an audit test, as in 0.4.59

#### Scenario: SCN-VER-358 (+) Python code next to another language audits, and a support file is not code
- **Given** one unit that changes `src/a.py` and `web/app.ts`, and another that changes `web/app.ts` and
  `tests/conftest.py`
- **When** the verifier reaches step 4a for each
- **Then** the first audits, and the second is `not_run` with the parenthesis naming `tests/conftest.py`

#### Scenario: SCN-VER-359 (+) Without a report a tests-only unit audits as before
- **Given** a unit that changes only `tests/test_pricing.py`, and a step 3 that left no unit-gate report
- **When** the verifier reaches step 4a
- **Then** the step is not `not_run` for its language

### Requirement: L4-VER-090 The audit test goes next to the unit's tests only when the report shows them
The folder of the unit's own Python tests (`red_test_directory`) SHALL count a changed `.py` test file only when step
3's unit-gate report holds a test of it. When no file qualifies, or step 3 left no report, the audit SHALL confirm that
the test command collects the audit file (`confirm_collected`) before it keeps the folder of `audit_directory`, and
SHALL write the file under `tests/` when it does not, as it does today when no folder is found.

#### Scenario: SCN-VER-360 (+) The audit file goes where the unit gate's report shows the unit's tests
- **Given** a Python unit that changes `src/a.py`, `tests/test_a.py` and two browser test files under `e2e/`, and a
  unit-gate report that holds tests of `tests/test_a.py` only
- **When** step 4a writes an audit test
- **Then** the file is `tests/test_l4_audit_c_<hex>_r<n>.py` and no collect-only run is made for it

#### Scenario: SCN-VER-361 (−) A folder the report does not show is confirmed first
- **Given** a Python unit whose only changed test files are under `e2e/`, which the unit gate's report does not show
- **When** step 4a writes an audit test
- **Then** an `audit-collect-check` gate runs before the audit file is kept, and a file the command does not collect is
  written under `tests/` instead

### Requirement: L4-VER-091 A verifier-agent call that a profile cannot answer goes to the next profile of the chain
A call of the `verifier_agent` role (the audit writer of step 4a, its collection retry and its lint retry, and the UI
test writer of step 5) whose reply is `error` (a reply stopped at the output limit, a tool call that the permission
rules refused, or any other adapter error that the run's own retries did not cure) SHALL be discarded and the same call
SHALL be asked of the next usable profile of `roles.verifier_agent` that is independent of the unit's implementers
(`select_judge(role="verifier_agent", skip=...)`, its probes and `probe_vetoes`), in the same run, as the step-9 judges
do (L4-VER-015, L4-VER-075). A usage limit or a lost login SHALL cool the profile down (`Factory.on_limit`, L4-AVL-003)
and move on the same way. A discarded profile SHALL be skipped for the rest of the round, by both steps. Each discard
SHALL be recorded as `availability.judge_error{role: "verifier_agent", profile, kind, detail, step}` (`kind`: `length`,
`permission` or `error`; `detail` redacted, at most 300 characters; `step`: `4a` or `5`), and the cost of a discarded
call as `budget.cost` with that profile. A reply that is `invalid` or a `timeout` SHALL keep its handling of 0.4.59 and
SHALL NOT move to another profile. When no profile is left, the call's result SHALL carry the detail `no profile of
roles.verifier_agent could answer: <profile>: <kind>: <detail>; ...`, step 4a SHALL wait for capacity with it (exit 12)
and step 5 SHALL record `writer_failed` with it, as each does today. What an audit or a generated test needs in order to
count SHALL NOT change.

#### Scenario: SCN-VER-362 (+) A length stop moves the audit writer's call to the next profile
- **Given** `roles.verifier_agent: [first, second]`, both independent of the implementer, and a `first` whose reply to
  the audit call stops at its output limit
- **When** step 4a asks for an audit test
- **Then** the ledger has `availability.judge_error` with `role: "verifier_agent"`, `profile: "first"`, `kind:
  "length"` and `step: "4a"`, `second` is asked the same call and its test is judged, and the unit does not wait

#### Scenario: SCN-VER-363 (+) A refused tool call moves the call, and the profile is skipped for the round
- **Given** the chain of SCN-VER-362 and a `first` whose run ends `permission_blocked`, and a round that reaches step 5
  with a UI gap
- **When** steps 4a and 5 ask their writers
- **Then** `availability.judge_error` has `kind: "permission"`, step 4a's call is answered by `second`, and step 5
  asks `second` without asking `first`

#### Scenario: SCN-VER-364 (−) The next profile must be independent of the implementers
- **Given** `roles.verifier_agent: [first, same, third]`, where `same` has the vendor of the unit's implementer, and a
  `first` whose reply is `error`
- **When** step 4a asks for an audit test
- **Then** `same` is not asked and `third` is

#### Scenario: SCN-VER-365 (+) A usage limit cools the profile and moves on
- **Given** the chain of SCN-VER-362 and a `first` whose run reports a usage limit
- **When** step 4a asks for an audit test
- **Then** a cool-down of `first` is recorded, `availability.fallback` names `first` and `second`, and `second`
  answers the call

#### Scenario: SCN-VER-366 (−) With no profile left the unit waits, and the reason names each failure
- **Given** the chain of SCN-VER-362, a `first` whose reply stops at its output limit and a `second` whose run ends
  `permission_blocked`
- **When** step 4a asks for an audit test
- **Then** the unit goes to phase `waiting_capacity` with exit 12, and the reason holds `no profile of
  roles.verifier_agent could answer: first: length:` and `second: permission:`

#### Scenario: SCN-VER-367 (+) Step 5's writer walks the chain too
- **Given** the chain of SCN-VER-362, a UI gap, and a `first` whose reply to the UI test call is `error`
- **When** step 5 asks for a UI test
- **Then** `second` is asked the same call, and the criterion's outcome is judged from its test, not `writer_failed`

#### Scenario: SCN-VER-368 (−) A timeout and an invalid reply do not move to the next profile
- **Given** the chain of SCN-VER-362, and a `first` whose audit reply times out, and in another round breaks the
  schema twice
- **When** step 4a asks for an audit test
- **Then** `second` is not asked, and the criterion's audit record is `timeout`, then `invalid`, each with its minor
  finding, as in 0.4.59

#### Scenario: SCN-VER-369 (+) A discarded call's cost is recorded
- **Given** the chain of SCN-VER-362 and a `first` whose discarded call cost 0.40 USD
- **When** step 4a asks for an audit test
- **Then** the ledger has a `budget.cost` of 0.40 with `profile: "first"`, and the step's own `budget.cost` holds only
  the calls whose replies it used
