"""Branch, ref and path names of a unit (SPEC 4.2, L4-WTR-001). Unit ids come from repo content: validate first."""

import re
from dataclasses import dataclass
from pathlib import Path

from l4.specs.base import parse_unit_id

_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*/?$")


def valid_branch_prefix(branch_prefix: str) -> bool:
    return bool(_PREFIX.match(branch_prefix)) and ".." not in branch_prefix and ".lock" not in branch_prefix


_BASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def valid_base_branch(base_branch: str) -> bool:
    """A base branch name that is safe to write into a CI file: no `..`, no trailing `/` or `.lock`, no quote, space,
    `$` or newline."""
    return bool(_BASE.match(base_branch)) and ".." not in base_branch and not base_branch.endswith(("/", ".lock"))


def check_branch_prefix(branch_prefix: str) -> None:
    if not valid_branch_prefix(branch_prefix):
        raise ValueError(f"not a usable branch prefix: {branch_prefix!r}")


def unit_branch(unit_id: str, branch_prefix: str) -> str:
    """`<prefix><framework>/<name>`, e.g. `l4/openspec/add-login`; ValueError for a bad unit id or prefix."""
    framework, name = parse_unit_id(unit_id)
    check_branch_prefix(branch_prefix)
    return f"{branch_prefix}{framework.value}/{name}"


def archive_branch(unit_id: str, branch_prefix: str) -> str:
    """`<prefix>archive/<framework>/<name>`: the post-merge archive MR's branch (L4-ARC-007)."""
    framework, name = parse_unit_id(unit_id)
    check_branch_prefix(branch_prefix)
    return f"{branch_prefix}archive/{framework.value}/{name}"


def lock_ref(unit_id: str) -> str:
    """The unit's lock ref `refs/l4/locks/<framework>/<name>` (G7: custom refs are accepted on the reference server)."""
    framework, name = parse_unit_id(unit_id)
    return f"refs/l4/locks/{framework.value}/{name}"


@dataclass(frozen=True)
class UnitNames:
    unit_id: str
    branch: str  # <prefix><framework>/<name>
    wip_branch: str
    lock_ref: str
    lock_branch: str
    archive_branch: str  # <prefix>archive/<framework>/<name>: the post-merge archive MR (L4-ARC-007)
    worktree: Path  # $L4_CACHE/worktrees/<key>/<fw>/<name>, outside the repository
    flock_path: Path  # $L4_CACHE/locks/<key>/<fw>/<name>.lock
    archive_worktree: Path  # $L4_CACHE/worktrees/<key>/archive/<fw>/<name>

    @classmethod
    def for_unit(cls, unit_id: str, *, branch_prefix: str, cache: Path, repo_key: str) -> "UnitNames":
        """`repo_key` is `l4.vcs.repokey.repository_key`: the paths carry it so two projects never share one."""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", repo_key):
            raise ValueError(f"not a usable repository key: {repo_key!r}")
        framework, name = parse_unit_id(unit_id)  # ValueError for anything that is not <framework>:<safe name>
        fw = framework.value
        return cls(
            unit_id=unit_id,
            branch=unit_branch(unit_id, branch_prefix),
            wip_branch=f"l4-wip/{fw}/{name}",
            lock_ref=lock_ref(unit_id),
            lock_branch=f"l4-lock/{fw}/{name}",
            archive_branch=archive_branch(unit_id, branch_prefix),
            worktree=cache / "worktrees" / repo_key / fw / name,
            flock_path=cache / "locks" / repo_key / fw / f"{name}.lock",
            archive_worktree=cache / "worktrees" / repo_key / "archive" / fw / name,
        )
