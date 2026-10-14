"""Push argument construction: never forced (L4-RACE-001, SCN-LCK-04). The one exception is the lease push of a lock
ref (L4-LCK-001): `--force-with-lease=<ref>:<expected>`, which the server refuses unless the ref still holds the value
the harness last saw.

M1: state-vcs-locks 1.7 (`Lease`) for the lock protocol of M2.
"""

import re
from collections.abc import Sequence

from l4.vcs.errors import GitError


class ForcedPushRefused(ValueError):
    """A refspec or option that could overwrite remote history, or one git would read as an option."""


class PushRejected(GitError):
    """The remote refused the update because the ref moved on: a non-fast-forward or `fetch first` of a branch, a lost
    lease of a lock ref. A protected branch or a push rule is not this (`! [remote rejected]`, G12): that is the
    forge's refusal, a plain `GitError`. Callers decide; nothing is forced."""


def is_non_fast_forward(stderr: str) -> bool:
    return _NON_FAST_FORWARD.search(stderr) is not None


def is_lost_lease(stderr: str) -> bool:
    return ("[rejected]" in stderr or "[remote rejected]" in stderr) and any(m in stderr for m in LEASE_LOST)


def build_push_args(remote: str, refspecs: Sequence[str]) -> list[str]:
    if not remote or remote.startswith("-"):
        raise ForcedPushRefused(f"not a remote name: {remote!r}")
    if not refspecs:
        raise ForcedPushRefused("nothing to push")
    for spec in refspecs:
        if spec.startswith("+"):
            raise ForcedPushRefused(f"forced refspec refused: {spec!r}")
        if not spec or spec.startswith("-"):
            raise ForcedPushRefused(f"option-like refspec refused: {spec!r}")
    return ["push", "--", remote, *refspecs]


_NON_FAST_FORWARD = re.compile(r"^\s*! \[rejected\].*\((?:non-fast-forward|fetch first)\)", re.MULTILINE)
# what git (client side) and a server (when the race is lost between the check and the update) say about a lease that
# no longer holds; any other refusal, a hook or a permission, is not worth another try
LEASE_LOST = ("stale info", "failed to update ref", "cannot lock ref", "failed to lock")
_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
LOCK_REF_PREFIX = "refs/l4/locks/"
ARCHIVED_REF_PREFIX = "refs/l4/archived/"
ATTEMPT_REF_PREFIX = "refs/l4/attempts/"  # `l4 restart` keeps old heads here (L4-OPS-004)


def _plain_ref(ref: str, prefix: str | tuple[str, ...]) -> bool:
    bad = ref.endswith("/") or re.search(r"[^A-Za-z0-9._/-]", ref) or ".." in ref
    return ref.startswith(prefix) and not bad


def build_branch_push_args(remote: str, branch: str, expected: str) -> list[str]:
    """Push HEAD to the unit branch only if the remote still holds `expected` ('' = it must not exist). A branch that
    a person deleted therefore fails with `stale info` instead of being created again (W-D2). The lease is never a
    `+` refspec; and because git forces a push whose lease holds, the caller checks fast-forward first."""
    if not remote or remote.startswith("-"):
        raise ForcedPushRefused(f"not a remote name: {remote!r}")
    if expected and not _OBJECT_ID.match(expected):
        raise ForcedPushRefused(f"not a commit id: {expected!r}")
    ref = f"refs/heads/{branch}"
    if not branch or not _plain_ref(ref, "refs/heads/") or branch.startswith("-"):
        raise ForcedPushRefused(f"not a branch name: {branch!r}")
    return ["push", f"--force-with-lease={ref}:{expected}", "--", remote, f"HEAD:{ref}"]


def build_lease_push_args(remote: str, sha: str, ref: str, expected: str) -> list[str]:
    """Push `sha` to the lock ref `ref` only if it still holds `expected` ('' = it must not exist). Nothing else can
    be pushed this way, and the lease is never a `+` refspec, which would silently override it."""
    if not remote or remote.startswith("-"):
        raise ForcedPushRefused(f"not a remote name: {remote!r}")
    if not _OBJECT_ID.match(sha):
        raise ForcedPushRefused(f"not a commit id: {sha!r}")
    if expected and not _OBJECT_ID.match(expected):
        raise ForcedPushRefused(f"not a commit id: {expected!r}")
    if not _plain_ref(ref, LOCK_REF_PREFIX):
        raise ForcedPushRefused(f"not a lock ref: {ref!r}")
    return ["push", f"--force-with-lease={ref}:{expected}", "--", remote, f"{sha}:{ref}"]


def build_restart_args(remote: str, branch: str, old_head: str, lock: tuple[str, str, str] | None = None) -> list[str]:
    """`l4 restart` (L4-OPS-004): push HEAD over the unit branch and, when there is a lock ref, move it to the attempt's
    `-locks` name, in ONE atomic push. The leases: the branch at `old_head` ('' = it must not exist), and for `lock` =
    `(lock ref, its sha, archived name)` the lock ref at that sha and the archived name absent. Either every ref moves
    or none does, so a lost lease leaves the pending ledger where the fold reads it."""
    if not remote or remote.startswith("-"):
        raise ForcedPushRefused(f"not a remote name: {remote!r}")
    if old_head and not _OBJECT_ID.match(old_head):
        raise ForcedPushRefused(f"not a commit id: {old_head!r}")
    ref = f"refs/heads/{branch}"
    if not branch or not _plain_ref(ref, "refs/heads/") or branch.startswith("-"):
        raise ForcedPushRefused(f"not a branch name: {branch!r}")
    args = ["push", "--atomic", f"--force-with-lease={ref}:{old_head}"]
    specs = [f"HEAD:{ref}"]
    if lock is not None:
        lock_ref, sha, archived = lock
        if not _OBJECT_ID.match(sha):
            raise ForcedPushRefused(f"not a commit id: {sha!r}")
        if not _plain_ref(lock_ref, LOCK_REF_PREFIX):
            raise ForcedPushRefused(f"not a lock ref: {lock_ref!r}")
        if not _plain_ref(archived, ATTEMPT_REF_PREFIX):
            raise ForcedPushRefused(f"not an attempts ref: {archived!r}")
        args += [f"--force-with-lease={lock_ref}:{sha}", f"--force-with-lease={archived}:"]
        specs += [f"{sha}:{archived}", f":{lock_ref}"]
    return [*args, "--", remote, *specs]


def build_retire_args(remote: str, sha: str, ref: str, archived: str) -> list[str]:
    """Move the lock ref `ref` to `archived` (a ref that must not exist yet, under `refs/l4/archived/` or, for
    `l4 restart`, `refs/l4/attempts/`) in one atomic push, only if `ref` still holds `sha`: the commit, and the pending
    ledger in it, is kept under the new name."""
    if not remote or remote.startswith("-"):
        raise ForcedPushRefused(f"not a remote name: {remote!r}")
    if not _OBJECT_ID.match(sha):
        raise ForcedPushRefused(f"not a commit id: {sha!r}")
    if not _plain_ref(ref, LOCK_REF_PREFIX):
        raise ForcedPushRefused(f"not a lock ref: {ref!r}")
    if not _plain_ref(archived, (ARCHIVED_REF_PREFIX, ATTEMPT_REF_PREFIX)):
        raise ForcedPushRefused(f"not an archived ref: {archived!r}")
    return [
        "push", "--atomic", f"--force-with-lease={ref}:{sha}", f"--force-with-lease={archived}:", "--", remote,
        f"{sha}:{archived}", f":{ref}",
    ]  # fmt: skip
