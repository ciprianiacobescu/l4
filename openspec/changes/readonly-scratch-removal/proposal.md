# A scratch cache that Go made read-only is removed

## Why

A consumer repository's unit crashed three runs in a row after an agent step, each time at the start of the next
agent step of the same run: `internal error: FileExistsError: [Errno 17] File exists:
'<cache>/units/<unit>/agent-tmp/scratch-cache/GOMODCACHE'`. L4-SEC-039 gives every agent step a private scratch cache
(`GOMODCACHE` among them) that is empty at the start of the step and removed at the end. Go extracts every module it
downloads into `GOMODCACHE` with read-only directories (0o555) and files, so `shutil.rmtree(..., ignore_errors=True)`
cannot empty it and says nothing; `readonly_with_scratch` then calls `scratch.mkdir(mode=0o700, parents=True)` on a
directory that still exists. Reproduced locally [V]: a 0o555 directory holding a 0o444 file survives
`rmtree(ignore_errors=True)`, and the `mkdir` raises `FileExistsError`. The repository's `gates.setup` has no
`go mod download` (doctor SANDBOX-005 warns), so the shared module cache was empty and the agent's Go commands filled
the scratch. A run could therefore complete only one agent step that touched Go before it stopped with exit 1, and the
plan used up its run limit.

## What Changes

- One removal helper, `l4.sandbox.base.remove_tree`, for the trees an agent or a gate can write: it removes a
  directory tree, and on a `PermissionError` it makes the directory that holds the failed entry, and the entry, writable
  (never through a symlink) and tries once more, as `resultalias._unlock_and_retry` already does for the result alias.
  A missing path is no error; a symlink or a file at the path is unlinked without following it.
- The places that empty a step's private trees use it: `readonly_with_scratch` (the scratch caches it makes),
  `Workbench.reset_agent_tmp`, `Workbench.discard_scratch`, the removal of a gate's scratch caches after the gate,
  `verifier_caches` (a verification round's own caches) and `resultalias.drop`.
- The start of a step (the reset of the agent's temp directory, the scratch caches, the verifier's caches) raises when
  the tree still cannot be removed; the removal at the end of a step and of a gate logs a warning and goes on, because
  the next start removes it again and says so.
- `docs/SPEC.md`: L4-SEC-039 says that removing a scratch cache first makes its read-only directories writable; a new
  scenario (the next free SCN-PRV id); a change-table row; CHANGELOG 0.4.30 under Fixed.

## Impact

- Code: `src/l4/sandbox/base.py`, `src/l4/sandbox/caches.py`, `src/l4/implementer/workbench.py`,
  `src/l4/implementer/resultalias.py`.
- Security: unchanged in kind and stronger in effect: the scratch is really empty at the start of every step, as
  L4-SEC-039 requires, instead of keeping the previous step's modules when the removal failed. The helper changes modes
  only inside the tree it removes and never follows a symlink, so an agent cannot make it change a file outside.
- Out of scope: the shared per-unit caches, which only `gates.setup` writes; `GOMODCACHE` in a gate stays read where it
  is (L4-SEC-039's exception).
