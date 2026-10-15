"""The unit worktree (SPEC 12.3, L4-WTR-001).

M0 never reuses a worktree: it is removed and recreated from the remote unit branch (or from base), so a crashed
run restarts the current task from the last pushed checkpoint. The fetch before it prunes (G8, `l4.vcs.refresh`).
The path carries the repository key (`l4.vcs.repokey`); `_remove` replaces a checkout of this project or an orphan
and refuses one that another repository owns.
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
from l4.vcs.repokey import key_of_common_dir


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
        """Whether `path` is ours to replace. Three outcomes for an existing checkout, by repository key
        (`l4.vcs.repokey`, SPEC L4-WTR-001): the same key (another clone or build directory of this project; the
        unit's flock, held by every caller before it prepares or removes the path, serialises those jobs) and an
        orphan (its gitdir points into a clone that no longer exists, so its origin cannot be read) are ours; a
        different key is another project's live checkout and is refused. A path without a `.git` is junk."""
        marker = path / ".git"
        if not marker.exists() and not marker.is_symlink():
            return True
        common = self._common_dir_of(path, marker)
        if common is None:
            return False  # a `.git` we cannot read: not ours to delete
        if common == "orphan":
            return True
        ours = Path(self._git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()).resolve()
        if common == ours:
            return True
        return key_of_common_dir(common, self._git.env) == key_of_common_dir(ours, self._git.env)

    @staticmethod
    def _common_dir_of(path: Path, marker: Path) -> Path | Literal["orphan"] | None:
        """The git common dir of the checkout at `path`; "orphan" when its gitdir no longer exists; None when the
        marker cannot be read."""
        if marker.is_dir():
            return marker.resolve()  # a clone's own `.git` directory
        try:
            text = marker.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        prefix = "gitdir:"
        if not text.startswith(prefix):
            return None
        gitdir = Path(text[len(prefix) :].strip())
        gitdir = (gitdir if gitdir.is_absolute() else path / gitdir).resolve()
        if not gitdir.is_dir():
            return "orphan"
        pointer = gitdir / "commondir"
        if pointer.is_file():
            target = Path(pointer.read_text(encoding="utf-8", errors="replace").strip())
            gitdir = (target if target.is_absolute() else gitdir / target).resolve()
            if not gitdir.is_dir():
                return "orphan"
        return gitdir

    def _remove(self, path: Path) -> None:
        if not self._belongs_to_this_repository(path):
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"{path} is a checkout of another repository; refusing to delete it "
                "(a leftover of the layout without a repository key, or a path outside the keyed cache)",
            )
        self._git.run("worktree", "remove", "--force", str(path), check=False)  # not registered: nothing to do
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
        self._git.run("worktree", "prune")
