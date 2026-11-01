## Why

A consumer's unit of 25 criteria was verified with its diff in two parts. On part 1 the judge's reply listed more than
three `riskiest_assumptions`, the schema allows exactly three, and the repair prompt got the same break back. The reply
was discarded, part 2 was never asked, and the round had no judge verdict: every criterion became a verdict question
("the judge gave no verdict for this criterion"). More judges were configured, but none was asked. The one field that
broke cannot change a verdict: it is free text that the harness keeps only as evidence.

Two rules disagreed with what happened. The repair of weak judges' replies (W-D1) fixes trivial breaks with one obvious,
meaning-preserving fix, but not a list of free text that is too long. And L4-VER-015 says that a judge whose answer is
"schema-invalid after repair" is discarded and "the next independent judge is tried; if none remains, affected criteria
are `needs_human`", while the ladder held the round at the first judge.

## What Changes

- The deterministic repair also folds a list of free text that is longer than its `maxItems` (`riskiest_assumptions`):
  the first items stay, and the rest are joined by newlines into the last allowed item, so no text is lost and the list
  has exactly the allowed number of items. Only named fields are folded, only when every item is a string; a list of
  objects is never shortened, and a short list is never filled.
- A whole prompt or a part whose reply still breaks the schema after the repair and the retry gives way to the next
  independent judge, as an answer that cannot be used already does: the discarded reply is never counted, and the next
  judge gets the whole prompt of that part. When no independent judge remains, the round holds the discarded reply as
  today (`needs_human`), never `waiting_capacity`. A follow-up keeps its own rule and is not moved to another judge.
- A timeout left after the splits of L4-VER-071 still holds the round and does not ask the next judge. L4-VER-015 says
  this now (its row said that a second timeout discards the judge "like a refused answer").

## Impact

- Code: `l4.verifier.judge_repair` (`FOLDED_LISTS`, the fold in `_walk`), `l4.verifier.ladder._ask_judges` (a
  `schema_invalid` of a prompt that is not a follow-up asks `next_judge("schema_invalid")`; a `WaitingCapacity` from it
  keeps the discarded reply).
- Spec: L4-VER-074, L4-VER-075 (new); the W-D1 paragraph of 10.3, the rows of L4-VER-015 and the batch sentence of
  L4-VER-071; SCN-VER-166; SCN-VER-283..287; change-table row 114.
- Cost: a judge that breaks the schema twice costs the next judge's call for that prompt, in place of a verdict question
  per criterion.
