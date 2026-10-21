"""The archive MR built with the real pinned OpenSpec (L4_LIVE=1): the fake provider of the unit tests is the model of
this, and this proves the model."""

import os

import pytest

from l4.postmerge import PostMergeArchiver
from l4.specs.openspec import OpenSpecProvider

from .merged_world import MergedWorld

pytestmark = pytest.mark.live


def test_the_real_cli_archive_changes_only_the_units_paths(tmp_path, raw, git_environ, gitlab):
    world = MergedWorld(tmp_path, raw, git_environ, gitlab).build()
    world.environ.update(L4_HOME=os.environ.get("L4_HOME", ""), PATH=os.environ["PATH"], HOME=os.environ["HOME"])
    if not world.environ["L4_HOME"]:
        del world.environ["L4_HOME"]
    world.merged_mr()
    archiver = PostMergeArchiver(world.cfg, world.app(), world.git, world.forge())
    result = archiver.open_archive_pr(world.ref())
    assert result.status == "opened", result.detail
    assert result.archived_as and result.archived_as.endswith("-add-x")
    assert isinstance(archiver._provider_for(tmp_path), OpenSpecProvider)
    paths = world.raw(world.origin, "diff", "--name-only", "--no-renames", "main..l4/archive/openspec/add-x").split()
    assert "openspec/specs/cap-add-x/spec.md" in paths
    assert all(
        p.startswith(("openspec/changes/add-x/", f"openspec/changes/archive/{result.archived_as}/", "openspec/specs/"))
        for p in paths
    )
