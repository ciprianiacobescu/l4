## ADDED Requirements

### Requirement: L4-VER-067 An accepted UI criterion is not held again
UI test generation (step 5) SHALL NOT call the writer for, and SHALL NOT raise a hold on, a UI criterion whose accept
is in force: an accept of the criterion itself, or of a UI hold of the criterion, while the criterion's text and its
tracing-test files are those the accept saw, no later reject or void was recorded, and no tracing test fails. It SHALL
record `verify.generated{status: "waived", by}`. A UI hold's text SHALL NOT name the generator's status.

#### Scenario: SCN-VER-247 (+) an accepted criterion verdict waives step 5
- **WHEN** a person accepted a verdict question on UI criterion C-1 and its text is unchanged
- **THEN** the next round records `verify.generated{criterion: C-1, status: waived}`, calls no writer and raises no hold

#### Scenario: SCN-VER-248 (+) an accepted UI hold waives a later gap of another status
- **WHEN** H-a (`fails_at_head` in round 1) was accepted, and in round 3 the generator would report `not_testable`
- **THEN** no new hold is raised for C-1

#### Scenario: SCN-VER-249 (+) an accept written before this change is found by its title
- **WHEN** the ledger holds an accepted `Hold H-…: UI criterion C-1 has no end-to-end test (fails_at_head)…` question
- **THEN** C-1 is waived

#### Scenario: SCN-VER-250 (−) a changed criterion or tracing test ends the waiver
- **WHEN** C-1's text changed, or a file of its tracing tests changed, since the accept
- **THEN** step 5 runs for C-1 as before

#### Scenario: SCN-VER-251 (−) a reject, a void or a failing tracing test is not waived
- **WHEN** the hold was rejected, or the accept was voided, or a tracing test of C-1 fails this round
- **THEN** step 5 runs for C-1 as before

#### Scenario: SCN-VER-252 (+) the hold's id stays the same across statuses
- **WHEN** C-1 has no e2e test with status `fails_at_head` in one round and `uncollectable` in the next, nothing accepted
- **THEN** both rounds raise the same hold id
