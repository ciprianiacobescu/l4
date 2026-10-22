"""A bare origin and clones of it, for the plan ledger tests (no network, no model)."""

import os
import subprocess
from pathlib import Path

from l4.vcs.git import Git
from l4.yolo.model import PlanEvent


def sh(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=_env())
    return done.stdout.strip()


def _env() -> dict[str, str]:
    """No global or system config; a fixed identity, so a commit made here never depends on git guessing one from the
    user and host names (a CI runner's host name has no domain, and git refuses the guess)."""
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }


def make_origin(root: Path) -> Path:
    origin = root / "origin.git"
    origin.mkdir()
    sh(origin, "init", "--bare", "--quiet")
    return origin


def make_clone(root: Path, origin: Path, name: str) -> Git:
    path = root / name
    subprocess.run(["git", "clone", "--quiet", str(origin), str(path)], check=True, capture_output=True, env=_env())
    return Git(path, environ=_env())


def ev(kind: str, **data) -> PlanEvent:
    return PlanEvent(type=kind, at="2026-10-14T10:00:00Z", data=data)
