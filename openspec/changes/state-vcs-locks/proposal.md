## Why

Every later change of the L4 harness (implementer, clarifier, verifier, forge/CI) must be able to crash, be killed or
lose its runner at any moment and still resume without duplicating work, losing work or racing a second run on the
same unit. That requires one durable record of what happened (the ledger), a pure derivation of the current state
from it, an isolated git workspace per unit, git commits that carry machine-readable provenance, and a lock so two
runs never mutate one unit. SPEC section 12 (state, ledger, locks) defines all of this normatively; section 7.5 and
section 18 (L4-SEC-006) constrain how git is invoked. Nothing else in the harness can be built or run live until this
layer exists, so it is delivered as the second slice after the CLI/config skeleton.

## What Changes

- Add the per-run JSONL ledger, the pure state fold (`state.json`, `l4/state@1`) and `l4 status --rebuild`.
- Encode the section 12.0 lifecycle table as data, with a single transition function that is the only writer of
  `phase.changed`, and the resume operation (`unit.resumed`, `budget.extended`) with its refusal rules.
- Add the idempotency key and the crash reconciliation of unfinished steps (resume after crash).
- Add a hardened git runner (`core.hooksPath=/dev/null`, `core.fsmonitor=false`, `protocol.ext.allow=never`,
  `--no-verify`, never a `+` refspec), commit trailers, and WIP snapshots built from a temporary index.
- Add one worktree per unit under `$L4_CACHE/worktrees/<fw>/<name>`: created from the remote unit branch (or from
  base), reused only after verification, base brought in by merge, harness-owned-file conflict resolution, pruning.
- Add unit locks. Walking skeleton (M1): an in-process push mutex plus a local `flock` lease. Full scope (M2): the
  remote git lease on `refs/l4/locks/<fw>/<name>`, atomic fenced pushes, rejection classification, heartbeat,
  takeover, branch-lock fallback, degraded no-atomic mode, human-push race handling (L4-RACE-001).
- Add the doctor checks owned by this layer: GIT-001, GIT-002, GIT-003, STATE-001, STATE-002, FORGE-005, FORGE-006.

## Capabilities

### New Capabilities

- `run-state`: ledger events and files, state fold and rebuild, lifecycle transitions, idempotency and crash
  reconciliation, pending ledger during review, resume with budget extensions.
- `unit-locks`: unit lease (local flock in M1, remote git lease in M2), in-process push mutex, fenced atomic pushes,
  rejection classification, lock fallbacks, concurrent human push handling.
- `worktrees`: git runner hardening, commit trailers, worktree per unit, base merge and conflict resolution, WIP
  snapshots, git config guard.

### Modified Capabilities

None.

## Impact

Owned source paths (SPEC section 4.2 names, implementation-map layout):

- `src/l4/state/ledger.py`, `src/l4/state/fold.py`, `src/l4/state/lifecycle.py`
- additional modules in the same package: `src/l4/state/idempotency.py`, `src/l4/state/reconcile.py`,
  `src/l4/state/resume.py`, `src/l4/state/status.py`, `src/l4/state/pending.py`
- `src/l4/vcs/git.py`, `src/l4/vcs/worktree.py`, `src/l4/vcs/trailers.py`, `src/l4/vcs/locks.py`
- additional modules: `src/l4/vcs/names.py`, `src/l4/vcs/merge.py`, `src/l4/vcs/wip.py`, `src/l4/vcs/push.py`
- `src/l4/doctor/checks_git.py`, `src/l4/doctor/checks_state.py` (registered through the bootstrap-core doctor
  registry)
- tests: `tests/unit/state/`, `tests/unit/vcs/`, `tests/integration/test_state_vcs_flow.py`

Depends on `bootstrap-core` (config models, redaction filter, exit codes, doctor registry, `l4 status` delegation)
and, for `tasks.md`/`questions.md` merge resolution only, on `spec-providers` (byte-safe marker writer, questions
model). Consumed by `implementer-tdd-loop` (orchestrator, steps, WIP loop), `simulation-harness`, `verifier`,
`forge-and-ci` and `clarification-loop`.
