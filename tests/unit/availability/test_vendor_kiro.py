"""The vendor of a kiro-cli profile is its model's family (kiro-judge L4-KJD-005, task 1.1)."""

import json
from pathlib import Path

import pytest

from l4.availability.vendor import (
    MODEL_FAMILIES,
    ROUTED_DEFAULT,
    RoutedSet,
    active_model_ids,
    built_in_with_reason,
    family_vendor,
    is_routed,
    normalise_model,
    resolve_vendor,
    routed_from_listing,
    served_vendor,
)
from l4.config.schema import Profile

LISTING = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli" / "2.32.0" / "list-models.json").read_text()
)

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


def test_the_table_holds_the_ten_vendors_and_unknown_models_have_none():  # xai and microsoft: copilot-cli 1.3
    assert {vendor for _, vendor in MODEL_FAMILIES} == {
        "anthropic", "openai", "google", "deepseek", "zhipu", "minimax", "alibaba", "moonshot", "xai", "microsoft",
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
        ({}, (None, "routed")),
        ({"vendor": "zhipu"}, (None, "routed")),  # SCN-KJD-16: auto is routed, whatever vendor says
        ({"model": "auto", "vendor": "zhipu"}, (None, "routed")),
        ({"model": "AUTO", "vendor": "zhipu"}, (None, "routed")),
        ({"model": "  ", "vendor": "zhipu"}, (None, "routed")),
        ({"model": "auto"}, (None, "routed")),
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


def test_the_active_models_of_the_recorded_listing():
    """SCN-KJD-31: 12 Active ids; `auto` and the 8 Experimental entries are out, an entry with no description is in."""
    ids = active_model_ids(LISTING)
    assert ids is not None and len(ids) == 12
    assert ids[0] == "claude-sonnet-5.5" and ids[-1] == "glm-5"
    for out in ("auto", "claude-opus-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "deepseek-3.2",
                "minimax-m2.1", "qwen3-coder-next", "kimi-k3"):  # fmt: skip
        assert out not in ids
    assert "claude-opus-5" in ids  # no description: Active
    assert {family_vendor(i) for i in ids} == {"anthropic", "minimax", "zhipu"}


def test_the_built_in_set_is_the_set_computed_from_the_recorded_listing():
    """SCN-KJD-32, second part. Both sides are normalised and sorted."""
    computed = routed_from_listing(LISTING)
    assert computed is not None
    assert (computed.vendors, computed.models) == (ROUTED_DEFAULT.vendors, ROUTED_DEFAULT.models)
    assert ROUTED_DEFAULT.vendors == ("anthropic", "minimax", "zhipu") and ROUTED_DEFAULT.source == "built-in"
    assert "claude-sonnet-4-5" in ROUTED_DEFAULT.models and "glm-5" in ROUTED_DEFAULT.models
    assert len(ROUTED_DEFAULT.models) == 12


def test_a_listed_model_of_no_known_family_adds_unknown_to_the_union():
    """SCN-KJD-33 (owner's decision: the union with the built-in set)."""
    listing = {"models": [{"model_id": "glm-5", "description": "GLM-5 model"}, {"model_id": "some-new-model"}]}
    found = routed_from_listing(listing)
    assert found is not None and found.source == "listed"
    assert found.vendors == ("anthropic", "minimax", "unknown", "zhipu")


def test_a_listing_that_grew_adds_its_vendor_and_a_shrunk_one_loses_none():
    grown = {"models": [{"model_id": "deepseek-3.2", "description": "DeepSeek V3.2"}]}
    assert routed_from_listing(grown).vendors == ("anthropic", "deepseek", "minimax", "zhipu")  # type: ignore[union-attr]
    shrunk = {"models": [{"model_id": "glm-5"}]}
    assert routed_from_listing(shrunk).vendors == ROUTED_DEFAULT.vendors  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "listing",
    [None, [], {}, {"models": {}}, {"models": []}, {"models": [{"model_id": "auto"}]},
     {"models": [{"model_id": "x-1", "description": "Experimental preview"}]}, {"models": ["glm-5"]}],
)  # fmt: skip
def test_a_listing_with_no_active_model_gives_nothing(listing):
    assert active_model_ids(listing) is None and routed_from_listing(listing) is None


def test_the_experimental_words_are_matched_in_any_letter_case():
    for words in ("PREVIEW of X", "an Experimental build", "Kimi is a Kiro EXCLUDED MODEL"):
        assert active_model_ids({"models": [{"model_id": "m-1", "description": words}]}) is None


def test_a_recorded_set_round_trips_and_a_malformed_one_is_not_believed():
    found = built_in_with_reason("kiro-cli chat --list-models failed (exit 1)")
    assert found.source == "built-in" and found.reason
    assert RoutedSet.from_detail(found.to_detail()) == found
    assert RoutedSet.from_detail(ROUTED_DEFAULT.to_detail()) == ROUTED_DEFAULT
    bad_ones = [
        None, "x", {}, {"source": "listed"}, {"source": "other", "vendors": ["a"], "models": []},
        {"source": "listed", "vendors": [], "models": []}, {"source": "listed", "vendors": [1], "models": []},
    ]  # fmt: skip
    for bad in bad_ones:
        assert RoutedSet.from_detail(bad) is None


def test_is_routed_is_kiro_cli_with_no_model_or_auto():
    assert is_routed(kiro()) and is_routed(kiro(model=" AUTO ")) and not is_routed(kiro(model="glm-5"))
    assert not is_routed(Profile(adapter="opencode"))


def test_a_listing_with_a_top_level_default_model_parses_the_same():
    """kiro-judge live: kiro-cli 2.32.0 prints `{"models": [...], "default_model": "auto"}`; only `models` is read."""
    bare = {"models": LISTING["models"]}
    for extra in ({"default_model": "auto"}, {"default_model": "claude-sonnet-5.5", "other": [1]}):
        assert routed_from_listing({**bare, **extra}) == routed_from_listing(bare)
        assert active_model_ids({**bare, **extra}) == active_model_ids(bare)
    assert routed_from_listing({"default_model": "auto"}) is None  # the key alone is not a listing
