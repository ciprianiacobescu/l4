"""Final review fixes y3: a deleted plan file (#10), the PR head sha (#14), a unit folder that is not there (#4)."""

import hashlib

import pytest

from l4.forge.github import GitHubForge
from l4.forge.gitlab import GitLabForge
from l4.yolo.digest import MISSING, FolderMissing, RevisionMissing, unit_digest
from l4.yolo.plans import active_on, plan_files
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_ledger_world import sh

A = unit_id("a")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def state(world, plan_id="p1"):
    return fold_plan(plan_id, world.events(plan_id))


def drop_plan_file(world, name="p1"):
    sh(world.repo, "rm", "-q", f".l4/plans/{name}.json")
    sh(world.repo, "commit", "-qm", "drop plan")
    world.push_main()


# --- #10: the plan file of an activated plan is deleted ------------------------------------------------------------


def test_a_deleted_plan_file_stops_the_plan_with_inputs_changed_once(world):
    world.plan()
    world.activate()
    world.step({"a": world.snapshot("a", None)})
    drop_plan_file(world)
    n = len(world.events())
    world.step({"a": world.snapshot("a", "implementing")})
    new = world.events()[n:]
    assert [e.type for e in new] == ["plan.stopped"]
    assert new[0].data["reason"] == "inputs_changed" and new[0].data["unit"] == "plan"
    assert new[0].data["detail"] == "the plan file was deleted"
    assert state(world).status == "stopped"
    world.step({"a": world.snapshot("a", "implementing")})  # once: a stopped plan is not stopped again
    assert len(world.events()) == n + 1


def test_a_deleted_plan_file_stops_a_waiting_plan_too(world):
    world.plan()
    world.activate()
    world.seed(ev("plan.waiting", reason="unit_escalated", unit=A))
    drop_plan_file(world)
    world.step({"a": world.snapshot("a", "implementing")})
    assert state(world).status == "stopped" and state(world).stop_reason == "inputs_changed"


def test_a_restored_plan_file_does_not_revive_the_old_activation(world):
    world.plan()
    world.activate()
    drop_plan_file(world)
    world.step({"a": world.snapshot("a", "implementing")})
    sh(world.repo, "revert", "--no-edit", "HEAD")
    world.push_main()
    n = len(world.events())
    step = world.step({"a": world.snapshot("a", "implementing")})
    assert state(world).status != "active" and A not in step.allow
    assert "unit.dispatched" not in [e.type for e in world.events()[n:]]


def test_a_plan_that_is_not_activated_is_left_alone_when_its_file_is_deleted(world):
    world.plan()
    world.reviewed()
    drop_plan_file(world)
    n = len(world.events())
    world.step({"a": world.snapshot("a", None)})
    assert len(world.events()) == n and state(world).status == "reviewed"


def test_active_on_counts_a_plan_whose_file_is_gone(world):
    world.plan()
    world.activate()
    states = {"p1": state(world)}
    assert active_on(states, plan_files(world.repo), "main") is not None
    drop_plan_file(world)
    assert plan_files(world.repo) == []
    assert active_on(states, [], "main") is not None  # review #10: the ledger status counts, the file or not


def test_active_on_ignores_a_final_plan_without_a_file(world):
    world.plan()
    world.activate()
    world.seed(ev("plan.cancelled", by="a", reason="r"))
    assert active_on({"p1": state(world)}, [], "main") is None


# --- #14: the PR head sha --------------------------------------------------------------------------------------------


def test_github_maps_the_head_sha():
    data = {
        "number": 1, "html_url": "https://h/1", "title": "t", "state": "open",
        "head": {"ref": "b", "sha": "a" * 40}, "base": {"ref": "main"},
    }  # fmt: skip
    assert GitHubForge._pr(data).head_sha == "a" * 40
    del data["head"]["sha"]
    assert GitHubForge._pr(data).head_sha is None


def test_gitlab_maps_the_mr_sha_as_the_head():
    data = {
        "iid": 1, "web_url": "https://h/1", "title": "t", "state": "opened", "source_branch": "b",
        "target_branch": "main", "sha": "d" * 40,
    }  # fmt: skip
    assert GitLabForge._pr(data).head_sha == "d" * 40
    del data["sha"]
    assert GitLabForge._pr(data).head_sha is None


# --- old #4: a unit folder that is not there --------------------------------------------------------------------------


def test_a_unit_folder_that_is_not_there_raises_a_revision_missing(world):
    rev = sh(world.repo, "rev-parse", "HEAD")
    with pytest.raises(FolderMissing) as err:
        unit_digest(world.git, rev, "openspec/changes/gone")
    assert isinstance(err.value, RevisionMissing)
    assert unit_digest(world.git, rev, "openspec/changes/a") != hashlib.sha256(b"").hexdigest()[:16]


def test_a_merged_unit_whose_folder_moved_to_the_archive_does_not_stop_the_plan(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("unit.merged", unit=A, head="h" * 40))
    sh(world.repo, "mv", "openspec/changes/a", "openspec/archive-a")
    sh(world.repo, "commit", "-qm", "archive a")
    world.push_main()
    world.step({"a": world.snapshot("a", "merged")})
    assert state(world).status != "stopped"


def test_an_unmerged_unit_whose_folder_is_gone_is_a_change_not_a_crash(world):
    world.plan()
    world.activate()
    sh(world.repo, "rm", "-rq", "openspec/changes/a")
    sh(world.repo, "commit", "-qm", "drop a")
    world.push_main()
    world.step({"a": world.snapshot("a", "implementing")})
    s = state(world)
    assert s.status == "stopped" and s.stop_reason == "inputs_changed" and s.stop_unit == A
    assert MISSING not in s.digests.values()
