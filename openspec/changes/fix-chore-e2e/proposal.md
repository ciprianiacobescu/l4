# A fix chore for a browser-test finding runs the browser tests, and a chore that changed nothing is not done

## Why

On a consumer (2026-10-30, harness 0.4.43) a unit's own new end-to-end test was broken: it called a Playwright
assertion with an argument type that version does not accept, so it raised an error before any check [V]. Red and
green run only `gates.test`, so nothing caught it before verification. Verification's step 3 ran the e2e gate, which
failed two tests, and made two findings for the same failures ("e2e gate failed" with the e2e log, and "new tests
failed" from the tests-ran check). Each became a plain fix chore. A fix chore (`run_single(kind="fix")`) runs only
`gates.test`, with an empty must-pass list, so:

- fix-1 task 1.1: the agent's edit of the test was put back by the guard (fix tasks may not change tests), nothing else
  changed, the test gate had no regression, and the task was ticked done with a commit of only `tasks.md` and the
  ledger [V];
- fix-1 task 1.2: the agent changed correct product code (an HTTP status the design fixes) to suit the second broken
  test, and nothing checked it against the e2e tests [V].

No record says which gate a failing test came from or why it failed (assertion or error), so nothing downstream can
tell a broken test from broken code.

## What changes

- Step 3 records, per failing test id, the gate it failed in (`test` or `e2e`), its failure kind and the first line of
  its message (redacted, capped), as a new `failures` map in the round's `verdict.json`.
- A fix chore whose finding is an e2e finding (the e2e gate failed, or failing ids that the round recorded under the
  e2e gate) runs `gates.build` (when configured) and the e2e gate after the test gate, with those ids as tests that
  must be in the report and pass. A server that never gets ready is a failed attempt with that reason, not a crash.
- A fix chore attempt in which the guard put back every edit and nothing else changed fails with `nothing changed: the
  guard put back every edit (<paths>)` instead of being ticked done. A chore for a CI job (ci-evidence D11/D12) keeps
  its rule (it commits the put-back chore, and `ci_not_fixed` reads it), and a retake keeps `_already_done`.
- A "new tests failed" or "new tests errored" finding whose ids are all among the failing ids of a failed gate finding
  of the same round becomes part of that finding's task: one task, not two.

## Impact

- Code: `l4.verifier.ladder` (`tests()`), `l4.verifier.report` (`verdict_json`), `l4.verifier.fixunit` (`_candidates`),
  `l4.implementer.tdd` (`run_single`), `l4.verifier.gates` (build and e2e runners reused), `l4.verifier.evidence`
  (`read_verdict`).
- Spec: L4-VER-069 and L4-IMP-090 added; L4-IMP-017 (the fix chore) amended; SCN-VER-254 to SCN-VER-256 and
  SCN-IMP-446 to SCN-IMP-449 added; change-table row 103.
- Not in this change: repairing the unit's own broken new test (a reviewed repair step, its own change). With this
  change such a unit's fix chore fails its attempts honestly and escalates to a person, instead of ticking done or
  bending correct code to the broken test.
