# Design: readonly-scratch-removal

## Decisions

**D1. Unlock and retry, not `ignore_errors`.** Go's module cache is read-only by design (`go clean -modcache` makes it
writable before it removes it). `shutil.rmtree(path, onexc=...)` (Python 3.12) calls the handler for each entry it
cannot remove; the handler makes the entry's parent directory and the entry `0o700`, each only when it is the removed
tree's root or lies inside it, and calls the failed function once more. This is `resultalias._unlock_and_retry`, moved
to `l4.sandbox.base` as the handler of `remove_tree` so that both callers share it; the old handler also changed the
mode of the tree's own parent, which the new one leaves alone. When rmtree could not open, list or stat a directory
(mode 0o000 or 0o300), retrying that call cannot help (`os.open` needs its flags, and rmtree does not descend after the
failure), so the handler removes that directory as a whole the same way once it is readable; an entry that is gone
already is no error, and one that fails a second time raises, so the retry cannot loop. On Python 3.11, which has no
`onexc`, the same handler goes in as `onerror`. rmtree never follows a symlink inside the tree, and the handler checks `is_symlink()` before each
`chmod`, so a link that an agent planted in the scratch cannot point a `chmod` at a file outside it.

**D2. Loud at the start, quiet at the end.** A start (`reset_agent_tmp`, `readonly_with_scratch(create=True)`,
`verifier_caches`) must give the step an empty tree: when the removal still fails, the `OSError` propagates and the run
stops with the path in the message, as any other failure to prepare a sandbox does. An end (`discard_scratch`, the
gate's scratch after the gate) is cleanup: a failure is logged as a warning naming the path, and the next start, which
removes the same tree, raises if the problem stays.

**D3. One helper for every private tree of a step.** The six call sites listed in the proposal are every place where
the harness removes a tree that an agent step or a gate could have written with `shutil.rmtree(..., ignore_errors=True)`
or with the alias's own handler. `envdirs.reset_tool_caches` (the tool caches inside `node_modules`) already raises on
a failure and is not changed.

## Failure cases

- A directory 0o555 holding a file 0o444 (Go's module layout) in a scratch cache: removed, and the next step's scratch
  is an empty directory.
- A directory with mode 0o000 (a test suite left it in the temp directory): removed with what it holds.
- A symlink in the scratch that points outside it: the link is removed; the target and its mode are unchanged.
- A tree that cannot be removed even after the unlock (another owner): the start raises `OSError` naming the path; the
  end logs a warning.
- The tree's own parent is read-only (it is outside the tree, for the result alias the worktree itself): its mode is
  not changed, and the removal raises.
- A missing path: nothing to do, no error.
