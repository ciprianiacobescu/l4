from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.state.ledger import LedgerWriter
from l4.vcs.git import BOT_IDENTITY, Git

UNIT_REL = Path("openspec/changes/add-x")
BRANCH = "l4/openspec/add-x"


@dataclass
class UnitRepo:
    repo: Path
    git: Git
    environ: dict[str, str]

    @property
    def unit_dir(self) -> Path:
        return self.repo / UNIT_REL

    def write_ledger(self, base: Path, *events: tuple[str, dict], run_id: str = "r-20261003T1312Z-7f3a") -> None:
        """Write a ledger for the unit under `base` (a checkout root): run.started, the events, run.finished."""
        writer = LedgerWriter.open(base / UNIT_REL, "openspec:add-x", run_id, redactor=Redactor({}))
        for event_type, data in events:
            writer.append(event_type, **data)
        writer.finish(0)

    def push_unit_branch(self, change: Callable[[Path], None], trailers) -> None:
        """Commit `change(repo)` on the unit branch, push it, return to main and forget the local branch."""
        self.git.run("checkout", "-q", "-b", BRANCH)
        change(self.repo)
        self.git.run("add", "-A")
        self.git.commit("checkpoint", trailers, BOT_IDENTITY)
        self.git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
        self.git.run("checkout", "-q", "main")
        self.git.run("branch", "-q", "-D", BRANCH)
        self.git.fetch("origin")


@pytest.fixture
def unit_repo(make_repo, git_for, git_environ, trailers) -> UnitRepo:
    repo = make_repo(remote=True)
    git = git_for(repo)
    (repo / UNIT_REL).mkdir(parents=True)
    (repo / UNIT_REL / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 first\n- [ ] 1.2 second\n")
    git.run("add", "-A")
    git.commit("add the change", trailers, BOT_IDENTITY)
    git.push("origin", ["HEAD:refs/heads/main"])
    return UnitRepo(repo, git, git_environ)
