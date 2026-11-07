## Context

What the code does today [V: read at the cited lines of amaster 145c910f]:

- `seed_attempts` (`src/l4/implementer/loop.py:364-390`) reads the task's events in its window (`deadline.window`: after
  the task's last `task.red_committed`, `task.green_committed` or `task.done` of the same fix unit, or the last
  `unit.retried`, `unit.resumed` or `unit.restarted`). It counts `task.attempt_failed` per phase and profile, keeps their
  `(profile, reason)` oldest first, and the highest attempt number (a `deadline.reached{when: during}` included). It
  does not read `implementer.escalated`.
- `_run_task` (`:455-565`) seeds its counters from it (`:460`). Before the first attempt (`:475-479`, D7b of
  `run-continuation`) it calls `_escalate_if_due` up to `len(roles.implementer)` times, while the profile it is on has
  failed at least `escalate_after` and fewer than `max_task_attempts` attempts of the phase and has a later profile. The
  first call is made on the workbench's profile, which is the run's selected profile (`Orchestrator._implement` passes
  the run's workbench).
- After each failed attempt (`:551`) it calls `_escalate_if_due` once. At the top of the loop (`:482`) it stops when
  the current profile has failed `max_task_attempts` attempts, and halts (`:552-565`) with `profiles` and the detail
  of L4-IMP-018, built from `failures[current]`, which holds the seeded profiles too.
- `_escalate_if_due` (`:393-420`) builds an `EscalationRequest(task, phase, profile, failures, attempt)` and calls the
  hook. The unit's hook is `Orchestrator._escalate` (`src/l4/orchestrator.py:1264-1277`), which selects through
  `_escalation_profile` (`:1279-1295`): `Factory.next_profile("implementer", unit, request.profile,
  constraints=(keeper,))` (`src/l4/agents/factory.py:230-249`), the first usable profile after `request.profile`, with
  the checks of `FallbackSelector.select(after=…)` (`src/l4/availability/fallback.py:329`): a constraint, then the
  cool-down, then the probe (`_veto`, `:391-412`). The fix loop's hook (`src/l4/verifier/fixloop.py:356-380`) calls the
  same `_escalation_profile` through `ctx.shared["escalate"]`. A refusal is `str(RoleUnavailable)` and is recorded as
  `implementer.escalation_skipped{task, phase, from, failures, reason}`.
- Nothing in the selection reads the failures of the profile it takes.

The consumer's two runs, as the ledger recorded them, with `[deepseek, glm, claude-sonnet]`, `escalate_after: 2`,
`max_task_attempts: 3`:

| Run | Step | Profile | Result | Counts after (red) |
|---|---|---|---|---|
| A | (selection) | glm | deepseek cooling | – |
| A | `4.1/red/1` | glm | the new tests pass before any implementation | glm 1 |
| A | `4.1/red/2` | glm | timeout (30 minutes) | glm 2 → `implementer.escalated{from: glm, to: claude-sonnet}` |
| A | `4.1/red/3` | claude-sonnet | not started: the soft deadline | – |
| B | (selection) | deepseek | usable again; 0 failures, so no move before the first attempt | glm 2 |
| B | `4.1/red/3`, `/4` | deepseek | failed | glm 2, deepseek 2 → move to the first usable after deepseek: glm |
| B | `4.1/red/5` | glm | failed | glm 3 = `max_task_attempts` → halt, exit 13 |

claude-sonnet ran no step in run B.

## Goals / Non-Goals

**Goals:** a move never takes a profile that has no attempt left for the step; a move that lands on a profile which
has used its `escalate_after` moves on; a run continues the step where the window's last move took it; the halt says
why no later profile took the step. The guards stay: a move goes only to a later profile, never parks a unit, never
breaks the judges' independence, skips a cooling profile, and a single run behaves as today.

**Non-Goals:** carrying the task's profile from red to green across runs (the window starts again at the red commit,
and green starts on the run's profile as today); a move at `max_task_attempts` (the trigger stays below it); a change to
the run's selected profile, to the limit fallback (L4-AVL-006), to the previous-attempt block, or to the doctor.

## Decisions

### D1. Spent: the selection refuses a profile that has no attempt left

A profile is *spent* for phase P of task T when its failed attempts of P of T in the window, seeded and this run's,
are at least `max_task_attempts`. `_escalate_if_due` puts them in the request: `EscalationRequest.spent:
tuple[tuple[str, int], ...]`, each `(profile, failures)` with failures ≥ `max_task_attempts`, in the order of
`failures[phase]` (default `()`, so the test fakes and any other caller stay valid). `loop.spent_constraint(request,
limit)` returns a `Constraint` that answers `spent: <n> failed attempts of <phase> of task <k>
(implementer.max_task_attempts <limit>)` for a spent profile and `None` for any other.
`Orchestrator._escalation_profile` passes `constraints=(spent_constraint(request, cfg.implementer.max_task_attempts),
keeper)`.

So the veto is a step of the selection's own walk (`_veto`), next to `serves`, the keeper and the cool-down: the walk
goes on to the next profile, the skip is in `availability.selected.skipped` (step `constraint`) and in the console's
skipped line, a spent profile is never probed, and when nothing is left the refusal's reason names every profile and
why. The fix loop gets it through the same method.

*Alternative rejected:* retry the hook in the loop when it returns a spent profile. It would build a workbench, probe
and record a move for a profile that cannot run.

*Why `max_task_attempts` and not `escalate_after`:* a profile that has used its `escalate_after` but not
`max_task_attempts` still has attempts when nothing after it can take the step (escalate-and-note D3: "held to
`escalate_after` when a later profile can take over, and to `max_task_attempts` otherwise"). Vetoing it would leave the
step on a cheaper profile instead (A 3 attempts in place of B's last one, in a chain `[A, B, C]` with C cooling). D2
moves on from it instead, when a later profile can take the step.

### D2. A move re-checks where it lands

`_escalate_while_due(wb, …)` holds the loop that `_run_task` has before the first attempt today: it calls
`_escalate_if_due` while the call moves the step, at most `len(roles.implementer)` times. `_run_task` calls it before the
first attempt (as today) and after each failed attempt (in place of the single call at `:551`). So a move that lands on
a profile with failures ≥ `escalate_after` and < `max_task_attempts`, and a later profile, is asked again at once; a
refusal leaves the step on that profile, which keeps its attempts up to `max_task_attempts`, as after any refusal
(L4-IMP-017). Each move is recorded as `implementer.escalated`, which is what L4-IMP-075 already says of the moves before
the first attempt.

Bounded: every move goes to a profile after the current one (`next_profile` walks after `request.profile`), a spent
profile is never taken (D1), and the loop stops at the chain's length or at the first call that does not move.

In a single run the landed profile has no failure of the phase, so the re-check is a no-op and no hook call is added
[I: the counts start at 0 in a fresh window; a profile the step comes back to after a limit is covered by D3's
same-run cases below].

### D3. A run continues the window's move

`Seeded.escalated_from: dict[str, str]`: per phase, the `from` of the newest `implementer.escalated` of the task in the
window (same `task`, same `fix_unit` or none, as the failures are read). Before the first attempt, `_run_task` takes F =
`escalated_from[P]`. When F is in `roles.implementer` and comes after the run's selected profile R there, the first move
is asked from F: `_escalate_if_due(…, origin=F)` builds the request with `profile=F` and F's count, under the conditions
of L4-IMP-017 for F (escalation on; F failed at least `escalate_after` and fewer than `max_task_attempts` attempts of P;
a profile after F). The selection walks after F, `implementer.escalated` names F as `from`, and the previous-attempt
block names F (the profile that did fail). Then D2's loop goes on from where it landed. When the move is refused, the
harness records `implementer.escalation_skipped{task, phase, from: F, failures, reason, on: R}` and the step starts on R,
where today's rule (L4-IMP-075) applies to R's own count. When F is R, F is before R, or no move is in the window,
nothing is added: the start is today's.

Run B under this rule: F = glm, after deepseek; glm has 2 failures and a later profile; the walk after glm takes
claude-sonnet; `implementer.escalated{from: glm, to: claude-sonnet, failures: 2, attempt: 3}` is recorded before
`4.1/red/3`, and attempts 3 to 5 run on claude-sonnet. With three failures there the unit halts with `… reached in red
on glm (2), claude-sonnet (3); …`: 5 failed attempts in all, the bound of one run that started on glm.

Why this rule:
- L4-IMP-075 says that a run that hands back and continues must not give a task fresh attempts, and that the moves of
  the earlier runs are made again before the first attempt. The rule assumed the run starts on the profile the moves
  started from. Run B started on another one because the profile that run A skipped as cooling was usable again.
  Continuing from the recorded move makes the second run do what one longer run would have done: in one run the step
  stays on the profile it moved to for the rest of the task (escalate-and-note D8), even when an earlier profile's
  cool-down ends meanwhile.
- The ledger already holds the fact: `implementer.escalated{from, to}` of the window. No new record is needed to read it.
- Walking after F, not selecting F's old target by name, makes the same selection again with today's checks: a cooling
  target gives way to the next usable profile after it, and the independence keeper and the spent veto apply.
- The window ends at the task's commit and at `l4 retry`, `l4 resume` and `l4 restart`, so a retried task still starts on
  the run's profile with fresh counts (escalate-and-note D8, D11).
- The step does not lose time on a tier it had left. Each attempt of run B's deepseek ran up to the 30 minute timeout,
  and a soft deadline can end a run between those attempts and the move.

*Alternative rejected (R1): start at the run's profile and rely on D1 and D2 only.* It also runs claude-sonnet in run
B (deepseek fails 3 and 4, the move lands on glm with 2 failures and D2 moves on to claude-sonnet for attempt 5), and
it gives deepseek, which never ran the step, its share. But it gives the step attempts that one run would not have
given it, on the cheapest tier of a chain that is ordered cheap first, after a stronger profile of that tier already
failed; and with two attempts of up to 30 minutes each before the move, the next soft deadline can fall before
claude-sonnet runs at all.

*Alternative rejected (R3): select the old target by name.* It needs a new selection call, and a target that is
cooling would need its own rule.

*Same-run cases checked by hand* [I, against `tests/unit/orchestrator/test_escalation.py`]: after a limit on the moved
profile the task goes on in a fresh `run_task` of the same run (L4-AVL-006). In SCN-IMP-182 and SCN-IMP-430 the
newest move is from the run's profile (F = R), so nothing is added and the recorded moves stay `[(impl, impl-b), (impl,
impl-c)]`. When a step had moved twice in the run (A to B, B to C) and C hit a limit, F = B: the move from B is
refused (C cooling) and recorded with `on: A`, then today's rule moves A to B and B is refused again; the step ends on B
with its last attempt, as today, with one more `implementer.escalation_skipped`.

### D4. The halt says why no later profile took the step

`_escalate_if_due` and `_escalate_while_due` return the refusal reason with the workbench (`tuple[Workbench, str |
None]`). `_run_task` keeps the newest refusal recorded while the step was on its current profile (a move clears it). At
the halt, when `roles.implementer` lists a profile after the current one and such a refusal exists, the detail is
`task <k>: max_task_attempts (<n>) reached in <phase>[ on <p1> (<f1>), …]; no later profile can take it (<reason>);
last failure: <reason>`. The clause comes before `last failure`, which can be long. The profiles list is today's: every
profile with failures of the phase in the window, seeded ones included, in the order they ran it. A halt on the last
profile, with escalation off, without a hook, or with no refusal keeps today's detail; so does SCN-IMP-177's and
SCN-IMP-179's. `breaker.tripped` gets no new field.

### D5. The log line of a refused continuation

`implementer.escalation_skipped` with `on` prints `task <k> <phase>: <from> failed <n> attempts; no later profile can
take it (<reason>); it starts on <on>`. Without `on` the line is today's (`…; it stays on <from>`).

## Risks / Trade-offs

- A cheaper profile that was cooling when the step moved past it gets no attempt of that step for the rest of the
  window, as in one run. A person who wants the cheap tier to try again runs `l4 retry`, which starts a new window.
- A refused continuation costs one selection walk before the first attempt, and records one more
  `implementer.escalation_skipped`. A cooling profile is not probed; a profile whose probe is cached is not probed again.
- D2 records two moves where one would do (deepseek to glm, then glm to claude-sonnet, in SCN-IMP-501), and selects glm
  once without running it. It keeps the moves before and after the first attempt one rule, and each move readable on
  its own.
- The strongest profile runs sooner in a continued run. Its attempts stay bounded by `max_task_attempts`, and the
  phase's failed attempts by `escalate_after × (k − 1) + max_task_attempts`: only the profile the step halts on reaches
  `max_task_attempts` in a window, and the veto keeps any other from running again.
- A profile reaches `max_task_attempts` only as the profile the step halts on, and a halted unit goes on through
  `l4 retry`, `l4 resume` or `l4 restart`, which start a new window [I: the paths read; the spec edit after a stop is
  taken inside those commands]. So a spent profile in a window is expected after a configuration change during the
  window (a lower `max_task_attempts`, a reordered or renamed chain). The veto is there so that such a window never
  halts with a later profile left, and so that no move re-enters a profile in any case.
