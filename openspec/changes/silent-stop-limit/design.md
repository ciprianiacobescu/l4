# Design: silent-stop-limit

## Context (verified on amaster f592bc7d, read-only analysis of 2026-10-29)

- The step passes `stall_timeout_s = idle_timeout` (`tdd.py` `agent_step`); the process runner sends SIGINT when no
  line came and no tool call is open, and sets `watch.stopped_idle_s` (`proc.py`); OpenCode maps it to status `timeout`.
- `agent.idle{…, tool_calls}` is written before `agent.finished`; only `quota`, `rate_limited` and `auth` raise
  `RoleLimit`; a `timeout` returns `StepOutcome("failed", "the agent showed no activity for …")`, which the loop counts
  (`task.attempt_failed`, toward `escalate_after` and `max_task_attempts`).
- `switch_profile` → `Factory.on_limit` records `availability.cooldown`, clears the probe cache, selects again,
  records `availability.fallback`, moves the run's profile when the limited one was the run's, and raises
  `WaitingCapacity` when nothing is left. A limit is never an attempt (tests/unit/orchestrator/test_escalation.py).
- Every adapter passes a stream reader; tool calls are counted by it (the watch snapshot). Token usage is read only
  from the final event by claude-code and codex, and kiro reports none: tokens cannot tell a silent run.

## D1 The rule

In `agent_step`, after the run and before the existing limit check: a run whose status is `timeout` with
`watch.stopped_idle_s` set, whose watch saw a stream reader and 0 tool calls, while `len(roles.implementer) > 1`, gets
`LimitSignal(tool, model, kind="silent", reset_at=None, source="run.idle", detail="no output for <idle_timeout>")` and
raises `RoleLimit` like a quota. `agent.idle` carries `silent: true` then (false otherwise).

## D2 What follows (existing code)

The limit path: the step's uncommitted work is discarded (a red commit stays), `availability.limit{kind: silent}`,
`availability.cooldown{kind: silent}` for `availability.default_cooldown`, the hello cache entry cleared,
`availability.fallback{reason: silent}`, the task goes on on the next usable profile with the previous-attempt note
("the profile went silent: no output for <N>"), and the next task starts on the run's new profile. A silent escalated
profile cools; the task goes back through the loop that replays its earlier failures. A fix task moves once as for a
limit. With no usable profile left the unit waits for capacity, as for a limit.

## D3 Not changed

An idle stop after at least one tool call, the wall-clock time limit, `idle_timeout: 0`, the deadline's cancel, a
single-profile chain (counted as today, so it never parks on itself), judges and the delegate (they skip a cooling
profile in every role, as for limits).
