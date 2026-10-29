## 1. The loop (L4-IMP-017)

- [x] 1.1 Write the tests first, in `tests/unit/implementer/test_escalation.py` (the two-profile config `TWO`, the fake
  hook `Hook`, the failing steps `BAD`/`INVALID`) and `tests/unit/implementer/test_loop.py` (escalation seeded from
  earlier runs). Then make the change of design D1 in `src/l4/implementer/loop.py`. Cases: a chore task with a marker
  fails twice on `impl` and passes on `impl-b`: the hook request has phase `single` and attempt 3, and the step keys
  are `1.1/single/1` to `1.1/single/3`; two seeded single failures move the task before its first attempt
  (SCN-IMP-420); a held single check counts nothing and moves nothing (SCN-IMP-422).

  Result: `_escalate_if_due` no longer returns on `single`, `EscalationRequest.phase` takes `"single"`, and the
  request's attempt is `attempts["red" if phase == "red" else "green"] + 1`. Tests added: the chore that fails twice on
  `impl` and moves to `impl-b` (`test_escalation.py`, with the helper `tag_as_chore` that writes the unit's `.l4/fix.json`
  marker), the held single check (`test_escalation.py`, passes before and after: it guards the held return) and the
  two seeded single failures (`test_loop.py`). Before the change the two move tests failed on an empty hook request list
  (the single phase never asked); now they pass, with the 77 other tests of `test_escalation.py`, `test_loop.py`,
  `test_single_phase.py` and `test_held_check.py` (79 passed in all).

## 2. The fix loop (L4-IMP-017)

- [x] 2.1 Write the tests first. Invert `tests/unit/verifier/test_fixloop_no_hook.py` (its fix unit is a single-phase
  chore and asserts no move): with the hook it moves (SCN-IMP-183, amended); without the `ctx.shared` key it does not. Add an
  end-to-end test in `tests/unit/orchestrator/test_escalation.py` (`run_l4(..., **TWO)`): after `noqa_green`, the chore
  fails twice on `impl` and passes on `impl-b`; assert `implementer.escalated{phase: single}` and that the run's
  profile is unchanged; a limit on `impl-b` in the fix task cools `impl-b` only and the next fix task starts on `impl`
  (SCN-IMP-421). Then implement design D2 in `src/l4/verifier/fixloop.py` and `src/l4/orchestrator.py`, clearing the
  task's selection in a `finally`.

  Result: the orchestrator split `_escalate` into the selection step `_escalation_profile(request)` (returns the
  chosen `Selected` and sets `_task_selected`, or why there is none) and the workbench build; it exposes the step as
  `ctx.shared["escalate"]` and a clearing call as `ctx.shared["escalation_ended"]`. `fix_hook` builds the `escalate=`
  callable (`_escalation`): it asks the shared step, builds the child workbench on the chosen profile
  (`_child_workbench(..., selected=)`), carries the baselines over and sets the escalation `PreviousAttempt`; the call
  of `run_task` has a `finally` that calls `escalation_ended`. Deviations: the two end-to-end tests are in
  `tests/unit/verifier/test_fixloop_escalate.py`, not in `tests/unit/orchestrator/test_escalation.py`, because the
  fix-loop fixtures (`valid_spec`, the OpenSpec stand-in, `run_l4` with the verifier) live in the verifier suite;
  `test_fixloop_no_hook.py` is renamed to `test_fixloop_escalate.py` and inverted. Before the change the move test and
  the limit test failed (the chore halted on `impl` after three attempts); now they pass, with the no-key test and the
  existing fix-loop fallback and orchestrator escalation tests (15 passed).

## 3. Checks

- [x] 3.1 Run `tests/unit/implementer`, `tests/unit/verifier` and `tests/unit/orchestrator` once with pytest (never in a
  loop) and wait for them to finish. Run ruff check and ruff format on the changed files. Report the counts.

  Result: `uv run --frozen pytest tests/unit/implementer tests/unit/verifier tests/unit/orchestrator -q -p no:cacheprovider`
  ran once: 3543 passed, 3 skipped, 1 xfailed in 3 h 34 min, no failure. `ruff check` and `ruff format --check` on the
  six changed source and test files report nothing.
