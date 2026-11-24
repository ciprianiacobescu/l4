## Why

A plan of seven units, 51 leaf tasks and 171 implementer calls ran on a chain of two free profiles and then a paid one
(`roles.implementer`). A ledger study of it found this:

- 32 of the 171 calls ended in an idle stop or at the agent's 1800 s time limit. They used 586 agent minutes, about
  18% of the plan's in-run time.
- After one free profile's idle stop, the next attempt on the same profile went silent again in 9 of 12 cases.
- One free profile took 9 of the 10 time-limit stops and succeeded in 10 of its 29 calls.
- Each of these stops was a failed attempt. The task spent its attempts on a profile that was stalling, and its
  escalation moved on only after `implementer.escalate_after` of them.

L4 already treats one kind of stall as a limit of the profile: an idle stop in which the stream reader counted no tool
call (a silent stop, L4-IMP-087). The profile cools, the task goes on on the next profile, and nothing counts. The two
stops above are the same fault, a profile that is not making progress, but they count.

Verified at 0.4.60 (663cd6d5):

- `src/l4/implementer/tdd.py:1158-1171` makes the stop `silent` only when `run.status == "timeout"`, the stream reader
  counted, `beat.tool_calls == 0` and `roles.implementer` lists more than one profile; `_silent_before` (`:1049-1058`)
  makes a task's second silent stop a failed attempt (`:1027`, `SILENT_AGAIN`).
- `:1192-1197` raises `RoleLimit` for a silent stop; `:1198-1210` turns every other non-`ok` status, an idle stop with
  tool calls and a time-limit stop included, into `StepOutcome("failed")`.
- The agent's time limit is `RunRequest.timeout_s = 1800` (`src/l4/agents/base.py:178`; `deadline.AGENT_TIMEOUT_S`);
  no key sets it. `implementer.idle_timeout` is 10m (`src/l4/config/schema.py:649`); a limit without a reset time
  cools for `availability.default_cooldown`, 30m (`:628`).
- A time-limit stop writes no `agent.idle` (only the idle mark does, `:1159`), and `availability.limit` has no task
  field, so the once-per-task rule of a silent stop cannot see it today.

## What Changes

- An implementer step that stalls is a limit of its profile when another profile can take the step, and no failed
  attempt. A stall is one of three kinds: `silent` (an idle stop with no tool call: L4-IMP-087, unchanged), `idle` (an
  idle stop after at least one tool call, or from an adapter with no stream reader) and `time` (the agent's 1800 s
  limit). The profile cools for `availability.default_cooldown`, its cached hello is cleared, the task goes on on the
  next usable profile in a new session, and the next task starts there too (L4-IMP-112, L4-AVL-014).
- The step's uncommitted work is discarded, as it is after any failed attempt and any limit. A red commit stays. A near
  pass that the step began from is handed on, so the next profile starts from the same tree. The ledger says how many
  files were discarded (L4-IMP-113).
- A task has one stall limit per attempt window, across the three kinds. The next stall of the task, on any profile,
  is a failed attempt as before. A 0.4.60 silent stop in the window counts as the first (L4-IMP-114).
- A stall of kind `idle` or `time` is a limit only when a profile with another cool-down key is not cooling and is
  not refused by the task's veto, and, in a fix unit, when the fix task has not already moved. Otherwise it is a failed
  attempt as today, so a stall never cools the last profile that can work or parks a fix unit (L4-IMP-115, L4-AVL-015).
- The fallback of every stall limit, the silent stop included, refuses a profile that is spent for the task's phase, also
  when no move of the run set L4-IMP-094's veto, because a fallback selects from the chain's start and a spent profile ends
  the task at once with `max_task_attempts` while an earlier profile has attempts left (L4-IMP-115).
- The new records are `agent.idle{kind, as_limit, discarded_files}`, a new `agent.time_limit`, and `kind` `idle` or
  `time` on `availability.limit`, `availability.cooldown` and `availability.fallback`. The runbook says how to read
  them and when to reorder a chain (L4-IMP-116).

Non-goals: a configurable agent time limit; editing a consumer's role chain; any other role (judges, the verifier agent,
the clarifier, the delegate, the spec writer) and any other status of an implementer step (`error`, `max_turns`,
`budget`, `permission_blocked`); a new configuration key; changing the silent stop's behaviour (it keeps parking when no
profile is usable); keeping the stalled step's edits for the next profile.

## Capabilities

### New Capabilities

- `implementer-stall-limit`: L4-IMP-112 (a stall is a limit of the profile), L4-IMP-113 (what the next profile starts
  from), L4-IMP-114 (one stall limit per task window), L4-IMP-115 (when a stall stays a failed attempt, and the
  interplay with escalation, the attempt window, the soft deadline and the fix loop), L4-IMP-116 (the records and
  texts), L4-AVL-014 (the cool-down kinds), L4-AVL-015 (an alternative must exist).

### Modified Capabilities

These requirements and scenarios of `docs/SPEC.md` say a stop after a tool call, or a time-limit stop, is a failed
attempt, or that a silent stop is the only stall limit. Each is amended in place, with a pointer to the new
requirement; none changes for a chain of one profile or for a task's second stall.

- L4-IMP-017 (the failed-attempt definition lists the limits that do not count), L4-IMP-024 (the failure reasons and
  the progress line), L4-IMP-087 (the closing "SHALL count as before" sentence), L4-AVL-003, L4-AVL-005 and L4-AVL-006
  (`kind: silent` is one of three stall kinds).
- The `agent.idle` record of §12.1 and the `idle_timeout` comment of the configuration reference.
- SCN-IMP-202, SCN-IMP-204, SCN-IMP-427, SCN-IMP-428 and SCN-IMP-545 now name the case in which the stop counts (one
  profile, or the task's second stall). SCN-IMP-426, SCN-IMP-438 and SCN-IMP-540 are unchanged.

## Impact

- `src/l4/implementer/tdd.py` (`agent_step`, `_silent_before`, `_previous_attempt_block`), `src/l4/implementer/workbench.py`
  (`Workbench.stall_plan`), `src/l4/agents/base.py` (`LimitSignal.kind`, `LimitSignal.veto`), `src/l4/agents/factory.py` (a new
  `Factory.can_replace`), `src/l4/orchestrator.py` (`_workbench`, `switch_profile`), `src/l4/verifier/fixloop.py`
  (`_child_workbench`, `_fall_back`, `fix_hook`), `src/l4/progress.py` (`_agent_idle`, a new `_agent_time_limit`).
- `docs/SPEC.md`, `docs/runbook.md`, `CHANGELOG.md`. No change to the skill.
- Ledger: new optional fields on `agent.idle`, one new event `agent.time_limit`, two new values of `kind`. An older
  reader ignores all of them. No configuration key, no new CLI option.
- Behaviour: a chain of two or more profiles stops spending failed attempts on the first stall of a task and moves
  the step instead. The cost is at most one extra step per task and attempt window, and the stalled step is paid for
  either way. A task whose profile cools may park the unit as any limit does (L4-AVL-015 names when it cannot).
