## Purpose

A unit's own new test that fails for a reason other than its checks can be repaired by a narrow, structurally checked
step, so an unattended plan does not wait on a person for it, and no fix step bends product code to a broken test.

## ADDED Requirements

### Requirement: L4-IMP-091 A repair chore may change only the failing tests' definitions
A candidate is a failing test of a round that (all of): sits in a file that matches `tdd.test_globs` and no
`tdd.test_support_globs` glob, is a Python file, was first added by a harness commit that carries `L4-TDD: red` of this
unit (absent at the unit's base, `unit_base`, which for a fix unit is its parent's), and failed with a kind other than
`assertion` or `not_implemented` (the round's `failures`). A finding SHALL become a `repair` chore only when every test
id it fails on is a candidate; otherwise it stays a plain fix chore. The task SHALL name each test, its kind and the
first line of its message, carry the excerpt of the gate log of the finding, and say that the test may be right and the
code wrong.

The repair step SHALL keep a change only when all of these hold, else it puts the change back and fails the attempt
naming the rule:
- every changed file is one of the candidates' files;
- in each, the AST facts (`l4.implementer.tamper.facts_of`) of every name other than the repaired tests are equal before
  and after; the module's statements that bind no name are equal; imports may only be added, and no `from x import *`;
- each repaired test keeps its decorators and its signature (the fixtures it requests); its body has the same number of
  top-level statements, at most 3 of them differ, each replaced in place, and no replacing statement is a `try`, `if`,
  loop or `with` that was not there; no `assert` statement of the test is removed; no `skip`, `xfail` or `importorskip`
  call or marker is added.
A change to any other file SHALL fail the attempt (after it is put back): product code is frozen in a repair. The
repaired tests SHALL then pass in the gate they failed in (`gates.test` with them as must-pass, or `gates.build` when
configured and the e2e gate with them as `must_contain`), under the test gate's no-regression rule. The commit SHALL
carry `L4-TDD: exempt` (the trailer every test-path check already walks) and the ledger `task.repaired{task, files,
tests}`. When the attempts are used up the task SHALL escalate as a fix chore does, with a note that the test may be
right and the product code wrong.

#### Scenario: SCN-IMP-450 (+) A broken assertion call is repaired
- **GIVEN** the unit's own `e2e/test_a.py::test_x` (added by its red commit) fails in the e2e gate with kind `other`
  ("value must be a string or regular expression")
- **WHEN** the repair step replaces `expect(page).to_have_url(lambda url: …)` with `page.wait_for_url(lambda url: …)` and
  the e2e gate then passes `test_x`
- **THEN** the change is committed (`L4-TDD: exempt`), `task.repaired` names the file and the test, and the task is done

#### Scenario: SCN-IMP-451 (−) Another test of the file is not touched
- **WHEN** the step also changes `test_y` of the same file, a helper or fixture `test_x` uses, or adds a module-level call
- **THEN** the change is put back and the attempt fails naming what changed

#### Scenario: SCN-IMP-452 (−) No check may go
- **WHEN** the step removes an `assert` of `test_x`, deletes a statement, wraps statements in a new `try`, changes its
  fixtures, or adds `pytest.skip`, `pytest.mark.xfail` or `importorskip`
- **THEN** the attempt fails naming the rule

#### Scenario: SCN-IMP-453 (−) Product code is frozen in a repair
- **WHEN** the step changes `src/app/page.tsx` as well
- **THEN** the product change is put back and the attempt fails

#### Scenario: SCN-IMP-454 (−) A repaired test must pass where it failed
- **WHEN** after the step `test_x` still fails in the e2e gate
- **THEN** the attempt fails naming `test_x`; after the last attempt the task escalates with the note that the test may
  be right and the code wrong

#### Scenario: SCN-IMP-455 (+) An assertion failure, a pre-existing test or a person's test is no repair
- **WHEN** the unit's own test fails by assertion, or a test that existed at the unit's base fails with any kind, or the
  failing test was first added by a person's commit on the unit branch
- **THEN** the fix unit makes a plain fix chore, as before

#### Scenario: SCN-IMP-456 (+) A non-Python test or a mixed finding is no repair
- **WHEN** the unit's own failing test with kind `other` is a TypeScript test, or the gate finding fails on one candidate
  and one pre-existing test
- **THEN** no repair chore is made; the fix chore and its escalation are as before

#### Scenario: SCN-IMP-457 (+) An added import is allowed
- **WHEN** the repair adds `import re` and uses `re.compile(...)` in one replaced statement of `test_x`
- **THEN** the change is kept

### Requirement: L4-VER-070 The verifier accepts a repair of the repaired tests only, and the judge sees it
`check_test_paths` and the check that red's tests are unchanged after red SHALL accept, for an `L4-TDD: exempt` commit,
the files a `task.repaired` of the same unit and task names, and nothing else. The judge's material for the next round
SHALL show each repaired test's lines before and after the repair (as for a named test that red changed, L4-VER-068).

#### Scenario: SCN-VER-257 (−) A repair commit that also changed another test is a blocker
- **GIVEN** an exempt commit of a repair task whose `task.repaired` names `e2e/test_a.py`
- **WHEN** the commit also changed `e2e/test_b.py`
- **THEN** `check_test_paths` reports `e2e/test_b.py`; `e2e/test_a.py` is accepted

#### Scenario: SCN-VER-258 (+) The judge sees the repair
- **WHEN** the next round's judge runs
- **THEN** its prompt has the repaired test's lines before and after the repair, as bounded data

## MODIFIED Requirements

### Requirement: ci-evidence D11 (amendment, the one exception)
A fix chore SHALL NOT change a test file, with one exception: a `repair` chore (L4-IMP-091) may change the definitions of
the unit's own new failing tests under the structural check, and nothing else.

#### Scenario: SCN-IMP-458 (+) A plain fix chore still may not change tests
- **WHEN** a plain fix chore (kind `fix`) edits the same test
- **THEN** the edit is put back as before
