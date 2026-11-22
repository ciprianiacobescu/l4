# ruff: noqa: F811
"""L4-YOLO-102: `plan.activated`, `plan.resumed` and `plan.cancelled` record who acted (`actor`, `marker`) and with
which harness (`harness_version`); the fold keeps the activation's actor; `l4 yolo status` and the plan report show
it, and an older ledger shows no kind. SCN-YOLO-289 to -292."""

import json

import l4
from l4.yolo.digest import plan_digest
from l4.yolo.report import render_report
from l4.yolo.state import fold_plan

from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, world  # noqa: F401

WHO = "alex@example.com"


def reviewed(world):
    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())


def last(world, kind):
    return [e for e in world.events() if e.type == kind][-1]


def status(world, capsys, *argv):
    capsys.readouterr()
    assert world.l4("status", "p1", *argv) == 0
    return capsys.readouterr().out


def report_of(world):
    from l4.yolo.plans import plan_files_at

    (file,) = [f for f in plan_files_at(world.clone, "origin/main") if f.plan_id == "p1"]
    events = world.events()
    return render_report(
        repository="r", plan=file.plan, state=fold_plan("p1", events), events=events, target_revision="abc",
        units={}, generated_at="t",
    )  # fmt: skip


def test_scn_yolo_289_a_persons_activation_records_and_shows_the_kind(world, forge, person, capsys):
    reviewed(world)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    data = last(world, "plan.activated").data
    assert (data["by"], data["actor"], data["marker"], data["harness_version"]) == (WHO, "person", None, l4.__version__)
    assert f"  activated by {WHO} (person)\n" in status(world, capsys)
    plan = json.loads(status(world, capsys, "--json"))["plans"][0]
    assert plan["activated_actor"] == "person" and plan["activated_marker"] is None
    assert f"- Activated by: {WHO} (person)\n" in report_of(world)


def test_scn_yolo_290_an_agents_activation_says_so_and_is_not_refused(world, forge, monkeypatch, capsys):
    reviewed(world)
    agent(world, monkeypatch)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    data = last(world, "plan.activated").data
    assert (data["actor"], data["marker"]) == ("agent", "CLAUDECODE")
    assert f"  activated by {WHO} (agent: CLAUDECODE)\n" in status(world, capsys)


def test_scn_yolo_290_an_agent_with_no_marker_and_no_terminal_is_shown_as_such(world, forge, monkeypatch, capsys):
    reviewed(world)
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: False)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    data = last(world, "plan.activated").data
    assert (data["actor"], data["marker"]) == ("agent", None)
    assert f"  activated by {WHO} (agent: no terminal)\n" in status(world, capsys)


def active(world, *events):
    reviewed(world)
    digest = plan_digest(world.plan_text)
    world.seed(
        "p1",
        ev("plan.activated", plan_digest=digest, digests={}, by=WHO, reason="go", limits={"max_cost_usd": 10.0}),
        *events,
    )


def test_scn_yolo_291_a_resume_and_a_cancel_record_the_kind(world, forge, person, capsys):
    active(world, ev("plan.stopped", reason="merge_refused", unit=A))
    assert world.l4("resume", "p1", "--reason", "r", "--no-run") == 0
    data = last(world, "plan.resumed").data
    assert (data["actor"], data["marker"], data["harness_version"]) == ("person", None, l4.__version__)
    assert "extend" in data and data["by"] == WHO
    out = status(world, capsys)
    assert f"  resumed by {WHO} (person)\n" in out
    document = json.loads(status(world, capsys, "--json"))["plans"][0]["resumed"]
    assert (document["by"], document["actor"], document["marker"]) == (WHO, "person", None) and document["at"]
    assert world.l4("cancel", "p1", "--reason", "r") == 0
    cancelled = last(world, "plan.cancelled").data
    assert (cancelled["actor"], cancelled["marker"], cancelled["harness_version"]) == ("person", None, l4.__version__)
    assert f"- Cancelled by: {WHO} (person)\n" in report_of(world)


def test_scn_yolo_291_the_harness_own_resume_is_not_a_persons(world, forge, person, capsys):
    active(world, ev("plan.stopped", reason="merge_refused", unit=A), ev("plan.resumed", by="harness", reason="x"))
    assert "resumed by" not in status(world, capsys)
    assert "resumed" not in json.loads(status(world, capsys, "--json"))["plans"][0]


def test_scn_yolo_292_an_older_ledger_folds_and_shows_no_kind(world, forge, person, capsys):
    active(world, ev("plan.stopped", reason="merge_refused", unit=A), ev("plan.resumed", by=WHO, reason="r", extend={}))
    state = fold_plan("p1", world.events())
    assert state.activated_by == WHO and state.activated_actor is None and state.activated_marker is None
    out = status(world, capsys)
    assert f"  activated by {WHO}\n" in out and "resumed by" not in out and "(person)" not in out
    plan = json.loads(status(world, capsys, "--json"))["plans"][0]
    assert plan["activated_actor"] is None and "resumed" not in plan
    assert f"- Activated by: {WHO}\n" in report_of(world)
