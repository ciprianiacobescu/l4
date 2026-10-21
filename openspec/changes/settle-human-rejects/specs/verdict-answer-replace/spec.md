## Purpose

A person can change a verdict answer on purpose, with the old answer kept in the file and the change named in the
commit.

## ADDED Requirements

### Requirement: L4-QMD-010 A verdict answer is replaced with --replace
`l4 questions answer Q-NNN --unit U --text TEXT --replace` SHALL be allowed only for a question of kind `verdict`
whose Status is `answered`, with a text that starts with `accept` or `reject`, and different from the current answer.
It SHALL write the new answer as `answer` does, keep the previous answer in an HTML comment under it (so that
`answer_text`, the answer digest and the reason of `human.verdict` hold the new text only), and name the replacement in
the commit subject (`(answer replaced)`). The next verification round records the new answer as a `human.verdict`, and
the latest verdict of a target is the one in force.

Without `--replace`, the refusal of an answered verdict question SHALL remain and its `Fix:` line SHALL name
`--replace`. With `--replace`, a question that is not a verdict question, or not `answered`, SHALL be refused
(L4-QMD-006 is unchanged: a clarification answer that a run used is changed by hand and becomes a fix unit).

#### Scenario: SCN-QMD-26 (+) A replaced answer keeps the old one in a comment
- **GIVEN** Q-004 of kind verdict, `answered` with `reject too long`
- **WHEN** `l4 questions answer Q-004 --unit U --text "accept the fix is in" --replace` runs
- **THEN** the section has the new answer, the old text in a comment, Status `answered`, and the commit subject ends with `(answer replaced)`

#### Scenario: SCN-QMD-27 (−) Without the flag, or for another kind, it is refused
- **GIVEN** an answered verdict question and an answered clarification question
- **WHEN** `answer` runs without `--replace` for the first, and with `--replace` for the second
- **THEN** both exit 2; the first `Fix:` names `--replace`, the second says a clarification answer is changed by hand

#### Scenario: SCN-QMD-28 (+) A replaced reject becomes an accept that clears the FAIL
- **GIVEN** a hold with a recorded `reject` and a replaced answer `accept ...`
- **WHEN** `consume_verdicts` and `effective_verdicts` run
- **THEN** a second `human.verdict` is recorded, the accept is in force, and the hold raises no finding
