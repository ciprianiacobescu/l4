"""The throw-away git world of a scenario (SPEC L4-SIM-002): a bare "remote", a clone seeded from a fixture, and a
second clone for the human who edits the remote between runs.

Every git call goes through `l4.vcs.git.Git`. Identities and dates are fixed (one minute apart), so two builds of the
same fixture have the same commit ids. Everything lives under one temporary directory, removed by `cleanup()` unless
`keep` is set (`l4 simulate --keep`).
"""

import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.resources.abc import Traversable
from pathlib import Path

from l4.safepath import safe_path
from l4.sim.scenarios import fixture_root
from l4.vcs.git import Git, Identity

SEED = Identity("Sim Seed", "sim-seed@example.invalid")
HUMAN = Identity("Sim Human", "sim-human@example.invalid")
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
BASE_BRANCH = "main"
_GIT_CONFIG = (("commit.gpgsign", "false"), ("init.defaultBranch", BASE_BRANCH), ("core.autocrlf", "false"))


_NOT_FIXTURE = frozenset({".l4-out", "__pycache__"})  # what a run or the interpreter leaves in the package directory


def _copy(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir(), key=lambda e: e.name):
        if entry.name in _NOT_FIXTURE or entry.name.endswith(".pyc"):
            continue
        if entry.is_dir():
            _copy(entry, destination / entry.name)
        else:
            (destination / entry.name).write_bytes(entry.read_bytes())


def write_files(base: Path, files: Mapping[str, str]) -> None:
    """Scenario paths are repository-relative; one that climbs out of `base` is refused."""
    root = base.resolve()
    for name, text in files.items():
        target = (root / name).resolve()
        if root not in target.parents:
            raise ValueError(f"{name!r} is outside the repository")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


@dataclass
class SimRepo:
    root: Path
    remote: Path  # bare
    clone: Path  # what `l4` runs in
    git: Git  # on the clone
    keep: bool = False
    _ticks: int = field(default=0, repr=False)
    _human: Git | None = field(default=None, repr=False)

    @classmethod
    def create(cls, fixture: str, *, root: Path | None = None, keep: bool = False) -> "SimRepo":
        """`root` defaults to a fresh `l4-sim-*` directory under the system temp directory."""
        seed = fixture_root(fixture).joinpath("repo")
        base = Path(tempfile.mkdtemp(prefix="l4-sim-")) if root is None else root
        base.mkdir(parents=True, exist_ok=True)
        remote, clone = base / "remote.git", base / "clone"
        environ = {  # nothing of the developer's git setup (identity, hooks, aliases) leaks in
            "PATH": safe_path(os.environ),
            "HOME": str(base),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        git = Git(base, environ=environ)
        git.run("init", "--quiet", "--bare", "-b", BASE_BRANCH, str(remote))
        _copy(seed, clone)
        in_clone = git.at(clone)
        in_clone.run("init", "--quiet", "-b", BASE_BRANCH)
        repo = cls(base, remote, clone, in_clone, keep)
        repo._commit(in_clone, SEED, "seed: " + fixture)
        in_clone.run("remote", "add", "origin", str(remote))
        in_clone.run("push", "--quiet", "-u", "origin", BASE_BRANCH)
        return repo

    def _commit(self, git: Git, who: Identity, message: str) -> str:
        self._ticks += 1
        when = (EPOCH + timedelta(minutes=self._ticks)).strftime("%Y-%m-%dT%H:%M:%S +0000")
        git.env["GIT_AUTHOR_DATE"] = git.env["GIT_COMMITTER_DATE"] = when
        git.run("add", "-A")
        config = (*_GIT_CONFIG, ("user.name", who.name), ("user.email", who.email))
        git.run("commit", "--quiet", "--no-verify", "--no-gpg-sign", "--allow-empty", "-m", message, config=config)
        return git.run("rev-parse", "HEAD").stdout.strip()

    def human_commit(self, files: Mapping[str, str], message: str, branch: str = BASE_BRANCH) -> str:
        """A person pushes `files` to `branch` of the remote (their own clone, the harness's untouched)."""
        if self._human is None:
            self.git.run("clone", "--quiet", str(self.remote), str(self.root / "human"), check=True)
            self._human = self.git.at(self.root / "human")
        human = self._human
        human.run("fetch", "--quiet", "origin")
        start = f"origin/{branch}" if human.rev_parse(f"origin/{branch}") else f"origin/{BASE_BRANCH}"
        human.run("checkout", "--quiet", "-B", branch, start)
        write_files(human.repo, files)
        sha = self._commit(human, HUMAN, message)
        human.run("push", "--quiet", "origin", f"{branch}:{branch}")
        return sha

    def cleanup(self) -> None:
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)
