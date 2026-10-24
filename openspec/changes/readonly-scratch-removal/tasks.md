# Tasks: readonly-scratch-removal

## 1. A step's private trees are removed even when Go made them read-only (L4-SEC-039)

- [ ] 1.1 Tests first, new file `tests/unit/sandbox/test_remove_tree.py`: a helper builds Go's layout (a directory
  `github.com/x/y@v1.0.0` with mode 0o555 holding `go.mod` with mode 0o444) under a temporary directory. Cover:
  `remove_tree` removes that tree; a missing path is no error; a symlink at the path is unlinked and its target kept;
  a symlink inside the tree to a 0o444 file outside it is removed while the outside file keeps mode 0o444 and its
  content; `readonly_with_scratch(caches, tmp, create=True)` called twice over a scratch that holds Go's layout gives an
  empty scratch directory both times (today the second call raises `FileExistsError`); `verifier_caches` called twice
  over a writable cache that holds Go's layout gives an empty directory both times. Make the trees writable in the
  tests' teardown so a failure leaves nothing pytest cannot remove. Then add `remove_tree(path: Path) -> None` to
  `src/l4/sandbox/base.py` with the unlock-and-retry handler of `src/l4/implementer/resultalias.py`
  (`_unlock_and_retry`, moved here; `resultalias.drop` calls `remove_tree`), and use it in `readonly_with_scratch` and
  in `verifier_caches` (`src/l4/sandbox/caches.py`) instead of `shutil.rmtree(..., ignore_errors=True)`.
- [ ] 1.2 Tests first, in the existing workbench tests (find them with `grep -rln reset_agent_tmp tests/unit`):
  `Workbench.reset_agent_tmp` called twice, with Go's layout written under `agent_tmp/scratch-cache/GOMODCACHE` after
  the first call, returns an empty private temp directory with fresh scratch caches (today: `FileExistsError`);
  `discard_scratch` removes Go's layout; when the end-of-step removal fails (patch `remove_tree` to raise
  `PermissionError`), `discard_scratch` logs a warning naming the path and does not raise. Then in
  `src/l4/implementer/workbench.py` use `remove_tree` in `reset_agent_tmp` (loud), `discard_scratch` and the removal of
  `gate-tmp/scratch-cache` after a gate (both: catch `OSError`, `log.warning("could not remove %s: %s", path, exc)`).
- [ ] 1.3 `docs/SPEC.md`: in L4-SEC-039, after "removed at the end", say that removing a scratch cache first makes its
  read-only directories writable (Go extracts modules read-only), never through a symlink, so the next step's scratch is
  empty; a failure at the start of a step stops the run naming the path, one at the end is a warning. Add the scenario
  "#### SCN-PRV-141 (+) A scratch cache that Go made read-only is empty for the next step · L4-SEC-039" (Given an agent
  step that filled its scratch `GOMODCACHE` with read-only module directories, When the next agent step of the run
  starts, Then its scratch `GOMODCACHE` is an empty directory and the run goes on) and a change-table row 71
  (`readonly-scratch-removal`). `CHANGELOG.md`: a `## 0.4.30 (unreleased)` section with a `### Fixed` line. Run
  `uv run python scripts/check_spec.py docs/SPEC.md` and the docs tests.
