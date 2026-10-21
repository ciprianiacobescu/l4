# Answer accepted findings: a resumed round keeps the judge's answers, a reply that leaves one out is asked again, and a person can waive a finding

Status: design, 2026-10-17. Harness at 0.4.6. Markers: **[V]** verified in the code or in the recorded ledger,
**[I]** inferred, **[G]** a chosen form.

## 0. The answer in six lines

1. A round resumed at aggregation records no `review.accepted_judged`, and the fold reads only the PASS round's rows,
   so a unit whose PASS came from an accepted hold never merges by itself (1.1) [V].
2. `_resume` records the reused round's rows again with the new round's number (D1).
3. A valid reply that leaves out an asked accepted or feedback id gets the second call of the judge run (D2).
4. A second reply that is not valid keeps the first verdict (D2).
5. `l4 yolo waive` records an audited waiver; the merge gate counts a waived finding as answered (D3).
6. The `Next:` line of a plan waiting with `accepted_finding_open` names retry, feedback and waive (D4).

## 1. Current state

### 1.1 Why the plan waits for good [V]

The ledger of the consumer repository's unit, rounds 1 to 7:

| round | verdict | `review.accepted_judged` rows |
|---|---|---|
| 1 | NEEDS_HUMAN (diff hold) | 5, all `not answered` |
| 4 | FAIL | 5: four `addressed: true`, one `false` with evidence |
| 6 | NEEDS_HUMAN (diff hold) | 5, all `not answered` |
| 7 | PASS (the hold accepted, steps 0-9 reused) | none |

- `_settle_accepted` (`src/l4/state/fold.py`) keeps the rows whose `round` is the PASS round's. Round 7 has none, so
  `accepted_addressed` and `accepted_evidence` are empty and the wait detail says `no answer recorded` for each id.
- `_resume` (`src/l4/verifier/ladder.py`) sets `result.feedback_outcomes = judged_outcomes(events, prev_round)`
  ("the judge check is not stored"), and records nothing for the accepted findings.
- The judge's reply in rounds 1 and 6 had no `accepted` list. `JudgeVerdict.accepted` is optional, so `_classify`
  calls the reply valid and `run_judge` stops after one call.
- The production files the findings are about are inside the first 120000 characters of the diff in both rounds
  (they end near character 93000), so the judge could see them. Round 4's diff was cut too, and that judge answered.

### 1.2 What a person can do today [V]

The runbook row for `accepted_finding_open`: run `l4 retry`, or merge the pull request yourself. A retry runs a new
round; when the judge finds a finding not addressed, the answer comes back the same. A merge by hand bypasses the
guarded merge (L4-YOLO-009) and records no reason in the plan ledger.

## 2. Decisions

### D1. A resumed round records the answers it relies on [G]

`_resume` reads the `review.accepted_judged` rows of the reused round (`prev.round`) from the ledger and records each
again: `review.accepted_judged{id, round: <new>, addressed, evidence, profile, reused_from: <prev>}`. The fold needs
no change. The rows are in the ledger before the round's `verify.verdict`, as in a fresh round. A reused round with
no rows (its judge step did not run, or it predates L4-YOLO-028) carries none: the wait says `no answer recorded`,
which is true.

Rejected: settling on "the latest round that has rows" in the fold. It would also read a FAIL round's rows for a later
PASS on other code.

### D2. A reply that leaves out an asked id is asked once more [G]

`JudgePrompt` carries the ids it asks for: `accepted_ids` and `feedback_ids`. After a valid reply, `run_judge`
computes the ids the reply does not answer. When some are missing and the run has a call left, it sends the first
prompt, the judge's own reply (redacted, cut as for a schema repair) and one message:

`Your reply left out the answers for these ids: accepted F-…, …; feedback FB-…. Reply again with the complete JSON
object, with one entry per id in accepted and in feedback.`

- A valid second reply is the verdict, `reply: retried`. Ids it still leaves out are `not answered`, as today.
- A second reply that is not valid, or a call that times out or errs, keeps the first verdict, `reply: valid` (or
  `repaired`). A valid verdict is never dropped for a missing evidence answer.
- A usage limit on the second call raises `RoleLimit`, as on any call.
- The cost and the calls of both calls add up.

Rejected: a schema with `accepted` and `feedback` required. The schema is shared by every backend and prompt
contract, and a missing list is not a broken reply: the criteria verdicts in it are good.

### D3. `l4 yolo waive` [G]

`l4 yolo waive PLAN FINDING --reason TEXT [--withdraw] [--yes] [--no-run]`:

- The plan must be `active`, `waiting` or `stopped`. Before activation, the accepted findings are not frozen yet, and
  `l4 yolo accept` is the command. A final plan is refused.
- `FINDING` must be the id of a finding of the activation's accepted items (`activated_accepted`), else exit 2 with
  the ids it has.
- A person sees the finding (id, criterion, severity, text, the acceptance's reason) and types the plan id. An agent
  needs `yolo.review.accept_by_agents: true` in `.l4/config.yaml` at `origin/<base>` and `--yes`, as for accept.
- It records `plan.finding_waived{finding, subject, reason, by, actor, marker}`; `--withdraw` records
  `plan.waiver_withdrawn{finding, reason, by, actor}` (never refused for the actor, as for accept). Both are pushed
  with the lease.
- Then it starts the harness's CI on the base branch, unless `--no-run`.

The fold keeps `PlanState.waived: finding -> data`. `_accepted_open` leaves out waived ids, so the wait's cause is
gone and the plan goes on: the next step merges through `merge_guarded`. The report shows `waived by <by> (<actor>):
<reason>` for a finding the verifier did not answer `addressed: true`.

Why a waiver is the right way out: an acceptance whose reason gives no handling for a finding cannot be judged
"handled as the reason says". The person who can decide it gets a command that keeps the merge in the harness and
the decision in the plan ledger.

### D4. The wait names its ways out [G]

`_next_line` for `waiting` with `accepted_finding_open` (the current unit U):

`the verifier did not answer every accepted finding of U with addressed: true (l4 yolo report PLAN): when it gave no
answer, l4 retry --unit U --reason TEXT; when the code must change, l4 feedback add --unit U ... then l4 retry --unit
U --reason TEXT; when a finding needs no handling, l4 yolo waive PLAN F-… --reason TEXT`

## 3. Risks

- A second judge call costs money. It happens only when a reply leaves out an asked id, which is a broken answer.
- A waiver by an agent: the same switch as accept (`accept_by_agents`), at the base branch, so a person set it.
- The consumer repository's ledger needs no repair: after the upgrade, `l4 retry` runs a fresh round with D2 [I].
