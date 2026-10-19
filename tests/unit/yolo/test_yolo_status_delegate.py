# ruff: noqa: F811
"""`l4 yolo status` names the delegate's decisions on the current unit, its cost against its share of the plan's cost
limit, and the idle runs (delegate-answers 14.1; L4-DLG-011, L4-YOLO-014; SCN-DLG-32, SCN-DLG-50)."""

import json
from datetime import UTC, datetime

import l4.yolo.commands as commands
from l4.state.ledger import LedgerEvent
from l4.yolo.digest import plan_digest

from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401

STAMP = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
REASON = "no document decides which tier"
LIMITS = {"max_cost_usd": 40.0, "max_runs": 10, "max_unit_attempts": 2, "deadline": None}


def activate(world, *events):
    world.push_plan()
    digest = plan_digest(world.plan_text)
    activated = ev("plan.activated", plan_digest=digest, digests={}, by="alex@example.com", reason="go", limits=LIMITS)
    world.seed("p1", ev("plan.admitted", plan_digest=digest, order=[A, B]), world.reviewed(), activated, *events)


def led(seq, type_, /, **data):
    return LedgerEvent(STAMP, "r-1", A, seq, type_, data)


DECISIONS = (
    led(1, "question.raised", id="Q-003", kind="technical"),
    led(2, "question.raised", id="Q-004", kind="product"),
    led(3, "delegate.result", question="Q-003", id="Q-003", status="answered", cost_usd=0.42, called=True),
    led(4, "budget.cost", usd=0.42, profile="delegate-opus", role="delegate", question="Q-003"),
    led(5, "delegate.result", question="Q-004", id="Q-004", status="escalated", reason=REASON, cost_usd=0.0),
)  # fmt: skip


def with_delegate(monkeypatch, events):
    real = commands._read_units

    def fake(ctx, rev, wanted, *, intake):
        units = real(ctx, rev, wanted, intake=intake)
        units.delegate[A] = tuple(events)
        return units

    monkeypatch.setattr(commands, "_read_units", fake)


def test_the_delegate_line_and_the_share(world, capsys, monkeypatch):  # SCN-DLG-32
    activate(world, ev("unit.dispatched", unit=A, run="r1"))
    with_delegate(monkeypatch, DECISIONS)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"delegate: 1 answered, 1 escalated (Q-004: {REASON})" in out
    assert "delegate cost $0.42 of $10.00" in out  # the share (0.25) of the plan's $40 limit


def test_the_idle_runs_line(world, capsys):  # SCN-DLG-50
    idle = [ev("plan.run_idle", unit=A, attempt=1, run=f"r{i}") for i in range(9)]
    activate(
        world,
        ev("unit.dispatched", unit=A, run="r1"),
        ev("plan.charged", unit=A, cost_usd=0, runs=12, attempt=1),
        *idle,
    )
    assert world.l4("status", "p1") == 0
    assert "runs 3 of 10 (9 idle, not counted)" in capsys.readouterr().out


def test_the_json_fields(world, capsys, monkeypatch):
    idle = [ev("plan.run_idle", unit=A, attempt=1, run="r0"), ev("plan.run_idle", unit=A, attempt=1, run="r1")]
    activate(
        world, ev("unit.dispatched", unit=A, run="r1"), ev("plan.charged", unit=A, cost_usd=0, runs=4, attempt=1), *idle
    )
    with_delegate(monkeypatch, DECISIONS)
    assert world.l4("status", "p1", "--json") == 0
    [plan] = json.loads(capsys.readouterr().out)["plans"]
    assert plan["usage"]["runs"] == 2 and plan["usage"]["idle_runs"] == 2
    assert plan["delegate"] == {
        "unit": A, "cost_usd": 0.42, "share_usd": 10.0, "answered": 1, "escalated": 1, "deferred": 0,
        "first_escalation": {"question": "Q-004", "reason": REASON},
    }  # fmt: skip


def test_a_plan_that_never_used_the_delegate_shows_nothing_more(world, capsys):
    activate(world, ev("unit.dispatched", unit=A, run="r1"))
    assert world.l4("status", "p1") == 0
    assert "delegate" not in capsys.readouterr().out
    assert world.l4("status", "p1", "--json") == 0
    assert "delegate" not in json.loads(capsys.readouterr().out)["plans"][0]
