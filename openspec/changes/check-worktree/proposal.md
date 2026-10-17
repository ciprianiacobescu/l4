## Why

A person writing a delivery plan on a feature branch must validate it before the pull request into the target, and the
docs sent them to `python3 <skill dir>/scripts/validate_plan.py`: a path inside a clone of the harness, which a
`uv tool install` does not give them. `l4 yolo check <plan>` exists, but it reads the plan file and the units from the
target branch, so it exits 2 for a plan that is not pushed yet. `l4 yolo review --worktree` and `l4 yolo findings
--worktree` already work on the working tree; `check` does not, and the worktree review even tells a refused plan to "run
l4 yolo check", which cannot help before the push. The owner: "there should be a l4 command that is available directly
from the uv install".

## What Changes

- **`l4 yolo check <plan> --worktree`** (L4-YOLO-034): reads the plan files and the units from the working tree, as
  `review --worktree` does, and runs the same admission as `l4 yolo check` (schema, ids, dependencies and cycles, intake
  of each unit, open questions, profiles, the target and the merge policy), plus the checks across all plan files that
  only the standalone validator ran so far: `uncovered` (a unit no plan lists, planned or excluded, except a derived unit
  whose parent is listed) and `covered_twice`. It prints the findings, then the order and the budget warnings. It writes
  nothing and needs no push. Exit 0 admitted, 2 with findings.
- The hints point to it: `l4 yolo draft`'s "Next:" lines, the worktree review's "not admitted" line.
- The docs lead with it (the skill's `plan.md`, `docs/yolo-mode.md`, the runbook §12); `validate_plan.py` stays for an
  agent or a CI step without the harness, and the two must agree (a parity test).

## Impact

- `src/l4/yolo/commands.py` (`run_check(..., worktree=True)`), `src/l4/yolo/plans.py` or a new module for the coverage
  checks, `src/l4/cli.py` (the flag), the hint texts, tests under `tests/unit/yolo/`.
- `docs/SPEC.md` (L4-YOLO-034, scenarios, the command table, the change row), the skill's `plan.md`, `docs/yolo-mode.md`,
  `docs/runbook.md`, `CHANGELOG.md`.
