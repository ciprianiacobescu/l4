# ruff: noqa: F811
"""`l4 yolo go` review (L4-YOLO-084; SCN-YOLO-216 to -221): a current review is reused, `--local` reviews here, a
force acceptance needs no review; CI reviews (the bounded wait) are the other tests of this file."""

from l4.availability.errors import RoleUnavailable
from l4.yolo.digest import plan_digest
from l4.yolo.model import Verdict

from .test_yolo_commands_activate import fake_judge  # noqa: F401
from .yolo_actor import person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, world  # noqa: F401


def no_model(monkeypatch):
    class Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no model")

    def boom(*args, **kwargs):
        raise AssertionError("no model")

    monkeypatch.setattr("l4.yolo.readiness.Factory", Boom)
    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", boom)


def committed(world) -> None:
    world.push_plan()
    world.pull()


def next_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("Next:")]


def test_a_current_review_is_reused(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-216."""
    no_model(monkeypatch)
    committed(world)
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    assert world.l4("go", "p1", "--reason", "R") == 0
    out = capsys.readouterr().out
    assert "review: ok: reviewed at 2026-10-14T10:00:00Z (ci): 3 READY, 0 not READY" in out
    assert [c.args for c in forge.called("start_run")] == [("main",)]  # the activation's run, never a review's
    assert world.kinds() == ["plan.admitted", "plan.reviewed", "plan.activated"]


def test_local_reviews_here(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-220, the positive half."""
    committed(world)
    fake_judge(monkeypatch, {}, batches={"b1": Verdict("READY")})
    assert world.l4("go", "p1", "--reason", "R", "--local") == 0
    out = capsys.readouterr().out
    reviewed = [e for e in world.events() if e.type == "plan.reviewed"]
    assert len(reviewed) == 1 and reviewed[0].data["source"] == "local"
    assert "review: done: p1: reviewed here" in out
    assert world.kinds()[-1] == "plan.activated"


def test_local_with_a_judge_that_cannot_run_stops_with_25(world, forge, person, monkeypatch, capsys):
    committed(world)

    def down(*args, **kwargs):
        raise RoleUnavailable("judges", "no profile is available")

    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", down)
    assert world.l4("go", "p1", "--reason", "R", "--local") == 25
    out = capsys.readouterr().out
    assert "review: stopped: review: no judge could answer, nothing was recorded" in out
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R"]
    assert world.kinds() == []


def test_a_covering_force_acceptance_skips_the_review(world, forge, person, monkeypatch, capsys):
    committed(world)
    no_model(monkeypatch)
    assert world.l4("accept", "p1", "--all", "--force", "--reason", "the judge is down", "--yes") == 0
    capsys.readouterr()
    assert world.l4("go", "p1", "--reason", "R") == 0
    out = capsys.readouterr().out
    assert "review: skipped: force-accepted: no review is needed" in out
    assert "findings: ok" in out and "activate: done" in out
    activated = world.events()[-1]
    assert activated.type == "plan.activated" and activated.data["review"] == "force_accepted"
    assert [c.args for c in forge.called("start_run")] == [("main",)]
