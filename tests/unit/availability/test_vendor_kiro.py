"""The vendor of a kiro-cli profile is its model's family (kiro-judge L4-KJD-005, task 1.1)."""

import pytest

from l4.availability.vendor import MODEL_FAMILIES, family_vendor, normalise_model, resolve_vendor, served_vendor
from l4.config.schema import Profile

PREFIXES = {
    "claude-sonnet-4.5": "anthropic",
    "us.anthropic.claude-sonnet-4-5": "anthropic",
    "anthropic.claude-haiku-4-5": "anthropic",
    "openrouter/anthropic/claude-sonnet-4.5": "anthropic",
    "gpt-5.6-sol": "openai",
    "o3-mini": "openai",
    "gemini-3.5-flash": "google",
    "deepseek-3.2": "deepseek",
    "glm-5": "zhipu",
    "minimax-m2.5": "minimax",
    "qwen3-coder-next": "alibaba",
    "qwen-max": "alibaba",
    "kimi-k3": "moonshot",
    "Claude-Sonnet-4.5": "anthropic",
}


@pytest.mark.parametrize(("model", "vendor"), PREFIXES.items())
def test_every_family_prefix_names_its_vendor(model, vendor):
    assert family_vendor(model) == vendor
    assert served_vendor(model) == vendor


def test_the_table_holds_the_eight_vendors_and_unknown_models_have_none():
    assert {vendor for _, vendor in MODEL_FAMILIES} == {
        "anthropic", "openai", "google", "deepseek", "zhipu", "minimax", "alibaba", "moonshot",
    }  # fmt: skip
    assert family_vendor("some-new-model") is None and family_vendor("auto") is None and family_vendor("") is None
    assert served_vendor("some-new-model") == "unknown"


def kiro(**fields) -> Profile:
    return Profile(adapter="kiro-cli", **fields)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"model": "claude-sonnet-4.5"}, ("anthropic", "declared")),
        ({"model": "claude-sonnet-4.5", "vendor": "Anthropic"}, ("anthropic", "declared")),
        ({"model": "qwen3-coder-next"}, ("alibaba", "declared")),
        ({"model": "glm-5"}, ("zhipu", "declared")),
        ({"model": "some-new-model", "vendor": "acme"}, ("acme", "declared")),
        ({"vendor": "zhipu"}, ("unknown", "unknown")),
        ({"model": "auto", "vendor": "zhipu"}, ("unknown", "unknown")),
        ({"model": "AUTO", "vendor": "zhipu"}, ("unknown", "unknown")),
        ({"model": "  ", "vendor": "zhipu"}, ("unknown", "unknown")),
    ],
)
def test_the_vendor_of_a_kiro_profile(fields, expected):
    assert resolve_vendor(kiro(**fields)) == expected


def test_an_opencode_profile_keeps_its_declared_vendor():
    profile = Profile(adapter="opencode", model="opencode/glm-5", vendor="acme")
    assert resolve_vendor(profile) == ("acme", "declared")
    assert resolve_vendor(Profile(adapter="opencode", vendor="zhipu")) == ("zhipu", "declared")


def test_a_served_model_still_decides_first():
    assert resolve_vendor(kiro(model="glm-5"), "claude-sonnet-4-5") == ("anthropic", "served")


def test_normalise_model_folds_dots_between_digits_dates_and_suffixes():
    assert normalise_model("claude-sonnet-4.5") == "claude-sonnet-4-5"
    assert normalise_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"
    assert normalise_model("Claude-Opus-4.8[1m]") == "claude-opus-4-8"
    assert normalise_model("gpt-5.6-sol") == "gpt-5-6-sol"
    assert normalise_model("qwen3-coder-next") == "qwen3-coder-next"
    assert normalise_model("v1.x") == "v1.x"  # a dot not between digits stays
