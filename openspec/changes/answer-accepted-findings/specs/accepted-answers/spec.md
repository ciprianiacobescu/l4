## Purpose

The judge's answers to the accepted findings and the feedback items reach the round that decides the merge: a round
resumed at aggregation keeps them, and a reply that leaves one out is asked once more.

## ADDED Requirements

### Requirement: L4-VER-017 The judge's evidence answers survive a resumed round and a reply that leaves one out
When a round resumes at aggregation (D4), the ladder SHALL record each `review.accepted_judged` row of the reused round
again, with the new round's number and `reused_from` set to the reused round. A reused round with no such row SHALL
carry none.

When the judge prompt has an accepted block or a feedback block and a valid reply leaves out an id of a block, the
judge run SHALL make one more call, within its at most two calls. The call SHALL send the first prompt, the judge's
own reply and a message that names each missing id. A valid second reply SHALL be the verdict, with `reply: retried`.
A second reply that is not valid, or a second call that fails without a usage limit, SHALL keep the first verdict.
An id that no kept reply answers SHALL be recorded as not answered, as before.

#### Scenario: SCN-VER-68 (+) A resumed round carries the accepted answers
- **GIVEN** a unit whose round 1 ended NEEDS_HUMAN with `review.accepted_judged{id: F-0a1b2c, round: 1, addressed: true}`
- **WHEN** round 2 resumes at aggregation
- **THEN** the ledger holds `review.accepted_judged{id: F-0a1b2c, round: 2, addressed: true, reused_from: 1}` and the judge is not called

#### Scenario: SCN-VER-69 (+) A reply that leaves out an accepted id is asked once more
- **GIVEN** a judge prompt with the accepted ids F-0a1b2c and F-3d4e5f and a valid first reply that answers only F-0a1b2c
- **WHEN** the judge run goes on
- **THEN** a second call names F-3d4e5f, its valid reply is the verdict with `reply: retried`, and both ids are recorded with the second reply's answers

#### Scenario: SCN-VER-70 (−) A broken second reply keeps the first verdict
- **GIVEN** the first reply of SCN-VER-69 and a second reply that is not valid
- **WHEN** the judge run ends
- **THEN** the verdict is the first reply's, the run made two calls, and F-3d4e5f is recorded as not answered

#### Scenario: SCN-VER-71 (+) A feedback id left out is asked for too, and a complete reply is one call
- **GIVEN** a prompt with the feedback item FB-001, a first reply without `feedback`, and in turn a first reply that answers every asked id
- **WHEN** the judge runs
- **THEN** the first makes a second call that names FB-001; the second makes one call
