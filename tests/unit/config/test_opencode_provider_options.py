"""An opencode profile may declare a custom OpenAI-compatible provider (SPEC 3.2, 8.3). The key is named by variable
(`api_key_env`), never carried: the options hold no secret and a bad option fails at load without echoing the value."""

import copy

import pytest
from pydantic import ValidationError

from l4.config.redaction import redactor_for_config
from l4.config.schema import L4Config, Profile

MODEL = "qwen3.6-35b-a3b:gguf:q5"
OPTIONS = {
    "provider": {
        "id": "magnitude", "base_url": "http://192.0.2.10:10100/inference/v1", "api_key_env": "MAGNITUDE_API_KEY",
        "models": {MODEL: {"context": 262144, "output": 16384}},
    },
    "tools": ["bash", "edit", "write", "read", "glob", "grep"],
    "reasoning": "none",
}  # fmt: skip


def profile(**options) -> Profile:
    return Profile(adapter="opencode", model=f"magnitude/{MODEL}", auth="api_key", vendor="alibaba", options=options)


def test_the_investigated_block_is_valid_and_parses():
    parsed = profile(**OPTIONS).opencode_options()
    assert parsed is not None and parsed.provider is not None
    assert parsed.provider.id == "magnitude" and parsed.provider.api_key_env == "MAGNITUDE_API_KEY"
    assert parsed.provider.models[MODEL].output == 16384
    assert parsed.tools == ["bash", "edit", "write", "read", "glob", "grep"] and parsed.reasoning == "none"


def test_a_profile_without_options_has_none():
    assert Profile(adapter="opencode", model="opencode/big-pickle").opencode_options() is None
    assert Profile(adapter="codex", options={"sandbox": "x"}).opencode_options() is None


def mutate(path: list[str], value) -> dict:
    out = copy.deepcopy(OPTIONS)
    node = out
    for key in path[:-1]:
        node = node[key]
    if value is KeyError:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


@pytest.mark.parametrize(
    ("path", "value", "needle"),
    [
        (["provider", "base_url"], "ftp://h/v1", "base_url"),
        (["provider", "base_url"], "http://user:pw@h/v1", "base_url"),
        (["provider", "base_url"], "http://h/v1?key=SECRET-VALUE", "base_url"),
        (["provider", "api_key_env"], "has space", "api_key_env"),
        (["provider", "api_key_env"], KeyError, "api_key_env"),
        (["provider", "id"], "Bad Id", "provider.id"),
        (["provider", "models", MODEL, "output"], 0, "output"),
        (["tools"], ["bash", "rm-rf"], "tools"),
        (["tools"], [], "tools"),
        (["reasoning"], "extreme", "reasoning"),
        (["provider", "surprise"], 1, "surprise"),
    ],
)
def test_bad_options_fail_at_load_naming_the_option(path, value, needle):
    with pytest.raises(ValidationError) as caught:
        profile(**mutate(path, value))
    assert needle in str(caught.value)
    assert "SECRET-VALUE" not in str(caught.value) and "pw@" not in str(caught.value)  # the message is value-free


def test_the_model_must_belong_to_the_declared_provider():
    with pytest.raises(ValidationError, match="provider.id"):
        Profile(adapter="opencode", model=f"other/{MODEL}", options=OPTIONS)


def test_reasoning_needs_a_provider_block_to_carry_it():
    with pytest.raises(ValidationError, match="reasoning"):
        Profile(adapter="opencode", model="opencode/big-pickle", options={"reasoning": "none"})


def test_tools_alone_is_valid_for_a_built_in_provider():
    assert Profile(adapter="opencode", model="x/y", options={"tools": ["read"]}).opencode_options() is not None


def test_the_redactor_picks_up_the_key_variable_through_the_provider_block():
    cfg = L4Config.model_validate({"profiles": {"mag": profile(**OPTIONS).model_dump()}})
    red = redactor_for_config(cfg, {"MAGNITUDE_API_KEY": "sk-magnitude-secret-0123456789"})
    assert "sk-magnitude-secret-0123456789" not in red.redact_text("Bearer sk-magnitude-secret-0123456789")
