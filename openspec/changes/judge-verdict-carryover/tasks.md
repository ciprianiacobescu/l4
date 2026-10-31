## 1. The rule (D1, D2)

- [x] 1.1 Write the tests first (tests/unit/verifier: a new test_carryover.py over a real git repo fixture, as
  test_judge_step.py builds one). Then implement `l4.verifier.carryover`: a pure decision over the stored verdict of R,
  the criteria, this round's trace, the changed paths and the blob checks it is given, plus one function that reads them
  through `Git` and `read_verdict`. Cases: SCN-VER-273..276 at the function level, each condition of D2 alone, a read
  failure.
  Result: `l4.verifier.carryover`: `decide` (pure: R's stored verdict, criteria, this round's trace, changed paths,
  `same_source` and `file_of` answers), `source_round`, `carry_over` (gathers through `Git` and `read_verdict`; an R head
  that is not a hex commit id of this repository, or any git/read failure, carries nothing and says why), `apply_carried`
  (adequacy rows, then `count_named`) and `carried_verdicts` (for the resumed round). tests/unit/verifier/
  test_carryover.py (37 tests): every condition of D2 has a test in which it alone fails; each was checked by removing
  the condition and seeing that test fail. Choices the design left open: a test id whose file is not found keeps its
  criterion from being carried; a candidate over the cap counts as a tracing test for D2.4; an adequacy row of no
  criterion about a test that traced the criterion goes with it (applied to that criterion only); an adequacy row that
  does not parse carries nothing.

## 2. Applying it (D3, D4)

- [x] 2.1 Write the tests first (tests/unit/verifier: a ladder-level test with a stub judge that times out, after a round
  that passed, over a head that adds one test file). Then implement: `_finalize` applies the rule when `run.judged` is None
  in a fresh round whose step 9 record is `failed` (not when it is `not_run`), the adequacy entries (`apply_adequacy`,
  then `count_named` with the adequate ones), `aggregate_criterion(carried=)`, `verify.carried`/`verify.not_carried`,
  `VerifyResult.judge_carried` `{round, head, verdict, adequacy}` in `verdict_json` and `restore_round`. A resumed round
  (`ladder._resume`: `run.judged` comes from the stored `judge_verdict` only, so it is None after such a round) adds the
  restored carried verdicts to `picked` in `_finalize`, with no git call and no read of the earlier round. Cases:
  SCN-VER-273, SCN-VER-277 (assert the resumed round's criterion outcomes, not only the field); the hold stays and the
  round cannot PASS; `_calibrate` and the stored `judge_verdict` see no carried verdict.
  Result: `ladder._carry_judge_passes` (called at the start of `_finalize`) runs `carryover.carry_over` only in a fresh
  round whose step-9 record is `failed`, applies `apply_carried` to the trace, sets `VerifyResult.judge_carried` and emits
  `verify.carried` / `verify.not_carried`; `_finalize` then adds `carried_verdicts(result.judge_carried)` to `picked`
  (fresh or restored by `restore_round`) and passes `carried=(round, head)` to `aggregate_criterion`; `verdict_json`
  stores `judge_carried`. `run.judged`, `result.judge_verdict` and `_calibrate` never see a carried verdict. A resumed
  round has no step records, so it never computes the rule: it uses the restored field, with no git call and no read of
  round 1. tests/unit/verifier/test_carryover_ladder.py (16 tests, a real bench: round 1 passes three criteria, round 3 adds
  one test file and its judge times out): SCN-VER-273 (A and B carried with the reason and events, C asked, the hold
  stays), the hold keeps an all-carried round from PASS, a person's reject and a failing test still decide, the adequacy
  rows are applied and stored (two shapes), a production change and a missing round record `verify.not_carried`,
  SCN-VER-277 (a judge that answered, a not_run step 9, and the resumed round's criterion outcomes with round 1's
  evidence deleted and no git call naming its head), a resumed round does not compute the rule again, and
  `aggregate_criterion(carried=)`.

## 3. Checks

- [x] 3.1 SPEC.md (L4-VER-072, SCN-VER-273..277, the two events, row 112), CHANGELOG 0.4.49, runbook; the verifier suite,
  ruff, `openspec validate judge-verdict-carryover --strict`.
  Result: L4-VER-072, SCN-VER-273..277, `verify.carried` and `verify.not_carried`, row 112, CHANGELOG 0.4.49 and the
  runbook's 7.1 note; the harness's memory path allowed beside the unit family (a follow-up commit with its test);
  tests/unit/verifier 1865 passed, carry-over tests 54 passed after it, docs tests 120 passed, ruff check clean.
