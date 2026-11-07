## Why

A consumer's TypeScript unit changed only interpreter code. Its first verification round failed on one pre-existing
browser test, a sign-in page test that the unit never touched; the same test had failed the same way on the consumer's
main branch days earlier, and the e2e gate of main at the same base passed. Step 3 runs `gates.test` and `gates.e2e`
once at the unit's head, and any failing test fails the step, so the round was FAIL and a fix unit was spawned for the
finding `e2e gate failed`. The fix agent could only touch the frozen test, the guard put it back ("nothing changed"),
the delegate escalated to a person, and a person had to commit a test fix: about three hours lost on a flake.

`verifier.flaky_repeats` (default 3) is declared in the schema and read nowhere. The SPEC's step-3 row says "each new
test repeated `flaky_repeats` times — any flip = flaky finding", and SCN-VER-05 ("Flaky new test") and SCN-VER-44 use
it, but no code or test does it. The only repeat in the verifier is step 1's: the run of the base's tests on the unit's
code repeats the test gate once when something failed, and a test that passes on the repeat is the minor finding `a
pre-existing test is flaky on the unit's code` (L4-VER-038). Step 1 runs only when the unit changed a test or support
file, so it did not run for this unit.

## What Changes

- When step 3's test gate or e2e gate fails and every failing test is pre-existing (not a red test of the unit, in a
  file of the head tree that `git diff <base> <head>` does not name) and at most five tests failed, the verifier runs
  the same gate again, as a whole, named `<gate>-repeat-<n>`, until every failing test has passed once, a run is not
  usable, a test that is not pre-existing fails, or the gate has run `verifier.flaky_repeats` times in all (default 3:
  at most two repeats; 1: none).
- A test that failed in one run and passed in another is the minor finding `a pre-existing test is flaky in the <gate>
  gate` and no longer fails the step. A pre-existing test that failed and never passed, and a test that is not
  pre-existing and failed in any run, keep the blocker `<gate> gate failed`, now naming only those tests.
- The report that step 3 hands on is the first run's with each flaky test's passing case; `failures` holds only the
  tests that still fail, so no fix chore is asked for a flaky test.
- Each gate that was repeated is recorded as `verify.gate_repeat{round, gate, runs, flaky, failing, stopped}`; each
  run has its own `gate.finished` and its own row in the Gates table of `verification.md`, where the first run's row
  reads `flaky` when every failure was flaky.
- The SPEC states what is done: the step-3 row of L4-VER-002, the §3.2 comment of `flaky_repeats`, the examples of
  L4-VER-003; SCN-VER-05 and SCN-VER-44 are rewritten in place (new tests are never repeated).

## Impact

- Code: a new module `l4.verifier.gate_repeat` (the candidate rule, the repeat loop, the finding); `l4.verifier.gates`
  (`run_test_gate` and `run_e2e_gate` take a gate name, `TestGateOutcome.ok` counts blocking findings only, a
  `repeats` field); `l4.verifier.types.GateLine.status` gains `flaky`; `l4.verifier.ladder` step 3 calls the loop for
  each gate; `l4.verifier.fixloop.failure_set` skips the rows of repeats.
- Spec: L4-VER-076 (new); the step-3 row of L4-VER-002, the unit-verdict examples of L4-VER-003, the §3.2 comment and
  the §12.1 event list amended; SCN-VER-05 and SCN-VER-44 amended; SCN-VER-288..297; change-table row 121.
- Behaviour: a round whose only failures are a few pre-existing tests in files the unit did not change costs one more
  gate run when the tests pass on it (two at most by default) and passes step 3 with a minor finding in place of
  spawning a fix unit. A pre-existing test that fails on every run costs two more gate runs before the blocker.
  Failures of the unit's own tests, and every other kind of gate failure, are judged as before, with no repeat.
- Not changed: step 1's repeat (L4-VER-038), the implementer's gates, new tests (never repeated), the fix chores and
  the rule that a fix chore which changed nothing is not done ("A fix chore that changed nothing is not done", 0.4.45;
  L4-IMP-090; only a retake completes without a change, L4-FBK-005).
