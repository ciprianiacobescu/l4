## ADDED Requirements

### Requirement: L4-YOLO-095 The plan review has a judge chain of its own
The readiness review (L4-YOLO-004: the CI step,
`l4 yolo review --local` and `--worktree`) SHALL ask the profiles of `roles.plan_judges` when that list is not empty, and
else those of `roles.judges`: that list is the review's chain. A list in `roles.plan_judges` SHALL replace `roles.judges`
for the review only; the profiles of `roles.judges` SHALL NOT follow it, and unit verification (step 9 and every other
reader of `roles.judges`) SHALL be unchanged. `roles.plan_judges` SHALL default to an empty list, so a configuration
without the key loads and reviews as before. It SHALL be a judge role: an adapter profile in it whose adapter cannot judge
SHALL fail the load (L4-CFG-006), a name that is not a defined profile SHALL be a CFG-002 failure, its `kiro-cli`
profiles SHALL be in CFG-011, ENV-004 SHALL warn for a profile of it whose CLI is unusable, `l4 doctor --live` SHALL probe
it when it is not empty (a failure is a warning), `l4 probe --role plan_judges` SHALL probe it, and the skill's
`yolo_preflight.py` SHALL count it among the judge roles. It SHALL be an optional role (L4-AVL-010) with no degradation
of its own, since an empty list means `roles.judges`. A judge of the review SHALL keep the rules it has today: a
tool-less call in an empty folder in the agent sandbox, and no independence rule, since a plan has no implementer to be
independent of. [V, the code: the review selects `roles.judges` (`readiness.ROLE`), so a consumer that wants another
judge first for its plan review must reorder the judges of its running units too.]

#### Scenario: SCN-YOLO-261 (+) The plan review asks its own chain · L4-YOLO-095
- **Given** profiles `j-unit` and `j-plan`, `roles.judges: [j-unit]` and `roles.plan_judges: [j-plan]`
- **When** the CI step reviews a plan of one unit, and the verifier selects the judge of a unit
- **Then** the review's call is made with `j-plan` and the unit's entry holds `judge: j-plan`; the verifier selects
  `j-unit`

#### Scenario: SCN-YOLO-262 (−) Without the key the review asks roles.judges, and a wrong profile is refused · L4-YOLO-095, L4-CFG-006
- **Given** a configuration without `roles.plan_judges`; one with `roles.plan_judges: []`; one whose
  `roles.plan_judges` names a `command` profile; and one whose `roles.plan_judges` names a profile that is not defined
- **When** each is loaded, and the first two review a plan, and `l4 doctor` runs on the last
- **Then** the first two review with the profiles of `roles.judges`; the third does not load, with `profiles.<name> is
  in roles.plan_judges, but its adapter command cannot judge`; the last loads, and CFG-002 fails naming
  `roles.plan_judges`

### Requirement: L4-YOLO-096 A subject a judge could not answer goes to the next judge of the chain, and what was answered stays
The review SHALL ask each subject (a unit, a batch) and each part of a batch reviewed in parts (L4-YOLO-098), called a
call below, of the first judge of the review's chain that is usable and not discarded for that call, in chain order. It
SHALL keep the verdict of every call a judge answered, so a later judge is asked only what is left, and a review that
finishes SHALL be recorded once, as one `plan.reviewed`. A judge SHALL be usable when the factory's selection succeeds
for that one profile (its probes, cool-down, `serves` and login gate, as `Factory.for_role` checks each profile) and
its sandbox can be made; one that is not usable SHALL be skipped for the rest of the review, as a failure of kind
`unusable` with its probe step and reason, or `sandbox` with the `SandboxUnavailable` text. When every judge of the chain is refused its sandbox, the review SHALL
exit 3 with the refusal (L4-YOLO-026, SCN-YOLO-61); a review that ended for the job's time or on a
timeout, or that answered anything, has a judge it could use and SHALL be incomplete (L4-YOLO-099), not that refusal.
After a call of a judge:
`error` without a length stop SHALL discard the judge for the rest of the review (kind `error`); `error` with a length
stop (`StructuredResult.length_stop`) of a call that is not split (L4-YOLO-098) SHALL discard the judge for that call
only (kind `length`); `schema_invalid` after the one repair prompt SHALL discard the judge for that call only (kind
`schema_invalid`); a usage limit or a lost login (`limit`) SHALL cool the profile down as for any role
(`Factory.cool_limited`, L4-AVL-003) and discard it for the rest of the review (kind `limit`); a timeout follows
L4-YOLO-097. Each discard SHALL be followed by the next judge for the same call. When no judge is left for a call and
the reply of a judge to it broke the schema, its verdict SHALL be BLOCKED with the harness finding `schema_invalid`
(L4-YOLO-004, so a chain of one judge gives today's verdict), and the review goes on with the next call; when no judge
is left and none broke the schema on it, the call has no answer and the review does not finish (L4-YOLO-099, reason
`no_judge`). The judges that failed a call of the same material key (kinds `error`, `length`, `schema_invalid` and
`timeout`) in a `plan.review_incomplete` recorded after the plan's latest `plan.reviewed` SHALL be asked that call after
the other judges of the chain, in chain order among themselves, so the next run does not start with the judge that
failed it; the ledger is that memory, since the runner cache may be new in every CI job. Every entry a judge answered
SHALL name it (`judge`); `plan.reviewed` SHALL carry `judge` (the first profile that answered, as before), `judges` (the
distinct profiles that answered in this review, in the order they first answered: not those of a reused entry or of a
reused part of a batch) and, when any, `failures`
(`[{profile, subject, kind, detail}]`, `detail` redacted and cut at its first line and 300 characters, one entry per
judge discarded or skipped in the review, `subject` empty for a skip at selection). The run log, and the output of
`l4 yolo review --local` and `--worktree`, SHALL print one line per failure (`<profile>: <subject>: <kind>: <detail>`). [V, a consumer's ten-unit plan lost three readiness reviews in 40 minutes: the first judge failed its hello,
the next stopped at its output limit on the batch, the whole review was discarded, and the later judges of the chain
were never asked.]

#### Scenario: SCN-YOLO-263 (+) A judge whose hello fails is skipped and named · L4-YOLO-096
- **Given** a review chain `[j1, j2]` where `j1`'s hello fails and `j2` answers READY
- **When** the review runs
- **Then** `j2` answers every subject; `plan.reviewed` holds `judges: [j2]` and `failures: [{profile: j1, subject: "",
  kind: unusable, detail: <the hello step's reason>}]`, and the run log has one line naming `j1`

#### Scenario: SCN-YOLO-264 (+) An error moves the subject to the next judge, and what was answered is kept · L4-YOLO-096
- **Given** units A and B in one batch and the chain `[j1, j2]`; `j1` answers A READY and ends `error` on B; `j2`
  answers B and the batch READY
- **When** the review runs
- **Then** one `plan.reviewed` is recorded with A `judge: j1`, B `judge: j2` and the batch `judge: j2`, `judges: [j1,
  j2]` and `failures: [{profile: j1, subject: B, kind: error}]`; `j1` is not asked the batch, and the charge counts
  the cost of all four calls

#### Scenario: SCN-YOLO-265 (+) A schema break moves only that subject · L4-YOLO-096
- **Given** the chain `[j1, j2]`; `j1`'s two replies to A break the schema, and `j1` answers B; `j2` answers A
- **When** the review runs
- **Then** A has `judge: j2` and B `judge: j1`, and `failures` holds `{profile: j1, subject: A, kind:
  schema_invalid}`

#### Scenario: SCN-YOLO-266 (−) With no judge left, a schema break is BLOCKED and an error leaves the review unfinished · L4-YOLO-096, L4-YOLO-004
- **Given** in turn: the chain `[j1]`, whose two replies to A break the schema and which answers B; the chain `[j1,
  j2]`, where `j1` ends `error` on A and `j2`'s two replies to A break the schema; the chain `[j1]`, which ends `error`
  on A
- **When** each review runs
- **Then** the first records A BLOCKED with `schema_invalid` and B as `j1` answered it (SCN-YOLO-08 holds); the second
  records A BLOCKED with `schema_invalid`; the third records no `plan.reviewed` and records
  `plan.review_incomplete{reason: no_judge}` whose `left` holds A

#### Scenario: SCN-YOLO-267 (+) A usage limit cools the judge and the next judge answers · L4-YOLO-096
- **Given** the chain `[j1, j2]` and a call of `j1` on A that reports a usage limit with a reset in two hours
- **When** the review runs
- **Then** the availability store holds a cool-down of `j1` until that reset, `j2` answers A and every later subject,
  `failures` holds `{profile: j1, subject: A, kind: limit}`, and no `RoleLimit` leaves the review

#### Scenario: SCN-YOLO-268 (+) A judge that failed a material is asked it last in the next run · L4-YOLO-096
- **Given** the chain `[j1, j2]` and, after the plan's latest `plan.reviewed`, a `plan.review_incomplete` whose
  `failures` hold `{profile: j1, subject: batch:b1/summary, kind: timeout}` for the material key M
- **When** the next review asks the part `batch:b1/summary`, whose material key is still M, and a unit whose key is not
  in any failure
- **Then** the part is asked of `j2` first, and the unit of `j1` first

#### Scenario: SCN-YOLO-269 (−) A judge that cannot be sandboxed here is skipped · L4-YOLO-096, L4-YOLO-026
- **Given** a machine without a usable bwrap, `sandbox.mode: auto`, and the review chain `[codex-judge, claude-judge]`
- **When** `l4 yolo review p1 --worktree` runs, and then runs with the chain `[codex-judge]` alone
- **Then** the first skips `codex-judge` with `kind: sandbox` and its reason, and `claude-judge` answers; the second
  exits 3 with the refusal of SCN-YOLO-61; and with `claude-judge` usable but the job out of time, the review is
  incomplete (`job_time`) and keeps its answers, and does not exit 3

### Requirement: L4-YOLO-097 A judge call of the review has a configured time, and a timeout ends the review for the run
Each judge
call of the review SHALL be bounded by `yolo.review.timeout` (a duration, default `15m`, the 900 seconds of before; a
value under `1m` SHALL fail the load with `yolo.review.timeout must be at least 1m`), which every caller passes. A call
that ends `timeout` SHALL NOT be repeated with the same prompt. A batch whose whole call times out SHALL be reviewed in
parts by the same judge (L4-YOLO-098). Any other timeout (a unit, a part, a batch that is not split) SHALL end the
review for this run without asking the next judge, which would spend its own time on the same material in the same job
(as a timeout holds a round in L4-VER-075): the review does not finish (L4-YOLO-099, reason `timeout`), and the next run
asks that call of the other judges first (L4-YOLO-096). In a CI job whose budget is known (L4-IMP-012), the plan step
SHALL start a judge call only when the job's time left before its soft deadline is at least `yolo.review.timeout` (the
repair prompt after a schema break is a call: it is checked too), and else end the review for this run with reason
`job_time`, keeping what it answered; the plan step runs before `l4 run`
arms the soft deadline that stops a unit's running steps (L4-IMP-068), so nothing else stops a review there. `l4 doctor` CFG-012 SHALL warn when
`yolo.review.timeout` is not less than the budget minus `ci.soft_deadline_margin`, the budget being `ci.time_budget`
when it is a duration, else (`auto`) the job's timeout as L4-IMP-077 reads it (nothing is said when it is unknown). [V, the
code: `readiness.DEFAULT_TIMEOUT_S` is 900 and no caller passes a timeout; a consumer's batch subject ran a judge past
900 s and nothing was recorded.]

#### Scenario: SCN-YOLO-270 (+) The configured time bounds each call · L4-YOLO-097
- **Given** `yolo.review.timeout: 30m`, a configuration without the key, and one with `yolo.review.timeout: 30s`
- **When** each is loaded and the first two review a plan
- **Then** every judge request of the first has `timeout_s` 1800, of the second 900; the third does not load, with
  `yolo.review.timeout must be at least 1m`

#### Scenario: SCN-YOLO-271 (−) A timeout ends the review for the run · L4-YOLO-097
- **Given** units A and B in one batch, the chain `[j1, j2]`, and `j1`, which answers A and times out on B
- **When** the review runs, and then the next run reviews with `j1` and `j2` answering
- **Then** the first asks `j2` nothing, records no `plan.reviewed`, and records `plan.review_incomplete{reason:
  timeout}` with A in `answered`, B and the batch in `left` and `{profile: j1, subject: B, kind: timeout}` in
  `failures`; the second asks B of `j2` first, asks the batch, and does not ask A again

#### Scenario: SCN-YOLO-272 (−) No call starts that the job has no time for · L4-YOLO-097
- **Given** a CI job with 10 minutes left before its soft deadline and `yolo.review.timeout: 15m`; a job with 901
  seconds left at its first call, a schema break, and 10 seconds left at the repair; and, for doctor,
  `ci.time_budget: 20m`, `ci.soft_deadline_margin: 10m` and `yolo.review.timeout: 15m`, and `ci.time_budget: auto` in a
  30-minute job with `ci.soft_deadline_margin: 20m`
- **When** the plan step reviews a plan, and `l4 doctor` runs
- **Then** no judge is asked and `plan.review_incomplete{reason: job_time}` is recorded; the second job asks the first
  call and not the repair, and records `job_time` with the subject in `left`; CFG-012 warns `yolo.review.timeout (15m) is
  not less than ci.time_budget (20m) minus ci.soft_deadline_margin (10m)`, and, for the auto budget, `yolo.review.timeout
  (15m) is not less than the job's timeout (30 min, <source>) minus ci.soft_deadline_margin (20m)`

### Requirement: L4-YOLO-098 A batch too large for one call is reviewed in parts
A batch subject that shows two or more units SHALL
be reviewed in parts, and never asked as a whole in that review, when its material (the user text the judge would get)
has more than `yolo.review.max_batch_chars` characters (default `0`: no split before a call, so a batch is asked whole
and split only by the other triggers; a positive value is the size bound), or when a `plan.review_incomplete` recorded after the plan's latest `plan.reviewed` holds
one of its parts (L4-YOLO-099). A part that only a `plan.reviewed` recorded SHALL be reused when the batch is split, but
SHALL NOT split it: once a review has finished, the next review of a changed batch starts whole again, so that `0`
turns the size split off. It SHALL also be reviewed in parts, by the same judge first, when its whole call stops at the
output limit or times out. (A `--worktree` dry run keeps its parts in a local cache: a cached part counts as kept, and splits
the batch, unless a cached line of its batch is as new as it, which a dry run that finished writes, or it is not newer than the
plan's latest `plan.reviewed` on the ledger, so that a review that finished in CI or with `--local` ends it as it does
for a ledger part; `l4 yolo review --worktree --fresh batch:<id>` asks the batch again.) The parts
SHALL be, in order: one part per unit the batch review shows, in plan order (`batch:<batch>/<unit>`), whose material is
the batch's with that unit's folder in full as a subject's is shown (its budgets and its `material_cut`), the
prerequisites outside the batch of that unit as a batch shows them, and each other unit of the batch read as a
prerequisite is read (L4-YOLO-024's order) within 6,000 characters; and one part `batch:<batch>/summary` whose material
is every unit of the batch read that way, the batch's prerequisites outside it by name only, and no folder in full. The
plan entry block of a part SHALL end with harness text that says what the part shows, that each unit is also reviewed
on its own and in the other parts, and that this call reports what lies between the units (`contradiction`,
`duplicate_scope`, `missing_dependency`, `interfaces`) and `batch_acceptance`; that text SHALL name no unit and no batch
(ids reach the prompt only inside `<l4:data>` blocks). The cut of a unit read within 6,000 characters SHALL NOT be a
`material_cut` and SHALL NOT be listed in `missing`. A part's material key SHALL be that of its own text, with the kind
`batch-part`. A subject that is not split SHALL be asked with the prompt it gets today, byte for byte, and keep its
material key, and the readiness prompt version SHALL stay 4. A part SHALL be asked as any call is (L4-YOLO-096,
L4-YOLO-097) and SHALL NOT be split again. When every part has a verdict, the batch's verdict SHALL be made from the
parts' verdicts as the judge gave them: the worst verdict (BLOCKED, then NEEDS_REVISION, then READY), the parts'
findings in part order with an exact repeat (criterion, severity and text) kept once, their assumptions and `missing`
lists joined the same way, and the `missing` line `judged in <n> parts (each unit in full with the other units read in
part, and every unit read in part): no call saw two units of the batch in full together; why: <cause>` (`its material
has <c> characters, over yolo.review.max_batch_chars (<m>)`, `the whole batch stopped at the output limit of
<profile>`, `the whole batch timed out on <profile>`, or `an earlier review run answered a part of it`), and one harness
finding of criterion `parts` and severity `minor`, added after the rules below: `this batch was reviewed in parts: no
judge saw two units' full text together, so defects visible only across units may be missed`. The finding is a note: it
SHALL NOT change the verdict, and a READY batch stays READY with it. `l4 yolo findings` SHALL show a batch that carries
it, READY or not, with the note in full and a `Resolve:` line that says it is a note (and, without `--all`, still says that every
subject is READY when none is open; the exit code is unchanged), and `l4 yolo status` SHALL name the
batches of the current review that were judged in parts (`reviewed in parts: <batches> (no judge saw two units' full
text together)`, and `review.in_parts` in `--json`). The note is not counted among the minor findings, in the text or in
`l4 yolo findings --json` (`minor`), and it SHALL NOT be carried into the accepted findings of a unit: `l4 yolo accept`
records every finding of the subject, the note too, but the run of a unit, its accepted block, the report and the merge
gate of a `merge: auto` plan (L4-YOLO-028, L4-YOLO-031) leave it out, so no verifier has to answer it and it holds no
merge. A part whose verdict is NEEDS_REVISION or BLOCKED and names no finding SHALL get the harness finding `verdict`
(L4-YOLO-023; its criterion is not `schema`, `unit_missing` or `completeness`, so the batch is still reused) before the
merge, so that another part's findings cannot hide it and the merged verdict is never READY because of it: for a BLOCKED
part, the other parts' `batch_acceptance` findings, moved to the assumptions on a batch with no acceptance profile,
would leave a BLOCKED verdict with no finding, which the rule of L4-YOLO-023 for a subject that only groups units makes
READY. A part that is BLOCKED only by `batch_acceptance` and is merged with a part that is NEEDS_REVISION with a major
finding gives BLOCKED, which is stricter than a whole-batch call (the rules run once, on the merged verdict, not on each
part: a known limit). The other rules of
L4-YOLO-004 and L4-YOLO-023 SHALL then be applied once, to the merged verdict, with the whole batch's cuts. The batch's entry
SHALL have the whole batch's material key, so that a later review of the same material reuses it (L4-YOLO-022), and
`parts` (`[{part, material, judge, verdict, findings, assumptions, missing}]`, with `reused_from` for a part that was
reused), whose rows SHALL be reusable by their own keys. `l4 yolo review --worktree --fresh batch:<id>` SHALL ask every
part again. A unit subject SHALL NOT be split: one whose reply stops at the output limit goes to the next judge
(L4-YOLO-096). [V, a consumer's batch subject the size of its whole plan stopped at the output limit of another judge
too; only the opencode adapters mark a length stop (L4-VER-071), so on the other adapters the size bound is what splits
a batch before its reply is cut.]

#### Scenario: SCN-YOLO-273 (+) A large batch is reviewed in parts from the start · L4-YOLO-098
- **Given** `yolo.review.max_batch_chars: 1000`, a batch of the units A, B and C whose batch material is longer than
  that, and a judge that answers READY
- **When** the review runs
- **Then** the judge is asked A, B and C, then `batch:b1/A`, `batch:b1/B`, `batch:b1/C` and `batch:b1/summary`, and never
  the whole batch; the part of A shows A's folder in full and B and C within 6,000 characters each, the summary part
  shows no folder in full, and no part's harness text names a unit or the batch; the batch's entry has the whole batch's
  material key, `parts` with four rows, the `missing` line `judged in 4 parts` and one minor finding of criterion
  `parts` (`this batch was reviewed in parts: no judge saw two units' full text together, so defects visible only
  across units may be missed`); the verdict is READY, and `l4 yolo status` names the batch as reviewed in parts

#### Scenario: SCN-YOLO-274 (+) A whole batch that stops at the output limit is split for the same judge · L4-YOLO-098, L4-YOLO-096
- **Given** a batch under the bound, the chain `[j1, j2]`, and `j1`, whose whole call on the batch ends `error` with a
  length stop, which answers the first parts, and whose call on the summary part stops at the limit again
- **When** the review runs
- **Then** `j1` is asked the parts after the whole batch, `j2` is asked the summary part, the batch's verdict comes from
  the parts with the `missing` line naming the output limit of `j1`, and `failures` holds `{profile: j1, subject:
  batch:b1/summary, kind: length}`; the same review with a whole call that times out is split in the same way

#### Scenario: SCN-YOLO-275 (+) The parts' verdicts make one verdict · L4-YOLO-098, L4-YOLO-023
- **Given** four parts answered READY; NEEDS_REVISION with one major finding F; NEEDS_REVISION with F again; and READY
  with one minor finding; and, separately, a batch with no acceptance profile whose parts' only finding is a
  `batch_acceptance` finding
- **When** the batch's verdict is made
- **Then** the first is NEEDS_REVISION with F once and the minor finding; with one part BLOCKED it is BLOCKED; the
  second is READY with the finding among its assumptions; a part that is NEEDS_REVISION with no finding, merged
  with a part that is READY with one minor finding, gives NEEDS_REVISION with the harness finding `verdict`, never
  READY; and a part that is BLOCKED with no finding, merged with a part whose only finding is `batch_acceptance` (or
  that is BLOCKED by it alone), gives BLOCKED with the harness finding `verdict`, never READY, also when the BLOCKED
  part is a kept part reused from an earlier review

#### Scenario: SCN-YOLO-276 (−) A batch that fits and a unit keep today's prompt · L4-YOLO-098
- **Given** a batch under the bound, a unit subject, a batch with one unit left to review (the others done), and a
  large batch (over 160,000 characters) with `yolo.review.max_batch_chars` at its default `0`
- **When** the review builds and asks them
- **Then** the batch under the bound and the unit are asked with the prompt of 0.4.58, byte for byte, and the same
  material keys, and the prompt version is 4; the last two are asked whole; a unit whose reply stops at the limit goes
  to the next judge unsplit

#### Scenario: SCN-YOLO-277 (+) A batch judged in parts, and a kept part, are reused · L4-YOLO-098, L4-YOLO-022
- **Given** a recorded review whose batch b1 was judged in parts, and a `plan.review_incomplete` after it that holds two
  of the four parts of the batch b2
- **When** a later review runs on the same material, and then `l4 yolo review p1 --worktree --fresh batch:b1` runs
- **Then** the first asks nothing about b1 and asks only the two other parts of b2; the second asks every part of b1
  again; and when a prerequisite outside b1 changes after the review, with `yolo.review.max_batch_chars: 0`, the next
  review asks b1 whole, and not in parts reused from the recorded review

### Requirement: L4-YOLO-099 A review that does not finish keeps what it answered and says why
A review that ends with a call that
has no answer (reasons `no_judge`, `timeout` and `job_time`) SHALL NOT record `plan.reviewed`, and SHALL record, with the
lease, `plan.admitted` when the admission of this plan digest and order is not recorded yet (as for a review that
finishes), and `plan.review_incomplete{plan_digest, prompt_version, source, by, target_rev, reason, answered, left, failures,
cost_usd}`: `answered` maps each unit, batch and part the review judged in this run (`<unit>`, `batch:<id>`,
`batch:<id>/<unit>`, `batch:<id>/summary`) to its entry as `plan.reviewed` writes it (`material`, `judge`, a unit's
`digest`), without an entry that has a harness `schema`, `unit_missing` or `completeness` finding; `left` lists the
subjects and parts with no answer; `failures` is that of L4-YOLO-096; `by` is set by a person's or an agent's command.
When no judge could be selected at all, `answered` SHALL be empty and `failures` SHALL name each profile and why. The
state fold SHALL ignore the event (L4-YOLO-006; an older harness ignores it too), so the plan's status, its review, its
acceptances and its activation are unchanged by it. Its cost SHALL be charged as that of a review that finishes
(`plan.charged{unit: plan:review}`, the running total), in the same write. A later review SHALL reuse the entries of
`answered` by their material key and the prompt version (L4-YOLO-022), with `reused_from` the event's time, so the next
run asks only what is left; a changed unit, a changed prerequisite or another prompt version changes the key, and the
subject is judged again. The history of `l4 yolo findings` SHALL count a judgement where it was made, in a
`plan.reviewed` or in a `plan.review_incomplete`. No event SHALL be written when the newest `plan.review_incomplete`
after the plan's latest `plan.reviewed` has the same plan digest, reason and failures (profile, subject, kind and material key,
so that the same judge failing the same unit on a text a person has changed since is written, and the next run asks
another judge first) and the run answered nothing and spent nothing; the log line is still printed. The run log SHALL say `<plan>: the review is
incomplete (<reason>): <a> answered and kept, <l> left; a later run asks the rest`, after the lines of the failures, and
no other plan is reviewed in that run. While the review is not current, `l4 yolo status` SHALL show, under the review
line, for the newest `plan.review_incomplete` of the current prompt version that is newer than the plan's latest
`plan.reviewed`: `incomplete <t> ago (<source>, <reason>): <a> answered and kept, <l> left`, one line per failure, and a
`fix:` line for the reason (`timeout`: raise `yolo.review.timeout` or put another judge first in `roles.plan_judges`;
`no_judge`: fix the judges named, `l4 doctor --live`, or set `roles.plan_judges`; `job_time`: give the CI job more time
or lower `yolo.review.timeout`); `--json` SHALL have `review.incomplete{at, source, reason, answered, left, failures,
cost_usd}`. `l4 yolo review --local` and `l4 yolo review --worktree --record` SHALL record the event in the same way
(`source: local` and `worktree`) and exit 12 with the same lines; a `--worktree` dry run SHALL write the answered
entries to its local cache, SHALL NOT move the plan ref, and SHALL exit 12. A `RoleUnavailable` or `RoleLimit` that
reaches a caller in another way SHALL still record nothing.

#### Scenario: SCN-YOLO-278 (+) Every judge fails, and the reason is recorded and shown · L4-YOLO-099
- **Given** units A and B in one batch, the chain `[j1, j2]`, `j1`'s hello fails, and `j2` answers A and B and ends
  `error` on the batch
- **When** the CI step reviews the plan, and `l4 yolo status p1` runs
- **Then** no `plan.reviewed` is recorded; `plan.review_incomplete{source: ci, reason: no_judge}` holds A and B in
  `answered` with `judge: j2`, the batch in `left`, and both failures, and `plan.charged{unit: plan:review}` holds the
  calls' cost; the log says `the review is incomplete (no_judge): 2 answered and kept, 1 left`; the status shows
  `incomplete`, `2 answered and kept, 1 left`, both failures and a `fix:` line, `--json` has `review.incomplete`, and the
  plan stays `admitted`

#### Scenario: SCN-YOLO-279 (+) The next run asks only what is left · L4-YOLO-099, L4-YOLO-022
- **Given** the ledger of SCN-YOLO-278 and `j2`, which now answers the batch
- **When** the next run reviews the plan, and `l4 yolo findings p1 A --all` runs
- **Then** only the batch is asked; one `plan.reviewed` holds A and B with `reused_from` the time of the
  `plan.review_incomplete`, and the batch with `judge: j2`; the history of A shows its judgement at that time

#### Scenario: SCN-YOLO-280 (−) A repeat adds nothing, and a changed unit is judged again · L4-YOLO-099
- **Given** the ledger of SCN-YOLO-278, and a run in which every judge fails as before, answers nothing and spends
  nothing; then a person changes the spec of A
- **When** that run reviews, and then the run after the change
- **Then** the first writes nothing to the plan ref and logs the line; the second judges A again and reuses B; and when
  `j1` times out on A at no cost, a person changes A, and `j1` times out on A again, the second timeout is recorded (its
  material key is new) and the run after asks `j2` first for A

#### Scenario: SCN-YOLO-281 (+) A local review records it, and a dry run keeps it locally · L4-YOLO-099
- **Given** the judges of SCN-YOLO-278
- **When** `l4 yolo review p1 --local` runs, and then, on a fresh ledger, `l4 yolo review p1 --worktree` runs twice
- **Then** `--local` records `plan.review_incomplete{source: local, by}` and exits 12 with the failure lines; each
  `--worktree` run leaves the plan ref where it was and exits 12, and the second asks only the batch

### Requirement: L4-YOLO-100 Documentation of the review's judge chain
The runbook SHALL say, in its procedure to review a plan
(12.2) and in its section on capacity, which chain reviews a plan, that the review moves a subject to the next judge and
keeps what was answered, what `incomplete` under `review:` in `l4 yolo status` means and the fix for each reason, the
keys `roles.plan_judges`, `yolo.review.timeout` and `yolo.review.max_batch_chars` with their defaults, and that a batch
reviewed in parts says so in `missing`. `docs/yolo-mode.md` SHALL say the same in place of "L4 records no review". The
skill SHALL name `roles.plan_judges` where `references/adopt.md` shows role chains, and `references/operate.md` (its
error table) and `references/plan.md` SHALL give the message of an incomplete review and what to do. The CHANGELOG
SHALL have the entry under Unreleased.

#### Scenario: SCN-YOLO-282 (+) The documentation names the chain and the unfinished review · L4-YOLO-100
- **When** the runbook, `docs/yolo-mode.md`, the skill's `references/adopt.md`, `references/operate.md` and
  `references/plan.md`, and the CHANGELOG are read
- **Then** the runbook names `roles.plan_judges`, `yolo.review.timeout`, `yolo.review.max_batch_chars` and
  `plan.review_incomplete` with a fix for each reason; `docs/yolo-mode.md` no longer says that L4 records no review;
  `adopt.md` names `roles.plan_judges`; `operate.md` and `plan.md` give the message of an incomplete review; the
  CHANGELOG's Unreleased section names the keys
