import pytest

from l4.ci.github import render_github_ci
from l4.ci.lint import lint_github_yaml
from l4.config.schema import L4Config

GOOD = render_github_ci(L4Config())


def broken(old: str, new: str) -> str:
    assert old in GOOD
    return GOOD.replace(old, new)


def test_cancelling_concurrency_rejected():
    problems = lint_github_yaml(broken("cancel-in-progress: false", "cancel-in-progress: true"))
    assert any("cancels runs in progress" in p for p in problems)
    expression = broken("cancel-in-progress: false", "cancel-in-progress: ${{ github.ref != 'main' }}")
    assert lint_github_yaml(expression)  # an expression cannot be shown to be false


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("persist-credentials: false", "persist-credentials: true", "persist-credentials"),
        ("    timeout-minutes: 180\n", "", "timeout-minutes"),
        (
            "permissions:\n  contents: write\n  pull-requests: write\n  issues: write\n  checks: read\n"
            "  statuses: write\n  actions: write\n",
            "",
            "permissions",
        ),
        ("  workflow_dispatch:\n", "  workflow_dispatch:\n  pull_request:\n", "pull_request"),
        ("  workflow_dispatch:\n", "  workflow_dispatch:\n  pull_request_target:\n", "pull_request_target"),
        ("  workflow_dispatch:\n", "  workflow_dispatch:\n  issue_comment:\n", "issue_comment"),
    ],
)
def test_policy_violations_are_named(old, new, expected):
    problems = lint_github_yaml(broken(old, new))
    assert problems and (expected is None or any(expected in p for p in problems))


def test_missing_concurrency_is_rejected_unless_the_workflow_sets_it():
    no_concurrency = broken("    concurrency:\n      group: l4\n      cancel-in-progress: false\n", "")
    assert any("no concurrency" in p for p in lint_github_yaml(no_concurrency))
    workflow_level = no_concurrency.replace(
        "jobs:\n", "concurrency:\n  group: l4\n  cancel-in-progress: false\njobs:\n"
    )
    assert lint_github_yaml(workflow_level) == []


def test_unparseable_and_jobless_documents():
    assert lint_github_yaml("a: [") == ["the workflow is not valid YAML"]
    assert lint_github_yaml("name: x\n") == ["the workflow has no jobs"]
    assert lint_github_yaml("- a\n") == ["the workflow has no jobs"]


def test_list_and_string_triggers_are_understood():
    as_list = (
        "on: [push, pull_request]\npermissions: {}\njobs:\n  a:\n    timeout-minutes: 1\n    concurrency: {group: g}\n"
    )
    assert any("pull_request" in p for p in lint_github_yaml(as_list))
    as_string = as_list.replace("[push, pull_request]", "pull_request")
    assert any("pull_request" in p for p in lint_github_yaml(as_string))


def test_the_job_start_step_passes_the_lint():
    """L4-IMP-066: the first step of both forms is a plain `run`; the lint checks permissions, triggers and
    concurrency, not the steps."""
    from l4.ci.github import ActionPin, render_github_action_ci

    assert "- name: job start\n" in GOOD
    assert lint_github_yaml(GOOD) == []
    action = render_github_action_ci(L4Config(), ActionPin("owner/harness", "a1" * 20))
    assert "- name: job start\n" in action
    assert lint_github_yaml(action) == []
