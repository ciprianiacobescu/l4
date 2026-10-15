"""Which units' archive pull requests the sweep may merge (L4-YOLO-009, D14): only those of an active `merge: auto` plan
on the base branch, read from the fetched plan ref."""

import pytest

from l4.yolo.cycle import auto_plan_units

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def units(world) -> frozenset[str]:
    return auto_plan_units(world.app, world.cfg, world.git)


def test_no_plan_file_means_no_unit(world):
    assert units(world) == frozenset()


def test_the_units_of_an_active_auto_plan(world):
    world.plan(merge="auto")
    world.activate()
    assert units(world) == {A, B}


@pytest.mark.parametrize("merge", ["human"])
def test_a_human_merge_plan_has_none(world, merge):
    world.plan(merge=merge)
    world.activate()
    assert units(world) == frozenset()


def test_a_plan_that_is_not_active_has_none(world):
    world.plan(merge="auto")
    world.reviewed()
    assert units(world) == frozenset()
    world.activate()
    world.seed(ev("plan.stopped", reason="unit_halted", unit=A))
    assert units(world) == frozenset()


def test_an_unreadable_plan_state_means_no_unit(world, monkeypatch):
    world.plan(merge="auto")
    world.activate()

    def broken(self):
        raise ValueError("ledger.jsonl line 1 is not a plan event")

    monkeypatch.setattr("l4.yolo.store.PlanStore.read", broken)
    assert units(world) == frozenset()
