# ruff: noqa: F811
"""Exclusions in the plan file (L4-YOLO-017, design D15; SCN-YOLO-35, SCN-YOLO-36) and the holder of a unit that two
plan files list (review #15)."""

import json

import pytest

from l4.yolo.admit import admit
from l4.yolo.model import Plan, PlanInvalid, PlanState, UnitInfo, load_plan
from l4.yolo.plans import _plan_file, held_by, holds_of, readable_unit_ids

from .test_yolo_admit_admission import batch, cfg, codes, infos, make_plan
from .yolo_cmd_world import A, B, plan_doc, world  # noqa: F401


def known(plan: Plan) -> dict[str, UnitInfo]:
    return {i: UnitInfo(id=i, folder=f"f/{i}") for i in plan.known_ids()}


def plan_text(plan_id, units, exclude=None, **over):
    raw = {
        "schema": "l4/delivery-plan@1", "plan_id": plan_id, "target": "main", "merge": "human",
        "batches": [{"id": "b1", "units": [{"id": u} for u in units]}],
    }  # fmt: skip
    if exclude is not None:
        raw["exclude"] = exclude
    return json.dumps({**raw, **over})


def file(plan_id, text):
    return _plan_file(f".l4/plans/{plan_id}.json", text)


# --- the model -------------------------------------------------------------------------------------------------------


def test_the_plan_file_may_list_exclusions():
    plan = load_plan(plan_text("p1", ["a"], [{"id": "b", "reason": "in review before the plan"}]))
    assert isinstance(plan, Plan) and [(x.id, x.reason) for x in plan.exclude] == [("b", "in review before the plan")]
    assert plan.known_ids() == ["a", "b"]


@pytest.mark.parametrize(
    "bad",
    [{"id": "b", "reason": ""}, {"id": "b", "reason": "x" * 201}, {"id": "b"}, {"id": "b", "reason": "r", "x": 1}],
)
def test_a_bad_exclusion_makes_the_file_invalid(bad):
    assert isinstance(load_plan(plan_text("p1", ["a"], [bad])), PlanInvalid)


def test_a_reason_of_200_characters_is_fine():
    assert isinstance(load_plan(plan_text("p1", ["a"], [{"id": "b", "reason": "x" * 200}])), Plan)


# --- admission -------------------------------------------------------------------------------------------------------


def test_an_exclusion_a_provider_knows_is_no_finding():
    plan = make_plan([batch("b1", [("a", [])])], exclude=[{"id": "z", "reason": "later"}])
    assert admit(plan, known_units=known(plan), cfg=cfg()).ok


def test_a_unit_both_planned_and_excluded_is_refused():  # SCN-YOLO-36
    plan = make_plan([batch("b1", [("a", [])])], exclude=[{"id": "a", "reason": "oops"}])
    result = admit(plan, known_units=known(plan), cfg=cfg())
    assert codes(result) == ["excluded_and_planned"] and result.findings[0].subject == "a"


def test_a_repeated_exclusion_is_a_duplicate_id():
    plan = make_plan([batch("b1", [("a", [])])], exclude=[{"id": "z", "reason": "1"}, {"id": "z", "reason": "2"}])
    result = admit(plan, known_units=known(plan), cfg=cfg())
    assert codes(result) == ["duplicate_id"] and result.findings[0].subject == "z"


def test_an_excluded_unit_no_provider_knows_is_an_unknown_unit():
    plan = make_plan([batch("b1", [("a", [])])], exclude=[{"id": "ghost", "reason": "gone"}])
    only_a = infos(plan)
    result = admit(plan, known_units=only_a, cfg=cfg())
    assert codes(result) == ["unknown_unit"] and result.findings[0].subject == "ghost"


def test_an_excluded_unit_is_not_part_of_the_order():
    plan = make_plan([batch("b1", [("a", [])])], exclude=[{"id": "z", "reason": "later"}])
    assert admit(plan, known_units=known(plan), cfg=cfg()).order == ("a",)


# --- holding ---------------------------------------------------------------------------------------------------------


def test_an_excluded_unit_is_not_held():  # SCN-YOLO-35
    files = [file("p1", plan_text("p1", ["openspec:a"], [{"id": "kiro:pick-priority", "reason": "in review"}]))]
    assert held_by({"p1": PlanState(plan_id="p1", status="active")}, files) == {"openspec:a": ("p1", "active")}


def test_an_invalid_file_leaves_its_excluded_ids_out_too():
    text = plan_text("p2", ["openspec:b", "openspec:c"], [{"id": "openspec:c", "reason": "r"}], parallel=True)
    assert readable_unit_ids(text) == ["openspec:b"]
    assert holds_of({}, [file("p2", text)]).held == {"openspec:b": ("p2", "invalid")}


def test_a_malformed_exclude_list_is_ignored_by_the_reader():
    text = json.dumps({"batches": [{"units": [{"id": "openspec:a"}]}], "exclude": ["junk", {"id": 3}, 7]})
    assert readable_unit_ids(text) == ["openspec:a"]


# --- review #15: which plan holds a unit two files list -------------------------------------------------------------


@pytest.mark.parametrize("status", ["active", "waiting", "stopped"])
def test_the_activated_plan_holds_a_unit_whatever_the_path_order(status):
    files = [file("p0", plan_text("p0", ["openspec:a"])), file("p1", plan_text("p1", ["openspec:a"]))]
    states = {"p1": PlanState(plan_id="p1", status=status)}
    assert held_by(states, files) == {"openspec:a": ("p1", status)}


def test_without_an_activated_plan_the_first_file_holds_it():
    files = [file("p0", plan_text("p0", ["openspec:a"])), file("p1", plan_text("p1", ["openspec:a"]))]
    states = {"p1": PlanState(plan_id="p1", status="reviewed")}
    assert held_by(states, files) == {"openspec:a": ("p0", "new")}


def test_a_cancelled_plan_does_not_outrank_an_earlier_file():
    files = [file("p0", plan_text("p0", ["openspec:a"])), file("p1", plan_text("p1", ["openspec:a"]))]
    assert held_by({"p1": PlanState(plan_id="p1", status="cancelled")}, files)["openspec:a"][0] == "p0"


def test_admission_of_the_earlier_plan_gets_held_by_other_plan_for_the_active_ones_unit():
    files = [file("p0", plan_text("p0", ["a"])), file("p1", plan_text("p1", ["a"]))]
    held = {u: pid for u, (pid, _) in held_by({"p1": PlanState(plan_id="p1", status="active")}, files).items()}
    p0, p1 = files[0].plan, files[1].plan
    r0 = admit(p0, known_units=infos(p0), cfg=cfg(base="main"), held=held)
    assert codes(r0) == ["held_by_other_plan"] and "p1" in r0.findings[0].text
    assert admit(p1, known_units=infos(p1), cfg=cfg(base="main"), held=held).ok


# --- the commands ----------------------------------------------------------------------------------------------------


def test_check_refuses_a_unit_that_is_planned_and_excluded_and_writes_nothing(world, capsys):  # SCN-YOLO-36
    world.push_plan(plan_doc(exclude=[{"id": A, "reason": "oops"}]))
    assert world.l4("check", "p1") == 2
    out = capsys.readouterr().out
    assert "excluded_and_planned" in out and A in out
    assert world.store().read().head is None


def test_check_refuses_an_excluded_unit_no_provider_knows(world, capsys):
    world.push_plan(plan_doc(exclude=[{"id": "kiro:nope", "reason": "gone"}]))
    assert world.l4("check", "p1") == 2
    assert "unknown_unit" in capsys.readouterr().out


def test_check_admits_a_plan_whose_exclusion_exists(world, capsys):
    world.push_plan(plan_doc({A: []}, exclude=[{"id": B, "reason": "in review before the plan"}]))
    assert world.l4("check", "p1") == 0
    assert f"order: {A}" in capsys.readouterr().out


def test_status_lists_the_exclusions_with_their_reasons(world, capsys):  # SCN-YOLO-35
    world.push_plan(plan_doc({A: []}, exclude=[{"id": B, "reason": "in review before the plan"}]))
    assert world.l4("status", "p1") == 0
    assert f"excluded: {B} (in review before the plan)" in capsys.readouterr().out
    assert world.l4("status", "p1", "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["plans"][0]["excluded"] == [{"id": B, "reason": "in review before the plan"}]
