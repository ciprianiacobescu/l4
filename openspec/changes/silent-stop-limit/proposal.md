# An agent that goes silent without doing anything is a limit, not a failed attempt

## Why

On 2026-10-29 a consumer's run (L4 0.4.39; `roles.implementer` = a free OpenCode profile, then two others;
`escalate_after: 2`; `idle_timeout: 10m`) lost about 20 minutes on every task [V, the run's ledger]:

- the free profile's hello passed at the start of the run;
- then seven implementer steps in a row on that profile ended `agent.finished{status: timeout}`, each stopped by the
  idle watchdog after 10 minutes with no tool call (six with 0 tokens in and out, no 503, 429 or overload text);
- L4-IMP-024 counts an idle stop as a failed attempt, so each task moved to the next profile only after two dead
  steps, and the next task started on the silent profile again (the run's selected profile never changes, L4-IMP-017);
- the passed hello stayed cached, so nothing told selection the profile was useless.

A profile that is reachable but does nothing is, for the run, unavailable. The limit path already does what is
needed: it cools the profile, clears its cached hello, moves the run's profile, records the fallback, and does not
count the step (L4-IMP-017, L4-AVL-006).

## What changes

- An implementer step stopped by the idle watchdog (L4-IMP-024) with no tool call seen by its stream reader is a
  *silent stop* when `roles.implementer` lists more than one profile. It raises the role limit with kind `silent`:
  `availability.limit{kind: silent}`, a cool-down of the profile for `availability.default_cooldown`, its hello cache
  cleared, `availability.fallback{reason: silent}`, the run's profile moved when it was the run's, and no failed
  attempt (no `task.attempt_failed`, nothing toward `escalate_after` or `max_task_attempts`).
- `agent.idle` gains `silent: true|false`; the previous-attempt note of the next step says the profile went silent.
- An idle stop after at least one tool call, a step that reaches its time limit, and every idle stop of a chain with a
  single profile count as before.
- Tokens are not used to decide: most adapters read usage only from their final event, so any killed run reads 0/0.

## Impact

- Code: `l4.implementer.tdd` (`agent_step`), `l4.agents.base` (the limit kind), `l4.availability` (the kind's
  cool-down), the progress lines and the previous-attempt wording.
- Spec: L4-IMP-087 added; L4-IMP-024, L4-IMP-017, L4-AVL-003, L4-AVL-005, L4-AVL-006 amended; SCN-IMP-202 amended;
  SCN-IMP-426 to SCN-IMP-431 added; change-table row 92.
- Risk: an agent whose first tool call runs, or which thinks, longer than `idle_timeout` with nothing printed reads as
  silent; it costs a cool-down of that profile and a move, no attempt.
