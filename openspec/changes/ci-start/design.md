# Design: ci-start

## Context (verified on amaster e66cde82)

- GitHub `start_run` → `dispatch_continuation` skips only when a run is *waiting*; GitLab `start_run` posts
  `POST /pipeline` and skips nothing. `base_runs` counts queued plus running runs (github: the newest 20 runs of
  `l4.yml`; gitlab: base pipelines; local). Nothing reads when the last run ended.
- Helpers: `start_run_result` and `how_to_start` (retry.py), `duration_seconds` (config/schema.py), the error pattern of
  `ci/watch.py`.

## D1 The forge call

`base_activity(ref) -> tuple[int, datetime | None] | None`: active = queued + in progress (the same listing as
`base_runs`); last_ended_at = the newest completed run's `updated_at` (GitHub run, GitLab pipeline `finished_at` or
`updated_at`); None when the listing fails or the forge type has none.

## D2 The command

`run_ci_start(app, cfg, *, if_idle: str | None)`: parse the duration (exit 2 when bad); require the forge token (exit
3 with the `how_to_start` line); `base_activity`: None → exit 3 "cannot tell whether a run is going; nothing started";
active > 0 → exit 0 "a run is queued or running; nothing started"; last ended < DURATION ago → exit 0 "the last run
ended N min ago (< DURATION); nothing started"; else `start_run` → exit 0 "started" with the run's link when known,
exit 3 when the forge refuses. Wire it in `_SPECS`, `HANDLERS`, `OWNING_CHANGE` and add the SPEC §2.1 row (the CLI
spec test fails without it).
