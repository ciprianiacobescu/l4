## Purpose

A finding a person rejects with a scenario becomes a fix task, whatever requirement it would belong to.

## ADDED Requirements

### Requirement: L4-VER-006 A rejected finding's scenario always has a requirement
When a person rejected a finding that cites no criterion with a `WHEN … THEN …` and the parent has several
requirements, the fix-unit planner SHALL put the scenario under an ADDED requirement of its own,
`<finding title> — finding <id>`, in the parent's first capability by name, and the finding SHALL get a red/green
task. A judge's spec-gap suggestion that no person rejected SHALL keep the rule that it needs the cited criterion's
requirement or the parent's only one.

#### Scenario: SCN-VER-76 (+) A rejected finding with no criterion gets a requirement of its own
- **GIVEN** a parent with three requirements in two capabilities, and the major finding `task 2.3 is ticked as already
  satisfied, but its text is not done` (no criterion) that a person rejected in Q-007 with a `WHEN … THEN …`
- **WHEN** the fix unit is planned
- **THEN** it has one task for the finding, the ADDED requirement `<finding title> — finding <id>` in the first
  capability by name holds the scenario, Q-007 is consumed, and nothing is left not converted

#### Scenario: SCN-VER-77 (−) A judge's spec gap with no criterion still needs one requirement
- **GIVEN** a PASS with `verifier.fix_minor_findings` on, a parent with two requirements, and a judge's minor spec-gap
  finding with no criterion that no person rejected
- **WHEN** the fix unit is planned
- **THEN** it has no task, and the finding is listed as not converted
