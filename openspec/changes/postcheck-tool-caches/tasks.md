## 1. Every gate runner empties the tool caches (L4-SEC-035)

- [ ] 1.1 Tests first, in two files:
  - `tests/unit/yolo/test_yolo_postcheck_profile.py`: a profile whose setup gate creates `node_modules/pkg/index.js`,
    `node_modules/.vite/stale` and a symlink `node_modules/.vitest-cache` pointing at a folder outside the worktree
    (holding a file), and whose next gate (lint) is a shell command that exits 0 only when each of
    `node_modules/.cache`, `.vite`, `.vite-temp` and `.vitest-cache` is a real directory (not a symlink) with no
    entries. The profile passes and the symlink's target folder still holds its file. A second test: the revision
    tracks `vendor/node_modules/lib.js`, the setup gate writes `vendor/node_modules/.cache/keep`, and the next gate
    exits 0 only when that file is still there.
  - `tests/unit/gates/test_dryrun.py`: the same two cases through the dry run's gate loop (read the file's existing
    tests for how they configure the gates and the sandbox).

  Then:
  - move `Workbench._tracked_env`'s body to `l4.sandbox.envdirs.tracked_env_paths(git) -> frozenset[str]` (same
    `git ls-files -z -- .venv node_modules ':(glob)**/node_modules/**'`, `check=False`); `_tracked_env` returns it;
  - in `l4.yolo.postcheck._run` and in the gate loop of `l4.gates.dryrun`: compute `tracked =
    tracked_env_paths(git.at(tree))` once (the dry run has a `Git` of the repository; use the worktree's), and for
    every gate that is not setup call `reset_tool_caches(tree, tracked)` BEFORE `gate_sandbox_spec(...)`; pass
    `tracked=() if builds_env else tracked` to `gate_sandbox_spec`. The reset must come before the spec is built,
    because `read_only_mounts` lists a tmpfs only for a cache folder that exists.
  - the module docstrings of `postcheck` and `dryrun` say they empty the tool caches before each gate (L4-SEC-035).

  The new tests must fail before the change and pass after. Run `tests/unit/yolo`, `tests/unit/gates`,
  `tests/unit/sandbox` and `tests/unit/implementer/test_envguard.py`.
- [ ] 1.2 Docs:
  - `docs/SPEC.md`: in L4-SEC-035, after "the harness empties them before each gate in every mode", name the runners:
    the workbench's gates, the post-merge check of L4-YOLO-009 and the gate dry run, each before it builds the gate's
    sandbox. Add "SCN-SEC-106 (+) The post-merge check empties the tool caches after a fresh install · L4-SEC-035,
    L4-YOLO-009" after SCN-SEC-105 (Given a profile whose setup gate creates `node_modules` with a stale `.vite` entry
    and a symlink at `.vitest-cache`; When the next gate runs; Then the four tool caches are real empty directories,
    the symlink's target is untouched and the profile passes), and a change-table row 75 (`postcheck-tool-caches`)
    after row 74.
  - `CHANGELOG.md`: `## 0.4.32 (unreleased)` above 0.4.31 with a `### Fixed` line: the post-merge check of a
    delivery plan and the gate dry run of `l4 yolo check` empty the tool caches before each gate, so a Vite 5 /
    Vitest 5 project's test gate loads its config and writes its report there too (a plan had stopped
    `postcheck_failed` with `report missing`).

  Run `scripts/check_spec.py docs/SPEC.md` and the docs tests.
