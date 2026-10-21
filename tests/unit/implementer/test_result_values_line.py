"""SCN-IMP-M1: the allowed `status` values sit next to the phase line, not only in the schema at the end of the prompt
(live 2026-10-06/07: magnitude-qwen wrote `"status": "red"` in 2 of 3 red attempts, with the schema 3000 characters
below the `# Phase: RED` line)."""

import copy
import re
from pathlib import Path

import pytest

from l4.implementer import prompt as prompt_module
from l4.implementer.prompt import render_prompt, result_values_line
from l4.implementer.result import RESULT_SCHEMA

from .test_prompt import ctx

LINE = re.compile(r"^result values: .*$", re.MULTILINE)


def section_of(text: str, heading_prefix: str) -> str:
    start = text.index(heading_prefix)
    nxt = re.search(r"^# ", text[start + 1 :], re.MULTILINE)
    return text[start : start + 1 + nxt.start()] if nxt else text[start:]


CASES = [
    ("red", False, "# Phase: RED", "red"),
    ("green", False, "# Phase: GREEN", "green"),
    ("single", False, "# Phase: SINGLE (fix", "single"),
    ("single", True, "# Phase: SINGLE (add tests", "single"),
]


@pytest.mark.parametrize(("role", "adds_tests", "heading", "phase"), CASES)
def test_the_line_is_in_the_phase_section_and_names_the_values(role, adds_tests, heading, phase, tmp_path: Path):
    text = render_prompt(role, ctx(result_path=tmp_path / "result.json", adds_tests=adds_tests)).text
    section = section_of(text, heading)
    lines = LINE.findall(section)
    assert len(lines) == 1, section
    line = lines[0]
    assert "status is one of done | blocked | failed | partial" in line
    assert "never the phase name" in line
    assert f'phase is "{phase}"' in line
    assert text.count("result values:") == 1
    # nothing but the phase's own text between the phase line and the values: no other section comes between them
    assert not re.search(r"^# ", section[len(heading) :].split("result values:")[0], re.MULTILINE)


def test_the_line_comes_right_after_the_phase_heading(tmp_path: Path):
    text = render_prompt("red", ctx(result_path=tmp_path / "r.json")).text
    heading_line = next(line for line in text.splitlines() if line.startswith("# Phase: RED"))
    lines = text.splitlines()
    assert lines[lines.index(heading_line) + 1].startswith("result values: ")


def test_the_values_come_from_the_schema_not_from_a_literal():
    swapped = copy.deepcopy(RESULT_SCHEMA)
    swapped["properties"]["status"]["enum"] = ["finished", "stuck"]
    line = result_values_line(swapped, "green")
    assert "status is one of finished | stuck" in line and "done" not in line
    assert 'phase is "green"' in line
    assert "done | blocked | failed | partial" in result_values_line(RESULT_SCHEMA, "red")


def test_the_renderer_uses_the_loaded_schema(monkeypatch, tmp_path: Path):
    swapped = copy.deepcopy(RESULT_SCHEMA)
    swapped["properties"]["status"]["enum"] = ["finished", "stuck"]
    monkeypatch.setattr(prompt_module, "RESULT_SCHEMA", swapped)
    text = render_prompt("red", ctx(result_path=tmp_path / "r.json")).text
    assert "status is one of finished | stuck" in text  # a later enum edit cannot leave the prompt stale


def test_a_native_adapter_gets_the_same_line_and_an_unchanged_output_section():
    native = render_prompt("red", ctx(result_path=None)).text
    contract = render_prompt("red", ctx(result_path=Path("/x/result.json"))).text
    assert LINE.findall(native) == LINE.findall(contract) and len(LINE.findall(native)) == 1
    assert "(schema enforced)" in native.split("# Output")[1]
    assert "conform to this JSON Schema" not in native
    assert "conform to this JSON Schema" in contract.split("# Output")[1]


def test_the_phase_value_must_be_a_known_phase():
    with pytest.raises(ValueError):
        result_values_line(RESULT_SCHEMA, "refactor")


def test_the_phase_must_be_one_the_schema_allows():
    """Review of M1.14: the line never tells the agent a phase value its schema would reject."""
    swapped = copy.deepcopy(RESULT_SCHEMA)
    swapped["properties"]["phase"]["enum"] = ["red", "green"]
    with pytest.raises(ValueError):
        result_values_line(swapped, "single")
    assert 'phase is "red"' in result_values_line(swapped, "red")
