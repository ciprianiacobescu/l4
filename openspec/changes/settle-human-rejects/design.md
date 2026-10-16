# Settle human rejects: a feedback-only fix unit ends the reject it answers, and the way out is named

Status: design, 2026-10-16. Harness at 0.4.5. Markers: **[V]** verified in the code or in the recorded ledger,
**[I]** inferred, **[G]** a chosen form.

## 0. The answer in eight lines

1. A reject is in force until a fix unit consumes it (`fix.spawned.consumed`). A feedback-only fix unit consumes
   nothing today, so a human reject that no task could be derived from outlives the feedback that fixed it (1.1) [V].
2. Read time: a `reject` whose `human.verdict` is before a `fix.spawned{feedback_only: true}` is consumed (D1).
3. Write time: the same spawn lists the questions of the rejects the round listed as not converted (D2).
4. A hold raised again is asked as a new question, since the old question is consumed (D3).
5. `next_step` for `escalated` with `no_convertible_finding` names feedback first, then the retry (D4).
6. `--replace` replaces the answer of an answered verdict question and keeps the old text in a comment (D5, D6).
7. A replaced reject-to-accept answer clears the FAIL, because the latest `human.verdict` per target wins (D6).
8. The old ledger of the consumer repository needs no repair: D1 reads it right [I].

## 1. Current state

### 1.1 Why the reject stays [V]

- `_hold_finding` makes a rejected hold with a reason that has no `WHEN ... THEN ...` a `human` major finding.
- `_candidates` (`src/l4/verifier/fixunit.py`) skips a human finding with no criterion and no scenario
  ("the human decides") and never adds its question to `consumed`.
- `plan_fix_unit` adds `cand.consumed` only for a task it makes, and a feedback task takes the `continue` before that
  line. A plan that is feedback-only has therefore `consumed == []`.
- `effective_verdicts` drops a reject only when `verdict.question in consumed`.
- The next round raises the hold again (same text, same `H-` id), `effective_verdicts` still returns the reject, and
  `settle_holds` adds the human finding again.

### 1.2 What the person could do [V]

`l4 status` printed `Next: l4 retry --unit U --reason TEXT`. A retry gave the same FAIL. `l4 questions answer Q-004`
refused, because the question is answered.

## 2. Decisions

### D1 Read time: a feedback-only spawn consumes the earlier rejects

`effective_verdicts` records, for the latest verdict of each target, its position in the ledger. A `reject` is dropped
when its question is in a `fix.spawned.consumed` list (today's rule) or when a `fix.spawned` with
`feedback_only: true` is after it in ledger order. A reject recorded after that spawn stays in force. A `fix.spawned`
without `feedback_only` (including `adopted: true`, written by `adopt_orphans`) keeps today's rule. An `accept` is not
touched by this rule.

**Why this rule is right.** A feedback-only spawn happens only when `plan.feedback_only` holds: every task of the plan
answers a feedback item. A reject in force that had a convertible form (a criterion, or a `WHEN ... THEN ...`) would be
a task of the plan or would be consumed with it, and the plan would not be feedback-only; so, at the spawn, every
reject in force was a non-convertible human one. The escalation's documented way out is to give the fix as feedback.
The feedback is the concrete form of that rejection, and `feedback.judged` checks in the next rounds that it was
addressed. Keeping the abstract reject in force after the concrete request was fixed and judged only repeats a
decision that the person has already turned into a request. [I]

Rejected alternative: judge the reject by title against the feedback items. It needs text matching and would fail for
a feedback item worded differently.

### D2 Write time: `consumed` lists the not converted rejects

`plan_fix_unit` collects, for each finding that `_candidates` lists as not converted because of a human decision, the
question of the reject of that finding (`rejects` by finding id, then by criterion). When the plan is feedback-only,
these questions are added to `FixPlan.consumed`; `after_verdict` writes the list into `fix.spawned.consumed` already.
A new ledger therefore says explicitly what D1 infers for an old one. For a plan that is not feedback-only the list is
unchanged (those rejects stay in force: the round also escalates or spawns a normal fix unit). [V for the code path;
the equivalence of D1 and D2 is covered by a test on each]

### D3 The hold is asked again

With the reject dropped, `unresolved_holds` keeps the hold and the round is NEEDS_HUMAN. `raise_verdict_questions`
treats only unconsumed questions as waiting (`verdict_status` leaves out the ones with a `human.verdict`), so Q-004
does not hold the target and a new question is raised. The person (or an agent that is allowed to) decides on the
fixed code. [V in `verdicts.py`]

### D4 The next step of the escalation

`next_step` is a pure function of `UnitFacts`. The planner's facts get `halt_reason` (the recorded code); for
`escalated` with `halt_reason == "no_convertible_finding"` the step is
`give the fix the human's finding asks for as feedback: l4 feedback add --unit U --kind behaviour --when ... --then ...
--text ... (then the git lines add prints), then l4 retry --unit U --reason TEXT; a retry alone repeats the same
verdict`. The flags are those of `l4 feedback add` (`--text` is required there). The orchestrator's refusal of
`l4 run --unit` and the sticky note section use the same sentence. The label `l4:retry` still moves the unit, and
`label_for` is unchanged: the label is the retry, and the sticky note says that it helps after the feedback. Other
causes keep their text. The code constant lives in `l4.state.next_step` (the verifier imports it), so `next_step.py`
does not import the fix loop.

### D5 `--replace` is for a verdict answer only

Allowed when the question is `answered`, of kind `verdict`, and the text starts with `accept` or `reject`. A question
that is still open (use plain `answer`), a clarification question (L4-QMD-006: an answer a run used becomes a fix unit
when its text changes by hand), an `accepted` or `dismissed` one, and a text equal to the current answer are refused.
`agent_reason` already refuses a verdict answer to an agent unless `clarifier.answer_by_agents` is true, so a replace
by an agent has the same rule.

### D6 The audited form

The new answer is written as the body of `### Answer`, as `answer` writes it. Then the previous answer is kept in an
HTML comment under it, one per replacement, oldest first:

```
<!-- l4 questions --replace by NAME on DATE; previous answer:
> reject the diff is too long ...
-->
```

`_visible` removes comments, so `answer_text`, the digest and the reason of `human.verdict` hold the new text only, and
the history never reaches a prompt. Each line of the previous answer is prefixed with `> ` (so no line reads as
structure) and `-->` is written as `--&gt;` [G]. A hand-edited history is kept as it is. The commit subject is
`answer Q-NNN (unit): title (answer replaced)`, with `Replaced: yes` in the trailer block.

The existing consumption already does the rest [V]: `consume_verdicts` appends a new `human.verdict` when the digest
of the effective answer differs from the recorded one, and `effective_verdicts` keeps the latest per target. The
accept of the replacement has the `text_sha256` of the question's `question.raised`, which is `finding_sha256` of the
hold id, so it is not void. The reject-to-accept test runs the whole chain.

## 3. Risks

- D1 reads a ledger of 0.4.5 where a person's reject came before a feedback-only spawn that was caused by something
  else. By D1's argument every reject in force at such a spawn was non-convertible, so none was convertible and lost.
  The only loss is a non-convertible reject that the person wanted to keep; they can reject again, and the new reject
  is after the spawn and stays [I].
- `--replace` changes a decision after the fact. It is audited by the commit and by the comment, and only a person
  (or a project that allows agents) can do it.
