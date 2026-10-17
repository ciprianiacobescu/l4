## 1. Gates (L4-GAT-005)

- [x] 1.1 Tests: `tests/unit/gates/test_runner_reports.py` (SCN-GAT-05, SCN-GAT-06, SCN-GAT-07).
- [x] 1.2 `junit.merge_reports`; `runner.run_gate` requires every listed report and merges them.

## 2. Doctor (L4-ADO-006)

- [x] 2.1 `repo_jobs._gate_commands` counts build and typecheck always; `normalise` drops `uv run` options
  (`tests/unit/ci/test_repo_jobs.py`, SCN-ADO-55).

## 3. Docs

- [x] 3.1 `docs/quickstart.md`, the skill's `adopt.md` and the `l4 init` note name the public harness first.
- [x] 3.2 `docs/SPEC.md` (L4-GAT-005, SCN-GAT-05..07, L4-ADO-006, SCN-ADO-55, the change row), `CHANGELOG.md`.
