"""Refresh the remote refs a fold reads (M1.1 gap G8).

The shell runner reuses its clone, and a plain `git fetch` neither prunes nor brings the lock refs: after the forge
deleted a merged unit branch, `origin/l4/...` would still fold the old ledger. So inside GitLab CI `l4 plan`,
`l4 status` and `l4 run` fetch the unit branches and the lock refs with `--prune` first; `WorktreeManager.ensure` does
the same before every worktree. A local run reads local refs, as in M0.
"""

import logging
from collections.abc import Mapping, Sequence

from l4.vcs.git import Git

REMOTE = "origin"
LOCK_REFSPEC = "+refs/l4/locks/*:refs/l4/locks/*"
PLAN_REFSPEC = "+refs/l4/plans/*:refs/l4/plans/*"  # delivery plans (yolo-mode D4): `l4 plan` reads them read-only
log = logging.getLogger("l4.refresh")
_refreshed: set[tuple[str, str]] = set()


def unit_refspecs(branch_prefix: str, remote: str = REMOTE) -> tuple[str, ...]:
    """The unit branches and the lock refs, and nothing else: `--prune` only touches refs that match these."""
    return (f"+refs/heads/{branch_prefix}*:refs/remotes/{remote}/{branch_prefix}*", LOCK_REFSPEC)


def refresh_in_ci(
    git: Git,
    *,
    environ: Mapping[str, str],
    branch_prefix: str,
    run_id: str,
    config: Sequence[tuple[str, str]] = (),
    remote: str = REMOTE,
) -> bool:
    """Fetch with `--prune` when `GITLAB_CI=true` or `GITHUB_ACTIONS=true` (`actions/checkout` never fetches
    `refs/l4/locks/*`), once per run (a run is one process). True when it fetched. A failed fetch raises: reading
    refs that are known to be stale is how a deleted branch comes back."""
    if environ.get("GITLAB_CI") != "true" and environ.get("GITHUB_ACTIONS") != "true":
        return False
    key = (run_id, str(git.repo.resolve()))
    if key in _refreshed:
        return False
    if git.run("remote", "get-url", remote, check=False).returncode != 0:
        log.info("no remote %s: the refs are not refreshed", remote)
        return False
    git.fetch(remote, refspecs=(*unit_refspecs(branch_prefix, remote), PLAN_REFSPEC), prune=True, config=config)
    _refreshed.add(key)
    return True
