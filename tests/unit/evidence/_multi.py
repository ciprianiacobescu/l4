"""Builds the git history of `tests/fixtures/py_multi`: a base commit, then per unit a spec commit and an
implementation range (a red commit with the tests, a green commit with the code) carrying `L4-Unit` trailers."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "py_multi"
RUN_ID = "20261004T000000Z-0001"
PINNED_DATE = "2026-10-04T00:00:00+00:00"  # the root commit sha is the S1 project key: it must not depend on the clock


@dataclass(frozen=True)
class UnitHistory:
    name: str
    id: str  # `openspec:<name>`
    base: str  # the commit after the unit's spec was added: the verifier's base
    red: str
    head: str  # the green commit
    spec_dir: str  # `openspec/changes/<name>`


def _overlay(source: Path, repo: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, repo, dirs_exist_ok=True)


def build_repo(repo: Path, *, git: Git | None = None, units: int = 8) -> tuple[Git, list[UnitHistory]]:
    """`repo` must not exist yet. Returns the Git handle and the first `units` unit histories in order."""
    shutil.copytree(FIXTURE / "base", repo)
    git = git or Git(repo)
    git = git.at(repo)
    git.env.update(GIT_AUTHOR_DATE=PINNED_DATE, GIT_COMMITTER_DATE=PINNED_DATE)
    git.run("init", "--quiet", "--initial-branch=main")
    git.run("add", "-A")
    git.commit("base: shop and inventory", CommitTrailers("base", RUN_ID, 1, "planning"))
    out: list[UnitHistory] = []
    for folder in sorted((FIXTURE / "units").iterdir())[:units]:
        name = folder.name.split("-", 1)[1]
        unit_id = f"openspec:{name}"
        _overlay(folder / "spec", repo)
        git.run("add", "-A")
        git.commit(f"spec: {name}", CommitTrailers(unit_id, RUN_ID, 1, "planning"))
        base = git.rev_parse("HEAD")
        red = green = ""
        for phase, tdd in (("red", "red"), ("green", "green")):
            _overlay(folder / phase, repo)
            git.run("add", "-A")
            trailers = CommitTrailers(unit_id, RUN_ID, 1, "implementing", task="1.1", tdd=tdd, step=f"1.1/{phase}/1")
            sha = git.commit(f"{phase}: {name}", trailers)
            red, green = (sha, green) if phase == "red" else (red, sha)
        assert base is not None
        out.append(UnitHistory(name, unit_id, base, red, green, f"openspec/changes/{name}"))
    return git, out
