# ruff: noqa: F811
"""L4-YOLO-106: what an overrule clears at the activation, in `l4 yolo go`, status, findings and the report, and what
is never carried to the unit. SCN-YOLO-299 to -302."""

import json

from l4.yolo.report import render_report
from l4.yolo.state import fold_plan

from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, world  # noqa: F401
from .yolo_overrule_world import (
    BATCH,
    FALSE_BLOCKING,
    MAJOR,
    MINOR,
    REASON,
    fid,
    overruled_event,
    reviewed_with,
)

WHO = "alex@example.com"
SECOND_BLOCKING = {"criterion": "contradiction", "severity": "blocking", "text": "A contradicts B"}


def overruled(world, findings=(FALSE_BLOCKING,), verdict="NEEDS_REVISION", **kw):
    reviewed_with(world, findings, verdict, **kw)
    world.seed("p1", overruled_event())


def activate(world, *extra):
    return world.l4("activate", "p1", "--reason", "go", "--no-run", *extra)


def activated(world):
    return [e for e in world.events() if e.type == "plan.activated"][-1]


def test_scn_yolo_299_the_overruled_plan_activates_and_nothing_is_carried(world, forge, person, capsys):
    overruled(world)
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"  overruled: {fid()} of {BATCH} by {WHO} (person): {REASON}\n" in out
    assert "review: current" in out and f"{BATCH}: NEEDS_REVISION" not in out
    assert world.l4("status", "p1", "--json") == 0
    review = json.loads(capsys.readouterr().out)["plans"][0]["review"]
    assert review["problems"] == []
    assert review["overruled"] == [
        {"finding": fid(), "subject": BATCH, "by": WHO, "reason": REASON, "holds": True}
    ]  # fmt: skip
    assert world.l4("findings", "p1") == 0
    text = capsys.readouterr().out
    assert f"{BATCH}: NEEDS_REVISION (cleared by an overrule: it does not stop the activation)" in text
    assert f"{fid()} [blocking/missing_dependency] {FALSE_BLOCKING['text']}" in text
    assert f"(overruled by {WHO} (person): {REASON})" in text
    assert "accept: l4 yolo accept" not in text  # a cleared subject has nothing to accept
    assert activate(world) == 0
    out = capsys.readouterr().out
    assert f"overruled: {fid()} of {BATCH} by {WHO} (person): {REASON}" in out
    assert out.index("overruled:") < out.index("activated on")
    event = activated(world)
    item = event.data["overruled"][fid()]
    assert (item["subject"], item["criterion"], item["severity"], item["text"]) == (
        BATCH, "missing_dependency", "blocking", FALSE_BLOCKING["text"],
    )  # fmt: skip
    assert (item["reason"], item["by"], item["actor"]) == (REASON, WHO, "person") and item["at"]
    assert BATCH not in event.data["accepted"]  # no accepted item: nothing is carried to the unit
    state = fold_plan("p1", world.events())
    assert fid() in state.activated_overruled and fid() not in json.dumps(state.activated_accepted)
    from l4.yolo.plans import plan_files_at

    (file,) = [f for f in plan_files_at(world.clone, "origin/main") if f.plan_id == "p1"]
    report = render_report(
        repository="r", plan=file.plan, state=state, events=world.events(), target_revision="abc", units={},
        generated_at="t",
    )  # fmt: skip
    assert f"- Overruled review findings ({BATCH}):" in report
    assert f"  - {fid()} [missing_dependency/blocking] {FALSE_BLOCKING['text']}: overruled by {WHO} (person)" in report
    assert REASON in report


def test_scn_yolo_300_a_blocked_entry_with_a_major_left_needs_an_acceptance(world, forge, person, capsys):
    overruled(world, [FALSE_BLOCKING, MAJOR], verdict="BLOCKED")
    capsys.readouterr()
    assert activate(world) == 2
    err = capsys.readouterr().err
    assert "batch b1: NEEDS_REVISION: testability" in err and FALSE_BLOCKING["text"] not in err
    # two judged versions of the batch (the first under made-up digests), then the acceptance is not refused as BLOCKED
    review = [e for e in world.events() if e.type == "plan.reviewed"][-1]
    first = json.loads(json.dumps(review.data))
    first["batches"]["b1"]["digests"] = {A: "old-a", B: "old-b"}
    world.seed("p1", ev("plan.reviewed", **first))
    world.seed("p1", ev("plan.reviewed", **json.loads(json.dumps(review.data))))
    assert world.l4("accept", "p1", BATCH, "--reason", "build the major as written") == 0
    accepted = [e for e in world.events() if e.type == "plan.accepted"][-1]
    assert accepted.data["overruled"] == [fid()]
    assert accepted.data["verdict"] == "BLOCKED"  # the entry's own, so `holds` is unchanged
    assert activate(world) == 0
    event = activated(world)
    assert event.data["overruled"][fid()]["subject"] == BATCH
    carried = event.data["accepted"][BATCH]["findings"]
    assert MAJOR in carried and FALSE_BLOCKING not in carried  # the overruled finding never reaches the unit


def test_scn_yolo_300_a_minor_left_is_ready_and_a_second_blocking_finding_refuses(world, forge, person, capsys):
    overruled(world, [FALSE_BLOCKING, MINOR])
    assert activate(world) == 0
    assert BATCH not in activated(world).data["accepted"]


def test_scn_yolo_300_a_second_blocking_finding_is_named_in_the_refusal(world, forge, person, capsys):
    overruled(world, [FALSE_BLOCKING, SECOND_BLOCKING])
    capsys.readouterr()
    assert activate(world) == 2
    err = capsys.readouterr().err
    assert SECOND_BLOCKING["text"] in err and FALSE_BLOCKING["text"] not in err
    assert [e for e in world.events() if e.type == "plan.activated"] == []


def test_scn_yolo_301_a_changed_material_ends_the_overrule(world, forge, person, capsys):
    overruled(world)
    review = [e for e in world.events() if e.type == "plan.reviewed"][-1]
    newer = json.loads(json.dumps(review.data))
    newer["batches"]["b1"]["material"] = "m-b1-new"  # the batch's material changed; the judge raised F again
    world.seed("p1", ev("plan.reviewed", **newer))
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert (
        f"overruled: {fid()} of {BATCH} by {WHO} (person): {REASON}; no longer holds: the subject's material changed"
        in out
    )
    assert activate(world) == 2
    assert FALSE_BLOCKING["text"] in capsys.readouterr().err
    reused = json.loads(json.dumps(review.data))  # a review that reuses the old material keeps the overrule
    reused["batches"]["b1"]["reused_from"] = "2026-10-14T10:00:00Z"
    world.seed("p1", ev("plan.reviewed", **reused))
    assert activate(world) == 0


def test_scn_yolo_302_a_withdrawal_by_an_agent_makes_the_activation_strict_again(world, forge, monkeypatch, capsys):
    overruled(world, [FALSE_BLOCKING, MAJOR], verdict="BLOCKED")
    review = [e for e in world.events() if e.type == "plan.reviewed"][-1]
    first = json.loads(json.dumps(review.data))
    first["batches"]["b1"]["digests"] = {A: "old-a", B: "old-b"}
    world.seed("p1", ev("plan.reviewed", **first), ev("plan.reviewed", **json.loads(json.dumps(review.data))))
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: "p1")
    assert world.l4("accept", "p1", BATCH, "--reason", "build the major as written") == 0
    agent(world, monkeypatch)
    assert world.l4("overrule", "p1", fid(), "--withdraw", "--reason", "r") == 0
    assert [e.data["actor"] for e in world.events() if e.type == "plan.overrule_withdrawn"] == ["agent"]
    capsys.readouterr()
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    assert activate(world) == 2
    err = capsys.readouterr().err
    assert FALSE_BLOCKING["text"] in err  # the acceptance still holds by its key, but the blocking finding is back


def test_go_as_a_person_after_an_overrule_does_not_stop_at_findings(world, forge, person, capsys):
    overruled(world)
    world.pull()
    forge.script_start_run("started")
    code = world.l4("go", "p1", "--reason", "R", "--json")
    doc = json.loads(capsys.readouterr().out)
    assert code == 0 and [e for e in world.events() if e.type == "plan.activated"], doc
    assert "findings" not in [s["step"] for s in doc.get("steps", []) if s.get("status") == "stopped"]


def test_a_withdrawn_overrule_is_gone_for_every_reader(world, forge, person, capsys):
    overruled(world)
    world.seed("p1", ev("plan.overrule_withdrawn", finding=fid(), reason="r", by=WHO, actor="person", marker=None))
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    assert "overruled:" not in capsys.readouterr().out
    assert activate(world) == 2
