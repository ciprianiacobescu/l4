## Context

`run_judge` makes at most two calls per prompt: a reply that breaks `l4/judge-verdict@1` is first repaired by
`judge_repair.repair_reply` (W-D1) and, when that does not make it valid, asked for once more with the violated paths.
A second break is `schema_invalid` with `reply: discarded`. `ladder._ask_judges` moves to the next independent judge
(`vc.next_judge`) only after a usage limit, a `model_mismatch` or an `error`; on `schema_invalid` and `timeout` it stops,
and `judge_body` holds the round (`the judge's reply was discarded (part P of N, schema_invalid: …)`) without asking the
other parts. `next_judge` adds the profile to the round's `skip` set and selects again; when no independent judge is
left it raises `WaitingCapacity` (`no independent verifier`).

## Decisions

### D1 The fold (L4-VER-074)

`judge_repair.FOLDED_LISTS = frozenset({"riskiest_assumptions"})`. In `_walk`, after the items of a list are walked:
when the field's name is in `FOLDED_LISTS`, the schema gives `maxItems` N, the list has more than N items and every item
is a string, the result is the first N − 1 items and then the remaining items joined by `"\n"`, and the field's path is
recorded. The join keeps every word of the reply (as a list in a free-text field is joined by newlines), and the result
has exactly N items, which `judge_parts._assumptions` needs (it takes the parts' first, second and third item). A list
in another field, a list with an item that is not a string, and a list shorter than its `minItems` are left as they
are: a list of criteria, findings or adequacy rows is never shortened, and an item is never invented. The repair's
other guards stay: the reply must be valid after it, and no criterion's id or verdict may change.

### D2 The next judge after a schema break (L4-VER-075)

In `_ask_judges`, a result with status `schema_invalid` for a call that is not a follow-up (`followup is None`) and with
a `vc.next_judge` SHALL call `vc.next_judge("schema_invalid", None)` and ask the new judge the same prompt (with its own
`criteria` and `rebuild`, so its reply can be split as any judge's can). `next_judge` skips the profile for the rest of
the round and does not cool it down: the same judge may answer another unit or round validly. A `WaitingCapacity` from
`next_judge` SHALL end the loop with the discarded result, so that `judge_body` holds the round as before and the
criteria are `needs_human`: running out of judges after a schema break is not a capacity problem, since every judge that
was asked answered. A `schema_invalid` batch of `_ask_batches` is returned to `_ask_judges` as it is today, so the next
judge gets the whole prompt, as after a batch that ends `error`. The discarded judge's `verify.judge` row
(`status: schema_invalid`, `reply: discarded`) stays in the ledger, the next judge's row follows it, and `verification.md`
names the judge that gave the final answer (as after a mismatch). No new event is needed.

### D3 A timeout still holds the round

A timeout left after the splits of L4-VER-071 (or a prompt that cannot be split, after its one retry) SHALL still hold
the round without asking the next judge: the next judge would spend its own timeouts on the same prompt, up to four per
part with the defaults, inside the same job. L4-VER-015's row is amended to say this; SCN-VER-271 already shows it.

### D4 Follow-ups keep their rule

A follow-up (L4-VER-057) that gives no valid verdict keeps the merged verdict of its criteria and does not stop the
round; it is not moved to another judge, so the judge that answered the parts answers its follow-ups.

## Risks

- A weak judge that breaks the schema on every prompt now costs a second judge's call per part in each round, in place
  of a verdict question per criterion. The skip set lasts for one round only.
- A part answered by another judge than the other parts is merged as today after a `model_mismatch` or an `error`.
