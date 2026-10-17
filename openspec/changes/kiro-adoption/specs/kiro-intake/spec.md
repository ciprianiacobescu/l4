## Purpose

A repository that adopts L4 with finished Kiro specs keeps them as history: L4 validates the work it may run, and reads
the common forms of requirements and references.

## ADDED Requirements

### Requirement: L4-KSP-006 Finished Kiro history is read, not validated as work
A done leaf whose `_Requirements:_` line is missing or names no criterion SHALL be a WARNING, not an ERROR, whatever
`sdd.enforce` says; a pending leaf SHALL keep the rule of L4-KSP-003. A `## Task Dependency Graph` whose block is not
JSON SHALL be a WARNING and the tasks SHALL run in document order; a JSON graph with an unknown key or a cycle SHALL stay
an ERROR. A reference `N` SHALL resolve when requirement `N` has criteria. A requirement SHALL be read under
`## Requirement N` with `### Acceptance Criteria` as under `### Requirement N` with `#### Acceptance Criteria`. A number
on a `_Requirements:_` line SHALL be a reference only when it stands alone, not inside a word such as `ADR-0014.8` or
`AC3`.

#### Scenario: SCN-ODD-10 (+) A finished leaf with no requirement link is a warning
- **GIVEN** a done leaf `- [x] 3.1 Add cache` with no `_Requirements:_` line, under `sdd.enforce`
- **WHEN** the spec is validated
- **THEN** SPEC-002 has a warning for 3.1 and no error, and intake admits the unit

#### Scenario: SCN-ODD-11 (−) A pending leaf with no requirement link is still an error
- **GIVEN** a pending leaf `- [ ] 3.2 Add eviction` with no `_Requirements:_` line, under `sdd.enforce`
- **WHEN** intake runs
- **THEN** it is rejected (14) with `task 3.2 cites no requirement`

#### Scenario: SCN-ODD-12 (+) A mermaid dependency graph falls back to document order
- **GIVEN** a `## Task Dependency Graph` whose block is ```` ```mermaid ````
- **WHEN** the spec is validated and its tasks are read
- **THEN** there is a warning and no error, and the tasks are in document order

#### Scenario: SCN-ODD-13 (+) A whole-requirement reference resolves
- **GIVEN** requirement 1 with criteria 1.1 and 1.2, and a pending leaf with `_Requirements: 1_`
- **WHEN** the spec is validated
- **THEN** the reference resolves, and the task cites C(1.1) and C(1.2)

#### Scenario: SCN-ODD-14 (+) A requirement one heading level higher is read
- **GIVEN** `requirements.md` with `## Requirement 1: Login` and `### Acceptance Criteria` holding two criteria
- **WHEN** its criteria are read
- **THEN** there are two, `Req 1.1` and `Req 1.2`

#### Scenario: SCN-ODD-15 (−) A number inside a word is not a reference
- **GIVEN** `_Requirements: 2.1, ADR-0014.8, Req 1 AC3_`
- **WHEN** the line is read
- **THEN** the references are `2.1` and `1`
