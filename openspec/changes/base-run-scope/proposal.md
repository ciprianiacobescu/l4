## Why

In a consumer's TypeScript unit (Node's test runner, a Postgres test cluster), the last task of the unit added one test
file whose five tests passed at head: the task's text said it needed no green code. The zero-value run varies Python
files only, so the base run (L4-IMP-003) had to decide. It hit the 30-minute gate timeout on every attempt (three of
three) while the same suite at head took about 5 minutes. With no report the check could not decide, the task was held
with a `pre_satisfied` question each time, and the unit stood for about four hours.

A local reproduction of that base run (the unit's code files swapped to their content at the unit base, every test file
as the work tree held it, as `base_run.py` does) showed why: every file finished within minutes except a test file that
an EARLIER task of the same unit had written. Against the base code it opened seven local listening servers and never
closed them, so its test process never exited and the runner waited for it until the gate's timeout. Its seven tests
take 3 to 8 seconds each at head. The runner's own per-test limit does not help: the tests end, the process does not.
That file decides nothing: the base run only reads the outcome of the step's own candidate tests.

The same reproduction with the unit's other test files set aside (added ones removed, changed ones at their base
content) finished in about 7 minutes under heavy load and wrote a report. All five candidates failed there by assertion,
which L4's own classifier (`variant.test_outcome`) reads as a proof: the base run would have confirmed the task with no
question.

## What Changes

- The base run puts the unit's other test files at the unit base for its run: a file that holds a test of the head
  report, that the unit added or changed (by commits or in the work tree), and that holds none of the tests the base run
  decides is removed for the run when the unit added it, and holds its unit-base content when the unit changed it.
  Every such file is put back byte for byte (sha256 checked) before anything else runs, like the production files.
  Test support files and files that hold no reported test (fixtures, data, `conftest.py`) stay as the work tree holds
  them. When the file of any decided test cannot be found, nothing is set aside and the run is today's.
- The base run gets its own time limit: twice the wall time of the step's own test gate, at least 5 minutes and at most
  `gates.timeout`. A base run that runs past it is stopped and decides nothing, as a timed-out base run does today; its
  reason names the limit.
- The ledger records the scope of each base run (`base_run.scope`).

## Capabilities

### New Capabilities

- `base-run-scope`: L4-IMP-097, the base run runs the step's candidates without the unit's other test files and within
  its own limit.

### Modified Capabilities

- L4-IMP-003 (confirmation by a base run): which test files stay as the work tree holds them, and the run's limit.

## Impact

- `src/l4/implementer/base_run.py` (`confirmed_by_base_run`, a new context manager), `src/l4/implementer/tdd.py` (both
  call sites pass the step's test gate time), `src/l4/implementer/discrimination.py` (`run_with_code_of` takes a time
  limit), `src/l4/implementer/workbench.py` (`run_gate` takes a time limit), `src/l4/gates/runner.py` (`GateResult`
  carries the run's wall time).
- `docs/SPEC.md` (L4-IMP-003, the new L4-IMP-097, SCN-IMP-526..532, change-table row 127), `CHANGELOG.md`.
- Limits: a candidate test that imports another of the unit's test files errors in the scoped run and is not confirmed by
  it (the hold that follows says so); a candidate file that itself leaves its process running still meets the limit, now
  after twice the test run instead of after `gates.timeout`.
