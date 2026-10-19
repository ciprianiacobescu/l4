"""A kiro-cli profile whose vendor contradicts its model's family does not load (kiro-judge SCN-KJD-15)."""

import pytest
from pydantic import ValidationError

from l4.config.schema import Profile


def test_a_vendor_that_contradicts_the_model_fails_to_load():
    with pytest.raises(ValidationError, match="vendor contradicts the model: claude-sonnet-4.5 is made by anthropic"):
        Profile(adapter="kiro-cli", model="claude-sonnet-4.5", vendor="amazon")


def test_the_family_vendor_and_unknown_families_load():
    assert Profile(adapter="kiro-cli", model="glm-5", vendor="zhipu").vendor == "zhipu"
    assert Profile(adapter="kiro-cli", model="glm-5", vendor="Zhipu").model == "glm-5"
    assert Profile(adapter="kiro-cli", model="some-new-model", vendor="acme").vendor == "acme"
    assert Profile(adapter="kiro-cli", model="claude-sonnet-4.5").vendor is None


def test_no_model_or_auto_loads_with_any_vendor():
    """SCN-KJD-16: the vendor of an auto profile is ignored (routed), it does not fail the load."""
    assert Profile(adapter="kiro-cli", vendor="zhipu").model is None
    assert Profile(adapter="kiro-cli", model="auto", vendor="zhipu").model == "auto"
    assert Profile(adapter="kiro-cli", model="AUTO", vendor="amazon").vendor == "amazon"


def test_another_adapter_is_not_checked_by_model_family():
    assert Profile(adapter="opencode", model="opencode/claude-x", vendor="acme").vendor == "acme"
    with pytest.raises(ValidationError, match="vendor contradicts the adapter"):
        Profile(adapter="codex", vendor="anthropic")
