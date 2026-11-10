"""`no_stored_login` (L4-OCV-017, design D4): a `cli_major: 2` opencode profile whose credential variable is
`OPENCODE_API_KEY` or whose model is an `opencode/` model needs no login stored in OpenCode's data home."""

import pytest

from l4.agents.credentials import no_stored_login
from l4.config.schema import Profile


def profile(model: str, major: int | None = 2, **extra) -> Profile:
    options = {"cli_major": major} if major is not None else {}
    return Profile(adapter="opencode", model=model, vendor="unknown", options=options, **extra)


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(profile("opencode-go/x", auth="api_key"), id="go-api-key"),
        pytest.param(profile("opencode/x", auth="api_key"), id="free-api-key"),
        pytest.param(profile("opencode/x"), id="free-no-auth"),
        pytest.param(profile("opencode/x", auth="subscription"), id="free-subscription"),
    ],
)
def test_a_v2_profile_with_the_api_key_or_a_free_model_needs_no_stored_login(candidate):
    assert no_stored_login(candidate) is True


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(profile("opencode-go/x"), id="go-no-auth"),
        pytest.param(profile("opencode-go/x", auth="subscription"), id="go-subscription"),
        pytest.param(profile("openrouter/x"), id="openrouter"),
        pytest.param(profile("openrouter/x", auth="api_key"), id="openrouter-api-key"),
        pytest.param(profile("opencode-go/x", major=1, auth="api_key"), id="v1-go-api-key"),
        pytest.param(profile("opencode/x", major=1, auth="api_key"), id="v1-free-api-key"),
        pytest.param(profile("opencode/x", major=1), id="v1-free"),
        pytest.param(profile("opencode-go/x", major=None, auth="api_key"), id="no-options-go-api-key"),
        pytest.param(profile("opencode/x", major=None), id="no-options-free"),
        pytest.param(Profile(adapter="codex", model="gpt-5", vendor="openai", auth="api_key"), id="codex"),
        pytest.param(Profile(adapter="claude-code", model="sonnet", vendor="anthropic"), id="claude-code"),
        pytest.param(Profile(adapter="fake"), id="fake"),
    ],
)
def test_every_other_profile_keeps_its_stored_login(candidate):
    assert no_stored_login(candidate) is False
