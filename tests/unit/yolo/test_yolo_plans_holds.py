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


def test_a_completed_plan_holds_nothing_any_more():  # design D10: it integrated its units (SCN-YOLO-28)
    files = [file("p1", plan_text("p1", ["openspec:a"]))]
    assert held_by({"p1": state("p1", "completed")}, files) == {}


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


# --- yolo.hold (L4-ADO-011, design D5) ------------------------------------------------------------------------------

from l4.yolo.cycle import Hold, config_holds, plan_holds  # noqa: E402

from .yolo_review_world import make_cfg  # noqa: E402

HELD = Hold("held by yolo.hold", "is held by yolo.hold")


def cfg_with(*hold):
    return make_cfg(yolo={"hold": list(hold)})


def test_config_holds_matches_an_id_and_a_pattern():
    cfg = cfg_with("openspec:a", "kiro:*")
    assert config_holds(cfg, ["openspec:a", "openspec:b", "kiro:x"], set()) == {"openspec:a": HELD, "kiro:x": HELD}


def test_config_holds_leaves_a_listed_unit_to_its_plan():
    assert config_holds(cfg_with("*"), ["openspec:a", "openspec:b"], {"openspec:a"}) == {"openspec:b": HELD}


def test_config_holds_leaves_the_fix_and_follow_up_units_of_a_listed_parent_to_it():
    units = [
        "openspec:a",
        "openspec:a-fix-1",
        "openspec:a-fix-1-fix-2",
        "openspec:a-followup-1",
        "kiro:k-fix-1",
        "openspec:b-fix-1",
    ]
    held = config_holds(cfg_with("*"), units, {"openspec:a"})
    assert sorted(held) == ["kiro:k-fix-1", "openspec:b-fix-1"]  # a-fix-*, a-followup-* follow their parent a


def test_plan_holds_does_not_config_hold_a_fix_unit_of_a_planned_parent():
    files = [file("p1", plan_text("p1", ["openspec:a"]))]
    phases = {"openspec:a": "implementing", "openspec:a-fix-1": "implementing", "openspec:z": "implementing"}
    holds = plan_holds(files, {}, phases, "main", cfg_with("*"))
    assert holds["openspec:z"] == HELD and "openspec:a-fix-1" not in holds


def test_config_holds_with_no_entry_holds_nothing():
    assert config_holds(cfg_with(), ["openspec:a"], set()) == {}


def test_plan_holds_adds_the_config_hold_for_a_unit_no_plan_lists():
    files = [file("p1", plan_text("p1", ["openspec:a"]))]
    phases = {"openspec:a": "implementing", "openspec:b": "implementing", "openspec:c": None}
    holds = plan_holds(files, {}, phases, "main", cfg_with("openspec:b", "openspec:c", "openspec:a"))
    assert holds["openspec:b"] == holds["openspec:c"] == HELD
    assert holds["openspec:a"].reason == "held by plan p1 (new)"  # a listed unit follows its plan


def test_plan_holds_never_holds_a_merged_or_archived_unit():
    phases = {"openspec:a": "merged", "openspec:b": "archived", "openspec:c": "implementing"}
    assert plan_holds([], {}, phases, "main", cfg_with("*")) == {"openspec:c": HELD}


def test_plan_holds_without_a_config_is_as_before():
    assert plan_holds([], {}, {"openspec:a": None}, "main") == {}


def test_an_excluded_unit_that_yolo_hold_matches_stays_held():
    """L4-ADO-011 (round-2 review): excluding a unit in a plan RELEASED it from yolo.hold; only the ids a plan PLANS
    count as listed, so an excluded one stays `held by yolo.hold`."""
    files = [file("p1", plan_text("p1", ["openspec:a"], exclude=[{"id": "openspec:b", "reason": "later"}]))]
    holds = plan_holds(files, {}, {"openspec:b": None, "openspec:a": None}, "main", cfg_with("*"))
    assert holds["openspec:b"] == HELD
    assert holds["openspec:a"].reason == "held by plan p1 (new)"  # the planned unit still follows its plan
    assert config_holds(cfg_with("*"), ["openspec:b"], set()) == {"openspec:b": HELD}
