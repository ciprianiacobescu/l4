import pytest

from l4.agents.base import ProbeResult
from l4.config.schema import L4Config
from l4.doctor import checks_provision


class Scripted:
    def __init__(self, binary: bool, auth: bool) -> None:
        self.binary, self.auth = binary, auth

    def probe(self, profile, step, ctx):
        ok = self.binary if step == "binary" else self.auth
        return ProbeResult(step, ok, {"logged_in": ok}, reason=None if ok else "no")


@pytest.mark.parametrize(
    ("binary", "auth", "status", "text"),
    [
        (True, True, "pass", "ready"),
        (True, False, "fail", "installed-not-authenticated"),
        (False, False, "fail", "missing"),
    ],
)
def test_prv_001_reports_each_profile_in_one_of_three_states(make_ctx, monkeypatch, binary, auth, status, text):
    from l4.agents import factory

    monkeypatch.setitem(factory.ADAPTERS, "codex", lambda: Scripted(binary, auth))
    cfg = L4Config.model_validate({"profiles": {"cx": {"adapter": "codex"}}, "roles": {"implementer": ["cx"]}})
    ctx, _ = make_ctx(cfg=cfg)
    result = checks_provision._prv_001(ctx)
    assert result.status == status and f"cx codex {text}" in result.message
    if text == "installed-not-authenticated":
        assert "codex login --device-auth" in (result.fix_hint or "")


def test_prv_001_row_names_the_unset_credential_variable(make_ctx, monkeypatch):
    from l4.agents import factory

    monkeypatch.setitem(factory.ADAPTERS, "codex", lambda: Scripted(True, False))
    cfg = L4Config.model_validate(
        {"profiles": {"cx": {"adapter": "codex", "auth": "api_key"}}, "roles": {"implementer": ["cx"]}}
    )
    ctx, _ = make_ctx(cfg=cfg)
    result = checks_provision._prv_001(ctx)
    assert result.status == "fail" and "cx: CODEX_API_KEY is not set" in result.message
    assert "CODEX_API_KEY" in (result.fix_hint or "")


def test_prv_001_skips_without_agent_cli_profiles_and_prv_002_prints_the_root_command(make_ctx, monkeypatch):
    ctx, _ = make_ctx()
    assert checks_provision._prv_001(ctx).status == "skip"
    monkeypatch.setattr(checks_provision, "detect_platform", lambda: "linux-x64")
    monkeypatch.setattr(checks_provision, "_os_release", lambda: "ID=ubuntu\n")
    result = checks_provision._prv_002(ctx)
    assert result.status == "fail" and "sudo apt-get install -y bubblewrap" in result.message


MODEL = "qwen3.6-35b-a3b:gguf:q5"
PROVIDER_PROFILE = {
    "adapter": "opencode", "model": f"magnitude/{MODEL}", "auth": "api_key", "vendor": "alibaba",
    "options": {"provider": {
        "id": "magnitude", "base_url": "http://192.0.2.10:10100/inference/v1", "api_key_env": "MAGNITUDE_API_KEY",
        "models": {MODEL: {"context": 262144, "output": 16384}},
    }},
}  # fmt: skip


def _provider_ctx(make_ctx, monkeypatch, handler, *, auth=True):
    import httpx

    import l4.agents.opencode_provider as provider
    from l4.agents import factory

    monkeypatch.setitem(factory.ADAPTERS, "opencode", lambda: Scripted(True, auth))
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    cfg = L4Config.model_validate({"profiles": {"mag": PROVIDER_PROFILE}, "roles": {"implementer": ["mag"]}})
    ctx, _ = make_ctx(cfg=cfg)
    return ctx


def test_prv_001_shows_the_provider_host_reachability_without_the_key(make_ctx, monkeypatch):
    import httpx

    ctx = _provider_ctx(make_ctx, monkeypatch, lambda request: httpx.Response(401))
    result = checks_provision._prv_001(ctx)
    assert result.status == "pass" and "mag opencode ready" in result.message
    assert "mag provider 192.0.2.10:10100 reachable" in result.message
    assert "MAGNITUDE_API_KEY" not in result.message and "/inference" not in result.message


def test_prv_001_an_unreachable_provider_is_a_note_not_a_failure(make_ctx, monkeypatch):
    import httpx

    def down(request):
        raise httpx.ConnectError("refused")

    ctx = _provider_ctx(make_ctx, monkeypatch, down)
    result = checks_provision._prv_001(ctx)
    assert result.status == "pass" and "mag provider 192.0.2.10:10100 unreachable" in result.message


def test_prv_001_a_missing_provider_key_names_the_variable_in_the_steps(make_ctx, monkeypatch):
    import httpx

    ctx = _provider_ctx(make_ctx, monkeypatch, lambda request: httpx.Response(401), auth=False)
    result = checks_provision._prv_001(ctx)
    assert result.status == "fail" and "installed-not-authenticated" in result.message
    assert "MAGNITUDE_API_KEY" in (result.fix_hint or "") and "OPENROUTER" not in (result.fix_hint or "")


def test_prv_001_speaks_github_for_a_github_origin_with_platform_auto(make_ctx, monkeypatch):
    """L4-GHP-009: with `ci.platform: auto` the origin decides; github.com gets the environment-secret words."""
    from l4.agents import factory

    monkeypatch.setitem(factory.ADAPTERS, "claude-code", lambda: Scripted(True, False))
    monkeypatch.setattr(checks_provision, "origin_url", lambda repo, env: "https://github.com/o/r.git")
    cfg = L4Config.model_validate(
        {"profiles": {"cc": {"adapter": "claude-code", "auth": "subscription"}}, "roles": {"implementer": ["cc"]}}
    )
    ctx, _ = make_ctx(cfg=cfg)
    result = checks_provision._prv_001(ctx)
    assert "a secret of the GitHub environment `l4`" in (result.fix_hint or "")
    assert "masked CI variable" not in (result.fix_hint or "")
