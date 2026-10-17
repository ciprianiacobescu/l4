## Why

A consumer repository with three uv projects runs its test gate as three pytest runs and lists three junit reports in
`gates.test.reports`. The harness read only the first report that existed (`runner.py`: `found = next(...)`), so
`l4 doctor` showed `test: pass (436/483 passed)`: the 60 tests of the second project and the 363 of the third were
invisible to red, green, traceability and the verifier. A unit that touched those projects could never prove a test.
The adoption docs also still said that a public repository needs a copy of the action and a deploy key; with the
published harness public, the plain action form works for any repository.

## What Changes

- **Every listed report is read** (L4-GAT-005). Each report in `gates.test.reports` must exist after the run, or the
  gate fails `report missing: <that report>`. The reports are merged into one: a test id that two reports hold keeps the
  worse result (error, failed, passed, skipped); the collection errors of all are kept. A single report reads as before.
- **The adoption docs and the init note name the public harness first**: the plain `--action` form needs no key; the
  adopting repository must allow actions from other repositories. The copy form and the deploy key stay for a private
  harness.

## Impact

- `src/l4/gates/junit.py` (`merge_reports`), `src/l4/gates/runner.py`, `src/l4/init/init.py` (the note).
- `docs/SPEC.md` (L4-GAT-005, SCN-GAT-05..07, the change row), `docs/quickstart.md`,
  `plugins/l4/skills/l4/references/adopt.md`, `CHANGELOG.md`.
