# Vite's config temp folder is writable in a test gate

## Why

A consumer repository's first unit after its admin UI moved to Vitest 5.0.5 (Vite 6.4) halted at the baseline:
`baseline_failed`, `report missing: .l4-out/junit-admin-ui.xml`. The gate's excerpt in the ledger was
`Error: ENOENT: no such file or directory, mkdir '<worktree>/apps/admin-ui/node_modules/.vite-temp'`. Vite bundles a
TypeScript config file into `node_modules/.vite-temp/` before it loads it, and tolerates only `EACCES` there.
L4-SEC-035 binds every `node_modules` read-only in a gate that does not build the environment and gives only
`node_modules/.cache` and `node_modules/.vite` an empty tmpfs, so Vitest cannot load its config and writes no report.

Reproduced in `node:22.23.3` with the same suite [V]: `node_modules` read-only with tmpfs over `.cache` and `.vite`
gives `failed to load config … ENOENT: … mkdir '…/node_modules/.vite-temp'`; with a tmpfs over `.vite-temp` as well,
60 test files and 731 tests pass and the junit report is written. Without the read-only bind the suite passes too.

## What Changes

- `node_modules/.vite-temp` joins `node_modules/.cache` and `node_modules/.vite` as a tool cache of L4-SEC-035: the
  harness empties it before every gate that does not build the environment (it makes it when it is missing), bwrap
  puts a tmpfs over it after the read-only bind of `node_modules`, and the environment manifest of L4-SEC-036 leaves it
  out, as it leaves out the other two.
- `docs/SPEC.md`: L4-SEC-035 and SCN-SEC-87 name `.vite-temp`; a new scenario (the next free SCN-SEC id) covers a test gate that
  loads a Vite config; CHANGELOG 0.4.29 under Fixed; the change table gains a row.

## Impact

- Code: `l4.sandbox.envdirs.TOOL_CACHE_DIRS` (one more name). `l4.implementer.envguard` and the bwrap argv already use
  it, so they follow.
- Security: unchanged in kind. Like `.vite`, `.vite-temp` is empty at the start of every gate and discarded after it
  (a tmpfs under bwrap, emptied by the harness in every mode), so nothing a gate writes there reaches a later gate.
- Out of scope: any other path a tool writes inside `node_modules`; L4-SEC-035 still says such a tool belongs in
  `gates.setup`.
