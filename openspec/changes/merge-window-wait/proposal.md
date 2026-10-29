# A plan waits out the hand-off CI window inside the run

## Why

After a unit's hand-off (`pr.ready`), the guarded merge treats "no CI on H yet" as running for ten minutes
(L4-CI-014), because a repository's CI may not have started. A `merge: auto` plan whose current unit is in that window
records `plan.waiting{merge_not_ready}` and starts no next run (L4-YOLO-013: once, not again while the detail holds).
Nothing then wakes the plan when the window closes: the next scheduled run, a person's command or a person's resume
does. On consumers this cost one manual resume per unit, and up to a schedule interval of idle time per unit, on every
repository whose pull requests to the target run no CI [V, plan ledgers of 2026-10-26 and 2026-10-27: seven units in
a row waited, each resumed by hand after the window].

`start_run` cannot start a run later: a run started now queues behind this one and arrives inside the window again.

## What changes

- When the only cause of `not_ready` is the window (`NOT_CREATED_YET`), the plan step of a CI run with a known job
  budget waits in the run for the rest of the window, re-reading H's CI about every 60 s, and then asks the merge guard
  again from the start. CI that appears during the wait ends the wait early, and the normal path records it.
- The wait is bounded by the job budget (`job_remaining_s`) minus a reserve for the merge, its confirmation and the
  integration. When the budget ends the wait before the window closes, the wait is recorded as today and the run starts
  the next run once; that run waits out the rest the same way (`_merge_wait_gone`).
- No wait outside CI, with an unknown budget, in a named run (`l4 run --unit`), in a read-only step, with
  `yolo.merge.require_ci: true`, or when a required check is named (the read is then `unreported`).
- `read_handoff_ci` exports `window_remaining(ready_at, now)`, which shares the skew clamp of `_in_window`;
  `MergeOutcome` carries the seconds left of the window, so no caller matches the detail text.
- `now` is passed through `merge_guarded` → `_ci_gate` → `read_handoff_ci`, so tests drive the clock.

## Impact

- Code: `l4.ci.handoff_ci`, `l4.yolo.merge` (`merge_guarded`, `_ci_gate`, `MergeOutcome`), `l4.yolo.cycle` (`_merge`,
  `_merge_wait_gone`, `yolo_step`), `l4.orchestrator` (passes the budget to `yolo_step`).
- Spec: L4-YOLO-012, L4-YOLO-013, L4-CI-014 amended; SCN-YOLO-122 amended; SCN-YOLO-240 to SCN-YOLO-245 added;
  change-table row 87.
- A CI job holds the `l4` concurrency slot for up to the rest of the window; a person's run queues behind it for at
  most about ten minutes, and the job's log says why it waits.
