"""ci.toolchains in the GitHub workflows (L4-CI-005): SCN-CI-19 (steps) and SCN-CI-20 (byte-identical without)."""

import re
from pathlib import Path

import pytest
import yaml

from l4.ci.github import ActionPin, render_github_action_ci, render_github_ci
from l4.config.schema import L4Config

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ci"
SHA = "a1" * 20
PIN = ActionPin(repository="owner/harness", sha=SHA, ref="v0.3.0")
COPY = ActionPin(repository="owner/harness", sha=SHA, copy=True)
TOOLS = {"go": {"version_file": "go.work"}, "node": {"version": "22"}, "pnpm": {"version": "11"}}


def cfg(toolchains=None, **ci) -> L4Config:
    return L4Config.model_validate({"ci": {**ci, **({"toolchains": toolchains} if toolchains is not None else {})}})


FORMS = {
    "plain": lambda c: render_github_ci(c),
    "action": lambda c: render_github_action_ci(c, PIN),
    "copy": lambda c: render_github_action_ci(c, COPY),
}


def steps_of(text: str) -> list[dict]:
    return yaml.safe_load(text)["jobs"]["l4"]["steps"]


def is_l4(step: dict) -> bool:
    return step.get("id") == "l4" or step.get("name") == "setup l4" or "l4-setup" in step.get("run", "")


@pytest.mark.parametrize("form", FORMS)
def test_scn_ci_19_the_workflow_sets_up_the_toolchains_before_l4(form):
    """SCN-CI-19 (+): pinned setup-go, setup-node and pnpm/action-setup steps before the L4 step, caches off."""
    steps = steps_of(FORMS[form](cfg(TOOLS, runner_tags=[])))
    uses = [s.get("uses", "") for s in steps]
    go = next(i for i, u in enumerate(uses) if u.startswith("actions/setup-go@"))
    node = next(i for i, u in enumerate(uses) if u.startswith("actions/setup-node@"))
    pnpm = next(i for i, u in enumerate(uses) if u.startswith("pnpm/action-setup@"))
    first_l4 = next(i for i, s in enumerate(steps) if is_l4(s) or "doctor" in s.get("run", ""))
    assert go < node < pnpm < first_l4
    assert steps[go]["with"] == {"go-version-file": "go.work", "cache": False}
    assert steps[node]["with"] == {"node-version": "22"}
    assert steps[pnpm]["with"] == {"version": "11"}


def test_the_setup_actions_are_pinned_by_a_full_commit_sha_with_the_release_in_a_comment():
    text = FORMS["plain"](cfg(TOOLS))
    for action in ("actions/setup-go", "actions/setup-node", "pnpm/action-setup"):
        assert re.search(rf"uses: {action}@[0-9a-f]{{40}} # v\d+\.\d+\.\d+\n", text), action


def test_a_version_string_and_a_version_file_render_the_matching_inputs():
    steps = steps_of(FORMS["action"](cfg({"go": {"version": "1.26"}, "node": {"version_file": ".nvmrc"}})))
    withs = [s["with"] for s in steps if s.get("uses", "").startswith(("actions/setup-go", "actions/setup-node"))]
    assert withs == [{"go-version": "1.26", "cache": False}, {"node-version-file": ".nvmrc"}]


def test_only_the_configured_toolchains_get_a_step():
    steps = steps_of(FORMS["action"](cfg({"pnpm": {"version": "11"}})))
    uses = [s.get("uses", "") for s in steps]
    assert not any(u.startswith(("actions/setup-go", "actions/setup-node")) for u in uses)
    assert any(u.startswith("pnpm/action-setup@") for u in uses)


@pytest.mark.parametrize("form", FORMS)
def test_the_toolchain_steps_are_the_only_difference_in_the_job(form):
    """SCN-CI-19 (+): without the three steps the job is the job of a repository with no toolchains."""
    with_tools = steps_of(FORMS[form](cfg(TOOLS, runner_tags=[])))
    kept = [s for s in with_tools if not s.get("uses", "").startswith(("actions/setup-", "pnpm/action-setup"))]
    assert len(with_tools) == len(kept) + 3
    assert kept == steps_of(FORMS[form](cfg(runner_tags=[])))


GOLDENS = [
    ("plain", {"runner_tags": ["agentic"]}, "l4.github.default.yml"),
    ("plain", {"runner_tags": []}, "l4.github.hosted.yml"),
    ("action", {"runner_tags": ["agentic"]}, "l4.github-action.default.yml"),
    ("action", {"runner_tags": []}, "l4.github-action.hosted.yml"),
    ("copy", {"runner_tags": []}, "l4.github-action.copy.yml"),
]


@pytest.mark.parametrize(("form", "ci", "golden"), GOLDENS)
def test_scn_ci_20_no_toolchains_no_steps_byte_identical(form, ci, golden):
    """SCN-CI-20 (+): the files were rendered by the code before this change and are held byte for byte."""
    expected = (FIXTURES / golden).read_text()
    assert FORMS[form](cfg(**ci)) == expected
    assert FORMS[form](cfg({}, **ci)) == expected  # an explicit empty `toolchains: {}` is the same
