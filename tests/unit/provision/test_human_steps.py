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
