## ADDED Requirements

### Requirement: L4-IMP-100 A green attempt that passed every test and failed only its static gates is the next attempt's start
A green attempt is a near pass when its test gate gives no failure (L4-IMP-002 (b)) and it fails only because a static
gate that passed at the step base fails now (L4-IMP-096): no replay put-back failure, no refused write and no link
outside the work tree. A replayed step (L4-IMP-065) SHALL NOT be a near pass. Before a near pass's changes are
discarded the harness SHALL keep them in memory (the work tree's diff against the red commit, binary, without the
ledger, as a held step is captured) with the profile, the attempt and the names of the failed static gates, and
`task.attempt_failed` SHALL carry `near_pass: true`.

The next green attempt of the task in the same run SHALL start from the red commit with those changes applied as
uncommitted changes, whatever profile runs it (an escalation included), and its prompt SHALL hold a `near pass` block:
the attempt and profile that wrote the changes, that every test passed, which static gates failed (their output is the
previous failure), and that it is to fix what they report and keep the rest unless a fix needs it. The previous-attempt
and escalation blocks SHALL NOT then say that the earlier changes were discarded. The changes SHALL be applied once: the
attempt after that SHALL start from the red commit as before, unless it was itself a near pass, whose changes replace
them. The applied changes SHALL go through every guard and check of a green step, as an agent's own changes do; no replay
guard SHALL be armed for them. A step to replay that `find_replay` finds SHALL come first, and the near pass SHALL then
be dropped. The harness SHALL record `task.near_pass_applied{task, attempt, from_attempt, from_profile, patch_sha256,
files}` when it applies them, and `task.near_pass_dropped{task, attempt, from_attempt, reason}` when it does not (a
replay, or a patch that does not apply, after which the attempt starts from the red commit). The patch SHALL NOT be
written to the repository, the ledger or a log.

When the task halts on `max_task_attempts`, the reason SHALL end with `; nearest: attempt <n> (<profile>) passed every
test and failed only its lint or type gates` for the newest near pass of the phase in this run, and `breaker.tripped`
SHALL carry `near_pass{attempt, profile}`. A near pass SHALL be kept for the run only: a later run (a retry, a resume, the
run after a soft deadline) starts from the red commit. A red step, a single (chore) step and a green attempt whose test
gate failed, however few tests failed, SHALL NOT be near passes.

#### Scenario: SCN-IMP-541 (+) The next attempt starts from a near pass
- **Given** green attempt 1 of a task, whose test gate passes and whose `gates.lint` command passed at the step base and
  fails now
- **When** attempt 2 starts
- **Then** attempt 1's `task.attempt_failed` holds `near_pass: true`; before attempt 2's agent runs, its work tree holds
  attempt 1's changes as uncommitted changes on the red commit and `task.near_pass_applied{from_attempt: 1}` is recorded;
  its prompt holds a `near pass` block that names attempt 1, its profile and the `lint` gate, and no block of it says
  that attempt 1's changes were discarded

#### Scenario: SCN-IMP-542 (+) An escalation keeps the near pass
- **Given** two implementer profiles A and B, `escalate_after: 1`, and A's green attempt 1, a near pass
- **When** the phase moves to B and B's attempt 2 starts
- **Then** B's work tree holds A's changes and its escalation block says that they are in the checkout, not that they were
  discarded

#### Scenario: SCN-IMP-543 (−) A failed test is no near pass
- **Given** a green attempt whose test gate fails one red test, and another whose test gate passes but whose agent wrote
  a link out of the work tree and whose lint fails
- **When** the next attempt of each starts
- **Then** it starts from the red commit, neither `task.attempt_failed` holds `near_pass`, and no `task.near_pass_applied`
  is recorded

#### Scenario: SCN-IMP-544 (+) A near pass is applied once
- **Given** attempt 2 started from attempt 1's near pass
- **When** attempt 2 fails its test gate and attempt 3 starts, and, in a second run of the same shape, attempt 2 is itself
  a near pass
- **Then** attempt 3 starts from the red commit in the first case, and from attempt 2's changes in the second

#### Scenario: SCN-IMP-545 (−) The halt names the nearest attempt
- **Given** a task whose green attempt 4 (claude-sonnet) was a near pass and whose attempt 5 reached the step's time limit,
  after which the profile is spent
- **When** the task halts
- **Then** its reason ends `; last failure: the agent step reached its time limit (30m); nearest: attempt 4
  (claude-sonnet) passed every test and failed only its lint or type gates`, and `breaker.tripped` holds `near_pass:
  {attempt: 4, profile: claude-sonnet}`

#### Scenario: SCN-IMP-546 (−) A replay or a patch that does not apply drops the near pass
- **Given** a near pass of attempt 1, and attempt 2 for which a held step answered `accept` is found to replay; and,
  separately, a near pass whose patch no longer applies to the red commit
- **When** attempt 2 starts in each case
- **Then** the first replays the held step with no near pass applied and records `task.near_pass_dropped{reason:
  "replay"}`; the second records `task.near_pass_dropped` with the apply error, starts from the red commit, and its prompt
  holds no `near pass` block
