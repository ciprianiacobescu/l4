## Context

`_check_reply` (`src/l4/delegate/reply.py:318-467`) applies its rules in this order and returns at the first one that
breaks:

1. the schema: `validate(reply, delegate_schema())` (`reply.py:348`). Any problem gives `not an l4/delegate-result@1
   document: …`;
2. the question id (`reply.py:360`);
3. the reason: `len(reason) > MAX_REASON_CHARS` (1000) gives `the reason has <n> characters: the limit is 1000`
   (`reply.py:362-363`);
4. the decision fits the kind (`FIT`, `reply.py:364-366`);
5. the entries: more than `MAX_CHECKED` (20) gives `the reply has <n> checked entries: the limit is 20`, and the first
   entry whose `ref`, `quote` or `claim` is over `MAX_CHECKED_CHARS` (300, 600, 600) gives `a checked <key> has <n>
   characters: the limit is <m>` (`reply.py:367-372`);
6. an `escalate` is kept here, with only the redacted refs of its entries (`reply.py:373-374`);
7. the rules of an acting decision: no harness-written ref, the 12-character quote, the resolution of each entry, the
   text checks, the verdict rules, the unfreeze rules and `check_question`.

Only the 12-character quote and an entry that does not resolve are `retryable` (`reply.py:386-393`). `_Pass._settle`
(`src/l4/delegate/run.py:662-719`) defers a retryable `Discarded` when `attempts_used(events, key) + 1 <
max_attempts_per_question` (`run.py:700`). It records `delegate.result{status: deferred, discarded, checked}`, and the
next prompt shows `discarded` (`limits.last_discard`, `prompt._previous_part`). Otherwise it escalates with `the reply
was discarded: <reason>`. A kept `escalate` goes to `_escalate` with the delegate's reason.

`_escalate` (`run.py:1046-1067`) redacts the reason, folds its whitespace and cuts it to `ESCALATED_CHARS` (300,
`run.py:117`). That text is both the `delegate.result` reason and the `Escalated by:` line of `questions.md`
(L4-DLG-008, "at most 300 characters"). The PR's sticky section (`notify.needs_person_section`, `sticky_line(reason, 300)`) and
`l4 status --unit` (`lines.REASON_WIDTH`, 300) read that record.

The prompt (`prompt.py:101`) says "`reason` says in at most 1000 characters why you decided so". It states no limit for
the entries. The result schemas `delegate-result.schema.json` and `delegate-batch.schema.json` carry no length limit
(`reason` has `minLength: 1` only).

## Goals / Non-Goals

**Goals:** a reply over a length limit is asked again, and the retry says which limit and by how much. An escalation
that is still over a limit on its last attempt reaches the person with the delegate's reason, cut and marked. No
question gets more attempts than today. A decision that acts on the unit is never kept on a cut text.

**Non-Goals:** other limits; the system text (`delegate@7`, the template lock); stating the entry limits in the
prompt; a repair of an acting decision; the sticky section's and `l4 status`'s 300 characters; the reference rules of
L4-DLG-005; schema-level limits (D6).

## Decisions

### D1. The length rules are one class, checked together, after the decision fits the kind

The new order is: the schema, the question id, the decision fits the kind, then the length class, then the `escalate`
keep and the rules of step 7 as before. The length class is the reason, the number of entries, and the `ref`, `quote`
and `claim` of each entry, all checked at once by `_length_problems(reason, checked) -> list[str]`. It gives one clause
per broken rule, in this fixed order, each in today's words:

- `the reason has <n> characters: the limit is 1000`;
- `the reply has <n> checked entries: the limit is 20`;
- `a checked ref has <n> characters: the limit is 300`, then the same for `quote` and `claim` (600 each). `<n>` is the
  longest value of that field among the entries; today the code names the first entry that is over.

The refusal's reason is the clauses joined by `; `, so a reply that breaks one rule has today's reason word for word.
Naming every broken rule lets one retry fix them all. Today a second overrun would only show up on the retry's reply,
with no attempt left.

The reason check moves after the decision fit. A decision that does not fit the kind is not retryable, and it now wins
over a length overrun, so no retry is spent on a reply that its decision discards anyway. The same holds for a wrong
question id, which already came first. The rules of step 7 run only on a reply within the limits, as today: the limits
bound the resolution work, and a reply that breaks a length rule and a later rule is asked again for the length, and
the later rule decides the next reply.

### D2. A length refusal is retryable and takes the question's attempt; it adds none

A length refusal sets `retryable` and takes the existing branch of `_settle` (`run.py:700`): `kept.retryable and
attempts_used(events, key) + 1 < max_attempts_per_question`. There is no counter per reason and no new allowance.
Checked against the code:

- `events` is the snapshot that `_ask` (`run.py:609`) or `_ask_batch` (`run.py:476`) took before the call.
  `attempts_used` (`limits.py:79-83`) counts the question's `delegate.result` records of its current raise, whatever
  they were: a deferral for a reference or a short quote, a timeout, an error, a batch with no result for the question,
  a call that failed. Only a soft-deadline deferral is left out (L4-DLG-013). `limit_reached` (`limits.py:152-154`) refuses a call
  once `attempts_used >= max_attempts_per_question`.
- With the default 2: the first call's reply is discarded for any retryable rule and deferred, so `attempts_used` is 1.
  On the second call `1 + 1 < 2` is false, so whatever discards that reply, the question ends there: escalated,
  discarded, or cut (D4). A reference retry and a length retry therefore never both happen. A timeout on the first call
  leaves no retry for a length overrun on the second, and the reverse holds too.
- With `max_attempts_per_question: N` a question can be called N times, and each retryable discard takes one of the
  N - 1 deferrals, as two reference discards in a row do today. The "asked again once" of L4-DLG-005 is the default
  value of this budget, not a separate rule. L4-DLG-029 says so explicitly.

The deferral is recorded as for a reference: `delegate.result{status: deferred, discarded: <the joined clauses>,
checked}`. `checked` is `_recorded`, which is empty when the entries break a limit, as today. A batch result is checked
on its own (`_settle` per result, L4-DLG-028), so one result over a limit is deferred and the others are answered. A
length deferral is not a failed batch (`batch_failed` reads only `timeout` and `error`), so the question may join a
later batch.

### D3. The retry says which limit and by how much

`_previous_part` (`prompt.py:242-248`) writes today `The previous reply to this question was discarded: <told>. Write
each reference in the form the rules give; the quote is copied word for word.` For a length reason the second sentence
says nothing useful. When every `; `-separated clause of `told` is a length clause (D1), that sentence is replaced by
one instruction per clause, in the clauses' order, joined by spaces:

| clause | instruction |
|---|---|
| `the reason has <n> characters: the limit is <m>` | `Shorten the reason to at most <m> characters; it had <n>.` |
| `the reply has <n> checked entries: the limit is <m>` | `Keep at most <m> checked entries; it had <n>.` |
| `a checked ref has <n> characters: the limit is <m>` | `Shorten each checked ref to at most <m> characters; the longest had <n>.` |
| `a checked quote has <n> characters: the limit is <m>` | `Shorten each checked quote to at most <m> characters, still copied word for word; the longest had <n>.` |
| `a checked claim has <n> characters: the limit is <m>` | `Shorten each checked claim to at most <m> characters; the longest had <n>.` |

Any other `told` keeps today's sentence. The parser (`_LENGTH_CLAUSES`, `_length_instructions(told) -> str | None`)
lives in `prompt.py`: `reply.py` imports `delegate_schema` from `prompt.py`, so `prompt.py` cannot import `reply.py`. A
test feeds every length refusal that `check_reply` produces through `build_prompt` and checks the instructions. The
clauses are fixed harness text with no repository content, so the redaction of `discarded` never changes them.
Parsing the recorded string keeps the ledger record, `last_discard` and `Material.previous` unchanged.

*Alternative rejected:* record a separate `hint` on the deferral. That is one more ledger field and one more `Material`
field for text that the reason already determines.

The system text does not change, so `delegate@7` and the template lock stay as they are: the lock pins `SYSTEM` only
(`templatelock.py:36`). The batch prompt uses the same `_previous_part` under `# Your previous reply to Q-NNN`.

### D4. With no attempt left, an escalation is cut to the limits; every other decision is discarded

`check_reply` stays pure: it does not know the attempts. For an `escalate` whose only broken rules are length rules,
the `Discarded` carries `escalation: Kept | None`, the escalation cut to the limits. `_settle` uses it when it does
not defer, and goes on as for a kept `escalate`. After the length class nothing else is checked for an `escalate`
(step 6), so `escalation` is set for every `escalate` that a length rule refused. Steps 1, 2 and 4 come first and are
never cut.

`_cut_escalation(reason, checked, redactor) -> Kept`:

- **The reason.** It is redacted whole first (`redactor.redact_text(reason)`): a cut inside a secret would leave a
  prefix the redactor cannot see, the reason L4-IMP-064 and L4-DLG-004 redact before any cut. When the redacted
  reason is over 1000 characters, it keeps its first 1000, followed by `CUT_MARK = " … [cut at {limit} of {n}
  characters]"`, with `limit` 1000 and `n` the redacted reason's length. The mark says that the text is cut and how much
  is missing; it is the harness's, in brackets, at the end.
- **The entries.** An entry whose `ref` is over 300 characters is dropped, then entries after the 20th are dropped,
  in reply order. Each kept entry is `{"ref": <redacted ref>}`, as an escalation records today. A ref is a locator
  (`path:line`, `spec:<file>#<anchor>`, `test:<id>`): one cut in the middle locates nothing, and one over 300 characters
  is no locator a person can follow, so it is dropped, not cut. The first 20 entries say what the delegate looked at,
  and the limit bounds the record.
- **Quote and claim.** An escalation records neither, so their length does not matter at the cut. Only the retry asked
  for them to be shortened.
- **`Kept.cut`.** It names `reason` when the mark was added and `checked` when an entry was dropped. `_escalate`
  records it on the result: `delegate.result{status: escalated, decision: escalate, reason, checked, cut}`.

A reply with any other decision (`answer`, `accept`, `reject`, `retry`) still over a limit on its last attempt is
discarded as today: `delegate.result{status: discarded, decision, reason}`, the `Escalated by:` line `the reply was
discarded: <reason>`, `checked` as `_recorded` gives it. These decisions act on the unit: they write an answer, set a
verdict, may unfreeze a file, and in a plan may lead to a merge. Their reason and claims are the record of why, and
acting on a cut reason or on dropped evidence is a different risk from showing a person a cut text. An escalation acts
on nothing: the person decides, and reads a text that says it is cut.

### D5. The person reads the cut reason: the line carries a delegate's escalate reason whole

`_escalate` cuts every reason to 300 characters with no mark (`run.py:1053`). A reason cut at 1000 with a mark at its
end would be shown as its first 300 characters, and the mark would never be seen. A delegate's escalate reason of 301
to 1000 characters is already cut that way today. So `_escalate` takes `whole: bool = False`, and the kept-escalation
branch of `_settle` (an `escalate`, cut or not) passes `whole=True`. The reason is then redacted and its whitespace
folded, but it is not cut: `check_reply` already bounds it at 1000 characters, or 1000 and the mark. Every other
escalation keeps 300 characters: a discarded reply, a limit, a refused write, an unusable chain, a served-model veto.
Those texts are the harness's; for a discarded reply the text is the harness's reason, not the delegate's.

The `delegate.result` reason holds the same text as the line, as today. The sticky section and `l4 status` are summaries
that name the question and point to `questions.md`; they keep 300 characters. L4-DLG-008's cap is amended for a
delegate's own `escalate` reason.

### D6. No `maxLength` or `maxItems` in the result schemas

Adding the limits to `delegate-result.schema.json` (and to the result items of `delegate-batch.schema.json`) is not
safe. Each path below turns an overrun into a failure that is not retryable, and usually the reply is lost:

- **L4's own check.** [V] `schemacheck` enforces `maxLength` and `maxItems` (`schemacheck.py:63-73`). `check_reply`
  validates against `delegate_schema()` first (`reply.py:348`) and refuses any problem as `not an l4/delegate-result@1
  document: $.reason: longer than 1000`, which is not retryable. The overrun would never reach the length rule.
- **The structured-output wrapper.** [V] `AgentJudge.complete_structured` validates the adapter's reply against the
  schema it sent (`agent_judge.py:191-195`) and returns `schema_invalid`. `_settle` turns every status but `ok` into
  `Discarded("not an l4/delegate-result@1 document: <detail>")` (`run.py:694-696`), which is not retryable. `_Reply`
  does not keep the rejected reply (`run.py:147-157`; `StructuredResult.raw` is dropped in `_call`, `run.py:765`), so
  the delegate's reason would be lost entirely: worse than today.
- **Claude Code.** [V] The delegate runs `claude -p … --json-schema <schema>` in read-only mode
  (`claude_code.py:160-161`), and the adapter validates `structured_output` again (`_attach_structured`,
  `claude_code.py:303-308`: `structured output invalid` → `schema_invalid` above). [U] Whether the CLI enforces
  `maxLength` itself is not verified: spikes/01 notes that its enforcement of `pattern` and `enum` was never seen. [I]
  If it does, a model that repeats the overrun ends in the result subtype `error_max_structured_output_retries`
  (research/02:41). The adapter reads that as a failed run with status `error` (`claude_code.py:214, 228-247`), so
  `_ask` defers or escalates it as an adapter error (`delegate attempts used`), with no reason kept.
- **Codex.** [V] `strictify_schema` copies every keyword, `maxLength` included (`codex.py:68-95`), and spikes/03:139-141
  found that OpenAI strict mode accepts `pattern`, `maxLength`, `minItems` and `maxItems`. [U] Whether it enforces
  `maxLength` while decoding is not verified. [I] If it does, the decoder would cut the reason at 1000 with no mark; if
  a reply breaks it, `_attach_result` validates (`codex.py:347-353`) and the reply is `schema_invalid` as above.
- **Prompt-contract adapters** (opencode, kiro-cli, copilot-cli). [V] They get the schema in the prompt
  (`schema_suffix`), and their replies are validated by the wrapper above.
- **A batch.** [V] One result's overrun would make the whole `l4/delegate-batch@1` document invalid, and every question
  of the batch would get the outcome of a failed call: a deferral that takes an attempt, or an escalation
  (`run.py:536-551`). One long reason would cost N questions.

So the limits stay in `check_reply`, the one place where an overrun is retryable and can be cut. The prompt states the
reason's limit and the retry states every limit. A test asserts that neither schema has a `maxLength` or `maxItems` for
`reason`, `checked`, `ref`, `quote` or `claim`; the batch's `results` keeps its `maxItems: N` (`prompt.batch_schema`).
That guards against a well-meant "tightening" of the schema. A `description` naming the limit was considered and left
out: it would change the schema every adapter gets, for a hint the prompt already gives.

### D7. A new requirement, L4-DLG-029

L4-DLG-005 is one paragraph (SPEC §9.1) that already holds the reference forms, the resolution rules, the
harness-written rule, the 12-character minimum and the limits. This change adds a check order, a retry text, a cut, a
record field and an exception to L4-DLG-008's cap. A new requirement keeps L4-DLG-005 readable and gives
SCN-DLG-144..153 one home. L4-DLG-005's sentence on the limits points to it, and L4-DLG-008's cap names the exception.

## Risks / Trade-offs

- An `escalate` over a limit is asked again before it is cut. The retry costs a call (the consumer run's cost $1.93)
  and delays the escalation by the retry wait and a run, for an outcome that is an escalation either way. Cutting at
  once would save both, but it would lose the reason's tail without giving the delegate the chance to shorten it. The
  class keeps one rule for every decision.
- With the default budget, a retry spent on a length overrun leaves none for the next reply: a reply that fixes its
  length but cites a quote that does not resolve is discarded. The budget is the owner's
  (`max_attempts_per_question`).
- A cut reason may lose a conclusion written at its end. The mark says that it is cut and by how much, and the call's
  published agent log holds the delegate's reply [I].
- The `Escalated by:` line of a delegate's escalation can be about 1,050 characters (the model, the CLI, the reason
  and the mark). It is one line of `questions.md`, which a person reads to answer, and markdown renders it as a
  paragraph. The PR's sticky section and `l4 status` still show 300 characters of it, with no mark.
- A reply that breaks a length rule and a rule of step 7 is asked again for the length first. Its next reply is then
  discarded for the later rule, and with the default budget it is not asked again.
- The reason of a reply that broke both a decision fit and the reason length used to be the length; it is now the
  decision fit. Neither is retryable, and only the text differs.
