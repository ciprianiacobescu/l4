## ADDED Requirements

### Requirement: L4-VER-074 An over-long list of free text in a judge's reply is folded, not discarded
The deterministic repair of a judge's reply SHALL fold a list in a field of `FOLDED_LISTS` (`riskiest_assumptions`) that
has more items than its `maxItems` N and only string items: the first N − 1 items SHALL stay as they are and the
remaining items SHALL be joined by newlines into the N-th item, and the field's path SHALL be recorded as repaired. A list
in another field, a list with an item that is not a string and a list with fewer items than its `minItems` SHALL NOT be
changed. The repair's other rules SHALL hold: a reply that is still invalid, or whose criteria's ids or verdicts would
change, is not repaired.

#### Scenario: SCN-VER-283 (+) five riskiest assumptions become three and the reply is kept
- **WHEN** a judge's reply is valid except that `riskiest_assumptions` has five strings
- **THEN** the repaired reply has three: the first two as they were and the third with the third, fourth and fifth
  joined by newlines; the fields are `("riskiest_assumptions",)`, the verdicts are unchanged, `run_judge` makes one call
  and its reply is `repaired`

#### Scenario: SCN-VER-284 (−) a short list or a list with an item that is not text is not folded
- **WHEN** `riskiest_assumptions` has one string, or four items one of which is an object
- **THEN** the repair leaves the reply as it is, and the repair prompt is asked with the violated path

### Requirement: L4-VER-075 A judge whose reply still breaks the schema gives way to the next independent judge
When the reply to a step-9 prompt or part is `schema_invalid` after the repair and the retry, the harness SHALL discard
it and ask the next independent judge the same prompt, as after a `model_mismatch` or an `error`; the discarded judge
SHALL be skipped for the rest of the round and SHALL NOT be cooled down. When no independent judge remains, the round
SHALL hold the discarded reply (`the judge's reply was discarded (…schema_invalid: …)`) and its criteria SHALL be
`needs_human`; the unit SHALL NOT wait for capacity. A batch of L4-VER-071 that ends `schema_invalid` SHALL be handled as
a whole prompt's schema break is: the next judge gets the whole prompt. A follow-up SHALL NOT be moved to another judge.
A timeout left after the splits SHALL still hold the round without asking the next judge.

#### Scenario: SCN-VER-285 (+) the next judge answers after a schema break
- **WHEN** the judges are `free` and `last`, and `free`'s reply breaks the schema twice
- **THEN** `verify.judge` records `free` with `schema_invalid` and then `last` with `ok`, the round has `last`'s
  verdict and `verification.md` names `last`

#### Scenario: SCN-VER-286 (−) no judge left after a schema break holds the round and does not wait
- **WHEN** the only independent judge's reply breaks the schema twice
- **THEN** the round holds `the judge's reply was discarded (schema_invalid: …)`, the criteria are `needs_human`, and the
  unit is `awaiting_human` (exit 11), not `waiting_capacity`

#### Scenario: SCN-VER-287 (+) a part's schema break gives way to the next judge for that part
- **WHEN** a diff is judged in two parts, the first judge answers part 1, its reply to part 2 breaks the schema twice,
  and another independent judge is configured
- **THEN** the other judge is asked part 2 with its whole prompt, the round's verdict merges both parts, and a batch of
  a split prompt that breaks the schema twice gives the next judge the whole prompt in the same way

## MODIFIED Requirements

### Requirement: L4-VER-015 Failure precedence
The row for a judge call that times out SHALL read: retried once, or split (L4-VER-071); a timeout left after that holds
the round, and the next judge is not asked (L4-VER-075). The row for an answer that is refused, truncated,
schema-invalid after repair or from a mismatched model is unchanged, and L4-VER-075 implements it for a schema break.

#### Scenario: SCN-VER-166 (−) A part whose reply is discarded discards the judge's verdict
- **WHEN** a diff in two parts whose second part's reply breaks the schema twice, and no other independent judge
- **THEN** the round has no judge verdict, it holds `the judge's reply was discarded (part 2 of 2, schema_invalid: …)`,
  and no verdict of part 1 is counted
