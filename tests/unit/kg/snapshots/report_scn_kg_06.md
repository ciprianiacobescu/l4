# Experience report

## Coverage

- Base ref: refs/remotes/origin/main, commit 0123456789, committed 2026-10-01T08:00:00+00:00. History newer than this commit is not read: run `git fetch` first.
- Floor: a key needs at least n = 2 units; a gate candidate needs at least n = 3 units.
- Units: n = 2 units (base n = 0, archive n = 1, branch n = 1, lock n = 0, attempt n = 0).
- Attempts: n = 2 attempts.
- Runs: n = 2 runs.
- Rounds: n = 2 rounds.
- Skipped inputs: files_unknown: n = 2.

## Lessons (approximate)

This shows what followed each lesson, not what the lesson caused. A lesson is linked to a finding key only by its dedupe key.

- L-09421538 "UI criteria need an end-to-end test" (n = 3 prompts): injected 1 unit / 1 task / 3 prompts, followed by 1 failure (red: new tests fail with an error that is neither an assertion nor notimplementederror)

## Recurring attempt failures (approximate)

A failure class is the first part of the reason of a failed task attempt, normalised.

none (n = 0)

## Recurring findings (approximate)

A key is the normalised title and the normalised requirement and scenario of the criterion.

none (n = 0)

## Gate candidates (approximate)

Deterministic findings and failure classes that recur in many units. A person may write a deterministic gate or a lint rule; this report writes nothing.

none (n = 0)

## Spec-gap hotspots

Kiro capabilities are units. A question or a NEEDS_HUMAN round counts for each capability of its unit's criteria.

- (no capability recorded): n = 1 unit; spec-blame findings n = 0; product or ambiguous questions n = 1; NEEDS_HUMAN rounds n = 0

## Profiles by role

The index has no record of a task that passed at its first attempt: a task is visible only through an injected prompt or a failed attempt. So this section counts failed attempts, and gives no first attempt share. The eval scorecards stay the authority for comparing models.

- implementer / impl-a: n = 1 run; n = 1 task with a failed attempt; n = 1 failed attempt; mean 1.0 failed attempts per such task; first-round PASS n = 0 of n = 1 (0%)
- implementer / impl-b: n = 1 run; n = 0 tasks with a failed attempt; n = 0 failed attempts; first-round PASS n = 0 of n = 0

## Stops

How a stop ended: a later retry or restart of the unit, else merged when the unit is in an archive folder, else still stopped.

- baseline_failed: n = 1 unit, n = 1 stop; retried n = 0, restarted n = 0, merged n = 0, still stopped n = 1
