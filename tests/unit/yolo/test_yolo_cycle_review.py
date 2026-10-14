"""The plan step before activation (L4-YOLO-004, L4-YOLO-010): no plan file changes nothing, a pushed plan is
admitted and reviewed once and holds its units (SCN-YOLO-30), a refused or invalid plan is said once, a judge
that cannot run records nothing."""

import pytest

from l4.agents.fake import Step
from l4.availability.errors import RoleUnavailable
from l4.yolo.digest import plan_digest
from l4.yolo.state import fold_plan

from .yolo_cycle_world import PLAN, READY, CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def test_a_repository_without_a_plan_file_is_left_alone(world):
    before = list(world.git.history)
    step = world.step()
    assert step.allow is None and step.actions == () and step.start_next_run is False
    assert world.git.history == before  # not even a fetch of a plan ref
    assert sh_refs(world) == ""


def test_scn_yolo_30_specs_pushed_with_their_plan_do_not_start_on_their_own(world):
    world.plan()
    step = world.step()
    assert world.kinds() == ["plan.admitted", "plan.reviewed"]
    assert step.allow == frozenset() and step.start_next_run is False
    assert step.refusals == {A: "is held by plan p1 (reviewed)", B: "is held by plan p1 (reviewed)"}
    reviewed = world.events()[1].data
    assert reviewed["units"][A]["verdict"] == "READY" and reviewed["units"][A]["digest"]
    assert reviewed["plan_digest"] == plan_digest((world.repo / ".l4/plans/p1.json").read_text())
    assert not world.git.run("branch", "-r", "--list", "origin/l4/*").stdout.strip()  # no unit branch was made


def test_a_reviewed_plan_is_not_reviewed_again_until_an_input_changes(world):
    world.plan()
    world.step()
    head = world.store().read().head
    world.step()
    assert world.store().read().head == head  # nothing recorded, the judge was not asked again
    world.commit({"openspec/changes/a/specs/x/spec.md": "## ADDED Requirements\n### Requirement: A\nA SHALL act.\n"})
    world.push_main()
    world.step()
    assert world.kinds() == ["plan.admitted", "plan.reviewed", "plan.reviewed"]


def test_the_judges_cost_is_charged_as_a_running_total(world):
    world.plan()
    world.judge = type(world.judge)([Step(structured=READY, cost_usd=0.5) for _ in range(6)])
    world.step()  # two units and their batch: three calls
    (charged,) = [e.data for e in world.events() if e.type == "plan.charged"]
    assert charged["unit"] == "plan:review" and charged["cost_usd"] == 1.5 and charged["attempt"] == 0
    world.commit({"openspec/changes/a/specs/x/spec.md": "## ADDED Requirements\n### Requirement: A\nA SHALL act.\n"})
    world.push_main()
    world.step()  # reviewed again: the key holds the running total, because the fold keeps the maximum per key
    assert [e.data["cost_usd"] for e in world.events() if e.type == "plan.charged"] == [1.5, 3.0]
    assert world.store().read().events and fold_cost(world) == 3.0


def test_a_plan_that_admission_refuses_is_refused_once(world):
    world.plan(deps={"b": ["openspec:ghost"]})
    world.step()
    world.step()
    assert world.kinds() == ["plan.refused"]
    codes = {f["code"] for f in world.events()[0].data["findings"]}
    assert "unknown_dependency" in codes
    assert world.judge.requests == []  # the second run did not ask the judge: admission stopped it first


def test_an_invalid_plan_file_is_refused_once_per_content(world):
    world.commit({".l4/plans/p1.json": '{"schema": "l4/delivery-plan@1", "parallel": 3}\n'})
    world.push_main()
    step = world.step()
    world.step()
    assert world.kinds() == ["plan.refused"]
    assert "unknown field" in world.events()[0].data["findings"][0]["text"]
    assert step.allow == frozenset({A, B})  # an invalid file lists no unit, so it holds none
    world.commit({".l4/plans/p1.json": '{"schema": "l4/delivery-plan@1", "parallel": 4}\n'})
    world.push_main()
    world.step()
    assert world.kinds() == ["plan.refused", "plan.refused"]


def test_a_judge_that_cannot_run_records_nothing(world, monkeypatch):
    world.plan()

    def no_judge(*args, **kwargs):
        raise RoleUnavailable("judge", "every profile is cooling down")

    monkeypatch.setattr("l4.yolo.cycle.review_plan_costed", no_judge)
    step = world.step()
    assert world.kinds() == [] and step.start_next_run is False
    assert any("no judge could run" in a for a in step.actions)


def test_a_plan_file_with_a_name_that_is_not_a_plan_id_is_skipped(world):
    world.commit({".l4/plans/Bad_Name.json": "{}\n"})
    world.push_main()
    step = world.step()
    assert step.allow == frozenset({A, B})


def test_units_outside_every_plan_run_while_no_plan_is_active(world):
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    step = world.step()
    assert A not in step.allow and B in step.allow
    assert step.refusals[A] == "is held by plan p1 (reviewed)"


def test_scn_yolo_34_a_cancelled_plan_still_holds_its_units(world):  # R8, review #8
    world.plan()
    world.step()
    world.seed(ev("plan.cancelled", by="alice", reason="no"))
    step = world.step()
    assert step.allow == frozenset()
    assert step.refusals[A] == "is held by plan p1 (cancelled)"
    world.git.run("rm", "-q", ".l4/plans/p1.json")  # removing the file from the target releases them
    world.git.run("commit", "-q", "-m", "drop the plan")
    world.push_main()
    assert world.step().allow is None  # no plan file on the target: the units are ordinary units again


def fold_cost(world) -> float:
    return fold_plan(PLAN, world.events()).used.cost_usd


def sh_refs(world) -> str:
    return world.git.run("ls-remote", "origin", "refs/l4/plans/*").stdout.strip()
