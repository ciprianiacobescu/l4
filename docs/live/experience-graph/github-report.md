# Experience report

## Coverage

- Base ref: refs/remotes/origin/l4/main, commit c2ecc2b445, committed 2026-10-14T15:03:14+03:00. History newer than this commit is not read: run `git fetch` first.
- Floor: a key needs at least n = 2 units; a gate candidate needs at least n = 3 units.
- Units: n = 4 units (base n = 4, archive n = 0, branch n = 4, lock n = 4, attempt n = 1).
- Attempts: n = 7 attempts.
- Runs: n = 26 runs.
- Rounds: n = 18 rounds.
- Skipped inputs: none (n = 0).

## Lessons (approximate)

This shows what followed each lesson, not what the lesson caused. A lesson is linked to a finding key only by its dedupe key.

- L-e7230fe4 (seen only in events) (n = 9 prompts): injected 1 unit / 2 tasks / 9 prompts, followed by 2 failures (red: no new test traces <criterion> ×2)

## Recurring attempt failures (approximate)

A failure class is the first part of the reason of a failed task attempt, normalised.

- vacuous: n = 2 units, n = 5 attempts; phase red n = 5; blame agent n = 5

## Recurring findings (approximate)

A key is the normalised title and the normalised requirement and scenario of the criterion.

none (n = 0)

## Gate candidates (approximate)

Deterministic findings and failure classes that recur in many units. A person may write a deterministic gate or a lint rule; this report writes nothing.

none (n = 0)

## Spec-gap hotspots

Kiro capabilities are units. A question or a NEEDS_HUMAN round counts for each capability of its unit's criteria.

- pick-priority: n = 1 unit; spec-blame findings n = 7; product or ambiguous questions n = 1; NEEDS_HUMAN rounds n = 1
- add-low-stock-message: n = 1 unit; spec-blame findings n = 2; product or ambiguous questions n = 0; NEEDS_HUMAN rounds n = 0
- reorder-quantity: n = 1 unit; spec-blame findings n = 2; product or ambiguous questions n = 0; NEEDS_HUMAN rounds n = 0
- shelf-code: n = 1 unit; spec-blame findings n = 2; product or ambiguous questions n = 0; NEEDS_HUMAN rounds n = 0

## Profiles by role

The index has no record of a task that passed at its first attempt: a task is visible only through an injected prompt or a failed attempt. So this section counts failed attempts, and gives no first attempt share. The eval scorecards stay the authority for comparing models.

- implementer / kiro: n = 14 runs; n = 4 tasks with a failed attempt; n = 9 failed attempts; mean 2.2 failed attempts per such task; first-round PASS n = 4 of n = 5 (80%)
- judges / claude-judge: n = 13 runs
- implementer / oc-free: n = 2 runs; n = 0 tasks with a failed attempt; n = 0 failed attempts; first-round PASS n = 2 of n = 2 (100%)

## Stops

How a stop ended: a later retry or restart of the unit, else merged when the unit is in an archive folder, else still stopped.

- fix_rounds_exhausted: n = 1 unit, n = 1 stop; retried n = 1, restarted n = 0, merged n = 0, still stopped n = 0
- max_task_attempts: n = 1 unit, n = 2 stops; retried n = 2, restarted n = 0, merged n = 0, still stopped n = 0
- same_failure: n = 1 unit, n = 1 stop; retried n = 1, restarted n = 0, merged n = 0, still stopped n = 0
