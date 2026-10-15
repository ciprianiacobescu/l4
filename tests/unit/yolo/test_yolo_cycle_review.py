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
    network = ("fetch", "ls-remote", "push")  # a local `git log` of the plan folder is the only read
    assert not any(w in args for args in world.git.history[len(before) :] for w in network)
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


# --- the review reuses what the judge already judged (L4-YOLO-022) ----------------------------------------

BASELINE = (  # the capability the units change has a baseline, so its deltas need no Purpose (L4-OSP-007)
    "# x Specification\n\n## Purpose\nThe capability the units of these tests change, with a baseline.\n\n"
    "## Requirements\n### Requirement: Base\nThe system SHALL exist.\n"
)
SPEC_NEW = "## ADDED Requirements\n### Requirement: A\nA SHALL act.\n"


def baselined(world):
    world.commit({"openspec/specs/x/spec.md": BASELINE}, "baseline")
    return world


def reviewed_events(world):
    return [e.data for e in world.events() if e.type == "plan.reviewed"]


def change_and_push(world, name, spec=SPEC_NEW):
    world.commit({f"openspec/changes/{name}/specs/x/spec.md": spec})
    world.push_main()


def test_scn_yolo_47_an_unchanged_unit_is_not_judged_again(tmp_path):
    world = baselined(CycleWorld(tmp_path))
    world.plan(deps={})
    world.judge = type(world.judge)([Step(structured=READY, cost_usd=0.5) for _ in range(10)])
    world.step()
    assert len(world.judge.requests) == 3  # a, b and their batch
    first = reviewed_events(world)[0]
    assert first["source"] == "ci" and first["judge"]
    assert first["units"][A]["material"] and "reused_from" not in first["units"][A]
    assert set(first["batches"]["b1"]["digests"]) == {A, B}
    change_and_push(world, "b")
    step = world.step()
    assert len(world.judge.requests) == 5  # b and the batch only
    second = reviewed_events(world)[1]
    assert second["units"][A]["reused_from"]
    assert second["units"][A]["verdict"] == first["units"][A]["verdict"]
    assert second["units"][A]["findings"] == first["units"][A]["findings"]
    assert second["units"][A]["material"] == first["units"][A]["material"]
    assert "reused_from" not in second["units"][B] and second["units"][B]["material"] != first["units"][B]["material"]
    totals = [e.data["cost_usd"] for e in world.events() if e.type == "plan.charged"]
    assert totals == [1.5, 2.5]  # the second review charged two calls, not three
    assert "plan p1: reviewed: 3 READY, 0 not READY, 2 judged, 1 reused (l4 yolo findings p1)" in step.actions


def test_scn_yolo_48_a_changed_prerequisite_makes_its_dependents_judged_again(tmp_path):
    world = baselined(CycleWorld(tmp_path))
    world.plan()  # b depends on a
    world.step()
    assert len(world.judge.requests) == 3
    change_and_push(world, "a")
    world.step()
    assert len(world.judge.requests) == 6  # a, b (its prerequisite changed) and the batch
    second = reviewed_events(world)[1]
    assert "reused_from" not in second["units"][A] and "reused_from" not in second["units"][B]


def test_scn_yolo_49_a_review_that_did_not_happen_is_not_reused(tmp_path):
    world = baselined(CycleWorld(tmp_path))
    world.plan(deps={})
    bad = [Step(structured={"nonsense": 1}), Step(structured={"nonsense": 2})]  # the repair also fails
    world.judge = type(world.judge)([*bad, *[Step(structured=READY) for _ in range(8)]])
    world.step()
    first = reviewed_events(world)[0]
    assert first["units"][A]["verdict"] == "BLOCKED" and first["units"][A]["findings"][0]["criterion"] == "schema"
    seen = len(world.judge.requests)
    assert seen == 4  # a twice (one repair), b, the batch
    change_and_push(world, "b")
    world.step()
    second = reviewed_events(world)[1]
    assert len(world.judge.requests) - seen == 3  # a again, b and the batch
    assert second["units"][A]["verdict"] == "READY" and "reused_from" not in second["units"][A]


def test_a_lost_lease_after_the_review_still_appends_the_same_facts(tmp_path, monkeypatch):
    from l4.yolo.model import PlanMoved
    from l4.yolo.store import PlanStore

    world = baselined(CycleWorld(tmp_path))
    world.plan(deps={})
    real, calls = PlanStore.append, []

    def once(self, events, *, files=None, expect):
        calls.append(1)
        if len(calls) == 1:
            raise PlanMoved("moved")
        return real(self, events, files=files, expect=expect)

    monkeypatch.setattr(PlanStore, "append", once)
    world.step()
    assert world.kinds() == ["plan.admitted", "plan.reviewed"] and len(world.judge.requests) == 3
    data = reviewed_events(world)[0]
    assert data["source"] == "ci" and data["units"][A]["material"] and data["batches"]["b1"]["digests"]
