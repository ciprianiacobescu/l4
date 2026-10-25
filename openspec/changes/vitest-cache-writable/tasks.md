## 1. Vitest's module cache is a tool cache (L4-SEC-035)

- [x] 1.1 Tests first, in three files:
  - `tests/unit/sandbox/test_env_dirs.py`: the reset and `read_only_mounts` include `.vitest-cache`. A missing one is
    made, one holding a file is emptied, a symlink is unlinked without following it, and its target is untouched.
    SCN-SEC-87's test also asserts the tmpfs over it comes after the read-only bind and before the guidance masks.
  - `tests/unit/implementer/test_envguard.py`: the manifest leaves `node_modules/.vitest-cache` out. A file a gate
    writes there is no change, with no `guard.violation` and no `env.rebuilt`. A file an agent step writes there
    (written straight into the worktree between `run_setup` and `check_env(..., phase="red")`) is no change either.
  - `tests/unit/runner/test_probe_m15_parity.py`: the bwrap argv has `--tmpfs <wt>/node_modules/.vitest-cache` after
    the read-only bind of `node_modules`, and the probe script's argv still equals the harness's.

  Then add `".vitest-cache"` to `TOOL_CACHE_DIRS` in `src/l4/sandbox/envdirs.py` and update the comment and
  docstrings there that name the caches (Vitest 5 keeps transformed modules there, `fsModuleCache` is on by default,
  and nothing catches the `mkdir` error).
  Result: the new assertions failed before the change (SCN-SEC-87's argv test, the new reset test, both envguard
  tests, the probe parity test); `".vitest-cache"` added to `TOOL_CACHE_DIRS`, the three test files pass.
- [x] 1.2 Docs:
  - `docs/SPEC.md`: L4-SEC-035 names `node_modules/.vitest-cache` with its reason (Vitest 5's module cache, on by
    default, read back in later runs) [V, Vitest 5.0.5: one file per run fails at file level with `mkdir`
    `.vitest-cache` under a read-only node_modules]. SCN-SEC-87's Then names it. Add a new scenario
    "SCN-SEC-105 (+) A test gate writes Vitest's module cache · L4-SEC-035" after SCN-SEC-104, and a change-table row
    74 (`vitest-cache-writable`) after row 73.
  - `CHANGELOG.md`: `## 0.4.31 (unreleased)` above 0.4.30, with a `### Fixed` line. The line says the test gate no
    longer fails one Vitest file per run, and the agent steps no longer report the cache as `guard.violation` and
    rebuild `node_modules`.

  Run `scripts/check_spec.py docs/SPEC.md` and the docs tests.
  Result: L4-SEC-035 and SCN-SEC-87 name `.vitest-cache`, SCN-SEC-105 added after SCN-SEC-104, change-table row 74,
  CHANGELOG 0.4.31 Fixed; `check_spec.py` and the docs tests pass.
