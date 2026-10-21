# ruff: noqa: F811
"""A merged MR counts as the unit's merge only when it was merged into the base branch (L4-YOLO-007, SCN-YOLO-13)."""

import logging

import pytest

from l4.ci.sweeper import Sweeper
from l4.postmerge import MergeDetector, PostMergeArchiver
from l4.specs.openspec import OpenSpecProvider
from l4.state.status import load_snapshot

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401
from ..archive.merged_world import MergedWorld
from ..forge.conftest import API, PROJECT, TOKEN, WEB  # noqa: F401


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab):
    return MergedWorld(tmp_path, raw, git_environ, gitlab).build()


def run_sweep(world: MergedWorld, run_id: str):
    app, forge = world.app(run_id), world.forge()
    archiver = PostMergeArchiver(world.cfg, app, world.git, forge, provider_for=world.provider_for)
    sweeper = Sweeper(app, world.cfg, world.git, forge, archiver, MergeDetector(world.git, base_branch="main"))
    provider = OpenSpecProvider(world.repo, world.environ)
    snaps = [load_snapshot(provider, world.git, ref, branch_prefix="l4/") for ref in provider.list_units()]
    return sweeper, sweeper.run(snaps), snaps


def test_a_pr_merged_into_another_branch_is_not_the_units_merge(world, gitlab, caplog):  # SCN-YOLO-13
    pr = world.forge().create_pr("l4/openspec/add-x", "release", "[l4] add-x: x", "b", draft=False)
    gitlab.merge(pr.number, world.merge_sha)
    with caplog.at_level(logging.WARNING):
        sweeper, actions, snaps = run_sweep(world, "r-20261005T1000Z-0001")
    assert [(a.what, a.detail) for a in actions] == [("misdirected", "merged into release, not the base main")]
    assert snaps[0].state.phase == "in_review"
    assert not any(mr["source_branch"].startswith("l4/archive/") for mr in gitlab.mrs.values())
    assert any("was merged into release, not the base main" in r.getMessage() for r in caplog.records)
    assert sweeper.misdirected == {"openspec:add-x": "merged into release, not the base main"}


def test_the_misdirected_merge_is_a_fact_of_the_unit_and_the_cause_of_status(world, gitlab):  # SCN-YOLO-13
    from l4.planner import facts_of
    from l4.state.next_step import reason

    pr = world.forge().create_pr("l4/openspec/add-x", "release", "[l4] add-x: x", "b", draft=False)
    gitlab.merge(pr.number, world.merge_sha)
    run_sweep(world, "r-20261005T1000Z-0001")
    provider = OpenSpecProvider(world.repo, world.environ)
    (ref,) = provider.list_units()
    state = load_snapshot(provider, world.git, ref, branch_prefix="l4/")
    assert state.state.phase == "in_review"
    assert (state.state.misdirected.merged_into, state.state.misdirected.base) == ("release", "main")
    assert reason(facts_of(state)) == "merged into release, not the base main"
    _, again, _ = run_sweep(world, "r-20261005T1100Z-0002")
    assert again == []  # said once: the fact is in the pending ledger


def test_a_pr_merged_into_the_base_still_counts(world, gitlab):
    world.merged_mr()
    sweeper, actions, _ = run_sweep(world, "r-20261005T1000Z-0001")
    assert [a.what for a in actions] == ["archive_opened"]
    assert sweeper.misdirected == {}
