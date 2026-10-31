## Context

Step 10 (`ladder._finalize`) aggregates each criterion from its trace, the human verdicts in force and the judge's word
(`pick_verdicts(run.judged)`). When step 9 gave no verdict (`judge_body` returned False after a discarded part, so
`run.judged` is None), `aggregate_criterion` gives every criterion with a passing, adequate tracing test `needs_human:
the judge gave no verdict for this criterion`, and each becomes a verdict question. A whole earlier round is reused only
when its subject is the same (`evidence.reusable`). Stored rounds are `.l4/evidence/round-<n>/verdict.json`
(`evidence.read_verdict`), which keep `head_sha`, `judge_verdict` (criteria, test adequacy) and `trace` (each
criterion's tests, ids and status).

## Decisions

### D1 When a verdict is carried

Only at step 10 of a fresh round whose step 9 ran and failed (`run.records["9"].status == "failed"`: a part's reply was
discarded), so `run.judged` is None. A round whose step 9 did not run (an earlier step failed) or whose judge answered
carries nothing. A resumed round (`_resume`, which rebuilds `run.judged` from the stored `judge_verdict` only) does not
compute the rule again: it takes the carried verdicts from the restored `judge_carried` (D4), which hold everything
needed, so the person's answers recorded since land on the carried passes and not on reopened questions. The source round R is the newest stored round below this one whose `judge_verdict` is a non-empty
object with criteria; there is no search further back per criterion. Any read failure (no such round, unreadable file,
`head_sha` that is not a commit, a git error) carries nothing and records `verify.not_carried{reason}`.

### D2 What must hold for a criterion C (all of them)

1. R's judge verdict for C is `pass`.
2. C's source file (`Criterion.source_path` under the unit's directory) has the same blob at R's head and at this head.
3. Every path of `git diff --name-only <R.head> <head>` is inside a directory of the unit family (`_unit_dirs`: the
   spec, `questions.md`, the evidence, and fix-unit directories, whose criteria are new ids and are never in R, so they
   are asked), or matches `tdd.test_globs` and no `tdd.test_support_globs`. Any other path carries nothing for any criterion
   (`verify.not_carried{reason: "a non-test file changed", paths: first 5}`).
4. No changed test file is the file of a test that traces C in R's `trace` or in this round's trace (the file of a test
   id: `test_locate.file_of_id` over the head tree, as `ladder._test_blobs` finds it).
5. The ids of C's tracing tests now are a subset of those in R's trace, and every test that traces C now passed.

### D3 What a carried criterion gets

`picked[C]` is R's `CriterionVerdict` for C (parsed with the judge verdict model; one that does not parse is not
carried). `run.judged` stays the round's own judge output (None), so `_calibrate` and the stored `judge_verdict` never
hold a carried verdict. R's `test_adequacy` entries whose criterion is C feed this round's trace as the judge's own
entries do in `judge_body`: `apply_adequacy`, then `count_named` with the adequate ones (which rescues a cap-only
criterion), before aggregation; the trace is stored with them applied. `aggregate_criterion` takes `carried: tuple[int, str] | None`, and a carried pass reads `the judge of round
<R> passed it at <head10>, and only tests that do not trace it changed since (carried)`. A human verdict in force and a
failing tracing test still come first, as for any judge verdict.

### D4 Records

`verify.carried{round, criterion, from_round, from_head}` for each carried criterion. `verify.not_carried{round,
from_round, reason, paths}` once per round when the rule carries none for a reason that applies to all of them (no
source round, a non-test change, a read failure). `VerifyResult.judge_carried: {criterion: {round, head, verdict, adequacy}}` (`verdict`: R's criterion verdict
row as stored; `adequacy`: R's test-adequacy rows for it), written by `verdict_json` and restored by `restore_round`;
`_finalize` adds the restored carried verdicts to `picked` in a resumed round, with no git call and no read of R. The hold of the discarded reply stays, and findings are not carried. The
S1 calibration rows (`_calibrate`) read `run.judged` only, so a carried verdict is never calibration data.

## Risks / Trade-offs

- The judge did not see the round's new tests. Every criterion that one of them traces is asked, and the hold stays, so
  the round cannot PASS without a person's or the delegate's answer to the hold.
- A test file that no criterion's tracing test lives in, but that changes what another test does (a shared fixture in a
  test file), is not caught by D2.4. Support files are caught by D2.3 (a support glob is not a test path).
- A merge of the base into the unit branch changes production paths, so it carries nothing.
- D2.2 compares a criterion's whole source file: any edit to it stops carrying every criterion in it. A Kiro unit has
  one `requirements.md`, so an edit there stops carrying all of the unit's criteria.
