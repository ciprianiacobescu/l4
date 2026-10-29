## 1. The loop (L4-IMP-017)

- [ ] 1.1 Write the tests first, in `tests/unit/implementer/test_escalation.py` (the two-profile config `TWO`, the fake
  hook `Hook`, the failing steps `BAD`/`INVALID`) and `tests/unit/implementer/test_loop.py` (escalation seeded from
  earlier runs). Then make the change of design D1 in `src/l4/implementer/loop.py`. Cases: a chore task with a marker
  fails twice on `impl` and passes on `impl-b`: the hook request has phase `single` and attempt 3, and the step keys
  are `1.1/single/1` to `1.1/single/3`; two seeded single failures move the task before its first attempt
  (SCN-IMP-420); a held single check counts nothing and moves nothing (SCN-IMP-422).

## 2. The fix loop (L4-IMP-017)

- [ ] 2.1 Write the tests first. Invert `tests/unit/verifier/test_fixloop_no_hook.py` (its fix unit is a single-phase
  chore and asserts no move): with the hook it moves (SCN-IMP-183, amended); without the `ctx.shared` key it does not. Add an
  end-to-end test in `tests/unit/orchestrator/test_escalation.py` (`run_l4(..., **TWO)`): after `noqa_green`, the chore
  fails twice on `impl` and passes on `impl-b`; assert `implementer.escalated{phase: single}` and that the run's
  profile is unchanged; a limit on `impl-b` in the fix task cools `impl-b` only and the next fix task starts on `impl`
  (SCN-IMP-421). Then implement design D2 in `src/l4/verifier/fixloop.py` and `src/l4/orchestrator.py`, clearing the
  task's selection in a `finally`.

## 3. Checks

- [ ] 3.1 Run `tests/unit/implementer`, `tests/unit/verifier` and `tests/unit/orchestrator` once with pytest (never in a
  loop) and wait for them to finish. Run ruff check and ruff format on the changed files. Report the counts.
