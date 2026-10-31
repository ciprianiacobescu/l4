## ADDED Requirements

### Requirement: L4-VER-071 A judge whose reply does not fit its output limit is asked again with fewer criteria
When a step-9 judge's reply to a prompt of two or more criteria stops at the model's output limit (an agent run with
`length_stop`, set by the opencode adapters when the stream's last reason is `length`), the harness SHALL ask the same
judge again with the prompt's criteria split in two halves, and SHALL split a half whose reply stops at the limit again,
at most `verifier.judge_length_splits` times (default 2), before the judge is discarded for the round. The batch replies
of a prompt SHALL be merged into one reply for it; a batch prompt SHALL say which of the unit's criteria it judges, and
only the first batch SHALL carry the feedback, accepted, satisfied and done-task blocks. A batch that gives no verdict
SHALL discard the judge as a whole prompt does today, and the next judge SHALL be given the whole prompt. The split
SHALL be recorded (`judge.length_split`, `verify.judge.batch_criteria`, `verdict.json` `judge_batches`). Follow-up calls
SHALL NOT be split.

#### Scenario: SCN-VER-265 (+) a part whose reply stops at the limit is judged in two batches by the same judge
- **WHEN** a judge's reply to part 1 of 4 with 29 criteria stops with last reason `length`, and its replies to 15 and to
  14 criteria fit
- **THEN** `judge.length_split{part: 1, criteria: 29 ids, into: [15, 14], depth: 1}` is recorded, the same judge answers
  both batches, part 1's reply holds 29 verdicts, the next judge is not selected, and `verdict.json` lists two
  `judge_batches` rows for part 1

#### Scenario: SCN-VER-266 (−) a judge whose smallest batch still stops at the limit is discarded and the next judge gets the whole part
- **WHEN** every reply of a judge stops at the limit, with `judge_length_splits` 2
- **THEN** the judge is asked at most 7 times for the part, `availability.judge_error` names the batch and its depth, and
  the next judge is given the part's prompt with all of its criteria

#### Scenario: SCN-VER-267 (+) only the first batch carries the unit-wide asks
- **WHEN** a prompt with feedback, accepted and satisfied items is split
- **THEN** the first batch's prompt holds those blocks and the batch section `This call judges 15 of the unit's 29
  criteria`, the second batch's prompt holds none of them, and no call asks for a missing feedback, accepted or satisfied
  id in the second batch

#### Scenario: SCN-VER-268 (+) the opencode adapters mark a length stop
- **WHEN** an opencode (v1 or v2) run's stream ends with last reason `length` and no result
- **THEN** the run's status is `error` as before and `length_stop` is true, and the structured result and the judge run
  carry it; a run that ends with any other reason has `length_stop` false

#### Scenario: SCN-VER-269 (−) no split when it is turned off, for a single criterion, or in a follow-up
- **WHEN** `verifier.judge_length_splits` is 0, or the prompt has one criterion, or a follow-up call's reply stops at the
  limit
- **THEN** no `judge.length_split` is recorded and the judge is handled as before (discarded, or the follow-up keeps the
  parts' verdict)
