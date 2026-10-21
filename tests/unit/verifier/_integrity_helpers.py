"""A throw-away git repository for the integrity checks: commits with harness trailers, and the context to check."""

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from l4.config.schema import L4Config
from l4.specs.base import Task
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git
from l4.verifier.integrity import IntegrityContext

from ..conftest import raw_git

UNIT = "openspec:add-thing"
UNIT_DIR = "openspec/changes/add-thing"
STAMP = datetime(2026, 10, 4, tzinfo=UTC)


def task(key: str, title: str = "Do the thing", *, done: bool = True) -> Task:
    return Task(key, key, title, done, "x" if done else " ", 0, 1, 0)


def event(kind: str, seq: int, **data: object) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-20261004T0000Z-aaaa", UNIT, seq, kind, data)


@dataclass
class Repo:
    path: Path
    environ: dict[str, str]
    events: list[LedgerEvent] = field(default_factory=list)

    def git(self, *args: str) -> str:
        return raw_git(self.path, self.environ, *args)

    def write(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    def delete(self, *paths: str) -> None:
        for rel in paths:
            (self.path / rel).unlink()

    def commit(
        self, message: str = "work", *, task: str | None = None, tdd: str | None = None, unit: str = UNIT
    ) -> str:
        """A commit by the bot identity with the harness's trailers (per-commit attribution reads authorship: M1.9)."""
        self.git("add", "-A")
        trailers = [f"--trailer=L4-Unit: {unit}", "--trailer=L4-Run: r-1", "--trailer=L4-Iteration: 1"]
        trailers.append("--trailer=L4-Phase: implementing")
        if task:
            trailers.append(f"--trailer=L4-Task: {task}")
        if tdd:
            trailers.append(f"--trailer=L4-TDD: {tdd}")
        self.git("-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid", "commit", "-q",
                 "--allow-empty", "-m", message, *trailers)  # fmt: skip
        return self.git("rev-parse", "HEAD").strip()

    def commit_as_human(self, message: str = "a person's fix") -> str:
        """A commit by a person: not the bot, no `L4-Run` trailer."""
        self.git("add", "-A")
        self.git("-c", "user.name=Ann", "-c", "user.email=ann@example.invalid", "commit", "-q", "--allow-empty",
                 "-m", message)  # fmt: skip
        return self.git("rev-parse", "HEAD").strip()

    def commit_as_harness(self, message: str, *, phase: str) -> str:
        """A commit by the bot identity with the harness's trailers (`phase`: implementing, lessons, ...)."""
        self.git("add", "-A")
        trailers = ["--trailer=L4-Run: r-1", f"--trailer=L4-Phase: {phase}"]
        self.git("-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid", "commit", "-q",
                 "--allow-empty", "-m", message, *trailers)  # fmt: skip
        return self.git("rev-parse", "HEAD").strip()

    def copy_tree(self, source: Path) -> None:
        if source.is_dir():
            shutil.copytree(
                source, self.path, dirs_exist_ok=True, copy_function=shutil.copy
            )  # new mtimes: no racy index

    def context(
        self, base: str, head: str, *, tasks: list[tuple[str, Task]] | None = None, cfg=None
    ) -> IntegrityContext:
        return IntegrityContext(
            Git(self.path, environ=self.environ), cfg or L4Config(), base, head, self.events,
            tasks if tasks is not None else [], [UNIT_DIR], UNIT,
        )  # fmt: skip


def new_repo(tmp_path: Path, environ: dict[str, str], base_files: dict[str, str] | None = None) -> tuple[Repo, str]:
    """A repository whose first commit holds `base_files`; returns it with that commit as the base."""
    path = tmp_path / "work"
    path.mkdir()
    repo = Repo(path, environ)
    repo.git("init", "-q", "-b", "main")
    repo.write(base_files or {"README.md": "hello\n"})
    return repo, repo.commit("base")
