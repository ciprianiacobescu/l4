"""A short result path inside the worktree for an adapter that writes its result from the prompt (SPEC 8.1, MAG).

A model that is told to write `/home/<user>/.cache/l4/units/<fw>/<unit>/agent-tmp/result.json` may "correct" a segment
of that long path (magnitude-qwen turned `units` into `worktrees` in 3 of 3 attempts) and write inside the worktree
instead. So the prompt names `.l4-result/result.json`, relative to the working directory, and that path is a symlink the
harness makes to the step's private directory just before the agent runs and removes just after.

What this is not: a second place a result is read from. The result is read from the private directory only
(`read_result_file(req.result_path)`); a file the agent wrote anywhere in the worktree, `agent-tmp/result.json`
included, is never a result and is discarded with the rest of a failed attempt. The alias is excluded from git
(`HARNESS_EXCLUDES`), a protected path, and gone before any gate or commit, so nothing that is written through it, or
in place of it, can reach a commit. The private directory is bound into the sandbox at its own host path, so the link
resolves under bwrap and under `sandbox.mode: none` without a change to the sandbox argument list.
"""

import os
from pathlib import Path

from l4.sandbox.base import remove_tree

RESULT_ALIAS = ".l4-result"
RESULT_FILE = "result.json"
RESULT_ALIAS_PATH = f"{RESULT_ALIAS}/{RESULT_FILE}"  # what the prompt says, relative to the working directory


def drop(worktree: Path) -> None:
    """Remove whatever is at the alias: the link (never its target), a file, or a directory put in its place."""
    path = worktree / RESULT_ALIAS
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        remove_tree(path)  # makes a read-only directory an agent left there writable; follows no link inside it


def link(worktree: Path, step_dir: Path) -> None:
    """Make `<worktree>/.l4-result` a link to `step_dir`, replacing any leftover."""
    drop(worktree)
    os.symlink(step_dir, worktree / RESULT_ALIAS, target_is_directory=True)
