# ruff: noqa: F811
"""A review made with an older readiness prompt is stale (L4-YOLO-004, review 7): the next CI run reviews again,
`l4 yolo status` says so, and activation refuses it."""

import pytest

from l4.yolo.digest import plan_digest
from l4.yolo.readiness import PROMPT_VERSION
from l4.yolo.state import fold_plan

from .yolo_cmd_world import A, B, ev, forge  # noqa: F401
from .yolo_cmd_world import world as cmd_world  # noqa: F401 - the fixture
from .yolo_cycle_world import CycleWorld


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def test_the_prompt_version_is_3():
    assert PROMPT_VERSION == 3


def test_the_ci_step_records_the_prompt_version(world):
    world.plan()
    world.step()
    reviewed = [e for e in world.events() if e.type == "plan.reviewed"]
    assert [e.data["prompt_version"] for e in reviewed] == [PROMPT_VERSION]
    assert fold_plan("p1", world.events()).review_prompt_version == PROMPT_VERSION


def test_a_review_without_a_prompt_version_is_stale_and_the_step_reviews_again(world):
    world.plan()
    world.reviewed(prompt_version=None)  # recorded by an older harness: version 1
    assert fold_plan("p1", world.events()).review_prompt_version == 1
    world.step()
    assert world.kinds().count("plan.reviewed") == 2
    assert fold_plan("p1", world.events()).review_prompt_version == PROMPT_VERSION
    head = world.store().read().head
    world.step()
    assert world.store().read().head == head  # now current: not reviewed again


def test_a_review_of_the_current_prompt_version_is_current(world):
    world.plan()
    world.reviewed()
    head = world.store().read().head
    world.step()
    assert world.kinds().count("plan.reviewed") == 1 and world.store().read().head == head


def test_status_says_the_review_prompt_changed_and_activation_refuses(cmd_world, forge, capsys):
    cmd_world.push_plan()
    old = cmd_world.reviewed()
    old.data.pop("prompt_version")
    cmd_world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(cmd_world.plan_text), order=[A, B]), old)
    assert cmd_world.l4("status", "p1") == 0
    assert "review: stale (the review prompt changed)" in capsys.readouterr().out
    assert cmd_world.l4("activate", "p1", "--reason", "go") == 2
    assert "older review prompt: run l4 yolo review p1" in capsys.readouterr().err
    assert not [e for e in cmd_world.events() if e.type == "plan.activated"]


def test_status_of_a_review_of_the_current_prompt_has_no_stale_note(cmd_world, forge, capsys):
    cmd_world.push_plan()
    cmd_world.seed(
        "p1", ev("plan.admitted", plan_digest=plan_digest(cmd_world.plan_text), order=[A, B]), cmd_world.reviewed()
    )
    assert cmd_world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "review: current" in out and "prompt changed" not in out
