"""merge_archive_guarded (L4-YOLO-009, design D9, R6): the archive branch head fast-forwards the target under the guard
of a unit merge plus the archive's own: every commit after the target tip is a strict harness commit, the archive PR is
open with the target as its base, and the target is the base branch. A moved target is stale, a protected one
refused."""

import stat

import pytest

from l4.forge.base import PullRequest
from l4.postmerge import merge_archive_guarded
from l4.vcs.trailers import CommitTrailers

from .test_yolo_merge_guard import World

ARCHIVE = "l4/archive/openspec/x"
URL = "https://forge.invalid/o/r/pull/9"


def archive_pr(state="open", base="main") -> PullRequest:
    return PullRequest(9, URL, ARCHIVE, base, "[l4] archive x", False, state, ())


def harness_commit(world: World, name: str) -> str:
    """A commit the way the archiver makes it: the bot as author and committer, with the `L4-Run` trailer."""
    (world.work / name).write_text(name + "\n")
    world.git.run("add", "-A")
    world.git.commit(
        f"chore(x): {name}",
        CommitTrailers(unit="openspec:x", run_id="r-20261014T1000Z-aaaa", iteration=1, phase="archived"),
    )
    return world.git.rev_parse("HEAD") or ""


@pytest.fixture
def world(tmp_path, raw, git_environ) -> World:
    w = World(tmp_path, raw, git_environ)
    raw(w.work, "checkout", "-q", "-b", ARCHIVE, "main")
    w.head = harness_commit(w, "archived.txt")
    raw(w.work, "push", "-q", "origin", ARCHIVE)
    return w


def merge(world, head=None, target="main", pr=None):
    return merge_archive_guarded(world.app, world.cfg, world.git, head or world.head, target, pr=pr or archive_pr())


def test_the_archive_head_fast_forwards_the_target(world):
    before = world.target()
    out = merge(world)
    assert (out.status, out.head, out.target_before) == ("merged", world.head, before)
    assert world.target() == world.head


def test_a_moved_target_is_stale_and_unchanged(world):
    world.move_target()
    moved = world.target()
    out = merge(world)
    assert out.status == "stale" and world.target() == moved


def test_a_protected_target_is_refused(world):
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    out = merge(world)
    assert out.status == "refused" and "protected branch" in out.detail


def test_a_persons_commit_on_the_archive_branch_is_not_merged(world, raw):  # review #10, R6
    person = world.commit(world.work, "person.txt", "a person's edit")
    head = world.git.rev_parse("HEAD")
    assert head == person
    raw(world.work, "push", "-q", "origin", ARCHIVE)
    before = world.target()
    out = merge(world, head=person)
    assert out.status == "not_ready" and person[:10] in out.detail and "not a harness commit" in out.detail
    assert world.target() == before


def test_a_persons_commit_below_the_harness_commit_is_not_merged_either(world, raw):
    raw(world.work, "checkout", "-q", "-b", "l4/archive/other", "main")
    person = world.commit(world.work, "person.txt", "edit")
    top = harness_commit(world, "archived2.txt")
    before = world.target()
    out = merge(world, head=top)
    assert out.status == "not_ready" and person[:10] in out.detail
    assert world.target() == before


def test_a_rebased_harness_commit_is_a_persons_under_the_strict_rule(world, raw):
    raw(world.work, "commit", "-q", "--amend", "--no-edit", "--reset-author")  # author t, committer t: not the bot
    amended = world.git.rev_parse("HEAD")
    before = world.target()
    out = merge(world, head=amended)
    assert out.status == "not_ready" and world.target() == before


@pytest.mark.parametrize(
    ("pr", "fragment"),
    [
        (archive_pr(state="closed"), "closed, not open"),
        (archive_pr(state="merged"), "merged, not open"),
        (archive_pr(base="release"), "aimed at release, not the target main"),
    ],
)
def test_the_archive_pull_request_must_be_open_and_aimed_at_the_target(world, pr, fragment):
    before = world.target()
    out = merge(world, pr=pr)
    assert out.status == "not_ready" and fragment in out.detail
    assert world.target() == before


def test_the_target_must_be_the_base_branch(world, raw):
    raw(world.work, "push", "-q", "origin", "main:refs/heads/staging")
    before = world.raw(world.origin, "rev-parse", "refs/heads/staging").strip()
    out = merge(world, target="staging", pr=archive_pr(base="staging"))
    assert out.status == "not_ready" and "staging" in out.detail and "base branch main" in out.detail
    assert world.raw(world.origin, "rev-parse", "refs/heads/staging").strip() == before


def test_a_missing_target_is_not_ready(world):
    world.raw(world.origin, "update-ref", "-d", "refs/heads/main")
    out = merge(world)
    assert out.status == "not_ready" and "does not exist" in out.detail
