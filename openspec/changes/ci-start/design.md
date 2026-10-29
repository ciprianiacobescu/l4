# Design: ci-start

## Context (verified on amaster e66cde82)

- GitHub `start_run` → `dispatch_continuation` skips only when a run is *waiting*; GitLab `start_run` posts
  `POST /pipeline` and skips nothing. `base_runs` counts queued plus running runs (github: the newest 20 runs of
  `l4.yml`; gitlab: base pipelines; local). Nothing reads when the last run ended.
- Helpers: `start_run_result` and `how_to_start` (retry.py), `duration_seconds` (config/schema.py), the error pattern of
  `ci/watch.py`.

## D1 The forge call

`base_activity(ref, *, branch_prefix="l4/") -> tuple[int, datetime | None] | None`. The harness's job holds one
concurrency group for the whole repository (GitHub `concurrency: l4`, GitLab `resource_group: l4`), so a run on any
branch that can start one makes a newly started run wait. `active` therefore counts the runs not over on every such
branch:
- GitHub: the newest 100 runs of `l4.yml` with no branch filter (the workflow is the harness's own); active = queued,
  in progress, waiting, requested, pending, and completed with the conclusion `action_required` (held for a person's
  approval, as `ci_run_state` reads it); `last_ended_at` = the newest other completed run's `updated_at`.
- GitLab: the newest 100 pipelines of the project, kept when the ref is `ref`, the project's default branch or starts
  with the unit-branch prefix (`forge.branch_prefix`); active = running, pending, created, preparing,
  waiting_for_resource, scheduled or canceling; `last_ended_at` = the newest finished one's `updated_at` (the list rows
  carry no `finished_at`; one is the fallback).
- None when a read fails, is not JSON, or a finished run has no readable end time; the local forge has no listing.
`base_runs`, `dispatch_continuation`, `start_run` and the relay keep their base-only listing: they decide something else.

## D2 The command

`run_ci_start(app, cfg, *, if_idle: str | None)`: parse the duration (exit 2 when bad); require the forge token (exit
3 with the `how_to_start` line); `base_activity`: None → exit 3 "cannot tell whether a run is going; nothing started";
active > 0 → exit 0 "a run is queued or running; nothing started"; last ended < DURATION ago → exit 0 "the last run
ended N min ago (< DURATION); nothing started"; else `start_run` → exit 0 "started" with the run's link when known,
exit 3 when the forge refuses. Wire it in `_SPECS`, `HANDLERS`, `OWNING_CHANGE` and add the SPEC §2.1 row (the CLI
spec test fails without it).
