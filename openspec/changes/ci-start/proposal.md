# `l4 ci start` starts the harness's CI run only when it is idle

## Why

People drive plans from a laptop with hand-written dispatchers (`gh workflow run` in a loop) that start a run while
another is queued or running, or right after one ended. L4 has `start_run` on both forges but no command that asks
first. The owner chose this before the other local-run phases (docs/plan/proposal-local-runs.md §4).

## What changes

- `l4 ci start [--if-idle DURATION]`: on the base branch, start the harness's CI run (GitHub: `workflow_dispatch` of
  `l4.yml`; GitLab: `POST /pipeline` with the forge token) only when no run of the harness is queued or running on any branch (the job holds one concurrency group for the
  repository) and, with
  `--if-idle`, the last one ended at least DURATION ago. It prints what it did or why not.
- `Forge.base_activity(ref) -> (active: int, last_ended_at: datetime | None) | None` on the GitHub, GitLab and local
  forges, from the run listings of the whole repository's group (not `base_runs`' base-only one); None means the forge cannot tell, and then nothing is started.
- Exit codes: 0 when a run was started or the forge said busy/recent (a loop goes on); 3 when the token is missing, the
  forge refuses, or it cannot tell (a loop notices); 2 for a bad duration.

## Impact

- Code: a new `l4.ci.start`, `l4.forge.github`, `l4.forge.gitlab`, `l4.forge.local`, `l4.forge.base`, the CLI tables
  (`_SPECS`, `HANDLERS`, `OWNING_CHANGE`).
- Spec: L4-OPS-024 added; the §2.1 command row; the stale `L4_TRIGGER_TOKEN` bullet amended; SCN-OPS-46 to SCN-OPS-50 (and 46a);
  change-table row 96. `l4 yolo drive` is not in this change.
- Risk: GitHub's run listing lags right after a dispatch, so two callers seconds apart can both start one. The idle time is measured with this machine's clock against the forge's
  timestamps, so a skewed laptop clock shifts it by the skew.
