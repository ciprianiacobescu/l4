## Context

`run_judge` (verifier/judge.py) makes at most `MAX_CALLS` (2) calls: a `timeout` status is neither returned at once nor
repaired, so the loop calls again with the same messages and a second timeout is returned. `_ask_judges` treats
`timeout` like `schema_invalid`: it ends the chain, and `judge_body` holds the round (`the judge's reply was discarded
(part K of N, timeout: no answer within 600s)`). 0.4.48 added the split of a prompt whose reply stopped at the output
limit (`_ask_batches`, L4-VER-071), keyed on `JudgeRun.length_stop`.

## Decisions

### D1 A timeout of a prompt that can be split is split, not retried

`run_judge(..., retry_timeout: bool = True)`: with False, a call that ends `timeout` is returned at once (`calls` 1,
status `timeout`). A prompt can be split when `rebuild` is set, it has two or more criteria and the cut it would make is within
`verifier.judge_length_splits`: the 0.4.48 numbering stays (the first cut, of the whole prompt, is depth 1; a batch made
at depth D can be cut when D < `judge_length_splits`). `_judge_call` passes `retry_timeout=not splittable`.

- `_ask_judges`: after the whole prompt's call, `timeout` on a splittable prompt goes to `_ask_batches(cause="timeout")`,
  as a length stop goes with `cause="length"`.
- `_ask_batches`: each half is called with `retry_timeout` False when it can itself be split; a half that ends `timeout`
  or a length stop and can be split is split again; a half that cannot be split keeps the one retry, and its `timeout`
  is returned as it ended, so the round is held as today.
- A follow-up passes no `rebuild`: its calls keep the retry and a timeout keeps the parts' verdict (L4-VER-057).

### D2 Records

`judge.length_split` gains `cause` (`length` or `timeout`); its other fields, `verify.judge` and `judge_batches` are
unchanged. `verifier.judge_length_splits` bounds both causes (its name is kept: 0.4.48 shipped it).

## Risks / Trade-offs

- With the default, a part whose every batch times out costs the whole prompt's timeout, one per level and a retry at the
  last: 4 × `judge_timeout_s` per part (2,400 s at 600 s) where today it costs 2; a 4-part diff that times out everywhere
  (an outage) costs 16 × 600 s before the hold. The parts are asked in order and the first part whose batches all time
  out holds the round, so the worst case needs the outage to begin after the earlier parts answered. A judge that answers smaller batches in time,
  which is the expected case, costs less than today's retry.
- A timeout from an outage, not from the prompt's size, is split too; the batches then time out and the round is held as
  today, later.
