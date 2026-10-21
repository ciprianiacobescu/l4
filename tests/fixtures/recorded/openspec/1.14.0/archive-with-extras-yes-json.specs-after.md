# openspec/specs/audit/spec.md after: openspec archive with-extras --yes --json; then find of the archived folder
# audit Specification

## Purpose
The audit capability records one line per greeting so that operators can count CLI usage.

## Requirements

### Requirement: Audit line
The system SHALL append one line per greeting to `audit.log`.

#### Scenario: One greeting, one line
- **WHEN** the user runs `greet Ada`
- **THEN** `audit.log` gains exactly one line
## ---- find openspec/changes/archive -type f
openspec/changes/archive/.gitkeep
openspec/changes/archive/2026-10-03-with-extras/.l4/state.json
openspec/changes/archive/2026-10-03-with-extras/.openspec.yaml
openspec/changes/archive/2026-10-03-with-extras/evidence/round-1/junit.xml
openspec/changes/archive/2026-10-03-with-extras/proposal.md
openspec/changes/archive/2026-10-03-with-extras/questions.md
openspec/changes/archive/2026-10-03-with-extras/specs/audit/spec.md
openspec/changes/archive/2026-10-03-with-extras/tasks.md
openspec/changes/archive/2026-10-03-with-extras/verification.md
