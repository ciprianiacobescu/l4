# Design: merge-window-wait

## Context (verified on amaster b4cf62b5)

- `read_handoff_ci` (src/l4/ci/handoff_ci.py) returns `running` with `NOT_CREATED_YET` when H has no considered job,
  `_in_window(ready_at, now)` holds (ten minutes after `pr.ready`, `WINDOW`, with the `MAX_SKEW` clamp) and
  `_can_start_ci` keeps the window (always on GitLab; on GitHub unless only `l4.yml` exists and nothing else can run).
- `_ci_gate` (src/l4/yolo/merge.py) turns it into `not_ready` with the "still running" detail; it reads the wall clock.
- `_merge` (src/l4/yolo/cycle.py) stores `_merge_not_ready[unit]` and returns None; `_dispatch` then calls
  `_wait_merge`, which writes `plan.waiting{merge_not_ready}` and returns `start_next_run=False`.
- A later run: the plan is `waiting`; `_wake` → `_merge_wait_gone` asks `merge_guarded` with `before_push` answering
  no and compares the detail with the recorded one; the same detail → None (still waiting).
- `job_remaining_s(cfg, environ, now, began)` (src/l4/orchestrator.py) gives the seconds left before the soft
  deadline, None when the budget is unknown. The plan step runs before `deadline.arm`, so nothing else bounds it.

## D1 The window as data

`window_remaining(ready_at, now) -> float | None` in `l4.ci.handoff_ci`: the seconds until `ready_at + WINDOW`, with
the clamp of `_in_window` (a time ahead by at most `MAX_SKEW` is `now`; further ahead, or None, gives None). `_in_window`
becomes `window_remaining(...) is not None and > 0`. `HandoffCi` gains `window_s: float | None`, set only with
`NOT_CREATED_YET` **and** no required check named (`_required` gave no names): inside the window a named required
check that H has not reported still reads `NOT_CREATED_YET` (`_can_start_ci` keeps the window when `required` is
non-empty), but after the window it becomes `unreported` and still blocks, so waiting for it gains nothing, and `MergeOutcome` gains `window_s` copied from the CI read when the `not_ready` comes from it and
nothing else blocks. No caller matches `NOT_CREATED_YET` in a detail string.

## D2 Where and when the step waits

One helper on the step, `_wait_window(ctx, unit, out) -> MergeOutcome`, called:
- from `_merge`, after `merge_guarded` returns `not_ready` with `window_s`;
- from `_merge_wait_gone`, when the probe returns `not_ready` with `window_s` and the recorded detail is the window's.
  After the wait it asks the probe again; a merge that can go on is "the cause is gone", and the step merges as on any
  wake.

It waits only when all hold: the step is not `read_only` and names no unit (`self.named` empty); `budget` (D3) is given
and returns a number; `yolo.merge.require_ci` is false; `out.window_s > 0`.

## D3 How long

`yolo_step(..., budget: Callable[[], float | None] | None = None)`. The orchestrator passes
`lambda: job_remaining_s(cfg, app.environ, clock.now(), waits.began)` for a CI run (`in_ci`), None otherwise.
The wait is `min(out.window_s + WINDOW_SLACK_S, budget() - MERGE_RESERVE_S)` with `WINDOW_SLACK_S = 15` and
`MERGE_RESERVE_S = confirm_wait_s + 150` (the merge push, the 30 s confirmation, `_integrate`'s post-merge work). No
wait when that is not positive.

## D4 During the wait

Sleep in slices of at most `WINDOW_POLL_S = 60` through the step's `sleep`; after each slice, read H's CI once
(`read_handoff_ci` with the step's `now`). When the read is no longer `NOT_CREATED_YET` (CI appeared, or the window
closed), stop waiting. A read error stops the wait too (the guard then reports it as today). Log at the start:
`<unit>: no CI on H yet; waiting up to <N> s for the hand-off window (ends <time>) before merging`, so a person whose
run queues behind this job sees why.

## D5 After the wait

Call `merge_guarded` again from the start (it re-reads the PR, the branch tips and, through `before_push`, the plan under
the lease, so a cancel or stop made during the wait holds). Its outcome is handled as any first outcome; it is never
waited on twice in one step.

## D6 Fallback

When the wait ended because the budget ran out and the window is still open (`window_s > 0` on the last read), the
step records the wait as today (`_wait_merge`) and returns `start_next_run=True`, once: a step that did not wait at all
(no budget, too small a budget) starts no run, as today. L4-YOLO-089's rule on runs with nothing changed is kept: the
chained run is started only by a step that waited.

## D7 Not changed

`preview()` (`l4 run --unit`) and the read-only step never sleep. `merge: human` plans do not merge and never reach
this path. Repositories whose PR CI is merely slow still wait for it as today (running CI is not the window).
