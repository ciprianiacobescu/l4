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
- [x] 1.2 Write the tests first, in `tests/unit/yolo/test_merge_safety_ci_gate.py`. Pass `now` through
  `merge_guarded` → `_ci_gate` → `read_handoff_ci` (keyword, default the wall clock), and add `window_s` to
  `MergeOutcome`, set from the CI read when the outcome is `not_ready` because of the window only. Cases: the window
  gives `window_s`; running CI, a required check that is unreported, and a red job give None.
  Result: `merge_guarded` and `_ci_gate` take `now` (default the wall clock) and pass it to `read_handoff_ci`;
  `MergeOutcome.window_s` (in `l4.yolo.model`) is set by `_ci_gate` from the CI read when the `not_ready` is the
  window's "still running" outcome (the read's `window_s` is None for every other cause). Both new tests in
  `tests/unit/yolo/test_merge_safety_ci_gate.py` failed on the unknown `now` keyword before and pass now (28 tests).

## 2. The wait (L4-YOLO-012, L4-YOLO-013)

- [x] 2.1 Write the tests first (use `tests/unit/yolo/yolo_cycle_world.py`: `step(**kw)` reaches `yolo_step`, which
  takes `now=` and `sleep=`; `StartRunForge.started` and the log line "next run on main: started" of
  `test_yolo_cycle_run.py`). Then add `budget: Callable[[], float | None] | None = None` to `yolo_step` and the step,
  and `_wait_window` (design D2 to D6) called from `_merge` and `_merge_wait_gone`. Constants `WINDOW_SLACK_S = 15`,
  `WINDOW_POLL_S = 60`, `MERGE_RESERVE_S = confirm_wait_s + 150`. Cases: SCN-YOLO-240 to SCN-YOLO-245; amend
  `test_ci_not_created_yet_waits_inside_the_window` (SCN-YOLO-122) to run without a budget; a cancel recorded during
  the wait (the plan read again under the lease is not active) merges nothing; the wait never runs twice in one step.
  Result: `yolo_step` takes `budget`; `_Step._wait_window` (called from `_merge` and `_merge_wait_gone` through an `ask`
  closure) waits in slices of `WINDOW_POLL_S` 60 s, reads H's CI after each with the new `l4.yolo.merge.read_ci`
  (shared with `_ci_gate`), and asks the guard again once; `_wait_merge` starts the next run only for a unit whose wait
  the budget cut short. The reserve is `MERGE_RESERVE_S` (150) plus the step's `confirm_wait_s`. New file
  `tests/unit/yolo/test_merge_window_wait.py` (SCN-YOLO-240 to 245, a cancel during the wait, no-room budgets, the
  wake path without a budget): all 13 failed on the unknown `budget` keyword before and pass now; SCN-YOLO-122 runs
  with `budget=None`. On an exact clock the wait ends when the window closes (360 s of 375 s), the slack only bounds it.
- [x] 2.2 Write the tests first, in the orchestrator's tests of the plan step (grep `yolo_step(` under
  `tests/unit/orchestrator`). Then pass `budget=` from the orchestrator's call of `yolo_step`: in CI (`in_ci`) a callable
  over `job_remaining_s(cfg, app.environ, <the run's clock>.now(), <the run's start>)`; outside CI None. Cases: a CI
  environment with `CI_JOB_TIMEOUT` gives a callable; a local run gives None.
  Result: `run_command` records the run's start with the services clock right after the config is loaded and passes
  `budget=` to `yolo_step`: a callable over `job_remaining_s(cfg, environ, clock.now(), began)` when `l4.ci.detect.in_ci`
  holds (imported as `running_in_ci`, since `continue_left_units` has a local `in_ci`), else None. New
  `tests/unit/orchestrator/test_plan_step_budget.py` (4 tests: a callable that runs down with the clock, a GitLab
  `CI_JOB_TIMEOUT` budget, a CI run with no known budget answers None, a local run gets None): they failed with
  `KeyError: 'budget'` before (checked with the orchestrator change stashed) and pass now.

## 3. Checks

- [x] 3.1 Run `tests/unit/ci`, `tests/unit/yolo` and `tests/unit/orchestrator` once with pytest (never in a loop) and
  wait for them to finish. Run ruff check and ruff format on the changed files. Report the counts.
  Result: `uv run --frozen pytest tests/unit/ci tests/unit/yolo tests/unit/orchestrator -q -p no:cacheprovider` on the
  four commits of 1.1 to 2.2: 2848 passed (2 h 12 min). `ruff check` and `ruff format --check` clean on the changed
  files. After 2.3 only the files it touched were run again (see 2.3).

- [x] 2.3 Review fixes. (1) A wait cut short by the budget on the wake path asks for the next run: `run()` ends the
  no-live-plan path with `start_next_run=bool(self._window_cut)`. (2) and (3) `_wait_window` reads `self.budget()` before
  every slice and stops, with `cut`, when the budget less the reserve is used up (the reads of the forge take time
  too); the wait still needed is recomputed from each read's `window_s` plus the slack, so a clock that runs ahead
  does not end the wait early, and `cut` is set only when the budget ended it; a cap of the first need plus
  `MAX_SKEW` bounds the loop. (4) `run_command` passes its start (`began`) to `run_units` in a CI run, so the soft
  budget of the units counts a plan step that waited when the job's start is unknown. (5) tests for a forge read error
  during the wait and for the once-per-step guard.
  Result: in `tests/unit/yolo/test_merge_window_wait.py` the tests for the wake-path chain, reads that take time and
  the fast clock failed before (no run started; four slices instead of three; no merge after 615 s) and pass now; the
  read-error and once-per-step tests were added as missing coverage and pass; the short-budget tests now use a budget
  that runs down with the clock. `tests/unit/orchestrator/test_plan_step_budget.py` has a fifth test for (4) that failed
  (`began` five minutes late). Run once each after the fix: `test_merge_window_wait.py` 18 passed,
  `test_plan_step_budget.py` + `test_yolo_cycle_run.py` 20 passed, `test_merge_safety_ci_gate.py` +
  `tests/unit/ci/test_handoff_ci.py` 55 passed; ruff check and format clean. The whole directories were not run again
  (CI runs them).
