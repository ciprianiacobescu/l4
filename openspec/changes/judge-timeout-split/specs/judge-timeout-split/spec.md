## MODIFIED Requirements

### Requirement: L4-VER-071 A judge whose reply does not fit its output limit or its time is asked again with fewer criteria
When a step-9 judge's reply to a prompt of two or more criteria stops at the model's output limit, or its call ends
`timeout`, the harness SHALL ask the same judge again with the prompt's criteria split in two halves, and SHALL split a
half that stops at the limit or times out again, at most `verifier.judge_length_splits` times. While a prompt can still
be split, its timeout SHALL NOT be retried with the same prompt; a batch that cannot be split again SHALL keep the one
retry of a timeout, and its timeout SHALL hold the round. `judge.length_split` SHALL name its `cause` (`length` or
`timeout`). Follow-up calls SHALL NOT be split.

#### Scenario: SCN-VER-270 (+) a part that times out is judged in two batches without a retry of the whole prompt
- **WHEN** a judge's call for part 3 of 4 with 29 criteria ends `timeout`, and its calls for 15 and 14 criteria answer
- **THEN** the whole prompt was called once, `judge.length_split{cause: timeout, into: [15, 14], depth: 1}` is recorded,
  the same judge answers both batches and part 3 has one reply with 29 verdicts

#### Scenario: SCN-VER-271 (−) a batch that cannot be split again keeps one retry, and its timeout holds the round
- **WHEN** every call of a judge times out, with `judge_length_splits` 2
- **THEN** the whole prompt and the first half are called once each, the first quarter twice, and the round holds `the
  judge's reply was discarded (part K of N, timeout: …)` as before

#### Scenario: SCN-VER-272 (−) a follow-up and a prompt of one criterion keep today's timeout handling
- **WHEN** a follow-up call or a prompt of one criterion times out
- **THEN** it is retried once with the same prompt, and no `judge.length_split` is recorded
