"""Pure rules of the M1.1 acceptance protocol that decide what a pipeline or a merge request proves (unit tested)."""

from datetime import datetime
from typing import Any

LOCK_NAMESPACES = ("refs/l4/", "l4-lock/")


def started_by_a_lock_ref_push(pipeline: dict[str, Any]) -> bool:
    """A pipeline on a ref in the lock namespace. GitLab's own `refs/merge-requests/<iid>/head` refs are not: every
    push to a merge request branch makes a (skipped, when the push says `[skip ci]`) merge request pipeline there."""
    return str(pipeline.get("ref", "")).startswith(LOCK_NAMESPACES)


def happened_after(stamp: str, anchor: str) -> bool:
    """`stamp` is not earlier than `anchor` (GitLab timestamps carry different UTC offsets, so compare instants)."""
    return datetime.fromisoformat(stamp) >= datetime.fromisoformat(anchor)
