"""`l4 plan` with delivery plans (L4-YOLO-010, L4-YOLO-015, SCN-YOLO-30): a held unit shows why and is not actionable,
a waiting unit of the active plan shows what it waits for, a unit outside the active plan says so. Read-only: the plan
state is the local `refs/l4/plans/*`."""

import json

import pytest

import l4.planner as planner
from l4.exitcodes import ExitCode

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


@pytest.fixture
def plan(world, monkeypatch, capsys):
    snapshots = {}
    monkeypatch.setattr(planner, "load_app_config", lambda app: (app, world.cfg))
    monkeypatch.setattr(planner, "snapshots", lambda app, cfg, units: [s for _, s in world.found(snapshots)])

    def go():
        result = planner.run_plan(world.app, units=(), as_json=True, probe=False, sweep=False, detailed_exitcode=True)
        rows = {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}
        return result, rows

    go.snapshots = snapshots
    return go


def test_no_plan_file_leaves_the_plan_as_it_was(plan):
    result, rows = plan()
    assert rows[A]["reason"] == "pending tasks" and rows[A]["actionable"] is True
    assert result.code == ExitCode.CONTINUE


def test_scn_yolo_30_held_units_show_the_plan_and_its_status(world, plan):
    world.plan()
    world.reviewed()
    result, rows = plan()
    assert rows[A]["reason"] == rows[B]["reason"] == "held by plan p1 (reviewed)"
    assert not rows[A]["actionable"] and not rows[B]["actionable"] and rows[A]["next_action"] == "none"
    assert result.code == ExitCode.OK and result.actionable == ()  # nothing to run


def test_a_unit_that_waits_for_another_shows_what_it_waits_for(world, plan):
    world.plan()
    world.activate()
    result, rows = plan()
    assert rows[A]["actionable"] is True and rows[A]["reason"] == "pending tasks"  # the eligible unit
    assert rows[B]["reason"] == "waits for openspec:a (not integrated)" and rows[B]["actionable"] is False
    assert result.actionable == (A,)


def test_a_unit_outside_the_active_plan_is_not_actionable(world, plan):
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    world.activate(order=[A])
    _, rows = plan()
    assert rows[B]["reason"] == "not in the active plan p1" and rows[B]["actionable"] is False


def test_a_stopped_plan_holds_its_units_and_frees_the_others(world, plan):
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    world.activate(order=[A])
    world.seed(ev("plan.stopped", reason="unit_halted", unit=A))
    _, rows = plan()
    assert rows[A]["reason"] == "held by plan p1 (stopped)" and rows[B]["actionable"] is True


def test_the_plan_reads_the_local_refs_and_writes_nothing(world, plan):
    world.plan()
    world.activate()
    before = world.git.run("for-each-ref").stdout
    plan()
    assert world.git.run("for-each-ref").stdout == before


# --- yolo.hold (L4-ADO-011, SCN-ADO-33..35) -------------------------------------------------------------------------


def hold(world, *patterns):
    world.cfg = world.cfg.model_copy(update={"yolo": world.cfg.yolo.model_copy(update={"hold": list(patterns)})})


def test_scn_ado_33_l4_plan_shows_a_held_unit_and_nothing_to_run(world, plan):
    hold(world, A, B)
    result, rows = plan()
    assert rows[A]["reason"] == rows[B]["reason"] == "held by yolo.hold"
    assert not rows[A]["actionable"] and rows[A]["next_action"] == "none"
    assert result.actionable == ()


def test_a_merged_unit_is_not_shown_held(world, plan):
    hold(world, "*")
    plan.snapshots["b"] = world.snapshot("b", "merged")
    _, rows = plan()
    assert rows[A]["reason"] == "held by yolo.hold" and rows[B]["reason"] != "held by yolo.hold"


def test_scn_ado_33_the_step_allows_only_the_units_not_held_and_calls_no_judge(world):
    hold(world, A)
    step = world.step()
    assert step.allow == frozenset({B})
    assert step.refusals == {A: "is held by yolo.hold"}
    assert step.plan_id is None and not step.actions
    assert world.kinds() == [] and world.judge.requests == []


def test_every_unit_held_allows_none(world):
    hold(world, "openspec:*")
    step = world.step()
    assert step.allow == frozenset() and set(step.refusals) == {A, B}


def test_an_empty_hold_leaves_the_step_as_it_was(world):
    assert world.step().allow is None


def test_a_merged_unit_is_allowed_by_the_step(world):
    hold(world, "*")
    step = world.step({"b": world.snapshot("b", "merged")})
    assert step.allow == frozenset({B}) and A in step.refusals


def test_scn_ado_34_a_new_unit_runs_alone(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    hold(world, A, B)
    assert world.step().allow == frozenset({unit_id("c")})


def test_scn_ado_35_a_pattern_holds_a_new_unit_until_a_plan_lists_it(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    hold(world, "*")
    C = unit_id("c")
    first = world.step()
    assert first.allow == frozenset() and first.refusals[C] == "is held by yolo.hold"
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": C}]}])
    world.activate(order=[C])
    step = world.step()
    assert step.allow == frozenset({C}) and step.plan_id == "p1"  # the plan lists c: it follows the plan
    assert step.refusals[A] == "is held by yolo.hold"  # a and b stay held, not 'outside the active plan'


def test_a_named_run_of_a_held_unit_is_refused_with_the_reason(world):
    hold(world, A)
    step = world.step(read_only=True)
    assert step.allow is not None and A not in step.allow
    assert step.refusals[A] == "is held by yolo.hold"


def exclude_in_plan(world, excluded: list[str], planned: list[str]) -> None:
    import json as _json

    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": u} for u in planned]}])
    path = ".l4/plans/p1.json"
    doc = _json.loads(world.git.run("show", f"HEAD:{path}").stdout)
    doc["exclude"] = [{"id": u, "reason": "not in this plan"} for u in excluded]
    world.commit({path: _json.dumps(doc, indent=2) + "\n"}, "exclude")
    world.push_main()


def test_a_unit_a_plan_excludes_and_yolo_hold_matches_stays_held_before_and_after_activation(tmp_path):
    """Round-2 review: the two excluded-and-held units of a consumer ran after a plan review."""
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    C = unit_id("c")
    hold(world, A, B)
    exclude_in_plan(world, [A, B], [C])
    first = world.step()  # a plan that is only reviewed
    assert A not in (first.allow or ()) and B not in (first.allow or ())
    assert first.refusals[A] == first.refusals[B] == "is held by yolo.hold"
    world.activate(order=[C])
    step = world.step()
    assert step.allow == frozenset({C})
    assert step.refusals[A] == step.refusals[B] == "is held by yolo.hold"


def test_a_unit_a_plan_plans_and_yolo_hold_matches_follows_the_plan(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    C = unit_id("c")
    hold(world, C)
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": C}]}])
    world.activate(order=[C])
    step = world.step()
    assert step.allow == frozenset({C}) and step.plan_id == "p1"
