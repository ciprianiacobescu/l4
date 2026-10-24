# Tasks: readonly-scratch-removal

## 1. A step's private trees are removed even when Go made them read-only (L4-SEC-039)
- [x] 1.1 Tests first, new file `tests/unit/sandbox/test_remove_tree.py`: a helper builds Go's layout (a directory
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
  Result: `tests/unit/sandbox/test_remove_tree.py` (8 tests) failed on a plain `rmtree(ignore_errors=True)`: the Go layout stayed (`assert not scratch.exists()`) and the second `readonly_with_scratch` and `verifier_caches` raised `FileExistsError`; `remove_tree` and its unlock-and-retry handler (moved from `resultalias`, limited to the tree being removed and never through a symlink) added to `src/l4/sandbox/base.py`, used by `readonly_with_scratch`, `verifier_caches` and `resultalias.drop`; the file passes.
- [x] 1.2 Tests first, in the existing workbench tests (find them with `grep -rln reset_agent_tmp tests/unit`):
  `Workbench.reset_agent_tmp` called twice, with Go's layout written under `agent_tmp/scratch-cache/GOMODCACHE` after
  the first call, returns an empty private temp directory with fresh scratch caches (today: `FileExistsError`);
  `discard_scratch` removes Go's layout; when the end-of-step removal fails (patch `remove_tree` to raise
  `PermissionError`), `discard_scratch` logs a warning naming the path and does not raise. Then in
  `src/l4/implementer/workbench.py` use `remove_tree` in `reset_agent_tmp` (loud), `discard_scratch` and the removal of
  `gate-tmp/scratch-cache` after a gate (both: catch `OSError`, `log.warning("could not remove %s: %s", path, exc)`).
  Result: the new tests in `tests/unit/implementer/test_cache_scratch.py` failed (Go's trees stayed in the reset agent temp directory and the discarded scratch, and `workbench.remove_tree` did not exist for the failure cases); `reset_agent_tmp` uses `remove_tree` and raises, `discard_scratch` and the gate's scratch removal use `discard_tree` (a warning `could not remove <path>: <error>`); the file passes.
- [x] 1.3 `docs/SPEC.md`: in L4-SEC-039, after "removed at the end", say that removing a scratch cache first makes its
  read-only directories writable (Go extracts modules read-only), never through a symlink, so the next step's scratch is
  empty; a failure at the start of a step stops the run naming the path, one at the end is a warning. Add the scenario
  "#### SCN-PRV-141 (+) A scratch cache that Go made read-only is empty for the next step · L4-SEC-039" (Given an agent
  step that filled its scratch `GOMODCACHE` with read-only module directories, When the next agent step of the run
  starts, Then its scratch `GOMODCACHE` is an empty directory and the run goes on) and a change-table row 71
  (`readonly-scratch-removal`). `CHANGELOG.md`: a `## 0.4.30 (unreleased)` section with a `### Fixed` line. Run
  `uv run python scripts/check_spec.py docs/SPEC.md` and the docs tests.
  Result: L4-SEC-039 says what the removal does, SCN-PRV-141 added (after SCN-PRV-112), change-table row 71, CHANGELOG 0.4.30 Fixed; `scripts/check_spec.py docs/SPEC.md` exits 0 and `tests/unit/docs` passes (`test_escalate_and_note_docs` now looks for `## 0.4.3 (` because `## 0.4.3` also matches the `## 0.4.30` heading).
- [x] 1.4 Review follow-up, tests first in `tests/unit/sandbox/test_remove_tree.py`: a directory with mode 0o000 and
  one with 0o300 under the removed tree, a root with mode 0o000, and the removal with Python 3.11's `rmtree` (no
  `onexc`, the handler as `onerror`). Then `remove_tree` removes a directory it could not open or list as a whole once
  it is readable, takes a vanished entry as removed, raises on a second failure of the same entry, and passes the
  handler as `onerror` below Python 3.12. L4-SEC-039, SCN-PRV-142 and the CHANGELOG say so.
  Result: the three tests failed (`TypeError: open() missing required argument 'flags'` from the retried `os.open`, and
  no 3.11 path); the file passes, and the removal also passes under a real Python 3.11.15 with warnings as errors.
