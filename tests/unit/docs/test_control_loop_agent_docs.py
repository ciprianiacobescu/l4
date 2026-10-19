"""The control-loop reference for coding agents ships with the skill and names only real commands and tools."""

import re
from pathlib import Path

import click

from l4.cli import cli
from l4.mcp import server, tools

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"
REFERENCE = SKILL / "references" / "control-loop.md"
CODE_SPAN = re.compile(r"`(l4 [^`]+)`")


def _resolve(words: list[str]) -> tuple[click.Command, list[str]]:
    command: click.Command = cli
    rest = list(words)
    while isinstance(command, click.Group) and rest and rest[0] in command.commands:
        command = command.commands[rest.pop(0)]
    return command, rest


def _spans(text: str) -> list[list[str]]:
    return [span.replace("\\|", " ").split() for span in CODE_SPAN.findall(text)]


def test_the_reference_ships_with_the_skill_and_is_short() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    assert len(text.split()) <= 900
    assert "references/control-loop.md" in (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "docs/control-loop.md" in text
    assert "NEVER check out" in text


def test_every_command_the_reference_names_exists() -> None:
    seen = 0
    for span in _spans(REFERENCE.read_text(encoding="utf-8")):
        command, rest = _resolve(span[1:])
        assert not isinstance(command, click.Group) or not rest or rest[0].startswith(("-", "<")), span
        if command is cli:
            continue  # `l4` followed by a word that is not a command: a placeholder or prose
        flags = {opt for param in command.params for opt in getattr(param, "opts", [])}
        for word in rest:
            if word.startswith("--"):
                assert word.split("=")[0] in flags | {"--help"}, (span, word)
        seen += 1
    assert seen >= 10


def test_every_mcp_tool_the_reference_names_exists() -> None:
    names = {tool.name for tool in tools.TOOLS}
    named = set(re.findall(r"\bl4_[a-z_]+\b", REFERENCE.read_text(encoding="utf-8")))
    named -= {"l4_"}
    assert {"l4_retry", "l4_plan_resume", "l4_question_answer", "l4_status", "l4_plan_status"} <= named
    assert named <= names, named - names


def test_the_mcp_instructions_point_to_the_reference() -> None:
    assert "l4_retry or l4_plan_resume" in server.INSTRUCTIONS
    assert "references/control-loop.md" in server.INSTRUCTIONS


def test_the_page_exists_and_the_readme_links_it() -> None:
    assert (ROOT / "docs" / "control-loop.md").is_file()
    assert "docs/control-loop.md" in (ROOT / "README.md").read_text(encoding="utf-8")
