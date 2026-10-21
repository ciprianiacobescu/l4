# ruff: noqa: F811
"""`l4 yolo go` is safe to run again, to interrupt and to run at the same time (L4-YOLO-089; SCN-YOLO-232 to -235)."""

from l4 import cancel
from l4.yolo import commands
from l4.yolo.digest import plan_digest
from l4.yolo.model import PlanMoved
from l4.yolo.store import PlanStore

from .test_yolo_go_accept import both_not_ready, kinds
from .test_yolo_go_activate import holding
from .test_yolo_go_review import Ci, no_model
from .yolo_actor import person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, world  # noqa: F401
from .yolo_review_events import TESTABILITY, two_rounds


def committed(world) -> None:
    world.push_plan()
    world.pull()


def next_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("Next:")]


def origin_main(world) -> str:
    return world.remote.rev_parse("refs/heads/main") or ""


def test_a_second_run_with_nothing_changed_does_nothing(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-232."""
    committed(world)
    two_rounds(world, [TESTABILITY], unit=B)
    no_model(monkeypatch)
    asked: list[object] = []
    monkeypatch.setattr("l4.yolo.go.start_run_result", lambda app, cfg: asked.append(1) or ("started", "x"))
    assert world.l4("go", "p1", "--reason", "R") == 26
    first = capsys.readouterr().out
    head, main = world.store().read().head, origin_main(world)
    assert world.l4("go", "p1", "--reason", "R") == 26
    second = capsys.readouterr().out
    assert next_lines(second) == next_lines(first) == ["Next: l4 yolo go p1 --reason R --accept-findings"]
    assert world.store().read().head == head and origin_main(world) == main
    assert asked == [] and forge.called("start_run") == []


# --- interrupted runs (SCN-YOLO-233) ----------------------------------------------------------------------------------


def test_an_interrupted_accept_goes_on(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-233, first part."""
    committed(world)
    both_not_ready(world)
    real, calls = commands.run_accept, []

    def interrupted(*args, **kwargs):
        calls.append(kwargs.get("subject"))
        if len(calls) == 2:
            raise cancel.RunCancelled()
        return real(*args, **kwargs)

    monkeypatch.setattr("l4.yolo.commands.run_accept", interrupted)
    argv = ("go", "p1", "--reason", "R", "--accept-findings", "--yes")
    try:
        assert world.l4(*argv) == 16
    finally:
        cancel.reset()
    assert [e.data["subject"] for e in kinds(world, "plan.accepted")] == [A] and kinds(world, "plan.activated") == []
    monkeypatch.setattr("l4.yolo.commands.run_accept", real)
    capsys.readouterr()
    assert world.l4(*argv) == 0
    assert [e.data["subject"] for e in kinds(world, "plan.accepted")] == [A, B]
    assert len(kinds(world, "plan.activated")) == 1
    assert "accept: done: accepted 1 subject(s)" in capsys.readouterr().out  # A's acceptance held: not recorded again


def test_an_interrupted_wait_goes_on(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-233, second part."""
    committed(world)
    ci = Ci(world, monkeypatch)

    def interrupted():
        raise cancel.RunCancelled()

    ci.on_sleep[1] = interrupted
    try:
        assert world.l4("go", "p1", "--reason", "R") == 16
    finally:
        cancel.reset()
    assert world.kinds() == []
    world.seed("p1", world.reviewed())  # CI recorded the review meanwhile
    capsys.readouterr()
    no_model(monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 0
    assert world.kinds() == ["plan.reviewed", "plan.activated"]
    assert ci.asked == ["main"]  # the review was there: the forge was not asked again


# --- the plan lease (SCN-YOLO-234, -235) ------------------------------------------------------------------------------


def lost_lease_first(world, monkeypatch, *, seeded=None):
    """`PlanStore.append` whose first call seeds `seeded` (what another run recorded) and loses the lease."""
    original, calls = PlanStore.append, []

    def append(self, events, *, files=None, expect):
        calls.append([e.type for e in events])
        if len(calls) == 1:
            if seeded is not None:
                seeded()
            raise PlanMoved("the plan ref moved")
        return original(self, events, files=files, expect=expect)

    monkeypatch.setattr(PlanStore, "append", append)
    return calls


def test_a_lost_lease_reads_again_and_records_nothing_twice(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-234."""
    committed(world)
    two_rounds(world, [TESTABILITY], unit=B)
    original, other = PlanStore.append, {}

    def race():  # the other run recorded the same acceptance of B first
        store = PlanStore(world.remote_clone(), "p1")
        latest = next(e for e in reversed(world.events()) if e.type == "plan.reviewed")
        row = latest.data["units"][B]
        original(store, [holding(B, row["findings"], row["material"], reason="R")], expect=store.read().head)
        other["done"] = True

    calls = lost_lease_first(world, monkeypatch, seeded=race)
    assert world.l4("go", "p1", "--reason", "R", "--accept-findings", "--yes") == 0
    out = capsys.readouterr().out
    assert other == {"done": True}
    assert [e.data["subject"] for e in kinds(world, "plan.accepted")] == [B]
    assert len(kinds(world, "plan.activated")) == 1
    assert "accept: ok: 1 acceptance(s) hold" in out and next_lines(out) == ["Next: l4 yolo status p1"]
    assert calls[0] == ["plan.accepted"]


def test_a_lease_lost_again_and_again_stops_with_28(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-235: three re-reads, the fourth lost lease stops the run."""
    committed(world)
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    attempts = []

    def always(self, events, *, files=None, expect):
        attempts.append([e.type for e in events])
        raise PlanMoved("the plan ref moved")

    monkeypatch.setattr(PlanStore, "append", always)
    assert world.l4("go", "p1", "--reason", "R") == 28
    out = capsys.readouterr().out
    assert attempts == [["plan.activated"]] * 4
    assert "the plan moved" in out and next_lines(out) == ["Next: l4 yolo go p1 --reason R"]
    monkeypatch.undo()
    assert kinds(world, "plan.activated") == []


def test_no_progress_stops_with_28(world, forge, person, monkeypatch, capsys):
    """The guard of D2: a command that records nothing is not run again."""
    committed(world)
    runs = []
    monkeypatch.setattr("l4.yolo.commands.run_review", lambda app, **kw: runs.append(kw) or commands.ExitCode.OK)
    assert world.l4("go", "p1", "--reason", "R", "--local") == 28
    out = capsys.readouterr().out
    assert len(runs) == 1
    assert "no progress: review_local ran and the plan did not change" in out
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R --local"]
    assert world.kinds() == []
