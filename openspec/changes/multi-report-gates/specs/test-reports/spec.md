## Purpose

A test gate that runs several suites is judged on all of them.

## ADDED Requirements

### Requirement: L4-GAT-005 A test gate reads every report it lists
Every report in `gates.test.reports` SHALL exist after the gate's run, or the gate SHALL fail with
`report missing: <the first missing report>`. The harness SHALL merge the reports into one report: a test id that more
than one report holds SHALL keep the worse result, in the order error, failed, passed, skipped, and the collection
errors of every report SHALL be kept, each once. A gate with one report SHALL read it as before.

#### Scenario: SCN-GAT-05 (+) Two reports are read as one
- **GIVEN** a test gate whose command writes `.l4-out/a.xml` and `.l4-out/b.xml`, one passing test each, and lists both
- **WHEN** the gate runs
- **THEN** it passes and its report holds both tests

#### Scenario: SCN-GAT-06 (−) A listed report that is missing fails the gate
- **GIVEN** the gate of SCN-GAT-05 whose command writes only `.l4-out/a.xml`
- **WHEN** the gate runs
- **THEN** it fails with `report missing: .l4-out/b.xml`

#### Scenario: SCN-GAT-07 (−) A test in two reports keeps its worse result
- **GIVEN** two reports that both hold `tests.test_a::test_one`, passed in one and failed in the other
- **WHEN** the gate runs
- **THEN** the merged report has that test `failed`
