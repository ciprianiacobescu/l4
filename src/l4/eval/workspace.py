"""A cell's workspace (L4-EVAL-005, plan D2): a fresh bare mirror of the seeded base and a fresh clone of it.

Nothing is shared between two calls (no `.git`, no object store), and the seed commit has a fixed message, author,
committer and dates, so the same inputs and identity give the same hash. Only what the agent may see is committed: the
base project and the unit's OpenSpec change. The expected verdicts, the reference implementation and the hidden check
never leave the seed directory.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from l4.eval.seeds import NOT_SEEDS, SeedSet, SeedUnit

SEED_DATE = "2026-10-07T00:00:00+00:00"
_NOT_COPIED_FROM_UNIT = ("reference", "expected.json")
_CACHES = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", ".l4-out", ".ruff_cache", "*.pyc", *NOT_SEEDS)


@dataclass(frozen=True)
class Identity:
    name: str
    email: str


@dataclass(frozen=True)
class Workspace:
    root: Path
    origin: Path  # the bare mirror
    repo: Path  # the clone the cell runs in


def _env(identity: Identity | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.environ.get("HOME", "/"),
    }  # fmt: skip
    if identity is not None:
        env.update(
            GIT_AUTHOR_NAME=identity.name, GIT_AUTHOR_EMAIL=identity.email, GIT_AUTHOR_DATE=SEED_DATE,
            GIT_COMMITTER_NAME=identity.name, GIT_COMMITTER_EMAIL=identity.email, GIT_COMMITTER_DATE=SEED_DATE,
        )  # fmt: skip
    return env


def _git(cwd: Path, *args: str, identity: Identity | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=_env(identity), capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed in the eval workspace: {done.stderr.strip()[:300]}")
    return done.stdout.strip()


def default_identity(cwd: Path | None = None) -> Identity:
    """The committer identity of the repository the harness runs from (its git config), else a fixed one."""
    env = {**os.environ}
    for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"):
        env.pop(key, None)

    def read(key: str) -> str:
        done = subprocess.run(["git", "config", key], cwd=cwd, env=env, capture_output=True, text=True, check=False)
        return done.stdout.strip() if done.returncode == 0 else ""

    return Identity(read("user.name") or "l4-eval", read("user.email") or "l4-eval@invalid")


def make_workspace(seeds: SeedSet, unit: SeedUnit, directory: Path, *, identity: Identity | None = None) -> Workspace:
    """`directory` is emptied and rebuilt: `origin.git`, `repo/` (a clone with the identity set for the harness)."""
    identity = identity or default_identity()
    directory = Path(directory)
    if directory.exists():
        shutil.rmtree(directory)
    seed = directory / "_seed"
    origin, repo = directory / "origin.git", directory / "repo"
    seed.mkdir(parents=True)
    shutil.copytree(seeds.base, seed, ignore=_CACHES, dirs_exist_ok=True)
    change = seed / "openspec" / "changes" / unit.id
    shutil.copytree(
        unit.path, change, ignore=shutil.ignore_patterns(*_NOT_COPIED_FROM_UNIT, "__pycache__", "*.pyc", *NOT_SEEDS)
    )  # fmt: skip
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "add", "-A")
    _git(seed, "-c", "commit.gpgsign=false", "commit", "-q", "-m", f"seed: {unit.id}", identity=identity)
    _git(directory, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(seed, "push", "-q", str(origin), "main")
    shutil.rmtree(seed)
    _git(directory, "clone", "-q", str(origin), str(repo))
    _git(repo, "config", "user.name", identity.name)
    _git(repo, "config", "user.email", identity.email)
    return Workspace(directory, origin, repo)
