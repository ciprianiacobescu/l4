# A unit's own new test that fails before it checks anything gets one reviewed repair step

## Why

On a consumer (2026-10-30, harness 0.4.43) a unit's red step wrote an end-to-end test that raised an error from its
test library before any check (an argument type that the library version does not accept). Red and green run only
`gates.test`, so no phase that may write tests ever ran it [V]. Verification failed it; every fix chore may not change
test files (ci-evidence D11), so the guard put back the agent's correct one-line edit of the test, and an unattended
plan waited on the owner's commit. Worse, another fix chore bent correct product code to suit a second broken test of
the same unit [V]. fix-chore-e2e makes such a chore fail honestly; it still cannot repair the test.

A test the unit itself added (absent at the unit's base, written by one of its red steps), that fails with an error of
the test or its library rather than an assertion, is the unit's own unfinished work. Letting a fix chore change it in
general would let a model weaken a test until it passes. A narrow step can repair it: only the bodies of those tests,
no assertion removed, no skip added, no product code changed, checked against the gate it failed in, and seen by the
judge in the next round.

## What changes

- When a round's failures (`verdict.json` `failures`, fix-chore-e2e) include tests that the unit added (absent at the
  unit's base, present after a red commit of the unit), in a Python test file, whose failure kind is not `assertion` or
  `not_implemented`, the fix unit gets a `repair` chore for them (the marker's `repairs`), not a plain fix chore. The
  task says that the test may be right and the code wrong.
- The repair step (`run_single(kind="repair")`, its own prompt `single_repair`) may change only the definitions of
  those tests, and add imports. Every other test, helper, fixture and module statement of the file must be unchanged
  (the AST facts of `l4.implementer.tamper`), the decorators of the repaired tests too; the number of `assert`
  statements and `expect(...)`/`assert…(...)` calls of each repaired test must not drop; no `skip`/`xfail`/
  `importorskip` may be added. A change to any other file fails the attempt (product code is frozen in this step).
  Then the gate the test failed in runs (the test gate, or the build and the e2e gate) and the repaired tests must
  pass in it.
- The commit carries `L4-TDD: exempt` and the ledger `task.repaired{task, files, tests}`; the verifier's test-path and
  red-freeze checks accept those files of that task, and nothing else.
- When the repair attempts are used up, the task escalates to a person as a fix chore does, saying that the test may be
  right and the product code wrong.

## Impact

- Code: `l4.verifier.fixunit` (repair candidates), `l4.specs.fixmark` (`repairs`, `chore_kind` `repair`),
  `l4.implementer.tdd` (`run_single` kind `repair`), a structural check next to `l4.implementer.tamper`, a
  `single_repair` template and the template lock, `l4.verifier.integrity` (`_allowed_in_step` and the red-freeze check),
  `l4.implementer.guardnotes` (the advice).
- Spec: L4-IMP-091 and L4-VER-070 added; ci-evidence D11 amended (one narrow exception: a reviewed repair of the unit's
  own new test); SCN-IMP-450 to SCN-IMP-457 and SCN-VER-257 added; change-table row 104.
- Not in this change: non-Python tests (no AST check; they go to a person as today); tests that existed at the unit's
  base; a failure by assertion (that is a finding about the code).
- Residual risk: a rewritten assertion that is weaker but still passes survives the structural check; the judge sees
  the diff in the next round.
