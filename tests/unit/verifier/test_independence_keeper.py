from l4.config.schema import L4Config
from l4.verifier.selection import independence_constraint, independence_keeper

PROFILES = {
    "deepseek": {"adapter": "opencode", "model": "opencode-go/deepseek-v4.1-flash", "vendor": "deepseek"},
    "glm": {"adapter": "opencode", "model": "opencode-go/glm-5.3-flash", "vendor": "zhipu"},
    "claude-sonnet": {"adapter": "claude-code", "model": "sonnet", "vendor": "anthropic"},
    "claude-opus": {"adapter": "claude-code", "model": "opus", "vendor": "anthropic"},
    "claude-judge": {"adapter": "claude-code", "model": "haiku", "vendor": "anthropic"},
    "codex-judge": {"adapter": "codex", "model": "gpt-x", "vendor": "openai"},
    "kiro": {
        "adapter": "command",
        "vendor": "amazon",
        "options": {"argv": ["tool", "{prompt_file}"]},
    },  # no judge adapter
}


def cfg(judges, independence="different_vendor", implementer=None, **extra):
    return L4Config.model_validate(
        {
            "verifier": {"independence": independence},
            "profiles": PROFILES,
            "roles": {"implementer": implementer or ["deepseek", "glm", "claude-sonnet"], "judges": judges, **extra},
        }
    )


def verdict(c, implementers, name):
    return independence_keeper(c, implementers)(name, c.profiles[name])


def test_a_lone_claude_judge_refuses_claude_sonnet_after_deepseek_and_glm():
    c = cfg(["claude-judge"])
    reason = verdict(c, ["deepseek", "glm"], "claude-sonnet")
    assert reason == (
        "no profile of roles.judges would be independent of claude-sonnet (verifier.independence: different_vendor)"
    )


def test_a_lone_claude_judge_takes_glm_after_deepseek():
    assert verdict(cfg(["claude-judge"]), ["deepseek"], "glm") is None


def test_a_second_vendor_among_the_judges_takes_claude_sonnet():
    assert verdict(cfg(["claude-judge", "codex-judge"]), ["deepseek", "glm"], "claude-sonnet") is None


def test_a_second_claude_model_adds_no_vendor():
    c = cfg(["claude-judge"], implementer=["deepseek", "claude-sonnet", "claude-opus"])
    assert verdict(c, ["deepseek", "claude-sonnet"], "claude-opus") is not None
    # the judge was already lost to claude-sonnet: the keeper judges the candidate with the implementers given
    c2 = cfg(["claude-judge"], implementer=["deepseek", "glm"])
    assert verdict(c2, ["deepseek"], "glm") is None


def test_independence_none_takes_every_profile():
    c = cfg(["claude-judge"], independence="none")
    assert verdict(c, ["deepseek", "glm"], "claude-sonnet") is None


def test_judges_without_a_judge_adapter_refuse_nothing():
    c = cfg(["kiro"])
    assert verdict(c, ["deepseek"], "claude-sonnet") is None


def test_a_filled_verifier_agent_chain_is_checked_too():
    c = cfg(["claude-judge", "codex-judge"], verifier_agent=["claude-judge"])
    reason = verdict(c, ["deepseek", "glm"], "claude-sonnet")
    assert reason is not None and reason.startswith("no profile of roles.verifier_agent would be independent of")


def test_an_empty_verifier_agent_is_not_checked():
    c = cfg(["claude-judge", "codex-judge"])
    assert verdict(c, ["deepseek"], "claude-sonnet") is None


def test_the_keeper_agrees_with_the_independence_constraint():
    c = cfg(["claude-judge"])
    own = independence_constraint(c, ["deepseek", "glm", "claude-sonnet"])
    assert own("claude-judge", c.profiles["claude-judge"]) is not None
