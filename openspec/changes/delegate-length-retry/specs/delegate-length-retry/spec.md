## ADDED Requirements

### Requirement: L4-DLG-029 An escalation over a length limit keeps its reason cut, and any other reply is asked again
The length rules of L4-DLG-005 (a `reason` over 1000 characters, more than 20 `checked` entries, an entry's `ref` over
300 characters or its `quote` or `claim` over 600) SHALL be checked together, after the decision fits the kind and
before any other rule of the entries.
A reply whose decision is `escalate` and that breaks length rules SHALL be kept at once as an escalation cut to the
limits, with no retry, also when an attempt is left:
- its reason is redacted as written, its whitespace folded and the result redacted again (the one order of every
  record of a delegate's reason, so that a configured value with a line break is redacted too), and only then
  measured: over 1000 characters it keeps its first 1000 and ends with ` … [cut at 1000 of <n> characters]`, `<n>` the
  length of that redacted, folded reason, a cut that would fall inside a `[REDACTED:…]` placeholder being made just
  before it; within 1000 characters it is kept whole, redacted and folded;
- its entries whose `ref` is over 300 characters, and then those after the 20th, are dropped; the kept ones record
  their redacted `ref` only, so a quote's or a claim's length does not matter;
- it is recorded `delegate.result{status: escalated, decision: escalate, cut}`, where `cut` names `reason` and/or
  `checked` (none when nothing was cut).

An `escalate` that breaks a rule checked before the length rules (the schema, the question id, a decision that fits
no kind) SHALL keep today's path, discarded and never cut.
For any other decision the refusal SHALL name every length rule the reply breaks, in that order, one clause for each,
joined by `; `: `the reason has <n> characters: the limit is 1000`, `the reply has <n> checked entries: the limit is 20`,
and for each of the fields `ref`, `quote` and `claim` that is over its limit `a checked <ref|quote|claim> has <n>
characters: the limit is <m>` (there `<n>` is the longest value of that field among the entries). A reply that breaks
one rule SHALL be refused with today's reason word for word. The refusal SHALL be retryable like a reference that does
not resolve: with an attempt left it is recorded `delegate.result{status: deferred, discarded}` and asked again, and
with no attempt left the reply SHALL be discarded as before (`the reply was discarded: <reason>`). The next prompt
SHALL follow the reason with one instruction per rule in place of the sentence about references: `Shorten the reason
to at most 1000 characters; it had <n>.`, `Keep at most 20 checked entries; it had <n>.`, `Shorten each checked
<field> to at most <m> characters; the longest had <n>.` (for a quote: `…, still copied word for word; …`). The system
text and `delegate@7` SHALL NOT change.
A length retry SHALL take one of the question's attempts (`delegate.max_attempts_per_question`), as a deferral for a
reference, a short quote, a timeout or an error does. No rule SHALL add an attempt or keep its own count, so with the
default 2 a question's raise is called at most twice, whatever discarded its first reply: a reference retry and a
length retry never both happen. With a larger budget each retry takes one attempt, as two reference retries do.
The `Escalated by:` line and the `delegate.result` reason of a delegate's `escalate` decision, cut or not, SHALL carry
its reason whole (as cut above), redacted, in place of L4-DLG-008's 300 characters. Every other escalation reason,
the PR's sticky section and `l4 status` (its text and its `--json` `reason`) SHALL keep 300. `l4/delegate-result@1` and the results of `l4/delegate-batch@1` SHALL carry no
`maxLength` or `maxItems` for `reason`, `checked`, `ref`, `quote` or `claim`: a schema break is not retryable, fails a
whole batch and loses the reply.

#### Scenario: SCN-DLG-144 (+) a reason over the limit is asked again, and the retry names the limit
- **WHEN** `delegate.max_attempts_per_question` is 2, a first reply `answer` to Q-001 has a `reason` of 1028
  characters, and 10 minutes later the pass asks again
- **THEN** the first pass records `delegate.result{status: deferred, discarded: "the reason has 1028 characters: the
  limit is 1000"}` and writes no `Escalated by:` line
- **AND** the second prompt's `# Your previous reply` block says `The previous reply to this question was discarded:
  the reason has 1028 characters: the limit is 1000. Shorten the reason to at most 1000 characters; it had 1028.` and
  not the sentence about references, and a second reply within the limits is answered as any reply

#### Scenario: SCN-DLG-145 (+) every length rule a reply breaks is named at once
- **WHEN** a reply `answer` has 23 `checked` entries, one quote of 812 characters and one claim of 640
- **THEN** it is refused, retryable, with `the reply has 23 checked entries: the limit is 20; a checked quote has 812
  characters: the limit is 600; a checked claim has 640 characters: the limit is 600`
- **AND** the retry's prompt says `Keep at most 20 checked entries; it had 23. Shorten each checked quote to at most
  600 characters, still copied word for word; the longest had 812. Shorten each checked claim to at most 600
  characters; the longest had 640.`, and a reply with one `ref` of 301 characters is refused with `a checked ref has
  301 characters: the limit is 300`, as before

#### Scenario: SCN-DLG-146 (+) an escalation over the limit with an attempt left is cut at once, not asked again
- **WHEN** `max_attempts_per_question` is 2 and the first reply to Q-001 is `escalate` with a `reason` of 1028
  characters
- **THEN** Q-001 is escalated on that call, with one `delegate.asked` and no deferral: `delegate.result{status:
  escalated, decision: escalate, cut: [reason]}` has as `reason` the reply's reason redacted and folded (redact, then cut), cut
  to its first 1000 characters, then ` … [cut at 1000 of 1028 characters]`, and the `Escalated by:` line holds that reason whole, mark included, in place
  of `the reply was discarded: …`
- **AND** a second reply `escalate` over the limit after a reference deferral is cut the same way, and a kept
  `escalate` whose reason has 900 characters is written whole, while the sticky section and `l4 status` show its first
  300 characters

#### Scenario: SCN-DLG-147 (−) any other decision still over a limit on its last attempt is discarded
- **WHEN** on the last attempt a reply `answer`, `accept`, `reject` or `retry` has a reason of 1028 characters, or 21
  entries
- **THEN** the pass records `delegate.result{status: discarded, decision}`, cuts and writes nothing, and the `Escalated
  by:` line says `the reply was discarded: the reason has 1028 characters: the limit is 1000` (or names the entries)

#### Scenario: SCN-DLG-148 (+) an escalation's entries over the limits are dropped at once
- **WHEN** a reply `escalate`, with an attempt left, has a reason within the limit and 23 `checked` entries, the second
  with a `ref` of 340 characters and the fifth with a quote and a claim of 900
- **THEN** it is escalated on that call with `cut: [checked]` and the redacted refs of the first 20 entries that remain
  once the second is dropped, the fifth among them; an `escalate` whose only overrun is a quote or a claim is escalated
  with nothing cut and no `cut`

#### Scenario: SCN-DLG-149 (−) a length retry takes the question's attempt and adds none
- **WHEN** `max_attempts_per_question` is 2, the first reply to Q-001 was deferred for `checked spec:proposal.md does
  not resolve` (or the first call timed out), and the second reply is an `answer` whose reason has 1028 characters
- **THEN** it is not asked again: the second pass records `delegate.result{status: discarded}` and escalates, with two
  `delegate.asked` in all
- **AND** with `max_attempts_per_question: 3` both discards are deferred and a third call is made

#### Scenario: SCN-DLG-150 (−) the result schemas carry no length limit
- **WHEN** a reply's `reason` has 1028 characters
- **THEN** neither `delegate_schema()` nor `batch_schema(n)` has a `maxLength` or a `maxItems` for `reason`,
  `checked`, `ref`, `quote` or `claim` (`results` keeps `maxItems: n`), the reply passes `schemacheck.validate` against
  both, and `check_reply` judges it by the length rules (an `answer` refused, retryable; an `escalate` cut), never as
  `not an l4/delegate-result@1 document`

#### Scenario: SCN-DLG-151 (−) a rule before the length rules is not asked again and not cut
- **WHEN** a reply `answer` to a verdict question, or a reply `escalate` for another question id, has a reason of 1028
  characters
- **THEN** it is discarded with `the decision answer does not fit a verdict question` (or `the reply answers Q-002, not
  Q-001`), not retryable and not cut, and the question is escalated at once with `the reply was discarded: …`

#### Scenario: SCN-DLG-152 (+) a reason is redacted whole before it is cut
- **WHEN** a reply `escalate` has a reason of 1100 characters that holds a token the redactor knows from character 990
  to 1030, or a reason of 900 characters that holds a configured value with a line break
- **THEN** the reason is redacted, folded and redacted again, and only then measured: the cut reason holds no prefix of
  the token, is cut just before the placeholder that would have been cut in two, and ends with the mark, whose `<n>` is
  the length of the redacted, folded reason; the 900-character reason is kept whole with the placeholder in place of
  the value
- **AND** no part of either secret is in `delegate.result`, `questions.md` or the ledger

#### Scenario: SCN-DLG-153 (+) in a batch, a result over a limit is judged on its own
- **WHEN** a batch of three verdict questions gets a reply with one result for each, the second an `accept` whose
  reason has 1028 characters and the third an `escalate` whose reason has 1028 characters
- **THEN** the first is answered, the second is deferred with `discarded: "the reason has 1028 characters: the limit
  is 1000"`, and the third is escalated with its reason cut; the batch is not failed, and the next ask of the second,
  in a batch or alone, carries the instruction in its previous-reply block
