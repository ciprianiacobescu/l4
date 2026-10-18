## Purpose

Every variant run of the red phase and the verifier is judged per test against the real run, so a run that could not
run a test is inconclusive, never "still passes", and the zero values never break the imports they measure.

## ADDED Requirements

### Requirement: L4-IMP-060 A variant run is judged against the real run
Every variant run SHALL pass `--continue-on-collection-errors` and be judged per test against the real run: failed by
assertion is a proof; passed, or another error, is none; absent, or skipped only there, is inconclusive, as is every
test of a run with no report or no executed test. In a zero-value run a test the unit's own files made unrunnable is
no proof, not inconclusive. A reason SHALL quote the first `E` line, redacted before it is cut to 300 characters.

#### Scenario: SCN-IMP-300 (−) A readable report with collection errors and no test is inconclusive
- **GIVEN** a zero-value run whose JUnit report lists 45 collection errors, each ending
  `E   TypeError: 'NoneType' object is not callable`, and no test case
- **WHEN** the harness judges a criterion whose two tests passed in run (a)
- **THEN** the criterion is inconclusive, not "not discriminating", and its reason names the run and quotes
  `E   TypeError: 'NoneType' object is not callable`; had the collection errors been raised by the unit's own test
  files, or the test skipped itself on the zero answer, the criterion would be not discriminating and fail red

#### Scenario: SCN-IMP-301 (−) A base run goes on past an unrelated test that imports an added module
- **GIVEN** a unit that added `src/pytdd/middleware.py`, committed `tests/test_middleware.py` importing it, and a
  candidate test in `tests/test_pricing_rules.py` that fails by assertion against the unit base's `pricing.py`
- **WHEN** the base run swaps the production files to the unit base
- **THEN** pytest reports the collection error of `tests/test_middleware.py` and still runs the candidate, which
  confirms its criterion, and `run_with_code_of` returns a gate result whose report holds both

### Requirement: L4-IMP-061 Zeroing keeps what imports need
When the harness zeroes every public function, one annotated to return `Callable` or `type` SHALL keep its body only when
a module of the varied set applies it at import time. When a zero-value run leaves a candidate inconclusive, the
harness SHALL keep the zeroed functions its tracebacks call, and those called by the module-level statements of the
failing production module, and run again: at most twice, recording `zero.kept`.

#### Scenario: SCN-IMP-302 (+) A decorator factory annotated to return a callable keeps its body
- **GIVEN** `src/pytdd/telemetry.py` with `def traced(name: str) -> Callable[[_F], _F]`, and `src/pytdd/store.py`
  whose class body applies `@telemetry.traced("store.add")` to a method, and a `make_adder(n) -> Callable[[int], int]`
  that no varied module applies at import time
- **WHEN** the pre-satisfied zero-value run varies both modules
- **THEN** `traced` keeps its body, every test module imports, and `zero.kept{cause: annotation}` lists
  `src/pytdd/telemetry.py::traced`; `make_adder` is zeroed, so an honest test of it that follows check 5 keeps its proof

#### Scenario: SCN-IMP-303 (+) An unannotated decorator factory is kept after the run names it
- **GIVEN** the modules of SCN-IMP-302 with `def traced(name):` unannotated, and a candidate test of `Store.add`
- **WHEN** the first zero-value run fails to import `store.py` on the line `@telemetry.traced("store.add")`
- **THEN** the harness keeps `traced`, records `zero.kept{cause: collection, rerun: 1}`, runs once more, and the
  candidate fails by assertion there, which confirms its criterion; a test that failed by assertion in any pass counts, and
  a pre-existing test-support module on the traceback is read like a production one; for `_CFG = load()` above `RATE = _CFG["rate"]`
  the failing line calls nothing, and the harness keeps `load`, which the module-level statement above it calls

#### Scenario: SCN-IMP-304 (−) The keep reruns are bounded
- **GIVEN** a zero-value run whose every report names one more zeroed function on a failing collection line
- **WHEN** the harness keeps and reruns
- **THEN** it runs the gate three times in all, records two `zero.kept`, and the candidates are inconclusive

### Requirement: L4-IMP-062 Discrimination is not applicable to a dependency check
A pre-satisfied criterion whose every candidate test reads a dependency's version with a literal distribution name that
the criterion's text names, and uses no project code (also none reached by a string), SHALL be recorded
`proof: pre_satisfied, via: not_applicable`, with no variant run for it. Any other test SHALL stay not discriminating.

#### Scenario: SCN-IMP-306 (+) A version pin is recorded as not applicable
- **GIVEN** a criterion that names the installed `pytest` version, and a candidate `def
  test_runner_is_the_verified_pin(): assert importlib.metadata.version("pytest") == pytest.__version__` in a test
  file whose other tests import `pytdd`
- **WHEN** the pre-satisfied confirmation runs
- **THEN** its criterion is recorded with `via: not_applicable`, `criterion.pre_satisfied` carries the same `via`, and
  no variant run varies anything for it

#### Scenario: SCN-IMP-307 (−) A test that reads no dependency is still not discriminating
- **GIVEN** a candidate `def test_x(): assert 1 + 1 == 2`, another `def test_y(): assert json.loads("1") == 1`, a
  third `def test_z(): assert pytest.__version__` tagged with a criterion about `apply_discount`, and a fourth that
  reaches `pytdd` through `importlib.import_module("pytdd")` beside a `version("pytest")` read
- **WHEN** the pre-satisfied confirmation runs
- **THEN** no criterion is not applicable, and all fail red as `not discriminating`; so does a read of the repository's
  own distribution, one whose name is only part of another token or has no version beside it in the criterion's text,
  and one whose version is tested for truth rather than compared

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
  and no question is raised; a test that skips itself when the answer is the zero value, a test module that raises
  at import after reading a production answer, and a `parametrize` over a production answer fail red as they do on
  0.4.15 and are never held

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
