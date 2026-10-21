## Purpose

Defines the native Kiro provider: Kiro's task grammar, dependency waves, EARS criteria with requirement links, harness-side validate and archive, and bugfix-spec fix units, because Kiro ships no spec CLI (SPEC §4.5).

## ADDED Requirements

### Requirement: L4-KSP-001 (part a) Kiro task line grammar
Task parsing MUST use Kiro's parser regex `^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$` [V, Kiro IDE 1.2.4 bundle]. Markers are `' '` not started, `-` in progress, `~` queued, `x`/`X` done. Ordered-list bullets and empty brackets are not tasks.

#### Scenario: SCN-TMW-03 (−) A space before `*` is not optional
- **GIVEN** `- [ ] * 1.2 Write docs`
- **WHEN** parsed
- **THEN** 1.2 is a required leaf (title `* 1.2 Write docs`), consistent with Kiro's regex.

#### Scenario: SCN-KSP-N1 (−) Ordered bullets and empty brackets are not Kiro tasks
- **GIVEN** a Kiro `tasks.md` with `1. [ ] Draft`, `- [] Review` and `- [ ] 3.1 Ship`
- **WHEN** parsed
- **THEN** only 3.1 is a task.

### Requirement: L4-KSP-001 (part b) Optional tasks, hierarchy, parents
An optional task is marked by `*` immediately after `]`. Hierarchy MUST follow the dotted number when any task is numbered, else indentation. Only leaves are executed. A parent MUST close when all its non-optional children are done and MUST NOT be closed while a non-optional child is open.

#### Scenario: SCN-TMW-02 (+) Optional Kiro leaves are skipped and do not block parents
- **GIVEN** parent `2.` with children `2.1` (required) and `2.2*` (optional)
- **WHEN** 2.1 is done
- **THEN** `2.` is closed `[x]`, 2.2 stays `[ ]`, no `[-]` was ever written on `2.`.

#### Scenario: SCN-KSP-N2 (−) Parent cannot be closed over an open required child
- **GIVEN** parent `3.` with required children `3.1` done and `3.2` not started
- **WHEN** `set_marker(unit, "3", Marker.DONE)` is called
- **THEN** `ParentHasOpenChildren` is raised naming 3.2 and the file is unchanged.

### Requirement: L4-KSP-002 Dependency order from waves
Dependency order MUST come from the `## Task Dependency Graph` JSON block (`waves`) when present and valid: a task depends on every task in earlier waves. Otherwise document order applies. Pending leaves missing from the graph MUST be inserted at their document position.

#### Scenario: SCN-KSP-N3 (−) Invalid graph falls back to document order
- **GIVEN** a `## Task Dependency Graph` block whose JSON does not parse
- **WHEN** `tasks(unit)` is ordered
- **THEN** leaves are in document order and a `warnings` entry names the invalid block.

#### Scenario: SCN-KSP-N4 (−) Leaf missing from the graph is not dropped
- **GIVEN** a valid graph that omits pending leaf 2.4
- **WHEN** `tasks(unit)` is ordered
- **THEN** 2.4 appears at its document position between its neighbours.

### Requirement: L4-KSP-003 Criteria and requirement links
Criteria MUST come from `requirements.md` (EARS acceptance criteria, numbered per requirement) or `bugfix.md`; task-to-criterion links MUST come from `_Requirements: 2.1, 3.3_` lines. A leaf task without a requirements reference MUST be reported by doctor as `SPEC-004` and, under `sdd.enforce`, block intake unless the task kind is TDD-exempt.

#### Scenario: SCN-KSP-N5 (−) Leaf without _Requirements_ blocks intake under enforce
- **GIVEN** `sdd.enforce: true` and a Kiro leaf 1.2 with no `_Requirements:_` line and no exempt tag
- **WHEN** intake and `l4 doctor` run
- **THEN** SPEC-004 lists 1.2 and the unit is rejected; the same leaf tagged `[docs]` passes.

#### Scenario: SCN-KSP-N6 (−) Dangling requirement reference
- **GIVEN** a task citing `_Requirements: 9.9_` and no criterion 9.9
- **WHEN** `validate(unit)` runs
- **THEN** the report is invalid and names task and reference.

### Requirement: L4-KSP-004 Harness-side validate and archive
Because Kiro has no validate or archive command [V], `validate()` MUST check file presence, task grammar, graph JSON and that requirement references resolve. `archive()` MUST record `archived` in state and, when `kiro.archive_dir` is configured, move the spec folder there.

#### Scenario: SCN-KSP-N7 (−) Missing tasks.md fails validation
- **GIVEN** `.kiro/specs/x/` with `requirements.md` and `design.md` only
- **WHEN** `validate(unit)` runs
- **THEN** the report is invalid with an issue "tasks.md missing".

#### Scenario: SCN-KSP-N8 (+) Archive without archive_dir only records state
- **GIVEN** `kiro.archive_dir: null` and a done unit
- **WHEN** `archive(unit)` runs
- **THEN** the folder stays in place and `ArchiveReport.moved_to` is null.

### Requirement: L4-KSP-005 Kiro bugfix fix units
Fix units MUST be Kiro bugfix specs: `bugfix.md`, `design.md`, `tasks.md` and `.config.kiro` `{"specId": <uuid4>, "workflowType": "requirements-first", "specType": "bugfix"}`. The `workflowType` value for bugfix specs is [I] and MUST be confirmed against a Kiro-created bugfix spec.

#### Scenario: SCN-KSP-N9 (−) A fix unit is not a feature spec
- **GIVEN** parent Kiro spec `user-auth` and findings
- **WHEN** `create_fix_unit(parent, 1, findings, None)` runs
- **THEN** `.kiro/specs/user-auth-fix-1/` has `bugfix.md`, `design.md`, `tasks.md`, `.config.kiro` with `specType: bugfix` and no `requirements.md`.
