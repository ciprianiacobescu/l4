"""M1.13 line 7 (MAG): the alias targets the directory the opencode config already allows; the SPEC says what it is."""

import json
from pathlib import Path

from l4.agents.base import PermissionPolicy
from l4.agents.opencode import config_content

SPEC = Path(__file__).resolve().parents[3] / "docs" / "SPEC.md"


def test_the_external_directory_rule_allows_the_step_dir_only_after_the_deny_all():
    config = json.loads(config_content(PermissionPolicy("implement"), Path("/c/units/fw/u/agent-tmp"), "x/y"))
    rule = config["permission"]["external_directory"]
    assert list(rule) == ["*", "/c/units/fw/u/agent-tmp/**", "/c/units/fw/u/agent-tmp/*"]  # last match wins
    assert rule["*"] == "deny" and set(rule.values()) == {"deny", "allow"}


def test_the_spec_says_what_the_alias_is_and_what_it_is_not():
    text = SPEC.read_text(encoding="utf-8")
    assert "`.l4-result/result.json`" in text and "`<worktree>/agent-tmp/result.json`" in text
    assert "is never a result" in text
