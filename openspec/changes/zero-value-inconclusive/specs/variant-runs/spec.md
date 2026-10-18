## Purpose

Every variant run of the red phase and the verifier is judged per test against the real run, so a run that could not
run a test is inconclusive, never "still passes", and the zero values never break the imports they measure.

## ADDED Requirements

### Requirement: L4-IMP-060 A variant run is judged against the real run
Every variant run (run (b), the pre-satisfied zero-value run, the base run, `test-at-red`, the audit's and the extra
proofs' runs) SHALL pass `--continue-on-collection-errors` and SHALL be judged per test against the real run: failed by
assertion is a proof; passed, or another error, is none; absent, or skipped only there, is inconclusive, as is every
test of a run with no report or no executed test. A reason SHALL quote the first `E` line when there is one, cut at
300 characters, redacted.

#### Scenario: SCN-IMP-300 (−) A readable report with collection errors and no test is inconclusive
- **GIVEN** a zero-value run whose JUnit report lists 45 collection errors, each ending
  `E   TypeError: 'NoneType' object is not callable`, and no test case
- **WHEN** the harness judges a criterion whose two tests passed in run (a)
- **THEN** the criterion is inconclusive, not "not discriminating", and its reason names the run and quotes
  `E   TypeError: 'NoneType' object is not callable`

#### Scenario: SCN-IMP-301 (−) A base run goes on past an unrelated test that imports an added module
- **GIVEN** a unit that added `src/pytdd/middleware.py`, committed `tests/test_middleware.py` importing it, and a
  candidate test in `tests/test_pricing_rules.py` that fails by assertion against the unit base's `pricing.py`
- **WHEN** the base run swaps the production files to the unit base
- **THEN** pytest reports the collection error of `tests/test_middleware.py` and still runs the candidate, which
  confirms its criterion, and `run_with_code_of` returns a gate result whose report holds both

### Requirement: L4-IMP-061 Zeroing keeps what imports need
When the harness zeroes every public function, one annotated to return `Callable` or `type` (also `X | None` of
them) SHALL keep its body. When a zero-value run leaves a candidate inconclusive, the harness SHALL keep the zeroed
functions called on the failing lines of the run's new collection errors and of setup assertions outside the unit's
files, and run again: at most twice, only when a new function is kept, recording `zero.kept`.

#### Scenario: SCN-IMP-302 (+) A decorator factory annotated to return a callable keeps its body
- **GIVEN** `src/pytdd/telemetry.py` with `def traced(name: str) -> Callable[[_F], _F]`, and `src/pytdd/store.py`
  whose class body applies `@telemetry.traced("store.add")` to a method
- **WHEN** the pre-satisfied zero-value run varies both modules
- **THEN** `traced` keeps its body, every test module imports, and `zero.kept{cause: annotation}` lists
  `src/pytdd/telemetry.py::traced`

#### Scenario: SCN-IMP-303 (+) An unannotated decorator factory is kept after the run names it
- **GIVEN** the modules of SCN-IMP-302 with `def traced(name):` unannotated, and a candidate test of `Store.add`
- **WHEN** the first zero-value run fails to import `store.py` on the line `@telemetry.traced("store.add")`
- **THEN** the harness keeps `traced`, records `zero.kept{cause: collection, rerun: 1}`, runs once more, and the
  candidate fails by assertion there, which confirms its criterion

#### Scenario: SCN-IMP-304 (−) The keep reruns are bounded
- **GIVEN** a zero-value run whose every report names one more zeroed function on a failing collection line
- **WHEN** the harness keeps and reruns
- **THEN** it runs the gate three times in all, records two `zero.kept`, and the candidates are inconclusive

### Requirement: L4-IMP-062 Discrimination is not applicable to a dependency check
A pre-satisfied criterion whose every candidate test reads a dependency (a module from outside the repository that is
not in the standard library, or `importlib.metadata`) and uses no project code, no repository helper and no fixture
beyond pytest's built-ins SHALL be recorded `proof: pre_satisfied, via: not_applicable`, with no variant run for it. A
test that reads no dependency SHALL stay not discriminating.

#### Scenario: SCN-IMP-306 (+) A version pin is recorded as not applicable
- **GIVEN** a candidate `def test_runner_is_the_verified_pin(): assert importlib.metadata.version("pytest") ==
  pytest.__version__` in a test file whose other tests import `pytdd`
- **WHEN** the pre-satisfied confirmation runs
- **THEN** its criterion is recorded with `via: not_applicable`, `criterion.pre_satisfied` carries the same `via`, and
  no variant run varies anything for it

#### Scenario: SCN-IMP-307 (−) A test that reads no dependency is still not discriminating
- **GIVEN** a candidate `def test_x(): assert 1 + 1 == 2`, and another `def test_y(): assert json.loads("1") == 1`
- **WHEN** the pre-satisfied confirmation runs
- **THEN** neither criterion is not applicable, and both fail red as `not discriminating`

## MODIFIED Requirements

### Requirement: L4-IMP-002 Red phase: what a variant run proves
The red phase is unchanged except these clauses. Run (b) and the pre-satisfied confirmation SHALL judge their runs by
L4-IMP-060. A test fails by assertion on the zero values when it failed by assertion, or when its setup failed by
assertion at a line of a test or support file that the unit added or changed since the unit base; a setup assertion
anywhere else is inconclusive, and a setup error of another kind is no proof. A criterion is confirmed when one of its
tests fails by assertion, not discriminating only when every one of its tests ran and none did, and inconclusive
otherwise. A red attempt with a criterion that is not discriminating fails as before (counted), its message listing the
inconclusive criteria apart (`inconclusive: <id> (<reason>)`); an attempt whose unconfirmed criteria are all
inconclusive is held (L4-IMP-063). The zero-value stubs keep what imports need (L4-IMP-061).

#### Scenario: SCN-IMP-308 (+) A fixture assertion in the unit's own test file counts
- **GIVEN** a test file the unit added whose fixture asserts `telemetry.init(exporter) is True`, and three candidates
  that use the fixture and passed in run (a)
- **WHEN** the zero-value run makes `init` answer `False`
- **THEN** each candidate errors in setup by assertion at a line of that file, and their criteria are confirmed

#### Scenario: SCN-IMP-309 (−) A fixture assertion in a pre-existing conftest does not count
- **GIVEN** the fixture of SCN-IMP-308 in `tests/conftest.py`, unchanged since the unit base
- **WHEN** the zero-value run makes `init` answer `False`
- **THEN** the candidates are inconclusive, the harness keeps `init` and reruns, and the body's assertions decide

#### Scenario: SCN-IMP-310 (−) A refuted criterion fails the attempt beside an inconclusive one
- **GIVEN** a red step with criterion A whose tests passed on the zero values, and criterion B whose test module did
  not import in the zero-value run nor at the base
- **WHEN** the red checks finish
- **THEN** the attempt fails with `not discriminating: A (…)` and `inconclusive: B (…)`, counts as a failed attempt,
  and no question is raised

### Requirement: L4-IMP-003 Confirmation by a base run confirms or decides nothing
The base run SHALL pass `--continue-on-collection-errors` and SHALL only confirm: a criterion is confirmed when one of
its new tests fails by assertion there. A test that passes at the base, errors there, or does not run there (its module
cannot import at the base) confirms nothing and refutes nothing. A criterion the base run does not confirm keeps the
zero-value run's result: not discriminating, or inconclusive; with no zero-value run (nothing to vary, no project
module imported) it is not discriminating as before. A skipped base run keeps its reason in the message as before.

#### Scenario: SCN-IMP-311 (−) A base run cannot refute what the zero-value run could not decide
- **GIVEN** a criterion whose zero-value run was inconclusive, and whose candidate passes at the unit base
- **WHEN** the confirmation combines the two runs
- **THEN** the criterion is inconclusive, not `not discriminating`
