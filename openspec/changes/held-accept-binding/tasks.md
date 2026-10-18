Every task follows these rules:
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .` and
  `ruff format --check` on the files that changed. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Keep and replay (L4-IMP-065)

- [ ] 1.1 Tests first (`tests/unit/implementer/test_held_accept.py`), then `held_patch.py`, `held.py`, `tdd.py`,
  `loop.py`, `workbench.py`: capture, `_raise_held` writes and commits, replay in `run_red`, `run_green`,
  `run_single`, refusals, retry and cleanup, the `accepted tests` block, the protected path.
- [ ] 1.2 Docs: L4-IMP-065 and SCN-IMP-320..326, L4-IMP-063's text, the change table (row 48), the runbook and the
  skill, CHANGELOG `0.4.17`, and the `l4 questions answer` line.
