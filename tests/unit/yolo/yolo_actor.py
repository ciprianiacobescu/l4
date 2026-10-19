"""Who types: the `person` fixture and the `agent()` helper of the `l4 yolo accept|waive` tests."""

import pytest


class Asked(list):
    """The prompts a person was asked; `kwargs` holds the keyword arguments of each."""

    def __init__(self) -> None:
        super().__init__()
        self.kwargs: list[dict] = []


@pytest.fixture
def person(monkeypatch):
    """A terminal on stdin, a person who types `p1` when asked for the plan id; the returned list holds the prompts,
    its `kwargs` attribute the keyword arguments of each prompt."""
    asked = Asked()
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)

    def prompt(text, **kwargs):
        asked.append(text)
        asked.kwargs.append(kwargs)
        return "p1"

    monkeypatch.setattr("l4.yolo.commands.click.prompt", prompt)
    return asked


@pytest.fixture
def asked_kwargs(person):
    return person.kwargs


def agent(world, monkeypatch, marker="CLAUDECODE"):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: False)
    world.app.environ[marker] = "1"

    def no_prompt(*args, **kwargs):
        raise AssertionError("an agent is never prompted")

    monkeypatch.setattr("l4.yolo.commands.click.prompt", no_prompt)
