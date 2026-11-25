## Context

Read at `next-int` (50bb9526). Labels: [V] read in code or ledger text, [I] inferred from code, not run, [U] not verified.

- `src/l4/evidence/testsran.py:113-122`: `old_skipped` is every skipped id that is not new; `touched` is the part whose
  file is in `changed` (`file_of_test`, `:46-78`, which builds `.py` paths only); each `touched` id is named in one
  `Severity.MAJOR` finding, source `deterministic`. No base data is read [V].
- `src/l4/verifier/ladder.py:970-995` (`_collect_step`) adds `ev.ran.findings` to the round. `:998-1013`
  (`_quality_step`) adds `ev.later_holds`, and returns first when diff coverage is off or has no evidence [V].
- `src/l4/evidence/collect.py:54-67` (`Hold.kind` is `scope | coverage | unsafe`), `:81-84` (`later_holds` is
  `hold_records[scope_holds:]`), `:321-341` (the tests-ran call and the `records` list) [V].
- `src/l4/verifier/verdicts.py`: a hold is a plain `str` in `result.holds`; its kind is read back from its text by
  `hold_kind` (`:110-119`: scope, judge_view, coverage, else `other`). `_hold_question` (`:751-815`), `_hold_finding`
  (`:240-284`), `settle_holds` (`:287-325`), `hold_sha256` (`:328-332`) and `subsumed_findings` (`:161-174`) all work from
  that text and from `result.hold_views` [V].
- `src/l4/verifier/ladder.py:1091-1139` (`_finalize`): the accept of a hold stays in force while its `text_sha256` equals
  `hold_sha256(hold, result.hold_views)`; `effective_verdicts` (`verdicts.py:457-506`) never reads `by` [V].

## Goals / Non-Goals

Goals: a person can waive a skip that the unit did not make; a skip the unit made stays a deterministic finding; no new
dead end (a fix unit that cannot fix); an already open fix unit for the old finding can be closed without forging
anything.

Non-goals: see the proposal. In particular, no non-Python skips (D1), no change to what a fix
chore may edit (D4).

## Decisions

### D1. The base report as a necessary condition, and the rule beside it (L4-VER-092)

Question 1 of the brief: does the verifier hold a base-side report? The first version of this change said no and decided
from the AST alone. An adversarial review showed that a unit which ADDS a skip can still be read as not having added
one, whenever the skip reaches the test by a path that a comparison of the file's own constructs cannot see: a marker
imported from another module (`from tests.markers import requires_stack`, `@requires_stack`), a condition variable that
the unit changed under an unchanged `skipif(not HAS)`, a test class that newly inherits a skipped base class, a skip
added to a fixture whose name starts with `test`, a marker added at run time, a mark under a module-level `if`, an
alias of pytest. So the rule has two necessary conditions: the AST rule, and a base report.

What exists [V, read in code]:

- Step 1's `check_base_tests` runs the gate at head with the unit's changed test and support files put back at their
  base version (`src/l4/verifier/base_tests.py`, `support_at_base`). That run, `r1`, is not a base report: it is the base's
  test files on the UNIT's code. The base reference `r0` is the base's own tests on the base's own code, read only when `r1`
  is not all green: from `wb.baselines` (source `baseline`), rebuilt from an earlier round's `integrity.base_tests`
  (source `evidence`: its `passed` list only), or from a run in a base worktree (source `base worktree`: `_base_reference`).
  `r0` comes with every status when its source is `baseline` or `base worktree`.
- When `r1` is all green, `r0` is `r1` ("not needed"): it says nothing about the base's statuses.
- The record `integrity.base_tests = {base_sha, command, passed, collection_errors}` kept `passed` only.

A test T (a JUnit id of an old skipped test of a changed file P) **predates** the unit when ALL of these hold; the first
that fails makes T a deterministic finding as today (fail closed):

(a) **A base report with statuses holds T as `skipped`.** The report is the base's tests on the base's code. Where it
comes from, in this order (`base_tests.SkipLookup`):

1. step 1's `r0` of this round, when its source is `baseline` or `base worktree` (a full report). It is handed over on
   `Outcome.base_report` to the ladder's `_Run`, never stored into `wb.baselines`, whose meaning belongs to the
   implementer. `r1` is never used, and neither is an `r0` rebuilt from passed ids or equal to `r1`;
2. the newest earlier round's `integrity.base_tests` with the same base sha and test command that HAS a `skipped` key.
   A record without the key is passed over: it was written by an older harness, or by a round whose `r0` was not a full
   report. An absent key means "not observed", never "nothing skipped". Step 1 writes `skipped` (the sorted ids whose
   status is `skipped`) only when its `r0` came from a full report (source `baseline` or `base worktree`); `_evidence`
   and `_base_reference` are unchanged and step 1 still does not skip its own check;
3. one run of the test gate in a base worktree, as `_base_reference` does (`base_checkout`, `run_gate_at`, network off),
   its result, a full report or the reason there is none, kept on `wb.base_runs` (its own attribute) so that no
   round runs it twice, a failed run included, whatever the failure (an exit of the checkout, or any other exception: a
   second asker of the round gets the same reason and no second run; Review H, note A: the exceptions that were not an
   `L4Exit` were not kept, so a second asker ran the gate again; the message is the first line, redacted and cut, with
   the type of an exception that is not an exit).
   The verifier builds a workbench for each round (`ladder.bench`), so `wb.base_runs` lives for one round. What
   carries a base worktree run to the next round is the record: when the lookup got its report from such a run it
   writes `skipped` into this round's `integrity.base_tests` (and the whole record, `passed` and `collection_errors`
   included, when step 1 wrote none), and the next round's lookup finds it at source 2 (`SkipLookup.record`, called by
   `_collect_step`; also when the collection of evidence raises). Only a full report is ever written. The lines that
   copied `base_skips` to a workbench rebuilt after a limit or an escalation (`orchestrator._escalate`,
   `_fall_back`, `fixloop._escalation`, `_fall_back`) read nothing: only the verifier makes this run, and the
   workbench of an implementer step never does. They were removed.

The lookup is made only when a skipped test of a changed file passes (b) and (c): no such test, no lookup and no run.
Cost: at most one extra run of the base's test gate in a round, and only when step 1 had no full report, no earlier
round recorded the statuses, and such a test exists; once a round has run it, the record of that round holds the
statuses and no later round runs it again for this base and command. When no source gives a report (the gate gave none, or raised), every
such test stays a finding, and the step note and `tests_ran.summary.skipped_note` say `no base report with statuses:
<why>`. The lookup runs inside the never-raises wrapper of `collect.skip_predating`: `_collect_step` drops all evidence
when `collect_evidence` raises, which would drop the finding.

(b) **The skip constructs of P, compared at the base and at the head on the AST** (`scan.skip_constructs`). This is what
step 1 already does to find a skip the unit added, `scan.skip_markers(after) - scan.skip_markers(before)` per file
(`src/l4/verifier/integrity.py`, blocker `a skip or xfail marker was added`) [V]. That function counts markers per test
name, so it misses a changed condition (the count stays 1), an alias (`requires_stack = pytest.mark.skipif(...)`, then
`@requires_stack`), `pytest.importorskip` and a condition on a continuation line. A line-token diff of the hunks (`-U0`)
misses the last one too, and flags every test of the file for one added skip. So this change adds `scan.skip_constructs`,
described in D3, and leaves `skip_markers` and the step 1 check alone. Concretely:

1. `name_status` (and `changed_files`, which drops the old path) reports P with status `M` (`collect.py`: an added file is
   `A`; a rename is reported `R` at its head path, with its old path beside it, so a moved test is never predating). A new file is already the blocker `new tests were skipped` or `new
   test file ran no test` (`testsran.py`).
2. The blobs of P at base and at head are read with `show_blob` and both parse; a git error, a file over
   `MAX_SOURCE_BYTES` or a syntax error is a failure of this rule, never a pass.
3. T maps to a qualified name `q` of P (module, class parts of the id's classname, function without `[param]`; module
   functions and methods of module-level classes only, as `scan._qualified` does), and `q` is **collected as a test** at
   the base: its name starts with `test` and it is not decorated with `pytest.fixture` in any form
   (`scan.collected_tests`; `defined_tests`, which step 1 uses, is unchanged). A test that did not exist at base, was
   renamed, or moved to another class is not predating.
4. The unit added no skip construct in a **scope that can skip q**: `new = constructs(head) - constructs(base)`
   (multiset difference, so removing a skip never matters and one more of the same text does); `new` has no entry whose
   scope is `q`, `q`'s class, `<module>`, or a function or method of P that is not a collected test (`scan.shared_scopes`:
   a fixture whatever its name, a helper, `setUp`, a collection hook). An added skip on another test does not touch q.
5. The file is read once per path: `skippred.SkipRule` parses and scans the base and the head blob once and answers each
   test of the file against that (`skipdeps.SkipFacts`: the constructs, the collected tests, the shared scopes, the
   bindings of the module and of each class, computed once). The first version scanned the file again for each test:
   600 skipped tests of one file took 82 seconds, now 0.2.

(c) **No support or runner-configuration file changed, unconditionally.** The unit's diff changed no file that matches
`tdd.test_support_globs` or `tdd.runner_config_files` (`cfg.tdd.test_support_globs`, `cfg.tdd.runner_config_files`), and
none whose NAME is `conftest.py`, `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `pyproject.toml`, `setup.cfg`
or `tox.ini`, in any directory (a root-anchored glob misses a nested one). A rename counts at its old path too
(`tests/conftest.py` renamed to `tests/conftest_bak.py` takes the support file out of the run, which can unskip or
skip). The first version dropped this check whenever the file held a construct in scope; a changed `conftest.py` can skip
a test whatever the file says, so the shortcut is gone. Review H added what else sets up the interpreter, the
dependencies or the tests tree, by name anywhere in the tree: `sitecustomize.py`, `usercustomize.py`, `noxfile.py`,
`setup.py`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `pdm.lock`, `requirements*.txt` and `constraints*.txt`; and
any changed `.py` file under a path that matches `tdd.test_globs` that defines no test (an `__init__.py`, a helper, a module
a test imports: `collect._support_modules`, read at the head, and at the base for a deleted or renamed file, with the rule
of `support_base.is_support_source`, which is the rule of the support files the verifier already puts back for its own
runs). A test module that defines tests and that the file under review imports is not in this list: that is the residual
"a changed sibling test module the file imports" (D1 residuals), and the base report is what stands in front of it.

(d) **What decides an unchanged skip is unchanged: the dependency closure** (`skipdeps.SkipFacts.closure`). (b) compares
the text of the skip constructs; it cannot see that the unit changed WHY an unchanged construct skips: `FLAG = True` became
`FLAG = os.environ.get("Z") is None` under an unchanged `@pytest.mark.skipif(FLAG, ...)`; a guard `if not
os.environ.get("S"): pytest.skip(...)` became `if True: pytest.skip(...)`; the body of `has()` changed under
`@skipif(not has(), ...)`. The closure of the test q is a multiset of `(label, ast.dump)` pairs (no positions, so a
comment or a line wrap is no change) of
   - the skip-relevant **parts**: q's decorators; the decorators, bases and keywords of its class and the class-level skip
     statements; the module-level skip statements (a `pytestmark` assignment whatever its value, a module `importorskip`, a
     `pytest.skip(..., allow_module_level=True)`, a marker alias); the statements of q's body up to and including the last
     one that contains or encloses a skip call or marker, or that loads a name or calls a method of the class that skips
     (so a guard `if` and the setup before it are in, an assertion after it is not); the whole definition of each fixture q
     takes by parameter or `usefixtures` (and of the fixtures those take), of every `autouse=True` fixture, and of every
     function or method of the module or of q's class that no runner collects and that skips (`setUp`, a helper);
   - the **bindings** of every name those parts load and that the module (or q's class) binds: an import (per alias: an
     unrelated name added to the same `import` line is no change), a from-import, an assignment, an augmented or annotated
     assignment, a `def`, a `class`; a name bound inside a module-level `if` or `try` has the whole top-level statement as
     its binding, because the block's condition decides which binding is in force; then the names each binding loads, in
     turn, with a depth bound of 20 and a visited set (a longer chain is not compared: the test stays a finding).
   The closure of q at the base and at the head SHALL be equal, and q SHALL exist at the head. It is an equality, stricter
   than (b): removing one of two skip decorators of q is a difference too, and the skip stays a finding. An unrelated added
   import, an added test function, an unrelated flag or helper, and an assertion after the guard are not in the closure
   and (d) alone is not tripped by them. (e) is stricter on the file as a whole: of these only the added import (a whole
   new statement of a new name), the added test function and the assertion after the guard leave the hold, and an
   unrelated flag or helper does not (a changed line of the module outside a test). A module of `@INTEGRATION` tests
   whose unit changed an assertion and a comment in two of them, added an import and a new test is a hold for the skipped
   ones.

(e) **Where the unit may change the file: a whitelist** (`skipscope.Confined`; Review H, rework 9). (b) and (d) list what
decides a skip, and three review rounds kept finding an in-file way to change WHY an already skipped test skips that the
lists miss: a flag that a string condition names (`skipif('FLAG')`), a class attribute read through `self`, an added
`setup_method`, a helper method that calls the method that skips, a fixture reached through `pytestmark =
pytest.mark.usefixtures('res')` or `request.getfixturevalue('res')`, a module binding hidden by a class binding, a
statement run at import (`cfg.enabled = True`, `os.environ[...] = ...`, `ITEMS.append(1)`, `del FLAG`), a name bound by a
`for`, `with`, `:=`, `except as` or `match`, a `from x import *`, a module `__getattr__`. A list is a blacklist, and one
more entry is always found. (e) is the list the other way round: the unit may change the file only in these places, and
(b) and (d) stay as defence, so that (e) is what bounds the in-file cases. For a skipped old test T of a changed file,
EVERY changed line, a line of the base that the head no longer has (located in the base's tree) and a line of the head
that the base does not have (located in the head's tree), SHALL be one of:
   1. a blank line or a comment-only line, told with `tokenize`: a docstring is not a comment, and a blank line inside
      a string is not blank (its line holds a token of the string);
   2. a line inside a collected test (the notion of `skipdeps` and `scan.collected_in`: a function or method whose name
      starts with `test` and that `pytest.fixture` does not decorate; never a fixture, `setUp`, `setup_method` or a
      helper), existing at both sides or a whole new one at the head. For T itself, and for every test whose skip status
      is being decided (each one is asked on its own), a change to its decorators, to its `def` line and signature (its
      parameters are fixtures) or to the statements of its body up to and including the last one that contains or
      encloses a skip call or marker (the prefix of the closure, `SkipFacts.skip_relevant`), or the last one that calls
      `request.getfixturevalue(...)` (it runs a fixture that is named by a string, and a changed name is a changed skip), is not allowed. Rework 10 (Review J) widens the two ends of that prefix: it runs up to the last statement that holds a `raise` of anything, or a name `Skipped`, `SkipTest` or `skip.Exception` (a form of a skip that `skipdeps` does not read: `raise Skipped("old")`), and a body that mentions `getfixturevalue` anywhere, as an attribute, an alias (`get = request.getfixturevalue`), a name or a string (`getattr(request, "getfixturevalue")`), has no free line at all. A test that is not T may change whole and may be removed, and its signature too, but its decorators only in one way (rework 10, for any collected test, existing or new, candidate or not): a `pytest.mark.<name>` or `pytest.mark.<name>(...)` may be added or removed when `<name>` is not `skip`, `skipif`, `xfail`, `usefixtures` or `parametrize`; any other difference of the decorators (compared as trees, in order, with the plain marks left out) is a change. The first design took the decorators of a test that is not T for free (they cannot skip T), and a review found that a decorator runs when the module is imported and can be anything: an alias of `pytest.fixture` (`fx = pytest.fixture`, `functools.partial(pytest.fixture)`) turns a new `test_new` into a fixture that overrides one T takes, which the name-based check of fixtures does not see. A plain mark can still carry an expression in its arguments (`@pytest.mark.slow(ITEMS.append(1))`), which is the residual of import-time code. One exception, found in review: a collected test that the
      file reads by its name from a place that is not free is not free. `skipif('test_check()')`, a decorator that calls
      `test_check()`, a helper that does, `self.test_helper()` in a class statement or in the prefix of T make the body of that test a part of why T skips. The structure keeps such a test whole (tree and lines), and T's own parts (decorators, signature, prefix) are read for the names they reach. The reach is transitive (rework 10): a test kept whole is read for the names it reaches in turn, `self.test_mid()` that calls `self.test_inner()`, also through a helper that is not collected, until no new test is reached (a fixed point, over both sides);
   3. a whole new module-level `import M`, `import M as N` or `from M import a, b` statement, on lines of its own (not `import json; X = 1`), of a module of the standard library (rework 10: the top-level package is in `sys.stdlib_module_names`, so a module of the repository, a third party package and every relative import are out: an import runs a module's code, and the content of a module outside the file is not compared), that binds only names that the base module neither binds nor loads (a `Name` anywhere, a module-level `def` or `class`, an import alias anywhere, `global`, `except as`, a `match` capture) and that no string condition of a `skipif`, `xfail`, `skipIf` or `skipUnless` names, not `*`, not `__future__`, not a builtin and not one of the names pytest gives a string condition (`os`, `sys`, `platform`, `config`). Rework 10 adds the names that a runner reads off a module by convention (`pytestmark`, `setup_module`, `teardown_module`, `setup_function`, `teardown_function`, `setUpModule`, `tearDownModule`, `load_tests`, any `pytest_*` name, any name that starts with `test` or `Test`: a collected name or a hook), and the names that the base spells as a parameter (`ast.arg`: a possible fixture), as a fixture (the def's name and its `name=`) or as an identifier-like string anywhere (`usefixtures("db")`, `getfixturevalue("db")`, `depends=["a"]`: a name that is read by a string). The module's own dotted path counts too: no part of it may be an identifier-like string of the base, or a part of a dotted one, or a word of a string condition (`"json" not in sys.modules`, `hasattr(xml, "dom")`: loading the module changes `sys.modules` or sets a package attribute that a skip reads by its spelling). A base module that
      has a `from x import *` takes no added import. A test the head adds takes no name the base binds, loads or reads as
      an attribute.
   Nothing else at module level or class level is allowed: no other statement may be added, removed or changed, a module
   docstring, a class's decorators and bases, a class attribute, `setUp` and a helper included. If the line mapping fails,
   a blob does not parse or does not tokenize, a name is defined twice, a test is not collected at both sides, the coding
   line changed, or anything is ambiguous, (e) is False (the major).
   **What (e) leaves, said plainly.** A free place runs code too. The decorators and the default values of a test that is
   not T run when the module is imported (`def test_y(a=ITEMS.append(1))`, `@pytest.mark.parametrize('b',
   [ITEMS.append(1)])`), and the body of another test runs before T when the order says so (a test that sets a module global that a later skip reads). Both are the residual "run-time or import-time state that another test sets" (D1 residuals); after rework 10 the decorator of such a test is a plain mark only, and its arguments (`@pytest.mark.slow(ITEMS.append(1))`) and its default values stay free; the rule is not tightened for them, because the real case is a unit that edits assertions in tests and adds tests. The
   changed sibling test module that defines tests and that T's file imports is in neither (c) nor (e): it is the residual "a changed sibling test module the file imports", because nobody compares its content, and the base report is what stands in front of it. (e) judges the test it is asked about, not every candidate of the file at once:
   each candidate is protected in its own place and free in the others, which is what SCN-VER-375 needs (a skip call added to the body of one test does not touch another; since rework 10 a skip decorator is no free change, so it keeps the whole file a finding).
   **How the lines are mapped.** The first design said `git diff -U0` or `difflib` on the two blobs. A diff of lines has to
   guess which line became which, and with 600 tests that share lines (`    assert x`, the same decorator) `difflib`
   took 18 s on one file and can still align a changed line with an unchanged one. The implementation pairs statements
   instead: the statements of the module and of its classes that are not collected tests, and the imports the base had,
   pair up in order; each pair must be the same tree (`ast.dump`, no positions) and the same lines of text (comment and
   blank lines left out, a line inside a string kept); T must be at the same place among them; T's decorators, signature
   and prefix must be the same trees and the same text. A line that no kept statement holds, and that is not a comment or a
   blank line, is then a line of a collected test or of a new import. So every removed and every added line is located in
   the tree of its own side, nothing is guessed, and the cost is linear. The pairing is also the structure check that a
   line check alone cannot make: deleting the `def` line of a test makes its body part of the function above it, and
   adding a `def` in the middle of a helper splits it, each with every changed line inside what looks like a test and a
   changed tree outside one. A formatting-only change of a kept statement (`x = 1` to `x = (1)`) is a changed line and
   keeps the finding, as the line rule says.
   The line is exact on purpose and the whitelist is narrow: a unit that also adds a helper, a fixture, a flag or a class
   attribute to the file, or rewrites a docstring, keeps the finding and a person has to look at the file. The cost of a
   false negative is one question, the cost of a false positive is a waived skip that the unit made.

What the conditions cover. (a) is what ties the skip to the base: an imported marker, a changed condition variable and
a newly inherited skipped base class all make a test that RAN at the base and is skipped now, which the base report says.
(b), (c) and (d) cover the case "skipped at the base AND the unit changed why": a skip the unit added to a fixture, a
block, a run-time marker or an alias, a file that can skip from outside, and a flag, a guard, a helper, a fixture or an
import of the file that the unit changed under a skip that reads the same. (e) is what bounds the in-file cases: the
unit changed the file only where it cannot change why a test skips, so a way to do it that (b) and (d) do not list is
still out.

Residual risks, stated in the hold's question, in the Evidence line, in the runbook and in the SPEC (L4-VER-092,
L4-VER-093), and in no other words: the rule compares evidence, not behaviour. A test that was skipped at the base can
still be skipped now for another reason when the cause is outside what is compared: production code the unit changed, a module the file imports that the unit did not change (an added import is allowed only from the standard library), run-time or import-time state that another test sets (its body, decorator or default values), a changed sibling test module the file imports, and dynamic forms and plugins that read test names (`exec`, `getattr`, `importlib`, `globals()`, a plugin such as test dependencies). That is, **production code the unit changed** (`skipif(not hasattr(mod, "x"))`), **a module the file imports that the unit did not change** whose marker, fixture or base class a skip reads (an imported module's content is not read, which is why an added import is allowed only from the standard library; a module of the tests tree that defines no test and that changed is rule (c)), **run-time or import-time state that another test sets** (a test body is a place the unit may change, and a body that sets a module global that a later test's skip reads is not told apart; nor is the argument of a plain mark or a default value of a test, run when the module is imported), **a changed sibling test module the file imports** (it defines tests, so it is neither a support module of (c) nor a part of this file) and **dynamic forms and plugins that read test names** (`exec`, `getattr(pytest, "skip")`, `importlib`, `globals()`, a name set in a function through `global`, a plugin such as test dependencies: `@pytest.mark.dependency(depends=["test_a"])` reads another test's outcome by a string, and a hook such as `pytest_generate_tests` that looks a test name up). What (d) and (e) cover, inside the file, is no longer a residual. The statuses are those of a run in another
environment: the base worktree run has the network off and no `PYTEST_ADDOPTS` (`BASE_RUN_ENV` belongs to step 1's run
of the base's tests on the head's code), while the head's gate has `gates.network` (`allow` by default). A skip that
depends on the network can look skipped at the base only, so the base report holds as skipped a test that would run, or
fail, at the head. The accept is a person's statement either way, bound to the file's content (D2).

Languages: `file_of_test` builds `.py` paths only (`testsran.py`), so the finding, and this change, exist for Python ids
only [V]. Go (`t.Skip`), Vitest and Jest (`.skip`, `xit`, `xtest`, `xdescribe`, `.todo`, `.only`) do not matter today: a
skipped Go or TypeScript id is attributed to no changed file and raises nothing, and the same would be true of the new
hold. `.only` skips the other tests of its file and would matter the day those ids map to files; the construct table (D3)
is where it would go.

### D2. Where the hold is raised, and what it carries (L4-VER-092, L4-VER-093)

`check_tests_ran` gains the keyword `predating: Collection[str] = ()`: the ids that `collect_evidence` found to predate
the unit (rules 1-5, computed there because only it has `git`, the base and the head). The ids of `touched` that are in
`predating` leave the finding and go to `TestsSummary.skipped_predating: tuple[str, ...]` (a new field with a default;
`report.py:131-132` and `:179` rebuild the summary from `verdict.json`, so both the writer and the reader convert it like
`skipped_unchanged`; an older `verdict.json` has none and reads as empty). With the default `()` the function behaves as
today, so every existing test of it stays valid.

`collect_evidence` groups `skipped_predating` by file (`file_of_test`) and makes one `Hold` per file, kind `skipped`,
subjects `(path,)`, text

    skipped: existing tests in `<path>` were also skipped in a base report, and the file adds or changes no skip the harness reads (<n> tests)

and one `hold_views` entry per hold (the mechanism of the `judge view:` and UI holds, `ladder.py:1822-1829`,
`ui_step.py:304-316`): `{"sha": sha256(text NUL head-blob-sha NUL sorted ids), "paths": sorted ids, "base_source": ...}`. `base_source` names the
base report that held the ids as skipped (`step 1 base run`, `an earlier round's record` or `a base worktree run`); it is
in neither the text nor the binding, so a source that changes between rounds for the same file and ids is the same hold
(same `H-` id, same `sha`) and an accept stays in force. The question and the Evidence line print it
(`tests_ran.summary.skipped_source`). The accept is then
bound to the head content of the file and to the full list of skipped ids, so a later edit of the file, or a change of
which tests are skipped, voids it and the hold is asked again (`ladder.py:1097` computes `current` from `hold_sha256`).
The text names the file and a count, not the ids, so it is stable and short; the ids are in the question (D4) through
`view["paths"]`, the way the judge-view question lists its files (`verdicts.py:821-826`, `QUESTION_MAX_PATHS`).

The hold joins the round in `_collect_step`, next to the finding it replaces, not in `_quality_step`: step 6 returns before
`later_holds` when diff coverage is `off` or measured nothing (`ladder.py:1003-1006`), and the finding was raised in that
case too. To keep `later_holds` from adding the same hold twice, `Evidence` gets `ran_holds: int` (how many of
`hold_records` come from the tests-ran check) and `later_holds` becomes `hold_records[scope_holds + ran_holds:]`; the
order of `records` is step 1 holds, then skipped holds, then coverage holds (`collect.py:331-336`). `Evidence.to_json`
already lists every record, so `verdict.json` shows `kind: "skipped"`.

`hold_kind` (`verdicts.py:110-119`) gets a branch for the text prefix `skipped: existing tests in ` and the new
`HoldKind` value `skipped`. This is what routes the question, the reject and the delegate; adding the `Hold.kind` literal
alone would leave the hold `other`, whose question asks for a WHEN THEN sentence (`verdicts.py:787-792`).
`hold_subjects` returns `()` for it. Otherwise `subsumed_findings` (`:161-174`) would treat a blocking judge finding that
names the test file as about the hold, and an accept of the skip would settle it as minor (`settle_holds`, `:296-317`): a
person's statement about skipped tests would silence a judge's finding about the file's assertions.

Other readers of the hold list [V]: `s1_labels._SET_OF` (`verifier/s1_labels.py:23`, `hold_map` `:30-45`) ignores any kind
not in `{scope, coverage}`; `s1/labels.py:30` types `HoldRef.kind` as scope or coverage and gets only those; the System-One
export reads `ev.ran.summary` counts only (`s1/items.py:128-137`), whose `skipped` and `all_passed` are unchanged. So no
S1 data changes. The canary's mutation `skip_old_test` adds a skip, which stays a finding (`s1/canary.py:550-575`).

### D3. The skip-construct rules (`scan.skip_constructs`)

`skip_constructs(source) -> Counter[tuple[str, str]] | None`: the key is `(scope, text)`, `text` the `ast.unparse` of
the construct (so line wraps and quotes do not matter, and a changed condition does); `None` when the source does not
parse. `scope` is `<module>`, a module-level class name, a module-level function name, or `Class.method`. A construct is:

| Construct | Matches (on the unparsed text) | Scope |
|---|---|---|
| marker as decorator | `mark.skip`, `mark.skipif`, `mark.xfail` (the regex of `scan._SKIP_MARK`), `unittest.skip`, `unittest.skipIf`, `unittest.skipUnless`, `unittest.expectedFailure` | the decorated function, method or class |
| marker in a `parametrize` | the same text inside `pytest.param(..., marks=...)` or `marks=[...]` of a decorator: the whole decorator is the construct | the decorated function |
| module or class mark | an assignment (also annotated) at module or class level whose value contains a marker: `pytestmark = [...]`, `requires_stack = pytest.mark.skipif(...)`; the target name is recorded as an **alias** | `<module>` or the class |
| alias use | a decorator whose unparse contains a recorded alias as a whole word (`@requires_stack`) | the decorated function or class |
| runtime call | a call to `pytest.skip`, `pytest.xfail`, `pytest.importorskip`, `<x>.skipTest`, or `raise ...SkipTest(...)`, anywhere in a module-level statement, a function body or a class body (assigned or not: `docker = pytest.importorskip("docker")`) | the enclosing function or class, else `<module>` |
| run-time marker | any call of `.add_marker(` or `.applymarker(`, and any call with a skip, skipif or xfail marker among its arguments (`pytestmark.append(pytest.mark.skip)`, `register(pytest.mark.xfail)`) | the enclosing function or class, else `<module>` |
| block | a mark assignment (or an alias definition) nested in a module-level or class-level `if`, `try`, `with`, `for`, `while` or `match` block | `<module>` or the class |
| import alias | `import pytest as pt`, `import unittest as ut`, `from pytest import mark as m`, `from pytest import skip as s`, `from unittest import skip as s`, and a name assigned one of those (`skip = pytest.skip`, recorded as a construct itself): the text is read with the alias written out, so `@m.skip` and `pt.skip(...)` are the constructs above | as the construct they stand for |

`.only`, `.skip`, `.todo`, `xit`, `xtest`, `xdescribe` (Vitest, Jest) and `t.Skip` (Go) are not in the table: the
check cannot see those ids (D1). Not in the table either: a skip with no construct in the file (condition (c) of D1), `-k`
and `--deselect` options (runner configuration: (c)), a fixture that calls `pytest.skip` in another file, a marker
imported from another module, and a skip reached by `getattr` or `importlib` (the base report of D1 (a) is what stands
between these and a hold, except when the test was skipped at the base too).

A function or method that no runner collects as a test (`scan.shared_scopes`: a fixture, whatever its name, a helper,
`setUp`, a collection hook) is a scope that every test of the file shares (D1, rule (b)4); a function decorated with
`pytest.fixture` in any form (`@pytest.fixture`, with arguments, `@pt.fixture`, `@fixture`) is never a test. Rule (e) of
D1 uses the same notion of a collected test: it decides where the unit may change the file, and the constructs of this
table still say what skips (for (b), kept as defence). A decorator or a signature of another test cannot skip this test (a
decorator is applied to the function it decorates), so (e) leaves the whole of another collected test free, its
decorators included; the decorators of this test, its signature (parameters are fixtures) and its body up to its last
skip are not free. A file is
tested against these cases, each a scenario: an unchanged `skipif`; a condition changed on a continuation line; an alias
defined and applied; an alias newly applied to an old test; a module-level `importorskip` added; a skip added to another
test; a fixture that gained `pytest.skip`, named `test_env` or not; a mark in a module-level block; `add_marker`; an
import alias; an unparsable head.

How a file spells a skip (its import aliases and the names bound to a marker) is read once into `scan.SkipReader`;
`skip_constructs`, the closure of D1 (d) (`skipdeps`) and the test of "this statement contains a skip" share it, so the
three cannot disagree on what a skip is. The constructs say WHAT skips; the closure of D1 (d) says what the skip DEPENDS
on in the file, and the two are compared separately: a flag the unit changed under a `skipif` that reads the same is no
construct and is in the closure. A `pytestmark` assignment is a skip-relevant statement whatever its value
(`pytestmark = getattr(pytest.mark, "sk" + "ip")` is not a construct, but is a changed part of the closure).

### D4. The question, the reject, and why a reject makes no fix unit (L4-VER-093)

The brief's intended path was `reject` to a deterministic finding to a fix unit. The code says that cannot work.

- A fix chore never changes a test file. `run_single` puts the test paths back (`restore_frozen` and `freeze_test_paths`,
  `src/l4/implementer/tdd.py:4075-4086`) and an attempt whose only edits were put back fails with `nothing changed: the
  guard put back every edit` (`:4091-4096`); a test chore (`kind="tests"`) may add tests only (`:4066-4072`) [V].
- The fix unit of the consumer's case did exactly that: it asked a technical question, because the finding asks for a
  change in a test file that the chore may not make.
- A reject can only mean "make these tests run in the gate", which is a change of a test file or of the gate. So a
  deterministic finding after a reject recreates the dead end, one fix round and one question later; and a delegate that
  rejects would do it with nobody in the loop.

So a rejected skipped hold follows the `judge view:` pattern, not the scope and coverage one: `_hold_finding`
(`verdicts.py:240-257`) returns a `human` major finding with its own title `SKIPPED_REJECTED_TITLE` (`Rejected hold: a
skipped test is not accepted`), whatever the reason says, even with a `WHEN ... THEN ...`; `fixunit.py:262-266` lists it
as not converted like `JUDGE_VIEW_REJECTED_TITLE`; `fixloop._no_task_cause` (`:694-712`) names it and the round escalates
with the new code `skipped_tests_rejected`, with a `way_out` text in `src/l4/state/next_step.py:36-72` and a section
7.3.4 of the runbook: change the file in your own commit on the unit branch (remove the skip, or make the tests able to
run in the gate), then `l4 retry --unit <unit> --reason TEXT`; or replace the answer with an accept (`l4 questions answer
... --replace`) once you ran the tests. A person's commit on a test file is allowed and listed by step 1
(`integrity.py:355-395`, `Outcome.human_tests`).

The question (`_hold_question`, new branch before the generic `else`) says: which file and how many tests, the ids (from
`view["paths"]`), what was compared and no more (the tests were also skipped in a base report, named by its source; the
file adds or changes no skip construct the harness reads: decorators, marks and skip calls in the file; no support or
runner-configuration file changed), what is NOT told apart (a skip that comes from production code the unit changed, or
from a module the test imports: a marker or fixture there; the tests were skipped at the base too, but the reason may
have changed), that often the cause is an environment the gate does not have, that `accept`
means the person ran them where they can run or knows they pass there and holds for this content of the file only, and
that `reject: <reason>` ends the round, because a fix unit cannot change test files.

### D5. Who may answer (L4-VER-094)

- The delegate: `delegate.kinds` includes `verdict` by default (`config/schema.py:1055`), and `check_reply` refuses a
  judge-view reject and a judge-view accept that cites no file (`delegate/reply.py:458-462`), while `_without_a_call`
  (`delegate/run.py:852-872`) keeps a question from a call when no check can be made. A skipped hold has no check a
  read-only model can make: an accept says the tests ran elsewhere, and a reject ends the round with no automatic way on.
  So the whole hold is a person's: `_without_a_call` returns `a skipped-test hold is a person's decision` for kind
  `skipped` (no call, the question is escalated like the other cases), `check_reply` refuses both decisions with status
  `escalated` as a backstop (the `hold_kind` argument exists, `reply.py:396-409`), and the delegate prompt's hold rule
  (`delegate/prompt.py:93-94`) names the kind. This differs from the brief's lean (delegate may reject) on purpose: a
  delegate reject is a unit stop with no fix.
- An agent: `l4 questions` already refuses an agent on a `verdict` question unless `clarifier.answer_by_agents` is true
  (`docs/SPEC.md` L4-QMD-009, `:1758-1764`, `src/l4/specs/questions_cli.py:488-545`) [V]. With that key set, an agent can
  write a verdict answer. `effective_verdicts` ignores `by`. So `_finalize` (`ladder.py:1098`), right after
  `effective_verdicts`, drops the verdict of any `skipped` hold whose `by` is not `human` (`agent`, `delegate`,
  `clarifier`, the values of `clarifier/actor.py:38`), and records `human.void{question, target, reason}` once per
  question (the event the regression void uses, `ladder.py:1131`). The hold is then unresolved, and because the
  consumed question is no longer waiting (`verdict_status`, `verdicts.py:369-395`) the next round asks it again [I]. The
  precedent for a model's accept that is recorded but not applied is `held_patch.py:541-551` (`held.accept_ignored`).
  A person who runs `l4 questions answer` is `by: human` (`clarifier/actor.py:106-129`).

### D6. A unit that already has a fix unit for the old finding (L4-VER-095)

State to resolve: the parent `openspec:<name>` is `fixing`; `<name>-fix-2` has one task, 1.1, the old finding, and an open
technical question Q-001 that holds it; two of three fix rounds are used.

What exists:

- `l4 retry` refuses a unit in `fixing` (`state/retry.py:61-62` lists it in `_CONTINUES`; `:80-81` says `the harness
  continues it at the next run`) [V]. `l4 resume` is for halted and escalated units. A spec push during `fixing` waits
  until the fix unit ends (runbook 7.14, and a fix unit's folder does not count as a spec edit) [V].
- `open_fix_unit` is cleared only by `fix.done` (`state/fold.py:353-355`), which `fix_hook` appends when no task of the
  fix unit is pending and none is held (`fixloop.py:434-443`); the only edge to `verifying` is `FIX_UNIT_DONE`
  (`state/lifecycle.py:143`) [V]. A pending task held by an open question makes `fix_hook` return `blocked`
  (`:440-442`), and the planner says `fixing: fix unit questions open` (`planner.py:194-199`).
- The harness's own way to finish a task with no step is `_already_done`: it ticks the box, commits with `L4-TDD:
  already-done` and writes `task.done{tdd: "already-done", reason}`; step 1's TDD history skips such a task
  (`tdd.py:3104-3122`, `integrity.py:1105-1106`) [V].

What a person can do, and does not work:

- **Tick task 1.1 by hand in `<name>-fix-2/tasks.md`.** `fix_hook` would read it as done and append `fix.done`
  (`fixloop.py:433-443`: `questions_hold` is false with no pending leaf, and `holds`, `specs/questions.py:740-762`, counts
  pending tasks only). But the next verification, under the new harness, fails at step 1: `check_protected`
  (`integrity.py:187-190`) adds `<fix dir> (touched by non-harness commit <sha>)` for every commit in `base..head` that
  touches the fix unit's folder and is not the harness's, `questions.md` apart (`verifier/provenance.py:36-42`). That is a
  blocker, `a protected path was changed`, no fix chore can repair it (a fix step cannot change that folder), and it
  spends the last fix round. [V, from the code; no run]. A person's tick is therefore not an allowed action.
- **Answer Q-001.** The task then runs, and the chore fails (`nothing changed: the guard put back every edit`), `max_task_attempts`
  halts the unit. Nothing is gained.
- **`l4 restart`.** Works, and drops the ledger, the evidence and the fix units (runbook, the CAUTION at 7.13). Too big.

So the spec adds the minimal path, built from parts that exist: `l4 retry` is accepted for a unit in `fixing` **only when
the open fix unit is waiting on a person**, that is, when its pending tasks are all held by open questions
(`questions_hold(tasks, blocked)`, the planner's own test, `planner.py:313-327`). It records `unit.retried{reason, by,
actor, close_fix_unit: <name>}` and starts a run, as for any retry (`state/retry.py:129-141`). In that run `fix_hook`
(before it selects a task) sees the event and, **in harness commits**, for each pending task of the fix unit: ticks it as
`already-done` with the reason `closed by l4 retry: <reason>` (`task.done{tdd: "already-done", closed_by: "retry"}`,
parents ticked as `_already_done` does); sets each open question that held it to Status `superseded by retry` (a new
status text, read like `superseded by restart` in `holds`: it holds no task; `specs/questions.py:275-276`, `:396`,
`:753`), recorded with `question.superseded{ids}` so that it leaves `questions.open` and `l4:needs-answers` goes
(`orchestrator.answers_recorded`, `:670-679` is the same mirror sync). The event is written BEFORE the commit that holds
the question's new Status, so that it travels inside the commit (rework 7, F9: a run that ends after the commit would
otherwise leave the question's Status and the ledger disagreeing, and the next run's `fix.close_skipped` would never
write it); `task.done` names the commit's sha and follows it, and a commit without it is no step 1 blocker
(`check_tdd_history` has nothing to check for an `already-done` commit with no event); then the loop proceeds to `fix.done`. The unit goes
to `verifying`, the round is fresh (`reusable` reuses only a NEEDS_HUMAN round, `verifier/evidence.py:108-116`; the last
round failed), and with the new harness the old finding is a hold. The fix round stays counted (`fix_rounds_counted`,
`fold.py:340-345`; `_used_rounds`, `fixloop.py:480-483`: the folder is on disk), so a person who then rejects the hold
has one round left; an accept needs none. A later FAIL makes `-fix-3`.

Why a harness commit and not the person's: the tick is what step 1 refuses from a person (above), and the harness writes it
with the trailers its own checks accept. Why `already-done` and not a new tdd kind: `integrity.py:1105` already skips it, and
step 0 needs every task of the family ticked (`preconditions.py:291-296`; `FamilyProvider.tasks` returns the whole family
for the parent, `fixloop.py:157-160`), so an unticked fix task would be a blocker too [V].

The question's fate (answer to (b)): Q-001 is **superseded, not left open and not answered**: its text and the fix unit's
`questions.md` stay as history, its Status becomes `superseded by retry`, it holds nothing, and it is not in
`questions.open`. If a task of the fix unit is not pending (already ticked) its question is left as it is.

Order matters, and the runbook says it: **upgrade first.** The retry needs the new `l4` (an older `l4` refuses `fixing`),
and the pin must be the release, because the fresh round runs under the pin: on the old harness it raises the same major,
the unit fails again, and the last fix round (`-fix-3`) is spent on a finding no fix can make (`l4 upgrade` moves the pin;
an `l4` older than the pin refuses state-changing commands, `CHANGELOG.md` L4-OPS-026). Steps: `l4 upgrade --harness-ref
<release>` and merge to the base; `l4 retry --unit openspec:<name> --reason "..."` from a clone on the base with the new
`l4`; the run verifies; `l4 questions answer Q-NNN --unit openspec:<name> --text "accept ..."` (or `reject: ...`) for the
hold; the next run goes on. The bound for "waiting on a person": a fix unit that is running, or has a task no question
holds, is refused with `the fix unit <name> is running: the harness continues it at the next run`, so a retry cannot throw
away work in progress.

**The window of a failed closing commit (review G6, kept).** `question.superseded` is recorded before the commit that
carries the question's new Status, so that a run that ends AFTER the commit loses nothing (the F9 repair of group 7). The
price is the opposite case: when the commit itself fails, the run's ledger commit still carries the event, because the
ledger is append-only and the harness has no primitive that takes a line back out of it (`restore_if_tampered` restores
what the writer wrote). Between that run and the next, the ledger says superseded and the file says open (`l4 status`
and the plan read the ledger). Evidence: a failed first commit, injected, left exactly that, and the next run closed the
fix unit from its start (the request `close_fix_unit` was still pending, the tick and the Status had not been committed),
wrote the event again with the same ids, and ended with the file, the ledger and the fold agreeing
(`test_a_close_whose_commit_fails_leaves_the_ledger_ahead_of_the_file_until_the_next_run_repairs_it`, SCN-VER-404).
The alternative, to record the event after the commit, moves the window to the other side (a crash after the commit
leaves the file ahead of the ledger, the case group 7 fixed) and would need a new repair path that re-reads the file;
that is more code and a new way to be wrong for a window that the next run already closes. So the code stays, the test
pins the repair, and the runbook's known limits and L4-VER-095 say that the window exists and that the next run repairs it.

Not verified [U]: that `Orchestrator.resume` can record `unit.retried` in `fixing` without a phase edge (`lifecycle.py:122`
lists `FIXING` for a set of edges; the implementation reads it first, task 5.1); that `question.superseded` takes a fix
unit's technical question out of the parent's `questions.open` (the fold's rule, `state/fold.py:272`, is described for
verdict questions); and the end-to-end run, which the scenarios SCN-VER-387..390 cover with fakes.

### D7. Upgrade and risks

- No key, on by default. A unit whose changed file has old skipped tests stops failing at step 3 and waits for a person
  (exit 11). A unit whose round is already FAIL for the old finding stays so until D6's retry.
- A hold is asked once per file and content; the accept is void when the file or its skipped set changes.
- A `skipped` hold in `verdict.json` read by an older harness is an `other` hold (its question asks for a WHEN THEN);
  not a supported downgrade.
- Residuals: D1's (production code the unit changed, a module the file imports that the unit did not change (an added import is allowed only from the standard library), run-time or import-time state that another test sets (its body, decorator or default values), a changed sibling test module the file imports, and dynamic forms and plugins that read test names (`exec`, `getattr`, `importlib`, `globals()`, a plugin such as test dependencies); a base run whose environment differs from the head's); one more run of the base's test gate in a round, when no full report or
  recorded status exists; a skip the unit added in a place the table does not list is a hold only when the base report
  also held the test as skipped, and a person must accept it; a person's own commit that adds a skip stays a
  deterministic major, as today (`integrity.py:355-361` lists it for people, and step 3 raises the finding): out of scope.
- Parallel changes may claim L4-VER-092; this branch took the next free id by reading `docs/SPEC.md` (last: L4-VER-091,
  SCN-VER-371) and the active changes.
