from l4.provision.readiness import HUMAN_STEPS, AdapterReadiness, AdapterState, steps_for


def test_steps_printed_only_for_unauthenticated_profiles():
    assert "claude setup-token" in steps_for("claude-code", "subscription")[0]
    assert "CLAUDE_CODE_OAUTH_TOKEN" in steps_for("claude-code", "subscription")[1]
    assert "ANTHROPIC_API_KEY" in steps_for("claude-code", "api_key")[0]
    assert "OPENROUTER_API_KEY" in steps_for("opencode", "api_key")[0]
    assert (
        "codex login --device-auth" in steps_for("codex", "subscription")[0]
        and "runner user" in steps_for("codex", None)[0]
    )
    assert "CODEX_API_KEY" in steps_for("codex", "api_key")[0]
    assert "kiro-cli login" in steps_for("kiro-cli", "subscription")[0]
    assert "KIRO_API_KEY" in steps_for("kiro-cli", "api_key")[0]
    assert steps_for("fake", None) == () and steps_for("codex", "weird") == ()
    ready = AdapterReadiness("p", "codex", AdapterState.READY)
    assert ready.steps == ()
    assert all(isinstance(text, str) and text for steps in HUMAN_STEPS.values() for text in steps)


def _unauthenticated(adapter: str, auth: str | None, environ: dict[str, str], *, cfg=None, origin=None):
    from pathlib import Path

    from l4.agents.base import ProbeCtx, ProbeResult
    from l4.agents.factory import Factory
    from l4.config.schema import L4Config, Profile
    from l4.provision.readiness import adapter_readiness

    class Scripted:
        def probe(self, profile, step, ctx):
            return ProbeResult(step, step == "binary", reason=None if step == "binary" else "not logged in")

    ctx = ProbeCtx(environ, Path("."), lambda *a: None)
    profile = Profile(adapter=adapter, auth=auth) if auth else Profile(adapter=adapter)
    factory = Factory(cfg or L4Config(), ctx, adapters={adapter: Scripted()})
    return adapter_readiness("p", profile, factory, ctx, origin=origin)


def test_prv001_names_the_missing_variable():
    row = _unauthenticated("codex", "api_key", {})
    assert row.state is AdapterState.INSTALLED_NOT_AUTHENTICATED
    assert row.detail == "p: CODEX_API_KEY is not set"
    assert "CODEX_API_KEY" in row.steps[0]  # the human steps text is kept
    assert _unauthenticated("claude-code", "subscription", {"CLAUDE_CODE_OAUTH_TOKEN": " "}).detail == (
        "p: CLAUDE_CODE_OAUTH_TOKEN is not set"
    )
    assert _unauthenticated("kiro-cli", "subscription", {}).detail == "p: KIRO_API_KEY is not set"
    # no variable for this profile (codex file login), or the variable is set: nothing to name
    assert _unauthenticated("codex", "subscription", {"CODEX_API_KEY": "x"}).detail is None
    assert _unauthenticated("kiro-cli", "subscription", {"KIRO_API_KEY": "x"}).detail is None


def test_github_steps_name_the_environment_secret():
    """L4-GHP-009 / SCN-GHP-12 area: on GitHub a key is a secret of the GitHub environment, not a masked CI variable."""
    from l4.config.schema import L4Config

    steps = steps_for("claude-code", "api_key", platform="github", environment="l4")
    assert steps == ("store your key as a secret of the GitHub environment `l4`: ANTHROPIC_API_KEY",)
    subscription = steps_for("claude-code", "subscription", platform="github", environment="prod-ci")
    assert "claude setup-token" in subscription[0]
    assert "secret of the GitHub environment `prod-ci`: CLAUDE_CODE_OAUTH_TOKEN" in subscription[1]
    assert all("masked CI variable" not in text for t in HUMAN_STEPS for text in steps_for(*t, platform="github"))
    # no environment configured (ci.github_environment: null): a repository secret
    assert "repository secret" in steps_for("codex", "api_key", platform="github", environment=None)[0]
    # the runner-VM logins do not mention a CI variable at all and stay as they are
    assert steps_for("codex", "subscription", platform="github") == steps_for("codex", "subscription")
    # GitLab keeps its texts
    assert steps_for("claude-code", "api_key", platform="gitlab") == steps_for("claude-code", "api_key")
    assert "masked CI variable ANTHROPIC_API_KEY" in steps_for("claude-code", "api_key")[0]

    # the readiness row takes the platform from the config of the factory (ci.platform), else the forge type
    cfg = L4Config.model_validate({"ci": {"platform": "github", "github_environment": "l4"}})
    row = _unauthenticated("claude-code", "api_key", {}, cfg=cfg)
    assert row.steps == steps
    assert _unauthenticated("claude-code", "api_key", {}).steps == steps_for("claude-code", "api_key")
    on_gitlab = L4Config.model_validate({"ci": {"platform": "gitlab"}})
    assert _unauthenticated("claude-code", "api_key", {}, cfg=on_gitlab).steps == steps_for("claude-code", "api_key")
    from_origin = _unauthenticated("claude-code", "api_key", {}, origin="git@github.com:acme/widgets.git")
    assert from_origin.steps == steps


def test_github_provider_key_is_not_called_a_masked_ci_variable():
    from types import SimpleNamespace

    from l4.provision.readiness import provider_steps

    profile = SimpleNamespace(
        opencode_options=lambda: SimpleNamespace(provider=SimpleNamespace(api_key_env="PROV_KEY"))
    )
    assert "a masked CI variable on a runner" in provider_steps(profile)[0]
    on_github = provider_steps(profile, platform="github", environment="l4")[0]
    assert "secret of the GitHub environment `l4`" in on_github and "PROV_KEY" in on_github
    assert "masked" not in on_github


def test_opencodes_own_key_is_named_when_unset():
    """L4-PRV-028: the readiness row and its steps for an opencode-go profile with auth api_key."""
    from pathlib import Path

    from l4.agents.base import ProbeCtx, ProbeResult
    from l4.agents.factory import Factory
    from l4.config.schema import L4Config, Profile
    from l4.provision.readiness import adapter_readiness

    class Scripted:
        def probe(self, profile, step, ctx):
            return ProbeResult(step, step == "binary", reason=None if step == "binary" else "no key")

    profile = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", auth="api_key")
    cfg = L4Config.model_validate({"ci": {"platform": "github"}})

    def row(environ):
        ctx = ProbeCtx(environ, Path("."), lambda *a: None)
        return adapter_readiness("p", profile, Factory(cfg, ctx, adapters={"opencode": Scripted()}), ctx, cfg=cfg)

    unset = row({})
    assert unset.detail == "p: OPENCODE_API_KEY is not set"
    assert unset.steps == (
        "run `l4 setup github --secret OPENCODE_API_KEY=<ENV>` (the value comes from your environment)",
    )
    assert row({"OPENCODE_API_KEY": "x"}).detail is None


COPILOT_STEPS = (
    "create a fine-grained personal access token owned by your personal account (not an organization) with the "
    "Copilot Requests permission (classic ghp_ tokens are refused)",
    "store it as the masked CI variable COPILOT_GITHUB_TOKEN",
)


def test_copilot_readiness_names_the_token_and_where_it_goes():  # SCN-PRV-138
    for auth in ("subscription", "api_key"):
        assert steps_for("copilot-cli", auth) == COPILOT_STEPS
        row = _unauthenticated("copilot-cli", auth, {})
        assert row.state is AdapterState.INSTALLED_NOT_AUTHENTICATED
        assert row.steps == COPILOT_STEPS
        assert row.detail == "p: COPILOT_GITHUB_TOKEN is not set"
        github = steps_for("copilot-cli", auth, platform="github", environment="ci")
        assert github[0] == COPILOT_STEPS[0]
        assert github[1] == "store it as a secret of the GitHub environment `ci`: COPILOT_GITHUB_TOKEN"
    assert _unauthenticated("copilot-cli", "api_key", {"COPILOT_GITHUB_TOKEN": "fake"}).detail is None
    assert _unauthenticated("copilot-cli", None, {"GH_TOKEN": "fake"}).detail == "p: COPILOT_GITHUB_TOKEN is not set"
