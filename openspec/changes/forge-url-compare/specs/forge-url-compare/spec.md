## Purpose

The guarded merge recognises the unit's own pull request whether its link is stored with the forge host or with
`<forge>`.

## ADDED Requirements

### Requirement: L4-OBS-002 The guarded merge compares links in both forms
When the guarded merge (L4-YOLO-008) finds the open pull request of a unit's branch, it SHALL compare the forge's link
with the unit's stored link after both are scrubbed of the forge host (`canonical`), and SHALL log that the pull request
is not the unit's only when they differ.

#### Scenario: SCN-YOLO-239 (+) a stored `<forge>` link is the unit's pull request
- **WHEN** a unit's stored link is `<forge>/o/r/pull/7` and the forge finds `https://forge.invalid/o/r/pull/7` open for
  the unit's branch
- **THEN** the merge logs no line that the pull request is not the unit's; with a stored `<forge>/o/r/pull/8` it does
