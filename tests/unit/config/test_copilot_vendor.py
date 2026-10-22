"""A copilot-cli profile whose vendor contradicts its model's family does not load (L4-FAC-020, SCN-FAC-42)."""

import pytest
from pydantic import ValidationError

from l4.availability.vendor import resolve_vendor
from l4.config.schema import L4Config, Profile


def test_a_vendor_that_contradicts_the_model_fails_to_load():  # SCN-FAC-42
    with pytest.raises(ValidationError, match="vendor contradicts the model: claude-sonnet-5.5 is made by anthropic"):
        Profile(adapter="copilot-cli", model="claude-sonnet-5.5", vendor="microsoft")
    with pytest.raises(ValidationError, match="vendor contradicts the model: grok-4.1 is made by xai"):
        L4Config.model_validate(
            {"profiles": {"p": {"adapter": "copilot-cli", "model": "grok-4.1", "vendor": "openai"}}}
        )


def test_the_family_vendor_and_unknown_families_load():
    assert Profile(adapter="copilot-cli", model="grok-4.1", vendor="xai").vendor == "xai"
    assert Profile(adapter="copilot-cli", model="grok-4.1", vendor="XAI").model == "grok-4.1"
    assert Profile(adapter="copilot-cli", model="some-new-model", vendor="acme").vendor == "acme"
    assert Profile(adapter="copilot-cli", model="claude-sonnet-5.5").vendor is None


@pytest.mark.parametrize("unknown", ["unknown", "Unknown", " UNKNOWN "])
def test_vendor_unknown_is_no_claim_and_loads(unknown):
    profile = Profile(adapter="copilot-cli", model="claude-sonnet-5.5", vendor=unknown)
    assert resolve_vendor(profile) == ("anthropic", "declared")


def test_an_auto_profile_with_a_vendor_loads_and_stays_routed():
    for model in (None, "auto", "AUTO"):
        profile = Profile(adapter="copilot-cli", model=model, vendor="zhipu")
        assert profile.vendor == "zhipu" and resolve_vendor(profile) == (None, "routed")


def test_another_adapter_is_not_checked_by_model_family():
    assert Profile(adapter="opencode", model="opencode/claude-x", vendor="acme").vendor == "acme"
