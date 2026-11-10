## Why

In a consumer run the delegate escalated a question with a `reason` of 1028 characters (a $1.93 call). `check_reply`
refuses a reason over `MAX_REASON_CHARS` (1000), and that refusal is not retryable, so the reply was discarded and the
question went to a person at once. The person read only `the reply was discarded: the reason has 1028 characters: the
limit is 1000`. The delegate's own reason, which had found the real cause (a spec line that contradicted the code), was
in no file a person reads.

The other length rules behave the same way: more than 20 `checked` entries, a `ref` over 300 characters, a `quote` or a
`claim` over 600. Only a reference that does not resolve and a quote under 12 characters are asked again (L4-DLG-005).
A model overruns a length limit more easily than it misquotes a file: it counts characters poorly, and the prompt states
only the reason's limit.

A reason within the limit does not reach the person whole either: `_escalate` cuts every escalation reason to 300
characters (`ESCALATED_CHARS`, L4-DLG-008), in `questions.md` and in the ledger, with no mark. So keeping a long reason
is not enough: the line a person reads must carry it.

## What Changes

- The length rules are one class, checked together right after the decision fits the kind. When a reply breaks one,
  the refusal names every rule it breaks, joined by `; `, each in today's words; a reply that breaks one rule has
  today's reason word for word.
- An `escalate` reply that breaks only length rules is cut to the limits at once, with no retry, even when an attempt
  is left. Its reason is redacted whole, then cut after 1000 characters and ended with ` … [cut at 1000 of <n>
  characters]`. Its entries whose `ref` is over 300 characters, and then those after the 20th, are dropped. It is
  recorded `delegate.result{status: escalated, decision: escalate, cut}`. The outcome is an escalation either way, and
  a retry would cost a paid call and delay the person (design D4).
- For any other decision (`answer`, `accept`, `reject`, `retry`), a length refusal is retryable like a reference that
  does not resolve. The retry takes one of the question's attempts (`delegate.max_attempts_per_question`), as every
  other deferral does, and no rule adds an attempt: with the default 2 a question is called at most twice, whatever
  discarded its first reply. With no attempt left the reply is discarded as today.
- The retry's prompt says how to fix each overrun, for example `Shorten the reason to at most 1000 characters; it had
  1028.`, in place of the sentence about references. The system text and its version `delegate@7` do not change.
- The `Escalated by:` line and the `delegate.result` reason of a delegate's own `escalate` decision carry its reason
  whole: redacted, bounded by the 1000-character rule, plus the mark when it was cut. They are no longer cut at 300.
  The harness's own escalation reasons, the PR's sticky section and `l4 status` keep 300.
- The result schemas get no `maxLength` or `maxItems` (design D6). With them, an overrun would be a schema break, which
  is not retryable, fails a whole batch, and loses the reply.

## Impact

- Code: `l4.delegate.reply` (`_length_problems`, `_cut_escalation`, `CUT_MARK`, `Kept.cut`, the order of the checks),
  `l4.delegate.run` (the kept-escalate branch of `_settle` passes `whole` and `cut` to `_escalate`), `l4.delegate.prompt`
  (`_previous_part` writes the length instructions).
- Spec: L4-DLG-029 (new). L4-DLG-005 (its sentence on the limits and its retry exception) and L4-DLG-008 (the
  300-character cap) are amended, and so is the `delegate.result` record of §12.1 (`cut`). Adds SCN-DLG-144..153 and
  change-table row 122.
- Behaviour: an escalation over a length limit now reaches the person at once, with its reason. Before, it was discarded
  and the person read only the limit. An answer, accept, reject or retry over a length limit costs one more call where
  it used to cost a person's time, and is discarded as before when no attempt is left. The question's attempts are not
  raised. An `escalate` whose quote or claim is over 600 characters is now kept (an escalation records neither).
- Not changed: the limits themselves; the system text, `delegate@7` and the template lock; the result schemas; the
  reference rules of L4-DLG-005; `_recorded`; the sticky section and `l4 status` (300 characters).
