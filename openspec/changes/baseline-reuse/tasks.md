## 1. Record and reuse (L4-IMP-088)

- [x] 1.1 Write the tests first (tests/unit/implementer/conftest.py `make_bench`, `red_step`/`green_step`,
  `FakeAdapter`; count `gate.finished` names as tests/unit/implementer/test_tdd_red.py does). Then implement design D1
  to D3 in `l4.implementer.workbench` (the slot, the tree of the worktree) and `l4.implementer.tdd` (`run_green`,
  `run_single`, `baseline`). Cases: SCN-IMP-432 to SCN-IMP-437; the verifier still finds `wb.baselines[base_sha]`;
  tests/unit/implementer/test_tdd_red.py and tests/unit/implementer/test_setup.py still pass.
  Result: tests/unit/implementer/test_baseline_reuse.py (21 tests) covers SCN-IMP-432 to 437 and passed. Before the code
  they failed for the missing feature (`baseline()` took no `task`, no `gate.reused`, no `Workbench.last_tested`).
  `l4.vcs.wip.worktree_tree` writes the worktree as a tree through a temporary index. `Workbench` gets `last_tested`
  (a `KeptRun`), `incidents` (a count of `guard.violation` and `env.rebuilt` events in `emit`), `gate_digest`,
  `mark_tested` and `keep_tested`; `discard_changes` and `agent_step` clear the slot. `run_green` and `run_single` take
  the mark right before the test gate (none when `fix_gate_env` returns an environment) and keep it after the commit.
  `baseline(wb, base_sha, task=None)` reuses it through `reused_baseline` (a `diff-tree` of the kept tree against the
  base's tree, only the ledger, `tasks.md` and `.l4/held/` may differ) and records `gate.reused{name, from, task,
  source_sha, tree}`; `task` is the task the baseline serves. Two readings of the design: the incident window runs from
  the mark to the end of `keep_tested` (so it also covers the zero-value runs, the static gates and the commit, the
  conservative side), and the slot is cleared at the end of `agent_step`, next to `setup_at`, not before the agent
  runs (no gate runs in between). The `run_red` that follows a reuse still runs `run_setup` at the new head, as before.

## 2. Checks

- [x] 2.1 Run only the test files you changed or added plus tests/unit/implementer/test_tdd_clean_head.py, once each
  (the machine is loaded; CI runs the full suite), then ruff check and ruff format on the changed files. Report counts.
  Result: ran test_baseline_reuse.py (21 passed), test_tdd_clean_head.py (3 passed), test_tdd_red.py (48 passed) and
  test_setup.py (16 passed), one command each; ruff check and ruff format are clean on the four changed files.
