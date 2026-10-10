"""Work-in-progress snapshots (SPEC L4-IMP-011, state-vcs-locks D1).

A snapshot is a commit built from a temporary index, so the worktree's real index, its HEAD, its stash and its files
are never touched. It is stored under the local ref `refs/l4/wip/<framework>/<name>` of the runner's clone and never
pushed. M1: state-vcs-locks 2.x pushes it to `l4-wip/<framework>/<name>` under the lease, once fencing exists.
"""

import tempfile
from collections.abc import Sequence
from pathlib import Path

from l4.exitcodes import ExitCode, L4Exit
from l4.specs.base import parse_unit_id
from l4.vcs.git import BOT_IDENTITY, Git

WIP_REF_PREFIX = "refs/l4/wip"
MESSAGE = "wip: snapshot of unfinished work [skip ci]"
STEP_TRAILER = "L4-Step"


class WipMismatch(L4Exit):
    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, message)


def wip_ref(unit_id: str) -> str:
    framework, name = parse_unit_id(unit_id)
    return f"{WIP_REF_PREFIX}/{framework.value}/{name}"


def snapshot_wip(
    git: Git,
    unit_id: str,
    *,
    config: Sequence[tuple[str, str]] = (),
    step: str | None = None,
    update_ref: bool = True,
    exclude: str | None = None,
) -> str | None:
    """Commit every change of the worktree (tracked, deleted, untracked and binary files; `config` carries the harness
    excludes, e.g. `core.excludesFile`) on top of HEAD, point the unit's WIP ref at it and return its id. None when the
    worktree already equals HEAD: there is nothing to keep, and the ref is left as it was. `step`
    (`<task>/<phase>/<attempt>`) is written into the message as the `L4-Step` trailer, so a later run can tell which
    step the work belongs to (`l4.state.reconcile`)."""
    ref = wip_ref(unit_id)
    head = git.rev_parse("HEAD")
    if head is None:
        raise WipMismatch("the worktree has no commit to snapshot on top of")
    with tempfile.TemporaryDirectory(prefix="l4-wip-") as scratch:
        temporary = git.at(git.repo)
        temporary.env["GIT_INDEX_FILE"] = str(Path(scratch) / "index")
        temporary.run("read-tree", head)
        pathspec = (".",) if exclude is None else (".", f":(exclude){exclude}")
        temporary.run("add", "-A", "--", *pathspec, config=config)
        tree = temporary.run("write-tree").stdout.strip()
        if tree == git.run("rev-parse", f"{head}^{{tree}}").stdout.strip():
            return None
        identity = (("user.name", BOT_IDENTITY.name), ("user.email", BOT_IDENTITY.email))
        message = MESSAGE if step is None else f"{MESSAGE}\n\n{STEP_TRAILER}: {step}"
        sha = temporary.run("commit-tree", tree, "-p", head, "-m", message, config=identity).stdout.strip()
    if update_ref:
        git.run("update-ref", ref, sha)
    return sha


def restore_wip(git: Git, wip_sha: str, *, exclude: str | None = None) -> None:
    """Put a snapshot's files back into the worktree whose HEAD it was taken on, then `reset -q <head>` returns the
    index to HEAD and leaves the files, so the work shows as uncommitted changes again. Refuses a snapshot taken on
    another commit. Without `exclude`, `read-tree -u --reset` writes the snapshot's tree (deleting what it deleted).
    With `exclude` (a path the caller keeps writing, such as the run's ledger) that path is never touched, because
    `read-tree --reset` would replace the live file with the snapshot's copy: `checkout --no-overlay` writes the
    snapshot's files except that path and removes what the snapshot deleted, a directory and a file that swapped
    places included, and the directories it empties."""
    head = git.rev_parse("HEAD")
    parent = git.rev_parse(f"{wip_sha}^")
    if head is None or parent != head:
        raise WipMismatch("the snapshot was not taken on this worktree's HEAD; it is not restored")
    if exclude is None:
        git.run("read-tree", "-u", "--reset", wip_sha)
    else:
        git.run("checkout", "--no-overlay", wip_sha, "--", ".", f":(exclude){exclude}")
    git.run("reset", "-q", head)
