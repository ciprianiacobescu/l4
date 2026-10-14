"""Admission (design D2): one test per finding code, the order, SCN-YOLO-03, SCN-YOLO-04, SCN-YOLO-05."""

import json

from l4.config.schema import L4Config
from l4.yolo.admit import admit
from l4.yolo.model import Plan, UnitInfo, load_plan


def make_plan(batches, *, target="staging", merge="human", **extra) -> Plan:
    raw = {"schema": "l4/delivery-plan@1", "plan_id": "p1", "target": target, "merge": merge, "batches": batches}
    plan = load_plan(json.dumps({**raw, **extra}))
    assert isinstance(plan, Plan), plan
    return plan


def cfg(base="staging", policy="human", profiles=None) -> L4Config:
    return L4Config.model_validate(
        {"forge": {"base_branch": base, "merge_policy": policy}, "yolo": {"profiles": profiles or {}}}
    )


def infos(plan: Plan, **over) -> dict[str, UnitInfo]:
    return {u.id: over.get(u.id, UnitInfo(id=u.id, folder=f"f/{u.id}")) for u in plan.units()}


def codes(result) -> list[str]:
    return [f.code for f in result.findings]


def batch(bid, units, deps=(), profile=None):
    out = {"id": bid, "depends_on": list(deps), "units": [{"id": i, "depends_on": list(d)} for i, d in units]}
    if profile:
        out["acceptance_profile"] = profile
    return out


def test_valid_plan_prints_its_order_a_b_c():  # SCN-YOLO-04
    plan = make_plan([batch("b1", [("a", []), ("b", ["a"])]), batch("b2", [("c", ["b"])], deps=["b1"])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert result.ok and result.findings == ()
    assert result.order == ("a", "b", "c")


def test_ties_break_by_batch_position_then_unit_position():
    plan = make_plan([batch("b1", [("x", []), ("y", ["z"]), ("z", [])]), batch("b2", [("w", [])])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert result.order == ("x", "z", "y", "w")


def test_order_is_empty_when_not_ok():
    plan = make_plan([batch("b1", [("a", []), ("a", [])])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert not result.ok and result.order == ()


def test_cycle_through_a_batch_prerequisite_names_the_path():  # SCN-YOLO-03
    plan = make_plan([batch("b1", [("a", ["c"])]), batch("b2", [("c", [])], deps=["b1"])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    cycle = [f for f in result.findings if f.code == "cycle"]
    assert len(cycle) == 1
    assert "a -> c -> b1 -> a" in cycle[0].text


def test_cycle_between_units():
    plan = make_plan([batch("b1", [("a", ["b"]), ("b", ["a"])])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert "a -> b -> a" in [f for f in result.findings if f.code == "cycle"][0].text


def test_target_mismatch_has_the_exact_text():  # SCN-YOLO-05
    plan = make_plan([batch("b1", [("a", [])])], target="main")
    result = admit(plan, known_units=infos(plan), cfg=cfg(base="l4/main"))
    found = [f for f in result.findings if f.code == "target_mismatch"]
    assert [f.text for f in found] == ["the plan targets main, the base branch is l4/main"]
    assert not result.ok


def test_duplicate_unit_id_and_duplicate_batch_id():
    plan = make_plan([batch("b1", [("a", [])]), batch("b1", [("a", [])])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert sorted(f.subject for f in result.findings if f.code == "duplicate_id") == ["a", "b1"]


def test_unknown_unit():
    plan = make_plan([batch("b1", [("a", []), ("ghost", [])])])
    known = infos(plan)
    del known["ghost"]
    result = admit(plan, known_units=known, cfg=cfg())
    assert [(f.code, f.subject) for f in result.findings] == [("unknown_unit", "ghost")]


def test_unknown_dependency_for_a_unit_and_for_a_batch():
    plan = make_plan([batch("b1", [("a", ["nope"])], deps=["nobatch"])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert sorted((f.code, f.subject) for f in result.findings) == [
        ("unknown_dependency", "a"),
        ("unknown_dependency", "b1"),
    ]


def test_self_dependency_for_a_unit_and_for_a_batch():
    plan = make_plan([batch("b1", [("a", ["a"])], deps=["b1"])])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert sorted((f.code, f.subject) for f in result.findings) == [("self_dependency", "a"), ("self_dependency", "b1")]


def test_unknown_profile_unit_refuses_none_and_batch_accepts_it():
    plan = make_plan([{"id": "b1", "acceptance_profile": "none", "units": [{"id": "a", "acceptance_profile": "none"}]}])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert [(f.code, f.subject) for f in result.findings] == [("unknown_profile", "a")]


def test_profile_from_config_is_known_for_units_and_batches():
    plan = make_plan([{"id": "b1", "acceptance_profile": "fast", "units": [{"id": "a", "acceptance_profile": "fast"}]}])
    assert admit(plan, known_units=infos(plan), cfg=cfg(profiles={"fast": ["lint"]})).ok


def test_unknown_batch_profile():
    plan = make_plan([{"id": "b1", "acceptance_profile": "slow", "units": [{"id": "a"}]}])
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert [(f.code, f.subject) for f in result.findings] == [("unknown_profile", "b1")]


def test_empty_plan():
    plan = make_plan([])
    assert codes(admit(plan, known_units={}, cfg=cfg())) == ["empty_plan"]
    plan = make_plan([{"id": "b1", "units": []}])
    assert codes(admit(plan, known_units={}, cfg=cfg())) == ["empty_plan"]


def test_merge_policy_auto_needs_the_config():
    plan = make_plan([batch("b1", [("a", [])])], merge="auto")
    assert codes(admit(plan, known_units=infos(plan), cfg=cfg(policy="human"))) == ["merge_policy"]
    assert admit(plan, known_units=infos(plan), cfg=cfg(policy="auto")).ok


def test_open_questions():
    plan = make_plan([batch("b1", [("a", [])])])
    known = infos(plan, a=UnitInfo(id="a", folder="f", open_questions=("which db?",)))
    assert codes(admit(plan, known_units=known, cfg=cfg())) == ["open_questions"]


def test_intake_failure_carries_the_detail():
    plan = make_plan([batch("b1", [("a", [])])])
    known = infos(plan, a=UnitInfo(id="a", folder="f", intake_ok=False, intake_detail="no tasks.md"))
    result = admit(plan, known_units=known, cfg=cfg())
    assert codes(result) == ["intake"] and "no tasks.md" in result.findings[0].text


def test_finished_units_cannot_be_planned():
    plan = make_plan([batch("b1", [("a", []), ("b", [])])])
    known = infos(
        plan, a=UnitInfo(id="a", folder="f", phase="merged"), b=UnitInfo(id="b", folder="f", phase="archived")
    )
    assert codes(admit(plan, known_units=known, cfg=cfg())) == ["finished", "finished"]


def test_external_dependencies():
    plan = make_plan([batch("b1", [("a", [])])])
    plan = plan.model_copy(update={"external_dependencies": [{"plan": "old"}]})  # load_plan refuses it earlier
    result = admit(plan, known_units=infos(plan), cfg=cfg())
    assert codes(result) == ["external_dependencies"]
    assert result.findings[0].text == "external dependencies are not supported in this version"


def test_a_unit_waits_for_all_units_of_a_prerequisite_batch():
    plan = make_plan([batch("b1", [("a", []), ("b", [])]), batch("b2", [("c", [])], deps=["b1"])])
    assert admit(plan, known_units=infos(plan), cfg=cfg()).order == ("a", "b", "c")
