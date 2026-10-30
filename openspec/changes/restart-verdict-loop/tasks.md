## 1. Verdict questions count only when this attempt raised them

- [ ] 1.1 Write the tests first: SCN-VER-257..260 (with real `questions.md` files and ledgers, through the orchestrator's
  run path and the planner as the existing verdict tests build them; SCN-VER-257 asserts no `verify.judge` event).
  Then give `verdict_status` a required keyword `raised: Collection[str]` (the ids of `question.raised{kind: verdict}`
  in the unit's current events; add them to the fold's `UnitState` if no field holds them), skip every verdict question
  not in it (`stale`, a new tuple of `VerdictQuestions`), and pass it from every caller (`git grep -n "verdict_status("`:
  orchestrator `_verdicts_ready`, planner ~388, delegate/due.py ~103, verifier/notes.py ~45, `legacy_round`,
  `raise_verdict_questions`, and the reader at verdicts.py ~841). `consume_verdicts` keeps its rule.
- [ ] 1.2 `l4 questions list` (and `show`, and the `--json` form as a field) marks a stale verdict question with
  `stale: raised by an earlier attempt; the next round asks again`. Test it.

## 2. Restart supersedes the old attempt's verdict questions

- [ ] 2.1 Write the tests first: SCN-OPS-52, SCN-OPS-53 (the restart tests' real repositories). Then make step 3 of
  `l4.state.restart` supersede every verdict question that the old attempt's ledgers did not consume (`human.verdict`
  for its id), answered or open, with `superseded by restart` (`QuestionsFile.supersede_by_restart`), keep answered
  technical questions, and list both kinds in `unit.restarted{superseded_questions}`. Update the module docstring.

## 3. Checks

- [ ] 3.1 Run once with pytest (in the foreground, never in a loop, never two runs at once) the test files you changed
  or added plus the verdict, legacy, planner, delegate-due, notes, restart and questions-cli test files; not whole
  directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md,
  CHANGELOG.md or docs/runbook.md.
