## Purpose

An implementer step that stalls on a profile, by an idle stop after tool calls or at the agent's time limit, is a limit
of that profile when another profile can take the step: the profile cools, the task goes on on the next profile from a
defined state, and the stop is no failed attempt. A task has one such limit per attempt window, and a stall that cannot
move stays a failed attempt.

## ADDED Requirements

### Requirement: L4-IMP-112 A stall of an implementer step is a limit of its profile, not a failed attempt
An implementer step (red, green or single, of a unit, a fix unit or a follow-up unit) whose agent run ends with status
`timeout`, and that the soft deadline did not stop, SHALL be a *stall*, of one of three kinds. `silent`: the idle mark is
set (L4-IMP-024), a stream reader counted, and it saw no tool call (L4-IMP-087). `idle`: the idle mark is set and the
stop is not silent, because the reader saw at least one tool call or the adapter has no stream reader. `time`: the idle
mark is not set, so the agent's wall-clock limit of 1800 s stopped the step. An idle stop that crosses the wall-clock
limit inside the 5-second grace after its SIGINT keeps the idle mark, so it is `silent` or `idle`. A stall SHALL be a
limit of its profile (L4-AVL-006) and no failed attempt when all of these hold: `roles.implementer` lists more than one
profile; the task has no earlier stall limit in its window (L4-IMP-114); and, for kinds `idle` and `time`, a profile can
replace this one (L4-IMP-115). Then the harness SHALL record the stall as L4-IMP-116 says, raise a limit whose kind is
the stall's kind (L4-AVL-014), and go on as after any limit: no `task.attempt_failed`, nothing toward
`implementer.escalate_after` or `implementer.max_task_attempts` (L4-IMP-017), the profile cooled, the task going on on
the next usable profile in a new session, and the next task starting there when the stalled profile was the run's.
A limit that the adapter itself found on the run SHALL be kept as it is. The soft deadline's cancel and every status
other than `timeout` SHALL be handled as before. A stall that does not meet all of the conditions SHALL fail the
attempt as before, with the reason it has today; its record SHALL carry `as_limit: false` and, when L4-IMP-114 or
L4-IMP-115 is why it did not move, the reason they name (L4-IMP-116). This
requirement SHALL NOT apply to any other role: a judge, the verifier agent, the clarifier, the delegate and the spec
writer SHALL keep their own rules.

#### Scenario: SCN-IMP-602 (+) An idle stop after tool calls is a limit and the task moves on
- **Given** `roles.implementer: [free, glm]`, `escalate_after: 2`, and a green step on `free` that made 14 tool calls and
  then printed nothing with no tool call open, while `glm` is usable
- **When** the idle watchdog stops it after 10 minutes
- **Then** `agent.idle{kind: idle, as_limit: true, silent: false, tool_calls: 14}`, `availability.limit{kind: idle,
  source: run.idle}`, `availability.cooldown{profile: free, kind: idle}` and `availability.fallback{reason: idle}` are
  recorded, and no `task.attempt_failed` is
- **And** the step runs again on `glm` in a new session whose previous-attempt note says `free` went idle (`no output for
  10m after 14 tool calls`), and the next task starts on `glm`

#### Scenario: SCN-IMP-603 (+) A time-limit stop is a limit and the task moves on
- **Given** `roles.implementer: [free, glm]` and a green step on `free` that prints a line every minute and reaches the
  agent's limit of 1800 s, while `glm` is usable
- **When** the step ends
- **Then** `agent.time_limit{as_limit: true, limit_s: 1800}` is recorded and no `agent.idle` is, with `availability.limit{kind:
  time, source: run.timeout}`, `availability.cooldown{profile: free, kind: time}` and `availability.fallback{reason: time}`
- **And** no `task.attempt_failed` is recorded, and `glm` runs the step with a note that `free` ran out of time (`the agent step reached
  its time limit (30m)`)

#### Scenario: SCN-IMP-617 (+) An idle stop of an adapter with no stream reader is an idle stall
- **Given** `roles.implementer: [script, glm]`, where `script` is a `command` profile whose adapter has no stream reader,
  and a step of it that prints nothing for the idle limit
- **When** the watchdog stops it
- **Then** `agent.idle{kind: idle, as_limit: true}` has no `tool_calls` count, `availability.limit{kind: idle}` has the
  excerpt `no output for 10m`, and the task moves to `glm` without a failed attempt

#### Scenario: SCN-IMP-618 (−) An idle stop that crosses the time limit in its grace keeps its idle kind
- **Given** a step whose idle rule fires in the same poll as the 1800 s limit, so that the runner sets both flags
- **When** the step ends
- **Then** it is an `idle` or `silent` stall by its tool-call count, `agent.idle` is recorded and `agent.time_limit` is not

#### Scenario: SCN-IMP-616 (−) A limit that the adapter found on a stalled run is kept
- **Given** `roles.implementer: [free, glm]` and a step on `free` that ends with status `timeout` after the adapter read a
  rate limit with a reset time from its stream
- **When** the step ends
- **Then** `availability.limit` and `availability.cooldown` carry that limit's kind and reset time, not the stall's, and
  `agent.idle` or `agent.time_limit` still records the stall

#### Scenario: SCN-IMP-619 (−) Another role's time-out is not a stall
- **Given** a judge, a verifier-agent writer, a clarifier and a delegate call that each time out, with a second profile in
  their chains
- **When** the calls end
- **Then** each is handled by its own rule as before, and no `agent.time_limit` and no `kind: time` cool-down is recorded

### Requirement: L4-IMP-113 The next profile starts from a defined state, and nothing of the stalled step is committed or carried
When a stall is a limit, the harness SHALL put the work tree back before the next profile's step, by the paths that every
limit takes. The step's own cleanup SHALL run first and for every status: scratch dropped, HEAD reset to the commit the
step began on (a commit the agent made is dropped), every protected path put back to that commit (the frozen and red
tests among them), gate configuration, Python source encodings and the ledger restored, and a changed environment
removed. Then `discard_changes` SHALL return every tracked file to HEAD, remove untracked and ignored files (the harness's
own directories and the ledger kept) and delete the unit's work-in-progress ref. A red commit SHALL stay. The harness
SHALL hand on only the near pass (L4-IMP-100) that the stalled step began from, as `RoleLimit.carry`, so that the next
profile's green step starts from that patch and never from the stalled agent's edits. Nothing of the stalled step SHALL
be committed, and no guard or gate SHALL treat it as a result. The next profile's step SHALL pass through every guard and
gate of an agent step (L4-IMP-002, L4-IMP-048 and the green freeze) as any step does. Setup and the baseline
SHALL run again before it. The attempt number of that step SHALL be the stalled step's again, as after any limit, and
its agent logs SHALL be kept next to the stalled step's. The stall's record SHALL say how many files the step left
uncommitted and name the first 20, so that the work that was discarded is not lost silently. When no profile can take
the step and the unit parks, the tree SHALL already be clean at HEAD. A stall SHALL NOT be a limit on a path that raises
without discarding (L4-IMP-115, a fix task's second move).

#### Scenario: SCN-IMP-604 (+) The next profile starts from HEAD, and the discarded work is recorded
- **Given** a green step on `free` that edited three files, one of them a frozen red test, and was stopped as a stall
- **When** the next profile's step starts
- **Then** `guard.violation` shows the frozen test put back, `agent.idle` or `agent.time_limit` has `discarded_files: 2` and
  `discarded_paths` with the two other paths, the work tree holds no change, the red commit is still the branch's head, and
  nothing of the stalled step is in a commit

#### Scenario: SCN-IMP-605 (+) A near pass is handed on, not the stalled edits
- **Given** green attempt 1 on `free` that passed every test and failed only its lint gate (a near pass), and attempt 2 on
  `free`, started from that near pass, that was stopped as a stall after editing other files
- **When** the step runs on `glm`
- **Then** `task.near_pass_applied{from_attempt: 1}` is recorded for it, its work tree holds attempt 1's patch and none of
  attempt 2's edits, and its prompt has the near-pass block and the previous-attempt block of the stall

#### Scenario: SCN-IMP-606 (+) A stalled red step leaves nothing for the next red
- **Given** a red step on `free` that wrote two test files and was stopped as a stall
- **When** `glm`'s red step starts
- **Then** the tree holds none of the two files, red's scope check and its test-tamper guards run on `glm`'s step only, and
  the task has no red commit until `glm`'s step passes them

### Requirement: L4-IMP-114 A task has one stall limit per attempt window, whatever the kind
A stall SHALL count as the task's stall limit when it is a limit (L4-IMP-112). When the task already has one in its window,
a stall of any kind, on any profile and in any run, SHALL be a failed attempt: it SHALL record `agent.idle{as_limit:
false, reason}` or `agent.time_limit{as_limit: false, reason}` with the reason `<kind>: already once for this task` and
fail with the reason it has today, and it SHALL count against the profile for the escalation (L4-IMP-017) and against
`implementer.max_task_attempts`. The window SHALL be the one that counts attempts (L4-IMP-075: it ends at a checkpoint of
the task, a retry, a resume or a restart, of the same fix unit or of none). An earlier stall limit is an `agent.idle` of
the task and fix unit with `as_limit` true, or with no `as_limit` and `silent` true (a silent stop of an earlier release),
or an `agent.time_limit` with `as_limit` true. A stall that was not a limit SHALL NOT count as one. A
`task.attempts_renewed` (L4-IMP-104) SHALL NOT end the window. So a chain whose profiles all stall halts on
`max_task_attempts` (exit 13) and does not park run after run.

#### Scenario: SCN-IMP-607 (−) A task's second stall counts, whatever its kind
- **Given** `roles.implementer: [free, glm]`, and a task whose first stall, an idle stop on `free`, was a limit that moved it
  to `glm`
- **When** the step on `glm` reaches the agent's time limit
- **Then** `agent.time_limit{as_limit: false, reason: "time: already once for this task"}` and `task.attempt_failed` with the
  reason `the agent step reached its time limit (30m)` are recorded, and `glm` is not cooled

#### Scenario: SCN-IMP-608 (+) A silent stop of an earlier release is the task's first stall
- **Given** a ledger written by an earlier release with `agent.idle{silent: true}` of task 1.2 in its window and no `kind`
  or `as_limit`
- **When** a step of task 1.2 reaches the agent's time limit
- **Then** it is a failed attempt with the reason `time: already once for this task`

#### Scenario: SCN-IMP-609 (+) A checkpoint opens a new window, and a renewal does not
- **Given** a task whose red step was a stall limit, a red commit, and then a green step that stalls on its first profile
- **When** the green step ends
- **Then** it is a stall limit again, because `task.red_committed` ended the window; and a task whose green window holds a
  stall limit and a `task.attempts_renewed` still has its next stall as a failed attempt

#### Scenario: SCN-IMP-610 (−) A chain of one profile is unchanged
- **Given** `roles.implementer: [free]` and, in turn, an idle stop after a tool call and a step that reaches the agent's limit
- **When** each ends
- **Then** each is a failed attempt with its reason of before, no profile cools, and the record has `as_limit: false` and no
  `reason`

#### Scenario: SCN-IMP-612 (+) A stall limit adds nothing to the escalation or the attempt count
- **Given** `roles.implementer: [free, glm]`, `escalate_after: 2`, `max_task_attempts: 3`, and one stall limit of the task
  on `free`
- **When** `glm`'s step fails twice
- **Then** `free` has no failed attempt, `glm` has two and moves the phase by L4-IMP-017 to the next profile after it, and the
  stall limit is no `implementer.escalated`

#### Scenario: SCN-IMP-621 (+) A silent stop keeps its behaviour
- **Given** `roles.implementer: [free, glm]`, `glm` cooling, and a step on `free` stopped with no tool call
- **When** the step ends
- **Then** it is a silent limit as in SCN-IMP-426, with no check for a replacement, and the unit waits for capacity (exit 12)
  as L4-IMP-087 says

### Requirement: L4-IMP-115 A stall that cannot move stays a failed attempt, and it moves nothing it should not
A stall of kind `idle` or `time` SHALL be a limit only when `Workbench.can_move(task)` is true, where the owner of the
workbench sets it from `Factory.can_replace` (L4-AVL-015); a workbench with none SHALL apply the chain-length test only. A
silent stop (L4-IMP-087) SHALL NOT use it. In a fix unit the fix loop's `can_move` SHALL also be false for a task that has
already moved after a limit in this run, because the fix loop moves a task once and parks the unit on its second limit,
and that path discards nothing (L4-IMP-113). A stall that is a limit SHALL go through the same fallback as every limit, so
that: the move asks with the task's veto and never takes a spent profile (L4-IMP-094), and may take a profile that has used
its share; a stall on a task's own profile (L4-IMP-017) leaves the run's profile where it is, and a stall on the run's
profile moves it; the failure counts, `seed_attempts` and the attempt window (L4-IMP-075, L4-IMP-104) are unchanged, so a
stall limit is no failed attempt and no renewal; the soft deadline (L4-IMP-067, L4-IMP-068) wins over a stall, and the
next profile's step starts only when `_check_step` lets it, with the stall limit staying recorded; and with a chain of one
profile, in an eval cell and in every case of L4-IMP-112 that does not hold, the stall is a failed attempt as before. When
a stall of kind `idle` or `time` is not a limit because of this requirement, its record SHALL carry `as_limit: false` and
the reason `<kind>: no other profile can take the step`.

#### Scenario: SCN-IMP-611 (−) A stall with no profile to replace it stays a failed attempt
- **Given** `roles.implementer: [free, glm, sonnet]`, `free` cooling, `sonnet` spent for the task's green phase (3 failed
  attempts), and a step on `glm` that reaches the agent's limit
- **When** the step ends
- **Then** `agent.time_limit{as_limit: false, reason: "time: no other profile can take the step"}` and `task.attempt_failed`
  are recorded, no profile is cooled, and the unit does not park

#### Scenario: SCN-IMP-613 (−) The soft deadline wins, and a step that does not fit is not started
- **Given** an armed soft deadline, and in turn a step that the deadline stops while the agent has been idle for 12
  minutes, and a time-limit stall that leaves 5 minutes
- **When** each ends
- **Then** the first is `cancelled`, writes no stall record and hands the step back (L4-IMP-068); the second is a stall
  limit, and the next profile's step is not started (`deadline.reached{when: before}`), the stall limit counting in the
  window of the next run

#### Scenario: SCN-IMP-614 (+) A fix task's first stall moves it
- **Given** a fix unit whose task has not moved, `roles.implementer: [free, glm]`, and a step on `free` stopped as an idle
  stall after tool calls
- **When** the step ends
- **Then** the profile cools, the fix task's work is discarded, and `glm` runs the task in a new session

#### Scenario: SCN-IMP-615 (−) A fix task that already moved does not park the unit on a stall
- **Given** a fix task that moved from `free` to `glm` after a usage limit in this run, and a step on `glm` that reaches the
  agent's limit
- **When** the step ends
- **Then** it is a failed attempt with `reason: "time: no other profile can take the step"`, nothing cools, the unit is not
  parked, and the stalled step's work is discarded by the failed attempt's own path

### Requirement: L4-IMP-116 A stall is recorded and told in the same words in the ledger, the log and the next prompt
The harness SHALL record an `idle` or `silent` stall in `agent.idle`, before `agent.finished`, with the fields it has and
the optional `kind` (`silent` or `idle`), `as_limit`, `discarded_files` and `discarded_paths` (at most 20); `silent` SHALL stay true exactly
when the kind is `silent` and `as_limit` is true. It SHALL record a `time` stall in a new `agent.time_limit{task, phase,
attempt, profile, limit_s, tool_calls?, as_limit, reason?, discarded_files?, discarded_paths?}`, before
`agent.finished`; `tool_calls` is left out when no reader counted. The `reason` of a stall that was not a limit is
`<kind>: already once for this task` (L4-IMP-114) or `<kind>: no other profile can take the step` (L4-IMP-115). The excerpt of the
limit's signal SHALL be `no output for <limit>` for `silent`, `no output for <limit> after <n> tool calls` for `idle`
(`no output for <limit>` without a count), and `the agent step reached its time limit (<limit>)` for `time`. The
progress log SHALL print, at WARNING, for `agent.idle` the line of L4-IMP-024 with the suffix `; <n> tool calls were made;
it is a limit of the profile, not a failed attempt` for an `idle` stall that is a limit (`; it is a limit of the profile,
not a failed attempt` without a count), the silent suffix of L4-IMP-087 for a silent one, and `; <reason>, so it counts as a
failed attempt` when `reason` is set; and for `agent.time_limit` `task <k> <phase> attempt <n>: <profile> reached the time
limit (<limit>)` with `; it is a limit of the profile, not a failed attempt` or `; <reason>, so it counts as a failed
attempt`. The previous-attempt block of the next profile SHALL say `went silent: <detail>, so L4 stopped it`, `went idle:
<detail>, so L4 stopped it` or `ran out of time: <detail>, so L4 stopped it`, followed by `, while working on this task`,
with `limit` `silent`, `idle` or `time` in its attribute and `<detail>` the signal's excerpt. `docs/runbook.md` SHALL
document these records and lines, and SHALL say that a profile whose `availability.cooldown` records of kind `idle` or
`time` recur belongs later in `roles.implementer`, which is the consumer's choice and which the harness never changes.

#### Scenario: SCN-IMP-620 (+) The records, the lines and the note name each kind
- **Given** one stall limit of each kind, one stall that was a second stall of its task, and one with no replacement
- **When** the ledger, the progress log and the next prompts are read
- **Then** each record has the fields above, each progress line has its suffix, `availability.limit` has the kind, and each
  previous-attempt block has its sentence and attribute, with no text of the agent in any of them

### Requirement: L4-AVL-014 A stall cools its profile for the default cool-down, with its own kind
A limit of kind `idle` or `time` (L4-IMP-112) has no reset time, so `availability.default_cooldown` SHALL apply to it, as
it does to `silent` (L4-AVL-003): the profile's `(tool, model)` is cooled in the registry with that kind and the signal's
source, its cached hello is cleared (L4-AVL-005), and `availability.limit{kind}`, `availability.cooldown{kind}` and
`availability.fallback{reason: <kind>}` are recorded. `LimitSignal.kind` SHALL include `idle` and `time`. A selection
SHALL skip the cooling profile without a request, and `l4 probe` SHALL show its kind. No key SHALL be added. A registry
entry of kind `idle` or `time` SHALL load in a reader that does not know the kinds (the kind is any string).

#### Scenario: SCN-AVL-37 (+) A stall cools for the default cool-down, and the length is the key's
- **Given** `availability.default_cooldown: 30m` and a `time` stall on `free`, then the same with `10m`
- **When** the limit is recorded
- **Then** the registry entry for `free` has `kind: time`, `source: run.timeout` and an end 30 minutes, then 10 minutes, after
  the stall, and `availability.cooldown` carries the same

#### Scenario: SCN-AVL-38 (+) The cooled profile is skipped, and its hello is asked again afterwards
- **Given** an `idle` stall on `free` whose hello was cached as passed
- **When** a selection runs before the cool-down ends, and another after it
- **Then** the first skips `free` with `cooling until <time> (idle); no probe sent`, and the second sends the hello again

#### Scenario: SCN-AVL-43 (+) An older reader loads the new kinds
- **Given** a cool-down file with entries of kind `idle` and `time`
- **When** it is read by `CooldownRegistry` and printed by `l4 probe`
- **Then** both entries load, cool their profiles, and show their kinds

### Requirement: L4-AVL-015 A stall is a limit only when a profile with another cool-down key can take the step
`Factory.can_replace(selected, constraints)` SHALL be true when `roles.implementer` lists a profile other than `selected` whose
cool-down key (`(tool, model)`) differs from the key of `selected`, that is not cooling in the registry, and that every
constraint of the request accepts (the task's veto of a spent profile among them). It SHALL send no probe and record
nothing. A stall of kind `idle` or `time` SHALL be a limit only when it is true (L4-IMP-115). When it is true and the
fallback still finds no usable profile (every candidate fails its probe), the unit SHALL park as it does for any limit:
`waiting_capacity`, exit 12, with `retry_after` the earliest end of a cool-down in the chain (L4-AVL-007), and the tree is
already clean (L4-IMP-113). A stall's cool-down is longer than `availability.wait_in_run` under the defaults, so the run
SHALL NOT wait for it unless a deployment sets `wait_in_run` and `wait_in_run_max_total` above it (L4-AVL-011).

#### Scenario: SCN-AVL-39 (−) With every other profile cooling, a stall is a failed attempt
- **Given** `roles.implementer: [free, glm]`, `free` cooling, and an `idle` stall on `glm`
- **When** the step ends
- **Then** no profile is cooled, `agent.idle{as_limit: false, reason: "idle: no other profile can take the step"}` and
  `task.attempt_failed` are recorded, and the unit does not park

#### Scenario: SCN-AVL-40 (−) A profile with the same cool-down key is no replacement
- **Given** `roles.implementer: [free-a, free-b]`, both of one adapter and one model, neither cooling, and a `time` stall on
  `free-a`
- **When** the step ends
- **Then** `can_replace` is false, the stall is a failed attempt, and `free-b` is not cooled

#### Scenario: SCN-AVL-41 (−) A profile the task has spent is no replacement
- **Given** `roles.implementer: [free, glm]`, `glm` with `max_task_attempts` failed green attempts of the task in its
  window, and a `time` stall on `free`
- **When** the step ends
- **Then** the stall is a failed attempt with the reason `time: no other profile can take the step`, and nothing cools

#### Scenario: SCN-AVL-42 (+) A replacement that fails its probe parks the unit, with the tree clean
- **Given** `roles.implementer: [free, glm]`, `glm` not cooling and not spent but failing its hello, and a `time` stall on
  `free`
- **When** the limit is handled
- **Then** `free` cools for `default_cooldown`, the work tree is clean at HEAD, no in-run wait happens, and the unit parks
  with exit 12 and `retry_after` the end of that cool-down
