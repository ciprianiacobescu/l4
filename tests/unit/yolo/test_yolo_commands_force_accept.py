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
