"""Refresh the remote refs a fold reads (M1.1 gap G8, L4-CLI-005).

The shell runner reuses its clone, and a plain `git fetch` neither prunes nor brings the lock refs: after the forge
deleted a merged unit branch, `origin/l4/...` would still fold the old ledger. So `l4 status`, `l4 plan`, `l4 resume`
and `l4 run` fetch the unit branches, the lock refs and the plan refs with `--prune` first, in a CI job and on a
person's computer alike (`--no-fetch` reads the local refs); `WorktreeManager.ensure` does the same before every
worktree.
"""

import logging
from collections.abc import Sequence

from l4.vcs.git import Git

REMOTE = "origin"
LOCK_REFSPEC = "+refs/l4/locks/*:refs/l4/locks/*"
PLAN_REFSPEC = "+refs/l4/plans/*:refs/l4/plans/*"  # delivery plans (yolo-mode D4): `l4 plan` reads them read-only
log = logging.getLogger("l4.refresh")
_refreshed: set[tuple[str, str]] = set()


def unit_refspecs(branch_prefix: str, remote: str = REMOTE) -> tuple[str, ...]:
    """The unit branches and the lock refs, and nothing else: `--prune` only touches refs that match these."""
    return (f"+refs/heads/{branch_prefix}*:refs/remotes/{remote}/{branch_prefix}*", LOCK_REFSPEC)


def _key(git: Git, run_id: str) -> tuple[str, str]:
    return (run_id, str(git.repo.resolve()))


def mark_refreshed(git: Git, run_id: str) -> None:
    """The process fetched the unit refs by itself (`l4 retry`, `l4 restart`): the refresh that follows must not fetch
    again, and `l4 restart` keeps the tracking ref of a deleted branch on purpose (`prune=False`)."""
    _refreshed.add(_key(git, run_id))


def refresh_remote_refs(
    git: Git,
    *,
    branch_prefix: str,
    run_id: str,
    config: Sequence[tuple[str, str]] = (),
    remote: str = REMOTE,
    fetch: bool = True,
) -> bool:
    """Fetch with `--prune` the unit branches, the lock refs (`actions/checkout` never fetches `refs/l4/locks/*`) and
    the plan refs, once per run (a run is one process); True when it fetched. `fetch=False` (`--no-fetch`) reads the
    local refs, and a checkout without the remote is not fetched. A failed fetch raises: reading refs that are known to
    be stale is how a deleted branch comes back."""
    if not fetch:
        return False
    key = _key(git, run_id)
    if key in _refreshed:
        return False
    if git.run("remote", "get-url", remote, check=False).returncode != 0:
        log.info("no remote %s: the refs are not refreshed", remote)
        return False
    git.fetch(remote, refspecs=(*unit_refspecs(branch_prefix, remote), PLAN_REFSPEC), prune=True, config=config)
    _refreshed.add(key)
    return True
