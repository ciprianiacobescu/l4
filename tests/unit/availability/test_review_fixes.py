"""Regressions found in the M1.2 stage A-B-C review."""

import logging
from datetime import timedelta

import httpx
import pytest

from l4.agents.base import LimitSignal, ProbeCtx, ProbeResult, RunResult
from l4.agents.factory import Factory, WaitingCapacity
from l4.availability.cooldown import Cooldown
from l4.availability.fallback import FallbackSelector
from l4.availability.quota import openrouter_quota
from l4.config.schema import AvailabilityCfg, L4Config, Profile, RolesCfg

from ._selection_helpers import T0, Scripted, fake_profile, healthy, later, probe_ctx, world
from .test_fallback import CHAIN, build

# --- the probe cache is valid only for the settings it was judged under --------------------------------------------


def factory_with(tmp_path, adapter, clock, store, profiles, availability=None):
    cfg = L4Config(
        profiles=profiles, roles=RolesCfg(implementer=list(profiles)), availability=availability or AvailabilityCfg()
    )
    return Factory(cfg, probe_ctx(tmp_path), adapters={"fake": adapter}, availability=store, clock=clock)


@pytest.mark.parametrize(
    "changed",
    [
        {"profile": {"min_remaining_percent": 100}},
        {"profile": {"min_version": "99.0.0"}},
        {"profile": {"model": "sonnet-b"}},
        {"availability": {"min_remaining_percent": 60}},
        {"availability": {"hello_prompt": "Say hi"}},
    ],
)
def test_a_changed_probe_setting_is_not_answered_from_the_cache(tmp_path, changed):
    clock, store = world(tmp_path)
    adapter = Scripted({**healthy("sonnet"), **healthy("sonnet-b")})
    base = {"claude": fake_profile("sonnet", vendor="anthropic")}
    assert factory_with(tmp_path, adapter, clock, store, base).for_role("implementer", "u").cached is False
    again = factory_with(tmp_path, adapter, clock, store, base).for_role("implementer", "u")
    assert again.cached is True  # control: the same settings reuse the result
    profiles = {"claude": base["claude"].model_copy(update=changed.get("profile", {}))}
    cfg_av = AvailabilityCfg(**changed.get("availability", {}))
    later(clock, minutes=5)
    assert factory_with(tmp_path, adapter, clock, store, profiles, cfg_av).for_role("implementer", "u").cached is False


def test_a_cache_entry_is_still_used_when_only_timing_settings_change(tmp_path):
    clock, store = world(tmp_path)
    adapter = Scripted(healthy("sonnet"))
    profiles = {"claude": fake_profile("sonnet", vendor="anthropic")}
    factory_with(tmp_path, adapter, clock, store, profiles).for_role("implementer", "u")
    longer = AvailabilityCfg(cache_ttl="30m", default_cooldown="1h")
    assert factory_with(tmp_path, adapter, clock, store, profiles, longer).for_role("implementer", "u").cached is True


# --- a limit that names a served id the profile does not pin cools the profile ------------------------------------


def served_limit(model: str = "claude-sonnet-4-5-20250929") -> LimitSignal:
    return LimitSignal("fake", model, "rate_limit", None, "claude.http_429", "")


@pytest.mark.parametrize("pinned", ["sonnet", None])
def test_a_served_id_limit_cools_the_profile_and_is_never_handed_back(tmp_path, pinned):
    profile = Profile(adapter="fake", model=pinned, vendor="anthropic")
    plan = healthy("sonnet") | healthy("m2") | healthy("")
    factory, adapter, clock, store = build(
        tmp_path, plan, profiles={"claude": profile, "other": fake_profile("m2")}, implementer=["claude", "other"]
    )
    first = factory.for_role("implementer", "u")
    assert first.profile_name == "claude"
    second = factory.on_limit(first, RunResult("rate_limited", tmp_path / "raw", limit=served_limit()))
    assert second.profile_name == "other"
    key = ("fake", pinned if pinned else "profile:claude")
    assert store.cooldowns.cooling(key, clock.now()) is not None
    assert store.cooldowns.entries(clock.now())[0].model == key[1]
    with pytest.raises(WaitingCapacity):  # and with nothing left in the chain it parks instead of looping
        factory.on_limit(second, RunResult("rate_limited", tmp_path / "raw"))


def test_a_limit_naming_the_pinned_model_cools_that_model(tmp_path):
    factory, _, clock, store = build(
        tmp_path, healthy("sonnet"), profiles={"c": fake_profile("sonnet")}, implementer=["c"]
    )
    first = factory.for_role("implementer", "u")
    with pytest.raises(WaitingCapacity):
        factory.on_limit(first, served_limit("sonnet"))
    assert store.cooldowns.entries(clock.now())[0].model == "sonnet"


def test_on_limit_refuses_to_return_the_profile_that_hit_the_limit(tmp_path, monkeypatch):
    factory, _, clock, _ = build(tmp_path, healthy("sonnet"), profiles={"c": fake_profile("sonnet")}, implementer=["c"])
    first = factory.for_role("implementer", "u")
    soon = Cooldown("c", "fake", "sonnet", clock.now() + timedelta(hours=1), "rate_limit", "x")
    monkeypatch.setattr(FallbackSelector, "record_cooldown", lambda self, *a: soon)  # a cool-down that never matches
    with pytest.raises(WaitingCapacity, match="still selectable") as err:
        factory.on_limit(first, RunResult("rate_limited", tmp_path / "raw"))
    assert err.value.retry_after == soon.until


def test_on_limit_accepts_a_bare_limit_signal(tmp_path):
    factory, _, clock, store = build(tmp_path, {**healthy("gpt-6", version="0.160.0"), **healthy("sonnet")})
    first = factory.for_role("implementer", "u")
    signal = LimitSignal("fake", None, "usage_limit", T0 + timedelta(hours=2), "w", "")
    assert factory.on_limit(first, signal).profile_name == "claude-sonnet"
    assert store.cooldowns.cooling(("fake", "gpt-6"), clock.now()).until == T0 + timedelta(hours=2)


# --- console lines say which steps were skipped -------------------------------------------------------------------


def test_skipped_auth_and_hello_steps_are_shown_as_skipped(tmp_path, caplog):
    plan = healthy("sonnet")
    plan["sonnet"]["auth"] = ProbeResult("auth", True, skipped=True)
    plan["sonnet"]["quota"] = ProbeResult("quota", True, skipped=True)
    plan["sonnet"]["hello"] = ProbeResult("hello", True, skipped=True)
    factory, _, _, _ = build(tmp_path, plan, implementer=["claude-sonnet"])
    with caplog.at_level(logging.INFO, logger="l4"):
        factory.for_role("implementer", "u")
    assert caplog.records[0].getMessage() == (
        "claude-sonnet ok (binary 2.1.288 · auth skipped · quota skipped · hello skipped) → selected"
    )


# --- the retry time counts only profiles that could have been used ------------------------------------------------


def test_a_profile_excluded_by_a_constraint_does_not_set_the_retry_time(tmp_path):
    factory, _, clock, store = build(tmp_path, {}, judges=CHAIN)
    soon, late = T0 + timedelta(hours=1), T0 + timedelta(hours=5)
    store.cooldowns.record("codex-sol", ("fake", "gpt-6"), soon, "usage_limit", "t", None, clock.now())
    store.cooldowns.record("claude-sonnet", ("fake", "sonnet"), late, "usage_limit", "t", None, clock.now())

    def only_anthropic(name, profile):
        return "independence: same vendor" if profile.vendor == "openai" else None

    with pytest.raises(WaitingCapacity) as err:
        factory.for_role("judges", "u", constraints=[only_anthropic])
    assert err.value.retry_after == late


# --- for_role reports the vendor and where it comes from -----------------------------------------------------------


def test_for_role_fills_vendor_and_provenance(tmp_path):
    profiles = {
        "codex": Profile(adapter="fake", model="gpt-6", vendor="openai"),
        "anon": Profile(adapter="fake", model="m"),
    }
    factory, _, _, _ = build(tmp_path, healthy("gpt-6") | healthy("m"), profiles=profiles, implementer=["codex"])
    picked = factory.for_role("implementer", "u")
    assert (picked.vendor, picked.provenance) == ("openai", "declared")
    factory, _, _, _ = build(tmp_path / "b", healthy("m"), profiles=profiles, implementer=["anon"])
    assert factory.for_role("implementer", "u").provenance == "unknown"


# --- the OpenRouter key goes to OpenRouter only --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base_url", "host"),
    [
        ("http://attacker.example/api/v1", "openrouter.ai"),
        ("https://attacker.example/api/v1", "openrouter.ai"),
        ("http://openrouter.ai/api/v1", "openrouter.ai"),
        ("https://openrouter.ai.evil.example/api/v1", "openrouter.ai"),
    ],
)
def test_the_openrouter_key_is_sent_to_https_openrouter_only(tmp_path, base_url, host):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"total_credits": 10, "total_usage": 1, "limit_remaining": None}})

    profile = Profile(adapter="opencode", model="openrouter/openai/gpt-5.4-mini", base_url=base_url, vendor="openai")
    ctx = ProbeCtx(environ={"OPENROUTER_API_KEY": "sk-or-SECRET"}, cwd=tmp_path, run=lambda *a: None)
    openrouter_quota(profile, ctx, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen and {r.url.host for r in seen} == {host}
    assert all(r.url.scheme == "https" for r in seen)
