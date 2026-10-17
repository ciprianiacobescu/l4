Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Command (L4-YOLO-034)

- [ ] 1.1 Tests: SCN-YOLO-86..89 in `tests/unit/yolo/`; a parity test that `uncovered`/`covered_twice` match
  `scripts/validate_plan.py` on the same fixture trees.
- [ ] 1.2 `run_check(..., worktree=True)`, the coverage checks in the package, the `--worktree` flag in `cli.py`, the
  hints of `l4 yolo draft` and of the worktree review.

## 2. Docs

- [ ] 2.1 `docs/SPEC.md` (L4-YOLO-034, SCN-YOLO-86..89, the command table row of `l4 yolo check`, the change row), the
  skill's `plan.md` (Validate: lead with `l4 yolo check <id> --worktree`; the script is the fallback without the
  harness), `docs/yolo-mode.md`, `docs/runbook.md` §12, `CHANGELOG.md` under `## 0.4.14 (unreleased)`.
