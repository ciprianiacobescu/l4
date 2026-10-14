import pytest

from l4.gates.junit import TestCase
from l4.implementer.prompt import PromptContext, load_template, render_prompt
from l4.implementer.result import (
    TRACE_HINT_EITHER,
    TRACE_HINT_NAME,
    TRACE_HINT_PYTEST,
    ImplementerResult,
    check_criteria,
    parse_result,
    trace_rules,
)

A, B = "C-aaaaaaaa", "C-bbbbbbbb"
FAMILY = {A, B}


def ctx() -> PromptContext:
    return PromptContext("openspec:u", "codex", "1.1", "1.1 Task", (), (), ".venv/bin/python -m pytest")


def result(*criteria_ids: str) -> ImplementerResult:
    return parse_result(
        {"status": "done", "phase": "red", "task_ids": ["1"], "summary": "s", "criteria_ids": list(criteria_ids)}
    )


def new(**tests: tuple[str, ...]) -> dict[str, TestCase]:
    return {f"t::{name}": TestCase(f"t::{name}", "failed", criteria=ids) for name, ids in tests.items()}


def test_declared_criteria_each_need_a_tracing_new_test():
    check = check_criteria(result(A, B), FAMILY, new(test_a=(A,), test_b=(B,), test_loose=()))
    assert check.error == "" and check.cited == (A, B)
    assert check.tracing == {A: ("t::test_a",), B: ("t::test_b",)}
    assert check.untraced == ("t::test_loose",)  # recorded, not failed


def test_without_criteria_ids_the_traces_of_the_new_tests_are_cited():
    check = check_criteria(result(), FAMILY, new(test_a=(A,), test_c_bbbbbbbb=()))
    assert check.error == "" and check.cited == (A, B)


def test_a_declared_criterion_no_new_test_traces_fails():
    check = check_criteria(result(A, B), FAMILY, new(test_a=(A,)))
    assert "C-bbbbbbbb" in check.error and "@pytest.mark.l4" in check.error


def test_a_criterion_outside_the_family_fails():
    check = check_criteria(result("C-99999999"), FAMILY, new(test_a=("C-99999999",)))
    assert "C-99999999" in check.error and "not one of" in check.error


def test_neither_source_yields_a_criterion_fails():
    check = check_criteria(result(), FAMILY, new(test_a=(), test_b=()))
    assert "no criterion" in check.error


def test_suppressions_are_parsed_and_default_to_none():
    assert result().suppressions == []
    raw = {"status": "done", "phase": "red", "task_ids": ["1"], "summary": "s",
           "suppressions": [{"file": "a.py", "line": 3, "rule": "F401", "reason": "re-export"}]}  # fmt: skip
    assert parse_result(raw).suppressions[0].rule == "F401"


@pytest.mark.parametrize("role", ["red", "green"])
def test_contract_5_and_red_3_state_the_trace_stub_and_suppression_rules(role: str):
    assert load_template("contract").version == 10 and load_template("red").version == 9
    text = render_prompt(role, ctx()).text  # type: ignore[arg-type]
    for rule in ('@pytest.mark.l4("C-', "`suppressions`", "signature-only", "guarded"):
        assert rule in text, rule
    red = render_prompt("red", ctx()).text
    assert "fail by assertion or with `NotImplementedError`" in red


VITEST = "npx vitest run --reporter=default --reporter=junit --outputFile.junit=.l4-out/junit.xml"


@pytest.mark.parametrize(
    "command",
    [".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml", "uv run pytest -q", "pytest", "cd api && pytest tests"],
)
def test_a_pytest_gate_keeps_the_marker_instruction(command: str):
    """SCN-IMP-65: the trace instruction of a pytest gate is the `l4` marker, as before."""
    assert trace_rules(command).rule == (
        'Tag every test with `@pytest.mark.l4("C-xxxxxxxx")` for each criterion id (listed below) that it checks'
    )


@pytest.mark.parametrize("command", [VITEST, "npx jest --ci", "go test ./...", "pnpm test", "pytest-xdist-runner x"])
def test_another_gate_gets_the_id_in_the_test_name(command: str):
    """SCN-IMP-66: outside pytest the instruction is the id in the test name."""
    rules = trace_rules(command)
    assert 'it("C-xxxxxxxx: …")' in rules.rule and "JUnit report" in rules.rule
    assert "@pytest" not in rules.rule + rules.also + rules.form
    assert "NotImplementedException" in rules.stub and "throw new Error" in rules.stub
    assert rules.hint == TRACE_HINT_NAME and trace_rules("pytest").hint == TRACE_HINT_PYTEST


def test_the_retry_messages_follow_the_hint_they_are_given():
    """SCN-IMP-67: no new test traces a criterion; the message carries the gate's hint."""
    for hint in (TRACE_HINT_PYTEST, TRACE_HINT_NAME):
        untraced = check_criteria(result(A), FAMILY, new(test_a=()), trace_hint=hint).error
        uncovered = check_criteria(result(), FAMILY, new(test_a=()), trace_hint=hint).error
        assert untraced == f"no new test traces {A}: {hint}" and uncovered == f"no criterion is covered: {hint}"
    assert "@pytest" not in TRACE_HINT_NAME and 'it("C-xxxxxxxx: …")' in TRACE_HINT_NAME


def test_without_a_hint_the_messages_name_both_forms():
    """SCN-IMP-67: the loop does not pass the gate's hint yet, so the default names the marker and the name."""
    error = check_criteria(result(A), FAMILY, new(test_a=())).error
    assert error.endswith(TRACE_HINT_EITHER) and "@pytest.mark.l4" in error and 'it("C-xxxxxxxx: …")' in error


def test_the_rendered_contract_follows_the_test_gate():
    """SCN-IMP-65, SCN-IMP-66: pytest keeps the marker sentence word for word; vitest gets the name rule everywhere."""
    pytest_ctx = ctx()
    vitest_ctx = PromptContext("openspec:u", "codex", "1.1", "1.1 Task", (), (), VITEST)
    marker = 'Tag every test with `@pytest.mark.l4("C-xxxxxxxx")` for each criterion id (listed below) that it checks, '
    assert (
        marker + "and report those ids as `criteria_ids`. Untagged tests do not count"
        in render_prompt("red", pytest_ctx).text
    )
    assert '@pytest.mark.l4("<criterion>", "<other criterion>")' in render_prompt("red", pytest_ctx).text
    for role in ("red", "green", "single"):
        text = render_prompt(role, vitest_ctx).text  # type: ignore[arg-type]
        assert "Put each criterion id (listed below) that a test checks in that test's name" in text
        assert "@pytest.mark.l4" not in text and "{trace_" not in text
    assert 'it("<criterion> <other criterion>: …")' in render_prompt("red", vitest_ctx).text
    tests_chore = PromptContext("openspec:u", "codex", "1.1", "t", (), (), VITEST, adds_tests=True)
    chore = render_prompt("single", tests_chore).text
    assert "@pytest" not in chore and "{trace_" not in chore


def test_a_trace_rule_on_the_context_replaces_the_contract_sentence():
    custom = PromptContext("openspec:u", "codex", "1.1", "t", (), (), VITEST, trace_rule="Name the id in the title")
    assert "- Name the id in the title, and report those ids" in render_prompt("green", custom).text


def test_the_stub_sentence_is_empty_for_pytest_and_language_neutral_otherwise():
    """SCN-IMP-68: Python prompts keep their stub rule; other gates are told how a stub throws."""
    assert trace_rules("uv run pytest").stub == ""
    stub = trace_rules(VITEST).stub
    assert stub.startswith(" Outside Python a stub's body only throws a not-implemented error: ")
    assert 'throw new Error("not implemented")` in TypeScript or JavaScript' in stub
    assert "throw new NotImplementedException()` in C#" in stub
    assert render_prompt("red", ctx()).text.count("a bare `pass` body)") == 1
    after_stub = "the rest of the body unchanged)."
    assert after_stub + " Outside Python" not in render_prompt("red", ctx()).text
    vitest_ctx = PromptContext("openspec:u", "codex", "1.1", "1.1 Task", (), (), VITEST)
    assert after_stub + stub in render_prompt("red", vitest_ctx).text
    assert "{trace_" not in render_prompt("green", vitest_ctx).text


def test_a_reopened_tasks_unchanged_criterion_needs_no_new_test_but_the_changed_one_does():
    """L4-OPS-015: the red step of a task a spec edit reopened; A is unchanged (its test exists), B has a new id."""
    ok = check_criteria(result(A, B), FAMILY, new(test_b=(B,)), exempt={A})
    assert ok.error == "" and ok.cited == (A, B) and ok.tracing == {B: ("t::test_b",)}
    missing = check_criteria(result(A, B), FAMILY, new(test_a=(A,)), exempt={A})
    assert B in missing.error and A not in missing.error


def test_without_exempt_every_cited_criterion_still_needs_a_new_test():
    assert A in check_criteria(result(A, B), FAMILY, new(test_b=(B,))).error


def test_an_exempt_criterion_a_new_test_traces_stays_traced():
    check = check_criteria(result(A, B), FAMILY, new(test_a=(A,), test_b=(B,)), exempt={A})
    assert check.error == "" and set(check.tracing) == {A, B}
