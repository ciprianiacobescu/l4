"""A symlink in the merged unit folder must not redirect the fold of the pending ledger (L4-STA-004)."""

import os

import pytest

from .merged_world import MergedWorld

ARCHIVE_BRANCH = "l4/archive/openspec/add-x"


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab):
    return MergedWorld(tmp_path, raw, git_environ, gitlab).build()


def commit_symlink(world: MergedWorld, link: str, outside) -> None:
    unit = world.repo / "openspec/changes/add-x"
    world.raw(world.repo, "rm", "-q", "-r", "-f", f"openspec/changes/add-x/{link}")
    (unit / link).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(str(outside), unit / link)
    world.raw(world.repo, "add", "-A")
    world.raw(world.repo, "commit", "-q", "-m", f"a merged MR that made {link} a symlink")
    world.raw(world.repo, "push", "-q", "origin", "main")
    world.merge_sha = world.raw(world.repo, "rev-parse", "HEAD").strip()
    world.merged_mr()


@pytest.mark.parametrize("link", [".l4", ".l4/ledger"])
def test_a_symlinked_ledger_folder_fails_the_archive_and_writes_nothing_outside(world, gitlab, tmp_path, link):
    outside = tmp_path / "outside-the-worktree"
    (outside / "ledger").mkdir(parents=True)
    commit_symlink(world, link, outside / "ledger" if link == ".l4/ledger" else outside)
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "failed" and "symlink" in result.detail
    assert list(outside.rglob("*.jsonl")) == []
    assert ARCHIVE_BRANCH not in world.remote_branches()
    assert len(gitlab.mrs) == 1  # the unit's own merged MR only
