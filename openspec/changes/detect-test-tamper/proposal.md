## Why

An independent review of 0.4.13 confirmed four findings with reproductions; all four still hold at 0.4.14 (design
section 1, re-run in this worktree):

- **verifier-2 (blocker):** step 1 never detects a weakened pre-existing test. Reproduced as a false PASS on broken code:
  the red step rewrote `assert total([1.25, 2.5]) == 3.75` to `is not None`, green made `total()` return `999.0`, and
  the verdict was PASS. `integrity.check_tests` compares only the names of tests and the skip markers.
- **implementer-4 (major):** a red step can weaken or shadow (a second `def` of the same name) a pre-existing test, and
  neither red nor the verifier sees it. SPEC L4-IMP-006 (2) and (5) ask for tamper detection per test on the AST; it is
  not built.
- **verifier-6 (blocker):** audit tests run with the unit's own `conftest.py` in place. Reproduced: an autouse fixture
  that swaps the code under test for a correct one while a constant is set made the audit pass on `return amount`, and
  the verdict was PASS. SPEC 10.2 row 4a already says the support files are reverted to the base for that run.
- **verifier-8 (minor):** a deleted pre-existing test is hidden when any other changed test file defines a test of the
  same bare name, whatever its body; a person's deletion is then not listed either.

## What Changes

- **One comparison** (`src/l4/implementer/tamper.py`, L4-IMP-045..047): a test is its file and qualified name; it is
  compared as every statement that binds its name (decorators, parametrisation, requested fixtures, body) plus what it
  uses in its own file (helpers, constants, fixtures, autouse fixtures, `pytestmark`, module setup, its class). A second
  binding is a change. A deleted test is moved only when the same definition appears under a new file or name.
- **Red** (L4-IMP-048, L4-IMP-006 (2) and (5)): after `classify_red` accepts the step, a pre-existing test that the step
  changed, rebound or deleted fails the attempt with `guard.test_tamper{rule: "pre-existing test", action: "rejected"}`
  and a retry text that says what to do. A reopened task's stale tests and a `[test-infra]` task are allowed.
- **Step 1** (L4-VER-030..032): the same comparison from the base to head. A harness change is a blocker
  (`a pre-existing test was changed` / `…deleted`) unless `tests.superseded`, a `[test-infra]` task or a `task.unfrozen`
  of the same task allows it; people's changes are listed. A later red commit that changes a test an earlier step of the
  unit wrote is a blocker too.
- **Step 4a and step 5's head run** (L4-VER-033..036): the unit's added, changed or deleted test-support files are put at
  their base versions for the run and restored byte for byte; a test that does not run that way runs with them only
  when step 1's content scan is `ok`, else it is rejected. `verify.audit`, `verify.generated` and verification.md say
  which way each test ran.

## Impact

- Code: new `src/l4/implementer/tamper.py`, `src/l4/verifier/support_base.py`; `implementer/tdd.py` (`run_red`),
  `implementer/guardnotes.py`, `implementer/discrimination.py` (`extra_env` for the zero-value run),
  `verifier/integrity.py` (`check_tests`), `verifier/types.py`, `verifier/audit.py`, `verifier/generate.py`,
  `verifier/ladder.py`, `verifier/report.py`. Tests under `tests/unit/implementer/` and `tests/unit/verifier/`, the
  reviewer's four reproductions among them.
- Spec: L4-IMP-045..048 and L4-VER-030..036 added; L4-IMP-006 and L4-VER-002 (rows 1, 4a, 5) modified;
  SCN-IMP-260..277, SCN-VER-100..123.
- Behaviour a consumer sees: a red attempt that edits an existing test now fails and is retried; a unit whose branch
  weakened a pre-existing test fails step 1 (a person restores the test on the unit branch); an audit test that relied
  on the unit's own `conftest.py` is held or rejected instead of accepted. Nothing changes for a unit that leaves its
  existing tests and support files alone.
- Docs: `docs/SPEC.md`, `docs/runbook.md` (what to do with the new blockers), `CHANGELOG.md` under `## 0.4.16
  (unreleased)`.
