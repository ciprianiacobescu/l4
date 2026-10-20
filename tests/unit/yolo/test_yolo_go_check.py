# ruff: noqa: F811
"""`l4 yolo go` check (L4-YOLO-083; SCN-YOLO-213 to -215): the admission at the target and the plan's state."""

import json

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.yolo import commands
from l4.yolo.digest import plan_digest

from .yolo_actor import person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401

ACTIVATED = {"digests": {}, "limits": {}, "by": "alex@example.com", "reason": "r"}


def committed(world, doc=None) -> None:
    world.push_plan(doc)
    world.pull()


def activate(world) -> None:
    world.seed("p1", ev("plan.activated", plan_digest=plan_digest(world.plan_text), **ACTIVATED))


def no_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no model")

    monkeypatch.setattr("l4.yolo.readiness.Factory", boom)
    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", boom)


def next_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("Next:")]


def test_a_plan_not_admitted_stops_at_check(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-213."""
    no_model(monkeypatch)
    committed(world, plan_doc({A: [B], B: [A]}))
    head = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R") == 22
    out = capsys.readouterr().out
    assert "check: stopped: cycle:" in out
    assert next_lines(out) == ["Next: l4 yolo check p1 --worktree"]
    assert "review:" not in out
    assert world.store().read().head == head and forge.called("start_run") == []


def test_a_plan_with_no_file_stops_at_preflight_not_at_check(world, forge, person, capsys):
    committed(world)
    assert world.l4("go", "nope", "--reason", "R") == 20
    out = capsys.readouterr().out
    assert "plan_missing" in out and next_lines(out) == ["Next: l4 yolo draft nope"]


@pytest.mark.parametrize("closing", ["active", "waiting", "completed"])
def test_an_active_plan_is_reported_as_active(world, forge, person, monkeypatch, capsys, closing):
    """SCN-YOLO-214."""
    no_model(monkeypatch)
    committed(world)
    activate(world)
    if closing == "waiting":
        world.seed("p1", ev("plan.waiting", reason="run_not_started", detail="x"))
    if closing == "completed":
        world.seed("p1", ev("plan.completed", revision="abc"))
    head = world.store().read().head
    for _ in range(2):
        assert world.l4("go", "p1", "--reason", "R") == 0
        out = capsys.readouterr().out
        lines = out.splitlines()
        assert "check: ok: p1 is " + closing in out
        for step in ("review", "findings", "accept"):
            assert any(line.startswith(f"{step}: skipped") for line in lines), (step, out)
        if closing == "active":
            assert "activate: ok: active since 2026-10-14T10:00:00Z by alex@example.com" in out
        elif closing == "waiting":
            assert "activate: ok: waiting: run_not_started" in out
        else:
            assert "activate: ok: completed" in out
        assert next_lines(out) == [f"Next: l4 yolo {'report' if closing == 'completed' else 'status'} p1"]
        assert world.store().read().head == head
    assert forge.called("start_run") == []


def test_cancelled_and_limit_stops_stop_at_check(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-215."""
    no_model(monkeypatch)
    committed(world)
    activate(world)
    world.seed("p1", ev("plan.cancelled", by="alex@example.com", reason="no"))
    head = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R") == 23
    out = capsys.readouterr().out
    assert "check: stopped: none: the plan is cancelled" in out and next_lines(out) == ["Next: l4 yolo status p1"]
    assert world.store().read().head == head


def test_a_plan_stopped_for_a_limit_names_resume(world, forge, person, monkeypatch, capsys):
    no_model(monkeypatch)
    committed(world)
    activate(world)
    world.seed("p1", ev("plan.stopped", reason="limit_runs", detail="60 runs"))
    head = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R") == 23
    out = capsys.readouterr().out
    assert "l4 yolo resume p1" in out and next_lines(out) == ["Next: l4 yolo status p1"]
    assert world.store().read().head == head


def test_a_rejected_unit_with_an_unchanged_spec_stops_at_check(world, forge, person, monkeypatch, capsys):
    no_model(monkeypatch)
    committed(world)
    activate(world)
    world.seed("p1", ev("plan.stopped", reason="unit_rejected", detail="x", unit=A, digest=world.digest(A)))
    assert world.l4("go", "p1", "--reason", "R") == 23
    out = capsys.readouterr().out
    assert "was rejected" in out or "rejection" in out
    assert next_lines(out) == ["Next: l4 yolo status p1"]


def test_a_rejected_unit_with_a_changed_spec_goes_on(world, forge, person, monkeypatch, capsys):
    no_model(monkeypatch)
    committed(world)
    activate(world)
    world.seed("p1", ev("plan.stopped", reason="unit_rejected", detail="x", unit=A, digest="an-older-digest"))
    assert world.l4("go", "p1", "--reason", "R", "--wait", "0") != 23
    assert "review:" in capsys.readouterr().out


def test_a_rejected_unit_with_an_unchanged_spec_is_23_even_when_the_plan_has_a_finding(
    world, forge, person, monkeypatch, capsys
):
    """D5.3 comes before D5.4: the plan_state stop wins over an admission finding."""
    no_model(monkeypatch)
    committed(world, plan_doc({A: [B], B: [A]}))  # a cycle: an admission finding
    activate(world)
    world.seed("p1", ev("plan.stopped", reason="unit_rejected", detail="x", unit=A, digest=world.digest(A)))
    assert world.l4("go", "p1", "--reason", "R") == 23
    assert next_lines(capsys.readouterr().out) == ["Next: l4 yolo status p1"]


def test_only_an_admission_refusal_is_22(world, forge, person, monkeypatch, capsys):
    """A fault while the plan is read keeps its meaning (exit 1, the document and one Next), it is no `not_admitted`."""
    committed(world)

    def fault(*args, **kwargs):
        raise L4Exit(ExitCode.INTERNAL_ERROR, "fetch failed: the network is down")

    monkeypatch.setattr("l4.yolo.commands._admission_at", fault)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    assert (
        doc["steps"][2]["name"] == "check"
        and doc["exit"] == 1
        and doc["next_command"] == "l4 yolo go p1 --reason R --json"
    )
    assert doc["steps"][2]["status"] == "stopped" and "the network is down" in doc["steps"][2]["detail"]


def test_a_sync_refusal_in_the_middle_of_the_run_is_a_stop_with_the_document_and_a_next(
    world, forge, person, monkeypatch, capsys
):
    committed(world)
    real = commands._sync
    calls: list[int] = []

    def sync(ctx, who):
        calls.append(1)
        if len(calls) >= 2:  # the preflight's fetch worked; the one that reads the plan does not
            raise L4Exit(ExitCode.USAGE_ERROR, "go: origin/main is not on origin")
        return real(ctx, who=who)

    monkeypatch.setattr("l4.yolo.commands._sync", sync)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 28
    doc = json.loads(capsys.readouterr().out)
    assert doc["exit"] == 28 and doc["next_command"] == "git push -u origin main" and doc["next_by"] == "caller"
    assert doc["steps"][2]["status"] == "stopped" and "not on origin" in doc["steps"][2]["detail"]


def test_a_plan_with_an_unknown_unit_is_still_22(world, forge, person, monkeypatch, capsys):
    """The rejected-unit check runs before the admission findings are returned: an unknown unit must not break it."""
    no_model(monkeypatch)
    committed(world, plan_doc({"openspec:nope": []}))
    assert world.l4("go", "p1", "--reason", "R") == 22
    out = capsys.readouterr().out
    assert "nope" in out and next_lines(out) == ["Next: l4 yolo check p1 --worktree"]
