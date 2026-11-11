## Context

`confirmed_by_base_run(wb, candidates, new_ids, *, real)` (`src/l4/implementer/base_run.py`) runs the test gate as
`test-base-run` through `run_with_code_of(wb, base, paths, name="test-base-run")`: the production files changed since
the unit base (`_plan`: commits plus the work tree, less test, support and exempt paths) are swapped to their base
content, added ones are set aside, everything is put back by sha256 (`red_code_in_place`). Test files and test support
files stay as the work tree holds them: `_canonical` refuses a path under the test or support globs, so
`red_code_in_place` cannot touch one. The run is classified (`variant.classify`) and only the outcomes of the decided
tests are read: `variant.test_outcome(run, t, real, own, zero_value=False)` for `t` in `candidates[c]` that are in
`new_ids` (at the no-new-test call site `new_ids` is every candidate test).

It is called from two places in `run_red` (`src/l4/implementer/tdd.py`): the new-tests path (`left` candidates,
`new_ids`) and the no-new-test path (`left`, `every`). At both, the step's `test` gate result (`gate`) and its report
(`report`, passed as `real`) are in scope.

`run_gate` (`src/l4/gates/runner.py`) runs a `GateSpec` whose `timeout_s` is `gates.timeout` for every gate
(`Workbench.run_gate` builds it); a command that runs past it is stopped and gives `result("fail", "timed out after
<n>s", timed_out=True)` with no report. `GateResult` carries no duration.

The test files of a unit are found today by `own_test_files(wb)` (the test and support files the unit added or changed:
the work tree's changes and `git diff --diff-filter=AM <unit base> HEAD`). A test id is mapped to its file in any
language by `test_locate.file_of_id(test_id, worktree_files(wb), own)` (exact path, the path with dots for slashes, a
dotted Python module, or the end of such a path; ambiguous matches resolved by `own`).

## Goals / Non-Goals

**Goals:** a base run that runs the step's candidate tests against the unit base code without the unit's other test
files, so that one of them that cannot finish at the base cannot keep the run from writing a report; a base run that
does not finish is stopped within a bound tied to the step's own test run, not after `gates.timeout`.

**Non-Goals:** narrowing the runner's command to files (runner-specific: L4 cannot rewrite a `pnpm run test` script);
a change of what a base run proves (L4-IMP-003, L4-IMP-060), of the zero-value run, of `test-at-red` or of the
verifier's runs; reading a partial report of a stopped run; the limit of any other gate.

## Decisions

### D1. The decided tests and their files

`decided = sorted({t for tests in candidates.values() for t in tests if t in new_ids})`. With `files =
worktree_files(wb)` and `own = own_test_files(wb)`, `keep = {file_of_id(t, files, own) for t in decided}`. When any of
them is None, or `real` is None, the run is unscoped: nothing is set aside (today's run), and the scope event says why
(`unscoped: "the file of <id> was not found"`, `"no head report"`).

### D2. Which test files are put to the unit base

The *reported files* are the files of the head report's tests: `file_of_id(head, files, own)` for each distinct id head
(the part before the first `::`) of `real.tests` and `real.collection_errors`, so a file is mapped once however many
tests it holds. The files put to the unit base for the run are the reported files that are in `own`, that are not in
`keep`, and that match `tdd.test_globs` and not `tdd.test_support_globs`. A file that holds no reported test (a fixture,
data, `conftest.py`, a helper module under a test glob) is never touched, and neither is a test support file.

For each such file: when it exists at the unit base (`git cat-file -e <base>:<path>`), its content is that blob for the
run; when the unit added it, it is removed for the run. Before the gate runs, every file is read through the no-follow
helpers of `discrimination.py` (`_read`); a file that is a link, is outside the work tree, cannot be read, or is larger
than `MAX_VARIED_BYTES`, makes the run unscoped (D1's fallback): nothing is set aside and the scope event names the
file. The swap uses `_put` and `_unlink` and the restore uses `_restore` (sha256 checked; a mismatch is the existing
`restore failed` record, never an exception), in a `finally` around `run_with_code_of`, so the work tree is
byte-identical after the run whatever the gate did (the guarantee of SCN-IMP-86).

The context manager lives in `base_run.py`:

```python
@contextmanager
def other_tests_at_base(wb: Workbench, base: str, keep: Collection[str], real: TestReport) -> Iterator[Scope]:
    """L4-IMP-097: the unit's own test files that hold none of the decided tests, at the unit base for the run."""
```

`Scope` holds `at_base` (changed files given their base content), `aside` (added files removed) and `unscoped` (the
reason, empty when scoped).

### D3. The base run's own limit

`GateResult` gains `seconds: float = 0.0`, the wall time of the command (measured in `gates.runner.run_gate` around the
process run; 0.0 for a gate that did not start). `Workbench.run_gate(..., timeout_s: int | None = None)` uses
`timeout_s` instead of `gates.timeout` when given; `run_with_code_of(..., timeout_s: int | None = None)` passes it on.
`confirmed_by_base_run(..., head_seconds: float = 0.0)` computes

```python
limit = duration_seconds(wb.cfg.gates.timeout)
bound = min(limit, max(BASE_RUN_FLOOR_S, ceil(BASE_RUN_FACTOR * head_seconds))) if head_seconds > 0 else limit
```

with `BASE_RUN_FLOOR_S = 300` and `BASE_RUN_FACTOR = 2`. Both call sites in `run_red` pass `head_seconds=gate.seconds`.
When the run is stopped at a bound below `gates.timeout`, the gate result's reason becomes `timed out after <bound>s:
the base run's own limit, twice the step's test run (at least 300s)` (`dataclasses.replace`), so the classified run's
reason (`the test-base-run run wrote no readable report (...)`) and the hold that follows name it.

Why twice the step's test run: the scoped base run runs no more tests than the step's own run (the same suite less the
unit's other test files) against older code; twice leaves room for a loaded machine. Why a floor: a suite of seconds
would get a bound that a slow start (a test database, a build) can pass. The factor and the floor are constants, not
configuration: `gates.timeout` stays the one knob, and the bound never exceeds it.

### D4. The ledger

Before the gate, `wb.emit("base_run.scope", decided=len(decided), kept=sorted(keep)[:20], at_base=sorted(at_base)[:50],
aside=sorted(aside)[:50], more=<count left out of the two lists>, timeout_s=bound, unscoped=<reason or "">)`. Paths are
work-tree relative; no test source is recorded.

## Risks / Trade-offs

- A candidate test that imports another of the unit's test files (a shared helper defined in a test file) errors in the
  scoped run: an error is no proof, so its criterion stays as the zero-value run left it (inconclusive: the task is held,
  as today when the run gives no answer). Moving such a helper to a support file avoids it.
- A file the unit changed that also defines a fixture another kept file imports gets its base version for the run; the
  same rule as above applies.
- A candidate file that itself never lets its process exit at the base still stops the run, now at the bound. The hold
  then names the bound.
- Mapping the head report's ids to files reads the work tree's file list once and maps each distinct id head once; for a
  suite of thousands of tests this is a few hundred `file_of_id` calls.
