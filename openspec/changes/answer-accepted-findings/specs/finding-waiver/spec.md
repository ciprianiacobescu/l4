## Purpose

A person can decide on record that an accepted finding needs no handling, so a plan that waits with
`accepted_finding_open` goes on and the harness merges the unit itself.

## ADDED Requirements

### Requirement: L4-YOLO-031 A person can waive an accepted finding, audited
`l4 yolo waive PLAN FINDING --reason TEXT [--withdraw] [--yes] [--no-run]` SHALL record
`plan.finding_waived{finding, subject, reason, by, actor, marker}` in the plan ledger, pushed with the lease, then start
the harness's CI on the base branch unless `--no-run`. It MUST be refused, with nothing recorded, for a plan that is not
`active`, `waiting` or `stopped`, for an id that is not a finding of the activation's accepted items, for an empty
reason, and for an agent unless `yolo.review.accept_by_agents` is true at `origin/<base>` and `--yes` is given. A
person MUST type the plan id after the finding is shown. `--withdraw` SHALL record `plan.waiver_withdrawn{finding,
reason, by, actor}` for a waived id. With `merge: auto`, the merge gate of L4-YOLO-028 SHALL count a waived finding as
answered. The report SHALL show `waived by <by> (<actor>): <reason>` for a waived finding the verifier did not answer
`addressed: true`. For a plan waiting with `accepted_finding_open`, the `Next:` line of `l4 yolo status` SHALL name
`l4 retry`, `l4 feedback add` and `l4 yolo waive`.

#### Scenario: SCN-YOLO-73 (+) A waived finding lets the harness merge the unit
- **GIVEN** an active `merge: auto` plan whose current unit is in review with a PASS and one accepted finding F-1 answered `addressed: false`, and the plan waits with `accepted_finding_open`
- **WHEN** a person waives F-1 with a reason and the next step runs
- **THEN** the plan ledger holds `plan.finding_waived{finding: F-1, reason, by, actor: person}`, the wait ends, and the unit is merged by the harness

#### Scenario: SCN-YOLO-74 (−) A waiver is refused where it does not apply
- **GIVEN** in turn: an id that is not an accepted finding of the activation; a plan not yet activated; an agent at a target without `accept_by_agents`; a person who types another answer than the plan id
- **WHEN** `l4 yolo waive` runs
- **THEN** it exits 2, says why, and records nothing

#### Scenario: SCN-YOLO-75 (+) The wait names its ways out
- **GIVEN** a plan waiting with `accepted_finding_open` on unit U
- **WHEN** `l4 yolo status` prints its `Next:` line
- **THEN** the line names `l4 retry --unit U`, `l4 feedback add --unit U` and `l4 yolo waive`
