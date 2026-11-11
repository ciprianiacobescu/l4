## 1. The wall time of a gate and a per-call limit (D3)

- [ ] 1.1 Write the tests first: in `tests/unit/gates/` (next to the existing `run_gate` tests; find them with
  `grep -rln "def test.*timed_out\|timed out after" tests/unit/gates`), a gate whose command sleeps briefly gives
  `GateResult.seconds > 0`, a gate that cannot start gives `0.0`; in `tests/unit/implementer/test_base_run_scope.py`
  (new), `Workbench.run_gate(name, command, timeout_s=1)` on a command that sleeps 5 seconds is stopped with
  `timed_out` and the reason `timed out after 1s`, and without `timeout_s` the limit is `gates.timeout`. Run them and
  see them fail.
- [ ] 1.2 Then add `seconds: float = 0.0` to `GateResult` (last field, so positional construction elsewhere keeps
  working), measured in `gates.runner.run_gate` around the process run (`time.monotonic()`), and `timeout_s: int | None
  = None` to `Workbench.run_gate` (used for `GateSpec.timeout_s` when given) and to `run_with_code_of` (passed on). Run
  `uv run --frozen pytest tests/unit/gates tests/unit/implementer/test_base_run.py tests/unit/implementer/test_base_run_scope.py -q`.

## 2. The scope of the base run (D1, D2, D4)

- [ ] 2.0 Read, before writing code, what the guards of a red step compare, and confirm design D2's last paragraph:
  `Workbench.run_gate_spec` (`snapshot_protected`, `restore_protected`, `revert_unsnapshotted`), `held_patch.ReplayGuard`
  (`restore_replay`, `_restore_one`), `stubs.ProductionGuard.check`, and `tdd._preexisting_changes` /
  `preexisting_test_changes`. If any of them keys on a file's modification time, inode or presence at gate time rather
  than its content, stop and report it instead of going on.
- [ ] 2.1 Write the tests first in `test_base_run_scope.py`, with the fixtures and helpers of
  `tests/unit/implementer/test_base_run.py` (`make_bench`, `step`, `commit_head`, `zero`, `based`, `snapshot`,
  `porcelain`; import or copy what you need). To see the work tree during the run, wrap `Workbench.run_gate` with a spy
  that records, for a gate named `test-base-run`, which of the paths of interest exist and their sha256, then calls the
  real one.
  - SCN-IMP-526: an earlier commit adds `tests/test_earlier.py` (a test that traces another criterion and passes at
    head) with the head code; the red step adds `tests/test_new.py` (`FAILS_AT_BASE`). During `test-base-run`,
    `tests/test_earlier.py` is absent and `tests/test_new.py` present; after it, both are back (snapshot equal);
    `run_red` ends `already_satisfied` with `via: base_run`; the `base_run.scope` event has `aside:
    ["tests/test_earlier.py"]`, `kept: ["tests/test_new.py"]`, `unscoped: ""`.
  - SCN-IMP-527: an earlier commit changes a test file that exists at the unit base (create it before the unit base in
    the bench's repository, as the bench creates its base files, or commit it on the base branch first; read
    `conftest.py` for how the unit base is made): during the run it holds the base content (`at_base`), after it the
    head content.
  - SCN-IMP-528: the red step appends its candidate test to `tests/test_earlier.py`: the file stays whole during the run
    (its earlier test included) and is under `kept`.
  - SCN-IMP-529: an earlier commit adds `tests/conftest.py`, `tests/fixtures/data.json` and a support file matching the
    bench's `tdd.test_support_globs`: all three are present and unchanged during the run.
  - SCN-IMP-530: monkeypatch `l4.implementer.base_run.file_of_id` to return None for the candidate: nothing is set aside
    (`tests/test_earlier.py` present during the run), and the event says `unscoped: "the file of tests.test_new::test_new_total was not found"`.
  - A linked test file (a symlink under `tests/` that holds a reported test) makes the run unscoped, and the link is
    unchanged after it.
  - A test file of the unit under a protected path (configure `odd.forbidden_paths` in the bench to cover it, or use a
    `**/migrations/**` path) stays during the run.
  - `test_base_run.py::test_scn_imp_301_...` must still pass unchanged: its earlier commit's test file
    (`tests/test_middleware.py`) is now set aside for the run, and the outcome is the same.
  - SCN-IMP-532: parametrize `confirmed`, `timed_out` (spy returns a timed-out `GateResult` without running) and
    `gate_error` (spy raises): the snapshot and `porcelain` are equal before and after, and no `restore failed` is
    recorded (`bench.events("guard.restore_failed")` or the name the code uses; grep `restore failed` in
    `discrimination.py`).
  Run them and see them fail.
- [ ] 2.2 Then add the context manager `other_tests_at_base` and `Scope` to `src/l4/implementer/base_run.py` (design D2;
  reuse `_read`, `_put`, `_unlink`, `_restore`, `_drop_bytecode`, `worktree_files`, `own_test_files` and
  `test_locate.file_of_id`; do not change `_canonical` or `red_code_in_place`), use it in `confirmed_by_base_run` around
  `run_with_code_of`, and emit `base_run.scope` (design D4) before the gate. Update the module docstring (the
  `test files ... stay as the worktree holds them` sentence). Run the tests of 1.2 plus
  `tests/unit/implementer/test_presatisfied_other_language.py tests/unit/implementer/test_already_satisfied_no_test.py
  tests/unit/implementer/test_unchanged_on_base.py tests/unit/implementer/test_held_check.py -q`.

## 3. The limit (D3)

- [ ] 3.1 Write the tests first (SCN-IMP-531): with `gates.timeout: 30m`, `confirmed_by_base_run(...,
  head_seconds=200.0)` calls the gate with `timeout_s=400`, `head_seconds=10.0` with 300, `head_seconds=1200.0` with
  1800, `head_seconds=0.0` with 1800 (spy on `run_with_code_of` or `Workbench.run_gate`); a spy that returns a timed-out
  result at 400 gives a classified reason containing `the base run's own limit` and leaves the criterion inconclusive
  (the run decides nothing); at 1800 (no own limit below `gates.timeout`) the reason is unchanged (`timed out after
  1800s`); `run_red` passes the step's test gate `seconds` at both call sites (spy on `confirmed_by_base_run` in
  `l4.implementer.tdd` and check `head_seconds > 0`). Run them and see them fail.
- [ ] 3.2 Then add `head_seconds: float = 0.0` to `confirmed_by_base_run` with `BASE_RUN_FLOOR_S = 300`,
  `BASE_RUN_FACTOR = 2` and the reason of design D3, and pass `head_seconds=gate.seconds` at both call sites in
  `run_red`. Run every test file named in 1.2 and 2.2.

## 4. Documents

- [ ] 4.1 `docs/SPEC.md`: in L4-IMP-003's paragraph **Confirmation by a base run**, after "while test files, test support
  files and harness, spec and documentation paths (evidence kind `exempt`) stay as the worktree holds them", add
  "(except the unit's own test files that hold none of the tests the run decides, which are at the unit base for the
  run, L4-IMP-097)", and after "Every file touched is put back byte for byte (sha256 checked) before anything else
  runs." add "The run has its own limit (L4-IMP-097)."; add L4-IMP-097 after L4-IMP-096 (or after L4-IMP-095 when
  L4-IMP-096 is not in this branch) with the text of `specs/base-run-scope/spec.md`; add SCN-IMP-526..532 after the last
  SCN-IMP scenario; add `base_run.scope` wherever the SPEC lists ledger event types (grep `criterion.pre_satisfied`
  in the SPEC's event catalogue, if it has one); add row 127 `base-run-scope` to the change table of section 21 (what
  changed, the functions, the consumer case in neutral words (a consumer's TypeScript unit: the base run hit the
  30-minute gate timeout three times because an earlier task's test file left its process running against the base
  code; a reproduction with the unit's other test files set aside wrote a report in about 7 minutes and confirmed the
  five candidates), the limits of the proposal, the ids, `openspec/changes/base-run-scope/`, the test file
  `test_base_run_scope`).
- [ ] 4.2 `CHANGELOG.md`: under `## Unreleased`, one entry in the style of the 0.4.56 entries (L4-IMP-097).
- [ ] 4.3 Run `uv run --frozen python scripts/check_spec.py`, `uv run --frozen pytest tests/unit/docs -q`,
  `uv run --frozen ruff check src tests` and `uv run --frozen ruff format --check src tests`.
