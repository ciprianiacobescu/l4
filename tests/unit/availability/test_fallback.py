import logging
from datetime import UTC, datetime, timedelta

import pytest

from l4.agents.base import LimitSignal, ProbeResult, RunResult
from l4.agents.factory import Factory, RoleUnavailable, WaitingCapacity
from l4.availability.fallback import Skipped, cooldown_until, format_skipped_line
from l4.config.schema import AvailabilityCfg, L4Config, Profile, RolesCfg
from l4.exitcodes import ExitCode

from ._selection_helpers import (
    RESET,
    T0,
    Scripted,
    Sink,
    config,
    exhausted,
    fake_profile,
    healthy,
    later,
    probe_ctx,
    world,
)

CODEX = fake_profile("gpt-6", vendor="openai", auth="subscription")
CLAUDE = fake_profile("sonnet", vendor="anthropic", auth="subscription")
PROFILES = {"codex-sol": CODEX, "claude-sonnet": CLAUDE}
CHAIN = ["codex-sol", "claude-sonnet"]


def build(tmp_path, plan, *, profiles=None, sink=None, **roles):
    clock, store = world(tmp_path)
    adapter = Scripted(plan)
    cfg = config(profiles or PROFILES, **(roles or {"implementer": CHAIN}))
    factory = Factory(
        cfg, probe_ctx(tmp_path), events=sink, adapters={"fake": adapter}, availability=store, clock=clock
    )
    return factory, adapter, clock, store


def test_exact_console_lines_and_event_shape(tmp_path, caplog):
    sink = Sink()
    factory, adapter, _, _ = build(tmp_path, {**exhausted("gpt-6"), **healthy("sonnet")}, sink=sink)
    with caplog.at_level(logging.INFO, logger="l4"):
        picked = factory.for_role("implementer", "openspec:add-login")
    assert [(r.name, r.getMessage()) for r in caplog.records] == [
        (
            "l4.implementer",
            "codex-sol skipped — quota: 5h window 100% used, 0% remaining (resets 2026-10-03T14:32Z); "
            "cool-down recorded",
        ),
        (
            "l4.implementer",
            "claude-sonnet ok (binary 2.1.288 · auth subscription · quota 49% used (session) · hello 2.1s) "
            "→ selected, fallback #1",
        ),
    ]
    [event] = sink.of("availability.selected")
    assert event == {
        "role": "implementer", "selected": "claude-sonnet", "fallback_index": 1, "fallback_from": "codex-sol",
        "skipped": [{
            "profile": "codex-sol", "step": "quota", "reason": "usage window exhausted", "used_percent": 100,
            "window_minutes": 300, "resets_at": "2026-10-03T14:32:00Z",
        }],
        "probes": {
            "codex-sol": {"binary": "0.160.0", "auth": "subscription"},
            "claude-sonnet": {
                "binary": "2.1.288", "auth": "subscription", "quota_used_percent": 49, "quota_window": "session",
                "hello_ms": 2104,
            },
        },
        "cached": False, "quota_window": "session",
    }  # fmt: skip
    assert picked.profile_name == "claude-sonnet" and picked.fallback_index == 1 and picked.fallback_from == "codex-sol"
    assert picked.skipped == event["skipped"] and "hello" not in adapter.probed("gpt-6")
    [cooldown] = sink.of("availability.cooldown")
    assert cooldown["profile"] == "codex-sol" and cooldown["until"] == "2026-10-03T14:32:00Z"
    assert cooldown["kind"] == "usage_limit" and cooldown["tool"] == "fake" and cooldown["model"] == "gpt-6"


def test_a_kiro_throttle_cools_the_profile_for_two_minutes_not_the_default_half_hour():
    from l4.agents.kiro_cli import throttle_signal

    signal = throttle_signal("Internal error (code -32603): The request was throttled by the service", T0)
    assert cooldown_until(signal, AvailabilityCfg(), T0) == T0 + timedelta(minutes=2)
    hinted = throttle_signal("Too many requests, retry in 9m30s", T0)
    assert cooldown_until(hinted, AvailabilityCfg(), T0) == T0 + timedelta(minutes=9, seconds=30)
    assert cooldown_until(LimitSignal("x", None, "rate_limit", None, "t", ""), AvailabilityCfg(), T0) == T0 + timedelta(
        minutes=30
    )  # a 429 with no hint still takes `default_cooldown`


def test_the_selected_event_keeps_the_kiro_usage_credits_with_their_source(tmp_path):
    plan = healthy("sonnet")
    plan["sonnet"]["quota"] = ProbeResult(
        "quota", True,
        {"quota_used_percent": 11, "quota_window": "credits", "credits_used": 5.42, "credits_included": 50.0,
         "credits_source": "kiro.usage"},
    )  # fmt: skip
    sink = Sink()
    factory, _, _, _ = build(tmp_path, plan, sink=sink, implementer=["claude-sonnet"])
    factory.for_role("implementer", "u")
    [event] = sink.of("availability.selected")
    probe = event["probes"]["claude-sonnet"]
    assert (probe["credits_used"], probe["credits_included"], probe["credits_source"]) == (5.42, 50.0, "kiro.usage")


def test_the_spec_cooling_line_and_the_skipped_step_form():
    cooling = Skipped("judge-sol", "cooling", "cooling", "credits", resets_at=datetime(2026, 10, 4, 13, 0, tzinfo=UTC))
    assert format_skipped_line("judges", cooling) == (
        "[l4] judges: judge-sol skipped — cooling until 2026-10-04T13:00Z (credits); no probe sent"
    )
    auth = Skipped("p", "auth", "codex is not logged in")
    assert format_skipped_line("implementer", auth) == "[l4] implementer: p skipped — auth: codex is not logged in"
    veto = Skipped("p", "constraint", "independence: vendor used by implementer")
    assert format_skipped_line("judges", veto) == "[l4] judges: p skipped — independence: vendor used by implementer"


def test_a_skipped_quota_step_and_a_cached_probe_render_in_the_selected_line(tmp_path, caplog):
    plan = healthy("sonnet")
    plan["sonnet"]["quota"] = ProbeResult("quota", True, skipped=True)
    factory, _, _, _ = build(tmp_path, plan, implementer=["claude-sonnet"])
    with caplog.at_level(logging.INFO, logger="l4"):
        factory.for_role("implementer", "u")
        factory.for_role("implementer", "u")
    first, second = (r.getMessage() for r in caplog.records)
    assert first == "claude-sonnet ok (binary 2.1.288 · auth subscription · quota skipped · hello 2.1s) → selected"
    assert (
        second
        == "claude-sonnet ok (binary 2.1.288 · auth subscription · quota skipped · hello 2.1s · cached) → selected"
    )


def test_cooling_profile_skipped_without_probe_and_cached_success_not_reprobed(tmp_path):
    sink = Sink()
    factory, adapter, clock, store = build(tmp_path, healthy("sonnet"), sink=sink)
    store.cooldowns.record("codex-sol", ("fake", "gpt-6"), T0 + timedelta(hours=2), "usage_limit", "test")
    first = factory.for_role("implementer", "u")
    assert first.profile_name == "claude-sonnet" and first.cached is False
    assert adapter.probed("gpt-6") == []  # a cooling profile costs no request
    calls = len(adapter.calls)
    second = factory.for_role("implementer", "u")
    assert second.cached is True and len(adapter.calls) == calls  # the fresh successful probe is used as it is
    later(clock, minutes=16)  # past cache_ttl (15m)
    third = factory.for_role("implementer", "u")
    assert third.cached is False and len(adapter.calls) == calls + 4


def test_an_expired_cooldown_is_reprobed(tmp_path):
    plan = {**exhausted("gpt-6"), **healthy("sonnet")}
    factory, adapter, clock, _ = build(tmp_path, plan)
    assert factory.for_role("implementer", "u").profile_name == "claude-sonnet"
    assert adapter.probed("gpt-6") == ["binary", "auth", "quota"]
    plan["gpt-6"] = healthy("gpt-6")["gpt-6"]  # the window reset
    later(clock, hours=3)  # past 14:32
    again = factory.for_role("implementer", "u")
    assert again.profile_name == "codex-sol" and again.fallback_index == 0 and again.fallback_from is None
    assert adapter.probed("gpt-6")[-4:] == ["binary", "auth", "quota", "hello"]


def test_only_a_success_or_a_failed_hello_is_cached(tmp_path):
    plan = {
        **exhausted("gpt-6"),
        "sonnet": {"hello": ProbeResult("hello", False, reason="unexpected reply")},
    }
    factory, adapter, clock, _ = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    seen = len(adapter.calls)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    # codex is cooling (a limit is the registry's to remember, not the cache's); sonnet's failed hello is cached,
    # so a model request is not spent again within the TTL
    assert len(adapter.calls) == seen
    later(clock, minutes=16)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert len(adapter.calls) == seen + 4  # the cached failure expired: sonnet runs the ladder again


def test_a_failure_of_a_free_step_is_probed_again_at_once(tmp_path):
    plan = {"sonnet": {"auth": ProbeResult("auth", False, reason="claude is not logged in")}}
    factory, adapter, _, _ = build(tmp_path, plan, implementer=["claude-sonnet"])
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    plan["sonnet"] = {}  # the operator logged in
    assert factory.for_role("implementer", "u").profile_name == "claude-sonnet"
    assert adapter.probed("sonnet")[:2] == ["binary", "auth"]


def test_a_missing_binary_or_login_writes_no_cooldown(tmp_path):
    plan = {"gpt-6": {"binary": ProbeResult("binary", False, reason="codex not found on PATH")}, **healthy("sonnet")}
    sink = Sink()
    factory, _, _, store = build(tmp_path, plan, sink=sink)
    assert factory.for_role("implementer", "u").profile_name == "claude-sonnet"
    assert store.cooldowns.entries(T0) == [] and sink.of("availability.cooldown") == []


def test_required_chain_exhausted_returns_waiting_capacity_with_earliest_reset(tmp_path):
    sink = Sink()
    plan = {**exhausted("gpt-6", resets=RESET), **exhausted("sonnet", resets=RESET + timedelta(hours=2))}
    factory, _, _, _ = build(tmp_path, plan, sink=sink)
    with pytest.raises(WaitingCapacity) as err:
        factory.for_role("implementer", "u")
    assert isinstance(err.value, RoleUnavailable) and err.value.code == ExitCode.WAITING_CAPACITY
    assert err.value.retry_after == RESET
    assert "codex-sol failed the quota probe" in str(err.value) and "retry after 2026-10-03T14:32Z" in str(err.value)
    assert sink.of("availability.selected") == []
    with pytest.raises(WaitingCapacity) as again:  # now both are cooling: no probe, same answer
        factory.for_role("implementer", "u")
    assert again.value.retry_after == RESET and "cooling until 2026-10-03T14:32Z" in str(again.value)


def test_auth_failure_parks_due_now_not_after_the_default_cooldown(tmp_path):
    """R4 (live job 5561): a missing login is probed again at once, so the unit is due on the next run."""
    plan = {
        "gpt-6": {"auth": ProbeResult("auth", False, reason="x")},
        "sonnet": {"binary": ProbeResult("binary", False, reason="claude not found on PATH")},
    }
    factory, _, _, _ = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity) as err:
        factory.for_role("implementer", "u")
    assert err.value.retry_after == T0
    assert [(u.profile, u.adapter, u.auth, u.step, u.reason) for u in err.value.unready] == [
        ("codex-sol", "fake", "subscription", "auth", "x"),
        ("claude-sonnet", "fake", "subscription", "binary", "claude not found on PATH"),
    ]


def test_limit_failure_keeps_the_cooldown_reset(tmp_path):
    plan = {**exhausted("gpt-6", resets=RESET), **exhausted("sonnet", resets=RESET + timedelta(hours=2))}
    factory, _, _, _ = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity) as err:
        factory.for_role("implementer", "u")
    assert err.value.retry_after == RESET and err.value.unready == ()


def test_mixed_auth_and_cooling_takes_the_cooling_reset(tmp_path):
    plan = {"gpt-6": {"auth": ProbeResult("auth", False, reason="x")}, **exhausted("sonnet")}
    factory, _, _, _ = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity) as err:
        factory.for_role("implementer", "u")
    assert err.value.retry_after == RESET
    assert [u.profile for u in err.value.unready] == ["codex-sol"]


def test_a_constraint_veto_is_unready_and_due_now(tmp_path):
    factory, _, _, _ = build(tmp_path, {}, judges=CHAIN)
    with pytest.raises(WaitingCapacity) as err:
        factory.for_role("judges", "u", constraints=[lambda n, p: "no"])
    assert err.value.retry_after == T0
    assert {(u.step, u.reason) for u in err.value.unready} == {("constraint", "no")}


def test_nothing_usable_emits_availability_unavailable(tmp_path):
    """R5 (live job 5561): the failed judge choice left nothing in the ledger."""
    sink = Sink()
    plan = {
        "gpt-6": {"auth": ProbeResult("auth", False, reason="codex is not logged in")},
        **exhausted("sonnet"),
    }
    factory, _, _, _ = build(tmp_path, plan, sink=sink, judges=CHAIN)
    with pytest.raises(WaitingCapacity):
        factory.for_role("judges", "u")
    [event] = sink.of("availability.unavailable")
    assert event["role"] == "judges" and event["required"] is True
    assert event["retry_after"] == "2026-10-03T14:32:00Z"
    assert [(s["profile"], s["step"]) for s in event["skipped"]] == [("codex-sol", "auth"), ("claude-sonnet", "quota")]
    assert sink.of("availability.selected") == []


def test_an_optional_role_with_nothing_usable_is_recorded_too(tmp_path):
    sink = Sink()
    plan = {"gpt-6": {"auth": ProbeResult("auth", False, reason="x")}}
    factory, _, _, _ = build(tmp_path, plan, sink=sink, profiles={"codex-sol": CODEX}, clarifier=["codex-sol"])
    with pytest.raises(RoleUnavailable):
        factory.for_role("clarifier", "u")
    [event] = sink.of("availability.unavailable")
    assert event["role"] == "clarifier" and event["required"] is False and event["retry_after"] is None


@pytest.mark.parametrize("role", ["clarifier", "s1_judge", "spec_writer"])
def test_optional_roles_never_wait(tmp_path, role):
    plan = {
        "gpt-6": {"auth": ProbeResult("auth", False, reason="x")},
        "sonnet": {"auth": ProbeResult("auth", False, reason="y")},
    }
    factory, _, _, _ = build(tmp_path, plan, **{role: CHAIN})
    with pytest.raises(RoleUnavailable) as err:
        factory.for_role(role, "u")
    assert not isinstance(err.value, WaitingCapacity) and err.value.code == ExitCode.WAITING_CAPACITY


@pytest.mark.parametrize("role", ["implementer", "verifier_agent", "judges"])
def test_required_roles_wait(tmp_path, role):
    plan = {
        "gpt-6": {"auth": ProbeResult("auth", False, reason="x")},
        "sonnet": {"auth": ProbeResult("auth", False, reason="y")},
    }
    factory, _, _, _ = build(tmp_path, plan, **{role: CHAIN})
    with pytest.raises(WaitingCapacity):
        factory.for_role(role, "u")


def test_a_profile_that_cannot_serve_is_skipped_and_the_walk_goes_on(tmp_path):
    profiles = {"api": Profile(backend="openai-chat", model="x"), "claude-sonnet": CLAUDE}
    factory, adapter, _, _ = build(tmp_path, healthy("sonnet"), profiles=profiles, judges=["api", "claude-sonnet"])
    picked = factory.for_role("judges", "u", serves={"fake"})
    assert picked.profile_name == "claude-sonnet" and picked.fallback_index == 1
    assert picked.skipped[0]["step"] == "serves" and "backend profile" in picked.skipped[0]["reason"]
    assert adapter.probed("x") == []


def test_constraints_veto_profiles_and_are_never_relaxed(tmp_path):
    seen = []

    def not_openai(name, profile):
        seen.append(name)
        return "independence: vendor used by implementer" if profile.vendor == "openai" else None

    factory, adapter, _, _ = build(tmp_path, healthy("sonnet"), judges=CHAIN)
    picked = factory.for_role("judges", "u", constraints=[not_openai])
    assert picked.profile_name == "claude-sonnet" and seen == ["codex-sol", "claude-sonnet"]
    assert picked.skipped[0] == {
        "profile": "codex-sol", "step": "constraint", "reason": "independence: vendor used by implementer",
    }  # fmt: skip
    assert adapter.probed("gpt-6") == []
    with pytest.raises(WaitingCapacity, match="profile codex-sol: no; profile claude-sonnet: no"):
        factory.for_role("judges", "u", constraints=[lambda n, p: "no"])


def test_model_family_limit_selects_same_tool_other_model(tmp_path):
    profiles = {"opus": fake_profile("opus"), "sonnet": fake_profile("sonnet")}
    plan = {**exhausted("opus"), **healthy("sonnet")}
    factory, adapter, _, _ = build(tmp_path, plan, profiles=profiles, implementer=["opus", "sonnet"])
    assert factory.for_role("implementer", "u").profile_name == "sonnet"
    assert adapter.probed("sonnet")  # the sibling model on the same tool was probed and used, not cooled
    assert factory.for_role("implementer", "u").cached is True


def test_an_unrecognised_quota_answer_is_logged_and_does_not_fail_the_profile(tmp_path):
    plan = healthy("sonnet")
    plan["sonnet"]["quota"] = ProbeResult(
        "quota", True, {"quota_unrecognised": True, "quota_note": "no usage window in the answer"}, skipped=True
    )
    sink = Sink()
    factory, _, _, _ = build(tmp_path, plan, sink=sink, implementer=["claude-sonnet"])
    assert factory.for_role("implementer", "u").profile_name == "claude-sonnet"
    assert sink.of("availability.quota_unrecognised") == [
        {"profile": "claude-sonnet", "step": "quota", "note": "no usage window in the answer"}
    ]
    factory.for_role("implementer", "u")  # cached: the note is not repeated
    assert len(sink.of("availability.quota_unrecognised")) == 1


def test_a_chain_naming_no_profile_or_an_undefined_one(tmp_path):
    factory, _, _, _ = build(tmp_path, {}, implementer=[])
    with pytest.raises(RoleUnavailable, match="no profile") as err:
        factory.for_role("implementer", "u")
    assert not isinstance(err.value, WaitingCapacity)


def test_cooldown_until_picks_the_reset_else_the_configured_default():
    cfg = AvailabilityCfg()
    soon = LimitSignal("t", None, "usage_limit", T0 + timedelta(hours=1), "s", "")
    assert cooldown_until(soon, cfg, T0) == T0 + timedelta(hours=1)
    assert cooldown_until(LimitSignal("t", None, "rate_limit", None, "s", ""), cfg, T0) == T0 + timedelta(minutes=30)
    assert cooldown_until(LimitSignal("t", None, "credits", None, "s", ""), cfg, T0) == T0 + timedelta(hours=24)
    past = LimitSignal("t", None, "usage_limit", T0 - timedelta(hours=1), "s", "")
    assert cooldown_until(past, cfg, T0) == T0 + timedelta(minutes=30)  # a reset in the past is no reset


def test_mid_run_limit_records_cooldown_and_selects_next(tmp_path):
    sink = Sink()
    plan = {**healthy("gpt-6", version="0.160.0"), **healthy("sonnet")}
    factory, adapter, clock, store = build(tmp_path, plan, sink=sink)
    first = factory.for_role("implementer", "openspec:u")
    assert first.profile_name == "codex-sol"
    run = RunResult(
        "rate_limited",
        tmp_path / "raw",
        limit=LimitSignal("fake", None, "usage_limit", T0 + timedelta(hours=1), "codex.turn_failed", "limit"),
    )
    second = factory.on_limit(first, run)
    assert second.profile_name == "claude-sonnet" and second.fallback_index == 1 and second.fallback_from == "codex-sol"
    assert store.cooldowns.cooling(("fake", "gpt-6"), clock.now()).until == T0 + timedelta(hours=1)
    [cooldown] = sink.of("availability.cooldown")
    assert cooldown["profile"] == "codex-sol" and cooldown["until"] == "2026-10-03T13:00:00Z"
    [fallback] = sink.of("availability.fallback")
    assert fallback == {
        "role": "implementer", "from": "codex-sol", "to": "claude-sonnet", "reason": "usage_limit",
        "resets_at": "2026-10-03T13:00:00Z",
    }  # fmt: skip
    assert store.probes.get("codex-sol", "x", 900, clock.now()) is None  # its cached probe is dropped
    calls = len(adapter.calls)
    again = factory.for_role("implementer", "openspec:u")
    assert again.profile_name == "claude-sonnet" and len(adapter.calls) == calls  # codex stays cooling, no probe


def test_mid_run_limit_without_a_signal_uses_the_default_cooldown_and_nothing_left_waits(tmp_path):
    sink = Sink()
    factory, _, clock, store = build(tmp_path, healthy("sonnet"), sink=sink, implementer=["claude-sonnet"])
    only = factory.for_role("implementer", "u")
    with pytest.raises(WaitingCapacity) as err:
        factory.on_limit(only, RunResult("rate_limited", tmp_path / "raw"))
    assert err.value.retry_after == T0 + timedelta(minutes=30)
    assert store.cooldowns.cooling(("fake", "sonnet"), clock.now()) is not None
    assert len(sink.of("availability.cooldown")) == 1 and sink.of("availability.fallback") == []


def test_on_limit_needs_a_selection_made_by_for_role(tmp_path):
    from l4.agents.factory import Selected

    factory, _, _, _ = build(tmp_path, {})
    with pytest.raises(ValueError):
        factory.on_limit(Selected("x", CODEX, Scripted()), RunResult("rate_limited", tmp_path / "raw"))


def test_the_ledger_run_id_is_recorded_on_the_cooldown(tmp_path):
    sink = Sink()
    factory, _, _, store = build(tmp_path, {**exhausted("gpt-6"), **healthy("sonnet")}, sink=sink)
    factory.for_role("implementer", "u")
    assert store.cooldowns.cooling(("fake", "gpt-6"), T0).recorded_by_run == "r-20261003T1200Z-abcd"


def test_a_lost_login_mid_run_is_logged_as_auth_not_as_a_rate_limit(tmp_path):
    sink = Sink()
    plan = {**healthy("gpt-6", version="0.160.0"), **healthy("sonnet")}
    factory, _, _, _ = build(tmp_path, plan, sink=sink)
    first = factory.for_role("implementer", "openspec:u")
    factory.on_limit(first, RunResult("auth", tmp_path / "raw", detail="could not authenticate"))
    [cooldown] = sink.of("availability.cooldown")
    assert (cooldown["kind"], cooldown["source"]) == ("auth", "run.auth")
    [fallback] = sink.of("availability.fallback")
    assert fallback["reason"] == "auth"


def test_a_missing_credential_variable_prints_the_auth_prefix_once():
    line = format_skipped_line("judges", Skipped("codex-main", "auth", "CODEX_API_KEY is not set"))
    assert line == "[l4] judges: codex-main skipped — auth: CODEX_API_KEY is not set"


# --- installed against pinned (L4-PRV-046, SCN-PRV-128) ---


def test_the_probe_identity_moves_with_the_override():
    from l4.availability.fallback import probe_identity

    profile, cfg, environ = CODEX, AvailabilityCfg(), {"HOME": "/h"}
    plain = probe_identity(profile, cfg, environ)
    assert probe_identity(profile, cfg, environ, pin=None) == plain
    held = probe_identity(profile, cfg, environ, pin="2.28.0")
    assert held != plain and held != probe_identity(profile, cfg, environ, pin="2.32.0")
    assert held == probe_identity(profile, cfg, environ, pin="2.28.0")


def test_a_changed_override_is_never_answered_from_the_cache(tmp_path):
    clock, store = world(tmp_path)
    claude = Profile(adapter="claude-code", model="sonnet", vendor="anthropic", auth="subscription")
    adapter = Scripted(healthy("sonnet"))

    def pick(held):
        cfg = L4Config(profiles={"claude": claude}, roles=RolesCfg(implementer=["claude"]), ci={"cli_versions": held})
        Factory(cfg, probe_ctx(tmp_path), adapters={"claude-code": adapter}, availability=store, clock=clock).for_role(
            "implementer", "u"
        )

    pick({})
    pick({})
    assert adapter.probed("sonnet").count("binary") == 1  # the same pin: answered from the cache
    pick({"claude-code": "2.1.200"})
    assert adapter.probed("sonnet").count("binary") == 2


def test_the_binary_text_names_a_drift_only():
    from l4.availability.fallback import _step_text

    drift = ProbeResult("binary", True, {"version": "2.33.0", "pin": "2.32.0"})
    assert _step_text(CODEX, "binary", drift) == "binary 2.33.0 (pinned 2.32.0)"
    same = ProbeResult("binary", True, {"version": "2.32.0", "pin": "2.32.0"})
    assert _step_text(CODEX, "binary", same) == "binary 2.32.0"
    assert _step_text(CODEX, "binary", ProbeResult("binary", True, {"version": "2.32.0"})) == "binary 2.32.0"


def test_selected_has_binary_pinned_only_on_a_drift(tmp_path):  # SCN-PRV-128
    base = tmp_path

    def event_for(version):
        tmp_path = base / version
        plan = healthy("sonnet", version=version)
        plan["sonnet"]["binary"] = ProbeResult("binary", True, {"version": version, "pin": "2.32.0"})
        sink = Sink()
        factory, _, _, _ = build(tmp_path, plan, sink=sink, implementer=["claude-sonnet"])
        factory.for_role("implementer", "u")
        [event] = sink.of("availability.selected")
        return event["probes"]["claude-sonnet"]

    drifted = event_for("2.33.0")
    assert drifted["binary"] == "2.33.0" and drifted["binary_pinned"] == "2.32.0"
    assert "binary_pinned" not in event_for("2.32.0")
