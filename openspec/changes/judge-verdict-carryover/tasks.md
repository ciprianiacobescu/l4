## 1. The rule (D1, D2)

- [ ] 1.1 Write the tests first (tests/unit/verifier: a new test_carryover.py over a real git repo fixture, as
  test_judge_step.py builds one). Then implement `l4.verifier.carryover`: a pure decision over the stored verdict of R,
  the criteria, this round's trace, the changed paths and the blob checks it is given, plus one function that reads them
  through `Git` and `read_verdict`. Cases: SCN-VER-273..276 at the function level, each condition of D2 alone, a read
  failure.

## 2. Applying it (D3, D4)

- [ ] 2.1 Write the tests first (tests/unit/verifier: a ladder-level test with a stub judge that times out, after a round
  that passed, over a head that adds one test file). Then implement: `_finalize` applies the rule when `run.judged` is None
  in a fresh round whose step 9 record is `failed` (not when it is `not_run`), the adequacy entries (`apply_adequacy`,
  then `count_named` with the adequate ones), `aggregate_criterion(carried=)`, `verify.carried`/`verify.not_carried`,
  `VerifyResult.judge_carried` `{round, head, verdict, adequacy}` in `verdict_json` and `restore_round`. A resumed round
  (`ladder._resume`: `run.judged` comes from the stored `judge_verdict` only, so it is None after such a round) adds the
  restored carried verdicts to `picked` in `_finalize`, with no git call and no read of the earlier round. Cases:
  SCN-VER-273, SCN-VER-277 (assert the resumed round's criterion outcomes, not only the field); the hold stays and the
  round cannot PASS; `_calibrate` and the stored `judge_verdict` see no carried verdict.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-VER-072, SCN-VER-273..277, the two events, row 112), CHANGELOG 0.4.49, runbook; the verifier suite,
  ruff, `openspec validate judge-verdict-carryover --strict`.
