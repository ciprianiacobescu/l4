## ADDED Requirements

### Requirement: L4-IMP-094 A move never takes a spent profile, passes over a used one, and a later run continues it
For phase P of task T, a profile SHALL be *spent* when its failed attempts of P of T in the window of L4-IMP-075 (those
of earlier runs and of this run) are at least `implementer.max_task_attempts`. A move (L4-IMP-017) SHALL NOT take a
spent profile: its selection SHALL refuse it as a constraint with `spent: <n> failed attempts of <phase> of task <k>
(implementer.max_task_attempts <m>)` and walk on, with the checks of every selection, so a cooling, unusable or
non-independent profile is skipped as before. A move SHALL also pass over a profile that has itself failed at least
`escalate_after` attempts of P (it used its share) while a later profile can take the step, and its selection SHALL
walk in two passes. The first refuses such a profile as a constraint with `used its share: <n> failed attempts of
<phase> of task <k> (implementer.escalate_after <m>)` (a spent profile, with the `spent:` text above). The second, run
only when the first takes no profile, refuses the spent profiles alone, so that a profile that used its share and has
attempts left takes the step when nothing after it can. A move SHALL record one `availability.selected`, that of the
pass that took the profile, and a profile that was passed over SHALL NOT be probed, recorded as selected or added to
the unit's implementer profiles. After a move of T, every limit fallback of T (L4-AVL-006: a later limit and a wait
in the run included) SHALL refuse the spent profiles of that move as the second pass does, so that the step never
goes back to a spent profile; a profile that used its share may take it, and the run's profile does not keep that
veto for a later task. When a move takes a profile that has itself failed at least `escalate_after` and
fewer than `max_task_attempts` attempts of P (only the second pass does), and `roles.implementer` lists a profile after
it, the harness SHALL try to move P again at once, before the next attempt, after a failed attempt as before the first
attempt; when that move is refused, P SHALL stay on that profile, which keeps its attempts up to `max_task_attempts`.
Every move SHALL go to a later profile of `roles.implementer`, so one try makes at most as many moves as the chain has
profiles. Before the first attempt that a run makes of T, when the window holds an `implementer.escalated` of P (of
the same fix unit, or of none), and the `from` F of the newest one comes after the run's selected profile in
`roles.implementer` and meets the conditions of L4-IMP-017 for a move, the first move SHALL be asked from F: its
selection walks after F, and `implementer.escalated` and the previous-attempt block name F. When that move is refused,
the harness SHALL record `implementer.escalation_skipped{task, phase, from, failures, reason, on}` with `from` F and
`on` the run's selected profile, P SHALL start on the run's selected profile, and L4-IMP-075 SHALL apply to that
profile's count. When P halts on `max_task_attempts` on a profile that `roles.implementer` lists a profile after, and a
move was refused while P was on that profile, the halt detail SHALL have `; no later profile can take it (<reason>)`
before `; last failure:`, with the reason of the newest such refusal. A run whose window has no move and no failure of
P, a chain of one profile, and `escalate_after: 0` SHALL keep their behaviour; `l4 retry`, `l4 resume` and `l4
restart` start a new window, so the task starts on the run's selected profile with fresh counts.

#### Scenario: SCN-IMP-500 (+) a later run continues the move of an earlier one
- **WHEN** `roles.implementer` is `[deepseek, glm, claude-sonnet]` (`escalate_after: 2`, `max_task_attempts: 3`), the
  window of task 4.1 holds glm's failed red attempts 1 and 2 and `implementer.escalated{from: glm, to: claude-sonnet}`,
  and this run selected deepseek
- **THEN** `implementer.escalated{task: "4.1", phase: "red", from: "glm", to: "claude-sonnet", failures: 2, attempt: 3}`
  is recorded before the first step, steps `4.1/red/3` to `4.1/red/5` run on claude-sonnet and deepseek runs none, and
  three failures halt the unit with `task 4.1: max_task_attempts (3) reached in red on glm (2), claude-sonnet (3); last
  failure: …`

#### Scenario: SCN-IMP-501 (+) a move passes over a profile which used its share while a later one is usable
- **WHEN** the window holds glm's failed red attempts 1 and 2 and a refused move from glm (claude-sonnet was cooling),
  this run is on deepseek with claude-sonnet usable, and deepseek fails red attempts 3 and 4
- **THEN** one `implementer.escalated{from: deepseek, to: claude-sonnet, failures: 2, attempt: 5}` is recorded, the one
  `availability.selected` of the move lists glm as skipped with `used its share: 2 failed attempts of red of task 4.1
  (implementer.escalate_after 2)`, glm is not probed and is not an implementer profile of the unit, and step
  `4.1/red/5` runs on claude-sonnet. With claude-sonnet cooling the move takes glm, which keeps its last attempt

#### Scenario: SCN-IMP-502 (+) a spent profile is not taken
- **WHEN** glm failed red three times in the window (an earlier configuration allowed it) and deepseek fails red twice
- **THEN** the move goes from deepseek to claude-sonnet, and `availability.selected` lists glm as skipped with
  `spent: 3 failed attempts of red of task 4.1 (implementer.max_task_attempts 3)`
- **AND** when claude-sonnet then hits a limit while deepseek is cooling, the limit's fallback refuses glm as spent
  too: the unit waits for capacity and glm runs no step; so does a later limit of the task, after the step fell back to
  deepseek

#### Scenario: SCN-IMP-503 (−) every later profile spent: no move, and the halt says why
- **WHEN** glm and claude-sonnet each failed red three times in the window and deepseek fails red three times
- **THEN** one `implementer.escalation_skipped{from: deepseek}` names both as spent, no `implementer.escalated` is
  recorded, and the unit halts with `task 4.1: max_task_attempts (3) reached in red on glm (3), claude-sonnet (3),
  deepseek (3); no later profile can take it (…); last failure: …`

#### Scenario: SCN-IMP-504 (−) a cooling target is skipped, and the run starts on its own profile
- **WHEN** the window is that of SCN-IMP-500 and claude-sonnet is cooling
- **THEN** `implementer.escalation_skipped{from: glm, on: deepseek}` is recorded, nothing parks, step `4.1/red/3` runs on
  deepseek, and after its failures 3 and 4 the step moves to glm, whose move on is refused, and `4.1/red/5` runs on glm

#### Scenario: SCN-IMP-505 (−) one run with nothing in its window is unchanged
- **WHEN** the window of task 4.1 is empty and deepseek, glm and claude-sonnet fail red 2, 2 and 3 times
- **THEN** the moves are deepseek to glm at attempt 3 and glm to claude-sonnet at attempt 5, each asked once, and the
  halt detail is `task 4.1: max_task_attempts (3) reached in red on deepseek (2), glm (2), claude-sonnet (3); last
  failure: …`

#### Scenario: SCN-IMP-506 (−) a retry starts the task on the run's profile
- **WHEN** the records of SCN-IMP-500's window are followed by `unit.retried`, and the next run starts task 4.1
- **THEN** no move is made before the first attempt, and step `4.1/red/1` runs on deepseek

#### Scenario: SCN-IMP-507 (+) the halt names why no later profile took the step
- **WHEN** `roles.implementer` is `[deepseek, glm]`, glm is cooling, and deepseek fails red three times
- **THEN** the halt detail is `task 4.1: max_task_attempts (3) reached in red; no later profile can take it (<the reason
  of the refusal after attempt 2>); last failure: …`

#### Scenario: SCN-IMP-508 (+) the log line of a refused continuation names where the step starts
- **WHEN** the progress log of SCN-IMP-504's run is read
- **THEN** it has `task 4.1 red: glm failed 2 attempts; no later profile can take it (…); it starts on deepseek`, and an
  `implementer.escalation_skipped` without `on` prints as before

#### Scenario: SCN-IMP-509 (+) a fix unit's chore continues the same way
- **WHEN** a fix unit's chore task 1.1 failed twice on glm in an earlier run and moved to claude-sonnet, and this run is
  on deepseek
- **THEN** the move from glm to claude-sonnet is recorded before the chore's first attempt, step `1.1/single/3` runs on
  claude-sonnet, and the run's selected profile is still deepseek
