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

Only the first silent stop of a task is a limit. Before classifying a stop as silent, `agent_step` looks for an earlier
`agent.idle{silent: true}` of the same task (and fix unit) in the unit's ledger, in the task's window (the one that
counts attempts: after the task's last checkpoint, a retry, a resume or a restart), whatever the profile and the run.
If there is one, the stop is a normal failed attempt and `agent.idle` carries `silent: false` and
`reason: "silent: already once for this task"`. Without this a chain whose profiles all go silent never halts: each run
cools one more profile, parks (exit 12), and the next run starts clean with no attempt counted. With it the task
reaches `max_task_attempts` and halts (exit 13) as before.

A run that already carries a limit (an adapter read a throttle and then ended `timeout`) raises that limit unchanged;
the silent signal is only made when the adapter found none.

## D2 What follows (existing code)

The limit path: the step's uncommitted work is discarded (a red commit stays), `availability.limit{kind: silent}`,
`availability.cooldown{kind: silent}` for `availability.default_cooldown`, the hello cache entry cleared,
`availability.fallback{reason: silent}`, the task goes on on the next usable profile with the previous-attempt note
("the profile went silent: no output for <N>"), and the next task starts on the run's new profile. A silent escalated
profile cools; the task goes back through the loop that replays its earlier failures. A fix task moves once as for a
limit; a second limit in the same fix task parks the unit, and the profile that hit it cools too (`Factory.cool_limited`),
so the next run does not select it again. With no usable profile left the unit waits for capacity, as for a limit.

## D3 Not changed

An idle stop after at least one tool call, the wall-clock time limit, `idle_timeout: 0`, the deadline's cancel, a
single-profile chain (counted as today, so it never parks on itself), judges and the delegate (they skip a cooling
profile in every role, as for limits).

A stream that reports a tool call only when it ends reads as silent while its first call runs longer than
`idle_timeout`. OpenCode (v1 and v2 share the reader) is one: its `tool_use` event arrives when the call is done. The
cost is one cool-down of that profile and a move, at most once per task, because a second silent stop of the task
counts (D1).
