# ruff: noqa: F811
"""`l4 yolo overrule PLAN FINDING --reason TEXT [--withdraw] [--yes]` (L4-YOLO-105; SCN-YOLO-296, -297, -298, -302,
-303): who may run it, what stays refused, what is recorded, and the withdrawal."""

import pytest

from l4.mcp.tools import TOOLS
from l4.yolo import commands
from l4.yolo.digest import plan_digest

from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, world  # noqa: F401
from .yolo_overrule_world import (
    BATCH,
    FALSE_BLOCKING,
    MAJOR,
    MINOR,
    REASON,
    SCHEMA_BLOCK,
    fid,
    overruled_event,
    reviewed_with,
)

WHO = "alex@example.com"


def overrule(world, finding=None, *extra, reason=REASON):
    return world.l4("overrule", "p1", finding or fid(), "--reason", reason, *extra)


def recorded(world, kind):
    return [e for e in world.events() if e.type == kind]


def test_scn_yolo_296_a_person_overrules_a_false_blocking_finding(world, person, capsys):
    reviewed_with(world)
    assert overrule(world) == 0
    captured = capsys.readouterr()
    assert f"{fid()} [missing_dependency/blocking] of {BATCH}: {FALSE_BLOCKING['text']}" in captured.out
    assert f"overruled: {fid()} of {BATCH} by {WHO} (person): {REASON}" in captured.out
    assert "Next: l4 yolo status p1" in captured.out
    assert person == [person[0]] and "p1" in person[0] and person.kwargs[0]["err"] is True
    (event,) = recorded(world, "plan.finding_overruled")
    data = event.data
    assert (data["finding"], data["subject"], data["criterion"], data["severity"]) == (
        fid(), BATCH, "missing_dependency", "blocking",
    )  # fmt: skip
    assert (data["text"], data["material"], data["reason"], data["by"]) == (FALSE_BLOCKING["text"], "m-b1", REASON, WHO)
    assert (data["actor"], data["marker"], data["confirmed"]) == ("person", None, "typed")
    assert data["judged_at"] == "2026-10-14T10:00:00Z" and data["harness_version"]


def test_a_person_with_yes_is_not_asked_and_the_event_says_so(world, person):
    reviewed_with(world)
    assert overrule(world, None, "--yes") == 0
    assert person == []
    assert recorded(world, "plan.finding_overruled")[0].data["confirmed"] == "--yes"


def test_any_other_answer_than_the_plan_id_records_nothing(world, monkeypatch, capsys):
    reviewed_with(world)
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: "yes")
    before = world.store().read().head
    assert overrule(world) == 2
    assert "the plan id was not typed: nothing was recorded" in capsys.readouterr().err
    assert world.store().read().head == before


@pytest.mark.parametrize("reason", ["", "   ", "x" * 1001])
def test_the_reason_rules_apply(world, person, reason, capsys):
    reviewed_with(world)
    before = world.store().read().head
    assert overrule(world, reason=reason) == 2
    assert person == [] and world.store().read().head == before
    assert "overrule: --reason" in capsys.readouterr().err


def test_a_lost_lease_says_the_plan_moved(world, monkeypatch, capsys):
    reviewed_with(world)
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)

    def prompt_while_the_plan_moves(text, **kwargs):
        world.seed("p1", ev("plan.refused", findings=[]))
        return "p1"

    monkeypatch.setattr("l4.yolo.commands.click.prompt", prompt_while_the_plan_moves)
    assert overrule(world) == 2
    assert "the plan moved: run the command again" in capsys.readouterr().err
    assert recorded(world, "plan.finding_overruled") == []


# --- SCN-YOLO-297: an agent ------------------------------------------------------------------------------------


def test_scn_yolo_297_an_agent_is_refused_before_anything_is_read(world, monkeypatch, capsys):
    reviewed_with(world)
    world.push({".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"}, "agents may accept")
    agent(world, monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("the plan was opened")

    monkeypatch.setattr(commands, "_open", boom)
    before = world.store().read().head
    assert overrule(world, None, "--yes") == 2
    err = capsys.readouterr().err
    assert "overrule: overruling a finding is a person's decision, never an agent's (CLAUDECODE is set)" in err
    assert "whatever yolo.review.accept_by_agents says" in err
    assert f'Fix: a person runs, in a terminal: l4 yolo overrule p1 {fid()} --reason "..."' in err
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: False)
    world.app.environ.pop("CLAUDECODE")
    assert overrule(world, None, "--yes") == 2
    assert "(stdin is not a terminal)" in capsys.readouterr().err
    monkeypatch.undo()
    assert world.store().read().head == before and recorded(world, "plan.finding_overruled") == []


def test_scn_yolo_297_the_mcp_server_offers_no_tool_that_runs_it():
    assert not [t for t in TOOLS if tuple(t.words)[:2] == ("yolo", "overrule")]
    assert not [t for t in TOOLS if "overrule" in t.name]


# --- SCN-YOLO-298: which findings ------------------------------------------------------------------------------


def refused(world, capsys, finding_id):
    capsys.readouterr()
    before = world.store().read().head
    assert overrule(world, finding_id) == 2
    assert world.store().read().head == before
    return capsys.readouterr().err


def test_scn_yolo_298_a_harness_finding_is_refused(world, person, capsys):
    reviewed_with(world, [SCHEMA_BLOCK], verdict="BLOCKED")
    err = refused(world, capsys, fid(SCHEMA_BLOCK))
    assert "is a harness finding (schema)" in err and "Fix: l4 yolo findings p1" in err
    assert person == []


def test_scn_yolo_298_a_major_finding_is_accepted_not_overruled(world, person, capsys):
    reviewed_with(world, [MAJOR, MINOR])
    err = refused(world, capsys, fid(MAJOR))
    assert "only a blocking finding is overruled" in err and f'Fix: l4 yolo accept p1 {BATCH} --reason "..."' in err


def test_scn_yolo_298_an_id_of_another_review_names_the_blocking_ids(world, person, capsys):
    reviewed_with(world)
    err = refused(world, capsys, "F-ffffff")
    assert "is not a finding of the latest review of p1" in err and fid() in err


def test_scn_yolo_298_an_entry_with_no_material_key_is_refused(world, person, capsys):
    review = reviewed_with(world)
    batch = {k: v for k, v in review.data["batches"]["b1"].items() if k != "material"}
    new = ev("plan.reviewed", **{**review.data, "batches": {"b1": batch}})
    world.seed("p1", new)
    err = refused(world, capsys, fid())
    assert "predates material keys" in err


def test_a_plan_with_no_review_is_refused(world, person, capsys):
    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]))
    assert overrule(world) == 2
    assert "p1 has no review yet: run l4 yolo review p1" in capsys.readouterr().err


# --- SCN-YOLO-303, the status rule -------------------------------------------------------------------------------


def test_scn_yolo_303_no_overrule_after_the_activation(world, person, capsys):
    review = reviewed_with(world)
    digest = plan_digest(world.plan_text)
    world.seed(
        "p1",
        ev("plan.activated", plan_digest=digest, digests={A: world.digest(A), B: world.digest(B)}, limits={}, by=WHO,
           reason="go", attempt_base={}, accepted={}),
    )  # fmt: skip
    assert review and overrule(world) == 2
    assert "overrule: p1 is active" in capsys.readouterr().err
    assert recorded(world, "plan.finding_overruled") == []


# --- the withdrawal (D1 step 4) ---------------------------------------------------------------------------------


def test_scn_yolo_302_an_agent_may_withdraw_an_overrule(world, monkeypatch, capsys):
    reviewed_with(world)
    world.seed("p1", overruled_event())
    agent(world, monkeypatch)
    assert world.l4("overrule", "p1", fid(), "--withdraw", "--reason", "r") == 0
    (event,) = recorded(world, "plan.overrule_withdrawn")
    assert (event.data["finding"], event.data["actor"], event.data["marker"]) == (fid(), "agent", "CLAUDECODE")
    assert event.data["reason"] == "r" and "Next:" in capsys.readouterr().out


def test_a_withdrawal_with_no_overrule_or_after_the_activation_is_refused(world, person, capsys):
    reviewed_with(world)
    assert world.l4("overrule", "p1", fid(), "--withdraw", "--reason", "r") == 2
    assert "has no overrule: nothing to withdraw" in capsys.readouterr().err
    world.seed("p1", overruled_event())
    world.seed(
        "p1",
        ev("plan.activated", plan_digest=plan_digest(world.plan_text),
           digests={A: world.digest(A), B: world.digest(B)}, limits={}, by=WHO, reason="go", attempt_base={},
           accepted={}),
    )  # fmt: skip
    assert world.l4("overrule", "p1", fid(), "--withdraw", "--reason", "r") == 2
    assert "frozen at its activation" in capsys.readouterr().err
    assert recorded(world, "plan.overrule_withdrawn") == []
