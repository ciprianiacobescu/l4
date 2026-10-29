# A task's baseline reuses the green gate run of the same tree

## Why

Each task measures a baseline with the full test gate before its red step. In a consumer's unit of 9 tasks the gate
takes about 65 s, and every baseline after the first ran right after the previous task's green gate had run the full
suite on the same code [V, 2026-10-29]: about 8 to 9 minutes per unit for runs that cannot differ. The cache of
baselines is keyed by commit, and the next task's base is the green commit, which the harness makes after the gate
(with the task's tick in tasks.md and the ledger lines), so it never hits.

## What changes

- Before the green gate the harness records the tree the gate tests (the worktree as a tree, via a temporary index,
  without the excluded config) and a digest of the gate (command, reports, format, timeouts, network, sandbox mode).
- After an accepted green with no extra environment (not a fix unit's coverage run), no guard restore and no
  environment rebuild during the gate, the run keeps that tree, digest and report.
- A later `baseline()` of the same run whose commit misses the cache reuses the kept report when the digest is the
  same and `HEAD`'s tree differs from the kept tree only in the unit's ledger, its `tasks.md` and its held files:
  it records `gate.reused{name: baseline, from: test, task, source_sha, tree}` and runs neither setup nor the gate.
- The keep is in memory, dropped by any agent step, a discard, a rebuilt workbench and a new job; the first baseline
  of a job is always measured. `resume_red` is unchanged.

## Impact

- Code: `l4.implementer.tdd` (`baseline`, `run_green`, `run_single`), `l4.implementer.workbench` (the slot, the tree
  of the worktree).
- Spec: L4-IMP-088 added; L4-IMP-002 amended (a base report may be a reused measurement); `gate.reused` in the event
  list; SCN-IMP-432 to SCN-IMP-437; change-table row 93.
- About 65 s saved per task after a job's first.
