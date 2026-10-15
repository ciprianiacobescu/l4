# ruff: noqa: F811
"""`l4 status` shows one line per plan that is not final (L4-YOLO-015, yolo-mode D12), from the plan refs the checkout
has: no network."""

import json

from l4.vcs.git import Git
from l4.yolo.commands import plan_lines

from ..yolo.yolo_cmd_world import A, B, ev, plan_doc, world  # noqa: F401


def fetch_plan(world, plan_id="p1"):
    """What an operator's checkout holds after it has read the plan ref once."""
    world.clone.run("fetch", "origin", f"+refs/l4/plans/{plan_id}:refs/l4/plans/{plan_id}")


def test_an_active_plan_has_a_line_above_the_table(world, capsys):
    world.push_plan()
    limits = {"max_cost_usd": 40.0, "max_unit_attempts": 2}
    charged = ev("plan.charged", unit=A, cost_usd=12.4, runs=2, attempts=1)
    world.seed(
        "p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits=limits),
        ev("unit.dispatched", unit=A), charged,
    )  # fmt: skip
    world.pull()
    fetch_plan(world)
    assert world.l4_raw("status") == 0
    first, header = capsys.readouterr().out.splitlines()[:2]
    assert first == "plan p1: active, unit openspec:add-greeting (-), 0/2 integrated, $12.40/$40.00"
    assert header.startswith("UNIT")


def test_the_line_counts_integrated_units_and_shows_the_phase_of_the_current_one(world):
    world.push_plan(plan_doc(limits={}))
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits={}),
               ev("unit.integrated", unit=A, revision="r"), ev("unit.dispatched", unit=B))  # fmt: skip
    world.pull()
    fetch_plan(world)
    git = Git(world.app.repo, environ=world.app.environ)
    assert plan_lines(world.app.repo, git, {B: "in_review"}) == [
        f"plan p1: active, unit {B} (in_review), 1/2 integrated, $0.00/unlimited"
    ]


def test_a_final_plan_has_no_line(world):
    world.push_plan()
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits={}),
               ev("plan.cancelled", by="a", reason="r"))  # fmt: skip
    fetch_plan(world)
    assert plan_lines(world.app.repo, Git(world.app.repo, environ=world.app.environ), {}) == []


def test_without_a_plan_the_output_is_unchanged(world, capsys):
    assert world.l4_raw("status") == 0
    assert capsys.readouterr().out.startswith("UNIT")
    assert world.l4_raw("status", "--json") == 0
    assert "plans" not in json.loads(capsys.readouterr().out)


def test_json_carries_the_plan_lines(world, capsys):
    world.push_plan()
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits={}))
    world.pull()
    fetch_plan(world)
    assert world.l4_raw("status", "--json") == 0
    assert json.loads(capsys.readouterr().out)["plans"][0].startswith("plan p1: active")


def test_a_plan_that_is_not_active_says_how_many_units_it_holds(world):
    """SCN-ADO-39."""
    world.push_plan()
    world.seed("p1", ev("plan.refused", plan_digest="x", findings=[]))
    world.pull()
    fetch_plan(world)
    git = Git(world.app.repo, environ=world.app.environ)
    (line,) = plan_lines(world.app.repo, git, {})
    assert line == (
        "plan p1: refused (holds 2 units; none of them runs until the plan is fixed, completed or its file is "
        "removed), 0/2 integrated, $0.00/$40.00"
    )


def test_an_active_plan_does_not_say_it_holds_units(world):
    world.push_plan()
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits={}))
    world.pull()
    fetch_plan(world)
    git = Git(world.app.repo, environ=world.app.environ)
    (line,) = plan_lines(world.app.repo, git, {})
    assert "holds" not in line
