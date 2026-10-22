"""The implementer's prompt states the per-test cap with its value (L4-VER-052, SCN-VER-170, SCN-VER-189)."""

import pytest
from tests.unit.implementer.conftest import red_step
from tests.unit.implementer.test_prompt import ctx

from l4.implementer.prompt import load_template, render_prompt
from l4.implementer.tdd import run_red
from l4.specs.base import Task

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
PYTEST = ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"
VITEST = "npx vitest run"
RULE = (
    "A test that traces more than {n} of this unit's criteria counts for none of them "
    "(verifier.max_criteria_per_test), and the harness rejects a red step or test chore that writes one: give each "
    "test one behaviour and at most {n} ids, tag a test only with the criteria whose outcome it asserts, put a "
    "criterion that many tests touch (a precondition, or a list of commands) only on the tests that assert it "
    "directly, and write another test rather than add an id to a test that has {n}."
)


@pytest.mark.parametrize("gate", [PYTEST, VITEST])
@pytest.mark.parametrize("cap", [3, 2])
def test_every_role_states_the_cap_with_its_value(gate: str, cap: int):
    for role, adds in (("red", False), ("green", False), ("single", False), ("single", True)):
        text = render_prompt(role, ctx(gate_command=gate, max_criteria_per_test=cap, adds_tests=adds)).text  # type: ignore[arg-type]
        assert RULE.format(n=cap) in text, (role, adds)
        assert "{max_criteria}" not in text
    red = render_prompt("red", ctx(gate_command=gate, max_criteria_per_test=cap)).text
    assert f"needs at least ⌈K/{cap}⌉ tests" in red
    assert f"when that test then carries at most {cap} ids (else write a new test that asserts a real answer)" in red


def test_the_default_cap_is_three():
    assert RULE.format(n=3) in render_prompt("red", ctx()).text


def test_the_templates_are_versioned():
    versions = {name: load_template(name).version for name in ("contract", "red", "single_tests", "single", "green")}
    assert versions == {"contract": 13, "red": 13, "single_tests": 5, "single": 3, "green": 6}


def test_tdd_passes_the_configured_cap(make_bench):
    bench = make_bench([red_step()], verifier={"max_criteria_per_test": 4})
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    assert "at most 4 ids" in req.prompt and "{max_criteria}" not in req.prompt
