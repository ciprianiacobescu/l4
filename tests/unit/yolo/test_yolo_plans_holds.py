"""Which plan holds which unit (design D10, R8, requirement L4-YOLO-010, SCN-YOLO-30): every unit listed in a plan file
is held whatever the plan's status, cancelled included; an invalid plan file still holds the unit ids its JSON names;
a file that is not JSON holds nothing and is reported in a separate list."""

import json

from l4.yolo.model import PlanState
from l4.yolo.plans import _plan_file, held_by, holds_of


def plan_text(plan_id, units, **over):
    raw = {
        "schema": "l4/delivery-plan@1", "plan_id": plan_id, "target": "main", "merge": "human",
        "batches": [{"id": "b1", "units": [{"id": u} for u in units]}],
    }  # fmt: skip
    return json.dumps({**raw, **over})


def file(plan_id, text):
    return _plan_file(f".l4/plans/{plan_id}.json", text)


def state(plan_id, status):
    return PlanState(plan_id=plan_id, status=status)


def test_a_cancelled_plan_still_holds_its_units():  # review #8, R8
    files = [file("p1", plan_text("p1", ["openspec:a"]))]
    assert held_by({"p1": state("p1", "cancelled")}, files) == {"openspec:a": ("p1", "cancelled")}


def test_a_completed_plan_file_on_the_target_holds_its_units_too():
    files = [file("p1", plan_text("p1", ["openspec:a"]))]
    assert held_by({"p1": state("p1", "completed")}, files) == {"openspec:a": ("p1", "completed")}


def test_a_plan_without_a_ledger_is_new():
    files = [file("p1", plan_text("p1", ["openspec:a"]))]
    assert held_by({}, files) == {"openspec:a": ("p1", "new")}


def test_removing_the_unit_from_the_file_releases_it():
    files = [file("p1", plan_text("p1", ["openspec:b"]))]
    assert held_by({"p1": state("p1", "cancelled")}, files) == {"openspec:b": ("p1", "cancelled")}
    assert held_by({"p1": state("p1", "cancelled")}, []) == {}


def test_an_invalid_plan_file_holds_the_unit_ids_its_json_names():  # review #8, R8, SCN-YOLO-30
    text = plan_text("p2", ["openspec:b", "openspec:c"], parallel=True)  # unknown field: the schema refuses it
    bad = file("p2", text)
    assert bad.plan is None and bad.invalid is not None
    result = holds_of({}, [bad])
    assert result.held == {"openspec:b": ("p2", "invalid"), "openspec:c": ("p2", "invalid")}
    assert result.unreadable == []


def test_an_invalid_file_with_a_ledger_shows_the_plan_status():
    bad = file("p2", plan_text("p2", ["openspec:b"], parallel=True))
    assert holds_of({"p2": state("p2", "active")}, [bad]).held == {"openspec:b": ("p2", "active")}


def test_unit_ids_are_read_from_whatever_batches_are_well_shaped():
    text = json.dumps(
        {"batches": [{"units": [{"id": "openspec:a"}, {"id": 7}, "x", {"name": "y"}]}, "junk", {"units": "no"}]}
    )
    assert holds_of({}, [file("p3", text)]).held == {"openspec:a": ("p3", "invalid")}


def test_a_file_that_is_not_json_holds_nothing_and_is_returned_apart():
    broken = file("p4", "{ not json")
    result = holds_of({}, [broken, file("p1", plan_text("p1", ["openspec:a"]))])
    assert result.held == {"openspec:a": ("p1", "new")}
    assert [f.plan_id for f in result.unreadable] == ["p4"]


def test_a_json_file_that_is_not_an_object_holds_nothing():
    arr = file("p5", "[1, 2]")
    assert holds_of({}, [arr]).held == {} and [f.plan_id for f in holds_of({}, [arr]).unreadable] == ["p5"]


def test_a_unit_listed_in_two_plans_is_held_by_the_first_file():
    files = [file("p1", plan_text("p1", ["openspec:a"])), file("p2", plan_text("p2", ["openspec:a"]))]
    assert held_by({}, files) == {"openspec:a": ("p1", "new")}
