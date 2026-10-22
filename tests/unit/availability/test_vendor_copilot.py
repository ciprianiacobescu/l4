"""L4-FAC-020 (SCN-FAC-42): a Copilot profile's vendor is its model's family, `auto` is routed over the built-in set."""

import re
from pathlib import Path

import pytest

from l4.availability.vendor import (
    COPILOT_ROUTED_DEFAULT,
    ROUTED_ADAPTERS,
    ROUTED_DEFAULT,
    ROUTED_DEFAULTS,
    built_in_routed,
    family_vendor,
    is_routed,
    normalise_model,
    resolve_vendor,
)
from l4.config.schema import Profile

HELP_CONFIG = Path(__file__).resolve().parents[2] / "fixtures/recorded/copilot-cli/1.0.102-notoken/help-config.txt"


def copilot(**kw) -> Profile:
    return Profile(adapter="copilot-cli", **kw)


def listed_ids() -> list[str]:
    """The ids `copilot help config` lists under `model`, in listed order."""
    text = HELP_CONFIG.read_text()
    block = text.split("  `model`:", 1)[1].split("  `contextTier`:", 1)[0]
    return re.findall(r'^\s+- "([^"]+)"\s*$', block, re.MULTILINE)


def test_the_new_families():
    assert family_vendor("grok-4.1") == "xai"
    assert family_vendor("mai-code") == "microsoft"
    assert family_vendor("MAI-code-1.1-flash") == "microsoft"
    assert family_vendor("kimi-k3") == "moonshot"  # the existing families are unchanged
    assert family_vendor("claude-sonnet-5.5") == "anthropic" and family_vendor("auto") is None


def test_routed_adapters_and_is_routed():
    assert ROUTED_ADAPTERS == ("kiro-cli", "copilot-cli")
    assert is_routed(copilot()) and is_routed(copilot(model="auto")) and is_routed(copilot(model="AUTO"))
    assert is_routed(copilot(model="  ")) and is_routed(copilot(model=" Auto "))
    assert not is_routed(copilot(model="claude-sonnet-5.5"))
    # kiro-cli's answers are unchanged
    kiro = Profile(adapter="kiro-cli")
    assert is_routed(kiro) and is_routed(Profile(adapter="kiro-cli", model="auto"))
    assert not is_routed(Profile(adapter="kiro-cli", model="glm-5"))
    assert not is_routed(Profile(adapter="opencode")) and not is_routed(Profile(adapter="claude-code"))


def test_a_pinned_copilot_profile_has_its_models_vendor():  # SCN-FAC-42
    assert resolve_vendor(copilot(model="claude-sonnet-5.5")) == ("anthropic", "declared")
    assert resolve_vendor(copilot(model="grok-4.7")) == ("xai", "declared")
    assert resolve_vendor(copilot(model="gpt-6.1-sol", vendor="openai")) == ("openai", "declared")
    # a model of no known family keeps the declared vendor
    assert resolve_vendor(copilot(model="some-new-model", vendor="acme")) == ("acme", "declared")
    assert resolve_vendor(copilot(model="some-new-model")) == (None, "unknown")


def test_an_auto_copilot_profile_is_routed_whatever_vendor_says():
    assert resolve_vendor(copilot()) == (None, "routed")
    assert resolve_vendor(copilot(model="auto", vendor="zhipu")) == (None, "routed")


def test_the_copilot_routed_default_is_the_help_config_list():
    ids = listed_ids()
    assert len(ids) == 31 and len(set(ids)) == 31
    assert all(family_vendor(i) is not None for i in ids)  # no id of an unknown family may enter the set
    assert COPILOT_ROUTED_DEFAULT.models == tuple(sorted(normalise_model(i) for i in ids))
    assert COPILOT_ROUTED_DEFAULT.vendors == tuple(sorted({family_vendor(i) for i in ids}))
    assert COPILOT_ROUTED_DEFAULT.vendors == ("anthropic", "google", "microsoft", "moonshot", "openai", "xai")
    assert "unknown" not in COPILOT_ROUTED_DEFAULT.vendors
    assert COPILOT_ROUTED_DEFAULT.source == "built-in" and COPILOT_ROUTED_DEFAULT.reason is None


def test_built_in_routed_follows_the_adapter():
    assert built_in_routed("p", copilot()) is COPILOT_ROUTED_DEFAULT
    assert built_in_routed("p", copilot(model="auto")) is COPILOT_ROUTED_DEFAULT
    assert built_in_routed("p", Profile(adapter="kiro-cli")) is ROUTED_DEFAULT
    assert ROUTED_DEFAULTS == {"kiro-cli": ROUTED_DEFAULT, "copilot-cli": COPILOT_ROUTED_DEFAULT}


@pytest.mark.parametrize("served", ["claude-sonnet-5.5", "gpt-6.1-sol", "grok-4.7", "mai-code-1.1-flash"])
def test_a_served_model_names_its_vendor(served):
    assert resolve_vendor(copilot(), served)[1] == "served"
