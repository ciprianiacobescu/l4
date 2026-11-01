## Why

A consumer's unit raised 51 questions in one verification round (25 verdict questions from a discarded judge reply,
25 UI holds and one hold). The delegate asked them one call at a time: 30 calls spent $43.83 of the unit's $50 cap,
about $1.46 a question, and the remaining 21 questions escalated to a person on the cost cap, though nothing about them
was harder. Each call paid again for the same reading: the system rules, the unit's specification, the earlier answers,
and the agent's own reading of the same files at the same head to check the same verification report.

The verdict questions of one round share almost all of that material. Asked together, the shared reading is paid once.

## What Changes

- The verdict questions of one target folder (the unit, or its open fix unit) that are due in a pass are asked in
  batches of up to `delegate.batch_size` (new, default 6; 1 asks one question per call as before). Each question first
  passes its own checks (still open, its limits, a question no call can settle, the soft deadline), as today.
- A batch is one call with one prompt (`delegate-batch@1`): the shared blocks once, then each question with its own
  target, judge reason and verification lines. The reply is `l4/delegate-batch@1`, one `l4/delegate-result@1` per
  question. Every result is checked on its own, with the question's own inputs, and answered, deferred or escalated on
  its own; a missing or doubled result is that question's failed attempt.
- Money: a batch of N needs N answers' cost left in the unit's cap and the plan's share (it is shortened to fit), and
  Claude Code's budget for the call is N times `max_cost_usd_per_answer`, so the worst case is today's. The call's cost
  is recorded once; each question's result carries its share.
- Independence: only questions with the same askers share a batch, so one selection is the one each would get alone;
  a served model that is an asker discards the batch's replies, as it discards one reply today.
- A question whose batch call timed out or failed is asked alone on its retry, and a batch whose prompt is too long is
  shortened.
- `delegate.max_questions_per_run` keeps counting questions, not calls.
- A batch of one, and every question of another kind, uses `delegate@7` and `l4/delegate-result@1` unchanged.

## Impact

- Code: `l4.delegate.run` (`_Pass.run` forms batches; `_ask_batch`), `l4.delegate.prompt` (`build_batch_prompt`,
  `batch_schema`, `BATCH_SYSTEM`), `l4/delegate/delegate-batch.schema.json` (new), `DelegateCfg.batch_size`, the doctor's
  DLG settings line.
- Spec: L4-DLG-028 (new); L4-DLG-003 (questions, not calls, under the cap), L4-DLG-005 (the batch document),
  L4-DLG-009 (a batch needs N answers' cost), L4-DLG-004 (the batch prompt); §3.2 `delegate.batch_size`;
  SCN-DLG-127..133; change-table row 116.
- Cost: one call for up to six verdict questions in place of six. A timeout or an adapter error of a batch costs each
  of its questions an attempt, as N separate timeouts would.
