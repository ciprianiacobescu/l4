"""A person's decision at the head of a task is binding in the red and green prompts (reject-reason 4.1)."""

import pytest
from tests.unit.implementer.test_prompt import ctx

from l4.implementer.prompt import render_prompt

RULE = 'If the task begins with a decision by a human ("Decided by ... in Q-..."), the person\'s decision is binding: '


@pytest.mark.parametrize(
    "role,must",
    [
        ("red", "your tests MUST assert what that decision describes"),
        ("green", "your change MUST do what that decision describes"),
    ],
)
def test_red_and_green_prompts_carry_the_decision_rule(role: str, must: str):
    text = render_prompt(role, ctx()).text  # type: ignore[arg-type]
    assert RULE + must in text


def test_single_keeps_its_decision_rule():
    assert "your change MUST do what that decision describes" in render_prompt("single", ctx()).text
