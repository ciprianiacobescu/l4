# A verdict question counts only in the attempt that raised it

## Why

On a consumer (2026-10-30, harness 0.4.45) `l4 restart` started a unit over while its `questions.md` held three verdict
questions answered `accept: ...` in the old attempt [V]. A restart keeps `questions.md` and supersedes only the
questions that are still open (`state/restart.py` `_supersede_open_questions`), while it drops the old attempt's
ledgers (`.l4/`). From then on every run of the new attempt looped: `verdict_status` (`l4.verifier.verdicts`) counted
the three carried-over answers as `ready`, so `_verdicts_ready` (`l4.orchestrator`) took `VERDICTS_ANSWERED` and the
unit verified again (about $0.72 of judge per round); `consume_verdicts` skipped each answer because no
`question.raised` of the new attempt names it (`a question the harness never raised`), so `verdicts_consumed` never
got them; the round ended NEEDS_HUMAN on the same three criteria, and `raise_verdict_questions` asked nothing new
because it treats a `ready` question as still waiting for its target. Three rounds ran before a person noticed; only
the plan's run and cost limits would have ended it.

The four functions disagree on what a verdict question is: `consume_verdicts` requires that the attempt's ledger raised
it, the others read `questions.md` alone.

## What changes

- A verdict question counts (open, ready, invalid, dismissed, waiting for its target) only when a
  `question.raised{kind: verdict}` of the unit's current ledgers names it. One that none names (carried over by a
  restart, or written by hand) is `stale`: it is not ready, not waiting and not consumed, and the round's targets are
  asked again by the normal rules (`raise_verdict_questions`, or the legacy path of L4-VER-013 for a round that raised
  none). `verdict_status` takes the raised ids as a required argument, so every caller (`orchestrator._verdicts_ready`,
  `planner`, `delegate.due`, `verifier.notes`, `legacy_round`, `raise_verdict_questions`) applies the same rule as
  `consume_verdicts`. A unit that already loops stops at its next run on the fixed harness, without a person's edit.
- `l4 restart` also supersedes every verdict question, answered, consumed or open, with
  `superseded by restart` (a verdict judged the old attempt's code and evidence). Answered technical questions stay:
  they are decisions the new attempt keeps. `unit.restarted{superseded_questions}` lists both kinds.
- `l4 questions list` shows a stale verdict question with `stale: raised by an earlier attempt; the next round asks
  again` instead of as waiting.

## Impact

- Code: `l4.verifier.verdicts` (`verdict_status`, `legacy_round`, `raise_verdict_questions`, the helper at ~841),
  `l4.state.fold` (the raised verdict question ids, if the state lacks them), `l4.orchestrator`, `l4.planner`,
  `l4.delegate.due`, `l4.verifier.notes`, `l4.state.restart`, `l4.questions_cli` (the list line).
- Spec: L4-VER-070 added; L4-VER-013 and L4-OPS-004 amended; SCN-VER-257..260, SCN-OPS-52..53; change-table row 105.
- Not in this change: verdict questions of a fix unit raised by its parent (they are in the fix unit's own ledger by
  the existing rules); batching many verdict questions into one delegate call.
