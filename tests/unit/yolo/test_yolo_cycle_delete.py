"""Merged branches are deleted unless configured to stay (squash-and-delete D6, D7; L4-YOLO-033): SCN-YOLO-82 (the unit
branch goes after the merge, its head kept), SCN-YOLO-83 (a person's push after the merge keeps it), SCN-YOLO-84 (the
branches of earlier merges are cleaned, five at most per step), SCN-YOLO-85 (`delete_branches: false`)."""

import pytest

from l4.forge.local import LocalForge
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, MergingForge, ev, unit_id
from .yolo_ledger_world import sh
from .yolo_review_world import make_cfg

A, B, C = unit_id("a"), unit_id("b"), unit_id("c")


class Person(MergingForge):
    """The merging local forge; `after` runs right after the merge call (a person pushing to the merged branch)."""

    after = None

    def merge_pr(self, number, *, sha, title, message):
        call = super().merge_pr(number, sha=sha, title=title, message=message)
        if self.after is not None:
            self.after()
        return call


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def kinds(world, kind):
    return [e.data for e in world.events() if e.type == kind]


def remote(world, ref):
    return sh(world.origin, "for-each-ref", "--format=%(objectname)", ref)


def ready(world, forge=None):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge = forge or Person(origin=world.origin)
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    return head, {"a": world.in_review("a", head)}


def test_scn_yolo_82_the_unit_branch_is_deleted_after_the_merge_and_its_head_is_kept(world):
    head, snaps = ready(world)
    world.step(snaps)
    assert remote(world, "refs/l4/merged/openspec/a") == head
    assert remote(world, "refs/heads/l4/openspec/a") == ""
    assert world.git.rev_parse("refs/remotes/origin/l4/openspec/a") is None  # the tracking ref went with it
    assert kinds(world, "unit.branch_deleted") == [{"unit": A, "branch": "l4/openspec/a", "head": head}]
    assert fold_plan("p1", world.events()).integrated[A]  # the plan went on


def test_scn_yolo_82_a_fast_forward_deletes_once_the_forge_shows_the_pull_request_merged(world):
    head, snaps = ready(world)
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        yolo={"merge": {"method": "fast-forward"}},
    )
    world.step(snaps)
    assert remote(world, "refs/heads/l4/openspec/a") == "" and remote(world, "refs/l4/merged/openspec/a") == head


def test_a_fast_forward_whose_pull_request_the_forge_does_not_show_merged_keeps_the_branch_until_it_does(world):
    head, snaps = ready(world, LocalForge(origin=world.origin))  # open until a person (or the forge) merges it
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        yolo={"merge": {"method": "fast-forward"}},
    )
    world.step(snaps)
    assert world.tip() == head and remote(world, "refs/heads/l4/openspec/a") == head
    assert remote(world, "refs/l4/merged/openspec/a") == "" and not kinds(world, "unit.branch_deleted")
    world.forge.merge(1)  # the forge catches up
    world.step({"a": world.in_review("a", head)})
    assert remote(world, "refs/heads/l4/openspec/a") == "" and remote(world, "refs/l4/merged/openspec/a") == head
    assert len(kinds(world, "unit.branch_deleted")) == 1


def test_scn_yolo_83_a_branch_a_person_pushed_to_after_the_merge_stays(world):
    head, snaps = ready(world)
    moved = []

    def person():
        moved.append(sh(world.origin, "commit-tree", f"{head}^{{tree}}", "-p", head, "-m", "a person's commit"))
        sh(world.origin, "update-ref", "refs/heads/l4/openspec/a", moved[0], head)

    world.forge.after = person
    world.step(snaps)
    assert remote(world, "refs/heads/l4/openspec/a") == moved[0]
    kept = kinds(world, "unit.branch_kept")
    assert len(kept) == 1 and kept[0]["unit"] == A and kept[0]["branch"] == "l4/openspec/a" and kept[0]["reason"]
    assert not kinds(world, "unit.branch_deleted")
    assert fold_plan("p1", world.events()).status != "stopped"


def merged_unit(world, name, *, head_moved=False):
    """An integrated unit of the plan whose unit and archive branches are on origin and whose pull requests merged."""
    head = world.unit_branch(name)
    world.forge.create_pr(f"l4/openspec/{name}", "main", f"[l4] {name}", "b", draft=False)
    pr = max(p for p in world.forge._prs)
    world.forge.merge(pr)
    archive = f"l4/archive/openspec/{name}"
    commit = sh(world.origin, "commit-tree", "refs/heads/main^{tree}", "-p", "refs/heads/main", "-m", "archive")
    sh(world.origin, "update-ref", f"refs/heads/{archive}", commit)
    world.forge.create_pr(archive, "main", f"[l4] archive {name}", "b", draft=False)
    world.forge.merge(max(p for p in world.forge._prs))
    world.seed(
        ev("unit.dispatched", unit=unit_id(name), run="r0"),
        ev("unit.merged", unit=unit_id(name), head=head, pr=pr, merge_commit=head, method="fast-forward"),
        ev("unit.integrated", unit=unit_id(name), revision=head),
    )
    if head_moved:
        later = sh(world.origin, "commit-tree", f"{head}^{{tree}}", "-p", head, "-m", "after the merge")
        sh(world.origin, "update-ref", f"refs/heads/l4/openspec/{name}", later, head)
    return head


def test_scn_yolo_84_branches_of_units_merged_before_the_upgrade_are_cleaned(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    world.plan(deps={})
    world.activate()
    world.forge = MergingForge(origin=world.origin)
    heads = {n: merged_unit(world, n, head_moved=n == "c") for n in "abc"}
    world.step()
    for name in "ab":
        assert remote(world, f"refs/heads/l4/openspec/{name}") == ""
        assert remote(world, f"refs/heads/l4/archive/openspec/{name}") == ""
        assert remote(world, f"refs/l4/merged/openspec/{name}") == heads[name]
    assert remote(world, "refs/heads/l4/openspec/c") != "" and remote(world, "refs/l4/merged/openspec/c") == ""
    assert remote(world, "refs/heads/l4/archive/openspec/c") == ""  # its archive branch was untouched by anyone
    deleted = {d["branch"] for d in kinds(world, "unit.branch_deleted")}
    assert {"l4/openspec/a", "l4/archive/openspec/a", "l4/openspec/b", "l4/archive/openspec/b"} <= deleted


def test_a_step_deletes_five_branches_at_most(tmp_path):
    names = ("a", "b", "c")
    world = CycleWorld(tmp_path, units=names)
    world.plan(deps={})
    world.activate()
    world.forge = MergingForge(origin=world.origin)
    for n in names:
        merged_unit(world, n)
    world.step()
    assert len(kinds(world, "unit.branch_deleted")) == 5  # six branches, five deletes
    world.step()
    assert len(kinds(world, "unit.branch_deleted")) == 6


def test_scn_yolo_85_keeping_the_branches_stays_an_option(world):
    head, snaps = ready(world)
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        yolo={"merge": {"delete_branches": False}},
    )
    world.step(snaps)
    assert remote(world, "refs/heads/l4/openspec/a") == head
    assert remote(world, "refs/l4/merged/openspec/a") == ""
    assert not kinds(world, "unit.branch_deleted") and not kinds(world, "unit.branch_kept")
