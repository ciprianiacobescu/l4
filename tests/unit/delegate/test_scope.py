"""Which units the delegate may answer for (delegate-answers 9.1; L4-DLG-001, D1; SCN-DLG-03/04/05)."""

import json

from l4.config.schema import DelegateCfg
from l4.delegate.scope import PlansView, in_scope, plan_cost
from l4.yolo.model import PlanState
from l4.yolo.plans import _plan_file

A, B, C = "openspec:a", "openspec:b", "openspec:c"


def plan_file(plan_id, units, target="main"):
    text = json.dumps(
        {
            "schema": "l4/delivery-plan@1", "plan_id": plan_id, "target": target, "merge": "human",
            "batches": [{"id": "b1", "units": [{"id": u} for u in units]}],
        }
    )  # fmt: skip
    return _plan_file(f".l4/plans/{plan_id}.json", text)


def view(files=(), states=None, hold=()):
    return PlansView(tuple(files), dict(states or {}), "main", tuple(hold))


def state(plan_id, status, current=None):
    return PlanState(plan_id=plan_id, status=status, current=current)


YOLO = DelegateCfg(enabled=True, scope="yolo")
ALL = DelegateCfg(enabled=True, scope="all")


def test_scope_yolo():  # SCN-DLG-03
    plans = view([plan_file("p1", [A, B])], {"p1": state("p1", "active", A)})
    assert in_scope(A, plans, YOLO)  # the current unit of an active plan
    assert not in_scope(B, plans, YOLO)  # a later unit of the plan is not current
    waiting = view([plan_file("p1", [A, B])], {"p1": state("p1", "waiting", A)})
    assert in_scope(A, waiting, YOLO)  # a waiting plan is the very case the delegate serves
    assert in_scope(C, view(), ALL) and not in_scope(C, view(), YOLO)  # a unit in no plan file: scope all only
    assert in_scope("openspec:a-fix-1", plans, YOLO, fix_of=A)  # the fix unit follows its parent
    assert not in_scope("openspec:b-fix-1", plans, YOLO, fix_of=B)


def test_scope_all():  # SCN-DLG-04
    quiet = view([plan_file("p1", [A])], {"p1": state("p1", "completed")})
    assert in_scope(C, quiet, ALL)  # no plan is active on the target
    assert in_scope(C, view([plan_file("p1", [A])], {"p1": state("p1", "stopped", A)}), ALL)
    assert in_scope(A, view([plan_file("p1", [A])], {"p1": state("p1", "active", A)}), ALL)  # still the current unit


def test_an_active_plan_keeps_other_units_out():  # SCN-DLG-05, L4-YOLO-010
    plans = view([plan_file("p1", [A])], {"p1": state("p1", "active", A)})
    assert not in_scope(C, plans, ALL)
    other_target = view([plan_file("p1", [A], target="release")], {"p1": state("p1", "active", A)})
    assert in_scope(C, other_target, ALL)  # an active plan on another target does not keep this one's units out


def test_held_stopped_cancelled_and_finished_are_out():
    for status in ("stopped", "cancelled", "reviewed", "new"):
        plans = view([plan_file("p1", [A])], {"p1": state("p1", status, A)})
        assert not in_scope(A, plans, ALL), status
    assert not in_scope(C, view(hold=["openspec:c"]), ALL)  # yolo.hold, no plan plans it
    assert in_scope(C, view(hold=["openspec:x*"]), ALL)
    plans = view([plan_file("p1", [A])], {"p1": state("p1", "active", A)})
    for phase in ("merged", "archived", "abandoned"):
        assert not in_scope(A, plans, ALL, phase=phase), phase
    assert not in_scope(A, plans, DelegateCfg(enabled=False, scope="all"))  # off by default


# -- the plan's share of cost (SCN-DLG-28) -------------------------------------------------------------------------


def costs(**by_unit):
    return lambda unit: by_unit.get(unit.partition(":")[2], 0.0)


def test_the_plan_cost_is_the_limit_in_force_and_the_delegate_cost_of_its_units():
    from l4.delegate.limits import PlanCost, limit_reached

    plans = view(
        [plan_file("p1", [A, B])],
        {"p1": PlanState(plan_id="p1", status="active", current=A, limits={"max_cost_usd": 40.0})},
    )
    found = plan_cost(plans, A, costs(a=6.0, b=2.5))
    assert found == PlanCost(40.0, 8.5)
    reason = limit_reached("Q-001", ["1.1"], None, [], found, DelegateCfg())  # share 0.25 of 40 = 10
    assert reason == "the delegate's share of the plan's cost is used ($8.50 of $10.00)"
    extended = PlanState(plan_id="p1", status="active", current=A, limits={"max_cost_usd": 40.0})
    extended.extended.cost_usd = 20.0  # `l4 yolo resume --extend`: the limit in force counts it
    assert plan_cost(view([plan_file("p1", [A])], {"p1": extended}), A, costs(a=1.0)) == PlanCost(60.0, 1.0)


def test_no_live_plan_and_no_cost_limit_give_no_share():
    from l4.delegate.limits import PlanCost

    unlimited = view([plan_file("p1", [A])], {"p1": state("p1", "active", A)})
    assert plan_cost(unlimited, A, costs(a=9.0)) == PlanCost(None)  # the ledgers are not even read
    stopped = view(
        [plan_file("p1", [A])], {"p1": PlanState(plan_id="p1", status="stopped", limits={"max_cost_usd": 5})}
    )
    assert plan_cost(stopped, A, costs(a=9.0)) is None
    assert plan_cost(view(), C, costs()) is None  # a unit in no plan
