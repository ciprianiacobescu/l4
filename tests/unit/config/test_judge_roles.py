"""L4-CFG-006: a judge role holds only adapters that can judge, checked when the configuration loads."""

import ast
from pathlib import Path

import pytest

from l4.config.loader import ConfigSchemaError, load_config_text

CMD = (
    "profiles.cmd is in roles.judges, but its adapter command cannot judge (a judge call has no tools): an adapter "
    "profile in roles.judges, roles.verifier_agent, roles.clarifier or roles.s1_judge must use one of claude-code, "
    "codex, opencode, kiro-cli, copilot-cli, fake; remove cmd from roles.judges at $"
)


def load(text: str) -> str:
    with pytest.raises(ConfigSchemaError) as err:
        load_config_text(text)
    return str(err.value)


def test_a_command_judge_fails_at_load_by_name():
    text = (
        "profiles:\n  cmd: {adapter: command, options: {argv: [tool]}}\n  claude: {adapter: claude-code}\n"
        "roles: {judges: [cmd, claude]}\n"
    )
    assert load(text) == CMD


@pytest.mark.parametrize("role", ["judges", "verifier_agent", "clarifier", "s1_judge"])
def test_a_kiro_cli_profile_loads_in_every_judge_role(role):
    """kiro-judge L4-KJD-008: kiro-cli is a judge adapter, so the load check of L4-CFG-006 passes it in every role."""
    cfg = load_config_text(f"profiles:\n  kiro: {{adapter: kiro-cli}}\nroles: {{{role}: [kiro]}}\n")
    assert getattr(cfg.roles, role) == ["kiro"]


@pytest.mark.parametrize(
    ("role", "adapter", "known"),
    [
        ("verifier_agent", "command", "command"),
        ("clarifier", "command", "command"),
        ("s1_judge", "command", "command"),
        ("judges", "mystery-cli", "(not one the harness knows)"),
    ],
)
def test_every_judge_role_is_checked(role, adapter, known):
    options = ", options: {argv: [tool]}" if adapter == "command" else ""
    text = f"profiles:\n  odd: {{adapter: {adapter}{options}}}\nroles: {{{role}: [odd]}}\n"
    message = load(text)
    assert f"profiles.odd is in roles.{role}, but its adapter {known} cannot judge" in message
    assert f"remove odd from roles.{role} at $" in message
    if adapter == "mystery-cli":
        assert "(not one the harness knows)" in message and "mystery-cli" not in message


def test_backend_profiles_allowed_adapters_and_undefined_names_load():
    cfg = load_config_text(
        "profiles:\n"
        "  laya: {backend: system-one, model: x}\n"
        "  judge-sol: {backend: openai-chat, model: x}\n"
        "  claude: {adapter: claude-code}\n"
        "  oc: {adapter: opencode}\n"
        "roles:\n  s1_judge: [laya, judge-sol]\n  judges: [claude, oc]\n  clarifier: [nope]\n"
        "  implementer: [kiro-not-defined]\n"
    )
    assert cfg.roles.clarifier == ["nope"]
    cfg = load_config_text(
        "profiles:\n  kiro: {adapter: kiro-cli}\nroles: {implementer: [kiro], spec_writer: [kiro]}\n"
    )
    assert cfg.roles.implementer == ["kiro"]


def test_the_constants_are_one():
    from l4.agents.factory import ADAPTERS
    from l4.config import roles
    from l4.llm import agent_judge

    assert agent_judge.JUDGE_ADAPTERS is roles.JUDGE_ADAPTERS
    assert set(roles.HARNESS_ADAPTERS) == set(ADAPTERS)
    tree = ast.parse(Path(roles.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "l4" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "l4" and node.level == 0


def test_copilot_cli_is_a_judge_and_a_harness_adapter_before_fake():
    """copilot-cli 4.2 (SCN-FAC-25)."""
    from l4.agents.factory import ADAPTERS
    from l4.config import roles

    for table in (roles.JUDGE_ADAPTERS, roles.HARNESS_ADAPTERS):
        assert "copilot-cli" in table and table.index("copilot-cli") < table.index("fake")
    assert "copilot-cli" in ADAPTERS and set(roles.HARNESS_ADAPTERS) == set(ADAPTERS)


def test_a_copilot_profile_holds_every_judge_role():
    cfg = load_config_text(
        "profiles:\n  copilot: {adapter: copilot-cli, model: claude-sonnet-5.5}\n"
        "roles: {judges: [copilot], clarifier: [copilot], verifier_agent: [copilot], s1_judge: [copilot]}\n"
    )
    assert cfg.roles.judges == cfg.roles.clarifier == cfg.roles.verifier_agent == cfg.roles.s1_judge == ["copilot"]
