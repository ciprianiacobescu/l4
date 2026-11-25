Read `design.md` first (D1-D7). Requirements: L4-VER-092..095 (`docs/SPEC.md`), scenarios SCN-VER-372..399. Run single test
files only (`uv run --frozen pytest <file> -q -p no:cacheprovider`), never a directory, never two runs at once, and never a
wait loop on `pgrep`. Every group writes its tests first, runs them and sees them fail, then changes the code.

## 1. The skip constructs and the rule (L4-VER-092, D1, D3)

- [x] 1.1 Tests first, in `tests/unit/verifier/test_scan.py` (the function) and a new `tests/unit/evidence/test_skip_predating.py` (the
  rule, with a temporary git repo as `tests/unit/evidence/test_scope.py` builds one): the table of D3 one case per row,
  an unchanged `skipif`, a condition changed on a continuation line, an alias defined and an old test newly decorated
  with it, a module-level `importorskip` added, a skip added to another test, a fixture that gained `pytest.skip`, a
  removed skip, an unparsable head; the rules 1-5 of D1 (file added, renamed, deleted; test absent at base; blob over
  `MAX_SOURCE_BYTES`; `git show` failing; support and runner-config files changed). SCN-VER-372..378.
- [x] 1.2 Then add `skip_constructs` to `src/l4/verifier/scan.py` (beside `skip_markers`, which stays as it is) and
  `skip_predating(git, base, head, files, ids, cfg, tree)` to `src/l4/evidence/collect.py` (or a new
  `src/l4/evidence/skippred.py` that `collect.py` imports): it returns the ids of `ids` whose skip predates the unit and
  never raises (every failure is "not predating"). Map an id to `(file, qualname)` with `file_of_test`
  (`src/l4/evidence/testsran.py`) and the classname, as `tamper.names_test_id` reads ids.

## 2. The check and the evidence (L4-VER-092, D2)

- [x] 2.1 Tests first, in `tests/unit/evidence/test_testsran.py` and `tests/unit/evidence/test_report.py`: `check_tests_ran(...,
  predating=ids)` removes those ids from the finding and puts them in `summary.skipped_predating`; the default `()` is
  the old behaviour (SCN-VER-380); `verdict.json` round trip (`evidence_json`, `render_evidence_json`) with and without
  the new key; the Evidence section prints `Skipped in a changed file before this unit (hold): ...`; `Evidence`
  records: one `Hold(kind="skipped")` per file in `hold_records`, `ran_holds`, `later_holds` without them, `to_json`.
- [x] 2.2 Then change `TestsSummary` and `check_tests_ran` (`src/l4/evidence/testsran.py`), `report.py` (`:88-90`, `:131-132`,
  `:179`), `Hold.kind`, `Evidence.ran_holds`, `later_holds` and the `records` order (`src/l4/evidence/collect.py`
  `:54-84`, `:321-341`); `collect_evidence` calls the rule of 1.2. Run `tests/unit/evidence/test_testsran.py`,
  `test_report.py`, `test_scope.py` one at a time and `tests/unit/s1/` test files that read `Evidence` (`test_items`,
  `test_canary`), one at a time: the S1 files must not change (D2, last paragraph).

## 3. The round, the question and the reject (L4-VER-093, D2, D4)

- [x] 3.1 Tests first, in `tests/unit/verifier/test_hold_verdicts.py`, `test_hold_binding.py`, `test_verdict_question_texts.py`,
  `test_fixunit.py` (or a new `test_fixunit_skipped_hold.py`), `test_ladder_evidence.py` and a new
  `tests/unit/state/test_next_step_skipped.py`: `hold_kind` of the text is `skipped` and `hold_subjects` is empty; the
  question text of SCN-VER-381 (ids from `view.paths`, no WHEN THEN request); the binding of SCN-VER-383 (file edit,
  skipped set change); the accept of SCN-VER-382; the reject of SCN-VER-384 (title, source `human`, with and without a
  `WHEN ... THEN ...`, not converted, no fix unit, escalation code, `way_out` text); SCN-VER-385; SCN-VER-379 (diff
  coverage off) in `_collect_step`.
- [x] 3.2 Then: `HoldKind`, `hold_kind`, `hold_subjects`, `SKIPPED_REJECTED_TITLE`, `_hold_question`, `_hold_finding`
  (`src/l4/verifier/verdicts.py`); `_collect_step` adds the holds and `result.hold_views` (`src/l4/verifier/ladder.py:970-995`);
  `src/l4/verifier/fixunit.py:262-266` treats the title like `JUDGE_VIEW_REJECTED_TITLE`; `_no_task_cause`
  (`src/l4/verifier/fixloop.py:694-712`) and the new code `SKIPPED_TESTS_REJECTED` with `skipped_way_out` in
  `src/l4/state/next_step.py` (`way_out`, `:60-72`). Run each file of 3.1, one at a time.

## 4. Who answers (L4-VER-094, D5)

- [x] 4.1 Tests first: `tests/unit/delegate/test_pass.py` or `test_review_fixes.py` (no call, escalated, SCN-VER-386),
  `tests/unit/delegate/test_reply.py` (`check_reply` refuses accept and reject, SCN-VER-387), `tests/unit/delegate/test_prompt.py`
  (the prompt names the kind), `tests/unit/verifier/test_verdict_actor.py` (SCN-VER-388: `by: agent`, `delegate` and
  `clarifier` dropped with one `human.void`, `by: human` applied; a second round does not record a second void).
- [x] 4.2 Then: `_without_a_call` (`src/l4/delegate/run.py:852-872`), `_check_reply` (`src/l4/delegate/reply.py:456-470`), the rule
  line of `src/l4/delegate/prompt.py:93-94`, and the filter after `effective_verdicts` in `_finalize`
  (`src/l4/verifier/ladder.py:1098`). Check that a voided consumed question is asked again (`raise_verdict_questions`,
  `verdicts.py:862-884`) with a ladder test; if it is not, ask the hold under a new question in `_finalize`.

## 5. Retry of a `fixing` unit (L4-VER-095, D6)

- [x] 5.1 Read first, and write down in the test file's docstring: that `Orchestrator.resume` (`src/l4/orchestrator.py:681-`)
  can record `unit.retried` for a unit in `fixing` with no phase edge (`state/lifecycle.py:122-144`), and that
  `question.superseded` (`state/fold.py:272`) takes a fix unit's technical question out of `questions.open`. Where
  either is not so, the task says what 5.2 changes.
- [x] 5.2 Tests first, in `tests/unit/state/test_retry.py` (or the file that holds the `refuse` tests), `tests/unit/verifier/test_fixloop.py`,
  `tests/unit/specs/test_questions*.py`, `tests/unit/planner/` and `tests/unit/verifier/test_integrity*.py`: SCN-VER-389
  (ticks, `already-done` commit and `task.done{closed_by}`, `superseded by retry`, `fix.done`, `verifying`, a fresh round
  with the hold, no `-fix-3`), SCN-VER-390 (`questions.open`, `l4 plan`, the label), SCN-VER-391 (the refusal text and
  no event), SCN-VER-392 (step 1 blocker for a person's tick: the existing behaviour, pinned), `holds()` ignoring a
  `superseded by retry` question, step 1 `check_tdd_history` skipping the closed task.
- [x] 5.3 Then: `refuse` and `retry_unit` (`src/l4/state/retry.py:61-141`: `fixing` accepted only when
  `questions_hold` is true for the open fix unit; `close_fix_unit` on the event), the fold (`src/l4/state/fold.py`,
  the new key of `unit.retried`), `fix_hook` (`src/l4/verifier/fixloop.py:410-447`: the close before the first task
  selection, harness commits, trailers as `_already_done` writes them, `tdd.py:3104-3122`), `QuestionsFile.supersede_by_retry`
  and `SUPERSEDED_BY_RETRY` (`src/l4/specs/questions.py:275-276`, `:396`, `:500-530`, `holds` `:753`).

## 6. Documents

- [x] 6.1 `docs/SPEC.md`: L4-VER-092..095 and SCN-VER-372..393 next to L4-VER-091 and SCN-VER-371; the amended step 3 row
  (`:6159`), the paragraph "Holds are decisions too" of L4-VER-013 (`:7249`), L4-DLG-024 (`:5957`), the evidence JSON and
  the Evidence section; the change table row. `docs/runbook.md`: section 7.1 (the hold and its two answers, with D1's
  residuals), 7.3.4 `skipped_tests_rejected`, the retry of a `fixing` unit with the **order**: upgrade the pin to the
  release first (`l4 upgrade --harness-ref <release>`, merge to base, an `l4` of the pin), then `l4 retry`, then answer
  the hold; why a person's tick is not the way (SCN-VER-392); section 8 table row; section 11 known limits.
  `CHANGELOG.md` under Unreleased: Changed (the finding becomes a hold), Added (hold kind, `skipped_predating`,
  `skipped_tests_rejected`, `l4 retry` in `fixing`), and an **Upgrade** line for a unit already in `fixing` for this
  finding. Run `tests/unit/docs/` files that read the runbook, one at a time.
- [x] 6.2 `openspec validate skipped-test-hold --strict`; `uv run --frozen ruff check` and `mypy` on the changed files;
  a last pass: grep the new text for a consumer's name (none).

## 7. Rework: the base report is a necessary condition (L4-VER-092, D1, review F1-F9)

- [x] 7.1 Tests first (they failed before the code): `tests/unit/evidence/test_skip_predating_reference.py` (one test per case F1-F7 at the
  level of the pure rule, fake reference), `tests/unit/evidence/test_skip_predating.py` (the lookup asked once and only
  for a candidate, no report, a lookup that raises, rule (c) unconditional), `tests/unit/evidence/test_skip_hold_evidence.py`
  (F1, F6, F7 through `collect_evidence`, the source in the view and not in the hold id or binding),
  `tests/unit/verifier/test_scan.py` (blocks, fixtures, run-time markers, aliases), `tests/unit/verifier/test_base_skips.py`
  (the `skipped` key written only for a full reference, lookup order (i)/(ii)/(iii), the cache, fail closed),
  `test_hold_verdicts.py` (the question's wording), `test_ladder_evidence.py` (the lookup of the round), and the combined
  test of `test_retry_fixing.py` in the real-world shape. SCN-VER-394..399.
- [x] 7.2 Then: `scan.collected_tests`, `scan.shared_scopes`, `skip_constructs` (F2-F5), `skippred.no_skip_added` and
  `skip_predates(..., skipped_at_base=)`, `BaseSkips`, `collect.skip_predating(..., base_skips)` returning `Predating`,
  `base_tests.SkipLookup` and the `skipped` key of step 1's record (`Outcome.base_report`), `Workbench.base_skips`, the
  lookup in `_collect_step`, the hold text, the view's `base_source`, `TestsSummary.skipped_source` and `skipped_note`,
  `_hold_question`, the Evidence line.
- [x] 7.3 F9, read in `_close_for_retry`: a crash between the close commit and its `task.done` is NOT fully repaired as it
  was (the commit holds the question's new Status but the ledger lacks `question.superseded`, and the next run's
  `fix.close_skipped` ends the request without writing it, so the fold keeps the question open); fixed by writing
  `question.superseded` before the commit, so it travels inside it. The `task.done` after the commit stays (it names the
  sha); its loss is harmless (step 1 reads the `already-done` commit with no event as nothing to check).
- [x] 7.4 Documents: D1 rewritten, the proposal's non-goal dropped, L4-VER-092 and L4-VER-093 and SCN-VER-372, 378, 381 amended
  and SCN-VER-394..399 added in the change's spec and in `docs/SPEC.md`, the `skipped` key, the runbook (7.1 bullet, 7.3.4 reject
  precedence, 11 known limits: F8, F9, reject precedence), the CHANGELOG entry.

## 8. Rework: in-file dependencies, cost, durable base run, runner files (L4-VER-092, D1, review G1-G7)

- [x] 8.1 Tests first (they failed before the code): `tests/unit/evidence/test_skip_predating_deps.py` (G1: a flag, a guard,
  its setup, a helper that is called, a helper that skips, a flag of a flag, an import now from another module, a changed
  `try`/`except ImportError` fallback, a taken or `autouse` fixture, a class flag, a base class, `setUp`, `pytestmark` of
  any value; an unrelated import, also on the same `import` line, an unrelated test, flag or helper, an assertion after
  the guard and the real-world `INTEGRATION` shape stay a hold; dynamic forms are the residual; a test absent at the head
  and a removed part are no hold), `test_skip_predating.py` (G3: 600 skipped tests in under 10 s; G5: a nested runner
  file by name, a conftest renamed away), `test_base_skips.py` (G2: `SkipLookup.record`, one base run for rounds 3 to 6
  on fresh workbenches through the real writer; G4: a failed run is kept, the exit's message is kept),
  `test_ladder_evidence.py` (G2: `_collect_step` writes the record, also when evidence collection raises),
  `test_hold_verdicts.py` (the question's wording), `test_retry_fixing.py` (G6: the window and its repair).
- [x] 8.2 Then: `scan.SkipReader`, `scan.skip_constructs_in`, `scan.collected_in`; `l4.verifier.skipdeps.SkipFacts`
  (one parse and one scan per source, the closure of a test); `skippred.SkipRule` (rules (b), (c), (d) for one file),
  `RUNNER_NAMES`; `collect.name_status` (the old path of a rename) and `skip_predating` (one rule per path);
  `Workbench.base_runs` and `BaseRun` (the report, or why there is none), `_run_base_gate` (kept also on failure, an
  exit is kept and raised again to the caller that made the run), `SkipLookup.record`, `ladder._keep_base_run`; the four
  `base_skips` carry lines (`orchestrator._escalate`, `_fall_back`, `fixloop._escalation`, `_fall_back`) removed: only
  the verifier makes this run, so they read nothing; `_hold_question`.
- [x] 8.3 G6, decided with evidence (a failed closing commit, injected): the ledger-ahead window is real and the next run
  repairs it; the code is kept, the window is pinned by a test and documented (design D6, L4-VER-095, SCN-VER-404, runbook 11).
- [x] 8.4 Documents: design D1 (a) 3, (b) 1 and 5, (c), the new (d), the residual list and the environment difference of
  the base run; D3; D6; L4-VER-092, L4-VER-093, L4-VER-095 and SCN-VER-396, 398 amended and SCN-VER-400..404 added in the
  change's spec and in `docs/SPEC.md` (step 3 row, the change table row); the runbook (7.1 hold bullet, 11 known limits:
  the base run has no network, the window); the CHANGELOG entry.

## 9. Rework: where the unit may change the file, a whitelist (L4-VER-092, D1 (e), review H)

- [x] 9.1 Tests first (they failed before the code): `tests/unit/evidence/test_skip_predating_location.py` (the 86 cases of
  review H, `t1.py`, `t2.py` and `t3.py`, each asserting `no_skip_added` is False, except the three unchanged controls and
  the run-time-state residual, which are asserted True and named; positive controls: the real-world shape also through
  `collect.skip_predating`, a comment-only change, a blank line between functions, a whole new test method, a changed body
  or decorator of another test, a new import of a new name; negative controls: an import that rebinds, a builtin, `*`,
  `__future__`, a docstring, a module statement, a class attribute, `setup_method`, a fixture, a candidate's prefix,
  signature, default and decorators, a moved candidate, a deleted `def` line, a `def` inserted into a helper, a string that
  swallows a fixture, a blank line inside a string; (c): one test per new name group in three directories, a support
  module under `tests/` added, changed, deleted and renamed); `test_base_skips.py` (note A: a failure that is not an
  `L4Exit` is kept and not run again).
- [x] 9.2 Then: `l4.evidence.skipscope` (`Confined`: pairing of statements by tree and by text, the added-import rule,
  `RESIDUALS`), `SkipFacts.skip_relevant` and `.ambiguous` and the memoised prefix (`skipdeps`), `SkipRule.changes_confined`
  and `RUNNER_NAMES`/`RUNNER_PATTERNS`/`support_module` (`skippred`), `collect._support_modules`, `base_tests._exit_reason`
  and `SkipLookup._look`/`_run_base_gate` keeping any failure, the question (`verdicts._hold_question`) and the Evidence
  line (`report`) with the same residual list. Found in the review of 9.1 and fixed with tests: a collected test
  that a string condition, a decorator, a helper or the prefix of T reads by its name is kept whole, and a statement that
  calls `request.getfixturevalue(...)` ends T's free body. Existing tests that expected a hold with an unrelated flag, helper, fixture,
  class decorator or a name added to an import line, or with a support module added, now expect the finding.
- [x] 9.3 Documents: design D1 ((c) names, the new (e), what the conditions cover, residuals, the failed-run sentence), D3;
  L4-VER-092 and SCN-VER-381, 400, 401, 402 amended and SCN-VER-405..408 added in the change's spec and in `docs/SPEC.md`
  (also the step 3 row and the change table row); runbook 7.1 hold bullet and section 11; the CHANGELOG entry.

## 10. Rework: added imports, transitive reach, decorators, getfixturevalue and raise (L4-VER-092, D1 (e), review J)

- [x] 10.1 Tests first (they failed before the code): `tests/unit/evidence/test_skip_predating_imports_reach.py` (G1: an added
  import of a module outside the standard library, a relative import, a name a runner reads off a module, a name the base
  spells as a parameter, a fixture or a string; G2: a test two and three calls away from the skip, also through a helper;
  G3: a decorator that is no plain `pytest.mark.<name>` on an existing, a new and a deleted test, an alias of
  `pytest.fixture`; G4: `getfixturevalue` by an alias, a string or `getattr`; G5: `raise` of anything and the names
  `Skipped`, `SkipTest`, `skip.Exception`; positive controls: the real-world shape, `import json`, a comment, a blank line,
  a new test with `@pytest.mark.slow`, a new method of an existing class).
- [x] 10.2 Then `l4.evidence.skipscope`: `_standard_library`, `_read_by_runner`, `_Names.importable` (parameters, fixtures
  and identifier-like strings of the base), `_Side.grow` (the fixed point, used by `build` and by `Confined.holds`),
  `_plain_mark` and `Confined._decorators` (any collected test, both sides), `_Side.prefix` (a `raise` or a skip
  exception name ends the free body, `getfixturevalue` anywhere protects the whole body), `RESIDUALS`. Existing tests whose
  expectation changed: `test_skip_predating.py` (`test_a_removed_skip_never_counts`, `..._changed_condition_on_a_continuation_line...`,
  `..._skip_decorator_added_to_one_test_keeps_the_whole_file_a_finding`, `..._alias_newly_applied_to_an_old_test...`: a decorator of another
  test that is no plain mark is no free change, so the file is no hold for any test), `test_skip_predating_location.py`
  (a replaced decorator of another test and a relative import move to the finding list; `request.getfixturevalue` followed
  by an assertion; the parametrize residual becomes a plain mark residual), `test_skip_hold_evidence.py` (two tests that
  added a decorator to `test_a` now add a skip call to its body or expect `test_b` in the finding), `test_hold_verdicts.py`
  (the residual wording).
- [x] 10.3 Documents: design D1 ((e) items 2 and 3, what (e) leaves, the residual list), L4-VER-092 and SCN-VER-373..376, 400, 405,
  406 amended and SCN-VER-409..411 added in the change's spec and in `docs/SPEC.md` (also the step 3 row and the change table
  row); the residual list in L4-VER-093, SCN-VER-381, the runbook (7.1 hold bullet, section 11) and the CHANGELOG entry.
