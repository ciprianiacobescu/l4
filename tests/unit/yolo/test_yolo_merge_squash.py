"""The squash path of the guarded merge (squash-and-delete D3, D4, D5; L4-YOLO-032) against a bare origin and the local
forge: SCN-YOLO-76 (squash by default), SCN-YOLO-78 (fast-forward stays an option), SCN-YOLO-79 (a refusal),
SCN-YOLO-80 (a head that moved), SCN-YOLO-81 (a target that moved during the merge)."""

import logging

import pytest

from l4.config.schema import L4Config
from l4.forge.base import MergeCall
from l4.forge.local import LocalForge
from l4.yolo.merge import confirm_merged, merge_guarded, squash_message

from .test_yolo_merge_guard import BRANCH, UNIT, World

RUN = "r-20261014T1000Z-aaaa"


@pytest.fixture
def world(tmp_path, raw, git_environ) -> World:
    made = World(tmp_path, raw, git_environ)
    made.cfg = L4Config.model_validate({"version": 1})  # the default method: squash
    return made


class ScriptedForge(LocalForge):
    """A local forge whose merge call answers as scripted, or acts first (a person pushes before the forge squashes)."""

    def __init__(self, origin, answer: MergeCall | None = None, before=None) -> None:
        super().__init__(origin=origin)
        self.answer, self.before = answer, before

    def merge_pr(self, number, *, sha, title, message):
        if self.before is not None:
            self.before()
        if self.answer is not None:
            self._log("merge", number)
            return self.answer
        return super().merge_pr(number, sha=sha, title=title, message=message)


def forge_for(world: World, title: str = "[l4] x [skip ci]", **kw) -> ScriptedForge:
    forge = ScriptedForge(world.origin, **kw)
    forge.create_pr(BRANCH, "main", title, "body", draft=False)
    return forge


def merge(world: World, forge, **kw):
    return merge_guarded(world.app, world.cfg, world.git, forge, world.snapshot(), sleep=lambda _s: None, **kw)


def message_of(world: World, sha: str) -> str:
    return world.raw(world.origin, "log", "-1", "--format=%B", sha).rstrip("\n")


def test_scn_yolo_76_a_verified_unit_is_squash_merged_by_default(world):
    before = world.target()
    forge = forge_for(world)
    out = merge(world, forge)
    assert (out.status, out.head, out.target_before, out.pr, out.raced) == ("merged", world.head, before, 1, False)
    assert out.landed == world.target() != world.head
    assert world.raw(world.origin, "rev-parse", f"{out.landed}^").strip() == before
    assert world.raw(world.origin, "rev-parse", f"{out.landed}^{{tree}}") == world.raw(
        world.origin, "rev-parse", f"{world.head}^{{tree}}"
    )
    text = message_of(world, out.landed)
    assert text.splitlines()[0] == "[l4] x (#1)" and "skip ci" not in text.lower()
    assert f"L4-Verified-Head: {world.head}" in text and f"L4-Unit: {UNIT}" in text and f"L4-Run: {RUN}" in text
    assert forge.get_pr(1).state == "merged" and len(forge.called("merge")) == 1
    assert not any(a[:2] == ["push", "--"] for a in world.git.history)  # the forge merged, nothing was pushed


@pytest.mark.parametrize("title", ["[ci skip] add x", "add x [skip ci]", "add [SKIP CI] x"])
def test_the_squash_title_never_carries_a_skip_ci_marker(world, title):
    out = merge(world, forge_for(world, title))
    first = message_of(world, out.landed).splitlines()[0]
    assert "skip" not in first.lower() and first.endswith(" (#1)")


def test_the_squash_message_is_title_body_and_trailers():
    title, body = squash_message("[l4] x [skip ci]", 7, UNIT, 3, "h" * 40, RUN)
    assert title == "[l4] x (#7)"
    assert body == (
        f"Squash of {UNIT}: 3 commits, verified head {'h' * 40}.\n\n"
        f"L4-Unit: {UNIT}\nL4-Verified-Head: {'h' * 40}\nL4-Run: {RUN}"
    )


def test_the_plan_may_still_refuse_before_the_forge_merges(world):
    forge = forge_for(world)
    out = merge(world, forge, before_push=lambda _to_be: False)
    assert out.status == "not_ready" and forge.called("merge") == []


def test_scn_yolo_78_fast_forward_stays_an_option(world):
    world.cfg = L4Config.model_validate({"version": 1, "yolo": {"merge": {"method": "fast-forward"}}})
    forge = forge_for(world)
    out = merge(world, forge)
    assert (out.status, out.landed, out.raced) == ("merged", world.head, False)
    assert world.target() == world.head and forge.called("merge") == []
    assert ["push", "--", "origin", f"{world.head}:refs/heads/main"] == world.git.history[-1][-4:]


def test_scn_yolo_79_a_forge_that_refuses_a_squash_is_refused(world):
    before = world.target()
    forge = forge_for(world, answer=MergeCall("refused", None, "Squash merges are not allowed on this repository"))
    out = merge(world, forge)
    assert out.status == "refused" and "Squash merges are not allowed" in out.detail and out.landed is None
    assert world.target() == before


def test_scn_yolo_80_a_head_that_moved_is_not_merged(world):
    before = world.target()
    forge = forge_for(world, answer=MergeCall("head_moved", None, "Head branch was modified"))
    out = merge(world, forge)
    assert out.status == "not_ready" and "Head branch was modified" in out.detail and out.landed is None
    assert world.target() == before


def test_scn_yolo_81_a_target_that_moved_during_the_merge_is_recorded(world, caplog):
    person = []
    forge = forge_for(world, before=lambda: person.append(world.move_target()))
    with caplog.at_level(logging.WARNING, logger="l4.yolo.merge"):
        out = merge(world, forge)
    assert out.status == "merged" and out.raced is True and out.landed == world.target()
    assert world.raw(world.origin, "rev-parse", f"{out.landed}^").strip() == person[0] != out.target_before
    assert any("moved" in r.getMessage() for r in caplog.records)


def test_a_squash_that_changed_the_tree_is_recorded_as_raced(world):
    class Merges(ScriptedForge):
        def merge_pr(self, number, *, sha, title, message):
            call = super().merge_pr(number, sha=sha, title=title, message=message)
            other = world.work.parent / "tree"
            world.raw(world.work.parent, "clone", "-q", str(world.origin), str(other))
            world.raw(other, "checkout", "-q", "main")
            (other / "odd.txt").write_text("a different tree\n")
            world.raw(other, "add", "-A")
            world.raw(other, "commit", "-q", "-m", "x")
            world.raw(other, "push", "-q", "origin", "main")
            return MergeCall("merged", world.target(), call.detail)  # the forge says this commit landed

    forge = Merges(world.origin)
    forge.create_pr(BRANCH, "main", "t", "b", draft=False)
    assert merge(world, forge).raced is True


def test_confirm_merged_reads_the_landed_commit_not_the_head(world):
    forge = forge_for(world)
    out = merge(world, forge)
    assert confirm_merged(forge, world.git, world.cfg, out.pr, out.landed, wait_s=0)
    assert not confirm_merged(
        forge, world.git, world.cfg, out.pr, world.head, wait_s=0
    )  # the head is not in the target
