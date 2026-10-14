# ruff: noqa: F811
"""The sweep and delivery plans (L4-YOLO-009, SCN-YOLO-19): the archive merge request of a unit of an active
`merge: auto` plan is merged by the harness with the fast-forward guard, every other archive merge request is left to a
person, and only an archive merge request to the base branch blocks the next archive."""

import logging
import stat

import pytest

from l4.ci.sweeper import Sweeper
from l4.postmerge import MergeDetector
from l4.specs.openspec import OpenSpecProvider
from l4.state.pending import read_pending
from l4.state.status import load_snapshot

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401
from ..archive.merged_world import MergedWorld
from ..forge.conftest import API, PROJECT, TOKEN, WEB  # noqa: F401

UNIT = "openspec:add-x"
ARCHIVE = "l4/archive/openspec/add-x"


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab):
    return MergedWorld(tmp_path, raw, git_environ, gitlab).build()


def sweep(world: MergedWorld, run_id: str, *, auto=()):
    app, forge = world.app(run_id), world.forge()
    archiver = world.archiver()
    sweeper = Sweeper(
        app, world.cfg, world.git, forge, archiver, MergeDetector(world.git, base_branch="main"), auto_units=auto
    )
    provider = OpenSpecProvider(world.repo, world.environ)
    snaps = [load_snapshot(provider, world.git, ref, branch_prefix="l4/") for ref in provider.list_units()]
    return sweeper.run(snaps)


def main_tip(world) -> str:
    return world.raw(world.origin, "rev-parse", "refs/heads/main").strip()


def events(world) -> list[str]:
    ref = "refs/l4/locks/openspec/add-x"
    world.git.fetch("origin", refspecs=(f"+{ref}:{ref}",))
    return [e.type for e in read_pending(world.git, ref).events]


def test_scn_yolo_19_the_archive_pr_of_a_unit_of_an_auto_plan_is_merged_by_the_harness(world):
    world.merged_mr()
    before = main_tip(world)
    actions = sweep(world, "r-20261005T1000Z-0001", auto={UNIT})
    assert [a.what for a in actions] == ["archive_merged"]
    archive = world.raw(world.origin, "rev-parse", f"refs/heads/{ARCHIVE}").strip()
    assert main_tip(world) == archive  # the tip is the archive branch head
    assert world.raw(world.origin, "log", "-1", "--format=%P", "refs/heads/main").split() == [before]  # fast-forward
    assert {"archive.opened", "archive.merged"} <= set(events(world))


def test_a_unit_that_is_not_in_an_active_auto_plan_is_never_merged_by_the_harness(world):
    world.merged_mr()
    before = main_tip(world)
    actions = sweep(world, "r-20261005T1000Z-0001")
    assert [a.what for a in actions] == ["archive_opened"] and main_tip(world) == before
    assert "archive.merged" not in events(world)


def test_an_existing_archive_pr_is_merged_on_a_later_sweep(world):
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")  # opened by a sweep outside any plan
    before = main_tip(world)
    actions = sweep(world, "r-20261005T1100Z-0002", auto={UNIT})
    assert [a.what for a in actions] == ["archive_merged"] and main_tip(world) != before


def test_a_refused_archive_push_is_archive_failed_and_the_pr_stays(world):
    world.merged_mr()
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do\n"
        '  if [ "$ref" = refs/heads/main ]; then echo "GH006: Protected branch update failed" >&2; exit 1; fi\n'
        "done\n"
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    before = main_tip(world)
    actions = sweep(world, "r-20261005T1000Z-0001", auto={UNIT})
    assert [a.what for a in actions] == ["archive_failed"]
    assert "Protected branch update failed" in actions[0].detail and main_tip(world) == before
    assert "archive.failed" in events(world)
    assert any(mr["source_branch"] == ARCHIVE for mr in world.gitlab.mrs.values())


def test_an_archive_pr_to_another_base_does_not_block_the_next_archive(world, caplog):
    world.merged_mr()
    other = world.forge().create_pr("l4/archive/openspec/old", "release", "[l4] archive old", "b", draft=False)
    with caplog.at_level(logging.WARNING):
        actions = sweep(world, "r-20261005T1000Z-0001")
    assert [a.what for a in actions] == ["archive_opened"]  # not archive_pending
    said = [r.getMessage() for r in caplog.records if f"!{other.number}" in r.getMessage()]
    assert len(said) == 1 and "aimed at release, not the base main" in said[0]


def test_an_archive_pr_to_the_base_still_blocks_one_at_a_time(world):
    world.merged_mr()
    world.forge().create_pr("l4/archive/openspec/old", "main", "[l4] archive old", "b", draft=False)
    actions = sweep(world, "r-20261005T1000Z-0001")
    assert [a.what for a in actions] == ["archive_pending"]
