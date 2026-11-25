Read `design.md` first (D1-D7). Requirements: L4-VER-092..095 (`docs/SPEC.md`), scenarios SCN-VER-372..393. Run single test
files only (`uv run --frozen pytest <file> -q -p no:cacheprovider`), never a directory, never two runs at once, and never a
wait loop on `pgrep`. Every group writes its tests first, runs them and sees them fail, then changes the code.

## 1. The skip constructs and the rule (L4-VER-092, D1, D3)

- [ ] 1.1 Tests first, in `tests/unit/verifier/test_scan.py` (the function) and a new `tests/unit/evidence/test_skip_predating.py` (the
  rule, with a temporary git repo as `tests/unit/evidence/test_scope.py` builds one): the table of D3 one case per row,
  an unchanged `skipif`, a condition changed on a continuation line, an alias defined and an old test newly decorated
  with it, a module-level `importorskip` added, a skip added to another test, a fixture that gained `pytest.skip`, a
  removed skip, an unparsable head; the rules 1-5 of D1 (file added, renamed, deleted; test absent at base; blob over
  `MAX_SOURCE_BYTES`; `git show` failing; support and runner-config files changed). SCN-VER-372..378.
- [ ] 1.2 Then add `skip_constructs` to `src/l4/verifier/scan.py` (beside `skip_markers`, which stays as it is) and
  `skip_predating(git, base, head, files, ids, cfg, tree)` to `src/l4/evidence/collect.py` (or a new
  `src/l4/evidence/skippred.py` that `collect.py` imports): it returns the ids of `ids` whose skip predates the unit and
  never raises (every failure is "not predating"). Map an id to `(file, qualname)` with `file_of_test`
  (`src/l4/evidence/testsran.py`) and the classname, as `tamper.names_test_id` reads ids.

## 2. The check and the evidence (L4-VER-092, D2)

- [ ] 2.1 Tests first, in `tests/unit/evidence/test_testsran.py` and `tests/unit/evidence/test_report.py`: `check_tests_ran(...,
  predating=ids)` removes those ids from the finding and puts them in `summary.skipped_predating`; the default `()` is
  the old behaviour (SCN-VER-380); `verdict.json` round trip (`evidence_json`, `render_evidence_json`) with and without
  the new key; the Evidence section prints `Skipped in a changed file before this unit (hold): ...`; `Evidence`
  records: one `Hold(kind="skipped")` per file in `hold_records`, `ran_holds`, `later_holds` without them, `to_json`.
- [ ] 2.2 Then change `TestsSummary` and `check_tests_ran` (`src/l4/evidence/testsran.py`), `report.py` (`:88-90`, `:131-132`,
  `:179`), `Hold.kind`, `Evidence.ran_holds`, `later_holds` and the `records` order (`src/l4/evidence/collect.py`
  `:54-84`, `:321-341`); `collect_evidence` calls the rule of 1.2. Run `tests/unit/evidence/test_testsran.py`,
  `test_report.py`, `test_scope.py` one at a time and `tests/unit/s1/` test files that read `Evidence` (`test_items`,
  `test_canary`), one at a time: the S1 files must not change (D2, last paragraph).

## 3. The round, the question and the reject (L4-VER-093, D2, D4)

- [ ] 3.1 Tests first, in `tests/unit/verifier/test_hold_verdicts.py`, `test_hold_binding.py`, `test_verdict_question_texts.py`,
  `test_fixunit.py` (or a new `test_fixunit_skipped_hold.py`), `test_ladder_evidence.py` and a new
  `tests/unit/state/test_next_step_skipped.py`: `hold_kind` of the text is `skipped` and `hold_subjects` is empty; the
  question text of SCN-VER-381 (ids from `view.paths`, no WHEN THEN request); the binding of SCN-VER-383 (file edit,
  skipped set change); the accept of SCN-VER-382; the reject of SCN-VER-384 (title, source `human`, with and without a
  `WHEN ... THEN ...`, not converted, no fix unit, escalation code, `way_out` text); SCN-VER-385; SCN-VER-379 (diff
  coverage off) in `_collect_step`.
- [ ] 3.2 Then: `HoldKind`, `hold_kind`, `hold_subjects`, `SKIPPED_REJECTED_TITLE`, `_hold_question`, `_hold_finding`
  (`src/l4/verifier/verdicts.py`); `_collect_step` adds the holds and `result.hold_views` (`src/l4/verifier/ladder.py:970-995`);
  `src/l4/verifier/fixunit.py:262-266` treats the title like `JUDGE_VIEW_REJECTED_TITLE`; `_no_task_cause`
  (`src/l4/verifier/fixloop.py:694-712`) and the new code `SKIPPED_TESTS_REJECTED` with `skipped_way_out` in
  `src/l4/state/next_step.py` (`way_out`, `:60-72`). Run each file of 3.1, one at a time.

## 4. Who answers (L4-VER-094, D5)

- [ ] 4.1 Tests first: `tests/unit/delegate/test_pass.py` or `test_review_fixes.py` (no call, escalated, SCN-VER-386),
  `tests/unit/delegate/test_reply.py` (`check_reply` refuses accept and reject, SCN-VER-387), `tests/unit/delegate/test_prompt.py`
  (the prompt names the kind), `tests/unit/verifier/test_verdict_actor.py` (SCN-VER-388: `by: agent`, `delegate` and
  `clarifier` dropped with one `human.void`, `by: human` applied; a second round does not record a second void).
- [ ] 4.2 Then: `_without_a_call` (`src/l4/delegate/run.py:852-872`), `_check_reply` (`src/l4/delegate/reply.py:456-470`), the rule
  line of `src/l4/delegate/prompt.py:93-94`, and the filter after `effective_verdicts` in `_finalize`
  (`src/l4/verifier/ladder.py:1098`). Check that a voided consumed question is asked again (`raise_verdict_questions`,
  `verdicts.py:862-884`) with a ladder test; if it is not, ask the hold under a new question in `_finalize`.

## 5. Retry of a `fixing` unit (L4-VER-095, D6)

- [ ] 5.1 Read first, and write down in the test file's docstring: that `Orchestrator.resume` (`src/l4/orchestrator.py:681-`)
  can record `unit.retried` for a unit in `fixing` with no phase edge (`state/lifecycle.py:122-144`), and that
  `question.superseded` (`state/fold.py:272`) takes a fix unit's technical question out of `questions.open`. Where
  either is not so, the task says what 5.2 changes.
- [ ] 5.2 Tests first, in `tests/unit/state/test_retry.py` (or the file that holds the `refuse` tests), `tests/unit/verifier/test_fixloop.py`,
  `tests/unit/specs/test_questions*.py`, `tests/unit/planner/` and `tests/unit/verifier/test_integrity*.py`: SCN-VER-389
  (ticks, `already-done` commit and `task.done{closed_by}`, `superseded by retry`, `fix.done`, `verifying`, a fresh round
  with the hold, no `-fix-3`), SCN-VER-390 (`questions.open`, `l4 plan`, the label), SCN-VER-391 (the refusal text and
  no event), SCN-VER-392 (step 1 blocker for a person's tick: the existing behaviour, pinned), `holds()` ignoring a
  `superseded by retry` question, step 1 `check_tdd_history` skipping the closed task.
- [ ] 5.3 Then: `refuse` and `retry_unit` (`src/l4/state/retry.py:61-141`: `fixing` accepted only when
  `questions_hold` is true for the open fix unit; `close_fix_unit` on the event), the fold (`src/l4/state/fold.py`,
  the new key of `unit.retried`), `fix_hook` (`src/l4/verifier/fixloop.py:410-447`: the close before the first task
  selection, harness commits, trailers as `_already_done` writes them, `tdd.py:3104-3122`), `QuestionsFile.supersede_by_retry`
  and `SUPERSEDED_BY_RETRY` (`src/l4/specs/questions.py:275-276`, `:396`, `:500-530`, `holds` `:753`).

## 6. Documents

- [ ] 6.1 `docs/SPEC.md`: L4-VER-092..095 and SCN-VER-372..393 next to L4-VER-091 and SCN-VER-371; the amended step 3 row
  (`:6159`), the paragraph "Holds are decisions too" of L4-VER-013 (`:7249`), L4-DLG-024 (`:5957`), the evidence JSON and
  the Evidence section; the change table row. `docs/runbook.md`: section 7.1 (the hold and its two answers, with D1's
  residuals), 7.3.4 `skipped_tests_rejected`, the retry of a `fixing` unit with the **order**: upgrade the pin to the
  release first (`l4 upgrade --harness-ref <release>`, merge to base, an `l4` of the pin), then `l4 retry`, then answer
  the hold; why a person's tick is not the way (SCN-VER-392); section 8 table row; section 11 known limits.
  `CHANGELOG.md` under Unreleased: Changed (the finding becomes a hold), Added (hold kind, `skipped_predating`,
  `skipped_tests_rejected`, `l4 retry` in `fixing`), and an **Upgrade** line for a unit already in `fixing` for this
  finding. Run `tests/unit/docs/` files that read the runbook, one at a time.
- [ ] 6.2 `openspec validate skipped-test-hold --strict`; `uv run --frozen ruff check` and `mypy` on the changed files;
  a last pass: grep the new text for a consumer's name (none).
