## 1. Vite's config temp folder is a tool cache (L4-SEC-035)

- [x] 1.1 Tests first: `tests/unit/sandbox/test_env_dirs.py` (reset and `read_only_mounts` include `.vite-temp`: made
  when missing, emptied, a symlink unlinked), `tests/unit/implementer/test_envguard.py` (the manifest leaves
  `node_modules/.vite-temp` out, so a file written there by a gate is no change), and
  `tests/unit/runner/test_probe_m15_parity.py` (the bwrap argv has `--tmpfs <wt>/node_modules/.vite-temp` after the
  read-only bind, and the probe script's argv still equals the harness's). Then add `".vite-temp"` to
  `TOOL_CACHE_DIRS` in `src/l4/sandbox/envdirs.py` and update the docstrings there that name the caches.
  Result: the new assertions failed for the missing `.vite-temp`; `".vite-temp"` added to `TOOL_CACHE_DIRS`, the three test files pass.
- [x] 1.2 `docs/SPEC.md`: L4-SEC-035 names `node_modules/.vite-temp` with its reason (Vite bundles the config there
  and tolerates only `EACCES`), SCN-SEC-87's Then names it, a new scenario "(+) A test gate loads a Vite configuration ·
  L4-SEC-035" with the next free SCN-SEC id, and a change-table row 70 (`vite-temp-writable`). `CHANGELOG.md`:
  `## 0.4.29 (unreleased)` with a `### Fixed` line. Run `scripts/check_spec.py docs/SPEC.md` and the docs tests.
  Result: L4-SEC-035 and SCN-SEC-87 name `.vite-temp`, SCN-SEC-104 added, change-table row 70, CHANGELOG 0.4.29 Fixed.
