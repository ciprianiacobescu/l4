"""SCN-OCV-03, SCN-OCV-25, SCN-OCV-27 (L4-OCV-001, L4-OCV-014): `options.cli_major` and `options.steps` are checked
at load, a v2 profile is refused in `roles.delegate`, and no message repeats a configured value."""

import pytest
from pydantic import ValidationError

from l4.config.loader import ConfigSchemaError, load_config_text
from l4.config.schema import Profile

MODEL = "opencode-go/deepseek-v4.1-flash"


def profile(model: str = MODEL, **options) -> Profile:
    return Profile(adapter="opencode", model=model, auth="api_key", options=options)


def refused(model: str = MODEL, **options) -> str:
    with pytest.raises(ValidationError) as caught:
        profile(model, **options)
    return str(caught.value)


def messages(model: str, **options) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        profile(model, **options)
    return [error["ctx"]["error"].args[0] if "ctx" in error else error["msg"] for error in caught.value.errors()]


def test_cli_major_defaults_to_one_and_accepts_two():
    assert profile(reasoning=None).opencode_options().cli_major == 1
    assert profile().opencode_options() is None
    assert profile(cli_major=1).opencode_options().cli_major == 1
    assert profile(cli_major=2).opencode_options().cli_major == 2


@pytest.mark.parametrize("value", [3, 0, "2", True, 2.0, None])
def test_any_other_cli_major_is_refused(value):
    assert "options.cli_major" in refused(cli_major=value)


def test_steps_are_accepted_on_a_v2_profile():
    steps = profile(cli_major=2, steps={"judge": 3, "implement": 200}).opencode_options().steps
    assert (steps.judge, steps.implement) == (3, 200)
    assert profile(cli_major=2, steps={"judge": 2}).opencode_options().steps.implement is None
    assert profile(cli_major=2, steps={"implement": 2000}).opencode_options().steps.judge is None


@pytest.mark.parametrize(
    "steps", [{"judge": 1}, {"judge": 21}, {"implement": 9}, {"implement": 2001}, {"judge": "3"}, {"other": 3}]
)
def test_steps_outside_the_ranges_are_refused(steps):
    assert "options.steps" in refused(cli_major=2, steps=steps)


def test_steps_without_cli_major_two_are_refused():
    expected = "options.steps applies to cli_major: 2 only (v1 runs without a step bound)"
    assert expected in refused(steps={"judge": 3})
    assert expected in refused(cli_major=1, steps={"judge": 3})


PROVIDER = {
    "id": "magnitude", "base_url": "http://192.0.2.10:10100/v1", "api_key_env": "MAGNITUDE_API_KEY",
    "models": {"secretmodel": {"context": 1000, "output": 100}},
}  # fmt: skip


def test_a_custom_provider_is_refused_on_v2():
    """SCN-OCV-25: no recorded v2 run with a provider key file, so the provider_refused message."""
    text = refused("magnitude/secretmodel", cli_major=2, provider=PROVIDER)
    assert (
        "options.provider is not supported with cli_major: 2 until the {file:} key form is recorded live "
        "(L4-OCV-013, provider_refused)"
    ) in text
    assert profile("magnitude/secretmodel", provider=PROVIDER).opencode_options().provider is not None


def test_the_renamed_providers_are_refused_on_v2():
    azure = refused("azure-cognitive-services/hiddenmodel", cli_major=2)
    assert "OpenCode v2 renamed provider azure-cognitive-services to azure: use azure/<model>" in azure
    vertex = refused("google-vertex-anthropic/hiddenmodel", cli_major=2)
    assert "OpenCode v2 renamed provider google-vertex-anthropic to google-vertex: use google-vertex/<model>" in vertex


def test_the_renamed_providers_stay_valid_on_v1():
    assert profile("azure-cognitive-services/m", cli_major=1).opencode_options() is not None
    assert profile("google-vertex-anthropic/m", cli_major=1).opencode_options() is not None


def test_a_tools_list_naming_list_is_refused_on_v2_and_allowed_on_v1():
    message = "options.tools: list has no OpenCode v2 permission action (glob and read cover it)"
    assert message in refused(cli_major=2, tools=["read", "list"])
    assert profile(cli_major=1, tools=["read", "list"]).opencode_options().tools == ["read", "list"]
    assert profile(cli_major=2, tools=["read", "edit"]).opencode_options().tools == ["read", "edit"]


def test_no_message_holds_the_model_id_second_part():
    for model in ("azure-cognitive-services/zzzsecret", "google-vertex-anthropic/zzzsecret"):
        found = messages(model, cli_major=2)
        assert found and all("zzzsecret" not in message for message in found)
    found = messages(
        "magnitude/zzzsecret",
        cli_major=2,
        provider={**PROVIDER, "models": {"zzzsecret": {"context": 1000, "output": 100}}},
    )
    assert found and all("zzzsecret" not in message for message in found)


# --- SCN-OCV-27 (L4-OCV-014): the delegate is not served by a v2 profile ---

DELEGATE = (
    "profiles.oc2 is in roles.delegate, but it runs OpenCode v2 (options.cli_major: 2), which does not serve the "
    "delegate in this release (its read-only mode, L4-DLG-016, is not recorded on v2): remove oc2 from "
    "roles.delegate or use a cli_major: 1 profile"
)


def config(major: int, roles: str) -> str:
    return (
        f"profiles:\n  oc2: {{adapter: opencode, model: {MODEL}, auth: api_key, options: {{cli_major: {major}}}}}\n"
        f"roles: {{{roles}}}\n"
    )


def test_a_v2_profile_in_roles_delegate_is_refused_by_name():
    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(config(2, "judges: [oc2], delegate: [oc2]"))
    assert DELEGATE in str(caught.value)
    assert MODEL not in str(caught.value).replace(DELEGATE, "")


def test_the_same_v2_profile_loads_in_the_other_roles():
    cfg = load_config_text(config(2, "judges: [oc2], implementer: [oc2]"))
    assert cfg.roles.judges == ["oc2"] and cfg.roles.delegate == []


def test_a_v1_opencode_profile_loads_in_roles_delegate():
    assert load_config_text(config(1, "delegate: [oc2]")).roles.delegate == ["oc2"]
    assert load_config_text(config(1, "judges: [oc2], delegate: [oc2]")).roles.delegate == ["oc2"]
