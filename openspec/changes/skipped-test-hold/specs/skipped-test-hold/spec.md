## Purpose

An old test that step 3 finds skipped, in a test file the unit changed, is a finding unless a base report with
statuses holds it as skipped too and the unit added or changed no skip that can affect it. When the skip predates the unit it is a hold that a person answers, and no fix unit is
made for it, because a fix unit cannot change test files. A unit that already has a fix unit for the old finding can be
moved on with `l4 retry`.

## ADDED Requirements

### Requirement: L4-VER-092 A skip that predates the unit is a hold, not a finding
Step 3 SHALL decide, for each old test that the gate report holds as `skipped` in a test file the unit changed, whether
its skip predates the unit. The skip SHALL predate the unit only when ALL of these hold: (a) a base report with statuses (the base's tests
on the base's code) holds the test as `skipped`; (b) the file is reported modified by `base..head` (not added, not
renamed, not deleted), its base and head blobs are read and parse as Python, the test maps to a qualified name of
the file that a runner collects as a test at the base (a function that `pytest.fixture` decorates is never a test,
whatever its name), and no skip construct was added or changed between the base and the head in a scope that can
skip that test (the test, its class, `<module>`, or a function or method of the file that is not a collected test:
a fixture, a helper, `setUp`, a collection hook), by `scan.skip_constructs` as a multiset difference of the head's
constructs over the base's, so that a removed skip never counts and a changed condition, a new alias use, a new
`importorskip`, a marker added at run time (`add_marker`, `applymarker`, `pytestmark.append(...)`), a mark in a
module-level or class-level `if`, `try`, `with` or `for` block, and a skip reached through an import alias
(`import pytest as pt`, `from pytest import mark as m`, `skip = pytest.skip`) do; (c) the unit changed no file
that matches `tdd.test_support_globs` or `tdd.runner_config_files`, none named `conftest.py`, `pytest.ini`, `.pytest.ini`,
`pytest.toml`, `.pytest.toml`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `sitecustomize.py`, `usercustomize.py`,
`noxfile.py`, `setup.py`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock` or `pdm.lock`, none that matches
`requirements*.txt` or `constraints*.txt`, in any directory, and no `.py` file under a path that matches `tdd.test_globs`
that defines no test (an `__init__.py`, a helper, a module a test imports: a support module of the tests tree, read at
the head, and at the base for a deleted or renamed one), and renamed none of them away (a rename counts at its old path
too), whether or not the file holds a skip construct; (d) the dependency
closure of the test's skip is equal at the base and at the head, and the test exists at the head: the multiset of the
`ast.dump` of its skip-relevant parts (its decorators; its class's decorators, bases and class-level skip statements; the
module-level skip statements, a `pytestmark` assignment whatever its value; the statements of its body up to and
including the last one that contains, encloses or calls a skip; the whole definition of each fixture it takes, of
every `autouse` fixture and of every non-collected function or method of the module or its class that skips) and of the
bindings (import per alias, assignment, `def`, `class`) of every name those parts load and the module or the class
binds, followed through the names those bindings load to a depth of 20 (a longer chain keeps the finding), so that
a flag, a guard's condition, a helper, a fixture or an import that the unit changed under a skip that reads the same
is a changed skip; an unrelated added import, test function, flag or helper, and an assertion after the guard are not in
the closure; and (e) every change the unit made to the file is in a place that cannot change why a test skips (a
whitelist of WHERE, beside the lists of (b) and (d), which stay as defence: (b) and (d) enumerate what decides a skip,
and each review found one more in-file way to change it). Every changed line, a line of the base that the head no longer
has and a line of the head that the base does not have, SHALL be: a blank line or a comment-only line (read with
`tokenize`: a docstring is not a comment, and a blank line inside a string is not a blank line); a line inside a
collected test (never a fixture, `setUp`, `setup_method` or a helper), existing at both sides or a whole new one at the
head, its decorators and signature included, except that for the test itself its decorators, its signature (its
parameters are fixtures) and the statements of its body up to and including the last one that contains, encloses or
calls a skip, or that raises or names a skip exception (`raise`, `Skipped`, `SkipTest`, `skip.Exception`), are not a place for a change, and the whole body of a test that mentions `getfixturevalue` anywhere (an attribute, an alias, a string) is not free either; for any collected test, existing or new, a decorator may differ between the two sides only by a `pytest.mark.<name>` or `pytest.mark.<name>(...)` that is added or removed, when `<name>` is not `skip`, `skipif`, `xfail`, `usefixtures` or `parametrize` (any other decorator, an alias of `pytest.fixture` or a `functools.partial` of it included, is a change); and except that a collected test that code outside the free places reads by its name (a
call or an attribute read in a decorator, a helper, a fixture, a class statement, the prefix of the test, or a word of a
string condition) is not free either, its whole definition being the same at both sides, and so is each collected test that such a test reads, again and again until no new one comes (a fixed point, `self.test_mid()` that calls `self.test_inner()`); or a whole new module-level `import M`, `import M as N` or `from M import a, b` statement, on lines of its own, of a module of the standard library (`sys.stdlib_module_names`: never a relative import), that binds only names which the base module neither binds nor loads, which no string condition of a skip marker names, which no runner reads off a module by convention (`pytestmark`, `setup_module`, `teardown_module`, `setup_function`, `teardown_function`, `setUpModule`, `tearDownModule`, `load_tests`, any `pytest_*`, `test*` or `Test*` name) and which the base spells nowhere as a parameter name, a fixture name (the def's name or its `name=`) or an identifier-like string (`usefixtures("db")`, `getfixturevalue("db")`, `depends=["a"]`) (not
`*`, not `__future__`, not a builtin or one of the names pytest gives a string condition: `os`, `sys`, `platform`,
`config`; a new test takes no such name either). Nothing else of the module or of a class SHALL be added, removed or
changed: no statement, no docstring, no decorator of a class, no `setUp`, `setup_method`, helper, fixture or class
attribute. The changed lines SHALL be located by pairing the statements of the two sides, not by a diff of lines: the
statements that are not collected tests, and the imports the base had, are the same trees (`ast.dump`) in the same
order and the same lines of text (comment and blank lines left out), the test is at the same place among them, and its
decorators, signature and skip-relevant statements are the same trees and the same text; a line that no such statement
holds is then in a collected test or in a new import. A source that does not tokenize, a name defined twice, a test that
is not collected at both sides, a coding line that changed, or anything else that is not clear keeps the test in the
finding.
The base report of (a) SHALL be, in this order: step 1's reference of the round when it is a full report of the
base's own run (a cached baseline or a base worktree run; never the head's run with the base's test files); the
`skipped` list of the newest earlier round's `integrity.base_tests` of the same base sha and test command that has
that key; else one run of the test gate in a worktree of the base (network off), kept so that no round runs it
twice, a failed run included, whatever the failure (an exit of the base checkout or any other exception: a second asker
of the round gets the same reason and no second run; the first line of the message, redacted and cut, and the type of
an exception that is not an exit, are kept in the note). A lookup that obtained its report from such a
run SHALL write `skipped` into this round's `integrity.base_tests` (the whole record, `passed` and `collection_errors`
included, when step 1 wrote none), so that the next round reads it from its predecessor's record and the base's gate runs
once for the base and the command, not once a round; nothing is written from anything that is not a full report. It SHALL be looked up only when a skipped test of a changed file passes (b) to (e). When none of these gives
a report, every such test SHALL stay in the finding, and the step note and `tests_ran.summary.skipped_note` SHALL
say `no base report with statuses: <why>`. Any doubt SHALL keep the test in the finding. A test whose skip predates the unit SHALL NOT be named in the finding `existing tests are
skipped in a changed test file`; the tests of one file SHALL be one hold of kind `skipped` with the text `skipped:
existing tests in `<path>` were also skipped in a base report, and the file adds or changes no skip the harness reads
(<n> tests)`.
Any other old skipped test of a changed file, and every case in which a blob cannot be read or parsed, SHALL stay in the
deterministic major finding as before. The hold SHALL join the round at step 3, whether diff coverage is on or off, and
SHALL be listed in `evidence.holds` of `verdict.json` with kind `skipped` and in `tests_ran.summary.skipped_predating`.
The Evidence section of `verification.md` SHALL print the line `Skipped in a changed file before this unit (hold): also
skipped in a base report (<source>); the file adds or changes no skip construct the harness reads and the unit changed it
only in places that cannot change why a test skips; not told apart: <the residuals below>. Tests: <ids>` when `skipped_predating` is not empty, and the line
`Skipped tests were not matched with a base report: <note>` when `skipped_note` is not empty, and a `verdict.json` that has no `skipped_predating`, `skipped_source` or `skipped_note` SHALL read them as empty.
The check SHALL run no test of the unit; the only run it can make is the third source of (a), at most one a round.
`integrity.base_tests` of `verdict.json` SHALL carry a `skipped` list (the sorted ids the base's report holds as
skipped) only when the reference of step 1, or the run of the lookup in step 3, was a full report of the base (source
`baseline` or `base worktree`); a
record rebuilt from an earlier round's passed ids, or the head's run with the base's test files (`not needed`),
SHALL NOT have the key, and an absent key SHALL mean "not observed", never "nothing skipped". The base report that
held the tests as skipped SHALL be named (`step 1 base run`, `an earlier round's record` or `a base worktree run`) in
`tests_ran.summary.skipped_source`, in the hold's view and in its question, and in neither the hold's text nor its
binding, so that the same file and ids read in another report are the same hold. Not told apart, and said so in the
question, in the Evidence line and in the runbook, in these words and no others: production code the unit changed, a module the file imports that the unit did not change (an added import is allowed only from the standard library), run-time or import-time state that another test sets (its body, decorator or default values), a changed sibling test module the file imports, and dynamic forms and plugins that read test names (`exec`, `getattr`, `importlib`, `globals()`, a plugin such as test dependencies), where the tests were
skipped at the base too for another reason (what (e) bounds is where the unit changed the file; it does not read
behaviour). The base report is a run without the network and without `PYTEST_ADDOPTS`, while the head's gate has `gates.network`:
a skip that depends on the network can look skipped at the base only. [V, the code: step 3 compared nothing with the base, and
a fix chore puts every test path back, so no fix unit could make a skipped test run]

#### Scenario: SCN-VER-372 (+) A stack-gated test whose assertion the unit edited is a hold
- **Given** `tests/test_live.py` at the base has `@pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason=...)` on `test_a` and `test_b`, the unit changed one assertion line in each, and both the gate report and the base's report hold both as `skipped`
- **When** step 3 collects evidence
- **Then** the round has no finding `existing tests are skipped in a changed test file`
- **And** it has one hold `skipped: existing tests in `tests/test_live.py` were also skipped in a base report, and the file adds or changes no skip the harness reads (2 tests)`, the verdict is NEEDS_HUMAN, and `tests_ran.summary.skipped_predating` lists both ids

#### Scenario: SCN-VER-373 (−) A skip the unit added stays a deterministic finding
- **Given** the unit added `@pytest.mark.skip` above `test_a`, which exists at the base, and `test_a` is skipped
- **When** step 3 collects evidence
- **Then** the major finding names `test_a`, there is no hold for it, and no person can waive the finding
- **And** a decorator that is no plain `pytest.mark.<name>` is no free change (L4-VER-092 (e)), so `test_b` of the same file is in the finding too; when the unit instead added a `pytest.skip(...)` call to the body of `test_a`, `test_b` stays in the hold of the file (SCN-VER-375)

#### Scenario: SCN-VER-374 (−) A changed condition on a continuation line is a changed skip
- **Given** `test_a` carries a two-line `@pytest.mark.skipif(` whose second line the unit changed from `os.getenv("A") != "true"` to `os.getenv("B") != "true"`
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold
- **And** a changed decorator of `test_a` is no free change for `test_b` either: it is in the finding too (L4-VER-092 (e))

#### Scenario: SCN-VER-375 (+/−) A skip call the unit added to the body of one test does not touch another test of the file; a skip decorator keeps both in the finding
- **Given** the unit added a `pytest.skip(...)` call to the body of `test_a`, `test_b` was skipped by an unchanged `skipif` and is skipped now
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and `test_b` is in the hold of the file
- **And** when the unit added `@pytest.mark.skip` above `test_a` instead, both are in the finding: a `skip` decorator is no plain mark, and no decorator that is none is a free change

#### Scenario: SCN-VER-376 (−) A skip construct in a shared scope touches every test of the file
- **Given** one of: the unit added `pytestmark = pytest.mark.skipif(...)`; added `docker = pytest.importorskip("docker")` at module level; gave a fixture of the file a `pytest.skip(...)` call
- **When** step 3 collects evidence
- **Then** every old skipped test of the file is in the finding and none is in a hold
- **And** when the unit instead applied an alias that the base already defines (`@requires_stack`) to the old test `test_a` only, `test_a` is in the finding, and so is `test_b`, skipped by an unchanged `skipif`: (b) alone would keep it in the hold, because an alias use is scoped to the function it decorates (D3), but a decorator that is no plain `pytest.mark.<name>` is no free change of the file (L4-VER-092 (e))

#### Scenario: SCN-VER-377 (−) A file or test that cannot be compared stays a finding
- **Given** each of: the test file is new in the unit; the file was renamed; the skipped test did not exist at the base (renamed or moved to another class); the head blob does not parse; the base blob is over `MAX_SOURCE_BYTES`; `git show` fails
- **When** step 3 collects evidence
- **Then** the old skipped tests of that file are in the finding and in no hold, and no exception escapes the evidence step

#### Scenario: SCN-VER-378 (+/−) A changed support or runner-configuration file keeps the finding
- **Given** `test_a` is skipped at the base and at the head by an unchanged `skipif`, and the unit changed only its test file
- **When** step 3 collects evidence
- **Then** `test_a` is in the hold
- **And** when the unit also changed `tests/conftest.py` (or a file of `tdd.runner_config_files`), `test_a` is in the finding instead, with or without a skip construct in the file: the skip may come from the changed file

#### Scenario: SCN-VER-379 (+) The hold is raised when diff coverage is off
- **Given** `verifier.evidence.diff_coverage.mode: off` and the case of SCN-VER-372
- **When** the ladder runs
- **Then** the hold is in `result.holds` and is asked, and it is in `later_holds` of no step

#### Scenario: SCN-VER-380 (+) Nothing changes when no skip predates the unit
- **Given** `check_tests_ran` is called without `predating`, or with an empty set
- **When** an old skipped test lies in a changed file
- **Then** the finding and `TestsSummary` are as before, and a `verdict.json` that has no `skipped_predating` reads as an empty tuple

### Requirement: L4-VER-093 The skipped-test hold is asked as a verdict question, bound to the file, and its reject makes no fix unit
The hold of L4-VER-092 SHALL be asked like any hold (`Kind: verdict`, target `H-` and eight hex digits of its text). Its
kind SHALL be read from the text prefix `skipped: existing tests in ` (`hold_kind` returns `skipped`); `hold_subjects`
SHALL return none for it, so no judge finding is settled by its answer. The question SHALL name the file and the count,
list the skipped test ids, name the base report that held them as skipped, say what was compared (the file adds or
changes no skip construct the harness reads, nothing inside the file that decides whether an unchanged skip skips, the
unit changed the file only in places that cannot change why a test skips, and no support, runner, setup or dependency file
changed) and what is not told apart (production code the unit changed, a module the file imports that the unit did not change (an added import is allowed only from the standard library), run-time or import-time state that another test sets (its body, decorator or default values), a changed sibling test module the file imports, and dynamic forms and plugins that read test names (`exec`, `getattr`, `importlib`, `globals()`, a plugin such as test dependencies)), say that an `accept` means the person ran them where they can run or knows they pass there and holds for this
content of the file only, and say that `reject: <reason>` ends the round because a fix unit cannot change test files. A
person's `accept` SHALL be bound (`result.hold_views`) to the head blob of the file and the full sorted list of its
skipped ids, so that an edit of the file or a change of the skipped set voids it and the hold is asked again. An `accept`
SHALL waive the hold. A `reject`, with or without a reason, with or without a `WHEN ... THEN ...`, SHALL become a finding
of source `human`, severity major, titled `Rejected hold: a skipped test is not accepted`, which the fix planner SHALL
list as not converted; no fix unit SHALL be written for it; the round SHALL end escalated with the reason
`skipped_tests_rejected`, and `l4 status` SHALL say the way out: a commit of the person's own on the unit branch that
removes the skip or makes the tests able to run in the gate, then `l4 retry --unit <unit> --reason TEXT`, or an accept
that replaces the answer once the tests ran. A reject of this kind beside another finding of a person that cannot be
converted into a fix task (or a reject of a hold on the judge's view) SHALL keep the code `skipped_tests_rejected` and its
way out, and the reason text of the escalation SHALL say that another finding of a person also cannot be converted into a
fix task; the other way out shows once this one is resolved.

#### Scenario: SCN-VER-394 (−) A test that ran at the base is not a predating skip
- **Given** `test_a` ran (status `passed`) in the base's report and is `skipped` at the head, and one of: it gained a marker imported from another module (`from tests.markers import requires_stack`, `@requires_stack`); the variable of an unchanged `skipif(not HAS)` changed from `HAS = True` to `HAS = False`; its class newly inherits a base class that is skipped
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold, whatever the constructs of the file say

#### Scenario: SCN-VER-395 (−) A fixture, a block, a run-time marker or an alias counts as a skip the unit added
- **Given** `test_a` was skipped at the base and at the head, and the unit added one of: a `pytest.skip(...)` call to a fixture whose name starts with `test` (`test_env`) or is any other (`@pytest.fixture`, with or without arguments, `@pt.fixture`); `pytestmark = pytest.mark.skip` in a module-level or class-level `if`, `try`, `with` or `for` block; `request.node.add_marker(...)`, `item.add_marker(...)` in a collection hook of the file, or `pytestmark.append(pytest.mark.skip)`; a skip through `import pytest as pt`, `from pytest import mark as m` (`@m.skip`), `import unittest as ut` (`@ut.skip`) or `skip = pytest.skip`
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold

#### Scenario: SCN-VER-396 (+) The base report is read from step 1, an earlier round or a base worktree run, in that order
- **Given** a skipped test of a changed file passes the rest of L4-VER-092
- **When** step 3 collects evidence
- **Then** the report is step 1's reference of the round when it is a full report of the base, else the `skipped` list of the newest earlier round's `integrity.base_tests` of the same base sha and command that has the key (a record without it is passed over), else one run of the test gate in a base worktree
- **And** the base's gate runs at most once in a round, and a run of the lookup is written into the round's `integrity.base_tests` so that later rounds read it (SCN-VER-402); no skipped test of a changed file that passes the rest means no lookup and no run

#### Scenario: SCN-VER-397 (−) No base report with statuses keeps the finding and says why
- **Given** the case of SCN-VER-372 and no report: step 1 had none, no earlier record has a `skipped` key, and the base worktree run gave no report or failed
- **When** step 3 collects evidence
- **Then** both tests are in the finding and in no hold, no exception escapes the evidence step, and the step note and `tests_ran.summary.skipped_note` say `no base report with statuses: <why>`

#### Scenario: SCN-VER-398 (+) The record carries `skipped` only when the base report was seen whole
- **Given** step 1's reference R0 is a cached baseline or a base worktree run, or is rebuilt from an earlier round's passed ids, or is the head's own run with the base's test files (`not needed`)
- **When** step 3 collects evidence
- **Then** `integrity.base_tests` has `skipped` (sorted ids) in the first case (and when step 3's lookup ran the base's gate itself, whether step 1 wrote a record or not) and no `skipped` key in the other two: an absent key is "not observed", never "nothing skipped", and the implementer's baseline is not changed

#### Scenario: SCN-VER-399 (+) A fixing unit retried after an older harness gets its base report from a base worktree run
- **Given** the earlier rounds' records carry `base_tests` without a `skipped` key (an older harness) and the fresh round after `l4 retry` is verified under the release
- **When** step 3 collects evidence
- **Then** that round runs the base's test gate once in a base worktree, holds the old skipped test as skipped, and has the hold and no major
- **And** when that run gives no report the round keeps the major and says why

#### Scenario: SCN-VER-400 (−) A flag, a guard, a helper, a fixture or an import that the unit changed under an unchanged skip keeps the finding
- **Given** `test_a` was skipped at the base and at the head by a skip construct whose text the unit did not change, the base report holds it as skipped, and the unit changed one of: `FLAG = True` to `FLAG = os.environ.get("Z") is None` under `@pytest.mark.skipif(FLAG, ...)`; the condition of a guard in the body, `if not os.environ.get("S"): pytest.skip(...)` to `if True: pytest.skip(...)`, or the setup before it; the body of `has()` under `@skipif(not has(), ...)`; a flag that a flag reads; a class-level flag, a base class, or a `setUp` of its class; a fixture the test takes or an `autouse` fixture; a from-import that a skip reads (`from helpers import has` to `from other import has`); a `pytestmark = ...` whatever its value
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold, because the dependency closure of its skip is not the same at the base and at the head
- **And** a skip whose closure is the same, with an assertion after the guard, a whole new standard library import of an unused name, or a new test added, stays in the hold of the file (an unrelated flag or helper of the module is no part of the closure, and is refused by (e): SCN-VER-406)

#### Scenario: SCN-VER-401 (+) Changes outside the closure of the skip leave the hold
- **Given** a module with `INTEGRATION = pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason=...)` and several tests marked `@INTEGRATION`, all skipped at the base and at the head, and the unit changed one assertion line and added a comment inside two of the test bodies, added an import, and added a test that is not skipped (the same change as SCN-VER-405; a name added to an `import` line the base has is a changed line outside a test, and is refused by (e))
- **When** step 3 collects evidence
- **Then** the skipped tests are in the hold of the file and in no finding, and a file of 600 skipped tests is decided in seconds: the file is read, parsed and scanned once for the path, not once for each test

#### Scenario: SCN-VER-402 (+) One base worktree run serves the later rounds of a unit, and a failed one is not run again
- **Given** the records of rounds 1 and 2 have `base_tests` without a `skipped` key, and rounds 3 to 6 are each verified on a workbench of their own, with the old skipped tests of a changed file passing the rest of L4-VER-092
- **When** step 3 collects evidence in each of those rounds
- **Then** the base's test gate runs once in a base worktree, in round 3, and `integrity.base_tests` of round 3 carries `skipped` (and `passed` and `collection_errors` when step 1 wrote no record); rounds 4 to 6 read it as `an earlier round's record` and run nothing
- **And** a base run that gave no report, or whose checkout exited (`gates.setup failed at the merge base`), is not run again in the same round by the second asker (step 1 and step 3 together), writes no `skipped`, and leaves the first line of the exit's message, redacted, in the step note (any other failure of the run is kept the same way: SCN-VER-408)

#### Scenario: SCN-VER-403 (−) A runner file by name in any directory, and a renamed support file, keep the finding
- **Given** `test_a` is skipped at the base and at the head by an unchanged `skipif`, and the unit also changed `services/api/tests/pyproject.toml` (or a `pytest.ini`, `setup.cfg`, `tox.ini` or `conftest.py` in any directory), or renamed `tests/conftest.py` to `tests/conftest_bak.py`
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold: the file name is read in any directory, and a rename counts at its old path too

#### Scenario: SCN-VER-405 (+) A change confined to comments, blank lines, test bodies beyond the skip and a new import leaves the hold
- **Given** a module with `INTEGRATION = pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason=...)` and several tests marked `@INTEGRATION`, skipped at the base and at the head, and the unit changed one assertion line and added a comment line inside two of the test bodies after any skip, added `import json` (a standard library module, and a name the base does not bind, load, spell in a string or name in a condition), and added a test that is not skipped at the end
- **When** step 3 collects evidence
- **Then** the skipped tests are in the hold of the file and in no finding, and the same holds for a comment-only change at module level, a blank line added or removed between functions, a whole new test method in a test class, a changed body of a test that is not the one asked about, a `pytest.mark.<name>` (a name that is not `skip`, `skipif`, `xfail`, `usefixtures` or `parametrize`) added to or removed from a test, and a statement added after the last skip of the test's own body
- **And** the base report was asked once, and the file is read, parsed, tokenized and paired once for the path, not once for each test

#### Scenario: SCN-VER-406 (−) A change outside those places keeps the finding, whatever the lists of (b) and (d) see
- **Given** `test_a` was skipped at the base and at the head, the base report holds it as skipped, and the unit changed the file in one of these places: a flag that a string condition names (`skipif('FLAG')`); a class attribute that the body reads through `self`, or an added `setup_method`, or a base class's attribute or method; a helper method that calls the method that skips; a fixture reached through `pytestmark = pytest.mark.usefixtures(...)`, `@pytest.mark.usefixtures(...)` or `request.getfixturevalue(...)`; a module binding that a class binding hides; a statement run at import (`cfg.enabled = True`, `os.environ[...] = ...`, `ITEMS.append(1)`, `del FLAG`, `setattr(sys.modules[__name__], ...)`); a name bound by `for`, `with`, `:=`, `except ... as` or `match`; a `from x import *`; a module `__getattr__`; a changed module docstring, a statement added to or removed from the module, a class attribute, `setup_method`, helper or fixture; the decorators, the signature (its default values too) or the statements up to the last skip of `test_a` itself (or the one that calls `request.getfixturevalue(...)`); a test that a skip condition, a helper or the prefix of `test_a` calls or names (`skipif('test_check()')`, `self.test_helper()`) and whose body changed; an import that binds a name the base binds, loads or names in a condition, a builtin, `os`, `sys`, `platform` or `config`, a `*` or a `__future__` import, or an import beside another statement on its line; a deleted `def` line (so that its body joins the function above) or a `def` inserted in the middle of a helper; an added import of a module that is not of the standard library or is relative (`from helpers import pytestmark`, `import env_setter`, `from . import x`), one that binds a name a runner reads off a module (`setup_module`, `load_tests`, `pytest_generate_tests`) or a name the base spells as a parameter, a fixture or a string (`usefixtures("db")`); a test two or more calls away from the skip whose body changed (`self.test_mid()` that calls `self.test_inner()`); a decorator of any collected test that is not a plain `pytest.mark.<name>` added, removed or changed (`@pytest.fixture` through an alias, `functools.partial(pytest.fixture)`, `skip`, `parametrize`), also on a new test; a body that mentions `getfixturevalue` (an alias, `getattr(request, "getfixturevalue")`) changed anywhere; a statement of the body up to the last `raise`, `Skipped`, `SkipTest` or `skip.Exception` of `test_a` changed
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold, because the changed line is not a comment, a blank line, a line of a collected test beyond what skips `test_a`, a plain mark of a test, or a whole new standard library import of a free name
- **And** a test whose changed place is another test's body that sets run-time state, and a dynamic form there (`globals()`, `exec`), stay in the hold, also when its decorator is a plain `pytest.mark.<name>` with an expression in its arguments or its defaults run at import: that is the residual of L4-VER-092 (the production code, an imported module, run-time or import-time state, a sibling test module, dynamic forms and plugins)

#### Scenario: SCN-VER-407 (−) A file that sets up the interpreter or the dependencies, and a support module of the tests tree, keep the finding
- **Given** `test_a` is skipped at the base and at the head by an unchanged `skipif`, and the unit also changed `sitecustomize.py`, `usercustomize.py`, `noxfile.py`, `setup.py`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `pdm.lock`, a `requirements*.txt` or a `constraints*.txt` (in any directory), or added, changed, deleted or renamed a `.py` file under a path that matches `tdd.test_globs` and that defines no test (`tests/__init__.py`, `tests/util.py`)
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold, and the base report is not asked for
- **And** a changed `.py` file outside the tests tree, and a changed test file that defines a test, are not by themselves a reason

#### Scenario: SCN-VER-408 (+/−) A failure of the base run that is not an exit is kept for the round too
- **Given** the lookup of SCN-VER-402 and a base worktree run that fails with an exception that is not an exit of the checkout (a full disk, a git error)
- **When** the lookup is asked twice in the round, and a second lookup object asks too
- **Then** the first answer is no report, with the type and the first line of the message, redacted and cut, in the note (`no base report with statuses: OSError: ...`), the same answer comes back each time, the base's gate ran once, and every test of that file stays in the finding

#### Scenario: SCN-VER-409 (−) An added import is allowed only from the standard library and takes no name that a runner or a fixture reads
- **Given** `test_a` was skipped at the base and at the head by an unchanged `skipif`, the base report holds it as skipped, and the unit added one import line: `from skipmod import pytestmark`, `from helpers import autouse_net`, `import env_setter`, `import numpy` (under `skipif("numpy" not in sys.modules)`) or `from . import helpers` (not of the standard library, or relative); `from json import load as setup_module`, `as pytestmark`, `as pytest_generate_tests`, `as setup_function`, `as load_tests`, `as test_x` or `as TestX` (a name a runner reads off a module); or an import of the standard library that binds `db` while the base has a parameter `db`, a fixture `db`, or a string `"db"` (`usefixtures("db")`, `getfixturevalue("db")`, `depends=["db"]`)
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold
- **And** `import json` of a name the base does not spell stays in the hold (SCN-VER-405)

#### Scenario: SCN-VER-410 (−) A test reached through another test, and a decorator that is not a plain mark, keep the finding
- **Given** `test_a` was skipped at the base and at the head, the base report holds it as skipped, and the unit changed the body of `test_inner`, which `test_mid` calls (`self.test_inner()`), which `test_a` calls in a guard or a decorator (`self.test_mid()`), or which a helper that `test_a` calls reaches the same way; or the unit added, removed or changed a decorator of any collected test that is not a plain `pytest.mark.<name>`: an alias of `pytest.fixture` (`@fx(name="res")`, `functools.partial(pytest.fixture)`) on a new test, a `skip`, `skipif`, `xfail`, `usefixtures` or `parametrize` mark, a `retry` or `mock.patch` decorator
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold, the tests reached through each other being kept whole until no new one is reached
- **And** a `@pytest.mark.slow` (a name that is none of those five) added to or removed from any test, also a new one, stays in the hold

#### Scenario: SCN-VER-411 (−) A body that runs a fixture by a string, a raise and a skip exception end the free part of the body
- **Given** `test_a` was skipped at the base and at the head, the base report holds it as skipped, and the unit changed a line of its body that is before or at a `raise` (of anything) or a name `Skipped`, `SkipTest` or `skip.Exception` (`if x: raise Skipped("old")` to `if not x: raise Skipped("old")`), or any line of a body that mentions `getfixturevalue` (`get = request.getfixturevalue`, `getattr(request, "getfixturevalue")`)
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold, and a comment line in those bodies, or a change after the last of those statements, leaves the hold

#### Scenario: SCN-VER-381 (+) The question names what a person needs to decide
- **Given** the hold of SCN-VER-372
- **When** the verdict question is raised
- **Then** its context lists `tests.test_live::test_a` and `tests.test_live::test_b`, names the base report that held them as skipped, says what was compared (the file adds or changes no skip construct the harness reads and nothing inside the file that decides whether an unchanged skip skips, the unit changed the file only in places that cannot change why a test skips, no support, runner, setup or dependency file changed) and what is not told apart (production code the unit changed, a module the file imports that the unit did not change (an added import is allowed only from the standard library), run-time or import-time state that another test sets (its body, decorator or default values), a changed sibling test module the file imports, and dynamic forms and plugins that read test names (`exec`, `getattr`, `importlib`, `globals()`, a plugin such as test dependencies)), offers `accept` and `reject: <reason>`, and does not ask for a `WHEN ... THEN ...`

#### Scenario: SCN-VER-382 (+) An accept waives the hold and the round can pass
- **Given** the hold of SCN-VER-372 and `accept ran against the stack on 2026-11-25`
- **When** the next round ends with no other finding
- **Then** the hold is resolved, the verdict is PASS, and the question is not asked again

#### Scenario: SCN-VER-383 (−) An edit of the file voids the accept
- **Given** the accept of SCN-VER-382 and a later commit that changes `tests/test_live.py`
- **When** the next round runs
- **Then** the hold has a new binding, the accept is not in force, and the hold is asked again

#### Scenario: SCN-VER-384 (−) A reject is the person's finding and makes no fix unit
- **Given** the hold of SCN-VER-372 and `reject: run them in the gate. WHEN the gate runs THEN they pass`
- **When** the round settles its holds
- **Then** there is one finding titled `Rejected hold: a skipped test is not accepted`, source `human`, with the person's text
- **And** the fix planner lists it as not converted (the scenario does not make a task), no fix unit is written, and the unit is escalated with `skipped_tests_rejected` and the way out of this requirement

#### Scenario: SCN-VER-385 (+) An accept does not settle a judge finding about the file
- **Given** the hold of SCN-VER-372 and a blocking judge-only finding whose text names `tests/test_live.py`
- **When** the hold is accepted
- **Then** the finding is not settled by it and is asked on its own

### Requirement: L4-VER-094 Only a person answers a skipped-test hold
The delegate SHALL NOT answer a skipped-test hold: `_without_a_call` SHALL return a reason for kind `skipped`, so the
question is escalated to a person with no model call, and `check_reply` SHALL refuse both an accept and a reject of it
with status `escalated`. The delegate prompt SHALL say so. A verdict of such a hold whose `by` is not `human` (`agent`,
`delegate`, `clarifier`, as `clarifier.answer_by_agents: true` allows an agent to write one) SHALL NOT be in force: step
10 SHALL drop it, SHALL record `human.void{question, target, reason}` once for its question, and the hold SHALL be asked
again by the next round.

#### Scenario: SCN-VER-386 (−) The delegate neither answers nor is called
- **Given** the delegate is on and a skipped-test hold is open
- **When** the delegate pass runs
- **Then** no model call is made for the question, it is escalated with the reason `a skipped-test hold is a person's decision`, and the unit stays in `awaiting_human`

#### Scenario: SCN-VER-387 (−) A reply that reaches `check_reply` is refused
- **Given** a delegate reply of `accept` or of `reject` with a `WHEN ... THEN ...` for a verdict question whose target is a skipped-test hold
- **When** `check_reply` runs
- **Then** it returns a discard with status `escalated`

#### Scenario: SCN-VER-388 (−) A model-authored answer is not in force
- **Given** `clarifier.answer_by_agents: true` and an `accept` of the hold recorded with `by: agent`
- **When** step 10 applies the verdicts
- **Then** the hold is unresolved, `human.void` is recorded for the question, the verdict is NEEDS_HUMAN and the next round asks the hold again
- **And** an `accept` with `by: human` is applied

### Requirement: L4-VER-095 A unit in `fixing` whose fix unit waits on a person can be retried
`l4 retry` SHALL be accepted for a unit in phase `fixing` when the open fix unit has at least one pending task and every
pending leaf of it is held by an open question (the planner's `fix unit questions open` state); in any other `fixing`
state it SHALL be refused with exit 2 as before, with the text `the fix unit <name> is running: the harness continues it
at the next run` when a task can run. The retry SHALL record `unit.retried` with `close_fix_unit: <name>` and start a run
as every retry does. In that run, before it selects a task, the harness SHALL, for each pending task of the fix unit,
tick it `already-done` in a harness commit (`L4-TDD: already-done`, `task.done{tdd: "already-done", closed_by: "retry",
reason}`, parents ticked), SHALL set the Status of each open question that held it to `superseded by retry` and record
`question.superseded` (before the commit that holds the question's new Status, so that the event travels inside it; when
that commit itself fails the ledger holds the event while the file still says open, until the next run, which closes the
fix unit again from its start because the request is still pending and records the event again with the same ids: a
known window, SCN-VER-404), and SHALL then end the fix unit with `fix.done`. A question set so SHALL hold no task, SHALL be
out of `questions.open`, and the label `l4:needs-answers` SHALL go; its text and the fix unit's other files SHALL be kept.
The unit SHALL go to `verifying` and the round SHALL be judged afresh. The fix round the closed unit used SHALL stay
counted. A person's own commit that ticks a task of a fix unit SHALL remain a step 1 blocker (`a protected path was
changed`); it is not a way to close one.
The run SHALL close a fix unit only when the same condition still holds when it reads the fix unit (an answer may have
come between the retry and the run): when a task of the fix unit can run, the run SHALL close nothing, SHALL record
`fix.close_skipped{fix_unit, reason}` and SHALL run the fix unit as it always does. The records of a close are
`unit.retried{close_fix_unit}`, `task.done{tdd: "already-done", closed_by: "retry"}` (also `fix_unit`, `reason`, `parents`),
`question.superseded{fix_unit, ids, closed_by: "retry"}` and `fix.done{closed_by: "retry"}`; the fold keeps the pending
close as `UnitState.close_fix_unit` until `fix.done` or `fix.close_skipped`. While a close is pending the planner fact
`UnitFacts.fix_closing` SHALL be true and `l4 plan` SHALL say `implement` with the reason `fix unit <name>: closed by the
retry at the next run` instead of `fixing: fix unit questions open`. For a unit in `fixing` whose open fix unit waits on
a person, `l4 status` SHALL name `l4 retry --unit <unit> --reason TEXT` as the way to close the fix unit, after
upgrading the pin to a release that has this requirement, and SHALL NOT tell anyone to tick a task by hand.

#### Scenario: SCN-VER-389 (+) A retry closes a fix unit that waits on its question and the parent verifies again
- **Given** the pin is the release, `openspec:<name>` is `fixing` with `<name>-fix-2` whose only task 1.1 is held by an open technical question Q-001, and two of three fix rounds are used
- **When** a person runs `l4 retry --unit openspec:<name> --reason "skipped tests are env-gated, see the hold"` and the run starts
- **Then** task 1.1 is ticked in a harness commit with `L4-TDD: already-done`, Q-001's Status is `superseded by retry`, `fix.done` is recorded, and the unit goes to `verifying`
- **And** the new round, judged afresh, has the hold of L4-VER-092 and no finding for the skipped tests, the verdict is NEEDS_HUMAN, and no `-fix-3` is written

#### Scenario: SCN-VER-390 (+) The question no longer blocks anything
- **Given** SCN-VER-389 after the close
- **When** `l4 plan` and `l4 questions list` run
- **Then** neither reports a fix unit question as open, and `l4:needs-answers` is not set for Q-001

#### Scenario: SCN-VER-391 (−) A fix unit that can run is not closed
- **Given** `openspec:<name>` is `fixing` and a task of its open fix unit is not held by any question
- **When** a person runs `l4 retry --unit openspec:<name> --reason TEXT`
- **Then** it exits 2 with `the fix unit <name>-fix-2 is running: the harness continues it at the next run`, and no event is recorded

#### Scenario: SCN-VER-392 (−) A person's tick of the fix unit's task is a blocker, not a way out
- **Given** a person's commit that changes `<name>-fix-2/tasks.md` from `- [ ] 1.1` to `- [x] 1.1`
- **When** the parent is verified
- **Then** step 1 has the blocker `a protected path was changed` naming `<name>-fix-2` and the non-harness commit, as for any person's commit on a fix unit's folder other than `questions.md`

#### Scenario: SCN-VER-393 (−) The same retry on the old harness spends the last fix round
- **Given** the unit's pin is the release before this change
- **When** the verification runs again after any way of closing the fix unit
- **Then** the old finding is raised again as a deterministic major and the round spends the last fix round: this is why the runbook says to upgrade the pin first, and the `l4` of the person is the pin or newer (an older `l4` refuses state-changing commands, L4-OPS-026)

#### Scenario: SCN-VER-404 (+/−) A close whose commit fails is repaired by the next run
- **Given** the retry of SCN-VER-389 and a run whose closing commit of the fix unit's task fails after `question.superseded` was recorded
- **When** that run ends (exit 1) and the next run starts
- **Then** after the failed run the ledger of the unit holds `question.superseded` while `questions.md` still says `open`, the task is unticked and `close_fix_unit` is pending, and `l4 status` and the plan read the question as closed
- **And** the next run closes the fix unit from its start: the tick, `superseded by retry`, `question.superseded` again with the same ids, `fix.done`, a fresh round, and no question open
