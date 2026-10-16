"""A snapshot of the working tree as a commit that touches no ref, the index or HEAD (review-resolution design D5,
section 8). `Git.rev_parse` needs a commit, hence `commit-tree` and not a bare tree."""

import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from l4.config.defaults import cache_root
from l4.vcs.git import Git

AUTHOR_NAME = "l4"
AUTHOR_EMAIL = "l4@localhost"
MESSAGE = "l4 working tree"


def _existing(git: Git, paths: Sequence[str]) -> list[str]:
    """The paths that are in the working tree or in HEAD: `git add -A` fails on a pathspec matching neither."""
    kept = []
    for path in paths:
        if (git.repo / path).exists() or git.run(
            "ls-tree", "--name-only", "HEAD", "--", path, check=False
        ).stdout.strip():
            kept.append(path)
    return kept


def snapshot(git: Git, paths: Sequence[str]) -> str:
    """A commit sha holding HEAD's tree plus the working-tree state of `paths`; `HEAD`, the index and every ref stay.
    The same tree on the same HEAD gives the same sha (fixed author, the date of HEAD or
    the epoch's first second, since git refuses @0)."""
    head = git.rev_parse("HEAD")
    base = cache_root(git.env, repo=git.repo) / "yolo-snapshot"
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="idx-", dir=base))
    try:
        date = "@1 +0000"
        if head is not None:
            date = f"@{git.run('log', '-1', '--format=%ct', head).stdout.strip()} +0000"
        temp = git.at(git.repo)
        temp.env = {
            **temp.env,
            "GIT_INDEX_FILE": str(scratch / "index"),
            "GIT_AUTHOR_NAME": AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_NAME": AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_DATE": date,
        }
        if head is not None:
            temp.run("read-tree", head)
        wanted = _existing(git, paths)
        if wanted:
            temp.run("add", "-A", "--", *wanted)
        tree = temp.run("write-tree").stdout.strip()
        parents = ["-p", head] if head is not None else []
        sha = temp.run("commit-tree", tree, *parents, "-m", MESSAGE).stdout.strip()
        git.history.extend(temp.history)
        return sha
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def clean(git: Git, paths: Sequence[str]) -> bool:
    """No staged, unstaged or untracked change under `paths`."""
    if not paths:
        return True
    done = git.run("status", "--porcelain=v1", "--untracked-files=all", "--", *paths)
    return not done.stdout.strip()
