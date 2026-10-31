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
- [x] 1.2 `l4 questions list` (and `show`, and the `--json` form as a field) marks a stale verdict question with
  `stale: raised by an earlier attempt; the next round asks again`. Test it.

  Result: `l4 questions list` reads each folder's ledger once (`folder_events`, the lock ref's pending file included) and
  folds `verdicts_raised`; a verdict question outside it (Status not superseded) is stale. It is listed whatever its
  Status (an answered stale one too, which the open-only listing would hide): `<unit> Q-001 stale <blocking> <title>`
  and under it the line `stale: raised by an earlier attempt; the next round asks again`. The `Next:` line points at the
  first row that is not stale. `--json` rows get `status`, `stale` and, for a stale one, `note`; `show` prints
  `Q-001 is stale: ...` and its JSON gets `stale` and `note`. The delegate hint of the list leaves stale questions out.
  A fix unit's folder is never marked, and a ledger that does not read gives no stale mark (its warning is shown instead).
  Tests: 5 added to `tests/unit/specs/test_questions_cli.py` (a real origin branch with a real `questions.md` and
  ledger); on the code before, 4 failed (the fifth pins what did not change: a question this attempt raised is listed as before). 108 passed in that file.

## 2. Restart supersedes the old attempt's verdict questions

- [x] 2.1 Write the tests first: SCN-OPS-52, SCN-OPS-53 (the restart tests' real repositories). Then make step 3 of
  `l4.state.restart` supersede every verdict question, answered, consumed or open, with `superseded by restart`
  (`QuestionsFile.supersede_by_restart`; a question already superseded stays as it is), keep answered
  technical questions, and list both kinds in `unit.restarted{superseded_questions}`. Update the module docstring.

  Result: step 3 (`_supersede_questions`, renamed from `_supersede_open_questions`) now sets to `superseded by restart`
  every question that is `open` (any kind, as before) and every verdict question that is not already superseded, in file
  order; the Status line needs to exist, as before. It cannot tell a consumed verdict question from an answered one in
  `questions.md` (the consumption is in the dropped ledger), so it acts on the kind alone. Answered technical questions
  stay byte for byte; a verdict question already `superseded by round 2` stays. `unit.restarted{superseded_questions}`
  lists all of them. The module docstring (step 3) is updated. Tests: SCN-OPS-52 and SCN-OPS-53 in
  `tests/unit/state/test_restart.py` (real origin, real restart, six questions of mixed kinds and Statuses; SCN-OPS-52
  also checks the planner facts show no verdict open or ready afterwards). On the code before, SCN-OPS-52 failed;
  SCN-OPS-53 passed (it pins the behaviour that stays). 99 passed in `test_restart.py` and `test_questions.py`.

## 3. Checks

- [x] 3.1 Run once with pytest (in the foreground, never in a loop, never two runs at once) the test files you changed
  or added plus the verdict, legacy, planner, delegate-due, notes, restart and questions-cli test files; not whole
  directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md,
  CHANGELOG.md or docs/runbook.md.

  Result: one pytest run in the foreground of the 20 files changed or added plus the verdict, legacy, planner,
  delegate-due, restart, questions and questions-cli files and `test_ladder_fix.py`, `test_ledger_writes.py` and
  `test_delegate_sim.py` (the ladder and delegate paths that raise and consume verdict questions): 450 passed, 0 failed,
  980 s, run on this branch's own environment (`uv run`). There is no test file for `verifier/notes.py` of its own:
  `verdict_section` is covered by the sticky-note tests in `test_stale_verdicts.py` and `test_legacy_round.py`.
  `ruff check` on `src` and `tests` is clean, and `ruff format --check` accepts every changed file but
  `test_gate_forgery.py`, which was already unformatted before this change (29 files of the repository are) and is left as it was. Nothing was run on whole
  directories. Not changed: docs/SPEC.md, CHANGELOG.md, docs/runbook.md. Deviations, all stated above: the reader at
  `verdicts.py` ~841 needed no change; SCN-VER-260 patches the setup rounds; the legacy check is `.any is False` over the
  non-stale questions, which is stricter than the amended wording of L4-VER-013 ("every verdict question naming the
  round's targets is stale") in one case: a live waiting question for another target also stops the legacy path, as
  before; the fold takes the raw ledger id of a `question.raised{kind: verdict}` as `consume_verdicts` does, so a fix
  unit's verdict event in the parent's ledger would also name the parent's same-numbered question (fix units raise none
  by the existing rules).

## 4. Review fixes (R1)

- [x] R1-1 The evidence commit of a round holds the run's ledger (`ledger_path(...)` joins the `paths` of
  `_commit_evidence` in `verify_hook`), so the `question.raised` of the round's questions reaches origin with the
  `questions.md` that `ctx.push()` publishes. Before, `l4 questions list`/`show` and the MCP tool read a question of the
  run in that window as stale, and a run killed in it lost the event (the next round asked the target under a new id).
  Result: `test_the_question_is_open_on_origin_when_the_evidence_commit_is_pushed` folds the origin branch from inside
  `after_verdict` (after the evidence push, before the close): `open=["Q-001"]`, `stale=[]`; it failed on the code before.
- [x] R1-2 SCN-VER-260 asserted two reads of the same origin against each other. It now asserts
  `[e["round"] for e in fixed.events("verify.verdict")] == [1, 2, 3]` (the unfixed harness would make a round 4); on the
  code before the fix the setup passed and this final run failed (it ran a judge-less round 4).
- [x] R1-3 The "no judge call" checks of SCN-VER-257 and 260 now follow a person's commit that changes the code
  (`change_code`), so the round cannot resume from round 1's record and the old rule judges the new subject. Checked on
  the source before this change (`6fbdb9bc`): 257 and 260 failed on their final run with exit 1, because the unfixed
  harness started a round that needed a judge and the test supplied none (a crash, not a count mismatch; it does
  discriminate). The change also means SCN-VER-258 now makes one judge call (the round cannot resume from round 1's record;
  the accept carries over because it binds to the criterion's text hash, not to the code), which the 1.1 Result did not say.
- [x] R1-4 When `raise_verdict_questions` asks a target that a stale question names, that stale question is set to
  `superseded by Q-NNN` (new `QuestionsFile.supersede_by_question`, next to `supersede_by_round`; the index row follows;
  the answer stays as history). Only stale questions of the targets asked again change; a stale question of another
  target stays stale and listed, and a waiting live question changes nothing. Tests: three in `test_verdicts.py`, and
  SCN-VER-257 asserts Q-001 reads `superseded by Q-002` and its index row says superseded (the spec's Q-004 is Q-002 in
  this fixture). Two of the three failed on the code before; the third pins that a waiting question changes nothing.
  `l4 questions list` no longer shows such a question: `test_list_does_not_show_a_stale_verdict_question_that_a_new_one_superseded`
  (a `superseded by Q-002` verdict row is neither listed nor stale; it passes on the code before, since a superseded
  question was never listed, and pins the interaction). `_supersede_stale` writes no `question.superseded` event, unlike
  `supersede_stale_verdicts`: a stale question is not in this attempt's `questions.open`, so nothing needs to leave it.
- [x] R1-5 Wording and one test. The MCP `l4_questions` and `l4_question` descriptions say stale questions are listed or
  marked. The planner's reason for a stale-only legacy round reads `legacy round N: NEEDS_HUMAN, and its verdict
  questions were raised by an earlier attempt (Q-001, ...), the run raises them again` (new fact `verdicts_stale`); a
  round with no question ever raised keeps the old text. `l4 questions answer` on a stale question prints one line,
  `Q-NNN is stale: raised by an earlier attempt; the next round asks its criterion again`. The unreadable-ledger warning
  names the unit once and what is not shown (`no question is marked stale` in the list, `no frozen path or stale mark is
  shown` in show and by default); it no longer says only "frozen paths". `test_a_stale_verdict_question_is_not_a_target_of_the_pass`
  covers `_Pass._targets` (a real `questions.md`, a fake pass object: a question that no event names is not a target,
  one that an event names is). It passes on the fixed code of 1.1; on the source before 1.1 it cannot run (the helpers use
  `verdicts_raised`), so it is regression cover, not a red test. The other new tests of this item failed on the code before.
- [x] R1-6 Documented, not changed. The legacy check is stricter than the wording of L4-VER-013: a live question for A
  with stale ones for B and C (rounds run on 0.4.45) asks B and C one round later, once A is answered and consumed,
  never stuck (spec note on L4-VER-013, proposal Notes). `delegate/run.py` `_Pass._events` and the `before` read of
  `consume_verdicts` read the branch ledger only, not the lock ref's pending ledger: unreachable today (the orchestrator
  folds both, and the evidence commit now carries the run's ledger) and no regression (proposal Notes). The spec text of
  L4-VER-070 and SCN-VER-257 now says the stale question is superseded and that the ledger travels with the evidence: a
  deviation from "document only", since R1-1 and R1-4 are behaviour changes the spec had to pin.
- [x] R1-7 Checks. One foreground run of the files changed or added by R1 plus `test_verdicts`, `test_fold_verdicts`,
  `test_delegate_action`, `test_questions_cli`, `test_restart`, `test_legacy_round`, `test_verdict_reentry` and the ladder
  tests that cover the evidence commit (`test_ladder_evidence`, `test_ledger_writes`): 358 passed, 0 failed, 1057 s. The
  evidence-commit tests needed no change to their expectations. The one test added after that run
  (`test_list_does_not_show_a_stale_verdict_question_that_a_new_one_superseded`) was run alone: 1 passed. `ruff check` on
  `src` and `tests` is clean; `ruff format --check` finds the same 29 files as before this change and no new one.
