## 1. The window as data (L4-CI-014)

- [x] 1.1 Write the tests first, in `tests/unit/ci/test_handoff_ci.py` (it passes `ready_at=` and `now=`). Then add
  `window_remaining(ready_at, now) -> float | None` to `l4.ci.handoff_ci` (design D1) with the clamp of `_in_window`,
  make `_in_window` use it, and add `window_s` to `HandoffCi` (set only with `NOT_CREATED_YET` and no required check
  named: a required check keeps the window but ends `unreported`, design D1). Cases: SCN-CI-070 (4
  minutes before → 360; 1 minute ahead → 600; 2 hours ahead → None; None → None); a read inside the window has
  `window_s` > 0; a read inside the window with a required check named (still `NOT_CREATED_YET`) has `window_s` None;
  a read with CI running has `window_s` None.
  Result: added `window_remaining` (signed seconds, so a closed window is zero or less; None for no time or a forged
  one), `_in_window` uses it, and `HandoffCi.window_s` is set with `NOT_CREATED_YET` when `_required` named no check.
  `tests/unit/ci/test_handoff_ci.py`: the three new tests (SCN-CI-070, window seconds per read, required check gives
  None) failed at import before, and the file passes now (27 tests).
- [ ] 1.2 Write the tests first, in `tests/unit/yolo/test_merge_safety_ci_gate.py`. Pass `now` through
  `merge_guarded` → `_ci_gate` → `read_handoff_ci` (keyword, default the wall clock), and add `window_s` to
  `MergeOutcome`, set from the CI read when the outcome is `not_ready` because of the window only. Cases: the window
  gives `window_s`; running CI, a required check that is unreported, and a red job give None.

## 2. The wait (L4-YOLO-012, L4-YOLO-013)

- [ ] 2.1 Write the tests first (use `tests/unit/yolo/yolo_cycle_world.py`: `step(**kw)` reaches `yolo_step`, which
  takes `now=` and `sleep=`; `StartRunForge.started` and the log line "next run on main: started" of
  `test_yolo_cycle_run.py`). Then add `budget: Callable[[], float | None] | None = None` to `yolo_step` and the step,
  and `_wait_window` (design D2 to D6) called from `_merge` and `_merge_wait_gone`. Constants `WINDOW_SLACK_S = 15`,
  `WINDOW_POLL_S = 60`, `MERGE_RESERVE_S = confirm_wait_s + 150`. Cases: SCN-YOLO-240 to SCN-YOLO-245; amend
  `test_ci_not_created_yet_waits_inside_the_window` (SCN-YOLO-122) to run without a budget; a cancel recorded during
  the wait (the plan read again under the lease is not active) merges nothing; the wait never runs twice in one step.
- [ ] 2.2 Write the tests first, in the orchestrator's tests of the plan step (grep `yolo_step(` under
  `tests/unit/orchestrator`). Then pass `budget=` from the orchestrator's call of `yolo_step`: in CI (`in_ci`) a callable
  over `job_remaining_s(cfg, app.environ, <the run's clock>.now(), <the run's start>)`; outside CI None. Cases: a CI
  environment with `CI_JOB_TIMEOUT` gives a callable; a local run gives None.

## 3. Checks

- [ ] 3.1 Run `tests/unit/ci`, `tests/unit/yolo` and `tests/unit/orchestrator` once with pytest (never in a loop) and
  wait for them to finish. Run ruff check and ruff format on the changed files. Report the counts.
