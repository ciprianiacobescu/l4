import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from l4.vcs.git import Git
from l4.vcs.repokey import repository_key
from l4.vcs.trailers import CommitTrailers


@pytest.fixture
def git_environ(tmp_path: Path) -> dict[str, str]:
    """A git environment that cannot see the developer's global config or home. Its one global file is the session's
    (`tests/conftest.py`): a committer identity and a default branch, the same on every machine, so a commit made
    through `Git` needs neither the developer's configuration nor git's guess from the user and host names."""
    home = tmp_path / "githome"
    home.mkdir()
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.environ["GIT_CONFIG_GLOBAL"],
    }


def raw_git(cwd: Path, environ: dict[str, str], *args: str) -> str:
    """Plain git for test setup and inspection; production code never does this (it uses Git)."""
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, env=environ, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout


@pytest.fixture
def raw(git_environ: dict[str, str]) -> Callable[..., str]:
    def run(cwd: Path, *args: str) -> str:
        return raw_git(cwd, git_environ, *args)

    return run


@pytest.fixture
def trailers() -> CommitTrailers:
    return CommitTrailers(unit="openspec:add-login", run_id="r-20261003T1312Z-7f3a", iteration=3, phase="implementing")


@pytest.fixture
def make_repo(tmp_path: Path, raw: Callable[..., str]) -> Callable[..., Path]:
    """A repository with one commit on `main`, optionally with a bare remote `origin` that has main pushed."""

    def make(name: str = "repo", *, remote: bool = False) -> Path:
        repo = tmp_path / name
        repo.mkdir()
        raw(repo, "init", "-q")
        (repo / "README.md").write_text("hello\n")
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "init")
        if remote:
            bare = tmp_path / f"{name}-origin.git"
            raw(tmp_path, "init", "-q", "--bare", str(bare))
            raw(repo, "remote", "add", "origin", str(bare))
            raw(repo, "push", "-q", "origin", "main")
            raw(repo, "fetch", "-q", "origin")
        return repo

    return make


@pytest.fixture
def git_for(git_environ: dict[str, str]) -> Callable[[Path], Git]:
    return lambda repo: Git(repo, environ=git_environ)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "py_tdd"
UNIT = "openspec:add-discount-codes"

# stands in for `uv sync --frozen`: it creates `.venv/bin/python`, a launcher for the interpreter running the tests,
# so that the gate command is the one the prompts name and no network is needed
MKVENV = textwrap.dedent(
    """\
    import os, stat, sys
    os.makedirs(".venv/bin", exist_ok=True)
    path = ".venv/bin/python"
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\\nexec %s \\"$@\\"\\n" % sys.argv[1])
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    """
)
TEST_COMMAND = ".venv/bin/python -m pytest -p no:cacheprovider -o junit_family=xunit1 --junitxml=.l4-out/junit.xml"


@dataclass
class TddRepo:
    repo: Path
    environ: dict[str, str]
    cache: Path
    setup_script: Path
    origin: Path

    @property
    def key(self) -> str:
        """The repository key of the checkout (`l4.vcs.repokey`): part of every worktree and lock path."""
        return repository_key(self.repo, self.environ)

    @property
    def setup_command(self) -> str:
        return f"{sys.executable} {self.setup_script} {sys.executable}"

    def config(
        self,
        *,
        implementer: dict | None = None,
        sandbox: dict | None = None,
        judge_vendor: str = "other",
        clarifier: dict | None = None,
        roles: dict | None = None,
        profiles: dict | None = None,
        observability: dict | None = None,
        availability: dict | None = None,
        ci: dict | None = None,
        **gates: object,
    ) -> str:
        """A `.l4/config.yaml` for the fake adapter: no sandbox, a venv launcher instead of `uv sync`."""
        import yaml

        body = {
            "version": 1,
            "sandbox": sandbox or {"mode": "none", "allow_none": True},
            "profiles": {
                "impl": {"adapter": "fake", "vendor": "fakeco"},
                "judge": {"adapter": "fake", "vendor": judge_vendor},
                **(profiles or {}),
            },
            "roles": {"implementer": ["impl"], "judges": ["judge"], **(roles or {})},
            "gates": {"setup": [self.setup_command], "test": {"command": TEST_COMMAND}, **gates},
            "implementer": implementer or {},
            # M1.6: these fixtures test the lifecycle, not the evidence; a one-scenario unit whose second branch no
            # test runs would otherwise hold for diff coverage (tests/unit/verifier/test_ladder_evidence*.py cover it)
            "verifier": {"evidence": {"diff_coverage": {"mode": "off"}}},
            **({"clarifier": clarifier} if clarifier else {}),
            **({"observability": observability} if observability else {}),
            **({"availability": availability} if availability else {}),
            **({"ci": ci} if ci else {}),
        }
        return yaml.safe_dump(body)

    def write_config(
        self,
        *,
        implementer: dict | None = None,
        sandbox: dict | None = None,
        judge_vendor: str = "other",
        clarifier: dict | None = None,
        roles: dict | None = None,
        profiles: dict | None = None,
        observability: dict | None = None,
        availability: dict | None = None,
        ci: dict | None = None,
        **gates: object,
    ) -> None:
        (self.repo / ".l4").mkdir(exist_ok=True)
        text = self.config(
            implementer=implementer, sandbox=sandbox, judge_vendor=judge_vendor, clarifier=clarifier, roles=roles,
            profiles=profiles, observability=observability, availability=availability, ci=ci, **gates,
        )
        (self.repo / ".l4" / "config.yaml").write_text(text)


@pytest.fixture
def tdd_repo(tmp_path: Path, git_environ: dict[str, str], raw: Callable[..., str]) -> TddRepo:
    """The py_tdd fixture as a git repository on `main` with a bare `origin` that has main pushed."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    raw(repo, "init", "-q")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "fixture")
    bare = tmp_path / "origin.git"
    raw(tmp_path, "init", "-q", "--bare", str(bare))
    raw(repo, "remote", "add", "origin", str(bare))
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "fetch", "-q", "origin")
    script = tmp_path / "mkvenv.py"
    script.write_text(MKVENV)
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache"), "L4_HOME": str(tmp_path / "l4home")}
    return TddRepo(repo, environ, tmp_path / "cache", script, bare)
