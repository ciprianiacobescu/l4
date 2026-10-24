# Tasks: retry-names-stopped-plan

## 1. `l4 retry` names a stopped plan that holds the unit (L4-OPS-002)

- [x] 1.1 Tests first, in the tests of `run_retry` (find them with `grep -rln run_retry tests/unit`; reuse their fixtures
  for a repository with a halted unit and the forge start mocked): with a committed plan file listing the unit and a plan
  state `stopped` (`stop_reason: unit_halted`), the retry succeeds, prints
  `plan <id> is stopped (unit_halted): the unit runs again after: l4 yolo resume <id> --reason TEXT`, and does not call
  the forge start; with the plan `active`, the start is called as before and no such line is printed; with no plan file,
  as before; with `--no-run` and a stopped plan, the hint line and no start; when the plan lookup raises, the retry still
  succeeds and starts the run. They fail before the change because the retry starts the run and prints no hint. Then in
  `src/l4/state/retry.py`, after a successful `retry_unit`, find the plans holding the unit as `l4 yolo status` does
  (look at how `src/l4/yolo/commands.py` builds the status: `plan_files_at`, `holds_of`, the fold of each plan's ledger)
  and print the line and skip `start_run_line` when one of them is `stopped`.
  Result: `run_retry` is covered by 6 new tests in `tests/unit/state/test_retry.py`; the stopped-plan cases failed because the retry started the run (`run started on main`) and printed no hint; `stopped_plan_holding` added to `src/l4/state/retry.py` (lazy imports of `l4.yolo`, any error logged at debug and ignored), `run_retry` prints the line and skips `start_run_line` for a stopped holder, `--no-run` included.
- [x] 1.2 `docs/SPEC.md`: L4-OPS-002 gains "unless a plan that holds the unit is `stopped`: the retry then prints
  `plan <id> is stopped (<reason>): the unit runs again after: l4 yolo resume <id> --reason TEXT` and starts no run",
  the command table row of `l4 retry` says the same in a few words, and a scenario "#### SCN-OPS-45 (+) A retry names
  the stopped plan that holds the unit · L4-OPS-002". `docs/runbook.md`: the `halted` procedure says that when the halt
  stopped a plan, `l4 yolo resume <plan> --reason TEXT` follows the retry. A change-table row 72
  (`retry-names-stopped-plan`); a `### Fixed` line in CHANGELOG 0.4.30. Run `scripts/check_spec.py docs/SPEC.md` and the
  docs tests.
  Result: L4-OPS-002 gains the exception, the `l4 retry` command-table row says the same, SCN-OPS-45 added after SCN-OPS-44, runbook 7.2 step 6 names the line and `l4 yolo resume` (12.3), change-table row 72, CHANGELOG 0.4.30 Fixed; `scripts/check_spec.py docs/SPEC.md` exits 0 and `tests/unit/docs` passes.
