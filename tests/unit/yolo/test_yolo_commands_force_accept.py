# ruff: noqa: F811
"""`l4 yolo accept PLAN --all --force` (L4-YOLO-057 to -061; SCN-YOLO-150 to -162): the flags, who may run it, what
stays refused, what is recorded and the withdrawal. No model is ever called."""

import pytest

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
