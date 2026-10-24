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

### D4 The follow-up of D3, assessed (2026-10-24, no code change)

The follow-up was examined before a 0.4.28 was built. The owner chose to record the result and change no code until a
release has other content. Labels: [V] checked, [I] inferred from checked facts.

The path-based writes in a worktree at f51c471b (v0.4.27 source): `git checkout <rev> -- <path>` in
`memory/round.py:48` (HEAD), `security/protected.py:256` `_put_back` (base, plus `unlink`/`rmtree` by name of a path
the base lacks), `state/reconcile.py:90` (HEAD), `implementer/tdd.py:2022` (red commit), `implementer/guards.py:262`
`restore_frozen` (red commit) and `:303` `restore_test_paths` (base), `implementer/stubs.py:866` `restore_to_base`;
whole-tree resets in `implementer/workbench.py:724` `_reset_to_head` (`checkout HEAD -- .` with an exclude, then
`git clean`) and `vcs/wip.py:81` (`checkout --no-overlay <wip> -- .`); and the Serena project file in
`implementer/workbench.py:842-875` (`_take_serena_project`, `_restore_project`, `settle_serena_project`).

1. **A link that is already there.** git replaces a linked folder on the path with a real folder and writes nothing
   through it [V, git 2.48.1: with `.serena -> ../outside`, `git checkout HEAD -- ':(literal).serena/project.yml'`
   left `../outside/project.yml` unchanged and made `.serena` a folder]. So the git sites never follow a link that
   exists before they run. They do not meet the letter of L4-SEC-020: git tests the path by name (`lstat`), not
   through descriptors opened with `O_NOFOLLOW`, so a link swapped in between git's test and its write could be
   followed.
2. **A link swapped in during the restore.** That needs a process still running in the worktree while the harness
   restores. Every agent and gate run goes through `sandbox.wrap` (`agents/base.py:114`, `agents/command.py:107`,
   `implementer/tdd.py:825`, `implementer/workbench.py:824`, `gates/runner.py:172`) [V], and bwrap runs it with
   `--unshare-pid --die-with-parent` (`sandbox/bwrap.py:82`) [V], so every process of the run ends with it [I, the
   kernel ends a PID namespace's processes when its first process exits]. With `sandbox.mode: none` the agent runs
   unconfined by an accepted risk (`sandbox/none.py`) and can write outside the worktree directly, so the race gives it
   nothing more. A process that left the sandbox another way already has the runner user's access. bwrap and none are
   the only modes. Conclusion [I]: no agent can use the race; a fix is defense in depth and the letter of L4-SEC-020.
3. **The one site that follows a link that is already there: the Serena project file.** `_take_serena_project` and
   `settle_serena_project` test only the last component (`is_file()` and `not is_symlink()`). With `.serena` itself a
   link to a folder elsewhere, `.serena/project.yml` reads as a regular file [V, Python: `is_file` True, `is_symlink`
   False]. The harness then reads that file (a 12-character sha256 prefix of it can reach a warning). When the
   revision has no `.serena/project.yml`, `_restore_project` unlinks it. Bounds: only a file named `project.yml`
   that the runner user can remove; `settle_serena_project` unlinks only bytes equal to what Serena wrote at its check
   [V]; `_take_serena_project` compares nothing, and it runs once per run, worktree and Serena context, so a run whose
   steps use two contexts checks again after an earlier agent step [V, `workbench.py:814`]; the unlink branch needs a
   revision without the file, and the three adopted consumers commit one [V, 2026-10-24]. Low severity [I], but this
   site converts first.

Planned shape when a release touches these files: one confined base-restore in `confined.py`, lifted from
`ReplayGuard._base_entry` and `_put_base_back` (`ls-tree`, then `put_blob` or `put_entry`, then
`update-index --add --cacheinfo`). It replaces the single-path sites (`stubs.restore_to_base`, both `guards.py`
restores, `protected._put_back`). The Serena file is read and removed through `read_entry`/`remove_entry`. The
whole-tree resets (`_reset_to_head`, `wip.py`) stay out of scope: they cover the whole tree, and a descriptor-confined
version of `git checkout -- .` and `git clean` is its own change.

## Contracts (texts, exact)

- Failure text: `the replayed step could not be put back to its saved patch (<where>): <path> is a <kind> at the base`.
  `<kind>` is `submodule` (mode 160000) or `entry of mode <mode>`; a path the base has no entry for ends with `<path> has
  no entry at the base`.

## Risks / Trade-offs

- `update-index --cacheinfo` leaves the entry without stat data, so the next `git status` hashes that file again: one
  read of a file the harness just wrote; no behaviour change.
- The racing test is probabilistic. Acceptance is that it passes 30 runs in a row in a Linux container and the eight
  Linux CI shards pass on a dispatched run.
