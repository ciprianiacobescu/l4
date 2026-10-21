"""`still_waits`: the one rule by which the plan step, `l4 yolo resume` and `l4 yolo status` decide that a waiting
plan's unit still waits for a person or for capacity with nothing to run (L4-YOLO-052)."""

import pytest

from l4.yolo.commands import answered_units
from l4.yolo.cycle import ACTIONABLE, still_waits

from .yolo_cycle_world import CycleWorld


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def test_the_actionable_actions_are_the_ones_a_run_can_take():
    assert {"implement", "clarify", "verify", "hand_off", "delegate"} == set(ACTIONABLE)  # delegate-answers 9.3


def test_a_unit_awaiting_a_human_with_an_open_question_still_waits(world):
    assert still_waits(world.snapshot("a", "awaiting_human")) is True


def test_a_unit_whose_answer_is_pushed_no_longer_waits(world, monkeypatch):
    monkeypatch.setattr("l4.planner.answers_unblock", lambda questions, tasks: ("Q-001",))
    assert still_waits(world.snapshot("a", "awaiting_human")) is False


def test_a_unit_that_is_not_in_a_wait_phase_does_not_wait(world):
    assert still_waits(world.snapshot("a", "implementing")) is False


def test_a_unit_waiting_for_capacity_still_waits(world):
    assert still_waits(world.snapshot("a", "waiting_capacity")) is True


def test_answered_units_holds_the_awaiting_or_clarifying_units_that_no_longer_wait(world, monkeypatch):
    snaps = [world.snapshot(n, p) for n, p in (("a", "awaiting_human"), ("b", "clarifying"), ("c", "implementing"))]
    # an open question still waits; a clarifying unit has the clarifier's own run to take (`clarify`) but no answer is
    # recorded for it: it is not described as answered (review N5)
    assert answered_units(snaps) == set()
    monkeypatch.setattr("l4.planner.answers_unblock", lambda questions, tasks: ("Q-001",))
    assert answered_units(snaps) == {"openspec:a", "openspec:b"}  # `c` is not waiting: it is no answered unit
    assert answered_units([world.snapshot("d", "waiting_capacity")]) == set()
