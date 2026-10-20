"""CFG-011 (kiro-judge L4-KJD-009, SCN-KJD-26): kiro-cli judge profiles, `auto` passing with its vendors."""

from datetime import UTC, datetime

from l4.availability.cooldown import AvailabilityStore
from l4.availability.probes import LadderReport, ProbeResult
from l4.availability.vendor import RoutedSet
from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.doctor import checks_config as cc
from l4.doctor.registry import CONFIG_SCOPES, REGISTRY

BASE = {"adapter": "kiro-cli", "min_version": "2.32.0"}
TRAIL = "tool-less harness agent, prompt on stdin, no trust flag"


def cfg(profiles: dict, **roles) -> L4Config:
    return L4Config.model_validate({"profiles": profiles, "roles": roles})


def test_the_check_is_registered_with_the_config_scopes_and_severity_warn():
    check = next(c for c in REGISTRY.checks() if c.id == "CFG-011")
    assert check.severity == "warn" and check.scopes == CONFIG_SCOPES


def test_scn_26_an_auto_judge_passes_naming_its_vendors_and_the_ignored_vendor(make_ctx):
    profiles = {"kj": {"adapter": "kiro-cli", "vendor": "zhipu", "min_version": "2.32.0"}}
    ctx, _ = make_ctx(cfg=cfg(profiles, judges=["kj"]))
    result = cc._cfg_011(ctx)
    assert result.status == "pass"
    assert f"kj: {TRAIL}, model auto, routed to anthropic, minimax, zhipu (built-in)" in result.message
    assert "a pinned model makes the served model checkable" in result.message
    assert "kj: vendor zhipu is ignored: auto is routed (set model to pin a vendor)" in result.message


def test_scn_26_warnings_for_options_agent_and_a_low_min_version(make_ctx):
    profiles = {
        "kj": {"adapter": "kiro-cli", "vendor": "zhipu", "min_version": "2.32.0"},
        "kj2": {"adapter": "kiro-cli", "model": "glm-5", "options": {"agent": "mine"}, "min_version": "2.32.0"},
        "kc": {"adapter": "kiro-cli", "model": "glm-5", "min_version": "2.28.0"},
    }
    ctx, _ = make_ctx(cfg=cfg(profiles, judges=["kj", "kj2"], clarifier=["kc"]))
    result = cc._cfg_011(ctx)
    assert result.status == "fail"
    assert "kj2: a judge always runs the harness's tool-less agent; options.agent is ignored here" in result.message
    assert "kc: the judge invocation was measured on kiro-cli 2.32.0" in result.message
    assert "kj: " in result.message and "kj: a judge always" not in result.message


def test_scn_26_fixed_profiles_pass_naming_the_pinned_model_and_vendor(make_ctx):
    profiles = {
        "kj": {**BASE},
        "kj2": {**BASE, "model": "glm-5"},
        "kc": {**BASE, "model": "claude-sonnet-5.5"},
    }
    ctx, _ = make_ctx(cfg=cfg(profiles, judges=["kj", "kj2"], clarifier=["kc"]))
    result = cc._cfg_011(ctx)
    assert result.status == "pass"
    assert f"kj2: {TRAIL}, model glm-5 (zhipu)" in result.message
    assert f"kc: {TRAIL}, model claude-sonnet-5.5 (anthropic)" in result.message


def test_an_unset_min_version_warns(make_ctx):
    ctx, _ = make_ctx(cfg=cfg({"kj": {"adapter": "kiro-cli", "model": "glm-5"}}, judges=["kj"]))
    result = cc._cfg_011(ctx)
    assert result.status == "fail" and "kj: the judge invocation was measured on kiro-cli 2.32.0" in result.message


def test_a_recorded_listing_gives_the_listed_source_with_its_date(make_ctx):
    ctx, _ = make_ctx(cfg=cfg({"kj": {**BASE}}, judges=["kj"]))
    listed = RoutedSet(("anthropic", "deepseek", "minimax", "zhipu"), ("glm-5",), "listed")
    report = LadderReport({"auth": ProbeResult("auth", True, {"logged_in": True, "routed": listed.to_detail()})})
    AvailabilityStore(cache_root(ctx.env, repo=ctx.repo)).probes.put(
        "kj", "identity", report.to_json(), datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    )
    result = cc._cfg_011(ctx)
    assert result.status == "pass"
    assert "routed to anthropic, deepseek, minimax, zhipu (listed 2026-10-19)" in result.message


def test_a_recorded_built_in_set_stays_built_in(make_ctx):
    ctx, _ = make_ctx(cfg=cfg({"kj": {**BASE}}, judges=["kj"]))
    fallback = RoutedSet(("anthropic", "minimax", "zhipu"), ("glm-5",), "built-in", "listing failed")
    report = LadderReport({"auth": ProbeResult("auth", True, {"routed": fallback.to_detail()})})
    AvailabilityStore(cache_root(ctx.env, repo=ctx.repo)).probes.put(
        "kj", "identity", report.to_json(), datetime(2026, 10, 19, tzinfo=UTC)
    )
    assert "(built-in)" in cc._cfg_011(ctx).message


def test_a_vendor_on_an_auto_implementer_is_noted_and_does_not_fail(make_ctx):
    profiles = {"impl": {"adapter": "kiro-cli", "model": "auto", "vendor": "acme"}}
    ctx, _ = make_ctx(cfg=cfg(profiles, implementer=["impl"]))
    result = cc._cfg_011(ctx)
    assert result.status == "pass"
    assert "no kiro-cli judge profile" in result.message
    assert "impl: vendor acme is ignored: auto is routed (set model to pin a vendor)" in result.message


def test_no_kiro_cli_profile_passes(make_ctx):
    profiles = {"oc": {"adapter": "opencode", "model": "opencode-go/glm-5.3-flash"}}
    ctx, _ = make_ctx(cfg=cfg(profiles, judges=["oc"]))
    result = cc._cfg_011(ctx)
    assert result.status == "pass" and result.message == "no kiro-cli judge profile"
