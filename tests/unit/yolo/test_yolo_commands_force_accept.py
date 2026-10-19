# ruff: noqa: F811
"""`l4 yolo accept PLAN --all --force` (L4-YOLO-057 to -061; SCN-YOLO-150 to -162): the flags, who may run it, what
stays refused, what is recorded and the withdrawal. No model is ever called."""

import pytest

from l4.yolo import commands
from l4.yolo.digest import plan_digest

from .yolo_actor import agent, asked_kwargs, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, plan_doc, world  # noqa: F401

REASON = "the judge is down; build as written"


def force(world, *extra, reason=REASON):
    return world.l4("accept", "p1", "--all", "--force", "--reason", reason, *extra)


def recorded(world, kind):
    return [e for e in world.events() if e.type == kind]


@pytest.fixture
def no_model(monkeypatch):
    """The force path never reaches a judge: building the factory or reviewing the plan fails the test."""

    def boom(*args, **kwargs):
        raise AssertionError("no model")

    class Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no model")

    monkeypatch.setattr("l4.yolo.readiness.Factory", Boom)
    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", boom)


# --- 2.1 the flags --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "words"),
    [
        (["p1", "--force", "--reason", "R"], "--force needs --all"),
        (["p1", "--all", "--reason", "R"], "--all needs --force"),
        (["p1", "openspec:a", "--all", "--force", "--reason", "R"], "--all takes no SUBJECT"),
        (["p1", "--reason", "R"], "a SUBJECT, or --all --force"),
        (["p1", "--all", "--force", "--reason", "  "], "--reason must say why"),
        (["p1", "--all", "--force", "--reason", "x" * 1001], "at most 1000"),
    ],
)
def test_the_flags_are_checked_before_anything_is_read(world, monkeypatch, capsys, argv, words):
    """SCN-YOLO-153."""
    world.push_plan()
    before = world.store().read().head

    def boom(*args, **kwargs):
        raise AssertionError("nothing is read before the flags are checked")

    monkeypatch.setattr("l4.yolo.commands._sync", boom)
    assert world.l4("accept", *argv) == 2
    assert words in capsys.readouterr().err
    assert world.store().read().head == before


# --- 2.2 who ----------------------------------------------------------------------------------------------------------


def test_an_agent_is_refused_even_when_agents_may_accept(world, monkeypatch, capsys):
    """SCN-YOLO-154."""
    world.push_plan()
    world.push({".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"}, "agents may accept")
    agent(world, monkeypatch)
    before = world.store().read().head
    assert force(world, "--yes") == 2
    err = capsys.readouterr().err
    assert "accept: --force is a person's decision, never an agent's (CLAUDECODE is set)" in err
    assert "whatever yolo.review.accept_by_agents says" in err
    assert 'Fix: a person runs, in a terminal: l4 yolo accept p1 --all --force --reason "..."' in err
    assert world.store().read().head == before


def test_an_mcp_caller_is_refused(world, monkeypatch, capsys):
    """SCN-YOLO-155."""
    world.push_plan()
    agent(world, monkeypatch, "AI_AGENT")
    world.app.environ["AI_AGENT"] = "l4-mcp"
    before = world.store().read().head
    assert force(world) == 2
    assert "AI_AGENT is set" in capsys.readouterr().err
    assert world.store().read().head == before


def test_no_terminal_is_refused_and_nothing_prompts(world, monkeypatch, capsys):
    """SCN-YOLO-156."""
    world.push_plan()
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: False)

    def no_prompt(*args, **kwargs):
        raise AssertionError("nothing prompts")

    monkeypatch.setattr("l4.yolo.commands.click.prompt", no_prompt)
    before = world.store().read().head
    assert force(world, "--yes") == 2
    assert "stdin is not a terminal" in capsys.readouterr().err
    assert world.store().read().head == before


def test_the_actor_is_checked_before_the_plan_is_fetched(world, monkeypatch, capsys):
    agent(world, monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("nothing is fetched for an agent")

    monkeypatch.setattr("l4.yolo.commands._sync", boom)
    assert force(world) == 2
    assert "never an agent's" in capsys.readouterr().err


# --- 2.3 what stays refused -------------------------------------------------------------------------------------------


@pytest.fixture
def at_a_prompt(person, no_model):
    """A person at a terminal who would type `p1`: a refusal must come before the prompt and nothing is recorded."""
    return person


def test_a_unit_with_no_folder_is_refused_by_admission(world, at_a_prompt, capsys):
    """SCN-YOLO-157."""
    world.push_plan(plan_doc({A: [], "openspec:ghost": []}))
    before = world.store().read().head
    assert force(world) == 2
    err = capsys.readouterr().err
    assert "accept: p1 is not admitted:" in err and "  unknown_unit:" in err and "openspec:ghost" in err
    assert at_a_prompt == [] and world.store().read().head == before


def test_a_missing_digest_is_refused_as_unit_missing(world, at_a_prompt, monkeypatch, capsys):
    world.push_plan()
    real = commands._now_digest
    monkeypatch.setattr(
        "l4.yolo.commands._now_digest",
        lambda ctx, unit, folder: "<folder missing>" if unit == B else real(ctx, unit, folder),
    )
    before = world.store().read().head
    assert force(world) == 2
    err = capsys.readouterr().err
    assert (
        f"accept: {B} has no folder with files on its branch or on origin/main (unit_missing): "
        "nothing can be built from it" in err
    )
    assert "Fix: push its folder, or remove it from .l4/plans/p1.json" in err
    assert at_a_prompt == [] and world.store().read().head == before


def test_a_cycle_is_refused(world, at_a_prompt, capsys):
    """SCN-YOLO-158."""
    world.push_plan(plan_doc({A: [B], B: [A]}))
    before = world.store().read().head
    assert force(world) == 2
    assert "  cycle:" in capsys.readouterr().err
    assert at_a_prompt == [] and world.store().read().head == before


def test_an_active_plan_is_refused(world, at_a_prompt, capsys):
    """SCN-YOLO-159."""
    world.push_plan()
    world.seed("p1", ev("plan.activated", plan_digest="pd", digests={A: "x"}, limits={}, by="me"))
    before = world.store().read().head
    assert force(world) == 2
    err = capsys.readouterr().err
    assert "p1 is active: an acceptance is possible before activation, or when the plan is stopped with" in err
    assert at_a_prompt == [] and world.store().read().head == before


def test_a_file_that_is_not_a_plan_is_refused(world, at_a_prompt, capsys):
    world.push_plan("this is not json")
    before = world.store().read().head
    assert force(world) == 2
    assert "accept: p1 is not a plan" in capsys.readouterr().err
    assert at_a_prompt == [] and world.store().read().head == before


def test_a_missing_plan_file_is_refused(world, at_a_prompt, capsys):
    assert force(world) == 2
    assert "no plan file .l4/plans/p1.json" in capsys.readouterr().err


# --- 2.4 record -------------------------------------------------------------------------------------------------------

BLOCKED_BY_SCHEMA = {"criterion": "schema", "severity": "blocking", "text": "schema_invalid: ok"}
PROMPT = "Type the plan id (p1) to accept every subject of p1 without a review"


def test_a_person_force_accepts_a_blocked_review_and_no_model_is_called(world, person, no_model, capsys):
    """SCN-YOLO-150."""
    world.push_plan()
    world.seed("p1", world.reviewed({A: "BLOCKED"}, findings={A: [BLOCKED_BY_SCHEMA]}))
    assert force(world) == 0
    out = capsys.readouterr().out
    assert (
        "p1: force-accept 3 subject(s) without a readiness review; no model reviews these specifications before "
        "they are built:" in out
    )
    assert f"  {A}: BLOCKED" in out
    assert f"  {B}: READY at these inputs: nothing is overridden" in out
    assert "  batch:b1: READY at these inputs: nothing is overridden" in out
    assert "force-accepted: 3 subject(s) of p1 without review by alex@example.com (person): " + REASON in out
    assert "Next: l4 yolo activate p1 --reason TEXT" in out
    assert person == [PROMPT] and person.kwargs[0]["err"] is True
    assert len(recorded(world, "plan.reviewed")) == 1  # no review was made
    (event,) = recorded(world, "plan.force_accepted")
    data = event.data
    assert data["plan_digest"] == plan_digest(world.plan_text) and data["reason"] == REASON
    assert (data["by"], data["actor"], data["marker"], data["confirmed"]) == (
        "alex@example.com",
        "person",
        None,
        "typed",
    )
    assert sorted(data["subjects"]) == sorted([A, B, "batch:b1"])  # the ledger sorts keys
    assert data["subjects"][A] == {
        "digest": world.digest(A), "skipped": ["blocked"], "review_at": "2026-10-14T10:00:00Z",
        "verdict": "BLOCKED", "material": None,
    }  # fmt: skip
    assert data["subjects"][B]["skipped"] == [] and data["subjects"][B]["digest"] == world.digest(B)
    assert data["subjects"]["batch:b1"]["digests"] == {A: world.digest(A), B: world.digest(B)}
    assert data["subjects"]["batch:b1"]["skipped"] == []


def test_a_plan_never_reviewed_is_admitted_and_force_accepted(world, person, no_model, capsys):
    """SCN-YOLO-151."""
    world.push_plan()
    assert force(world) == 0
    assert world.kinds() == ["plan.admitted", "plan.force_accepted"]
    admitted, accepted = world.events()
    assert admitted.data["plan_digest"] == accepted.data["plan_digest"] and admitted.data["order"] == [A, B]
    assert admitted.data["merge"] == "human"
    assert {s: r["skipped"] for s, r in accepted.data["subjects"].items()} == {
        A: ["no_review"], B: ["no_review"], "batch:b1": ["no_review"],
    }  # fmt: skip
    assert all(r["review_at"] is None for r in accepted.data["subjects"].values())
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    assert "admitted" in capsys.readouterr().out


def test_an_admitted_plan_gets_no_second_admission(world, person, no_model):
    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B], merge="human"))
    assert force(world) == 0
    assert world.kinds() == ["plan.admitted", "plan.force_accepted"]
    assert recorded(world, "plan.admitted")[0].at == "2026-10-14T10:00:00Z"  # the seeded one, not a new one


def test_a_person_force_accepts_with_yes(world, person, no_model, capsys):
    """SCN-YOLO-169."""
    world.push_plan()
    assert force(world, "--yes") == 0
    assert person == []
    assert "force-accept 3 subject(s) without a readiness review" in capsys.readouterr().out  # the summary is printed
    (event,) = recorded(world, "plan.force_accepted")
    assert event.data["confirmed"] == "--yes" and event.data["actor"] == "person"


def test_the_force_prompt_is_written_to_stderr(world, person, no_model):
    """SCN-YOLO-172."""
    world.push_plan()
    assert force(world) == 0
    assert person.kwargs[0]["err"] is True and "p1" in person[0]


def test_any_other_answer_records_nothing(world, monkeypatch, no_model, capsys):
    """SCN-YOLO-152."""
    world.push_plan()
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: "yes")
    before = world.store().read().head
    assert force(world) == 2
    assert "the plan id was not typed: nothing was recorded" in capsys.readouterr().err
    assert world.store().read().head == before


@pytest.mark.parametrize("reason", ["", "   ", "x" * 1001])
def test_the_reason_rules_apply(world, person, no_model, reason):
    world.push_plan()
    before = world.store().read().head
    assert force(world, reason=reason) == 2
    assert person == [] and world.store().read().head == before


def test_a_lost_lease_says_the_plan_moved(world, monkeypatch, no_model, capsys):
    world.push_plan()
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)

    def prompt_while_the_plan_moves(text, **kwargs):
        world.seed("p1", ev("plan.refused", findings=[]))
        return "p1"

    monkeypatch.setattr("l4.yolo.commands.click.prompt", prompt_while_the_plan_moves)
    assert force(world) == 2
    assert "the plan moved: run the command again" in capsys.readouterr().err
    assert recorded(world, "plan.force_accepted") == []


# --- 2.5 withdraw -----------------------------------------------------------------------------------------------------

A_SPEC = "openspec/changes/add-greeting/specs/greeting/spec.md"
A_SPEC_EDITED = """## Purpose

The greeting capability of the simulator fixture: a greeting names the person it greets.

## ADDED Requirements

### Requirement: Greet by name
The `greet(name)` function SHALL return `Hello, <name>!` for a non-blank name.

#### Scenario: Named greeting
- **WHEN** `greet("Ada")` is called
- **THEN** it returns `"Hello, Ada!"`

#### Scenario: Blank name
- **WHEN** `greet("  ")` is called
- **THEN** it raises `ValueError`
"""


def withdraw(world, reason="spec reworked"):
    return world.l4("accept", "p1", "--all", "--force", "--withdraw", "--reason", reason)


def state_of(world):
    from l4.yolo.state import fold_plan

    return fold_plan("p1", world.events())


def test_a_withdrawal_by_an_agent_removes_it(world, person, no_model, monkeypatch, capsys):
    """SCN-YOLO-161."""
    world.push_plan()
    assert force(world) == 0
    assert state_of(world).force_accepted is not None
    agent(world, monkeypatch, "AI_AGENT")
    capsys.readouterr()
    assert withdraw(world) == 0
    out = capsys.readouterr().out
    assert "p1: the force acceptance is withdrawn" in out and "Next: l4 yolo review p1" in out
    (event,) = recorded(world, "plan.force_acceptance_withdrawn")
    assert event.data == {"reason": "spec reworked", "by": "alex@example.com", "actor": "agent", "marker": "AI_AGENT"}
    assert state_of(world).force_accepted is None
    assert withdraw(world) == 2
    assert "accept: p1 has no force acceptance: nothing to withdraw" in capsys.readouterr().err


def test_nothing_to_withdraw(world, person, capsys):
    world.push_plan()
    before = world.store().read().head
    assert withdraw(world) == 2
    assert "accept: p1 has no force acceptance: nothing to withdraw" in capsys.readouterr().err
    assert world.store().read().head == before


def test_a_withdrawal_after_activation_is_refused(world, person, capsys):
    world.push_plan()
    world.seed(
        "p1",
        ev("plan.force_accepted", plan_digest="pd", subjects={}, reason="r", by="x", actor="person"),
        ev("plan.activated", plan_digest="pd", digests={A: "x"}, limits={}, by="me"),
    )
    before = world.store().read().head
    assert withdraw(world) == 2
    err = capsys.readouterr().err
    assert "the acceptances were frozen at its activation" in err and "cancel the plan (l4 yolo cancel p1)" in err
    assert world.store().read().head == before


def test_a_second_force_acceptance_replaces_the_first(world, person, no_model):
    """SCN-YOLO-162."""
    from l4.yolo.accept import force_holds

    world.push_plan()
    assert force(world, reason="first") == 0
    world.push({A_SPEC: A_SPEC_EDITED}, "A's spec changes")
    assert force(world, reason="second") == 0
    state = state_of(world)
    assert state.force_accepted["reason"] == "second"
    now = {A: world.digest(A), B: world.digest(B)}
    assert force_holds(state.force_accepted, plan_digest(world.plan_text), now) == {A: True, B: True, "batch:b1": True}
    assert len(recorded(world, "plan.force_accepted")) == 2
    assert len(recorded(world, "plan.admitted")) == 1  # the plan is admitted at this digest and order already
