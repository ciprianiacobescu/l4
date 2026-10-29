# The tasks of a fix unit move along the implementer chain

## Why

L4-IMP-017 moves a task phase that fails `escalate_after` times to the next usable profile of `roles.implementer`. It
also says "The tasks of a fix unit MUST NOT move", and a single-phase task (a `[chore]` of a fix unit or a follow-up)
never moves anywhere:

- fix units run their tasks through `fix_hook` → `run_task(wb, task)` with no `escalate` hook (src/l4/verifier/fixloop.py),
  so `_escalate_if_due` returns at once;
- follow-up units do get the hook, but `_escalate_if_due` returns on `phase == "single"` (src/l4/implementer/loop.py).

The only reason recorded for the exclusion is scope ("no hook", escalate-and-note design). A fix chore that the cheap
first profile cannot do therefore halts the unit after `max_task_attempts` on that profile, while a stronger profile is
configured and idle. The owner decided on 2026-10-29 to reverse the rule.

## What changes

- A single-phase task moves like red and green: `_escalate_if_due` no longer returns on `single`;
  `EscalationRequest.phase` takes `"single"`; the attempt number of a single step is the one it already uses
  (`attempts["green"]`).
- `fix_hook` receives the escalation hook: the orchestrator exposes its selection step through `ctx.shared` (as it does
  for `implementer` and `fall_back`), `fix_hook` builds the task's workbench on the selected profile, carries the
  baselines over, sets the previous-attempt note, and passes `escalate=` to `run_task`. After each task the selection
  is cleared, as the unit's own loop does, so the next task starts on the run's profile.
- The run's selected profile and the profile the fix loop reads still never change. A limit on a moved profile cools
  that profile only.
- L4-IMP-017's sentence "The tasks of a fix unit MUST NOT move" is replaced; SCN-IMP-183 is amended in place to a (+) scenario;
  the runbook's known limit on it is removed.

## Impact

- Code: `l4.implementer.loop`, `l4.verifier.fixloop`, `l4.orchestrator` (the `ctx.shared` key, the child workbench).
- Spec: L4-IMP-017 amended; SCN-IMP-183 amended; SCN-IMP-420 to SCN-IMP-422 added; change-table row 88; runbook §11.
- An escalation inside a fix unit adds a profile to the unit's implementer profiles, which can narrow the judges that
  pass the independence rule in a later round; the selection already refuses a profile that would leave no judge.
