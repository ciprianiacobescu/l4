## 1. The checks, the retry and the cut (D1 to D6)

- [x] 1.1 Write the tests first, in a new file `tests/unit/delegate/test_reply_length_retry.py` (import `check`,
  `cite`, `reply` and `STORE`/`FILES` as needed from `.test_reply`, as `test_reply_quote_tolerance.py` does), at the
  `check_reply` level:
  - SCN-DLG-144: an `answer` whose reason has 1001 characters gives a `Discarded` with `retryable` true and the reason
    `the reason has 1001 characters: the limit is 1000`; 1000 characters is kept.
  - SCN-DLG-145: 23 entries, one quote of 812 and one claim of 640 in an `answer` give one reason with the three
    clauses in the order count, quote, claim, joined by `; `, retryable; two quotes of 700 and 812 name 812 (the
    longest); one `ref` of 301 gives `a checked ref has 301 characters: the limit is 300` word for word.
  - SCN-DLG-146 and SCN-DLG-148 at this level: an `escalate` over a length limit gives a `Kept` (never a `Discarded`)
    with decision `escalate`. Its reason is the redacted reason's first 1000 characters plus ` … [cut at 1000 of <n>
    characters]` and `cut == ("reason",)`. With 23 entries, the second's `ref` of 340 and the fifth's quote and claim
    of 900, its `checked` is `({"ref": …}, …)` for the first 20 entries that remain once the second is dropped, and
    `cut == ("checked",)`; with both, `("reason", "checked")`. An `escalate` whose only overrun is a quote or a claim
    of 900 is a `Kept` with `cut == ()` and every entry's ref; one within every limit is today's `Kept` with `cut ==
    ()`.
  - SCN-DLG-147: `answer`, `accept` (verdict), `reject` (verdict) and `retry` (harness) over a limit give a
    retryable `Discarded` that keeps `decision`.
  - SCN-DLG-151: a verdict question with an `answer` whose reason has 1028 characters is refused `the decision answer
    does not fit a verdict question`, not retryable; an `escalate` for Q-002 to Q-001 with a long reason is refused
    `the reply answers Q-002, not Q-001`, not retryable, a `Discarded` (not cut).
  - SCN-DLG-152: a `Redactor` that knows a 40-character token placed at characters 990 to 1030 of a 1100-character
    escalate reason: the cut reason holds the placeholder and no prefix of the token of 4 characters or more, and ends
    with the mark.
  - SCN-DLG-150: `delegate_schema()` and `batch_schema(5)` have no `maxLength` and no `maxItems` under `reason`,
    `checked`, `checked.items.properties.{ref,quote,claim}` (for the batch, under `results.items`); `batch_schema(5)
    ["properties"]["results"]["maxItems"] == 5`; a reply with a reason of 1028 characters has `validate(reply,
    delegate_schema()) == []`, and `check_reply` refuses it as a length rule, retryable, for an `answer` and cuts it
    for an `escalate`.

  Update `tests/unit/delegate/test_reply.py`: in `test_too_many_checked_entries_discard_the_reply` and
  `test_a_long_checked_field_discards_the_reply` an `answer` still gets a `Discarded` naming the rule, now `retryable`;
  an `escalate` now gets a `Kept` (21 entries: 20 refs, `cut == ("checked",)`; a `ref` of 301: that entry dropped,
  `cut == ("checked",)`; a quote or claim of 601: kept whole, `cut == ()`). Rename the tests to say so.

  Then change `src/l4/delegate/reply.py` (D1, D4): add `CUT_MARK = " … [cut at {limit} of {n} characters]"`,
  `_length_problems(reason, checked) -> list[str]` (the clauses of D1, the longest value of each field) and
  `_cut_escalation(reason, checked, redactor) -> Kept` (redact the reason whole, cut after `MAX_REASON_CHARS` with the
  mark; drop the entries whose `ref` is over `MAX_CHECKED_CHARS["ref"]`, then those after `MAX_CHECKED`; keep `{"ref":
  redacted}`; set `cut`). Add `Kept.cut: tuple[str, ...] = ()`. In `_check_reply`, move the reason check after the
  decision fit and replace the reason, count and field checks with one `_length_problems` call; then, for `escalate`,
  return `_cut_escalation(...)` (it also gives today's `Kept` when nothing is over), and for any other decision with
  problems, `refuse("; ".join(problems), retryable=True)`. Leave every other rule, its text and its order unchanged,
  and leave `_recorded` as it is. Update the docstrings of the module and `Kept` (L4-DLG-029, delegate-length-retry;
  D6: why the schemas carry no length limit).

- [x] 1.2 `src/l4/delegate/run.py` (D2, D4, D5):
  - `_settle`: no new branch. The deferral branch (`retryable and attempts_used(events, key) + 1 <
    max_attempts_per_question`) is unchanged: there is no new counter, and a cut escalation is a `Kept`.
  - `_escalate`: add `whole: bool = False` (no cut to `ESCALATED_CHARS`, still redacted and whitespace folded) and
    `cut: Sequence[str] = ()` (recorded as `cut` on the result when not empty). The kept-escalate branch of `_settle`
    passes `whole=True` and `cut=kept.cut`; no other caller changes.

  Tests first, in `tests/unit/delegate/test_pass.py` (the `delegate_run`, `fake_clock` and `build_prompt` spy patterns
  of `test_a_reference_discard_is_asked_again_once` and `test_a_short_quote_is_named_to_the_retry`):
  - SCN-DLG-144: a first `answer` with a reason of 1028 characters is deferred with `discarded == "the reason has 1028
    characters: the limit is 1000"` and no `Escalated by:` line; the second ask's `material.previous` is that text, and a
    second reply within the limits is answered.
  - SCN-DLG-146: with the default `max_attempts_per_question` (2), one `escalate` reply with a reason of 1028
    characters gives exactly one `delegate.asked` and one result, `escalated`, with `decision: escalate`, `cut:
    ["reason"]` and the reason that ends `… [cut at 1000 of 1028 characters]`, and no `deferred` result; the pushed
    `questions.md` holds `- **Escalated by:** the delegate (delegate-model-1 via fake): <that reason>` whole and not
    `the reply was discarded`. A reference discard (deferred) followed by such an `escalate` gives `[deferred,
    escalated]` with the same cut. An `escalate` whose reason has 900 characters is written whole (the line holds all
    900) and its result has no `cut`.
  - SCN-DLG-147: two `answer` replies over the limit with `max_attempts_per_question: 2` give `[deferred, discarded]`,
    `decision: answer`, and the line `the reply was discarded: the reason has 1028 characters: the limit is 1000`.
  - SCN-DLG-148 through the pass: one `escalate` with the entries of 1.1 gives one `escalated` result whose `checked`
    holds 20 refs and `cut: ["checked"]`.
  - SCN-DLG-149: a reference discard, then an `answer` over the limit: `[deferred, discarded]`, two `delegate.asked`; a
    timeout (`fake` adapter outcome as in `test_a_timeout_defers_then_escalates_at_the_limit`), then an `answer` over
    the limit: `[deferred, discarded]`; with `max_attempts_per_question: 3` a reference discard and a length discard
    are both deferred and a third call is asked.
  In `tests/unit/delegate/test_batch.py`, SCN-DLG-153: a batch of three whose second result is an `accept` with a
  reason of 1028 characters and whose third is an `escalate` with a reason of 1028 characters: result 1 `answered`,
  result 2 `deferred` with that `discarded`, result 3 `escalated` with `cut: ["reason"]`, and no failed-batch deferral
  (no `reason: error`); the next ask's `material.previous` for Q-002 is that text (the batch heading `# Your previous
  reply to Q-002` is a prompt test of 1.3).

- [x] 1.3 `src/l4/delegate/prompt.py` (D3): add `_LENGTH_CLAUSES` (the five clause forms of D1) and
  `_length_instructions(told) -> str | None` (the instructions of D3 when every `; `-separated clause of `told` is a
  length clause, else None). `_previous_part` writes them in place of `Write each reference in the form the rules give;
  the quote is copied word for word.` when they exist. `SYSTEM`, `PROMPT_VERSION`, `BATCH_SYSTEM` and the schemas do not
  change. Tests first, in `tests/unit/delegate/test_prompt.py`:
  - SCN-DLG-144 and SCN-DLG-145: the `previous` block of `build_prompt` and `build_batch_prompt` for each clause alone
    and for the three of SCN-DLG-145 together, word for word;
  - a round trip: each length refusal that `check_reply` gives (reason, count, `ref`, `quote`, `claim`, and a mix)
    becomes, through `Material(previous=…)`, a block with no sentence about references;
  - `test_a_previous_discard_is_shown_after_the_question` still holds for a reference reason, and a reason that mixes
    a length clause with another text keeps the sentence about references;
  - `tests/unit/test_template_lock.py` passes with the lock as it is (no `--write`).

## 2. Docs and checks

- [x] 2.1 The spec commit has docs/SPEC.md (L4-DLG-029 in §9.1; the amended sentences of L4-DLG-005 and L4-DLG-008;
  `cut` on `delegate.result` in §12.1; SCN-DLG-144..153; row 122), the CHANGELOG bullet, and the scenario ranges of
  `tests/unit/docs/test_delegate_docs.py` and `tests/unit/docs/test_delegate_0422_docs.py` (`range(116, 154)`). Check
  each against the code as built (the clause and instruction texts, the mark, the record's field names) and correct the
  text where the code had to differ; say so in the result.
- [x] 2.2 `docs/runbook.md`, the common reasons of an escalated question (the paragraph that names `checked <ref>: the
  quote of <ref> is shorter than 12 characters`): add that a reply over a length limit (`the reason has <n>
  characters: the limit is 1000`, the entry limits) is asked again within `delegate.max_attempts_per_question`, unless
  it is an escalation, and that a delegate's escalation over the limit is escalated at once with its reason ending `…
  [cut at 1000 of <n> characters]` (its first 1000 characters).
- [x] 2.3 Run, once with pytest (never in a loop, never two runs at once, no `while pgrep` wait, never the whole suite),
  in one invocation: `tests/unit/delegate/test_reply_length_retry.py`, `tests/unit/delegate/test_reply.py`,
  `tests/unit/delegate/test_reply_0421.py`, `tests/unit/delegate/test_reply_quote_tolerance.py`,
  `tests/unit/delegate/test_pass.py`, `tests/unit/delegate/test_batch.py`, `tests/unit/delegate/test_prompt.py`,
  `tests/unit/delegate/test_review_fixes.py`, `tests/unit/test_template_lock.py` and `tests/unit/docs` (the whole of
  `tests/unit/delegate` takes more than ten minutes). Then `ruff check` and `ruff format --check` on the changed files, `python scripts/check_spec.py
  docs/SPEC.md`, and `openspec validate delegate-length-retry --strict`. Report the counts.
