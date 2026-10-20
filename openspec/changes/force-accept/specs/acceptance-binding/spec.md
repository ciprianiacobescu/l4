## Purpose

A person's acceptance stays bound to the judgement the person saw when the same material has more than one
judgement, an accepted subject is shown as accepted where its verdict is printed, and an acceptance that no longer
holds says why in one line.

## ADDED Requirements

### Requirement: L4-YOLO-065 A reuse keeps the judgement a person accepted
When a review reuses a recorded judgement of a material (the CI step, `l4 yolo review --local`,
`l4 yolo review --worktree` with or without `--record`) and an acceptance of the plan is bound to that material, the
review SHALL reuse the newest recorded judgement of that material whose findings have the acceptance's `findings_sha`,
when the ledger holds one, and otherwise the newest judgement of the material. The binding of L4-YOLO-027 MUST NOT
change: an acceptance holds only on the same material and the same findings.

#### Scenario: SCN-YOLO-173 (+) A reuse keeps the judgement a person accepted
- **GIVEN** a ledger where material M of unit A was judged NEEDS_REVISION with findings F1, a person accepted it, and a
  later `plan.reviewed` holds a second judgement of the same M with findings F2
- **WHEN** a new review runs (the plan file's limits changed, so the plan digest did, and A's material did not) and no
  judge is called
- **THEN** A's entry is the reuse of the F1 judgement (`reused_from` its time), the acceptance holds, and
  `l4 yolo activate` lists it; with no acceptance the newest judgement (F2) is reused as before

### Requirement: L4-YOLO-066 An acceptance says whether it holds, and why not
Where the verdict of an accepted subject is printed (`l4 yolo findings`, `l4 yolo review --worktree`,
`l4 yolo review --local`, the CI review log line) an acceptance that holds SHALL be said on that line, and a reused
entry SHALL show when it was judged. An acceptance that does not hold SHALL be explained in one line in
`l4 yolo status`, `l4 yolo findings` (text and `--json`) and the activation refusal: `other material` or `other
findings of the same material`, the accepted material and findings (8 characters each) and when they were judged, the
latest review's material and findings, when they were judged and whether they were `reused` or `new`, and for other
material whether the subject's own spec changed.

#### Scenario: SCN-YOLO-174 (−) Other findings of the same material are named as such
- **GIVEN** an acceptance of A bound to material M with findings F1 on the ledger, and a dry run
  `l4 yolo review p1 --worktree --fresh openspec:add-greeting` whose judge returns F3 for the same M
- **WHEN** the dry run prints A, and then a person commits and runs `l4 yolo review p1 --worktree --record`
- **THEN** the dry run's line says `no longer holds: it was for other findings of the same material: accepted findings
  <f8 of F1> …; the latest review shows findings <f8 of F3> judged <t> (new)`, never `the material changed`; the
  recorded review reuses F1 from the ledger (the local cache is not read) and the acceptance holds

#### Scenario: SCN-YOLO-175 (+) An accepted subject is shown as accepted where its verdict is printed
- **GIVEN** an acceptance of A that holds on the latest review, where A is NEEDS_REVISION and reused
- **WHEN** `l4 yolo findings p1`, `l4 yolo review p1 --worktree` and `l4 yolo review p1 --local` run
- **THEN** A's line in each says `accepted by <by>: it does not stop the activation`, the findings view has
  `reused: judged <t> on the same material`, the worktree line has `(reused), judged <t>`, and the `--local` review's
  `Next:` line names `l4 yolo activate` when every other subject is READY
