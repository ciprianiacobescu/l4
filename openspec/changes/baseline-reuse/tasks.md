## 1. Record and reuse (L4-IMP-088)

- [ ] 1.1 Write the tests first (tests/unit/implementer/conftest.py `make_bench`, `red_step`/`green_step`,
  `FakeAdapter`; count `gate.finished` names as tests/unit/implementer/test_tdd_red.py does). Then implement design D1
  to D3 in `l4.implementer.workbench` (the slot, the tree of the worktree) and `l4.implementer.tdd` (`run_green`,
  `run_single`, `baseline`). Cases: SCN-IMP-432 to SCN-IMP-437; the verifier still finds `wb.baselines[base_sha]`;
  tests/unit/implementer/test_tdd_red.py and tests/unit/implementer/test_setup.py still pass.

## 2. Checks

- [ ] 2.1 Run only the test files you changed or added plus tests/unit/implementer/test_tdd_clean_head.py, once each
  (the machine is loaded; CI runs the full suite), then ruff check and ruff format on the changed files. Report counts.
