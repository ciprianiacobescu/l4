# ruff: noqa: F811
"""`l4 yolo waive` (L4-YOLO-031; SCN-YOLO-73 the event, SCN-YOLO-74): a person, or an agent the target allows, waives
an accepted finding of an activated plan on record, and can withdraw the waiver."""

import pytest

from l4.yolo.digest import plan_digest
from l4.yolo.findings import finding_id

from .yolo_actor import agent, asked_kwargs, person  # noqa: F401 (fixtures)
from .yolo_cmd_world import A, ev, world  # noqa: F401
from .yolo_review_events import FAILURES, TESTABILITY

REASON = "the spec asks for no handling of these cases; checked by hand"
ID1, ID2 = finding_id(A, TESTABILITY), finding_id(A, FAILURES)
ALLOW = {".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"}


def activated(world, *events):
    """An active plan whose activation froze one accepted item of A with two findings."""
    world.push_plan()
    item = {"findings": [TESTABILITY, FAILURES], "reason": "use a plain path", "by": "alice", "actor": "person"}
    digest = plan_digest(world.plan_text)
    world.seed("p1", ev("plan.activated", plan_digest=digest, digests={}, limits={}, by="alice", reason="go",
                        accepted={A: item}), *events)  # fmt: skip
    return world


def recorded(world, kind):
    return [e for e in world.events() if e.type == kind]


def test_a_person_waives_a_finding_after_typing_the_plan_id(world, person, capsys):
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", f"  {REASON}  ", "--no-run") == 0
    out = capsys.readouterr().out
    assert TESTABILITY["text"] in out and "use a plain path" in out  # the person sees the finding and the acceptance
    assert len(person) == 1 and "p1" in person[0]
    (event,) = recorded(world, "plan.finding_waived")
    assert event.data == {
        "finding": ID1, "subject": A, "reason": REASON, "by": "alex@example.com", "actor": "person", "marker": None,
        "confirmed": "typed",
    }  # fmt: skip
    assert f"waived: {ID1}" in out and "Next: l4 yolo status p1" in out


def test_a_person_waives_with_yes_without_a_prompt(world, person, capsys):
    """SCN-YOLO-168, the waive part."""
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--yes", "--no-run") == 0
    assert person == []
    assert TESTABILITY["text"] in capsys.readouterr().out  # the finding and its acceptance are still shown
    (event,) = recorded(world, "plan.finding_waived")
    assert event.data["confirmed"] == "--yes" and event.data["actor"] == "person"


def test_a_person_who_types_waives_as_typed(world, person):
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 0
    (event,) = recorded(world, "plan.finding_waived")
    assert event.data["confirmed"] == "typed"


def test_the_waive_prompt_is_written_to_stderr(world, person, asked_kwargs):
    """SCN-YOLO-172."""
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 0
    assert asked_kwargs[0]["err"] is True and "p1" in person[0]


def test_without_a_terminal_nothing_prompts(world, monkeypatch, capsys):
    """SCN-YOLO-171: a regression guard; nothing is printed before the exit."""
    activated(world)
    world.push(ALLOW, "agents may accept")
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: False)

    def no_prompt(*args, **kwargs):
        raise AssertionError("nothing prompts")

    monkeypatch.setattr("l4.yolo.commands.click.prompt", no_prompt)
    before = world.store().read().head
    capsys.readouterr()
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 2
    captured = capsys.readouterr()
    assert "--yes" in captured.err and captured.out == ""
    assert world.store().read().head == before


def test_without_no_run_the_command_starts_a_run(world, person, capsys):
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", REASON) == 0
    out = capsys.readouterr().out
    assert "run started on" in out or "start a run with:" in out


@pytest.mark.parametrize("bad", ["F-000000", "not-an-id"])
def test_an_id_that_is_not_an_accepted_finding_is_refused(world, person, capsys, bad):
    """SCN-YOLO-74: an unknown id."""
    activated(world)
    before = world.store().read().head
    assert world.l4("waive", "p1", bad, "--reason", REASON, "--no-run") == 2
    err = capsys.readouterr().err
    assert f"waive: {bad} is not an accepted finding of p1" in err and ID1 in err and ID2 in err
    assert world.store().read().head == before and person == []


def test_a_plan_that_is_not_activated_is_refused(world, person, capsys):
    """SCN-YOLO-74: before activation the command is l4 yolo accept."""
    world.push_plan()
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 2
    assert "l4 yolo accept" in capsys.readouterr().err
    assert not recorded(world, "plan.finding_waived")


def test_a_final_plan_is_refused(world, person, capsys):
    activated(world, ev("plan.cancelled", by="alice", reason="stop"))
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 2
    assert "waive: p1 is cancelled" in capsys.readouterr().err


def test_an_agent_cannot_waive_unless_the_target_allows_it(world, monkeypatch, capsys):
    """SCN-YOLO-74: the same switch as accept."""
    activated(world)
    agent(world, monkeypatch)
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--yes", "--no-run") == 2
    assert "accept_by_agents" in capsys.readouterr().err
    world.push(ALLOW, "agents may accept")
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 2  # no terminal: --yes is needed
    assert "--yes" in capsys.readouterr().err
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--yes", "--no-run") == 0
    (event,) = recorded(world, "plan.finding_waived")
    assert event.data["actor"] == "agent" and event.data["marker"] == "CLAUDECODE"


def test_any_other_answer_than_the_plan_id_records_nothing(world, monkeypatch, capsys):
    """SCN-YOLO-74: the person typed something else."""
    activated(world)
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: "yes")
    before = world.store().read().head
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 2
    assert "nothing was recorded" in capsys.readouterr().err
    assert world.store().read().head == before


def test_an_empty_reason_is_refused(world, person, capsys):
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", "  ", "--no-run") == 2
    assert "waive: --reason must say why" in capsys.readouterr().err


def test_a_waiver_is_withdrawn_and_a_finding_without_one_has_nothing_to_withdraw(world, person, capsys):
    activated(world)
    assert world.l4("waive", "p1", ID1, "--reason", REASON, "--no-run") == 0
    assert world.l4("waive", "p1", ID1, "--reason", "look again", "--withdraw", "--no-run") == 0
    (event,) = recorded(world, "plan.waiver_withdrawn")
    assert event.data == {"finding": ID1, "reason": "look again", "by": "alex@example.com", "actor": "person"}
    assert world.l4("waive", "p1", ID2, "--reason", "x", "--withdraw", "--no-run") == 2
    assert f"waive: {ID2} has no waiver: nothing to withdraw" in capsys.readouterr().err
