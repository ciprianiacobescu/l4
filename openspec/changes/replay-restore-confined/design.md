## Context

Read with `proposal.md`. `ReplayGuard` (`src/l4/implementer/held_patch.py:527`) is armed when a held step is replayed.
After every gate run, `restore(where)` lists the paths that differ from the step base (`_paths`: `{path: existed at the
base}`) and the paths of the saved patch (`expected`), checks every parent folder for links (`check_parents`), then calls
`_restore_one(path, existed, restored)` for each. The fd-relative helpers are in `src/l4/implementer/confined.py`:
`remove_entry`, `put_entry(root, rel, expected)` (`expected` is an `Entry`: `("link", target, ...)` or `("blob", data,
mode)`), `put_blob(root, rel, write, executable)` and `check_parents`. `self._git(...)` checks that the work tree folder
is still the one the guard opened, then runs git in it by name.

## Decisions

### D1 The base entry is written through the folder's descriptor

In `_restore_one`, the branch for a path that is not in `expected` keeps its first steps (nothing to do when it neither
existed at the base nor exists now; `remove_entry` of what is there). When `existed` is true, instead of
`git checkout <base> -- :(literal)<path>`:

```python
def _base_entry(self, path: str) -> tuple[str, str] | None: ...   # (mode, blob id) of `path` at self.base, None: absent
```

reads `git ls-tree -z <base> -- :(literal)<path>` (one record: `<mode> <type> <blob>\t<path>`; nothing: None), then:
- mode `100644` or `100755`: `put_blob(self.root_fd, path, lambda out: wb.git.stream_blob(blob, out), mode ==
  "100755")`;
- mode `120000`: the target is the blob's content (`git cat-file blob <blob>`, decoded with `os.fsdecode`), and
  `put_entry(self.root_fd, path, ("link", target, 0))` writes the link;
- any other mode (`160000`, a submodule), or None: raise `_NotRestorable(path, kind)`; `restore` turns it into
  `self._put_back_failed(where, ...)` with the text of the proposal (`<kind>`: `submodule` for 160000; None ends
  with `<path> has no entry at the base`).
Then `self._git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")`. The branch for a path that did not
exist at the base is unchanged (`git rm --quiet --cached --ignore-unmatch`, an index-only command).

### D2 The restore runs no path-based git write

After the change, the only git commands `ReplayGuard.restore` runs are reads (`diff`, `ls-files`, `ls-tree`, `cat-file`)
and index-only writes (`rm --cached`, `update-index --cacheinfo`). A test pins this by recording the argv of every
`self._git` and `wb.git.run` call during a restore of a base path and asserting that none is `checkout`, `restore`,
`reset --hard`, `stash` or `clean`.

### D3 What is not changed

Other path-based restores of the harness (`guards.py` freeze restore, `security/protected.py` revert, `stubs.py`,
`workbench.discard_changes`) run after an agent step, when the sandbox has ended the agent's processes. They are named
here as a follow-up; this change touches only the replay guard, whose contract (L4-IMP-065) already says it never
follows a link.

## Contracts (texts, exact)

- Failure text: `the replayed step could not be put back to its saved patch (<where>): <path> is a <kind> at the base`.
  `<kind>` is `submodule` (mode 160000) or `entry of mode <mode>`; a path the base has no entry for ends with `<path> has
  no entry at the base`.

## Risks / Trade-offs

- `update-index --cacheinfo` leaves the entry without stat data, so the next `git status` hashes that file again: one
  read of a file the harness just wrote; no behaviour change.
- The racing test is probabilistic. Acceptance is that it passes 30 runs in a row in a Linux container and the eight
  Linux CI shards pass on a dispatched run.
