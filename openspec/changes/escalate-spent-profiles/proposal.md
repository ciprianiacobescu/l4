## Why

A consumer's unit halted on a red step that its strongest implementer profile never ran in the run that halted. The
chain was `roles.implementer: [deepseek, glm, claude-sonnet]` with `implementer.escalate_after: 2` and
`implementer.max_task_attempts: 3`.

- Run A: deepseek was cooling, so the run selected glm. Red attempt 1 failed (the new tests passed before any
  implementation) and attempt 2 failed (the 30 minute timeout). Red moved to claude-sonnet
  (`implementer.escalated{from: glm, to: claude-sonnet}`), and the run's soft deadline ended the run before attempt 3.
- Run B: deepseek was usable again, so the run selected it, and the task started there. deepseek had no failure of the
  task, so the move before the first attempt (L4-IMP-075, D7b of `run-continuation`) did not happen. Red attempts 3 and
  4 failed on deepseek. The move after attempt 4 went one profile on, to glm, which already had 2 failures of this red
  from run A. Attempt 5 failed on glm, glm reached `max_task_attempts`, and the unit halted (exit 13). claude-sonnet,
  where run A had moved the step, ran no step in run B.

Two rules in the code cause this. `seed_attempts` (`src/l4/implementer/loop.py:364-390`) counts the earlier runs'
failures per profile, but nothing reads where an earlier run moved the step, so a run starts the step on its own
selected profile. And a move (`_escalate_if_due`, `:393-420`, through `Orchestrator._escalation_profile`,
`src/l4/orchestrator.py:1279-1295`, and `Factory.next_profile`) takes the first usable profile after the current one
whatever that profile's own count is; after the move, the loop checks only `max_task_attempts` (`loop.py:482`), so a
profile that has already used its `escalate_after` gets its last attempt and the unit halts with a later profile left.

## What Changes

- A profile is **spent** for a phase of a task when its failed attempts of that phase in the window of L4-IMP-075 (the
  earlier runs' and this run's) reached `max_task_attempts`. A move never takes a spent profile: the selection refuses
  it as a constraint (`spent: <n> failed attempts of <phase> of task <k> (implementer.max_task_attempts <m>)`) and walks
  on. Cooling, unusable and non-independent profiles are skipped as before.
- A move that lands on a profile which has itself failed `escalate_after` attempts of the phase, and has a later
  profile, moves on at once, before the next attempt. A refused move leaves the step on that profile with its attempts
  up to `max_task_attempts`. Each move goes to a later profile, so the moves are bounded by the chain.
- A run continues the window's move. Before the first attempt, when the newest `implementer.escalated` of the phase in
  the window moved it from a profile that comes after the run's selected profile, the first move is asked from that
  profile. In run B: from glm, to claude-sonnet, before attempt 3. When that move is refused (claude-sonnet cooling),
  `implementer.escalation_skipped` records `on` (the run's profile), and the step starts on the run's profile as today.
- A halt on a profile that has a later profile says why no later profile took the step: `; no later profile can take it
  (<reason>)` before `; last failure:`.
- A single run, a chain of one profile, `escalate_after: 0`, and the window after `l4 retry`, `l4 resume` or
  `l4 restart` keep their behaviour.

## Impact

- Code: `l4.implementer.loop` (`Seeded.escalated_from`, `seed_attempts`, `EscalationRequest.spent`, `spent_constraint`,
  `_escalate_if_due`, a new `_escalate_while_due`, `_run_task`), `l4.orchestrator.Orchestrator._escalation_profile`
  (the fix loop reaches it through `ctx.shared["escalate"]`), `l4.progress.ProgressLog._escalation_skipped`.
- Spec: L4-IMP-094 (new); amendments of L4-IMP-017 (the move skips spent profiles; a later run's start), L4-IMP-018 (the
  halt clause, the log line with `on`), L4-IMP-075 (the first move of a run), the records list (`on`, `failures` on
  `implementer.escalation_skipped`); SCN-IMP-500..509; change-table row 119. The runbook's escalation notes.
- Behaviour: in a run that continues a task whose step an earlier run moved, the step runs on the profile the move went
  to, not on the run's first profile; a cheaper profile that the step had moved past gets no attempt of that step in
  the window. A move never ends on a profile that has used its attempts. Per phase, the failed attempts stay at most
  `escalate_after × (k − 1) + max_task_attempts` (escalate-and-note D3).
- Not changed: the trigger of a move after a failed attempt (`escalate_after` ≤ failures < `max_task_attempts`), the
  halt rule (the current profile reached `max_task_attempts`), the selection's checks, the independence keeper, the
  limit fallback (L4-AVL-006), the events' existing fields, the previous-attempt block.
