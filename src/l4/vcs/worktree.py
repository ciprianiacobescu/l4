"""The unit worktree (SPEC 12.3, L4-WTR-001).

M0 never reuses a worktree: it is removed and recreated from the remote unit branch (or from base), so a crashed
run restarts the current task from the last pushed checkpoint. The fetch before it prunes (G8, `l4.vcs.refresh`).
SPEC gap, to amend: the path has no repository key, so `_remove` refuses a path owned by another repository.
M1: state-vcs-locks 1.12 (reuse after fetch + HEAD check), 1.13/1.14 (WIP snapshot), 1.27/1.28 (merge base in).
"""

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.exitcodes import ExitCode, L4Exit
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import UnitNames
from l4.vcs.refresh import unit_refspecs


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    head: str
    source: Literal["remote_branch", "base"]


class WorktreeManager:
    def __init__(
        self,
        git: Git,
        *,
        base_branch: str,
        branch_prefix: str,
        remote: str = "origin",
        fetch_config: Sequence[tuple[str, str]] = (),
    ) -> None:
        """`fetch_config` is the credential helper (`git -c` pairs): once the forge hook strips the runner's userinfo
        from the origin URL, a later unit's fetch of an internal project has no other credential."""
        self._git = git
        self._base = base_branch
        self._prefix = branch_prefix
        self._remote = remote
        self._fetch_config = fetch_config

    def ensure(self, names: UnitNames) -> Worktree:
        self._refresh_and_clear(names.worktree)
        source: Literal["remote_branch", "base"] = "remote_branch"
        start = self._git.rev_parse(f"refs/remotes/{self._remote}/{names.branch}")
        if start is None:
            source = "base"
            start = self._base_head()
        return self._add(names.branch, names.worktree, start, source)

    def ensure_from_base(self, branch: str, path: Path) -> Worktree:
        """A fresh worktree on `branch`, cut from the latest base head whatever the remote holds under that name (the
        archive branch of a merged unit is built anew on the base the previous archive merged into)."""
        self._refresh_and_clear(path)
        return self._add(branch, path, self._base_head(), "base")

    def _refresh_and_clear(self, path: Path) -> None:
        repo = self._git.repo.resolve()
        if repo == path.resolve() or repo in path.resolve().parents:
            raise L4Exit(ExitCode.USAGE_ERROR, f"the worktree {path} must be outside the repository {repo}")
        # the base, the unit branches and the lock refs, pruned: a unit branch the forge deleted (merged, source branch
        # removed) must not come back from a stale tracking ref (G8)
        base = f"+refs/heads/{self._base}:refs/remotes/{self._remote}/{self._base}"
        try:
            self._git.fetch(
                self._remote, refspecs=(base, *unit_refspecs(self._prefix, self._remote)), prune=True,
                config=self._fetch_config,
            )  # fmt: skip
        except GitError as exc:
            if "couldn't find remote ref" in str(exc):
                raise GitError(["fetch", self._remote, self._base], 1, f"base branch {self._base} not found") from None
            raise
        self._remove(path)

    def _base_head(self) -> str:
        start = self._git.rev_parse(f"refs/remotes/{self._remote}/{self._base}")
        if start is None:
            raise GitError(["rev-parse", f"{self._remote}/{self._base}"], 1, f"base branch {self._base} not found")
        return start

    def _add(self, branch: str, path: Path, start: str, source: Literal["remote_branch", "base"]) -> Worktree:
        path.parent.mkdir(parents=True, exist_ok=True)
        # -B resets a local branch left over from an earlier run to the start point
        self._git.run("worktree", "add", "--quiet", "--no-track", "-B", branch, str(path), start)
        return Worktree(path, branch, start, source)

    def remove(self, path: Path) -> None:
        self._remove(path)

    def _belongs_to_this_repository(self, path: Path) -> bool:
        """False for a checkout that another repository owns. Worktree and lock paths carry no repository key (SPEC
        L4-WTR-001), so two projects on one runner that share a change name meet at the same path; deleting it would
        destroy the other project's live worktree. A path without a `.git` is junk and is ours to replace."""
        marker = path / ".git"
        if not marker.exists() and not marker.is_symlink():
            return True
        common = Path(self._git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()).resolve()
        try:
            text = marker.read_text(encoding="utf-8", errors="replace") if marker.is_file() else ""
        except OSError:
            return False
        prefix = "gitdir:"
        if not text.startswith(prefix):
            return False  # a real `.git` directory: a clone, not one of our worktrees
        gitdir = Path(text[len(prefix) :].strip())
        gitdir = (gitdir if gitdir.is_absolute() else path / gitdir).resolve()
        return common in gitdir.parents

    def _remove(self, path: Path) -> None:
        if not self._belongs_to_this_repository(path):
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"{path} is a checkout of another repository; refusing to delete it "
                "(two projects share a change name on this runner)",
            )
        self._git.run("worktree", "remove", "--force", str(path), check=False)  # not registered: nothing to do
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
        self._git.run("worktree", "prune")
