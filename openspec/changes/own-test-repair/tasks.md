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

  Result (adversarial fixes): the review's 20 probes (`repair-probe/probe.py`, all accepted before) are tests now,
  each refused, and the two consumer repairs stay accepted (`tests/unit/implementer/test_repair_probes.py`, 31; it
  failed at import before: no `encoding_problem`). (1) The real guarantee: `_run_repair` re-proves the repaired tests
  before the commit (`_repair_proof`): a unit-gate test through `discriminate_extra` (zero-value run, then the run on
  the unit base), an e2e test through the new `_e2e_base_proof` (the unit's source files of any language put back to
  the base with `red_code_in_place`, `run_build_only`, then the e2e gate: it must fail by an assertion; an error or a
  pass proves nothing; no production file to put back, a failed build or a server that is not ready is a failure; what
  the runs write is put away). Otherwise the attempt fails `the repaired test no longer tells a working product from a
  broken one: <id> (<why>)`. `task.repaired` now carries `proved` (id -> `zero_value` or `base`) and `sha10` (path ->
  sha10 of the file that was proved). In the verifier `traceability.red_proofs(ledger, file_sha)` drops the red proof
  of every test a `task.repaired` lists (matched by function, so parametrised variants too) and gives back `repair`
  only for the ids in `proved`, only while `file_sha(path)` is the recorded sha10 (`trace_criteria(file_sha=...)`, the
  ladder passes `_sha10`); without a proof the test is ignored as evidence like any unproved test. (2)
  `repaircheck.encoding_problem` (`tokenize.detect_encoding` must give `utf-8` or `utf-8-sig`, and the bytes must
  decode) and `check_repair_files`, used by `_repair_review` on the file before and after the step; the utf-7 probe
  file is refused. (3) The rules of `check_repair`: no added `return`/`yield`; checks counted by normalised name in
  the function's own scope with the nested scopes (`def`, lambda, comprehension) counted apart and not credited
  (`expect(page)` alone is no check, `to_have_url` and `wait_for_url` are one); no check below `and`/`or`, a
  conditional or `:=`; no `and`/`or` operand that reads no name, call, attribute or item; always-true asserts widened
  (a container, `X == X`, nothing read); `dir(builtins)` and names starting `assert`, `expect`, `wait_for` (and `ANY`)
  cannot be bound by a new import; imports are an ordered multiset (a repeated or reordered one is refused); writes to
  an attribute or item rooted at a non-local name, `global`/`nonlocal`, and calls of `globals`, `vars`, `setattr`,
  `delattr`, `__import__`, `exec`, `eval`, `compile` (the builtin; `re.compile` stays allowed) and `importlib.*` are
  refused; `SkipTest` joins the bail-outs. Deviation: a check that is swapped for another of a different name (an
  `assert` for a matcher) is refused though the count is the same; and `getattr` is not on the reach-out list
  (`__import__` is, and that is what P12 needs). (4) The trigger: `failures` records now carry `location`, the file of
  the deepest repository frame of the traceback (`gates.collection.deepest_repo_frame`: None when a later frame has an
  absolute path that is no library); `repair_candidates` requires it to match the test or support globs, so a
  `KeyError` raised in `src/app/x.py`, or a record without a location, is no candidate, while the library error raised
  from the test's own line is. A verdict of an older harness has no location, so such a round makes no repair chore.
  (5) `_introduced_by_red` also requires that no later commit by a person changed the test's parts or closure, and
  that no later commit took it out of the file (deleted and added again). (6) `check_test_paths` runs
  `check_repair_files` again on the parent and commit blobs of each file a `task.repaired` of the commit's task names
  and reports `a repair broke the structural rules of a repair` (also for a file added or deleted by the commit, or
  named with no test). Spec: L4-IMP-091 and L4-VER-070 and the scenarios SCN-IMP-459 to 463 and SCN-VER-259 are
  updated. Tests: new `test_repair_probes.py` (31), `test_traceability_repair.py` (7), 4 in
  `test_repair_integrity.py`, 6 in `test_repair_candidates.py`, 3 in `gates/test_collection.py`, 1 in
  `test_failures_map.py`, and in `test_repair_step.py` the vacuous forms, the base-proof cases (a pass or an error at
  the base, no production change), the recorded proof and the encoding case (26 in all). Runs, one at a time: probes,
  check, candidates, collection, failures map, traceability (3 files), repair integrity, integrity, fixloop and
  fixunit repair, gates, report: 270 passed; `test_repair_step`, `test_fix_chore_e2e`, `test_judge_step`,
  `test_fixloop_ci`, `test_template_lock`: 102 passed.

  Result (second adversarial fixes): every case of `repair-probe/probe2.py` (N1 to N14) and the n1/ fixture (the
  `PYTEST_ADDOPTS` and `os.path.exists` detectors) is a refused test now, with eight more of my own (an import alias
  of a denied module, a module-level alias, `open`, `__file__`, an unknown name, a name bound twice, `environ`,
  `getenv`); they are in `test_repair_probes.py` (56 tests in all; the second-pass ones failed before:
  the vocabulary and await rules did not exist). (1) The vocabulary rule in `repaircheck`: a replaced statement may load only names the test used before the
  step, names the module binds exactly once at module level, the test's own locals (computed from its own scope only:
  a comprehension target or a nested function's local no longer makes a module name look local, which closes N9), its
  parameters, a short list of pure builtins, and names bound by a new import of `re`, `json`, `datetime`, `math`,
  `decimal` or `fractions`; and never, under any alias (imports and plain assignments `o = os` are resolved, also
  inside the test), `os`, `sys`, `pathlib`, `open`, `inspect`, `functools`, `operator`, `importlib`, `builtins`,
  `object`, `type`, `getattr`, `setattr`, `delattr`, `globals`, `vars`, `environ`, `getenv`, any dunder name, or an
  attribute with such a name or any dunder attribute. Lambdas, comprehensions and nested defs bind their own names
  (the first iterable of a comprehension is read in the enclosing scope, so `[x for os in os]` is caught). A new
  import of any module outside the list is refused (`import-banned`). Deviations: this narrows the first pass, which
  allowed any new import that bound no checkish name; `print` and `isinstance` are on the builtin list; a name that an
  unchanged statement of the test already loads may be loaded again except the denied ones. (2) `await`: in an `async
  def` a check counts only when its call is directly under `Await`, so N3 is a dropped check. (3) The location:
  `failures` records now carry `frames`, every repository file of the traceback (`gates.collection.repo_frames`; None,
  so no record, when a frame has an absolute path that is no library, anywhere in it, or when there are more than 20
  files); a candidate needs all of them, and `location`, to match the test or support globs. `__tracebackhide__` in a
  production file of `unit_base..HEAD` (`git diff -G`) removes every candidate, because the hidden frame is not in the
  traceback at all and cannot be seen there (the loc/ case: the junit report of the hidden variant ends in the test's
  own line). A browser test also needs a usage-error message (`TypeError`, `ValueError`, `AttributeError`,
  `NameError`, "must be a", "unexpected keyword argument", "positional argument") and none of the page words (timeout,
  waiting for, locator, strict mode violation, resolved to, not found, net::, ...); the unit gate keeps the traceback
  rule only. Residual risk, stated: a product that makes the test's own line raise (it returns a value the line cannot
  use) is told from a test error only by the proof runs. A round stored by 0.4.45 or earlier has no `frames`, so it
  makes no repair chore. (4) `_repair_proof` accepts a unit test only on the zero-value proof; `base` alone fails the
  attempt (`it fails only against the base code; it must also fail when the product answers its zero values`), pinned
  by a unit whose base answers 5 and head answers 0. Spec: L4-IMP-091 (candidate rule, vocabulary, await, import list,
  proof rule) and the scenarios SCN-IMP-464 to 467. Runs, one at a time: `test_repair_step`, probes, check,
  candidates, collection, failures map, repair integrity, traceability repair, fixloop and fixunit repair: 200 passed;
  `test_gates`, `test_gates_e2e`, `test_report`, `test_integrity`, `test_traceability`, `test_fixloop_ci`,
  `test_resume_independence`, `test_fix_chore_e2e`, `test_judge_step`, `test_template_lock`, `test_fixmark_repairs`:
  217 passed.
