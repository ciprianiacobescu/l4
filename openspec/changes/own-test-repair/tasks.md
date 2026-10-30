## Context

Builds on fix-chore-e2e (the round's `failures` map; one task per failure; the e2e gate in a fix chore). Pointers
(verified on v0.4.44, re-locate): `run_single` (src/l4/implementer/tdd.py ~2310; kinds fix/tests/refactor),
`review_test_chore` (~2177) and `_appended`, `l4.implementer.tamper.facts_of` (AST facts per bound name: definition and
closure digests), `l4.specs.fixmark` (`test_chores`, `refactors`, `chore_kind`), `l4.verifier.fixunit._candidates`,
`l4.verifier.integrity._allowed_in_step` and `check_test_paths` (~600-640; walks commits with `L4-TDD` green, exempt,
already-done), the red-freeze check (find it: red's frozen tests unchanged after red), `unit_base` (discrimination.py
~720-730), `judge.NamedChange` and `ladder._named_changes` (0.4.43), the template lock (`uv run python -m
l4.templatelock --write`), `l4.implementer.prompt` templates.

## 1. Candidates and the marker

- [x] 1.1 Write the tests first (the fixunit and fixmark tests): SCN-IMP-455, SCN-IMP-456 (TypeScript; a mixed finding),
  a person's test (first added by a commit without `L4-TDD: red`), a support-glob file (`conftest.py`), and a candidate
  finding → `repair` chore. Verify (and pin with a test) that `unit_base(wb)` inside a fix unit is the parent's base.
  Then add `repairs` to the fix marker (a list of finding ids, absent = none, old markers read as before), `chore_kind`
  `repair` when every finding of the task is in `repairs`, and the candidate rule in `fixunit` (L4-IMP-091 first
  paragraph). The task text names each test, its kind and first line, carries the finding's gate log excerpt (bounded,
  redacted), and says the test may be right and the code wrong.

  Result: New `l4.verifier.repairs`: `repair_candidates(wb, failures)` returns the failing tests of a round that
  qualify (`RepairTest(id, path, name, gate, kind, message)`), re-derived from git by whoever asks (the planner now,
  the repair step in 3.1; the marker is never the proof). A test qualifies when its kind is not `assertion`,
  `not_implemented` or `collection`; its id resolves (`locate`: `a.b.test_c.Cls::test_x[p]` is `a/b/test_c.py` and
  `Cls.test_x`, at most one class) to a regular `.py` file with no link on the way, at HEAD and in the worktree, that
  matches `tdd.test_globs` and no `tdd.test_support_globs`; the file is absent at `unit_base`; the test is bound once
  in it; and the first commit of `unit_base..HEAD` after which it is a test (so a test a person appended to a red file
  does not qualify) is a harness commit (`is_harness`) with `L4-TDD: red` and an `L4-Unit` of the unit's family
  (`family_of`: the unit or its fix units). More than 50 commits on the file, or a base that cannot be found: no
  candidate. `failures.finding_test_ids` (a leaf) gives the ids a gate finding fails on, whole or None (collection
  records, a cut `test` side, a cut or unmatched `new tests ...` list); `fixunit._candidates` marks a task `repair`
  only when every finding of it is deterministic, has no criterion, no scenario and no human reject, and its ids are
  all in the new `repairable` argument of `plan_fix_unit` (default `()`: a caller that passes none sees no change).
  `Finding.repair` (specs.base), `FixMarker.repairs` (written and read like `retakes`; an older marker reads `()`),
  `chore_kind` `repair` (after `tests` and `refactor`; every chore finding of the task must be in `repairs`), and both
  scaffolds (openspec, kiro) write it. `decide_fix` (`fixloop._repair_inputs`) computes the candidates and reads the
  end of each gate finding's log (`repairs.log_tail`, 600 characters, a link never followed, redacted with the
  workbench's redactor) only for a round that has a failures map. The task text (`fixunit._repair_detail`, at most
  2,700 characters) names up to 8 tests with kind and first line, the log end and the closing sentence that the test
  may be right and the code wrong (the closing sentence is never the part that is cut). Deviation: none of substance.
  "unit_base inside a fix unit is the parent's" is pinned by a test on the merge base (a fix unit lives on its
  parent's branch). Tests: new `tests/unit/implementer/test_repair_candidates.py` (14),
  `tests/unit/verifier/test_fixunit_repair.py` (11), `tests/unit/verifier/test_fixloop_repair.py` (4),
  `tests/unit/specs/test_fixmark_repairs.py` (7). Before: the candidates module did not exist (import error), the
  marker had no `repairs`, `plan_fix_unit` took no `repairable`, `decide_fix` did not call `repair_candidates` (all 36
  failed or errored); after: 36 pass, and with the existing `test_fixunit`, `test_fixunit_one_failure`,
  `test_fixloop_ci`, `test_fix_unit`, `test_kiro_fix_unit`, `test_fixmark_refactors`, `test_fix_unit_test_only` 135
  passed.

## 2. The structural check

- [x] 2.1 Write the tests first (a new `tests/unit/implementer/test_repair_check.py`, pure: text before/after → findings):
  every bullet of L4-IMP-091's second paragraph, both ways (SCN-IMP-451, -452, -457, the two consumer repairs:
  `expect(page).to_have_url(lambda …)` → `page.wait_for_url(lambda …)` and adding `exact=True` to a `get_by_role` call
  are kept). Then add a pure module (next to `l4.implementer.tamper`, no public name starting with `test`) that returns
  the rule each change breaks, or nothing.

  Result: New pure module `l4.implementer.repaircheck` (next to `tamper`, no public name starting with `test`):
  `check_repair(before, after, tests)` returns `Broken(rule, detail)` for every rule the change breaks, `reason(...)`
  joins them for the retry prompt. Rules: `unparsable`; `repaired-test-missing` (a named test is not bound once, by
  one `def`, in both texts, or none is named); `outside-changed` (the module's statements other than top-level
  imports, with each repaired function replaced by a stand-in at its place, differ as AST dumps: helpers, fixtures,
  constants, other tests, a module-level call, the class around a repaired method, statement order); `import-removed`,
  `import-star`, `future-import`, `import-shadows` (a new import binds a name the file already binds, or an imported
  name with another source); per repaired test `decorators`, `signature` (parameters, return type, async),
  `statement-count`, `too-many-statements` (more than 3 differ, positional), `compound-added` (a differing statement
  gained a try, if, loop, with or match: counted over the whole statement, so a try inside an existing with is
  caught), `assert-removed`, `check-dropped`, `assert-constant`, `skip-added`. Deviations, both toward the stricter:
  (1) the proposal counts `expect(...)` and `assert...(...)` calls and SCN-IMP-450 (and the first consumer repair of
  the task text) replaces `expect(page).to_have_url(lambda ...)` by `page.wait_for_url(lambda ...)`, so counting
  `expect` alone would refuse the headline scenario: the `check` count is asserts plus calls of `expect`, `assert...`
  and `wait_for...` (not `wait_for_timeout` or `wait_for_load_state`), and it may not drop, while `assert` statements
  are also counted alone and may not drop; (2) an `assert` that cannot fail (a constant, a non-empty tuple, an `or`
  with a constant) added is refused (`assert-constant`), and `exit`, `_exit`, `quit`, `SystemExit` count with `skip`,
  `skipif`, `xfail`, `importorskip` as names that may not be added (`pytest.exit` ends the whole run). A check
  rewritten into a weaker one that still passes is the residual risk the proposal names. New
  `tests/unit/implementer/test_repair_check.py` (36): the consumer repairs (`wait_for_url`, `exact=True`), the added
  import (SCN-IMP-457), a method repair, three replaced statements, SCN-IMP-451/452 both ways. Before: the module did
  not exist (the test module failed at import); after: 36 passed.

## 3. The repair step and the verifier

- [ ] 3.1 Write the tests first (the run_single tests): SCN-IMP-450, -453, -454, -458. Then add `run_single(kind="repair")`
  with its own prompt template `single_repair` (the tests, kinds, first lines, log excerpt, the rules of the check, "the
  test may be right and the code wrong: if so, report blocked with a technical question"), put back and fail on any
  change outside the candidates' files, run the structural check, then the gate the tests failed in (fix-chore-e2e's e2e
  path, or the test gate with them as must-pass), commit with `L4-TDD: exempt` and record `task.repaired{task, files,
  tests}`. Regenerate the template lock.
- [ ] 3.2 Write the tests first (the integrity tests and the judge prompt tests): SCN-VER-257, SCN-VER-258, and that a
  plain exempt commit changing the same file is still a blocker. Then accept `task.repaired` files in `_allowed_in_step`
  for exempt commits of the same unit and task, the same in the red-freeze check, and give the judge each repaired test's
  lines before and after (reuse `NamedChange`).

## 4. Checks

- [ ] 4.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the test files that import a module you changed, in as few sequential runs as the time limit
  allows; not whole directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit
  docs/SPEC.md, CHANGELOG.md or docs/runbook.md.
