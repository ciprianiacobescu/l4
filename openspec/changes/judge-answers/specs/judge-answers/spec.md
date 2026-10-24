## Purpose

The judge reads the answers the unit's questions got, so it judges a criterion as an answer narrowed it instead of
sending a decision already made back to a person.

## ADDED Requirements

### Requirement: L4-VER-065 Every judge prompt carries the family's answered questions
Every judge prompt of a round (the whole diff, each part and each follow-up) SHALL carry one `<l4:data kind="answer"
id="<id>" by="<actor>">` block per answered question of the unit's family whose kind is `technical`, `product`,
`ambiguous` or unknown. `verdict` and `harness` questions, and dismissed, superseded and open questions, SHALL be left
out. `<id>` SHALL be `<fix unit>/Q-NNN` for a fix unit's question, and `<actor>` the answer's actor (L4-QMD-009). A
block SHALL hold the question's title and options, marked as the implementer's unverified text, and the effective
answer, each redacted before it is cut (title 300, options 2,000, answer 3,000 characters). The blocks together SHALL
be at most 12,000 characters, and the questions past that SHALL be named. The block's length SHALL be charged to the
judge's context budget before the spec text. An unreadable questions file SHALL be named in the block and SHALL NOT
stop the round.

#### Scenario: SCN-VER-232 (+) A technical answer reaches the judge
- **GIVEN** a unit whose `questions.md` holds Q-001 (`technical`, answered by a person "exit 1, not 2")
- **WHEN** the judge prompt is built
- **THEN** it holds one `<l4:data kind="answer" id="Q-001" by="human">` block with the title, the answer and the
  words that the question text is the implementer's

#### Scenario: SCN-VER-233 (−) Verdict, harness, dismissed and open questions stay out
- **GIVEN** answered questions of kinds `verdict` and `harness`, a dismissed `technical` question and an open
  `product` question
- **WHEN** the judge prompt is built
- **THEN** it holds no answer block

#### Scenario: SCN-VER-234 (+) A fix unit's answer is named under the fix unit
- **GIVEN** a family with fix unit `u-fix-1` whose `questions.md` holds an answered Q-001
- **WHEN** the parent's judge prompt is built
- **THEN** the block's id is `u-fix-1/Q-001`

#### Scenario: SCN-VER-235 (−) Long answers are cut and the rest named, never dropped silently
- **GIVEN** answered questions whose answers total more than 12,000 characters, one of them a 5,000-character answer
  holding a token-shaped secret across the 3,000th character
- **WHEN** the judge prompt is built
- **THEN** the long answer ends `[truncated: …]`, the secret appears in no piece, the block is at most 12,000
  characters, and a last line names every question not shown

#### Scenario: SCN-VER-236 (+) Parts and follow-ups carry the same block
- **GIVEN** a round whose diff is judged in two parts and then one follow-up, and one answered technical question
- **WHEN** the three prompts are built
- **THEN** each holds the same answer block

### Requirement: L4-VER-066 The judge judges a criterion as an answer narrowed it
The judge's rules SHALL say that an answer block is the project's decision and its question text the implementer's,
that a criterion an answer settles or narrows is judged as the answer reads it with the answer's id in its reason, that
an answer never makes a criterion pass without evidence, never outweighs a failing gate and adds no criterion, and
that an input an answer settles is not a `spec_gap`. The judge prompt version SHALL be `judge@13`. The round's
`verify.judge` event SHALL list the answers shown as `answers: [[<id>, <answer_sha256>], …]`.

#### Scenario: SCN-VER-237 (+) The rule and the version
- **GIVEN** the judge's system text
- **WHEN** a judge prompt is built
- **THEN** its version is `judge@13`, the system text holds the answer rule, and the template lock records version
  13 with the new text's hash

#### Scenario: SCN-VER-238 (+) The ledger names what the judge was told
- **GIVEN** a round whose prompt held answer blocks for Q-001 and `u-fix-1/Q-002`
- **WHEN** the judge has replied
- **THEN** the `verify.judge` event holds `answers` with both ids and their `answer_sha256`, and a round without an
  answered question records `answers: []`
