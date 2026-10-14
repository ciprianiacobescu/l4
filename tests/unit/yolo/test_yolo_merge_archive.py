"""merge_archive_guarded (L4-YOLO-009, design D9): the archive branch head fast-forwards the target under the same
guard as a unit merge; a moved target is stale, a protected one refused."""

import stat

import pytest

from l4.postmerge import merge_archive_guarded

from .test_yolo_merge_guard import World


@pytest.fixture
def world(tmp_path, raw, git_environ) -> World:
    w = World(tmp_path, raw, git_environ)
    raw(w.work, "checkout", "-q", "-b", "l4/archive/openspec/x", "main")
    w.head = w.commit(w.work, "archived.txt", "archive")
    raw(w.work, "push", "-q", "origin", "l4/archive/openspec/x")
    return w


def test_the_archive_head_fast_forwards_the_target(world):
    before = world.target()
    out = merge_archive_guarded(world.app, world.cfg, world.git, world.head, "main")
    assert (out.status, out.head, out.target_before) == ("merged", world.head, before)
    assert world.target() == world.head


def test_a_moved_target_is_stale_and_unchanged(world):
    world.move_target()
    moved = world.target()
    out = merge_archive_guarded(world.app, world.cfg, world.git, world.head, "main")
    assert out.status == "stale" and world.target() == moved


def test_a_protected_target_is_refused(world):
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    out = merge_archive_guarded(world.app, world.cfg, world.git, world.head, "main")
    assert out.status == "refused" and "protected branch" in out.detail
