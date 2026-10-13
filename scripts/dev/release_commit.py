#!/usr/bin/env python3
"""Build the slim release commit on branch `release` (L4-ACT-006).

    python scripts/dev/release_commit.py --source <sha> --version X.Y.Z [--repo DIR] [--branch release]

The commit's tree holds only the shipped paths of the source commit, its parent is the current tip of the branch
(none for the first release), its message is `release vX.Y.Z from <source sha>`. It is built with plumbing on a
temporary index, so the working tree, the index and the checked-out branch are never touched. Its tree is then
checked against a `git archive` of the same paths at the source; only when they are equal does the branch move.
The new commit's sha is printed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Always shipped (a missing src/ or pyproject.toml is an error) and shipped only when present.
REQUIRED = ("src", "pyproject.toml")
OPTIONAL = (
    "uv.lock", "README.md", "LICENSE", ".github/actions/l4",
    ".claude-plugin", "plugins/l4/.claude-plugin", "plugins/l4/skills",  # the l4 skill (not its tests/)
)  # fmt: skip
SHIPPED = REQUIRED + OPTIONAL
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(Exception):
    pass


def git(repo: Path, *args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> bytes:
    done = subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **(env or {})}, input=stdin, capture_output=True, check=False
    )
    if done.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def present_paths(repo: Path, source: str) -> list[str]:
    """The shipped paths that exist in the source commit."""
    found = [p for p in SHIPPED if git(repo, "ls-tree", "--name-only", source, "--", p).strip()]
    for needed in REQUIRED:
        if needed not in found:
            raise ReleaseError(f"{source} has no {needed}; refusing to build a release from it")
    return found


def tree_of_paths(repo: Path, source: str, paths: list[str]) -> str:
    """The tree sha of `paths` at `source`, from a temporary index."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        listing = git(repo, "ls-tree", "-r", "-z", "--full-tree", source, "--", *paths)
        records = []
        for entry in filter(None, listing.split(b"\0")):
            meta, name = entry.split(b"\t", 1)
            mode, _kind, sha = meta.split()
            records.append(b"%s %s\t%s\0" % (mode, sha, name))
        git(repo, "update-index", "--add", "-z", "--index-info", env=env, stdin=b"".join(records))
        return git(repo, "write-tree", env=env).decode().strip()


def archive_tree(repo: Path, source: str, paths: list[str]) -> str:
    """The tree sha of an extracted `git archive` of `paths` at `source` (an independent route to the same tree)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "x"
        root.mkdir()
        tar = git(repo, "archive", "--format=tar", source, "--", *paths)
        subprocess.run(["tar", "-xf", "-", "-C", str(root)], input=tar, check=True)
        scratch = Path(tmp) / "scratch.git"  # a throwaway object store: the real repository gains nothing
        subprocess.run(["git", "init", "-q", "--bare", str(scratch)], check=True)
        env = {"GIT_DIR": str(scratch), "GIT_WORK_TREE": str(root), "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(root, "add", "-A", "-f", env=env)
        return git(root, "write-tree", env=env).decode().strip()


def verify(repo: Path, commit: str, source: str) -> None:
    """Raise ReleaseError unless the commit's tree equals a `git archive` of the shipped paths at `source`."""
    expected = archive_tree(repo, source, present_paths(repo, source))
    actual = git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if actual != expected:
        raise ReleaseError(f"release tree {actual} differs from the git archive of {source} ({expected})")


def build(repo: Path, source: str, version: str, branch: str = "release") -> str:
    """Create the release commit, verify it, move `branch` to it, return its sha."""
    if not VERSION.match(version):
        raise ReleaseError(f"version must look like X.Y.Z, got {version!r}")
    source = git(repo, "rev-parse", "--verify", f"{source}^{{commit}}").decode().strip()
    tree = tree_of_paths(repo, source, present_paths(repo, source))
    ref = f"refs/heads/{branch}"
    probe = subprocess.run(["git", "rev-parse", "--verify", "-q", ref], cwd=repo, capture_output=True, text=True)
    parent = probe.stdout.strip() if probe.returncode == 0 else ""
    args = ["commit-tree", tree, "-m", f"release v{version} from {source}"]
    if parent:
        args += ["-p", parent]
    commit = git(repo, *args).decode().strip()
    verify(repo, commit, source)
    git(repo, "update-ref", "-m", f"release v{version}", ref, commit, parent or "0" * 40)
    return commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="the source commit (sha or ref)")
    parser.add_argument("--version", required=True, help="X.Y.Z, without the v")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--branch", default="release")
    args = parser.parse_args(argv)
    try:
        print(build(args.repo, args.source, args.version, args.branch))
    except ReleaseError as exc:
        print(f"release_commit: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
