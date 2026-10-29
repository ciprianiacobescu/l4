# Design: fix-unit-escalate

## Context (verified on amaster b4cf62b5, with the read-only analysis of 2026-10-28)

- `_run_task` selects `single` when the task has chore findings (a `[chore]` task in `.l4/fix.json` or
  `.l4/followup.json`); nothing else runs single.
- `_escalate_if_due` (src/l4/implementer/loop.py) returns when `not escalate or phase == "single" or not 1 <=
  limit_after < limit`; `EscalationRequest.phase` is `Literal["red", "green"]`; the request's attempt is
  `attempts[phase] + 1`, and `attempts` has only `red` and `green` keys (single counts in `attempts["green"]`), so
  `attempts["single"]` would raise.
- `failures["single"]` and `reasons["single"]` are seeded from earlier runs and filled after each failure.
- `Orchestrator._escalate` picks the next profile (with the independence check), builds the parent unit's workbench with
  `self._workbench(selected=chosen)`, copies the baselines, sets `PreviousAttempt(why="escalation", ...)` and
  `_task_selected`; the unit loop clears `_task_selected` after each task and a limit on the moved profile cools it
  (`switch_profile`).
- `fix_hook` (src/l4/verifier/fixloop.py) runs `run_task(wb, task)` on a child workbench from `_child_workbench`.
- Held checks (the test chore's discrimination hold included) return before a failure is counted, as for red and green;
  replay is keyed by task, check and question, not profile; the prompt's escalation note is phase-generic.

## D1 The loop

In `_escalate_if_due`: drop `phase == "single"`; widen `EscalationRequest.phase` to `Literal["red", "green",
"single"]`; the request's attempt is `attempts["red" if phase == "red" else "green"] + 1`. This alone makes follow-up
units move, including a move at the start of a later run from seeded failures (L4-IMP-075).

## D2 The fix loop

- The orchestrator puts its escalation entry point into `ctx.shared` under a new key (e.g. `"escalate"`), next to
  `"implementer"` and `"fall_back"`. Absent key → no hook (today's behaviour, and every test that builds a fix context
  without an orchestrator).
- `_child_workbench` takes `selected=` (default: the run's profile). `fix_hook` passes an `escalate=` callable to
  `run_task` that calls the shared entry point for the fix unit's workbench, so the moved profile, the copied baselines
  and the previous-attempt note land on the child workbench the task runs on.
- After each task (also on an exception: `try/finally`) the task's selection is cleared, so the next task starts on the
  run's profile.

## D3 Kept

- The run's selected profile and the profile the fix loop reads MUST NOT change.
- A limit on a moved profile cools that profile only, and the task goes on as after any limit.
- Held checks, `blocked` results, the hung frozen-test question and limits never count and never start a move.
- `max_task_attempts` is per profile and phase, as for red and green.

## D4 Not changed

The test chore's one-time hint on attempt 1 is not repeated for the new profile; the carried retry text holds it.
