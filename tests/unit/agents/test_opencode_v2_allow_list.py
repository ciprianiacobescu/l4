"""The OpenCode v2 implementer's permissions are an allow-list (L4-OCV-015, L4-OCV-005 amended; SCN-OCV-29 to -31): a
refuse-all comes first, so an OpenCode tool no rule names starts refused. Nothing here starts a process."""

import json
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy
from l4.agents.opencode_v2 import config_content_v2
from l4.config.schema import Profile

RESULT_DIR = Path("/tmp/l4-step/result")
PAID = "opencode-go/deepseek-v4.1-flash"
FREE = "opencode/big-pickle"
IMPLEMENT, JUDGE = PermissionPolicy("implement"), PermissionPolicy("judge")


def rule(action: str, resource: str, effect: str) -> dict[str, str]:
    return {"action": action, "resource": resource, "effect": effect}


def rules_of(policy: PermissionPolicy, model: str = PAID, **options) -> list[dict[str, str]]:
    profile = Profile(adapter="opencode", model=model, vendor="unknown", options={"cli_major": 2, **options})
    return json.loads(config_content_v2(policy, RESULT_DIR, model, profile.opencode_options()))["permissions"]


def effect_of(rules: list[dict[str, str]], action: str, resource: str) -> str | None:
    """The last rule whose action and resource both match decides (`*` spans any text)."""
    decided = None
    for item in rules:
        if fnmatchcase(action, item["action"]) and fnmatchcase(resource, item["resource"]):
            decided = item["effect"]
    return decided


def tail(refuse: str) -> list[dict[str, str]]:  # the rules of 0.4.55 after the allows and the git denies
    return [
        rule("external_directory", "*", "deny"), rule("external_directory", f"{RESULT_DIR}/**", "allow"),
        rule("external_directory", f"{RESULT_DIR}/*", "allow"), rule("webfetch", "*", "deny"),
        rule("websearch", "*", "deny"), rule("question", "*", "deny"), rule("skill", "*", refuse),
        rule("subagent", "*", refuse),
    ]  # fmt: skip


GIT_DENIES = [rule("shell", pattern, "deny") for pattern in ("git commit*", "git push*", "git reset*", "git checkout*")]


def implement_0455(refuse: str) -> list[dict[str, str]]:
    """The implement array of 0.4.55, read off the code before this change; the OpenCode CLI denies are not in it."""
    return [
        rule("edit", "*", "allow"), rule("read", "*", "allow"), rule("glob", "*", "allow"), rule("grep", "*", "allow"),
        rule("shell", "*", "allow"), *GIT_DENIES, *tail(refuse),
    ]  # fmt: skip


TOOLS_0455 = [rule("*", "*", "deny"), rule("read", "*", "allow"), rule("edit", "*", "allow"), *tail("deny")]
JUDGE_PAID_0455 = [rule("*", "*", "deny")]
JUDGE_FREE_0455 = [rule("*", "*", "deny"), rule("read", "*", "ask"), rule("shell", "*", "ask")]


def without_cli_denies(rules: list[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in rules if not (item["action"] == "shell" and "opencode" in item["resource"])]


@pytest.mark.parametrize(("model", "refuse"), [(PAID, "deny"), (FREE, "ask")])
def test_scn_ocv_29_an_implementers_rules_start_with_a_refuse_all(model, refuse):
    rules = rules_of(IMPLEMENT, model)
    assert rules[0] == {"action": "*", "resource": "*", "effect": refuse}
    assert without_cli_denies(rules[1:]) == implement_0455(refuse)


@pytest.mark.parametrize(
    "action",
    [
        "opencode_worktree_create", "opencode_worktree_list", "opencode_session_move", "opencode_session_rename",
        "opencode_models", "opencode_list_mcp_resources", "opencode_read_mcp_resource", "execute",
        "experimental_image_generate", "a_tool_added_later",
    ],
)  # fmt: skip
def test_scn_ocv_30_opencodes_own_tools_and_an_unknown_tool_are_refused_to_an_implementer(action):
    rules = rules_of(IMPLEMENT)
    assert [i for i in rules if fnmatchcase(action, i["action"]) and fnmatchcase("calc.py", i["resource"])] == [
        rules[0]
    ]
    assert effect_of(rules, action, "calc.py") == "deny"


def test_scn_ocv_30_the_tools_l4_names_stay_allowed():
    rules = rules_of(IMPLEMENT)
    for action in ("edit", "read", "glob", "grep"):
        assert effect_of(rules, action, "calc.py") == "allow", action
    assert effect_of(rules, "shell", "ls") == "allow"


def test_a_free_implementers_unknown_tool_is_asked_not_denied():
    """A removed tool gets a 403 from the free tier: the free refuse-all is `ask` (L4-OCV-005)."""
    assert effect_of(rules_of(IMPLEMENT, FREE), "opencode_worktree_create", "calc.py") == "ask"


def test_scn_ocv_31_options_tools_and_the_judges_keep_their_arrays():
    assert rules_of(IMPLEMENT, tools=["read", "edit"]) == TOOLS_0455
    assert rules_of(JUDGE) == JUDGE_PAID_0455
    assert rules_of(JUDGE, FREE) == JUDGE_FREE_0455
    for rules in (TOOLS_0455, JUDGE_PAID_0455, JUDGE_FREE_0455):
        assert [i for i in rules if i["action"] == "*"] == [rules[0]]  # one `*` rule, the first
