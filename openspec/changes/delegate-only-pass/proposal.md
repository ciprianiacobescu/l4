# A run that only answers questions answers all that are due, and a short quote is named as such

## Why

On a consumer (2026-10-29/30, harness 0.4.39-0.4.42) one verification round of a web unit raised 30 and 33 verdict
questions at once (one per held criterion) [V, the units' ledgers]. The delegate pass asks at most
`delegate.max_questions_per_run` (default 5) questions per run, and the unit verifies again only when every verdict is
settled (`planner.py`: `verdicts_ready and not verdicts_open`), so each further run was a delegate-only pass of 5:
a delegate-only run took 3.3 minutes. Then the per-unit cost cap (`max_cost_usd_per_unit`, $15; a call needs $3 left)
stopped the delegate after about 12 calls, and the rest went to a person. The two units used 9 and 6 of the plan's 60
runs.

Separately, the delegate's replies were thrown away 5 times (about $5.40 of one unit's $15) because a `checked` quote
was shorter than 12 characters (`MIN_QUOTE_CHARS`): the refusal said "does not resolve" and the prompt never states the
minimum, so the retry made the same mistake [V: the quotes were on the cited lines].

## What changes

- In a run whose only work for the unit is the delegate pass (no step of the unit ran in this run before it), the pass
  is not bound by `max_questions_per_run`: it asks until nothing is due, the soft deadline (L4-DLG-013) or a cost limit
  (L4-DLG-009). The pass at the end of a run that did unit work keeps the cap. The unit still does not continue in the
  same run (design D4 of delegate-answers is unchanged).
- A `checked` quote shorter than `MIN_QUOTE_CHARS` is refused with "the quote of <ref> is shorter than 12 characters"
  (retryable), and the prompt states the minimum.

## Impact

- Code: `l4.delegate.run` (the pass loop), its caller in `l4.orchestrator` (`_delegate`), `l4.delegate.reply`
  (`_resolves` reasons), `l4.delegate.prompt`.
- Spec: L4-DLG-003 and L4-DLG-005 amended (find the requirement that lists the reply checks); SCN-DLG-123 to SCN-DLG-126
  added; change-table row 99.
- Expected effect, stated honestly: with the default $15 per unit the cost cap still binds at about 12 calls, so this
  saves about one run per flood of verdicts, not most of them; the quote fix saves money on every flood. The cost cap
  is the owner's setting (`delegate.max_cost_usd_per_unit`) and is not changed here.
