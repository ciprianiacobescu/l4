# Vitest's module cache is a tool cache in a test gate

## Why

A consumer repository's unit could not pass a red step: four attempts on two implementers were all rejected with
`new tests passed before implementation`, naming 30 tests of `apps/admin-ui/tests/test_auth_scheme.test.ts`, a file the
task never touched. The unit then raised a question. The cause is in the gate, not in the agents. In every test gate
of that run exactly one Vitest file failed as a whole, and a different file each time: the baseline lost
`test_auth_scheme.test.ts` (its 30 tests became one failing file-level entry, 2638 = 2667 - 30 + 1). Red attempt 1 lost
`test_budget_bff.test.ts` and attempt 2 lost `test_agent_secret_grants.test.ts`. The 30 tests the baseline did not
have were counted as new, and they passed.

Vitest 5 turns on its file-system module cache by default (`fsModuleCache: true`, stored at
`node_modules/.vitest-cache` at the workspace root). It creates that folder with `mkdirSync` the first time it needs a
cache path for a module, and nothing catches the error. Under a read-only `node_modules`, the test file whose module
reaches it first fails at file level. The other files go on, because the cache root is recorded before the `mkdir`
(observed: exactly one failing file in each of six CI gate runs and in each local run).
L4-SEC-035 binds every `node_modules` read-only in a gate that does not build the environment and gives only `.cache`,
`.vite` and `.vite-temp` an empty tmpfs.

Reproduced with the same suite (Vitest 5.0.5, Vite 6.4, 731 tests) [V]: with `node_modules` writable, three runs pass
731 of 731. With `node_modules` made unwritable (`chmod u-w`, no `.vitest-cache`), two runs each fail exactly one file
at file level, a different file each time, with `EACCES: permission denied, mkdir '…/node_modules/.vitest-cache'`.
Under bwrap's read-only bind the same `mkdirSync` fails with `EROFS` instead [I: same code path; the CI gate logs are
not uploaded]. The run also shows the second effect. The agent sandboxes keep `node_modules` writable, so an agent that
runs Vitest writes about 97 cache files there. The environment check after the step then reports each one as a
`guard.violation` (rule `environment`), removes it and rebuilds `node_modules` (`env.rebuilt`, `reason: changed`).

## What Changes

- `node_modules/.vitest-cache` joins `.cache`, `.vite` and `.vite-temp` as a tool cache of L4-SEC-035. The harness
  empties it before every gate that does not build the environment (and makes it when it is missing), bwrap puts a
  tmpfs over it after the read-only bind of `node_modules`, and the environment manifest of L4-SEC-036 leaves it out, as
  it leaves out the other three.
- `docs/SPEC.md`: L4-SEC-035 and SCN-SEC-87 name `.vitest-cache`. A new scenario, SCN-SEC-105, covers a test gate that
  writes Vitest's module cache, and the change table gains row 74. CHANGELOG gets a 0.4.31 entry under Fixed.

## Impact

- Code: one more name in `l4.sandbox.envdirs.TOOL_CACHE_DIRS`. `l4.implementer.envguard`, `reset_tool_caches` and the
  bwrap argv already read the tuple, so they follow.
- Security: the same kind as before, and the reset matters more here than for `.vite-temp`. Vitest reads transformed
  code back from `.vitest-cache`. A file planted there, by an agent step (writable `node_modules`) or by an earlier
  gate, could replace a module's code in a later gate. The folder is therefore emptied before every gate in every
  sandbox mode and covered by a tmpfs under bwrap, as `.vite/deps` is, so nothing written there reaches a later gate.
  The cache gives no speed-up across gates. That is no loss, because today it is never written at all.
- Out of scope:
  - a project that sets `fsModuleCachePath` outside `node_modules` (that path is in the worktree, which a test gate can
    already write);
  - recognising a Vitest file-level failure as a collection error in `parse_junit`, so that the baseline would have
    named the file at once. That is a separate change, because it moves the red and discrimination verdicts of every
    TypeScript unit.
