# Design: baseline-reuse

## Context (verified on amaster f592bc7d, read-only analysis of 2026-10-29)

- `baseline()` (tdd.py) runs `run_setup` and the gate `baseline` inside `at_clean_head`, caching the report in
  `wb.baselines[base_sha]`; callers: `run_red` (base = `wb.head()`) and `run_single`; `resume_red` runs its own.
- The report serves red (new-test detection, stale tests, unchanged criteria, notes), green's regression check, and
  the verifier (`wb.baselines.get(base_sha)`).
- The next task's base is the green commit, made after the gate: `set_marker DONE`, `tick_completed_parents` edit
  tasks.md and `task.done` goes to the tracked ledger; a `_close_parents` commit may follow. Different sha and tree.
- The green gate uses the same `GateSpec`, sandbox and cache resets as the baseline, except fix units, whose green gate
  runs with the coverage plugin (`fix_gate_env`).
- A gate can change tracked files while it runs (a test that writes a file, a fixing linter in the static gates); so
  the tested tree must be taken from the worktree before the gate, never from the commit.

## D1 Record

At the green gate (tdd.py `run_green`, and the single step's gate in `run_single`): before the gate, compute the tree of
the worktree with a temporary index (read HEAD, `add -A` honouring `exclude_config`, `write-tree`, as `snapshot_wip`
does) and the gate digest (sha256 of command, reports, format, `gates.timeout`, the per-test timeout, network, sandbox
mode). After the green is accepted and committed, keep `wb.last_tested = (tree, digest, report, sha)` only when
`extra_env` is None, no `guard.violation` and no `env.rebuilt` was recorded during the gate.

## D2 Reuse

In `baseline()`, after a sha miss: when `wb.last_tested` is set, its digest equals the current one, and
`git diff --name-only <tree> HEAD^{tree}` lists only the unit's ledger file, its `tasks.md` and paths under its
`.l4/held/`, set `wb.baselines[base_sha] = report`, record `gate.reused{name: "baseline", from: "test", task,
source_sha, tree}`, and return it without setup or gate.

## D3 Invalidate

Set `wb.last_tested = None` before any agent step (where `setup_at` is reset), on `discard_changes`, when a workbench
is rebuilt (do not carry it), and naturally at a new job. Only the unit worktree's `run_gate` records.

## D4 Not changed

The step keys (L4-STA-003) keep the base sha; a job's first baseline is measured; `resume_red`; `static_baseline`
(a later change could reuse the static gates the same way); the setup cache.

## Residual risk (named, accepted)

The recorded tree is what git sees: it leaves out ignored and excluded files and git-derived state. A later lint or
typecheck that rewrites ignored outputs (a compiler's `outDir`) is not part of it, and the green gate ran with `HEAD` at
the red commit and a dirty tree, so a version derived from git (setuptools-scm, hatch-vcs, `git describe`) differs from
the one the next base has. A test whose outcome depends on either could see a different result at the next base than the
reused report says. The first baseline of every job is measured, and the verifier measures its own base.
