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


# --- CI reviews with a bounded wait (D6.5) ----------------------------------------------------------------------


def head_of(world) -> str | None:
    return world.store().read().head


class Ci:
    """The fake forge and the fake CI of the wait: `asked` lists the forge's calls, `sleeps` the seconds slept, and the
    n-th sleep runs `on_sleep[n]` (a plan event seeded as CI would record it); the clock adds the slept seconds."""

    def __init__(self, world, monkeypatch, *, answer="started"):
        from l4.yolo import go

        self.world, self.asked, self.sleeps, self.on_sleep, self.now = world, [], [], {}, 0.0

        def fake(app, cfg):
            self.asked.append(cfg.forge.base_branch)
            return answer, {"started": "run started on main"}.get(answer, "start a run with: gh workflow run l4.yml")

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
            action = self.on_sleep.get(len(self.sleeps))
            if action is not None:
                action()

        monkeypatch.setattr(go, "start_run_result", fake)
        monkeypatch.setattr(go, "_sleep", sleep)
        monkeypatch.setattr(go, "_clock", lambda: self.now)

    def records_review_at(self, n):
        self.on_sleep[n] = lambda: self.world.seed("p1", self.world.reviewed())


def test_ci_is_asked_and_awaited(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-217."""
    committed(world)
    ci = Ci(world, monkeypatch)
    ci.records_review_at(2)
    assert world.l4("go", "p1", "--reason", "R") == 0
    out = capsys.readouterr().out
    assert ci.asked == ["main"] and ci.sleeps == [15.0, 15.0]
    assert (
        "review: waiting: CI was asked at " in out
        and "(started); polling the plan ledger every 15s for up to 30m" in out
    )
    assert "review: done: reviewed in CI at 2026-10-14T10:00:00Z" in out
    assert world.kinds() == ["plan.reviewed", "plan.activated"]


def test_after_its_own_push_go_does_not_ask_the_forge(world, forge, person, monkeypatch, capsys):
    committed(world)
    ci = Ci(world, monkeypatch)
    ci.records_review_at(1)
    (world.app.repo / "docs").mkdir()
    (world.app.repo / "docs" / "note.md").write_text("a note\n", encoding="utf-8")
    world.clone.run("add", "docs/note.md")
    world.clone.run("commit", "--quiet", "-m", "a note")
    assert world.l4("go", "p1", "--reason", "R") == 0
    out = capsys.readouterr().out
    assert "push: done: pushed 1 commit(s)" in out and ci.asked == [] and ci.sleeps == [15.0]
    assert "the push started CI on main" in out


def test_a_skip_ci_head_asks_the_forge(world, forge, person, monkeypatch, capsys):
    committed(world)
    ci = Ci(world, monkeypatch)
    ci.records_review_at(1)
    (world.app.repo / "note.md").write_text("a note\n", encoding="utf-8")
    world.clone.run("add", "note.md")
    world.clone.run("commit", "--quiet", "-m", "a note [skip ci]")
    assert world.l4("go", "p1", "--reason", "R") == 0
    assert ci.asked == ["main"]
    assert "push: done" in capsys.readouterr().out


def test_the_wait_is_bounded(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-218."""
    from l4.yolo import go

    committed(world)
    ci = Ci(world, monkeypatch)
    polls = []
    real = go._poll
    monkeypatch.setattr(go, "_poll", lambda *a, **k: polls.append(1) or real(*a, **k))
    assert world.l4("go", "p1", "--reason", "R", "--wait", "1m") == 24
    out = capsys.readouterr().out
    assert len(polls) <= 5 and ci.sleeps == [15.0] * 4 and ci.asked == ["main"]
    assert "review: pending: CI was asked at " in out and "no review recorded within 1m" in out
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R --wait 1m"]
    assert "findings:" not in out and head_of(world) is None  # nothing is recorded


def test_wait_zero_asks_and_returns(world, forge, person, monkeypatch, capsys):
    committed(world)
    ci = Ci(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--wait", "0") == 24
    out = capsys.readouterr().out
    assert ci.asked == ["main"] and ci.sleeps == [] and "review: pending" in out
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R --wait 0"]
    assert world.l4("go", "p1", "--reason", "R", "--wait", "0") == 24  # run again: asked again, still nothing recorded
    assert ci.asked == ["main", "main"] and head_of(world) is None


def test_no_run_can_be_asked(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-219."""
    from l4.config.redaction import load_app_config
    from l4.state.retry import how_to_start

    committed(world)
    ci = Ci(world, monkeypatch, answer="unsupported")
    assert world.l4("go", "p1", "--reason", "R") == 24
    out = capsys.readouterr().out
    app, cfg = load_app_config(world.app)
    assert ci.sleeps == [] and ci.asked == ["main"]
    assert next_lines(out) == [f"Next: {how_to_start(app, cfg, 'main')}"]
    assert "then run the go command again" in out and "review: pending" in out


def test_a_ci_refusal_during_the_wait_is_not_admitted(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-221."""
    committed(world)
    ci = Ci(world, monkeypatch)
    finding = {"code": "open_questions", "subject": A, "text": f"{A} has open questions"}
    ci.on_sleep[1] = lambda: world.seed(
        "p1", ev("plan.refused", plan_digest=plan_digest(world.plan_text), findings=[finding])
    )
    assert world.l4("go", "p1", "--reason", "R") == 22
    out = capsys.readouterr().out
    assert "review: stopped: open_questions: " in out and "has open questions" in out
    assert next_lines(out) == ["Next: l4 yolo check p1 --worktree"] and ci.sleeps == [15.0]
    assert world.kinds() == ["plan.refused"]


def test_each_poll_checks_for_a_cancel(world, forge, person, monkeypatch, capsys):
    from l4 import cancel

    committed(world)
    ci = Ci(world, monkeypatch)
    ci.on_sleep[1] = cancel.request
    try:
        assert world.l4("go", "p1", "--reason", "R") == 16
    finally:
        cancel.reset()
    assert world.kinds() == [] and ci.sleeps == [15.0]
