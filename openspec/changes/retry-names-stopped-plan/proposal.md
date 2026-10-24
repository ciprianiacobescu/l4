# `l4 retry` names the stopped plan that holds the unit

## Why

A consumer unit halted `baseline_failed` on a harness bug, which also stopped its delivery plan (`stopped:
unit_halted [<unit>]`). After the harness was fixed, `l4 retry --unit <unit> --reason …` answered `retried: now
implementing` and started a run on the base branch. That run did nothing: `plan agent-auth: stopped (holds 1 unit; none
of them runs until the plan is fixed, completed or its file is removed)`, `run: nothing to do`. The plan went on only
after `l4 yolo resume agent-auth --reason …`, which the retry output never named. One run of the plan's budget was
spent, and an operator who trusts the retry's output waits for a run that never comes.

## What Changes

- After a successful retry, `l4 retry` looks up the plans that hold the unit (the plan files at the base and their
  states, as `l4 yolo status` does). When one of them is `stopped`, it prints one line,
  `plan <id> is stopped (<stop reason>): the unit runs again after: l4 yolo resume <id> --reason TEXT`, and starts no
  run, because a run would find nothing to do; `l4 yolo resume` starts the run (L4-OPS-002's start is skipped as with
  `--no-run`, and the line says so). The exit code stays 0.
- A plan that is `active`, `waiting`, `reviewed` or in any other status changes nothing: the retry starts its run as
  before. Plan files that cannot be read, or states that cannot be fetched, change nothing either (the lookup is a hint,
  never a reason to fail the retry).
- `docs/SPEC.md`: L4-OPS-002 gains the exception and a scenario (the next free SCN-OPS id); the runbook's `halted`
  procedure says that a stopped plan needs `l4 yolo resume` after the retry; a change-table row; CHANGELOG 0.4.30.

## Impact

- Code: `src/l4/state/retry.py` (`run_retry`), with a small lookup over `l4.yolo.plans` and the plan states.
- No change to what the retry records or pushes, nor to `l4 yolo resume`, which an agent may already run without an
  `--extend-…` (L4-YOLO-051).
