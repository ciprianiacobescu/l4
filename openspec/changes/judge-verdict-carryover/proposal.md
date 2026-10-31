## Why

A consumer's unit was verified three times on the same production code. In round 1 the judge passed all 29 criteria.
Round 2 reused that step 9 on the same head and failed on a person's rejects. The fix unit then added one test file,
which was the only change outside the spec directory. In round 3 the judge timed out on part 3 of 4, the round had no
judge verdict, and every one of the 29 criteria became a verdict question ("the judge gave no verdict for this
criterion"). The consumer's delegate answers each at about $1. The verdicts of round 1 still described the code exactly:
nothing a judge had passed had changed.

## What Changes

- When step 9 of a round ends with no judge verdict (the reply of a part was discarded: timeout, schema break after the
  repair), each criterion takes the `pass` of the newest earlier round that has a judge verdict, if all of these hold:
  - the criterion's source file is the same at both heads;
  - every path that changed between the two heads is in a directory of the unit family or is a test file (a test glob
    that is not a support glob), and none of those test files holds a test that traces the criterion (at that round or
    now);
  - no test traces it now that did not trace it then, and every test that traces it passes now.

  The earlier round's test-adequacy entries for the criterion's tests are applied with it.
- The criterion's reason says `the judge of round <R> passed it at <head10>, and only tests that do not trace it changed
  since (carried)`. The ledger records `verify.carried`, and `verify.not_carried` with the reason when no criterion can be
  carried. `verdict.json` keeps `judge_carried`.
- Nothing else is carried: the round keeps its hold (`the judge's reply was discarded …`), so it cannot PASS until a
  person or the delegate answers the hold; findings are not carried. Criteria that cannot be carried are asked as today.

Not in this change: carrying a verdict when the round's judge answered but left a criterion out; carrying `fail` or
other verdicts; partial replies of the round's own parts.

## Impact

- Code: `l4.verifier.carryover` (new: the rule, pure over git facts and the stored verdict), `l4.verifier.ladder`
  (`_finalize` applies it when `run.judged` is None), `l4.verifier.types` (`judge_carried`), `l4.verifier.report`
  (`verdict_json`), `l4.verifier.evidence` (`restore_round`).
- Spec: L4-VER-072 (new); SCN-VER-273..277; change-table row 112.
- Cost: fewer verdict questions in a round whose judge gave no answer after a test-only change; no extra judge call.
