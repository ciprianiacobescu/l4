## Purpose

The zero-value run finds the modules a test imports wherever a Python project keeps its packages, so that a test of
existing behaviour in a workspace member can be confirmed.

## ADDED Requirements

### Requirement: L4-IMP-025 The modules a test imports are found under every import root
The harness SHALL look up the modules a test imports, for the zero-value run (L4-IMP-002), the head stubs of run (b),
the audit sampling (step 4a) and the proof of tests people or a test chore wrote (step 4), under these import roots:
the repository root, `src`, every directory named `src`, and every directory that holds a `pyproject.toml`,
`setup.py` or `setup.cfg` together with that directory's `src`. The directories SHALL come from git's tracked files
and its untracked files that are not ignored. A dotted name SHALL resolve to `<root>/<dotted as path>.py` and
`<root>/<dotted as path>/__init__.py` under every root where that file exists with the exact case, and every match
SHALL be varied. A match under the test globs SHALL NOT be varied.

#### Scenario: SCN-IMP-211 (+) A workspace member's module is found
- **GIVEN** a base branch with `packages/calc/pyproject.toml`, `packages/calc/src/acme/calc/ops.py` (`acme` has no
  `__init__.py`) and a test `packages/calc/tests/test_ops.py` that imports `acme.calc.ops`
- **WHEN** the harness looks up the modules that test imports
- **THEN** it finds `packages/calc/src/acme/calc/ops.py`

#### Scenario: SCN-IMP-212 (+) A flat member's package is found
- **GIVEN** `packages/flat/setup.cfg`, `packages/flat/flatpkg/core.py` and a test that imports `flatpkg.core`
- **WHEN** the harness looks up the modules that test imports
- **THEN** it finds `packages/flat/flatpkg/core.py`

#### Scenario: SCN-IMP-213 (+) Existing behaviour in a workspace member is pre-satisfied
- **GIVEN** the member of SCN-IMP-211 on the base branch, unchanged by the unit, and a new test of `double` that
  passes in run (a)
- **WHEN** its criterion is confirmed
- **THEN** the zero-value run varies `ops.py`, the test fails by assertion, the criterion is confirmed, and `ops.py`
  holds its original bytes afterwards

#### Scenario: SCN-IMP-214 (−) A directory that is no import root is not searched
- **GIVEN** `scripts/json.py`, in a directory with no project file and not named `src`, and a test that imports `json`
- **WHEN** the harness looks up the modules that test imports
- **THEN** it finds none

#### Scenario: SCN-IMP-215 (−) An ignored directory is not searched
- **GIVEN** an ignored `.venv/` that holds a `pyproject.toml` and a package `vendored`, and a test that imports
  `vendored`
- **WHEN** the harness looks up the modules that test imports
- **THEN** it finds none
