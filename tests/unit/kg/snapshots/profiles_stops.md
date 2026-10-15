## Profiles by role
The index has no record of a task that passed at its first attempt: a task is visible only through an injected prompt or a failed attempt. So this section counts failed attempts, and gives no first attempt share. The eval scorecards stay the authority for comparing models.

- implementer / impl-a: n = 1 run; n = 1 task with a failed attempt; n = 2 failed attempts; mean 2.0 failed attempts per such task; first-round PASS n = 1 of n = 1 (100%)
- implementer / impl-b: n = 1 run; n = 1 task with a failed attempt; n = 1 failed attempt; mean 1.0 failed attempts per such task; first-round PASS n = 0 of n = 1 (0%)
- judge / judge-a: n = 1 run

## Stops
How a stop ended: a later retry or restart of the unit, else merged when the unit is in an archive folder, else still stopped.

- verifier_errors: n = 2 units, n = 2 stops; retried n = 0, restarted n = 1, merged n = 1, still stopped n = 0
- same_failure: n = 1 unit, n = 2 stops; retried n = 1, restarted n = 0, merged n = 0, still stopped n = 1
