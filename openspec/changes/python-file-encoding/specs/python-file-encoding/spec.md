## Purpose

No step and no commit of a unit can hide Python code from the harness's checks and from the judge behind a source
encoding the harness does not read.

## ADDED Requirements

### Requirement: L4-SEC-042 A Python file that a unit changes must be UTF-8
After every agent step, a Python file (`.py`, `.pyi`) that the step added or changed and whose declared encoding
(`tokenize.detect_encoding` on its bytes) is neither `utf-8` nor `utf-8-sig` SHALL be put back to the step's base (a new
file removed), recorded as `guard.violation{path, rule: "python encoding", action}`, and SHALL fail the attempt with the
advice `Python files must stay UTF-8: do not add a coding cookie that names another encoding`. The verifier SHALL report
a blocker for every Python file the unit's diff (base..head) adds or changes, whoever committed it, whose declared
encoding is neither: `a Python file declares a non-UTF-8 encoding (<path>: <encoding>)`, naming the fix (convert the
file to UTF-8 and remove the cookie). A file that cannot be read as a regular file of the tree is the existing checks'
concern.

#### Scenario: SCN-SEC-110 (−) Red cannot hide a return in a pre-existing test
- **GIVEN** a pre-existing `tests/test_a.py::test_existing` and a red step that adds `# coding: utf-7` as line 1 and
  `  # +AAo-    return` to a line of `test_existing`, plus a new failing test
- **WHEN** the step ends
- **THEN** `tests/test_a.py` is put back, `guard.violation{rule: "python encoding"}` is recorded and the attempt fails
  with the advice

#### Scenario: SCN-SEC-111 (−) Green cannot hide code in a product file
- **WHEN** a green step writes `src/app/x.py` with a `# coding: utf-7` cookie
- **THEN** the file is put back and the attempt fails, as in SCN-SEC-110

#### Scenario: SCN-SEC-112 (−) The verifier blocks such a file from anyone
- **GIVEN** the unit's diff adds `# coding: utf-7` to `tests/test_a.py` in a person's commit
- **WHEN** the integrity checks run
- **THEN** a blocker names `tests/test_a.py: utf-7` and the fix

#### Scenario: SCN-SEC-113 (+) UTF-8 files are unaffected
- **WHEN** a step writes a file with no cookie, with `# -*- coding: utf-8 -*-`, or with a byte-order mark
- **THEN** nothing is put back and the verifier reports nothing

#### Scenario: SCN-SEC-114 (+) A non-Python file is unaffected
- **WHEN** a step writes `docs/a.md` whose first line reads `# coding: utf-7`
- **THEN** nothing is put back and the verifier reports nothing
