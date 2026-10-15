"""A snapshot of the working tree as a commit that touches no ref, the index or HEAD (review-resolution design D5,
section 8). Contract only: the bodies come in wave 1."""

from collections.abc import Sequence

from l4.vcs.git import Git


def snapshot(git: Git, paths: Sequence[str]) -> str:
    """A commit sha holding HEAD's tree plus the working-tree state of `paths`; `HEAD`, the index and every ref stay."""
    raise NotImplementedError


def clean(git: Git, paths: Sequence[str]) -> bool:
    """No staged, unstaged or untracked change under `paths`."""
    raise NotImplementedError
