# ruff: noqa: F811
"""`l4 yolo go` (L4-YOLO-086): the activation, the part a person's run reaches."""

from l4.yolo.digest import plan_digest

from .yolo_actor import person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, world  # noqa: F401


def reviewed(world):
    """Plan `p1` pushed, the checkout up to date, admitted and reviewed READY at the digests of the origin."""
    world.push_plan()
    world.pull()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())


def test_a_person_activates_a_reviewed_ready_plan(world, forge, person, capsys):
    """SCN-YOLO-200 (the part after the push)."""
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert person == []  # activation asks nothing
    activated = [e for e in world.events() if e.type == "plan.activated"]
    assert len(activated) == 1 and activated[0].data["reason"] == "ship it"
    lines = out.splitlines()
    heads = [line.split(":")[0] for line in lines if not line.startswith(" ") and not line.startswith("Next:")]
    assert heads == ["preflight", "push", "check", "review", "findings", "accept", "activate"]
    assert "preflight: ok" in lines[0] and "activate: done" in out
    assert "check: ok: admitted at origin/main " in out
    assert "review: ok: reviewed at " in out and "accept: skipped" in out
    assert [line for line in lines if line.startswith("Next:")] == ["Next: l4 yolo status p1"]
    assert lines[-1] == "Next: l4 yolo status p1"
    assert "  p1: activated on main" in out  # what `l4 yolo activate` printed, indented under the step
    assert [c.args for c in forge.called("start_run")] == [("main",)]


def test_a_second_run_reports_the_active_plan(world, forge, person, capsys):
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    capsys.readouterr()
    head = world.store().read().head
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert "activate: ok: active since " in out and "review: skipped" in out
    assert out.splitlines()[-1] == "Next: l4 yolo status p1"
    assert world.store().read().head == head
