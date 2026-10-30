## Purpose

A verdict answer that no round of the unit's current attempt asked for can neither settle a criterion nor keep the
unit verifying again for ever.

## ADDED Requirements

### Requirement: L4-VER-070 A verdict question counts only in the attempt that raised it
A verdict question in `questions.md` SHALL count as open, ready, invalid or dismissed, and as waiting for its target,
only when a `question.raised{kind: verdict}` event of the unit's current ledgers names its id. A verdict question that
no such event names SHALL be `stale`: it SHALL NOT make a run take `VERDICTS_ANSWERED`, SHALL NOT be consumed, SHALL NOT
keep `raise_verdict_questions` or the legacy path of L4-VER-013 from asking its target, SHALL NOT be offered to the
delegate, and SHALL NOT appear in the sticky note as waiting. Every reader of verdict questions (`verdict_status` and
its callers in the orchestrator, the planner, the delegate, the notes and the legacy check) SHALL apply this rule, the
one `consume_verdicts` applies. `l4 questions list` SHALL show a stale verdict question with `stale: raised by an
earlier attempt; the next round asks again`. [V, a consumer unit after `l4 restart` verified again on every run on
three carried-over answered verdict questions that it never consumed]

## MODIFIED Requirements

### Requirement: L4-OPS-004 restart (step 3)
Step 3 SHALL keep `questions.md` with every open question and every verdict question that the old attempt did not
consume, answered or not, set to `superseded by restart`, and SHALL keep answered technical questions as they are;
`unit.restarted{superseded_questions}` SHALL list every question it superseded.

#### Scenario: SCN-VER-257 (−) A carried-over answer does not make the unit verify again
- **GIVEN** a unit whose `questions.md` holds Q-001, a verdict question on criterion C answered `accept: fine`, and
  whose current ledgers hold no `question.raised` for Q-001, and whose last round ended NEEDS_HUMAN on C
- **WHEN** the next run starts
- **THEN** it does not take `VERDICTS_ANSWERED` and makes no judge call; it raises a new verdict question for C with
  `question.raised{kind: verdict}` and waits for the answer

#### Scenario: SCN-VER-258 (+) An answer to a question this attempt raised is consumed as before
- **GIVEN** the same unit after the new question Q-004 for C is answered `accept: fine`
- **WHEN** the next run starts
- **THEN** it records `human.verdict` for Q-004, and Q-001 is neither consumed nor asked again

#### Scenario: SCN-VER-259 (−) A stale question is not offered to the delegate and is listed as stale
- **WHEN** the delegate computes the due questions, and a person runs `l4 questions list`, for the unit of SCN-VER-257
- **THEN** Q-001 is not due, and the list shows it with `stale: raised by an earlier attempt; the next round asks again`

#### Scenario: SCN-VER-260 (+) A unit that already loops stops on the fixed harness
- **GIVEN** the unit of SCN-VER-257 after three rounds that each ended NEEDS_HUMAN on C, its state `awaiting_human`
- **WHEN** a run of the fixed harness starts
- **THEN** it raises a verdict question for C (the legacy path when the round raised none) and makes no judge call

#### Scenario: SCN-OPS-52 (−) A restart supersedes an answered verdict question
- **GIVEN** a unit whose `questions.md` holds a verdict question answered but not consumed
- **WHEN** `l4 restart` runs
- **THEN** that question's Status is `superseded by restart` and `unit.restarted{superseded_questions}` names it

#### Scenario: SCN-OPS-53 (+) A restart keeps an answered technical question
- **GIVEN** a unit whose `questions.md` holds an answered technical question
- **WHEN** `l4 restart` runs
- **THEN** the question and its answer stay as they were
