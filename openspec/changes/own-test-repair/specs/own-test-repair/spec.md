## Purpose

A unit's own new test that fails for a reason other than its checks can be repaired by a narrow, structurally checked
step, so an unattended plan does not wait on a person for it, and no fix step bends product code to a broken test.

## ADDED Requirements

### Requirement: L4-IMP-091 A repair chore may change only the failing tests' definitions, and the repaired tests are proved again
A candidate is a failing test of a round that (all of): sits in a file that matches `tdd.test_globs` and no
`tdd.test_support_globs` glob, is a Python file, is bound once in it, was first added by a harness commit that carries
`L4-TDD: red` of this unit (absent at the unit's base, `unit_base`, which for a fix unit is its parent's) and has not
been changed by a person's commit since (its facts and what it uses in the file, `tamper.facts_of`, are as the red
commit left them; a file taken out and added again is no candidate), failed with a kind other than `assertion` or
`not_implemented` (the round's `failures`), and was raised in a test or support file: the round records the file of the
deepest repository frame of the traceback (`location`), which SHALL match `tdd.test_globs` or `tdd.test_support_globs`;
a failure raised in a production module, or one whose location cannot be told (no traceback, or a deeper frame with an
absolute path that is no library), is no candidate, because any exception from wrong product code has the kind `other`.
A finding SHALL become a `repair` chore only when every test id it fails on is a candidate; otherwise it stays a plain
fix chore. The task SHALL name each test, its kind and the first line of its message, carry the excerpt of the gate log
of the finding, and say that the test may be right and the code wrong. The step SHALL derive the candidates again from
git and the stored round; the marker is never the proof.

The repair step SHALL keep a change only when all of these hold, else it puts the change back and fails the attempt
naming the rule:
- every changed file is one of the candidates' files, and each is UTF-8 before and after (`tokenize.detect_encoding`
  gives `utf-8` or `utf-8-sig`; pytest honours a `# coding:` cookie, so another codec could hide code from the AST);
- in each, the AST facts (`l4.implementer.tamper.facts_of`) of every name other than the repaired tests are equal before
  and after; the module's statements that bind no name are equal; imports may only be added, in place, as an ordered
  multiset (an existing import is not moved, removed or repeated), no `from x import *`, no `__future__` import, and a
  new import binds no name that the file or Python's builtins bind and none that starts with `assert`, `expect` or
  `wait_for` (nor `ANY`);
- each repaired test keeps its decorators and its signature (the fixtures it requests); its body has the same number of
  top-level statements, at most 3 of them differ, each replaced in place, and no differing statement gains a `try`,
  `if`, loop, `with` or `match`;
- each keeps its checks in its own scope (not in a nested `def`, lambda or comprehension, which may never run): no
  `assert` statement is removed, and the multiset of check names (assert statements, matchers of `expect(...)`,
  `assert...(...)` and `wait_for_...(...)` calls, normalised so that `to_have_url` and `wait_for_url` are one check) does
  not lose a name, nor does the nested scope; no check sits below `and`/`or`, a conditional expression or `:=`;
- it gains no `return`, `yield`, always-true `assert` (a constant, a non-empty container, an expression compared with
  itself, an `or` with such an operand), no `and`/`or` operand that reads no name, call, attribute or item, no `skip`,
  `skipif`, `xfail`, `importorskip`, `SkipTest` or `exit`, no write to an attribute or item of a name outside its
  locals, no `global`/`nonlocal`, and no call of `globals`, `vars`, `setattr`, `delattr`, `__import__`, `exec`, `eval`,
  `compile` or `importlib`.
A change to any other file SHALL fail the attempt (after it is put back): product code is frozen in a repair. The
repaired tests SHALL then pass in the gate they failed in (`gates.test` with them as must-pass, or `gates.build` when
configured and the e2e gate with them as `must_contain`), under the test gate's no-regression rule.

The repaired tests SHALL be proved again before the commit, the way a test nobody proved is: a repaired unit-gate test
SHALL fail by an assertion when the project's functions answer their zero value, or against the unit base's production
code (`discriminate_extra`); a repaired e2e test SHALL fail by an assertion when the unit's source files are put back to
their base, built, and run in the e2e gate. A test that does not, or whose run cannot be made (no production file
changed, the build or the server fails), fails the attempt: "the repaired test no longer tells a working product from a
broken one". The commit SHALL carry `L4-TDD: exempt` (the trailer every test-path check already walks) and the ledger
`task.repaired{task, base, files, tests, ids, proved, sha10}`, where `proved` maps each test id to how it was proved and
`sha10` ties the proof to the content of its file. When the attempts are used up the task SHALL escalate as a fix chore
does, with a note that the test may be right and the product code wrong.

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

#### Scenario: SCN-IMP-459 (−) A vacuous repair is refused
- **WHEN** the step turns `assert x == 4` into `assert x == 4 or 1 == 1`, `assert x == ANY`, an early `return`, or a
  call that no longer reaches the product
- **THEN** the attempt fails, naming the rule or, for a test that passes without the product, "the repaired test no
  longer tells a working product from a broken one"

#### Scenario: SCN-IMP-460 (−) Code hidden by an encoding cookie is refused
- **WHEN** the file starts with `# coding: utf-7` before or after the step
- **THEN** the attempt fails naming the encoding

#### Scenario: SCN-IMP-461 (−) A failure raised by product code is no repair
- **WHEN** a unit's own test fails with kind `other` and the deepest repository frame of its traceback is
  `src/app/x.py`, or the traceback is not recorded
- **THEN** no repair chore is made

#### Scenario: SCN-IMP-462 (−) A test a person changed is no repair
- **WHEN** a person's commit on the unit branch changed the failing test, or what it uses in its file, after the red
  commit, or deleted the file and added it again
- **THEN** no repair chore is made

#### Scenario: SCN-IMP-463 (+) A repaired test keeps no old proof and gets its own
- **WHEN** a repair is committed with `proved` and `sha10`
- **THEN** the verifier counts the test as proved by the repair while its file has that content, and by nothing when the
  file changed after it

### Requirement: L4-VER-070 The verifier accepts a repair of the repaired tests only, re-checks it, and the judge sees it
`check_test_paths` and the check that red's tests are unchanged after red SHALL accept, for an `L4-TDD: exempt` commit,
the files a `task.repaired` of the same unit and task names, and nothing else. For each such file the structural rules
of a repair (including the encoding rule) SHALL run again on the file before and after the commit, with the tests the
event names; a file that breaks them, was added or deleted by the commit, or is named with no test, is a blocker. A test
a `task.repaired` lists SHALL keep no red proof by its id: its proof is the one the event records (`proved`), valid only
while the file still has the content `sha10` names. The judge's material for the next round SHALL show each repaired
test's lines before and after the repair (as for a named test that red changed, L4-VER-068).

#### Scenario: SCN-VER-257 (−) A repair commit that also changed another test is a blocker
- **GIVEN** an exempt commit of a repair task whose `task.repaired` names `e2e/test_a.py`
- **WHEN** the commit also changed `e2e/test_b.py`
- **THEN** `check_test_paths` reports `e2e/test_b.py`; `e2e/test_a.py` is accepted

#### Scenario: SCN-VER-259 (−) A repair commit that breaks the rules is a blocker
- **GIVEN** an exempt commit whose `task.repaired` names `e2e/test_a.py`
- **WHEN** the commit removed an assert of the repaired test, declared another encoding, or added another test
- **THEN** `check_test_paths` reports a blocker naming the file and the rule

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
