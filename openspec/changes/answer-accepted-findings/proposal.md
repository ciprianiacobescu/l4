## Why

A plan on a consumer repository waited for good after its unit passed (seen on 0.4.6). The plan was activated with
five accepted review findings for the unit (L4-YOLO-028). With `merge: auto`, the unit merges only when the judge of
its PASS round answers `addressed: true` for each one.

1. **A resumed round drops the judge's answers.** Round 6 ended NEEDS_HUMAN on a hold ("the diff is longer than 120000
   characters"). The person accepted the hold, and round 7 resumed at aggregation (D4): it reused steps 0-9 and called
   no judge. `_resume` (`src/l4/verifier/ladder.py`) carries the judge's feedback answers into the new round
   (`judged_outcomes`), but it does not carry the `review.accepted_judged` rows. The fold settles the accepted
   answers on the rows of the PASS round only (`_settle_accepted`), so round 7 had none. All five findings showed
   `no answer recorded`, and the plan waited with `accepted_finding_open`. A perfect round 6 judge would have left the
   same wait.
2. **The judge left its answers out, and nothing asked again.** In rounds 1 and 6 the judge's reply had no `accepted`
   list, although the prompt held the block and the reply schema has the field. `accepted` is optional in the schema,
   so the reply was valid, and the ladder recorded `not answered` for each finding. In round 6 the same reply answered
   every feedback item. A feedback item left out of a reply has the same cause: it counts as not addressed, and a
   round that could pass fails into a fix unit.
3. **No way out when the judge says no.** The runbook says: run `l4 retry`, or merge the pull request yourself. A retry
   gives the same answer when the judge finds a finding not addressed (round 4 said that for one of the five: the
   person's reason gave no handling for it). The plan then waits until a person merges by hand, outside the harness's
   guarded merge, and the harness records no reason for it.

## What Changes

- **A resumed round carries the accepted answers** (L4-VER-017). When a round resumes at aggregation, the ladder
  records the `review.accepted_judged` rows of the round it reuses again, with the new round's number and
  `reused_from`. The fold is unchanged: the PASS round has its rows.
- **A reply that leaves out an asked answer is asked once more** (L4-VER-017). When the prompt has an accepted or a
  feedback block and a valid reply leaves out an id of it, the judge gets one more call. The call names the missing
  ids and shows the judge its own reply. A valid second reply is the verdict (`reply: retried`). An invalid one keeps
  the first verdict: a valid verdict is never dropped over an evidence answer. An id that is still missing is
  recorded as today (`not answered`). The call counts in the at most two calls of a judge run.
- **A person can waive an accepted finding, audited** (L4-YOLO-031). `l4 yolo waive PLAN FINDING --reason TEXT
  [--withdraw] [--yes] [--no-run]` records `plan.finding_waived` (or `plan.waiver_withdrawn`) in the plan ledger, then
  starts a run. The merge gate counts a waived finding as answered, so the harness merges the unit itself, through its
  guarded merge. The same rules as `l4 yolo accept` decide who may waive: a person types the plan id, an agent needs
  `yolo.review.accept_by_agents: true` at the target and `--yes`. The report and `l4 yolo status` show the waiver.
- **The wait names its ways out.** For a plan that waits with `accepted_finding_open`, the `Next:` line of `l4 yolo
  status` names `l4 retry` (no answer), `l4 feedback add` (the judge says not addressed and the code must change) and
  `l4 yolo waive` (a person decides the finding needs no handling).
- **Docs.** `docs/SPEC.md`, the runbook, `docs/yolo-mode.md`, the skill's `plan.md`, and `CHANGELOG.md`
  (`## 0.4.7 (unreleased)`).

Not in this change:
- a judge that sees a diff longer than 120000 characters in parts (a lesson for a later release);
- a disposition per finding at `l4 yolo accept` time.

## Capabilities

### New Capabilities

- `accepted-answers`: the judge's answers to accepted findings and feedback items survive a resumed round, and a reply
  that leaves one out is asked once more (L4-VER-017).
- `finding-waiver`: `l4 yolo waive` and what the merge gate, the report and the status make of a waiver
  (L4-YOLO-031).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline. `tasks.md` section 4 holds the `docs/SPEC.md` work.
