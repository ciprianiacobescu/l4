"""A merged unit's fix units are archived with it, in one commit, parent first (M1.3 line 39)."""

import json

import pytest

from .merged_world import MergedWorld

ARCHIVE_BRANCH = "l4/archive/openspec/add-x"
DONE = "# Tasks\n\n## 1. Fix\n\n- [x] 1.1 something (F-aaaaaaaa)\n"
DELTA = (
    "## Purpose\nRegression scenarios for the add-x capability found by the verifier in add-x.\n\n"
    "## ADDED Requirements\n\n### Requirement: Average \N{EM DASH} regression 1\nIt SHALL hold.\n\n"
    "#### Scenario: Empty\n- **WHEN** empty\n- **THEN** zero\n"
)


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab) -> MergedWorld:
    return MergedWorld(tmp_path, raw, git_environ, gitlab).build()


def add_fix_unit(world: MergedWorld, ordinal: int, *, delta: bool = False) -> None:
    folder = world.repo / "openspec" / "changes" / f"add-x-fix-{ordinal}"
    (folder / ".l4").mkdir(parents=True)
    (folder / "tasks.md").write_text(DONE)
    marker = {"schema": "l4/fix-unit@1", "parent": "openspec:add-x", "round": ordinal, "findings": ["F-aaaaaaaa"]}
    (folder / ".l4" / "fix.json").write_text(json.dumps(marker))
    if delta:
        (folder / "specs" / "cap-fix").mkdir(parents=True)
        (folder / "specs" / "cap-fix" / "spec.md").write_text(DELTA)
    world.raw(world.repo, "add", "-A")
    world.raw(world.repo, "commit", "-q", "-m", f"fix unit {ordinal}")
    world.raw(world.repo, "push", "-q", "origin", "main")
    world.raw(world.repo, "fetch", "-q", "origin")


def test_the_parent_and_its_fix_units_are_archived_in_one_commit(world):
    add_fix_unit(world, 2, delta=True)
    add_fix_unit(world, 1)
    world.merged_mr()
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "opened" and result.archived_as == "2026-10-05-add-x"
    (sha,) = world.archive_commits(ARCHIVE_BRANCH)
    listing = world.raw(world.origin, "diff", "--name-status", "--no-renames", f"main..{ARCHIVE_BRANCH}")
    paths = {line.split("\t")[1]: line.split("\t")[0] for line in listing.splitlines()}
    archive = "openspec/changes/archive/"
    for name in ("add-x", "add-x-fix-1", "add-x-fix-2"):
        assert paths[f"{archive}2026-10-05-{name}/tasks.md"] == "A"
        assert paths[f"openspec/changes/{name}/tasks.md"] == "D"
    assert paths["openspec/specs/cap-fix/spec.md"] == "A" and paths["openspec/specs/cap-add-x/spec.md"] == "A"
    assert (
        world.raw(world.origin, "rev-parse", f"{sha}^").strip() == world.raw(world.origin, "rev-parse", "main").strip()
    )


def test_a_fix_unit_that_is_not_done_stops_the_archive(world):
    add_fix_unit(world, 1)
    (world.repo / "openspec" / "changes" / "add-x-fix-1" / "tasks.md").write_text("- [ ] 1.1 open (F-aaaaaaaa)\n")
    world.raw(world.repo, "commit", "-q", "-am", "reopen")
    world.raw(world.repo, "push", "-q", "origin", "main")
    world.merged_mr()
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "failed" and "add-x-fix-1" in result.detail
    assert world.remote_branches().count(ARCHIVE_BRANCH) == 0


def test_a_unit_with_no_fix_units_archives_as_before(world):
    world.merged_mr()
    assert world.archiver().open_archive_pr(world.ref()).status == "opened"
