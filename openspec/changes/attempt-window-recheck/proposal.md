## Why

Two ways a task loses attempts that it should have, each seen in consumer units.

**An unfreeze leaves one attempt.** Three times in two units, green attempts 1 and 2 failed against a wrong frozen red
browser test, and attempt 3 raised a question. The delegate accepted the suggestion that unfreezes the test, and the
next run had one attempt left (attempt 3 of 3). Once that attempt failed on a second wrong line, and the breaker
halted the unit for a person. Once it passed.

What exists at 0.4.59 (verified in code):

- `implementer/loop.py` `seed_attempts` counts the task's `task.attempt_failed` events in `deadline.window`. The window
  starts after the task's last `task.red_committed`, `task.green_committed` or `task.done`, or after the last
  `unit.retried`, `unit.resumed` or `unit.restarted` (`deadline.py` `COMMITS`, `RESETS`). Neither `question.answered`
  nor `task.unfrozen` starts it. A blocked attempt records no `task.attempt_failed`, so its number is used again.
- `implementer/tdd.py` `run_green` records `task.unfrozen{reason: human_answer | delegate_answer}` at the start of
  every green attempt while the answer stands, not once. `seed_attempts` runs before the first of them in a run.
- Only the delegate's answers are capped per task (`delegate.max_answers_per_task`, default 3, over the unit's whole
  ledger: `delegate/limits.py` `answers_used`). A person's or an agent's answers are not.

**A flake fails a step.** Red and green fail an attempt as soon as a test that passed in the step's base report fails
once (`red broke existing tests`, `green broke existing tests`: `tdd.classify_red` and `tdd.green_failures`). Nothing
repeats it. Verification repeats a flaky pre-existing test (L4-VER-076, `verifier/gate_repeat.py`), and so does step
1's run of the base's tests (`base-tests-repeat`). Three attempts in two units were lost to pre-existing tests of the
consumer's e2e stack helper: one starts the stack on fixed ports with a 90-second ready timeout, one checks that no DNS
lookup happens. The cause is not known. Port contention or load is a guess.

## What Changes

- A task's green phase gets a new attempt window once per answered question that opens a frozen file for it. When
  green is about to start in a run, an answer grant (`reason: human_answer` or `delegate_answer`) whose question no
  earlier renewal of the task named renews the window: `task.attempts_renewed{task, phase, questions, failed}` is
  recorded, and the phase's failed-attempt counts, their reasons and the newest move of the phase are cleared. Attempt
  numbers go on. At most two renewals that clear a failure per task come between two retries, resumes or restarts by a
  person. The task's own text (`named_by_task`) renews nothing (L4-IMP-104).
- Before red, green or a fix, tests or refactor chore fails an attempt for regressed pre-existing tests alone (one to
  five tests that failed or errored, did not hang, and lie in files the unit did not change), the step runs its test
  gate once more, as `test-recheck`, on the tree run 1 started from. A regressed test that passes in that run is
  flaky. It does not fail the attempt when every regressed test passed and no test that passed in run 1 failed. A test
  that fails again still fails the attempt, whose reason then says so. The re-run is recorded as
  `task.tests_rechecked`. The rest of the step reads run 1's report with each flaky test's passing case. The re-run
  starts only when the soft deadline leaves room for it and the tree can be put back (L4-IMP-105).
- `verification.md` lists every pre-existing test that passed only on a task step's re-run, from the ledger
  (L4-VER-082).

Non-goals: a renewal for an answer that unfreezes nothing, for a red or single step, or for the deadline's stop count
(L4-IMP-071); selecting single tests inside the consumer's command (the gate runs whole, as in L4-VER-076); the
repair chore (`_run_repair`); a new finding or a change to the verdict.

## Capabilities

### New Capabilities

- `attempt-window-recheck`: L4-IMP-104 (an answer that unfreezes a task's file renews its green attempts, once per
  question, bounded), L4-IMP-105 (a step re-runs its test gate once before failing on regressed pre-existing tests),
  L4-VER-082 (verification lists the tests a step's re-run passed).

### Modified Capabilities

- L4-IMP-075: the window of green's failure counts also starts after a `task.attempts_renewed` of the task.

## Impact

- `src/l4/implementer/loop.py` (`seed_attempts`, `_run_task`, a new `_renew_on_answers`), `src/l4/implementer/tdd.py`
  (`run_red`, `run_green`, `run_single`, `RedVerdict`, `classify_red`, `green_failures`), a new
  `src/l4/implementer/recheck.py`, `src/l4/verifier/gate_repeat.py` (`untouched`, `short_of_time`: shared, no change of
  behaviour), `src/l4/verifier/types.py` (`VerifyResult.step_flakes`), `src/l4/verifier/ladder.py`,
  `src/l4/verifier/report.py`, `src/l4/verifier/evidence.py`.
- `docs/SPEC.md` (L4-IMP-104, L4-IMP-105, L4-VER-082, the L4-IMP-075 amendment, SCN-IMP-566..576, SCN-VER-322..323,
  change-table row 140, ledger §12.1), `docs/runbook.md`, `CHANGELOG.md`.
- Ledger: two new events, `task.attempts_renewed` and `task.tests_rechecked`. An older harness ignores both. No
  configuration key.
- Cost: at most one more test-gate run per attempt, only for an attempt that would otherwise fail on one to five
  regressed pre-existing tests. At most two more windows of green attempts per task between two `l4 retry`,
  `l4 resume` or `l4 restart`.
