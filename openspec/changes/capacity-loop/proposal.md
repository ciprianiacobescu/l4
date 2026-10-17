## Why

On a consumer repository a delivery plan burned 50 of its 80 runs in about 50 minutes and stopped with `limit_runs`.
Both implementer profiles failed the `hello` probe with `opencode authentication failed (login expired or rejected)`
(the provider key had stopped working). No profile was cooling, so by L4-AVL-007 the unit parked in `waiting_capacity`
with `retry_after` equal to the time of the park ("nothing but a fix ends it, the next run probes again"). The plan step
then saw the unit as actionable (the retry time had passed), resumed itself, dispatched the unit and chained the next run
(L4-YOLO-012). Each run took about 22 seconds, failed the same probe, and chained the next: one run a minute, every run
charged to the plan, until the run limit stopped it. The two rules are each right; together they loop.

## What Changes

- **A capacity wait never chains a run** (L4-YOLO-035): a plan step that dispatches a unit in `waiting_capacity` does not
  start the next run; the next trigger (the schedule, a push, a person's command) probes again.
- **A wait only a fix can end stops the plan** (L4-YOLO-035): when the current unit parks in `waiting_capacity` with no
  profile of the chain cooling, twice in a row for the same unusable profiles, the plan stops with
  `capacity_needs_fix`; the stop names the profiles, their failures (for example `opencode authentication failed`) and
  the fix (renew the secret the profile reads, or install the binary), and `l4 yolo resume` goes on after the fix.
- `l4 yolo status` and the runbook's stop table name the new reason and its fix.

## Impact

- `src/l4/yolo/cycle.py` (dispatch of a waiting unit, the stop), `src/l4/yolo/state.py` (the counter of fix-only parks,
  if needed), the unit's `availability.unavailable` event read for the cause; tests under `tests/unit/yolo/`.
- `docs/SPEC.md` (L4-YOLO-035, scenarios, the stop reasons table, the change row), `docs/runbook.md`, `docs/yolo-mode.md`,
  `CHANGELOG.md`.
