"""agent-factory 8.3 (reduced): a busy subscription login is skipped when a later profile is usable, else waited for."""

import pytest

from l4.agents.base import RunRequest
from l4.agents.factory import Factory, WaitingCapacity
from l4.agents.fake import Step
from l4.agents.gate import ConcurrencyGate, GatedAdapter
from l4.availability.cooldown import identity_hash

from ._selection_helpers import Scripted, config, fake_profile, healthy, probe_ctx, world

# two logins: the gate is per (tool, identity), and the identity of a profile includes its base_url
A = fake_profile("alpha", auth="subscription").model_copy(update={"base_url": "https://a.example"})
B = fake_profile("beta", auth="subscription").model_copy(update={"base_url": "https://b.example"})
A_TWIN = fake_profile("alpha-2", auth="subscription").model_copy(update={"base_url": "https://a.example"})
KEYED = fake_profile("keyed", auth="api_key")


def setup(tmp_path, plan, profiles, chain, *, gate=None):
    clock, store = world(tmp_path)
    ctx = probe_ctx(tmp_path)
    adapter = Scripted(plan)
    cfg = config(profiles, implementer=chain)
    factory = Factory(cfg, ctx, adapters={"fake": adapter}, availability=store, clock=clock, gate=gate)
    real_gate = gate or ConcurrencyGate.for_user(ctx.environ)  # the lock dir is the user's, not the cache's
    return factory, adapter, real_gate, ctx


def hold(gate, ctx, profile):
    slot = gate.try_acquire("fake", identity_hash(profile, ctx.environ), 1)
    assert slot is not None
    return slot


def test_second_run_waits_or_falls_back(tmp_path, caplog):
    plan = {**healthy("alpha"), **healthy("beta")}
    factory, adapter, gate, ctx = setup(tmp_path, plan, {"a": A, "b": B}, ["a", "b"])
    slot = hold(gate, ctx, A)
    picked = factory.for_role("implementer", "u")
    assert picked.profile_name == "b" and picked.fallback_index == 1
    assert picked.skipped == [{"profile": "a", "step": "concurrency", "reason": "concurrency: max_concurrency 1 busy"}]
    assert adapter.probed("alpha") == []  # a busy login is not probed
    slot.release()
    assert factory.for_role("implementer", "u").profile_name == "a"  # free again


def test_a_busy_profile_that_is_the_last_candidate_is_waited_for(tmp_path):
    clock = {"t": 0.0}
    holder: list = []

    def sleep(seconds):
        clock["t"] += seconds
        if clock["t"] >= 4:
            holder[0].release()

    cache = tmp_path / "cache"
    gate = ConcurrencyGate(cache, sleep=sleep, monotonic=lambda: clock["t"])
    factory, adapter, _, ctx = setup(tmp_path, healthy("alpha"), {"a": A}, ["a"], gate=gate)
    holder.append(hold(gate, ctx, A))
    picked = factory.for_role("implementer", "u")
    assert picked.profile_name == "a" and picked.skipped == [] and clock["t"] == 4.0
    assert adapter.probed("alpha") == ["binary", "auth", "quota", "hello"]


def test_a_profile_busy_for_the_whole_wait_makes_the_role_wait(tmp_path):
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    gate = ConcurrencyGate(tmp_path / "cache", sleep=sleep, monotonic=lambda: clock["t"])
    factory, adapter, _, ctx = setup(tmp_path, healthy("alpha"), {"a": A}, ["a"], gate=gate)
    hold(gate, ctx, A)
    with pytest.raises(WaitingCapacity, match="profile a is busy"):
        factory.for_role("implementer", "u")
    assert clock["t"] >= 120 and adapter.calls == []


def test_a_subscription_adapter_holds_a_slot_around_each_run(tmp_path):
    factory, adapter, gate, ctx = setup(tmp_path, healthy("alpha"), {"a": A}, ["a"])
    inside: list[bool] = []

    class Spy(Scripted):
        def run(self, req):
            inside.append(gate.is_busy("fake", identity_hash(A, ctx.environ), 1))
            return super().run(req)

    factory._adapters["fake"] = Spy(healthy("alpha"), [Step()])
    picked = factory.for_role("implementer", "u")
    assert isinstance(picked.impl, GatedAdapter) and picked.impl.name == "fake"
    request = RunRequest(
        profile=A, role="implementer", cwd=tmp_path, prompt="p", result_path=tmp_path / "r",
        raw_events_path=tmp_path / "e", env={},
    )  # fmt: skip
    assert picked.impl.run(request).status == "ok"
    assert inside == [True] and not gate.is_busy("fake", identity_hash(A, ctx.environ), 1)


def test_an_api_key_profile_is_not_gated_unless_it_asks_for_a_cap(tmp_path):
    plain, _, _, _ = setup(tmp_path / "plain", healthy("keyed"), {"k": KEYED}, ["k"])
    assert not isinstance(plain.for_role("implementer", "u").impl, GatedAdapter)
    capped = KEYED.model_copy(update={"max_concurrency": 2})
    cap, _, _, _ = setup(tmp_path / "capped", healthy("keyed"), {"k": capped}, ["k"])
    assert isinstance(cap.for_role("implementer", "u").impl, GatedAdapter)


def test_two_profiles_on_one_login_share_its_slot(tmp_path):
    plan = {**healthy("alpha"), **healthy("alpha-2")}
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    gate = ConcurrencyGate(tmp_path / "cache", sleep=sleep, monotonic=lambda: clock["t"])
    factory, adapter, _, ctx = setup(tmp_path, plan, {"a": A, "twin": A_TWIN}, ["a", "twin"], gate=gate)
    hold(gate, ctx, A)  # the one login is in use: neither profile can run
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert adapter.calls == []
