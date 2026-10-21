"""next_eligible (design D2, L4-YOLO-010): direct and batch prerequisites, accepted batches, the waiting reasons."""

import json

from l4.yolo.admit import next_eligible, plan_order
from l4.yolo.model import Plan, PlanState, load_plan


def make_plan(batches) -> Plan:
    raw = {"schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "t", "merge": "human", "batches": batches}
    plan = load_plan(json.dumps(raw))
    assert isinstance(plan, Plan)
    return plan


def state(plan: Plan, integrated=(), accepted=(), current=None) -> PlanState:
    return PlanState(
        plan_id="p1",
        status="active",
        order=list(plan_order(plan)),
        integrated={u: "rev" for u in integrated},
        accepted_batches={b: "rev" for b in accepted},
        current=current,
    )


A_B = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}]}])


def test_a_then_b():
    got = next_eligible(A_B, state(A_B), {})
    assert got.unit == "a" and got.waiting == {"b": "waits for a (not integrated)"}
    got = next_eligible(A_B, state(A_B, integrated=["a"]), {})
    assert got.unit == "b" and got.waiting == {}


def test_a_and_b_then_c():
    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}, {"id": "c", "depends_on": ["a", "b"]}]}])
    got = next_eligible(plan, state(plan, integrated=["a"]), {})
    assert got.unit == "b" and got.waiting["c"] == "waits for b (not integrated)"
    got = next_eligible(plan, state(plan, integrated=["a", "b"]), {})
    assert got.unit == "c"


def two_batches(profile="all"):
    return make_plan(
        [
            {"id": "b1", "acceptance_profile": profile, "units": [{"id": "a"}, {"id": "b"}]},
            {"id": "b2", "depends_on": ["b1"], "units": [{"id": "c"}]},
        ]
    )


def test_batch_prerequisite_needs_all_its_units_integrated():
    plan = two_batches()
    got = next_eligible(plan, state(plan, integrated=["a"]), {})
    assert got.unit == "b" and got.waiting == {"c": "waits for b (not integrated)"}


def test_batch_prerequisite_needs_acceptance_when_it_has_a_profile():
    plan = two_batches("all")
    got = next_eligible(plan, state(plan, integrated=["a", "b"]), {})
    assert got.unit is None and got.waiting == {"c": "waits for batch b1 (acceptance)"}
    got = next_eligible(plan, state(plan, integrated=["a", "b"], accepted=["b1"]), {})
    assert got.unit == "c"


def test_batch_with_profile_none_counts_as_accepted_once_its_units_are_integrated():
    plan = two_batches("none")
    assert next_eligible(plan, state(plan, integrated=["a", "b"]), {}).unit == "c"


def test_integrated_unit_is_never_eligible_and_all_done_gives_none():
    plan = two_batches("none")
    got = next_eligible(plan, state(plan, integrated=["a", "b", "c"]), {})
    assert got.unit is None and got.waiting == {}


def test_serial_current_unit_is_the_only_candidate():
    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}]}])
    got = next_eligible(plan, state(plan, current="b"), {"b": "in_review"})
    assert got.unit == "b" and got.waiting == {"a": "waits for its turn: b runs first (one unit at a time)"}


def test_no_current_second_independent_unit_waits_for_the_first():
    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}]}])
    got = next_eligible(plan, state(plan), {})
    assert got.unit == "a" and got.waiting == {"b": "waits for its turn: a runs first (one unit at a time)"}


def test_a_current_unit_already_integrated_is_ignored():
    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}]}])
    got = next_eligible(plan, state(plan, integrated=["a"], current="a"), {})
    assert got.unit == "b"


def test_a_merged_unit_without_current_is_not_dispatched_again():
    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}]}])
    got = next_eligible(plan, state(plan), {"a": "merged"})
    assert got.unit == "b" and "a" in got.waiting


def test_order_without_state_order_is_computed():
    plan = two_batches("none")
    st = PlanState(plan_id="p1", status="active")
    assert next_eligible(plan, st, {}).unit == "a"


# --- review #13 (R10) -----------------------------------------------------------------------------------------------


def test_merged_not_integrated_lists_every_merged_unit_in_plan_order():
    from l4.yolo.admit import merged_not_integrated

    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]}])
    st = state(plan, integrated=["a"])
    st.merged["c"] = "sha-c"  # merged by the step
    got = merged_not_integrated(plan, st, {"a": "merged", "b": "merged", "c": "merged", "d": "in_review"})
    assert got == ["b", "c"]  # a is integrated; b was merged by a person (phase); d is not merged


def test_merged_not_integrated_counts_an_archived_unit_and_ignores_units_outside_the_plan():
    from l4.yolo.admit import merged_not_integrated

    plan = make_plan([{"id": "b1", "units": [{"id": "a"}]}])
    assert merged_not_integrated(plan, state(plan), {"a": "archived", "zzz": "merged"}) == ["a"]
    assert merged_not_integrated(plan, state(plan), {}) == []
    assert merged_not_integrated(plan, state(plan, integrated=["a"]), {"a": "merged"}) == []


def test_a_merged_non_current_unit_is_named_while_another_unit_is_dispatched():  # review #13
    from l4.yolo.admit import merged_not_integrated

    plan = make_plan([{"id": "b1", "units": [{"id": "a"}, {"id": "b"}]}])
    phases = {"a": "merged"}
    assert next_eligible(plan, state(plan), phases).unit == "b"
    assert merged_not_integrated(plan, state(plan, current="b"), phases) == ["a"]  # the step post-checks it
