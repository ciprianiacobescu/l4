# ruff: noqa: F811
"""`l4 yolo accept` (L4-YOLO-027; SCN-YOLO-62 the event, -63, -64, -65): who may accept, what the person sees and
types, what is recorded, and the withdrawal."""

import pytest

from l4.yolo.findings import findings_sha
from l4.yolo.model import PlanMoved
from l4.yolo.store import PlanStore

from .yolo_actor import agent, asked_kwargs, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, world  # noqa: F401
from .yolo_review_events import BLOCKING, FAILURES, MATERIAL, TESTABILITY, entry, review, two_rounds

REASON = "keep the thresholds; test with a 3x tolerance"
MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "L4_RESULT_PATH")


def accepted_world(world, findings=(TESTABILITY, FAILURES)):
    world.push_plan()
    two_rounds(world, list(findings))
    return world


def recorded(world, kind):
    return [e for e in world.events() if e.type == kind]


def test_a_person_accepts_after_two_versions_and_the_event_is_recorded(world, person, capsys):
    """SCN-YOLO-62, the event part."""
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", f"  {REASON}  ") == 0
    out = capsys.readouterr().out
    assert TESTABILITY["text"] in out and FAILURES["text"] in out  # the person sees every finding
    assert person == [person[0]] and "p1" in person[0]
    (event,) = recorded(world, "plan.accepted")
    data = event.data
    assert data["subject"] == A and data["material"] == "m2" and data["reason"] == REASON
    assert data["actor"] == "person" and data["marker"] is None and data["by"] == "alex@example.com"
    assert data["rounds"] == 2 and data["verdict"] == "NEEDS_REVISION" and data["prompt_version"]
    assert data["findings"] == [TESTABILITY, FAILURES] and data["findings_sha"] == findings_sha([TESTABILITY, FAILURES])


def test_any_other_answer_than_the_plan_id_records_nothing(world, monkeypatch, capsys):
    accepted_world(world)
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: "yes")
    before = world.store().read().head
    assert world.l4("accept", "p1", A, "--reason", REASON) == 2
    assert "accept:" in capsys.readouterr().err
    assert world.store().read().head == before


def test_a_person_with_yes_is_still_asked_for_the_plan_id(world, person):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", REASON, "--yes") == 0
    assert len(person) == 1


def test_a_batch_can_be_accepted(world, person):
    world.push_plan()
    batch = {"verdict": "NEEDS_REVISION", "digest": None, "findings": [FAILURES]}
    for at, digests, material in (
        ("2026-10-14T10:00:00Z", {A: "x1", B: "y1"}, "b1"),
        ("2026-10-14T11:00:00Z", {A: "x2", B: "y1"}, "b2"),
    ):
        world.seed("p1", review(world, at, {}, {"b1": {**batch, "digests": digests, "material": material}}))
    assert world.l4("accept", "p1", "batch:b1", "--reason", REASON) == 0
    assert recorded(world, "plan.accepted")[0].data["subject"] == "batch:b1"


def test_one_judgement_is_not_enough(world, person, capsys):
    """SCN-YOLO-63: judged twice, on one version of the text."""
    world.push_plan()
    for at, material in (("2026-10-14T10:00:00Z", "m1"), ("2026-10-14T11:00:00Z", "m2")):
        world.seed("p1", review(world, at, {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY], material)}))
    before = world.store().read().head
    assert world.l4("accept", "p1", A, "--reason", "x") == 2
    err = capsys.readouterr().err
    assert f"accept: {A} was judged not READY on 1 version; 2 are needed (yolo.review.accept_after_rounds)" in err
    assert world.store().read().head == before and person == []


@pytest.mark.parametrize(
    ("verdict", "findings", "fix"),
    [
        ("BLOCKED", [{"criterion": "schema", "severity": "blocking", "text": "no answer"}], "run l4 yolo review p1"),
        ("NEEDS_REVISION", [BLOCKING], "fix the spec"),
        ("NEEDS_REVISION", [MATERIAL], "shorten the file or raise yolo.review.max_file_chars"),
    ],
)
def test_blocked_a_blocking_finding_and_a_cut_cannot_be_accepted(world, person, capsys, verdict, findings, fix):
    """SCN-YOLO-64."""
    accepted_world(world)
    two_rounds(world, findings, verdict=verdict)
    before = world.store().read().head
    assert world.l4("accept", "p1", A, "--reason", "x") == 2
    err = capsys.readouterr().err
    assert "accept:" in err and fix in err
    assert world.store().read().head == before


def test_an_agent_cannot_accept_unless_the_target_allows_it(world, monkeypatch, capsys):
    """SCN-YOLO-65."""
    accepted_world(world)
    agent(world, monkeypatch)
    before = world.store().read().head
    assert world.l4("accept", "p1", A, "--reason", "x", "--yes") == 2
    err = capsys.readouterr().err
    assert "accept: acceptance is a person's decision" in err
    assert f'l4 yolo accept p1 {A} --reason "..."' in err
    assert world.store().read().head == before
    world.push({".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"}, "agents may accept")
    assert world.l4("accept", "p1", A, "--reason", REASON, "--yes") == 0
    (event,) = recorded(world, "plan.accepted")
    assert event.data["actor"] == "agent" and event.data["marker"] == "CLAUDECODE"


def test_an_agent_that_may_accept_must_say_yes(world, monkeypatch, capsys):
    accepted_world(world)
    agent(world, monkeypatch)
    world.push({".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"}, "agents may accept")
    before = world.store().read().head
    assert world.l4("accept", "p1", A, "--reason", REASON) == 2
    assert "--yes" in capsys.readouterr().err
    assert world.store().read().head == before


def test_a_withdrawal_removes_an_acceptance(world, person, capsys):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", REASON) == 0
    assert world.l4("accept", "p1", A, "--withdraw", "--reason", "the spec changed") == 0
    (event,) = recorded(world, "plan.acceptance_withdrawn")
    assert event.data == {"subject": A, "reason": "the spec changed", "by": "alex@example.com", "actor": "person"}


def test_an_agent_may_withdraw_without_the_target_allowing_it(world, person, monkeypatch):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", REASON) == 0
    agent(world, monkeypatch, "AI_AGENT")
    assert world.l4("accept", "p1", A, "--withdraw", "--reason", "no") == 0
    assert recorded(world, "plan.acceptance_withdrawn")[0].data["actor"] == "agent"


def test_withdrawing_what_was_not_accepted_is_refused(world, person, capsys):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--withdraw", "--reason", "no") == 2
    assert "nothing to withdraw" in capsys.readouterr().err


@pytest.mark.parametrize(
    "later", [("plan.activated",), ("plan.activated", "plan.waiting"), ("plan.activated", "plan.stopped")]
)
def test_a_withdrawal_after_activation_is_refused_and_says_what_to_do(world, person, capsys, later):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", REASON) == 0
    data = {"plan.activated": {"plan_digest": "x", "digests": {}, "limits": {}, "by": "a", "reason": "r"},
            "plan.waiting": {"reason": "merge_not_ready", "unit": A, "detail": "d"},
            "plan.stopped": {"reason": "unit_halted", "unit": A}}  # fmt: skip
    world.seed("p1", *(ev(kind, **data[kind]) for kind in later))
    before = world.store().read().head
    capsys.readouterr()
    assert world.l4("accept", "p1", A, "--withdraw", "--reason", "no") == 2
    out = capsys.readouterr()
    assert "withdrawn" not in out.out and "cancel" in out.err and "l4 yolo review" in out.err
    assert world.store().read().head == before and not recorded(world, "plan.acceptance_withdrawn")


def test_a_withdrawal_on_a_plan_stopped_with_inputs_changed_is_allowed(world, person):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", REASON) == 0
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"),
               ev("plan.stopped", reason="inputs_changed", unit=A))  # fmt: skip
    assert world.l4("accept", "p1", A, "--withdraw", "--reason", "the spec changed") == 0
    assert recorded(world, "plan.acceptance_withdrawn")


@pytest.mark.parametrize("reason", ["", "   ", "x" * 1001])
def test_the_reason_is_required_and_at_most_1000_characters(world, person, capsys, reason):
    accepted_world(world)
    before = world.store().read().head
    assert world.l4("accept", "p1", A, "--reason", reason) == 2
    assert "--reason" in capsys.readouterr().err
    assert world.store().read().head == before


def test_a_reason_of_1000_characters_is_accepted(world, person):
    accepted_world(world)
    assert world.l4("accept", "p1", A, "--reason", "x" * 1000) == 0


def test_a_lost_lease_says_the_plan_moved(world, person, monkeypatch, capsys):
    accepted_world(world)

    def moved(self, events, expect=None):
        raise PlanMoved("moved")

    monkeypatch.setattr(PlanStore, "append", moved)
    assert world.l4("accept", "p1", A, "--reason", REASON) == 2
    assert "the plan moved: run the command again" in capsys.readouterr().err


def test_a_subject_that_is_not_in_the_review_and_a_plan_with_no_review_are_refused(world, person, capsys):
    world.push_plan()
    assert world.l4("accept", "p1", A, "--reason", "x") == 2
    assert "no review" in capsys.readouterr().err
    world.seed("p1", review(world, "2026-10-14T10:00:00Z", {}))
    assert world.l4("accept", "p1", "openspec:zzz", "--reason", "x") == 2
    assert "openspec:zzz" in capsys.readouterr().err


def test_a_ready_subject_has_nothing_to_accept(world, person, capsys):
    world.push_plan()
    world.seed("p1", review(world, "2026-10-14T10:00:00Z", {}))
    assert world.l4("accept", "p1", A, "--reason", "x") == 2
    assert "nothing to accept" in capsys.readouterr().err


def test_an_active_plan_cannot_be_accepted_on(world, person, capsys):
    accepted_world(world)
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    assert world.l4("accept", "p1", A, "--reason", "x") == 2
    assert "active" in capsys.readouterr().err
