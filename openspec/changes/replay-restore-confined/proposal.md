## Why

The replay guard of a held step (L4-IMP-065) promises that it never follows a link: it reaches each path from the work
tree one component at a time with `O_NOFOLLOW` and acts only through that folder's file descriptor. One branch of its
restore breaks that promise. A path that is not part of the saved patch and that existed at the step base is put back
with `git checkout <base> -- <path>` (`ReplayGuard._restore_one`, `src/l4/implementer/held_patch.py:728`). Git resolves
that path by name: when a process that outlived a gate swaps a folder of the path for a link between the guard's check
and git's write, git writes the base file through the link, outside the work tree.

The security test `test_h_real_thread_racing_the_guard` (`tests/unit/implementer/test_held_guard_links.py`) shows it on
Linux: a thread flips `tests/fixtures` between a folder and a link to an outside folder while the restore runs, and the
outside folder changes in about one run in six (two of eight nightly CI runs of the harness; it passes on macOS). An
instrumented run named the operation: `git checkout <base> -- tests/fixtures/old.txt` created `old.txt` in the outside
folder.

## What Changes

- **The restore of a base path is confined like every other write of the guard** (L4-IMP-086). The base entry of the
  path (`git ls-tree -z <base> -- :(literal)<path>`) is written through the folder's file descriptor: a regular file by
  `put_blob` (the blob streamed with `git cat-file blob`, the executable bit from the mode), a link by `put_entry` (its
  target from the blob). The index entry is set with `git update-index --add --cacheinfo <mode>,<blob>,<path>`, which
  never touches the work tree. No restore of the guard runs a path-based git command that writes the work tree.
- A path whose base entry is neither a regular file nor a link (a submodule) is not put back: the step fails as an
  attempt with `the replayed step could not be put back to its saved patch (<where>): <path> is a <kind> at the base`.

## Impact

- Code: `src/l4/implementer/held_patch.py` (`ReplayGuard._restore_one`, a helper for the base entry).
- Tests: `tests/unit/implementer/test_held_guard_links.py` (the racing test is the acceptance test; a new test checks
  that the restore of a base path runs no `git checkout`), the existing replay tests.
- Spec: L4-IMP-086, SCN-IMP-411 and SCN-IMP-412, change row 66 of `docs/SPEC.md`.
- No config, no template, no event change.
