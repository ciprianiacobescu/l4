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

- [x] 3.1 Write the tests first (the run_single tests): SCN-IMP-450, -453, -454, -458. Then add `run_single(kind="repair")`
  with its own prompt template `single_repair` (the tests, kinds, first lines, log excerpt, the rules of the check, "the
  test may be right and the code wrong: if so, report blocked with a technical question"), put back and fail on any
  change outside the candidates' files, run the structural check, then the gate the tests failed in (fix-chore-e2e's e2e
  path, or the test gate with them as must-pass), commit with `L4-TDD: exempt` and record `task.repaired{task, files,
  tests}`. Regenerate the template lock.

  Result: `run_single(kind="repair")` (the kind is now `fix`, `tests`, `refactor` or `repair`; `fix` is untouched and
  still puts a test edit back, SCN-IMP-458) delegates to the new `_run_repair` in `l4.implementer.tdd`. Before any run
  it re-derives what it may touch (`_repair_scope`): the ids the task's findings fail on come from the parent round's
  stored verdict (`_parent_verdict`, now shared with `_e2e_chore_scope`; `failures.finding_test_ids`, whole or
  refused) and every id must still be a `repair_candidates` result asked of git now, so a marker or verdict that names
  a pre-existing test, an assertion failure, a mixed finding or a round that is not on record fails the attempt with
  no agent step. The prompt is the new `single_repair` template (version 1; `PromptContext.repair_tests`, a "Tests to
  repair" data block, `contract@13+single_repair@1`), threaded through `_prompt`, `agent_step` and `step_or_replay`;
  it states the rules and tells the agent to report blocked with a technical question when the code is at fault. After
  the step `_repair_review` removes planted links (guard.violation, never followed), puts every changed path outside
  the candidates' files back to the base (`restore_to_base`; rule `repair scope`, with its own advice in
  `guardnotes`), runs `check_repair` on each candidate file against its text at the base and puts a file that breaks a
  rule back, failing the attempt naming the rule; no change at all is `nothing changed`. Freezes exclude the candidate
  files (the manifest drops them; `freeze_test_paths(keep=...)`, and `_e2e_chore_reason`/`_drop_gate_output` got a
  `keep` parameter so the e2e path no longer undoes the repair). The gate the tests failed in then runs: the test gate
  with the unit-gate candidates as must-pass (`green_failures`, which keeps the no-regression rule), and the build
  plus the e2e gate through the existing `_e2e_chore_reason` with an `E2eScope` whose ids include the candidates; the
  static gates must not get worse. What the gates write is put away (`_drop_gate_output`), a gate that rewrote the
  repaired file fails the attempt, and the final tree is re-reviewed (only the repaired files, same digests) before
  the commit. The commit is `L4-TDD: exempt`; `task.repaired{task, files, tests, ids}` is emitted before it (plus
  `base` is added in 3.2 for the judge), then `task.tdd_exempt` and `task.done`. When the attempts are used up
  `_run_task` appends a note that the repaired test may be right and the product code wrong
  (`loop.REPAIR_EXHAUSTED_NOTE`). Template lock regenerated (`implementer/single_repair`, added to
  `IMPLEMENTER_TEMPLATES` and to the cases of `test_template_lock.py`). Deviations: (1) a planted link in the agent
  step fails the attempt and is removed with a `guard.violation`; it does not halt the unit through `refused_write`
  (that path's text says a gate planted it); links planted by the gates still go through the existing
  `refused_write`/`stop_on_unsafe`. (2) A repair whose scope cannot be proved fails as an ordinary attempt, so after
  `max_task_attempts` it escalates like any chore. New `tests/unit/implementer/test_repair_step.py` (20, SCN-IMP-450
  to 454 and 458, the link cases, the loop dispatch and the exhaustion note). Before (the source files of this task
  stashed): 15 of the 20 failed; after: 20 passed, `test_template_lock` 6, and with the neighbours
  `test_fix_chore_e2e`, `test_single_phase`, `test_prompt`, `test_test_path_freeze` 131 passed, `test_escalation` and
  `test_guard_notes` pass.
- [x] 3.2 Write the tests first (the integrity tests and the judge prompt tests): SCN-VER-257, SCN-VER-258, and that a
  plain exempt commit changing the same file is still a blocker. Then accept `task.repaired` files in `_allowed_in_step`
  for exempt commits of the same unit and task, the same in the red-freeze check, and give the judge each repaired test's
  lines before and after (reuse `NamedChange`).

  Result: `integrity._allowed_in_step` now reads `task.repaired` next to `task.unfrozen` and `task.tests_added`: an
  exempt commit may change the files a `task.repaired` of the same unit (`_unit_of`, the event's `fix_unit`) and task
  names, and nothing else; a green commit, another task, another fix unit or a plain exempt commit of the same file is
  still a blocker (SCN-VER-257 and the plain case of SCN-IMP-458 on the verifier side). Finding "the red-freeze
  check": none of the other integrity checks can see a repair commit. `check_freeze` compares the red and the green
  commit of one task and unit (the repair is a later exempt commit of another task and, in a fix unit, another unit);
  `check_tests` compares only tests that exist at the base (a repaired test is the unit's own and new);
  `_later_red_changes` walks only red commits; `check_tdd_history` skips exempt tasks. A test builds a history (base,
  red, green, a fix unit's repair commit with the same task key) and shows all four checks and `run_integrity` pass,
  so no allowance was added anywhere else (deviation from the spec text "the same in the red-freeze check": there was
  nothing to change; the test pins it). The judge: `task.repaired` now carries the step's `base`;
  `ladder._repaired_changes` builds one `NamedChange` per repaired test (once per test, the earliest base) with the
  test's own lines (`repaircheck.function_source`, decorators included) in its file at that base and at head;
  `build_judge_prompt` has a `repaired_changes` argument that renders a separate "Repaired tests" block (a data block,
  bounded like the named tests, with the instruction to treat a gone or weaker check as a finding), and the judge step
  passes it. The named-tests block and the judge system text are unchanged (version and system equal, as a test pins).
  New: `tests/unit/verifier/test_repair_integrity.py` (5), three tests in `test_judge_step.py`, one in
  `test_repair_check.py`, a `base` assertion in `test_repair_step.py`. Before (integrity, judge and ladder stashed): 6
  of the 8 new tests failed; after: 8 passed, and with `test_integrity`, `test_prompt`, `test_judge_step`,
  `test_ladder` 158 passed.

## 4. Checks

- [x] 4.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the test files that import a module you changed, in as few sequential runs as the time limit
  allows; not whole directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit
  docs/SPEC.md, CHANGELOG.md or docs/runbook.md.

  Result: Sequential pytest runs, no whole directory, one at a time: (a) the verifier and specs files that import a
  changed module (`test_failures_map`, the `test_fixloop*` and `test_fixunit*` files, `test_gates`, `test_gates_e2e`,
  `test_report`, `test_resume_independence`, `specs/test_fix_unit`, `test_kiro_fix_unit`, `test_fixmark_refactors`,
  `test_fix_unit_test_only`) plus the new `test_fixmark_repairs`, `test_fixunit_repair`, `test_fixloop_repair`,
  `test_repair_candidates`, `test_repair_check` and `test_template_lock`: 331 passed; (b) the implementer files
  `test_loop`, `test_guard_notes`, `test_refactor_chore`, `test_criterion_tests_chore`, `test_decided_tests_chore`,
  `test_prompt_context`, `test_retry_note_prompt`, `test_tdd_prompt_contract` and the new `test_repair_step`: 163
  passed; earlier in the work: `test_fix_chore_e2e`, `test_single_phase`, `test_prompt`, `test_test_path_freeze` 131
  passed, `test_escalation` 19 passed, and `test_integrity`, verifier `test_prompt`, `test_judge_step`,
  `test_repair_integrity`, `test_ladder` 158 passed. Not run: the other test files that import `l4.implementer.tdd`,
  `prompt` or `loop` (the time limit; each full file run is several minutes). `ruff check src tests/unit` passes and
  every file this change touched is `ruff format` clean (29 other files of the repository are not, as before).
  `docs/SPEC.md`, `CHANGELOG.md` and `docs/runbook.md` are untouched. Overall deviations are listed in the Results of
  1.1, 2.1, 3.1 and 3.2.
