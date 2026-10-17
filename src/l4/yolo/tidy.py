"""Deleting the branches of merged plan units (squash-and-delete D6, D7; L4-YOLO-033).

`tidy_unit_branch`: the verified head is kept at `refs/l4/merged/<framework>/<name>` (create-only), then the unit
branch is deleted under a lease on that head. `tidy_archive_branch`: the archive branch is deleted under a lease on its
head (its commit is on the base already). Both answer the plan event to record, or None when there was nothing to do:
`unit.branch_deleted{unit, branch, head}`, or `unit.branch_kept{unit, branch, reason}` when a person's push moved the
branch (the lease), the keep ref holds another commit, or the forge refused the delete. Neither raises for a git
refusal, so no plan stops for a branch.

The caller decides that the forge shows the pull request merged: GitHub closes an open pull request whose head branch
is deleted.
"""

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.base import fetch_auth_config
from l4.forge.gitlab import push_auth_config
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.push import ForcedPushRefused, delete_branch, keep_ref, merged_ref

_REASON_CHARS = 300

Tidied = tuple[str, dict[str, object]]  # (plan event type, its data)


def _kept(unit: str, branch: str, reason: str) -> Tidied:
    return "unit.branch_kept", {"unit": unit, "branch": branch, "reason": reason}


def _delete(app: AppContext, cfg: L4Config, git: Git, unit: str, branch: str, head: str) -> Tidied | None:
    config = push_auth_config(cfg, app.environ)
    try:
        done = delete_branch(git, branch, head, config=config, read_config=fetch_auth_config(cfg, app.environ))
    except (GitError, ForcedPushRefused) as exc:
        lines = [line.strip() for line in str(getattr(exc, "stderr", "") or exc).splitlines() if line.strip()][:3]
        return _kept(unit, branch, app.redactor.redact_text(" | ".join(lines))[:_REASON_CHARS] or "the delete failed")
    if done == "gone":
        return None
    if done == "kept":
        return _kept(unit, branch, f"the branch is no longer at the merged head {head[:10]}: left as it is")
    return "unit.branch_deleted", {"unit": unit, "branch": branch, "head": head}


def tidy_unit_branch(app: AppContext, cfg: L4Config, git: Git, unit: str, branch: str, head: str) -> Tidied | None:
    from l4.yolo.merge import _have  # noqa: PLC0415 - the object may be a tip another clone pushed

    config = push_auth_config(cfg, app.environ)
    ref = merged_ref(unit)
    try:
        _have(git, cfg, app.environ, head)
        kept = keep_ref(git, ref, head, config=config, read_config=fetch_auth_config(cfg, app.environ))
    except (GitError, ForcedPushRefused) as exc:
        return _kept(unit, branch, app.redactor.redact_text(f"{ref} could not be written: {exc}")[:_REASON_CHARS])
    if kept == "differs":
        return _kept(unit, branch, f"{ref} holds another commit than the merged head {head[:10]}: left as it is")
    return _delete(app, cfg, git, unit, branch, head)


def tidy_archive_branch(app: AppContext, cfg: L4Config, git: Git, unit: str, branch: str, head: str) -> Tidied | None:
    return _delete(app, cfg, git, unit, branch, head)


def branch_tips(app: AppContext, cfg: L4Config, git: Git) -> dict[str, str]:
    """One `ls-remote` of the harness' branches: branch name -> tip."""
    listing = git.run(
        "ls-remote", "origin", f"refs/heads/{cfg.forge.branch_prefix}*", config=fetch_auth_config(cfg, app.environ)
    ).stdout
    tips = {}
    for line in listing.splitlines():
        sha, _, ref = line.partition("\t")
        if sha and ref.startswith("refs/heads/"):
            tips[ref.strip().removeprefix("refs/heads/")] = sha
    return tips
