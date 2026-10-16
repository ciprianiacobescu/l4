"""CFG-009 (escalate-and-note L4-IMP-018, SCN-IMP-185): an escalation that cannot act, or that changes nothing."""

from l4.config.schema import L4Config
from l4.doctor import checks_config as cc
from l4.doctor.registry import REGISTRY

MODEL = "opencode-go/deepseek-v4.1-flash"


def cfg(implementer: list[str], profiles: dict, **implementer_cfg) -> L4Config:
    return L4Config.model_validate(
        {"profiles": profiles, "roles": {"implementer": implementer}, "implementer": implementer_cfg}
    )


DS_GLM = {
    "deepseek": {"adapter": "opencode", "model": "opencode-go/deepseek-v4.1-flash"},
    "glm": {"adapter": "opencode", "model": "opencode-go/glm-5.3-flash"},
}


def test_escalate_after_not_below_max_task_attempts_fails_naming_the_second_profile(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["deepseek", "glm"], DS_GLM, max_task_attempts=2))
    result = cc._cfg_009(ctx)
    assert result.status == "fail"
    assert (
        "implementer.escalate_after (2) is not below implementer.max_task_attempts (2): no task moves to glm"
        in result.message
    )
    assert result.fix_hint == (
        "set implementer.escalate_after below max_task_attempts, or 0 when you do not want escalation"
    )


def test_two_profiles_with_one_adapter_and_model_fail(make_ctx):
    profiles = {"oc-a": {"adapter": "opencode", "model": MODEL}, "oc-b": {"adapter": "opencode", "model": MODEL}}
    ctx, _ = make_ctx(cfg=cfg(["oc-a", "oc-b"], profiles))
    result = cc._cfg_009(ctx)
    assert result.status == "fail"
    assert f"profiles oc-a and oc-b run the same model ({MODEL}): a move from oc-a to oc-b changes nothing" in (
        result.message
    )


def test_a_chain_of_one_profile_passes(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["deepseek"], DS_GLM, max_task_attempts=2))
    result = cc._cfg_009(ctx)
    assert result.status == "pass"
    assert result.message == "one implementer profile: a task that fails stays on it"


def test_escalate_after_zero_passes(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["deepseek", "glm"], DS_GLM, max_task_attempts=2, escalate_after=0))
    assert cc._cfg_009(ctx).status == "pass"


def test_a_working_chain_passes(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["deepseek", "glm"], DS_GLM))
    assert cc._cfg_009(ctx).status == "pass"


def test_profiles_without_a_model_are_not_the_same_model(make_ctx):
    profiles = {"a": {"adapter": "claude"}, "b": {"adapter": "claude"}}
    ctx, _ = make_ctx(cfg=cfg(["a", "b"], profiles))
    assert cc._cfg_009(ctx).status == "pass"


def test_it_is_a_warning_on_a_laptop_and_in_ci():
    check = {c.id: c for c in REGISTRY.checks()}["CFG-009"]
    assert check.severity == "warn"
