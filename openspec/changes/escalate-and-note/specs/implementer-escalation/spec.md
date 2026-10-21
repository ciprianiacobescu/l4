## Purpose

A task step that one implementer profile fails again and again moves to the next usable profile of the implementer
chain, cheap first, with the reasons of the earlier failures. Each profile has its own attempts, the last one has
`max_task_attempts`, and the move never parks a unit or breaks the independence of its verification. A person sees
which profiles ran and why the task moved.

## ADDED Requirements

### Requirement: L4-IMP-017 A task phase that fails on one profile moves to the next usable profile of the chain
The configuration SHALL have the key `implementer.escalate_after` (an integer, at least 0, default 2). `0` means that
no task moves.

A failed attempt is an attempt that the implementer loop counts against `max_task_attempts`: a harness check that does
not pass, an invalid agent result, or an agent run that ends with a status that is not `ok` and not a limit. It SHALL
count against the profile that ran it. A limit (L4-AVL-006), a `blocked` result and the question about a frozen test
that hangs MUST NOT count, and MUST NOT start an escalation.

In the unit's own task loop, after a failed attempt of phase P of task T, the harness SHALL try to move P to another
profile when all of these hold:
- `escalate_after` is at least 1 and less than `implementer.max_task_attempts`;
- the current profile has failed at least `escalate_after` attempts of P of T;
- `roles.implementer` lists a profile after the current one.

The move SHALL select the first usable profile after the current one in `roles.implementer`, by profile name, with the
checks of every selection (serves, cool-down, the probe ladder or its cache, the login lock). Two profiles of the same
adapter, provider or vendor are two profiles. The selection:
- MUST NOT park the unit, MUST NOT record `availability.unavailable`, and MUST NOT cool down the profile that failed;
- MUST NOT take a profile when, with it added to the unit's implementer profiles, no profile of `roles.judges`, or of a
  non-empty `roles.verifier_agent`, would pass the independence rule of `verifier.independence` (L4-VER-001); with
  `verifier.independence: none` this check takes every profile;
- SHALL record `availability.selected{role: implementer, selected, escalated_from}` with no `fallback_from`, so that the
  new profile is an implementer profile of the unit for the judge veto.

When a profile is taken, the harness SHALL record `implementer.escalated{task, phase, from, to, failures, attempt}`
(`failures`: the failed attempts of `from` in P; `attempt`: the number of the next step). The next attempt of P SHALL
run on that profile in a fresh session. Its prompt SHALL carry a previous-attempt block that names the profile it
replaces and lists, oldest first, the reason of every failed attempt of P of T on earlier profiles, each cut at 1000
characters. When no profile is taken, the harness SHALL record `implementer.escalation_skipped{task, phase, from,
reason}`, and P SHALL stay on the current profile. The harness SHALL try again after each later failed attempt of
that profile.

Each profile SHALL have its own count of failed attempts per phase. The unit SHALL halt on `max_task_attempts` only
when the current profile has failed `max_task_attempts` attempts of P. The step key `<task>/<phase>/<attempt>` SHALL
count across profiles.

The task SHALL keep the profile for its later phases in that run. The next task, and every task of a later run, SHALL
start on the run's selected profile. The run's selected profile, and the profile that the fix loop reads, MUST NOT
change. A limit on a step of the moved profile SHALL cool that profile (not the run's), and the task SHALL go on as
after any limit (L4-AVL-006). The tasks of a fix unit MUST NOT move.

#### Scenario: SCN-IMP-176 (+) The live case moves red from deepseek to glm
- **GIVEN** `roles.implementer: [deepseek, glm]` (two OpenCode profiles with the same adapter and key, models `opencode-go/deepseek-v4.1-flash` and `opencode-go/glm-5.3-flash`), the defaults `escalate_after: 2` and `max_task_attempts: 3`, and judges of a third vendor
- **AND** deepseek's red attempt 1 of task 4.1 writes a test that calls a function with a keyword it does not have (`TypeError`), and attempt 2 returns a result without `summary`
- **WHEN** attempt 2 is counted
- **THEN** `implementer.escalated{task: "4.1", phase: "red", from: "deepseek", to: "glm", failures: 2, attempt: 3}` and `availability.selected{selected: "glm", escalated_from: "deepseek"}` are recorded, no cool-down is recorded for deepseek, and step `4.1/red/3` runs on glm
- **AND** glm's prompt has a previous-attempt block with `reason="escalation"` that lists both reasons, the guarded-stub advice included, and the section "Your previous attempt was rejected" with the result values line

#### Scenario: SCN-IMP-177 (+) The last profile gets max_task_attempts, then the unit halts and names both
- **GIVEN** the setup of SCN-IMP-176, and glm fails red attempts 3, 4 and 5
- **WHEN** attempt 5 is counted
- **THEN** no further escalation is tried (glm is the last profile), `breaker.tripped{reason: "max_task_attempts", task: "4.1", phase: "red", attempts: 5, profiles: [{profile: "deepseek", failures: 2}, {profile: "glm", failures: 3}]}` is recorded, and the unit halts with the detail `task 4.1: max_task_attempts (3) reached in red on deepseek (2), glm (3); last failure: …`

#### Scenario: SCN-IMP-178 (+) The task keeps the profile; the next task starts cheap
- **GIVEN** the setup of SCN-IMP-176, and glm commits red at attempt 3
- **WHEN** the green step of 4.1 runs, and then task 4.2 starts
- **THEN** green of 4.1 runs on glm with no previous-attempt block, its commit carries `L4-Agent: glm/opencode-go/glm-5.3-flash` and no `L4-Fallback-From`, and the red step of 4.2 runs on deepseek

#### Scenario: SCN-IMP-179 (−) No move when escalation is off or cannot act
- **GIVEN** deepseek failing red three times, in turn with: `roles.implementer: [deepseek]`; `[deepseek, glm]` and `escalate_after: 0`; `[deepseek, glm]` and `max_task_attempts: 2`
- **WHEN** the attempts are counted
- **THEN** no `implementer.escalated` and no `implementer.escalation_skipped` is recorded, and the unit halts after the profile's `max_task_attempts` with the detail of today (no profile list)

#### Scenario: SCN-IMP-180 (−) No usable later profile: the task stays and nothing parks
- **GIVEN** `[deepseek, glm]` and glm cooling until tomorrow
- **WHEN** deepseek fails red attempt 2, then attempt 3
- **THEN** `implementer.escalation_skipped{task: "4.1", phase: "red", from: "deepseek"}` is recorded after each, no `availability.unavailable` is recorded, the unit does not go to `waiting_capacity`, and it halts after deepseek's third failure

#### Scenario: SCN-IMP-181 (−) A profile that would leave no independent judge is not taken
- **GIVEN** `roles.implementer: [deepseek, glm, claude-sonnet]` (claude-sonnet: vendor anthropic), `roles.judges: [claude-judge]` (vendor anthropic), `verifier.independence: different_vendor`, and deepseek and glm each failing red twice
- **WHEN** glm's second failure is counted
- **THEN** glm was taken after deepseek, claude-sonnet is not taken, `implementer.escalation_skipped` names `no profile of roles.judges would be independent of claude-sonnet`, and glm gets its third attempt
- **AND** with `roles.judges: [claude-judge, codex-judge]` (codex-judge: vendor openai) the same failures move red to claude-sonnet

#### Scenario: SCN-IMP-182 (−) A question and a limit do not count; a limit on the moved profile cools that profile
- **GIVEN** `[deepseek, glm]`
- **WHEN** deepseek's red attempt 1 fails, and its attempt 2 ends `blocked` with a question
- **THEN** no escalation is tried and the question is raised as today
- **AND WHEN** in another run deepseek fails red twice, red moves to glm, and glm's step ends with a usage limit
- **THEN** the cool-down is recorded for glm and not for deepseek, no attempt is counted for glm, the run's profile stays deepseek, and the task goes on with fresh counts on deepseek

#### Scenario: SCN-IMP-183 (−) The tasks of a fix unit do not move
- **GIVEN** `[deepseek, glm]` and a fix unit whose task deepseek fails three times
- **WHEN** the attempts are counted
- **THEN** no `implementer.escalated` is recorded, and the fix unit halts after deepseek's third failure as today

### Requirement: L4-IMP-018 A person sees which profiles ran a task and why it moved
`task.attempt_failed` SHALL carry `profile`, and its `attempt` SHALL be the step's attempt number. `breaker.tripped`
for `max_task_attempts` SHALL carry `profiles`, a list of `{profile, failures}` in the order the profiles ran the
phase; `attempts` SHALL stay the failed attempts of the phase. When two or more profiles ran the phase, the halt
detail SHALL be `task <k>: max_task_attempts (<n>) reached in <phase> on <p1> (<f1>), <p2> (<f2>); last failure:
<reason>`. With one profile it MUST stay as before.

The progress log SHALL print:
- for `implementer.escalated`: `task <k> <phase>: escalated from <from> to <to> after <n> failed attempts`;
- for `implementer.escalation_skipped`, as a warning: `task <k> <phase>: <from> failed <n> attempts; no later profile
  can take it (<reason>); it stays on <from>`;
- for `task.attempt_failed` with `profile`: `task <k> <phase> attempt <n> failed on <profile>: <reason>`;
- for `breaker.tripped` with two or more profiles: `halted: max_task_attempts (task <k>: <p1> <f1>, <p2> <f2>)`;
- for `availability.selected` with `escalated_from`: the selection line ending `→ selected, escalated from <from>`.

An event without the new fields SHALL print as before.

The doctor SHALL have the check CFG-009 (warn). It SHALL fail when `roles.implementer` has two or more profiles and
`implementer.escalate_after` is neither 0 nor less than `implementer.max_task_attempts`, and when two profiles of
`roles.implementer` have the same adapter and the same model. Each failure names the keys or the profiles, and the fix
line says what to set. A chain of one profile SHALL pass.

#### Scenario: SCN-IMP-184 (+) The records and the lines name the profiles
- **GIVEN** the run of SCN-IMP-177
- **WHEN** the progress log is read
- **THEN** it has `task 4.1 red attempt 2 failed on deepseek: …`, `task 4.1 red: escalated from deepseek to glm after 2 failed attempts`, `implementer: glm ok (…) → selected, escalated from deepseek`, `task 4.1 red attempt 5 failed on glm: …` and `halted: max_task_attempts (task 4.1: deepseek 2, glm 3)`
- **AND** an older ledger whose `task.attempt_failed` has no `profile` prints `task 1.1 red attempt 1 failed: …` as before

#### Scenario: SCN-IMP-185 (+) CFG-009 warns about an escalation that cannot act
- **GIVEN** in turn: `roles.implementer: [deepseek, glm]` with `max_task_attempts: 2` and the default `escalate_after`; two profiles `oc-a` and `oc-b` with adapter `opencode` and model `opencode-go/deepseek-v4.1-flash`; `roles.implementer: [deepseek]`
- **WHEN** `l4 doctor` runs
- **THEN** CFG-009 fails with `implementer.escalate_after (2) is not below implementer.max_task_attempts (2): no task moves to glm`, then fails with `profiles oc-a and oc-b run the same model (opencode-go/deepseek-v4.1-flash): a move from oc-a to oc-b changes nothing`, then passes, and the doctor's exit code follows the `warn` severity
