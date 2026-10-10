## Purpose

Defines stable acceptance-criterion IDs, how tests trace them, and the orphan-ID check, so that every criterion can be tied to discriminating test evidence (SPEC §4.7).

## ADDED Requirements

### Requirement: L4-CRT-001 (part a) Stable criterion ID formula
Every acceptance criterion MUST get an ID `C-<8 lowercase hex>` equal to `sha256("<framework>|<capability-or-spec>|<requirement title>|<scenario title or criterion text>")[:8]` over whitespace-normalised components. Kiro MUST use the criterion's normalised text, not its number, so inserting a criterion does not shift other IDs. Each criterion also gets a human alias.

#### Scenario: SCN-CRT-05 (+) Inserting a Kiro criterion does not shift IDs
- **GIVEN** Kiro requirement 2 with criteria 2.1–2.3, tests tagged with their IDs
- **WHEN** a human inserts a new criterion between 2.1 and 2.2 (renumbering the later ones)
- **THEN** the IDs of the existing criteria are unchanged (only their aliases change); the new criterion gets a new ID.

#### Scenario: SCN-CRT-N6 (−) Editing a scenario title changes only that ID
- **GIVEN** an OpenSpec capability with three scenarios and their IDs recorded
- **WHEN** one scenario title is edited
- **THEN** exactly that scenario's ID differs; the other two are unchanged and still match `^C-[0-9a-f]{8}$`.

### Requirement: L4-CRT-001 (part b) criteria.json on every intake
IDs and aliases MUST be written to `<unit>/.l4/criteria.json` on every intake, with a deterministic key order and no timestamps, so an unchanged spec yields a byte-identical file. OpenSpec aliases read `capability › Requirement › Scenario`; Kiro aliases read `Req 2.3`.

#### Scenario: SCN-CRT-01 (+) Stable criterion IDs
- **GIVEN** an unchanged spec across two runs
- **WHEN** intake runs twice
- **THEN** `.l4/criteria.json` is byte-identical and IDs match `^C-[0-9a-f]{8}$`.

#### Scenario: SCN-CRT-N7 (−) A unit without criteria yields an empty list, not a missing file
- **GIVEN** an OpenSpec change that has `tasks.md` but no scenarios
- **WHEN** intake runs
- **THEN** `.l4/criteria.json` is written with an empty criteria list and doctor SPEC-004 warns "unit has no criteria".

### Requirement: L4-CRT-002 Tracing conventions
A test MUST trace a criterion only when the literal ID appears in its reported name, title, tag or marker argument. Accepted conventions: Playwright `@C-…` in the title or `tag`; pytest `@pytest.mark.l4("C-…")` or the ID in the test name; any JUnit-producing framework with the ID in the test case name. An ID elsewhere in the test body MUST NOT trace.

#### Scenario: SCN-CRT-03 (+) All tagging conventions trace
- **GIVEN** a Playwright test with `tag: '@C-1a2b3c4d'`, a pytest test with `@pytest.mark.l4("C-1a2b3c4d")` and a Go test named `TestLogin_C-1a2b3c4d`
- **WHEN** reports are joined
- **THEN** all three trace `C-1a2b3c4d`.

#### Scenario: SCN-CRT-04 (−) An ID in a code comment does not trace
- **GIVEN** a test whose body contains `// covers C-1a2b3c4d` but whose name/tags do not
- **WHEN** reports are joined
- **THEN** it does not trace the criterion.

### Requirement: L4-CRT-003 Orphan criterion IDs
`doctor` MUST report orphan IDs, meaning IDs found in tests but absent from every active or archived unit, as check `SPEC-005` with severity warning.

#### Scenario: SCN-CRT-02 (−) Renamed scenario orphans old tags
- **GIVEN** scenario "Valid login" renamed to "Successful login" after tests were tagged with the old ID
- **WHEN** doctor and verifier run
- **THEN** SPEC-005 warns about the orphan ID; the renamed criterion is *uncovered* until a test carries its new ID.
