"""The agent's shell may not start the OpenCode CLI (L4-OCV-016; SCN-OCV-33, -34). The denies are a guard: the sandbox
is the boundary. Nothing here starts a process."""

import json
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy
from l4.agents.opencode import GIT_WRITES, config_content
from l4.agents.opencode_v2 import OPENCODE_CLI, config_content_v2
from l4.config.schema import Profile

RESULT_DIR = Path("/tmp/l4-step/result")
PAID = "opencode-go/deepseek-v4.1-flash"
FREE = "opencode/big-pickle"
IMPLEMENT, JUDGE = PermissionPolicy("implement"), PermissionPolicy("judge")
CLI_DENIES = [{"action": "shell", "resource": pattern, "effect": "deny"} for pattern in OPENCODE_CLI]
CLI_COMMANDS = [
    "opencode2 api GET /api/project",
    "opencode serve --service",
    "/home/u/.local/bin/opencode2 run x",
    "node_modules/.bin/opencode --version",
]
ORDINARY_COMMANDS = [
    "ruff check src/l4/agents/opencode_v2.py",
    "cat src/l4/agents/opencode.py",
    "ls tests/fixtures/recorded/opencode",
]


def rules_of(policy: PermissionPolicy, model: str = PAID, **options) -> list[dict[str, str]]:
    profile = Profile(adapter="opencode", model=model, vendor="unknown", options={"cli_major": 2, **options})
    return json.loads(config_content_v2(policy, RESULT_DIR, model, profile.opencode_options()))["permissions"]


def shell_effect(rules: list[dict[str, str]], command: str) -> str | None:
    """The last `shell` rule whose resource matches the command decides (`*` spans any text)."""
    decided = None
    for item in rules:
        if item["action"] == "shell" and fnmatchcase(command, item["resource"]):
            decided = item["effect"]
    return decided


def test_the_deny_patterns_are_the_three_of_the_spec():
    assert OPENCODE_CLI == ("opencode*", "opencode2*", "*bin/opencode*")


@pytest.mark.parametrize("options", [{}, {"tools": ["bash", "read"]}], ids=["default", "tools-bash-read"])
def test_scn_ocv_33_the_shell_may_not_start_the_opencode_cli(options):
    rules = rules_of(IMPLEMENT, **options)
    last_git = max(i for i, item in enumerate(rules) if item["resource"] in GIT_WRITES)
    assert rules[last_git + 1 : last_git + 4] == CLI_DENIES  # right after the last git deny
    for command in CLI_COMMANDS:
        assert shell_effect(rules, command) == "deny", command
    for command in ORDINARY_COMMANDS:
        assert shell_effect(rules, command) == "allow", command


def test_scn_ocv_33_a_free_model_gets_the_same_denies():
    rules = rules_of(IMPLEMENT, FREE)
    assert [i for i in rules if i["action"] == "shell" and "opencode" in i["resource"]] == CLI_DENIES
    assert all(shell_effect(rules, command) == "deny" for command in CLI_COMMANDS)


def test_the_path_pattern_has_no_slash_before_bin():
    """`*/bin/opencode*` would miss npm's `.bin`, and `*/opencode*` would refuse a path that holds `/opencode`."""
    assert (
        "*bin/opencode*" in OPENCODE_CLI and "*/bin/opencode*" not in OPENCODE_CLI and "*/opencode*" not in OPENCODE_CLI
    )
    assert not fnmatchcase("node_modules/.bin/opencode --version", "*/bin/opencode*")  # the miss the choice avoids
    assert fnmatchcase("ls tests/fixtures/recorded/opencode", "*/opencode*")  # the refusal the choice avoids


@pytest.mark.parametrize(
    "rules",
    [
        pytest.param(rules_of(IMPLEMENT, tools=["read", "edit"]), id="tools-read-edit"),
        pytest.param(rules_of(JUDGE), id="judge-paid"),
        pytest.param(rules_of(JUDGE, FREE), id="judge-free"),
    ],
)
def test_scn_ocv_34_no_cli_deny_without_a_shell(rules):
    assert not [item for item in rules if "opencode" in item["resource"]]


def test_scn_ocv_34_the_v1_configuration_is_unchanged():
    """v1 gets no CLI deny (design D3): its `OPENCODE_CONFIG_CONTENT` of an implementer is 0.4.55's, which
    `test_factory_opencode_major.py` pins as a literal (that test passes without an edit)."""
    document = json.loads(config_content(IMPLEMENT, RESULT_DIR, PAID))
    assert document["permission"]["bash"] == {"*": "allow", **{pattern: "deny" for pattern in GIT_WRITES}}
    assert "opencode" not in json.dumps(document["permission"])
