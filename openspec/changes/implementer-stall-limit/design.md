## Context

Read at 0.4.60 (663cd6d5):

- `src/l4/agents/proc.py:139-195` `ProcRunner._wait`: the soft deadline is checked first (`run_deadline.fired()`, 147-157:
  `interrupted` and `deadline` set, `stopped_idle_s` cleared); then the idle rule (162-169: `watch.stopped_idle_s` is
  set and the group gets SIGINT); then the wall-clock limit (170: `timed_out`); SIGKILL follows 5 s after the SIGINT. An
  idle stop that crosses the wall-clock limit inside that grace sets both flags. Every adapter maps `timed_out or
  stalled` to status `timeout` (`claude_code.py:194`, `codex.py:259`, `opencode.py:377`, `kiro_cli.py:251`, and the
  others), so the status alone does not tell an idle stop from a time-limit stop; `watch.stopped_idle_s` does.
- `src/l4/implementer/tdd.py:1061-1210` `agent_step`. `base = wb.head()` (1070); `carried = apply_near_pass(...)`
  (1086); the run (1126-1138, inside `wb.wip_snapshots`); a `finally` (1138-1157) that always runs `wb.discard_scratch()`,
  `revert_protected(wb.git, wb.protected, base, ...)`, `revert_gate_config`, `revert_python_encoding`,
  `wb.restore_ledger` and `wb.check_env`; then the idle record (1158-1171), `agent.finished` (1172-1177), cost
  (1182-1187), the soft deadline's `DeadlineReached` (1188-1189), `RoleLimit` for `LIMIT_STATUSES` (`quota`,
  `rate_limited`, `auth`: 1190-1191), the silent `RoleLimit` (1192-1197), and the failed `StepOutcome` for any other
  status that is not `ok` (1198-1210).
- 1158-1171: `silent = run.status == "timeout" and beat.counts and beat.tool_calls == 0 and
  len(wb.cfg.roles.implementer) > 1`; `again = silent and _silent_before(wb, task)`; `SILENT_AGAIN` is `silent: already
  once for this task` (1027). `_silent_before` (1049-1058) reads `agent.idle{silent: true}` of the task and fix unit in
  `deadline.window`. A time-limit stop writes no `agent.idle` and no other record with a task, so nothing in the ledger
  says that it happened except `agent.finished{status: timeout}` and `step.finished`.
- `LimitSignal.kind` is a `Literal` that ends in `"silent"` (`src/l4/agents/base.py:48`). `Factory.on_limit`
  (`src/l4/agents/factory.py:353-370`) calls `cool_limited` (332-351: `record_cooldown`, `probes.invalidate`), then
  `for_role` from the top of the chain, and raises `WaitingCapacity` when it hands back the profile that limited.
  `cooldown_until` (`availability/fallback.py:239-245`) gives `default_cooldown` when `resets_at` is None.
  `record_cooldown` (577-591) writes `availability.cooldown{role, profile, tool, model, until, kind, source}`; the
  fallback writes `availability.fallback{role, from, to, reason, resets_at}` with `reason` the limit's kind
  (`factory.py:365-369`). `Cooldown.from_json` accepts any string as `kind` (`availability/cooldown.py:179-190`).
- `src/l4/orchestrator.py:1203-1209` catches `RoleLimit` in `_implement`, keeps `exc.carry` in `carries`, and calls
  `_fall_back` (1351-1363): `_record_limit` (960-965, `availability.limit{tool, kind, source, excerpt}`),
  `wb.discard_changes()`, `switch_profile` (1235-1257), a rebuilt workbench with the baselines carried over.
  `switch_profile` asks with the task's veto (`_task_veto`, L4-IMP-094) and records `PreviousAttempt(profile, kind,
  task, detail=...)`, with `detail` only for kind `silent` (1255). `Workbench.discard_changes`
  (`implementer/workbench.py:823-830`): `checkout HEAD -- .` except the ledger, `git clean -fdx` except the harness
  directories and the ledger, and `update-ref -d` of the unit's WIP ref.
- `src/l4/verifier/fixloop.py:339-355` `_fall_back` (the same: `availability.limit`, `discard_changes`,
  `ctx.shared["fall_back"]`, `PreviousAttempt` with `detail` only for kind `silent`, 356); `fix_hook` (431-441): a
  `RoleLimit` of a task already in `retried` cools the profile and is raised with no `discard_changes`; the first one
  moves the task once.
- `src/l4/implementer/loop.py:476-512` `seed_attempts` counts `task.attempt_failed` and `deadline.reached{when: during}`
  in `deadline.window` (after the task's last checkpoint, retry, resume or restart: `deadline.py:259-279`); a limit
  records neither, so the attempt number of the step that the next profile runs is the stalled step's again (as after
  every limit today; `agent_step` keeps both steps' logs with a `-r2` stem, 1077-1082). `run_green` (tdd.py:2263-2268),
  `run_red` (1650-1652) and `run_single` (3747-3760) call `wb.discard_changes()` when the step is not `ok`: a failed
  attempt discards the work too. A failed attempt does not hand on a near pass: `carry = done.near_pass` (loop.py:822),
  which is None for a stall. `_check_step` (loop.py:648-660) runs before every step.
- `src/l4/progress.py:281-296` `_agent_idle` prints `; no tool call was made, so it is a limit of the profile, not a
  failed attempt` when `silent` is true and `; <reason>, so it counts as a failed attempt` when `reason` is set.
  `_previous_attempt_block` (`tdd.py:835-858`) says `went silent: <detail>` for kind `silent` and `stopped on a <kind>
  limit` for every other kind. The runbook documents both texts (`docs/runbook.md:298-299`, 498-501, 540-550).
- `src/l4/eval/cellconfig.py:92` builds an eval cell with one implementer profile, so the cell is a chain of one.

Evidence is in the proposal.

## Goals / Non-Goals

**Goals:** an implementer step that stalls on a profile moves to another profile instead of spending the task's
attempts on it, once per task window; the next profile starts from a state that is defined and that every guard of
L4-IMP-002 and the green freeze still hold on; nothing about a verdict, a person-only action or the attempt bounds
changes; a stall that cannot move stays a failed attempt, so the change never parks a unit that would have retried.

**Non-Goals:** the ones in the proposal.

## Decisions

### D1. What a stall is, and where it is decided (L4-IMP-112)

In `agent_step`, after the cleanup and the two records, in this order: the soft deadline's raise (1188) stays first, then
`LIMIT_STATUSES` (1190), then the stall. A stall needs `run.status == "timeout"`. Its kind is:

- `silent`: `watch.stopped_idle_s` is set, the stream reader counted (`beat.counts`) and `beat.tool_calls == 0`. This is
  L4-IMP-087, word for word.
- `idle`: `watch.stopped_idle_s` is set and the stop is not `silent`: the reader saw at least one tool call, or the
  adapter has no stream reader (`beat.counts` is false: the `command` adapter). An idle stop that crosses the
  wall-clock limit inside the 5 s grace keeps the idle mark, so it is `idle` or `silent`, never `time`.
- `time`: `watch.stopped_idle_s` is None: the 1800 s limit stopped the step.

An adapter that found a limit on the run keeps it (`run if run.limit is not None`, as for a silent stop), so the
cool-down is that limit's. A stall is a limit of its profile (`as_limit`) when the chain holds more than one profile
(`len(wb.cfg.roles.implementer) > 1`, the silent stop's test, so a chain of one is a failed attempt as today), the task
has not used its stall limit (D3), and, for kinds `idle` and `time`, a profile can replace this one (D5). Otherwise the
stop is a failed attempt, with the reason it has today and, when it is a stall that could not move, a `reason` in its
record. The raise is `RoleLimit(run, carried)` with a `LimitSignal(tool, model, kind, None, source, excerpt)` that also carries the
spent veto of D5:
`source` is `run.idle` for `silent` and `idle`, and `run.timeout` for `time`; the `excerpt` is `no output for <limit>`
for `silent` (unchanged), `no output for <limit> after <n> tool calls` for `idle` (`no output for <limit>` when the
reader did not count), and `the agent step reached its time limit (<limit>)` for `time`, where `<limit>` is the idle
limit that applied (L4-IMP-099 may have raised it) or the step's `timeout_s`. `LimitSignal.kind` gains `"idle"` and
`"time"`.

Scope: `agent_step` is the one place an implementer step ends. It serves red, green and single (chore) steps of a unit,
a fix unit and a follow-up unit, all of which use `roles.implementer`. A judge, the verifier agent, the clarifier, the
delegate and the spec writer never reach it, and no status other than `timeout` changes.

### D2. The records (L4-IMP-116)

`agent.idle` keeps every field it has and gains optional ones: `kind` (`silent` or `idle`), `as_limit` (bool),
`discarded_files` and `discarded_paths` (D4). `silent` keeps its meaning for 0.4.60 readers: it is true exactly when the
kind is `silent` and `as_limit` is true. `agent.idle` is still written only when the idle rule fired, before
`agent.finished`. A new event `agent.time_limit{task, phase, attempt, profile, limit_s, tool_calls?, as_limit, reason?,
discarded_files?, discarded_paths?}` is written for a `time` stall, before `agent.finished`; `limit_s` is `timeout_s`, and
`tool_calls` is left out when the reader did not count. `reason` is set when the stall was not a limit (D3, D5).

A stall that is a limit also leaves what every limit leaves: `availability.limit{kind}`, `availability.cooldown{kind}`
and `availability.fallback{reason}`, with `kind` and `reason` `silent`, `idle` or `time`; the cool-down's `source` is the
signal's.

Texts. The failure reasons of a stall that stays an attempt are the ones of 0.4.60 (`the agent showed no activity for
...` and `the agent step reached its time limit (...)`). `SILENT_AGAIN` stays `silent: already once for this task`; the
other two are `idle: already once for this task` and `time: already once for this task`; the guard's is `<kind>: no
other profile can take the step`. The progress line of `agent.idle` appends `; <n> tool calls were made; it is a limit
of the profile, not a failed attempt` (`; it is a limit of the profile, not a failed attempt` when the count is unknown)
for kind `idle` with `as_limit`, keeps the silent text, and keeps `; <reason>, so it counts as a failed attempt`. A new
line for `agent.time_limit` (WARNING): `task <k> <phase> attempt <n>: <profile> reached the time limit (<limit>); it is a
limit of the profile, not a failed attempt`, or `...; <reason>, so it counts as a failed attempt`, or, with neither, `task
<k> <phase> attempt <n>: <profile> reached the time limit (<limit>)`. The next profile's previous-attempt block reads
`went silent: <detail>, so L4 stopped it` (unchanged), `went idle: <detail>, so L4 stopped it` or `ran out of time:
<detail>, so L4 stopped it`, each followed by `, while working on this task`, with `limit="idle"` or `limit="time"` in
the `<l4:data>` attribute; `PreviousAttempt.detail` is the signal's excerpt for all three kinds (`orchestrator.py:1255` and
`fixloop.py:356` test `kind == "silent"` today).

### D3. One stall limit per task window (L4-IMP-114)

`_silent_before` becomes `_stalled_before(wb, task) -> bool`. It reads `deadline.window(_ledger_events(wb), task.key,
fix_unit=...)`, as `_silent_before` does, and is true when an event of this task and fix unit is one of:

- `agent.idle` with `as_limit` true, or with no `as_limit` and `silent` true (a 0.4.60 silent stop);
- `agent.time_limit` with `as_limit` true.

The count is one for the three kinds together. Reasons to share it: the point of the rule is that a task cannot go
through every profile of the chain parking, whichever way each profile stalls, and the cost of a stall is one step on a
profile, not the kind of stall. A stall that was not a limit (`as_limit` false) does not count toward it, so a task's
second stall is a failed attempt and its third is too. The window is the one of L4-IMP-075: a checkpoint of the task
(`task.red_committed`, `task.green_committed`, `task.done`), `unit.retried`, `unit.resumed` and `unit.restarted` end
it. A `task.attempts_renewed` (L4-IMP-104) does not: an answer renews attempts, and the stall limit is not an attempt.
So between two checkpoints a task has at most one stall limit, and at most three in all (red, green, and a chore's
single step each have a window of their own). Every other stall is a failed attempt, bounded by L4-IMP-075 and
L4-IMP-094 as before.

### D4. What the next profile starts from (L4-IMP-113)

The chain, from the code above, for each exit of a stall that is a limit:

1. **The step's own cleanup** (`agent_step` 1138-1157) runs before the stall is decided, for every status: scratch
   dropped; `revert_protected` resets HEAD to `base` (`reset --mixed`), which drops a commit the agent made, and puts
   every protected path back to `base`, the frozen tests and the red tests among them; gate configuration, Python
   encodings and the ledger are restored; an environment directory that differs is removed and setup builds it again.
2. **The records.** `changed = sorted(p for p in wb.changed_files() if p != wb.ledger_rel)` is read here, after step 1, so
   it is what the step leaves uncommitted. `discarded_files` is its length and `discarded_paths` its first 20.
3. **Unit loop.** `RoleLimit` reaches `_implement`; `carries[task] = exc.carry` keeps the near pass the step started from
   (None for red, for a single step and for a green step with no near pass); `_fall_back` records `availability.limit`,
   calls `wb.discard_changes()` (tracked files back to HEAD, untracked and ignored files removed, the unit's WIP ref
   deleted, the ledger and harness directories kept), switches the profile and rebuilds the workbench with the baselines
   carried over.
4. **Fix loop.** The same, in `fixloop._fall_back`, for a fix task's first move.
5. **Park.** When `switch_profile` finds no profile, it raises `WaitingCapacity` after step 3's discard, so the tree is
   clean at HEAD when the unit parks; the near pass in memory is lost, as for any limit (L4-IMP-100 keeps one for the
   run only).
6. **The next profile's step.** `_run_task` seeds the attempts (a stall limit adds no failure), resumes the red commit,
   and runs the step in a new session from the tree of step 3; `apply_near_pass` writes the near pass's patch from
   memory (the patch of the earlier attempt that passed every test, never the stalled agent's edits). Setup and the
   baseline run again (`wb.setup_at` and `wb.last_tested` were cleared). A red step starts from the unit's head with no
   test of the stalled step, and a green step from the red commit.

So the state is HEAD (the red commit for a green step, the unit's head for a red or single step), no uncommitted change
except the near pass, protected paths at `base`. Red's scope check, its test-tamper guards, the production guard, green's
freeze of the red tests and every gate run after an `ok` step (`run_red` 1657, `run_green` after 2268, `run_single`
after 3760): a stalled step has no result and reaches none of them, and nothing of it is committed, so nothing needs
them. The next profile's step passes through all of them as any step does. The freeze is held by step 1 as well as by the
discard.

Nothing is lost silently: the ledger records how many files and which (up to 20) the step left; the agent's redacted event
stream is published under `.l4-out/agent/<run>/`; `wip.snapshot{shas}` names the snapshots of the step (the WIP ref that
points at them is deleted by `discard_changes`, as for a failed attempt, so the objects are unreachable and git collects
them). Keeping the stalled step's edits for the next profile is not done: they are the work of a profile that stopped
making progress, they may be half-written, and a prompt that carries them would let a stalling profile's tree decide the
next one's.

Two differences from a failed attempt, both for the better. A failed attempt drops a carried near pass (`carry =
done.near_pass`, None); a limit hands it on. A failed attempt tells the next attempt a failure reason; a limit gives the
previous-attempt block (D2).

The fix loop's second limit of a task (`fixloop.py:431-435`) cools the profile and raises with no `discard_changes`. The
stalled step's edits and WIP ref would stay, and a later run could restore them (`refs/l4/wip`, L4-IMP-100). A stall
never takes that path: D6.

### D5. A profile must be able to replace this one, and the fallback must not pick a spent one (L4-IMP-115, L4-AVL-015)

`Workbench.stall_plan` is a new optional field, `Callable[[Task, str], StallPlan] | None`, that the owner of the workbench
sets (`None`, a bench in a unit test, means the chain-length test only and no veto). `StallPlan(replaceable: bool, veto:
Constraint)`. `agent_step` asks it once per stall, with the task and the step's phase (`role`: `red`, `green` or `single`).

**replaceable.** A new `Factory.can_replace(selected, constraints) -> bool` reads the cool-down registry and
`roles.implementer`, sends no probe, records nothing, and is true when the chain lists a profile `p` other than `selected`
such that:

- the cool-down key of `p` (`cooldown_key`, `(tool, model)`) differs from the key of `selected`, because recording the
  stall's cool-down cools every profile with that key, so a profile that shares it cannot take the step;
- `p` is not cooling now (`cooldowns.cooling`);
- every constraint of the request, the task's veto (L4-IMP-094) and the `veto` below among them, accepts `p`.

A stall of kind `idle` or `time` is a limit only when `replaceable` is true. `Orchestrator._workbench` sets a closure that
builds the selection the way `switch_profile` does (the task's own selection, or the run's) and calls `can_replace`.
`fixloop._child_workbench` sets one that also says not replaceable for an `idle` or `time` stall of a task already in
`retried` (the fix loop moves a task once after a limit and parks the unit on a second: D4).

**veto.** A limit fallback selects again from the top of the chain (`Factory.on_limit`, `factory.py:360`), so it can hand
the step to a profile that has used all its attempts of the phase. `_run_task` then ends the task at once
(`loop.py:753`, `failures[phase][profile] >= max_task_attempts` breaks the loop and the task halts on
`max_task_attempts`), while a profile before it still has attempts left. The veto of L4-IMP-094 (`_task_veto`) is set only
by a move of this run (`orchestrator.py:1342`), so a stall that follows no move has none, and neither has a silent stop of
0.4.60. So `stall_plan` also returns a `Constraint` built like `loop.spent_constraint`, from `seed_attempts` of the window
(`failures[phase]`, of this fix unit or of none): it refuses each profile whose failed attempts of the phase are at least
`implementer.max_task_attempts`, with the text `spent: <n> failed attempts of <phase> of task <k> (implementer.max_task_attempts
<m>)`. `agent_step` puts it on the stall's signal (`LimitSignal.veto`, a field outside equality and repr), and
`switch_profile` adds it to the task's own veto when it asks `Factory.on_limit` (`asked`). Both loops reach
`switch_profile`, so this is one change. It applies to the three kinds: for a silent stop it is a protection that 0.4.60
lacks, and nothing else about the silent stop changes. When the adapter found its own limit on the run, the signal is the
adapter's and carries no veto: that path is the genuine limit's, as before. `seed_attempts` is in `loop.py`, which imports
`tdd.py`; the closure is built where both are visible, which is why the plan is a field of the workbench.

Why `replaceable`: with no alternative, the limit would cool the only profile that can work (a stall is often the first sign
of a profile that is slow, not dead), then `for_role` finds nothing and the unit parks for `default_cooldown` (30m, above
`availability.wait_in_run`, so no in-run wait: L4-AVL-011), where today it retries at once. Every other unit and judge
that uses the same `(tool, model)` would skip it for that time. A failed attempt costs at most `escalate_after` tries and
moves the task by L4-IMP-017 as before.

A silent stop keeps its 0.4.60 behaviour and does not need `replaceable`: it did nothing, the profile is demonstrably not
working, and the park when nothing else is usable is the rule of L4-IMP-087. Residual risk: a profile that is not cooling
and that `can_replace` accepts can still fail its probe in `for_role`; then the unit parks, as it does for a silent stop.
It is named in the risks.

### D6. Interplay (L4-IMP-115)

- **Escalation (L4-IMP-017, L4-IMP-094).** A stall limit adds no `task.attempt_failed`, so it adds nothing to a profile's
  count toward `escalate_after` or `max_task_attempts`, starts no escalation and records no `implementer.escalated`. It
  is a limit fallback, so `switch_profile` asks with the task's veto and with D5's spent veto: it never takes a profile that
  is spent for the task's phase, whether or not a move of this run set the task's veto. It may take a profile that has used
  its share (`escalate_after`), as any limit fallback may. The run's profile follows the fallback as it does for any limit
  (`switch_profile`, 1238-1252): it moves when the stalled profile was the run's, so the next task starts on the new one.
- **Attempt window and renewal (L4-IMP-075, L4-IMP-104).** The failure counts are unchanged. The attempt number of the next
  step is the stalled step's again, as after every limit; the logs keep both. A renewal does not reset D3's count.
- **Soft deadline (L4-IMP-067, L4-IMP-068).** The deadline's cancel is checked first in the runner and in `agent_step`, so
  a step stopped by it is never a stall. A `time` stall used 1800 s of the run's budget; `step.timed` records the step as
  for a failed time-limit step today. The next profile's step goes through `_check_step` and is not started when it does
  not fit (`deadline.reached{when: before}`, not counted); the stall limit stays recorded and counts in D3.
- **In-run wait (L4-AVL-011).** A stall cools for `default_cooldown` (30m); `wait_in_run` is 5m by default, so the run does
  not wait for it. D5 keeps the case in which every other profile is cooling from reaching it.
- **A chain of one profile** is a failed attempt as today (the test is `len(roles.implementer) > 1`). So is an eval cell.
- **The fix loop** moves a fix task once after a limit. A stall in a fix task is a limit only when the task has not moved
  (D5), and then the first move is as in D4; otherwise it is a failed attempt.

### D7. The cool-down (L4-AVL-014)

A stall's signal has no reset time, so `cooldown_until` gives `availability.default_cooldown` (30m). That is the silent
stop's, it needs no key, and it fits the evidence: after one idle stop the same profile went silent again in 9 of 12
tries within the next attempt, so a profile should be left alone for longer than one attempt (10 minutes of idle plus the
work around it); `credits_cooldown` (24h) is for an account that has no credit left, not for a profile that stalled. A deployment that
wants another length sets `availability.default_cooldown`, which also changes the cool-down after a limit that gives no
reset time. The cool-down covers the profile's `(tool, model)` in the runner's cache (`$L4_CACHE/availability.json`, L4-AVL-003),
so judges and the delegate that use the same tool and model skip it too, as for any limit. When a runner's cache is not
kept between CI jobs, the cool-down lasts for the rest of that run only (inferred from L4-AVL-003; not re-derived here).
The cached hello of the profile is cleared (L4-AVL-005).

### D8. On by default, and no key

The change is on by default. It can only move a step to another profile; it records no result for the stalled step, adds
no pass, and every gate, guard and verifier check applies to the next profile's step as to any step. It never gives an
agent a person's action. The bound on steps is one extra step per task window (D3). A deployment that does not want it has
a chain of one profile. No key is added, because a key would have to be read by the orchestrator, the fix loop and the
step, and the silent stop has none.

### D9. Upgrade

A consumer moves its pin from 0.4.60 while units are in flight.

- A 0.4.60 ledger has `agent.idle{silent}` and no `kind`, `as_limit` or `agent.time_limit`. D3 counts a 0.4.60 silent stop
  as the task's stall limit. A task's failed attempts from idle and time-limit stops stay failed attempts: nothing is
  recounted, and a task that already failed twice that way and halted needs `l4 retry`, `l4 resume` or `l4 restart` as
  before. A task whose window holds those failures but no stall limit may take its first stall limit on the new pin.
- The cool-down file is read by `Cooldown.from_json`, which accepts any string as `kind`, so a 0.4.60 `l4 probe` reading a
  cool-down of kind `idle` or `time` prints it and skips the profile.
- A 0.4.60 reader of a new ledger sees `agent.idle` with the old fields (and `silent` false for `idle`) and an unknown
  event `agent.time_limit`, which it ignores; its `_silent_before` does not count the new stalls. That matters only if a
  pin moves back, and then a task may take one more stall limit.
- No file, label, plan or configuration changes. The `kind` `idle` and `time` appear in `availability.*` records of the
  new pin only.

## Risks / Trade-offs

- A profile that is slow but working is cooled for 30m after its first time-limit stop of a task and the task moves. The
  stalled step's 1800 s are paid either way; what is new is that the profile is skipped for a while. The task's second
  stall counts as a failed attempt, so a slow profile is never skipped more than once per task window. The runbook says
  how to read the records and when to move the profile later in the chain.
- OpenCode reports a tool call only when it ends, so a first call longer than the idle limit reads as a stall there
  (L4-IMP-087, L4-IMP-099 name it). It was a silent stop at the cost of one cool-down; it is now also an `idle` stop after
  a tool call. The limit is raised for the longest gate run, so a test run does not trigger it.
- An agent that finished its edits and hung before it exited is a `time` stall; the next profile redoes the work. That is
  cost, not a wrong result: the old path also threw the step away.
- A profile that D5 accepts can still fail its probe, and the unit parks with `retry_after` as for a silent stop.
- A cool-down is keyed `(tool, model)`: two profiles with the same adapter and model cool together, and D5 does not count
  one as the other's replacement.
- The attempt number of the step after a stall is reused, as after every limit; a reader that assumes one `step.started`
  per number already tolerates it.
