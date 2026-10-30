## 1. Verdict questions count only when this attempt raised them

- [x] 1.1 Write the tests first: SCN-VER-257..260 (with real `questions.md` files and ledgers, through the orchestrator's
  run path and the planner as the existing verdict tests build them; SCN-VER-257 asserts no `verify.judge` event).
  Then give `verdict_status` a required keyword `raised: Collection[str]` (the ids of `question.raised{kind: verdict}`
  in the unit's current events; add them to the fold's `UnitState` if no field holds them), skip every verdict question
  not in it (`stale`, a new tuple of `VerdictQuestions`), and pass it from every caller (`git grep -n "verdict_status("`:
  orchestrator `_verdicts_ready`, planner ~388, delegate/due.py ~103, verifier/notes.py ~45, `legacy_round`,
  `raise_verdict_questions`, and the reader at verdicts.py ~841). `consume_verdicts` keeps its rule.

  Result: `UnitState.verdicts_raised` (the fold, from `question.raised{kind: verdict}`, raw ids as `consume_verdicts`
  reads them) is the one source of the raised ids; `verdict_status(file, consumed, *, raised)` takes it as a required
  keyword and returns the new `stale` tuple. Callers: orchestrator `_verdicts_ready`, `_raise_legacy_verdicts` and the
  two `verdict_section` calls (the fold of `self.state`, refolded after each `_go`), planner `facts_of`, `legacy_round`
  (reads `state.verdicts_raised`), `held_ids` for `delegate/due.py` and `delegate/run.py`, `verdict_section`
  (`verifier/notes.py`, a required `raised`) and `raise_legacy_verdicts`. `raise_verdict_questions` takes a required
  `raised`; in `verifier/ladder.py` `_ask_verdicts` computes it with one helper `_raised_now` (the branch ledger files
  plus the lock ref's pending files, as the orchestrator folds them) before the raise and again after it, so the note
  built after the raise sees this run's own questions. Deviation: the reader at `verdicts.py` ~841
  (`supersede_stale_verdicts`) never called `verdict_status` and already applies the raised rule through `_raised`, so
  it is unchanged. `consume_verdicts` is unchanged. Tests: new `tests/unit/verifier/test_stale_verdicts.py` (SCN-VER-257,
  258, 260, the plan row, the sticky note: 5 tests, real branch, ledger and `questions.md`); SCN-VER-259's delegate half
  in `tests/unit/planner/test_delegate_action.py`; stale/legacy/raise cases in `test_verdicts.py`; the fold field in
  `test_fold_verdicts.py`; the existing tests pass `raised=`. SCN-VER-260 builds the looping unit with two patched runs
  (the old `_verdicts_ready` rule and a `raise_verdict_questions` that asks nothing), since the fixed code cannot loop;
  the last run is unpatched. Run on the code before the fix, the five tests of that file failed (257 took `verdicts_answered` and verified round 2; 260 ended without a new question), as did the SCN-VER-259 delegate test and the fold test. After the fix: 5 passed there, 128 passed in the verdict, supersede, hold, fold, delegate-action and question-text files.
- [ ] 1.2 `l4 questions list` (and `show`, and the `--json` form as a field) marks a stale verdict question with
  `stale: raised by an earlier attempt; the next round asks again`. Test it.

## 2. Restart supersedes the old attempt's verdict questions

- [ ] 2.1 Write the tests first: SCN-OPS-52, SCN-OPS-53 (the restart tests' real repositories). Then make step 3 of
  `l4.state.restart` supersede every verdict question, answered, consumed or open, with `superseded by restart`
  (`QuestionsFile.supersede_by_restart`; a question already superseded stays as it is), keep answered
  technical questions, and list both kinds in `unit.restarted{superseded_questions}`. Update the module docstring.

## 3. Checks

- [ ] 3.1 Run once with pytest (in the foreground, never in a loop, never two runs at once) the test files you changed
  or added plus the verdict, legacy, planner, delegate-due, notes, restart and questions-cli test files; not whole
  directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md,
  CHANGELOG.md or docs/runbook.md.
