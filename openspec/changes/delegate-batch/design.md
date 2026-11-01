## Context

`_Pass.run` lists the due questions oldest first (`(target, question)` pairs over the unit and its open fix unit) and
calls `_question` for each until the cap (`max_questions_per_run`, counted in `self.calls`) or, in a delegate-only run,
until none is due, the first soft-deadline deferral or a cost limit. `_question` re-reads the question (`_current`),
checks `limit_reached`, `_without_a_call` and `_soft_deadline`, selects a profile with the question's own askers
(`select_delegate`) and calls `_ask`. `_ask` builds `delegate@7` (`_prompt`), records `delegate.asked`, calls the
adapter read-only (`_call`, Claude Code with `max_budget_usd = max_cost_usd_per_answer` and `MAX_TURNS`), records the
cost (`_record_cost`), follows a limit to the next profile, and then defers, escalates or checks the reply
(`check_reply` with the question's frozen paths, existing tests, chore flag, cap-only file and judge-view files) and
answers (`_answer`, one commit per answer). `delegate_cost` sums `budget.cost{role: delegate, usd}` and counts every
`delegate.result{called}` with no `cost_usd` at `max_cost_usd_per_answer`.

## Decisions

### D1 Which questions share a call (L4-DLG-028)

A verdict question starts a batch; the questions after it in the pass's order that are verdict questions of the same
target folder with the same askers (`askers(events, key, implementers)`, the set the independence veto reads) join it,
up to `delegate.batch_size` questions and, in a capped pass, up to the questions the cap still allows (with the defaults,
6 and 5, a capped pass asks one batch of 5). Questions with other askers are never in one batch, so no question that a
profile could answer alone becomes unservable in company (SCN-DLG-06). A question whose latest `delegate.result` of its
current raise is a deferral from a batch call that ended `timeout` or `error` (`batch` set) is asked alone on its retry,
so that a batch too large for the timeout does not fail again and escalate all its questions. A question whose blocking tasks or verdict target (the keys `answers_used` counts) meet a key of a question
already in the batch does not join; it starts a later batch. Before the call each candidate passes the checks
`_question` makes today, in the same order: `_current` (a question answered meanwhile is dropped), `limit_reached`
(escalated as today), `_without_a_call` (escalated as today) and the soft deadline (deferred as today; it also ends
the batch, as the first soft deadline ends a delegate-only pass). The candidates that pass are the batch. A batch of
one is asked by `_ask` exactly as today. A question of another kind is asked alone, as today.

`self.calls` counts questions: a batch adds its size, so `max_questions_per_run` still bounds the questions a capped
pass asks.

### D2 Money (L4-DLG-009)

A batch of N needs `N × max_cost_usd_per_answer` left in the unit's cap (`max_cost_usd_per_unit` less
`delegate_cost`) and in the plan's share; it is shortened from its end until it fits (the questions left out are asked
by a later batch or escalate on the limit as today). The adapter's budget is `N × max_cost_usd_per_answer`
(`max_budget_usd` where `budget_cap`), so no batch may spend more than its questions could one by one. The call's cost
is one `budget.cost{usd, role: delegate, question: <first key>, questions: [keys], batch}`; each `delegate.result`
carries `batch`, `batch_size` and `cost_usd` = the call's cost divided by N (rounded to 6 decimals), or None when the
call reported none, so that `delegate_cost` counts a priced batch once and an unpriced one at N answers' cost, the
budget it was given. Credits are recorded once, and each result carries its share.

### D3 Independence and kinds (L4-DLG-002, L4-DLG-019)

One selection serves the batch: its questions have the same askers (D1), so `select_delegate` with the first key's
askers and the kinds constraint of `verdict` is the selection each question would get alone; no
usable profile is `_unavailable` for each question (deferred or escalated as today). The served model is checked
against the askers (`_served_veto`, the first key's); since the askers are the batch's, a veto escalates every question
of the batch `discarded` with today's text.

### D4 The batch prompt (L4-DLG-004)

`build_batch_prompt(views, materials, shared, budget_tokens, redact)`: `BATCH_SYSTEM` is `SYSTEM` with the question
rule and the final line made plural (`results` holds one result per question below, in any order, each with its
`question` id; every rule applies to each result on its own). The user text holds once the unit's specification (its
section keys from every question's title and context), the conventions, the earlier answers of the unit (none of the
batch's questions) and the latest failing gate; then for each question `# Question Q-NNN`, its question block, the
reason its previous reply was discarded, and its verdict target, judge reason and verification lines, each piece capped
as today. It ends `Decide questions Q-…, Q-… now.` The digest and the redaction are as for `delegate@7`; the version is
`delegate-batch@1`. `l4/delegate-batch@1` is `{"results": [l4/delegate-result@1]}` with `minItems` 1 and `maxItems`
the batch size, `additionalProperties` false. `max_turns` is `MAX_TURNS + 20 × (N − 1)`, at most 140; the timeout is
`delegate.timeout`.

The prompt is bounded as a whole too: when the rendered user text of a batch is longer than `BATCH_MAX_CHARS`
(160,000 characters, about 40,000 tokens), the batch is shortened from its end and built again, down to two questions;
a batch of one is `delegate@7`. The per-piece caps alone would allow about 108,000 characters of verdict material for
six questions plus the documents' share.

### D5 The reply (L4-DLG-005)

A call that ends `limit` moves the whole batch to the next profile, as `_ask` does. A reply that is not a valid batch
document (`timeout`, `error`, a schema break, `model_mismatch`) gives each question today's outcome for that status
(a deferral or, with its attempts used, an escalation; `model_mismatch` escalates each `discarded`). For a valid
document, each question takes its result by `question` id and goes through `check_reply` with its own inputs, then
`_answer`, `_escalate` or the retryable deferral, as `_ask` does. A question with no result, or with two, is
`delegate.result{status: deferred, reason: "the batch reply had no result for Q-NNN" | "… two results for Q-NNN"}` when
an attempt is left under `max_attempts_per_question`, else escalated with that reason; a call was made, so it counts.
A result whose `question` is not in the batch is ignored and logged. Answers are written and committed one by one, as
today.

### D6 Records

One `delegate.asked` per question of the batch, each with the batch's `prompt_sha256`, `batch` (the first key and the
size, `<key>+<N>`) and `batch_size`, so every reader that looks at `question` stays right. `delegate.pass` gains
`calls`, the number of adapter calls the pass made.

### D7 Configuration

`delegate.batch_size: int`, default 6, at least 1 and at most 20 (the reply limit of 20 `checked` entries is per
result, not per batch). 1 asks one question per call. The doctor's DLG settings line names it. Read from the base
branch with the rest of the section (L4-DLG-001).

## Limits

- A batch's timeout or adapter error costs each of its questions an attempt: with `max_attempts_per_question` 2, two
  failed batch calls escalate up to six questions. A single call would have cost the same per question, but the failures
  come together.
- The answers of one call are not independent of each other: one misreading can repeat across them. Each result is
  still checked on its own citations.
- A harness, technical, product or ambiguous question is still one call.
