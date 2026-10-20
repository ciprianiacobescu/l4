## Purpose

A fix task built from a person's reject is checked against what the person said: their own `WHEN … THEN …`, else the
cited criterion as it is written. The judge's suggested fix, which describes the code as it is now, never becomes the
check of a task a person rejected, every reject a task consumes is quoted in it, and a verdict question tells the
person how to set the check.

## ADDED Requirements

### Requirement: L4-VER-059 A person's reject decides a fix task's check
The verdicts of a finding in a fix task SHALL be the `reject` of the finding and the `reject` of its cited criterion,
in that order, each when present. Every verdict of every finding of a task SHALL be quoted in the task's decisions
(`Decided by <by> in Q-NNN: <reason>; Q-MMM: <reason>.`, together within the characters L4-VER-006 keeps for decisions), whichever of them gave a
scenario, and both questions are consumed. The task's regression scenarios SHALL come from these verdicts only: the
`WHEN … THEN …` of each reason that has one, the finding's first, each text pinned once. The judge's `suggested_fix`
SHALL be a scenario only of a spec-gap finding that has no verdict (a minor on a PASS with
`verifier.fix_minor_findings`); it MUST NOT become a scenario of a finding that has a verdict, whether the reason is
empty, says nothing of it, or agrees with it, and no model or text match decides agreement. A finding that has a
verdict and no scenario from it SHALL keep its cited criterion and add no regression requirement, so the fix is checked
against that criterion's own scenarios (OpenSpec: `skip_specs: true` when no other task adds a scenario; Kiro: only the
restated criterion as `2.n`). Without a cited criterion such a finding SHALL NOT be converted: it is listed `rejected
with no criterion and no WHEN ... THEN ...: answer again with a scenario`, and its question is not consumed.

#### Scenario: SCN-VER-205 (−) A reason without a scenario does not pin the judge's suggestion
- **GIVEN** a judge-only major spec-gap finding on criterion C, whose scenario says a lookup of an unknown id exits 1,
  with the suggested fix `WHEN the id is unknown THEN the command exits 2`, and the person's answer `reject: the
  criterion requires exit 1; the code exits 2`
- **WHEN** the next round fails and the fix unit is written
- **THEN** its one task cites the finding and C, its text starts `Decided by human in Q-002: the criterion requires exit
  1; the code exits 2.`, the OpenSpec fix unit has no spec delta and `skip_specs: true`, the Kiro `bugfix.md` has one
  expected item (C restated) and the task's `_Requirements:_` names only it, and no file of the fix unit contains `THEN
  the command exits 2`

#### Scenario: SCN-VER-206 (−) A bare reject does not pin it either
- **GIVEN** the finding of SCN-VER-205 answered `reject` with no reason
- **WHEN** the fix unit is written
- **THEN** the task cites the finding and C, its text starts `Decided by human in Q-002: rejected, no reason given.`,
  and no regression requirement is added

#### Scenario: SCN-VER-207 (+) The person's scenario is the check
- **GIVEN** the finding of SCN-VER-205 answered `reject: the criterion requires exit 1. WHEN the id is unknown THEN the
  command exits 1`
- **WHEN** the fix unit is written
- **THEN** it adds the regression requirement of C's requirement with the scenario `WHEN the id is unknown` / `THEN the
  command exits 1`, the task cites the finding, C and the new criterion, and no file of the fix unit contains `THEN the
  command exits 2`

#### Scenario: SCN-VER-208 (+) A criterion's reject is quoted and its scenario pinned
- **GIVEN** the finding of SCN-VER-205 answered as Q-003 `reject: the code exits 2`, and criterion C answered as Q-002
  `reject: the criterion requires exit 1. WHEN the id is unknown THEN the command exits 1`
- **WHEN** the fix unit is written
- **THEN** one task cites the finding and C, its text starts `Decided by human in Q-003: the code exits 2; Q-002: the
  criterion requires exit 1.`, the fix unit consumes Q-003 and Q-002, and its one added scenario is Q-002's

#### Scenario: SCN-VER-209 (−) A rejected spec gap with no criterion and no scenario is not converted
- **GIVEN** a judge-only major spec-gap finding whose criterion the unit does not have, with a suggested fix `WHEN a THEN
  b`, answered `reject: wrong`, and no other finding in the round
- **WHEN** the round fails
- **THEN** no task is made from it, it is listed `rejected with no criterion and no WHEN ... THEN ...: answer again with
  a scenario`, its question is not consumed, and the unit escalates with `no finding of this round can be converted
  into a fix task`

#### Scenario: SCN-VER-210 (+) A spec gap that no person rejected still pins the judge's suggestion
- **GIVEN** a round that passes with `verifier.fix_minor_findings: true` and a minor spec-gap finding on C with the
  suggested fix `WHEN a blank code is given THEN it raises ValueError`
- **WHEN** the fix unit is written
- **THEN** it adds the regression requirement of C's requirement with that scenario, as before this change

### Requirement: L4-VER-060 A verdict question says how a person sets the fix's check
The verdict question of a judge-only finding SHALL say that a rejected finding is fixed by a fix unit and that the
reason comes first in it; when the finding cites a criterion, that ending the reason with one sentence `WHEN <the
situation> THEN <the behaviour you expect>` (WHEN and THEN in capitals) makes it a scenario of the fix unit, and that
without one the fix is checked against that criterion as it is written; when it cites none, that the sentence is needed
or no fix can be made from the reject. For a spec gap with a suggested fix it SHALL also say that the suggested fix
describes what the code does now, that a reject does not use it, and that ending the reason with it pins that
behaviour. The verdict question of a criterion SHALL say the same of `the scenario above`, in place of the advice to
answer with a scenario only when the code is right. Both SHALL offer the options `accept` and `reject: <reason>, then
WHEN ... THEN ... to set the check`. Hold questions are unchanged.

#### Scenario: SCN-VER-211 (+) A finding question says how to set the check
- **GIVEN** a round that ends NEEDS_HUMAN on a judge-only major finding on criterion C, not a spec gap
- **WHEN** its verdict question is raised
- **THEN** its context says `your reason comes first in it` and `Without one, the fix is checked against criterion C as
  it is written.`, does not mention a suggested fix being unused, and its second option is `reject: <reason>, then WHEN
  ... THEN ... to set the check`

#### Scenario: SCN-VER-212 (+) A spec-gap question says the suggestion is the code as it is
- **GIVEN** a judge-only major spec-gap finding on C with a suggested fix
- **WHEN** its verdict question is raised
- **THEN** its context shows the suggested fix and says `The suggested fix describes what the code does now, and a
  reject does not use it: to pin that behaviour, end the reason with it.`

#### Scenario: SCN-VER-213 (−) A finding question with no criterion says the sentence is needed
- **GIVEN** a judge-only major finding that cites no criterion
- **WHEN** its verdict question is raised
- **THEN** its context says `This finding cites no criterion: end the reason with one sentence WHEN <the situation> THEN
  <the behaviour you expect>, with WHEN and THEN in capitals, or no fix can be made from the reject.` and does not say
  `Without one, the fix is checked against`

#### Scenario: SCN-VER-214 (+) A criterion question says the same of its scenario
- **GIVEN** a criterion that is `needs_human` after a round
- **WHEN** its verdict question is raised
- **THEN** its context says `Without one, the fix is checked against the scenario above as it is written.`, no longer
  says `If the code is right and the scenarios are incomplete`, and its second option is `reject: <reason>, then WHEN
  ... THEN ... to set the check`
