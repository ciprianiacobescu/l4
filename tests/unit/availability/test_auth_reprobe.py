"""M1.12 line 5 (L4-AVL-005/007): a role that is needed re-probes a remembered auth refusal once before it parks.

The rule has to be tight both ways: an org that was just fixed must not wait the cache out while a run is parked on
it, and a real outage must not turn into a probe on every call."""

import logging

import pytest

from l4.agents.base import LimitSignal, ProbeResult
from l4.agents.factory import Factory, RoleUnavailable, WaitingCapacity

from ._selection_helpers import T0, Scripted, Sink, config, fake_profile, healthy, later, probe_ctx, world

A = fake_profile("m-a", vendor="openai", auth="subscription")
B = fake_profile("m-b", vendor="anthropic", auth="subscription")
CHAIN = ["a", "b"]


def refused(kind="auth", reason="claude reported an error (api_error_status 403)"):
    return {"hello": ProbeResult("hello", False, reason=reason, failure_class=kind)}


def build(tmp_path, plan, *, sink=None, **roles):
    clock, store = world(tmp_path)
    adapter = Scripted(plan)
    cfg = config({"a": A, "b": B}, **(roles or {"implementer": CHAIN}))
    factory = Factory(
        cfg, probe_ctx(tmp_path), events=sink, adapters={"fake": adapter}, availability=store, clock=clock
    )
    return factory, adapter, clock, store


def hellos(adapter, model):
    return adapter.probed(model).count("hello")


def test_every_profile_skipped_by_a_cached_auth_refusal_is_probed_once_more_before_the_park(tmp_path):
    plan = {"m-a": refused(), "m-b": refused()}
    factory, adapter, _, _ = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (1, 1)
    with pytest.raises(WaitingCapacity):  # inside the 2m window: the remembered refusal, then one fresh try each
        factory.for_role("implementer", "u")
    assert (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (2, 2)  # exactly one more each: no loop


def test_repeated_calls_cannot_turn_one_refusal_into_a_probe_storm(tmp_path):
    """Review fix: the cache entry a re-probe wrote is a fresh answer; the next call in its window must not ask again,
    or every select of a parked role costs one model request per profile."""
    plan = {"m-a": refused(), "m-b": refused()}
    factory, adapter, clock, _ = build(tmp_path, plan)
    for _ in range(6):
        with pytest.raises(WaitingCapacity):
            factory.for_role("implementer", "u")
    assert (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (2, 2)  # the first ask, one re-probe, then the entry
    later(clock, seconds=130)  # past auth_failure_ttl (2m): the entry is gone, the walk asks again, once more re-probes
    for _ in range(4):
        with pytest.raises(WaitingCapacity):
            factory.for_role("implementer", "u")
    assert (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (4, 4)


def test_a_reprobe_that_passes_is_selected_and_replaces_the_cache_entry(tmp_path):
    plan = {"m-a": refused(), **healthy("m-b")}
    plan["m-b"]["hello"] = ProbeResult("hello", False, reason="x", failure_class="auth")
    factory, adapter, clock, _ = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    plan["m-a"] = {}  # the organisation was fixed: the profile answers now
    later(clock, seconds=20)
    picked = factory.for_role("implementer", "u")
    assert picked.profile_name == "a" and picked.cached is False and picked.fallback_index == 0
    calls = len(adapter.calls)
    again = factory.for_role("implementer", "u")  # the success is what is remembered now
    assert again.profile_name == "a" and again.cached is True and len(adapter.calls) == calls


def test_a_remembered_failure_that_is_not_an_auth_refusal_is_not_probed_again(tmp_path):
    plan = {"m-a": refused("other", "unexpected reply"), "m-b": refused("other", "unexpected reply")}
    factory, adapter, _, _ = build(tmp_path, plan)
    for _ in range(3):
        with pytest.raises(WaitingCapacity):
            factory.for_role("implementer", "u")
    assert (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (1, 1)


def test_an_optional_role_never_reprobes(tmp_path):
    plan = {"m-a": refused(), "m-b": refused()}
    factory, adapter, _, _ = build(tmp_path, plan, clarifier=CHAIN)
    for _ in range(2):
        with pytest.raises(RoleUnavailable):
            factory.for_role("clarifier", "u")
    assert (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (1, 1)


def test_a_usable_profile_later_in_the_chain_means_no_extra_probe(tmp_path):
    plan = {"m-a": refused(), **healthy("m-b")}
    factory, adapter, _, _ = build(tmp_path, plan)
    assert factory.for_role("implementer", "u").profile_name == "b"
    assert factory.for_role("implementer", "u").profile_name == "b"
    assert hellos(adapter, "m-a") == 1  # the remembered refusal stood: something else was usable


def test_a_failed_reprobe_is_one_fresh_entry_not_a_doubled_one_and_is_remembered_again(tmp_path, caplog):
    sink = Sink()
    plan = {"m-a": refused(), "m-b": refused()}
    factory, _, clock, _ = build(tmp_path, plan, sink=sink)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    with caplog.at_level(logging.INFO, logger="l4"), pytest.raises(WaitingCapacity) as err:
        factory.for_role("implementer", "u")
    last = sink.of("availability.unavailable")[-1]
    assert [(s["profile"], s["step"]) for s in last["skipped"]] == [("a", "hello"), ("b", "hello")]
    assert all("cached" not in s for s in last["skipped"])  # these are fresh answers now
    assert str(err.value).count("profile a failed") == 1 and "retry after" in str(err.value)
    messages = [r.getMessage() for r in caplog.records]
    assert [m for m in messages if "skipped" in m][-2:] == [  # the last word on each profile is a fresh one
        "a skipped — hello: claude reported an error (api_error_status 403)",
        "b skipped — hello: claude reported an error (api_error_status 403)",
    ]
    assert [u.profile for u in err.value.unready] == ["a", "b"]  # a human fix ends it: due on the next run
    assert err.value.retry_after == clock.now()


def test_a_reprobe_that_hits_a_limit_records_the_cooldown(tmp_path):
    plan = {"m-a": refused(), "m-b": refused()}
    factory, _, _, store = build(tmp_path, plan)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    limit = LimitSignal("fake", "m-a", "rate_limit", None, "fake.429", "")
    plan["m-a"] = {"hello": ProbeResult("hello", False, reason="429", limit=limit, failure_class="limit")}
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert [c.profile for c in store.cooldowns.entries(T0)] == ["a"]


def test_no_cache_probe_still_ignores_a_remembered_refusal(tmp_path):
    """Line 6: `l4 probe --no-cache` never read the cache; pinned here for both classes."""
    plan = {"m-a": refused("auth"), "m-b": refused("other", "unexpected reply")}
    factory, adapter, _, _ = build(tmp_path, plan)
    first = factory.probe_all(["a", "b"], refresh=False)
    assert [p.cached for p in first] == [False, False]
    cached = factory.probe_all(["a", "b"], refresh=False)
    assert [p.cached for p in cached] == [True, True]
    forced = factory.probe_all(["a", "b"], refresh=True)
    assert [p.cached for p in forced] == [False, False] and (hellos(adapter, "m-a"), hellos(adapter, "m-b")) == (2, 2)
