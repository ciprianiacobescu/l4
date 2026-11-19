"""SCN-FAC-54, SCN-FAC-55 (L4-FAC-023): `options.max_output_tokens` is a whole number from 1024 to 256000, at most a
custom provider's model output and below the profile's `context_window`; no message repeats the value."""

import pytest
from pydantic import ValidationError

from l4.config.schema import Profile

MODEL = "opencode-go/deepseek-v4.1-flash"
CUSTOM_MODEL = "qwen3.6-35b-a3b:gguf:q5"
RULE = "options.max_output_tokens: must be a whole number from 1024 to 256000"


def profile(model: str = MODEL, context_window: int | None = None, **options) -> Profile:
    return Profile(adapter="opencode", model=model, auth="api_key", context_window=context_window, options=options)


def custom(output: int, *, context: int = 262144, **options) -> Profile:
    provider = {
        "id": "magnitude",
        "base_url": "http://192.0.2.10:10100/inference/v1",
        "api_key_env": "MAGNITUDE_API_KEY",
        "models": {CUSTOM_MODEL: {"context": context, "output": output}},
    }
    return Profile(
        adapter="opencode",
        model=f"magnitude/{CUSTOM_MODEL}",
        auth="api_key",
        vendor="alibaba",
        options={"provider": provider, **options},
    )


def messages(build) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        build()
    return [error["ctx"]["error"].args[0] if "ctx" in error else error["msg"] for error in caught.value.errors()]


@pytest.mark.parametrize("cli_major", [1, 2])
@pytest.mark.parametrize("value", [1024, 32000, 256000])
def test_a_whole_number_in_range_loads(value, cli_major):
    assert profile(cli_major=cli_major, max_output_tokens=value).opencode_options().max_output_tokens == value


@pytest.mark.parametrize("value", [1023, 256001, 0, -1, True, 65536.0, "65536"])
def test_anything_else_is_refused_without_the_value(value):
    found = messages(lambda: profile(max_output_tokens=value))
    assert found == [RULE]


@pytest.mark.parametrize("value", [1023, 256001, 65536.0, "65536"])
def test_the_value_is_never_echoed(value):
    assert str(value) not in messages(lambda: profile(max_output_tokens=value))[0]


def test_absent_the_key_is_none():
    assert profile().opencode_options() is None
    assert profile(reasoning=None).opencode_options().max_output_tokens is None
    assert profile(cli_major=2).opencode_options().max_output_tokens is None


def test_a_key_above_the_custom_providers_model_output_is_refused():
    expected = (
        "options.max_output_tokens is above the output of the model's entry in options.provider.models "
        "(OpenCode asks for the smaller): raise the entry's output or lower the key"
    )
    assert expected in messages(lambda: custom(16384, max_output_tokens=32000))
    assert custom(16384, max_output_tokens=16384).opencode_options().max_output_tokens == 16384
    assert custom(16384, max_output_tokens=1024).opencode_options().max_output_tokens == 1024
    assert custom(65536, max_output_tokens=65536).opencode_options().max_output_tokens == 65536


def test_a_key_at_or_above_the_custom_providers_model_context_is_refused():
    expected = (
        "options.max_output_tokens must be below the context of the model's entry in options.provider.models "
        "(the prompt and the reply share the window)"
    )
    for key in (65536, 70000):  # the entry's output (100000) is above both: only the context rule applies
        found = messages(lambda key=key: custom(100000, context=65536, max_output_tokens=key))
        assert found == [expected] and str(key) not in found[0]
    assert custom(100000, context=65536, max_output_tokens=65535).opencode_options().max_output_tokens == 65535
    both = messages(lambda: custom(16384, context=16384, max_output_tokens=20000))  # above the output and the context
    assert len(both) == 1 and expected in both[0] and "above the output of the model's entry" in both[0]
    assert custom(16384, context=16385, max_output_tokens=16384).opencode_options().max_output_tokens == 16384


def test_a_key_at_or_above_context_window_is_refused():
    expected = "options.max_output_tokens must be below context_window (the prompt and the reply share the window)"
    assert expected in messages(lambda: profile(context_window=65536, max_output_tokens=65536))
    assert expected in messages(lambda: profile(context_window=65536, max_output_tokens=100000))
    assert profile(context_window=65536, max_output_tokens=65535).opencode_options().max_output_tokens == 65535


def test_a_profile_without_context_window_is_not_checked():
    assert profile(max_output_tokens=256000).opencode_options().max_output_tokens == 256000


def test_another_adapters_options_are_not_read():
    built = Profile(adapter="claude-code", options={"max_output_tokens": 1})
    assert built.opencode_options() is None
