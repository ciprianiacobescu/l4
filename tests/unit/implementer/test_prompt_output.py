"""SCN-IMP-186 and SCN-IMP-187 at render level: the `# Output` section of a prompt-contract step (design D1)."""

import json
from pathlib import Path

import pytest
from tests.unit.implementer.test_prompt import ctx

from l4.implementer.prompt import Role, load_template, render_prompt
from l4.implementer.result import FILE_RESULT_SCHEMA

PATH = Path(".l4-result/result.json")
FIRST = (
    '# Output\nGive the result of this step as one JSON object with "status" and "summary": "status" is "done" when '
    'you did the step, or "blocked" when you need an answer from a person (then "questions" holds at least one '
    'question), and "summary" tells in one to three sentences what you did.'
)


def output_of(role: Role, **over: object) -> str:
    text = render_prompt(role, ctx(**over)).text
    return text[text.index("# Output") :]


def test_a_prompt_contract_output_starts_with_status_and_summary_and_ends_with_the_path():  # SCN-IMP-186
    out = output_of("red", result_path=PATH, adapter="opencode")
    assert out.startswith(FIRST + "\n")
    assert out.rstrip("\n").splitlines()[-1] == "Write your result object to `.l4-result/result.json`."
    assert "final message" not in out
    schema = json.dumps(FILE_RESULT_SCHEMA, separators=(",", ":"), sort_keys=True)
    assert f"The object must conform to this JSON Schema: {schema}" in out
    assert '"required":["status","summary"]' in out
    for key in ("phase", "task_ids", "files_changed", "tests_added"):
        assert f'"{key}"' not in json.dumps(FILE_RESULT_SCHEMA["properties"])
    assert "{schema}" not in out and "{path}" not in out


def test_the_output_template_is_version_1_and_the_version_names_it():
    assert load_template("output").version == 1
    assert render_prompt("red", ctx(result_path=PATH)).template_version == "contract@11+red@10+output@1"
    assert render_prompt("single", ctx(result_path=PATH)).template_version.endswith("+output@1")


@pytest.mark.parametrize("role", ["red", "green", "single"])
def test_a_native_output_is_todays_text_and_the_version_has_no_output(role: Role):  # SCN-IMP-187
    fields = (
        f'phase "{role}", task_ids ["1.1"], criteria_ids = the criterion ids your work traces, '
        "tests_added = the pytest node ids you added, suppressions = every new `# noqa` or `# type: ignore`, "
        "files_changed; use null for anything you have nothing for."
    )
    rendered = render_prompt(role, ctx())
    assert rendered.text.endswith(
        f"# Output\nYour final message is the result JSON object (schema enforced): {fields}\n"
    )
    assert "+output" not in rendered.template_version
