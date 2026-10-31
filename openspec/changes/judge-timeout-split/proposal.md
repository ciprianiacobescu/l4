## Why

A consumer's unit (29 criteria, 4 parts) lost its judge in round 3: part 3's call ran out of `verifier.judge_timeout_s`
(600 s), `run_judge` retried the same prompt once and that call ran out too, so the reply was discarded and the round
held with no verdict (step 9 failed after 2,814 s). The same judge had answered the same parts in round 1. A judge that
needs longer than the timeout to answer every criterion of a part is in the same position as one whose reply does not
fit its output limit (L4-VER-071): fewer criteria per call shorten both the reply and the time to write it.

## What Changes

- A step-9 prompt of two or more criteria whose call times out is split like a length stop (L4-VER-071): the same
  judge is asked for each half of the criteria, and a half that times out is split again, at most
  `verifier.judge_length_splits` times.
- While a prompt can still be split, its timeout is not retried with the same prompt (`run_judge(retry_timeout=False)`):
  the split is the retry. A batch that cannot be split again keeps today's one retry, and its timeout holds the round as
  today.
- `judge.length_split` gains `cause` (`length` or `timeout`).

Not in this change: follow-up calls (unchanged: a timeout keeps the parts' verdict); the timeout value; other roles.

## Impact

- Code: `l4.verifier.judge.run_judge` (`retry_timeout`), `l4.verifier.ladder` (`_judge_call`, `_ask_judges`,
  `_ask_batches`).
- Spec: L4-VER-071 amended; SCN-VER-270..272; change-table row 111.
- Time: a prompt that times out costs one timeout instead of two before it is split; a part whose every batch times out
  costs at most one timeout per level and one retry at the last (4 timeouts per part with the default, today 2).
