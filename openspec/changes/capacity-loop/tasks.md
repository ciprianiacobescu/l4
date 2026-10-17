Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.

## 1. Plan step (L4-YOLO-035)

- [ ] 1.1 Tests: SCN-YOLO-90..92 in `tests/unit/yolo/`, with the yolo cycle test world and a fake availability park.
- [ ] 1.2 `yolo/cycle.py`: no chained run when the dispatched unit is `waiting_capacity`; the `capacity_needs_fix` stop
  after two identical fix-only parks; `l4 yolo resume` allowed after it.

## 2. Docs

- [ ] 2.1 `docs/SPEC.md` (L4-YOLO-035, SCN-YOLO-90..92, the stop reasons, the change row), `docs/runbook.md` (the stop
  table: cause and fix), `docs/yolo-mode.md`, `CHANGELOG.md` under `## 0.4.14 (unreleased)`.
