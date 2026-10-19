"""M1.12 lines 2 and 3 (L4-AVL-005): a failed hello is remembered by its class."""

import pytest
from pydantic import ValidationError

from l4.agents.base import ProbeResult
from l4.agents.factory import Factory, WaitingCapacity
from l4.availability.fallback import probe_identity
from l4.config.schema import AvailabilityCfg

from ._selection_helpers import Scripted, config, fake_profile, later, probe_ctx, world

PROFILE = fake_profile("sonnet", vendor="anthropic", auth="subscription")


def hello_fail(kind, reason="claude reported an error (api_error_status 403)"):
    return {"sonnet": {"hello": ProbeResult("hello", False, reason=reason, failure_class=kind)}}


def build(tmp_path, plan, **availability):
    clock, store = world(tmp_path)
    adapter = Scripted(plan)
    cfg = config({"claude-sonnet": PROFILE}, implementer=["claude-sonnet"])
    cfg = cfg.model_copy(update={"availability": AvailabilityCfg(**availability)})
    factory = Factory(cfg, probe_ctx(tmp_path), adapters={"fake": adapter}, availability=store, clock=clock)
    return factory, adapter, clock, store, cfg


def read_back(tmp_path, store, cfg, now):
    identity = probe_identity(PROFILE, cfg.availability, probe_ctx(tmp_path).environ)
    return store.probes.get("claude-sonnet", identity, 15 * 60.0, now)


def test_an_other_failure_is_cached_for_cache_ttl_an_auth_failure_for_auth_failure_ttl(tmp_path):
    for kind, expect_after_3m in (("other", True), ("auth", False)):
        root = tmp_path / kind
        root.mkdir()
        factory, adapter, clock, store, cfg = build(root, hello_fail(kind))
        with pytest.raises(WaitingCapacity):
            factory.for_role("implementer", "u")
        assert read_back(root, store, cfg, clock.now()) is not None  # both are remembered at first
        later(clock, minutes=3)
        assert (read_back(root, store, cfg, clock.now()) is not None) is expect_after_3m
        later(clock, minutes=13)  # 16m: past cache_ttl
        assert read_back(root, store, cfg, clock.now()) is None


def test_a_transient_failure_is_not_cached_at_all(tmp_path):
    factory, adapter, clock, store, cfg = build(tmp_path, hello_fail("transient", "timeout"))
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert read_back(tmp_path, store, cfg, clock.now()) is None
    seen = len(adapter.calls)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert len(adapter.calls) == seen + 4  # the whole ladder ran again: nothing was cached


def test_a_failure_without_a_class_keeps_the_old_rule(tmp_path):
    factory, adapter, clock, store, cfg = build(tmp_path, hello_fail(None, "unexpected reply"))
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    later(clock, minutes=3)
    assert read_back(tmp_path, store, cfg, clock.now()) is not None


def test_a_longer_auth_failure_ttl_is_honoured_and_changing_it_keeps_the_cache(tmp_path):
    factory, _, clock, store, cfg = build(tmp_path, hello_fail("auth"), auth_failure_ttl="10m")
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    later(clock, minutes=5)
    assert read_back(tmp_path, store, cfg, clock.now()) is not None
    # the TTL is timing, not identity: a changed value must not make every cached probe unreachable
    other = AvailabilityCfg(auth_failure_ttl="1m")
    environ = probe_ctx(tmp_path).environ
    assert probe_identity(PROFILE, cfg.availability, environ) == probe_identity(PROFILE, other, environ)


def test_auth_failure_ttl_is_a_duration_defaulting_to_two_minutes():
    assert AvailabilityCfg().auth_failure_ttl == "2m"
    assert AvailabilityCfg(auth_failure_ttl="30s").auth_failure_ttl == "30s"
    for bad in ("-1m", "soon", "1d", ""):
        with pytest.raises(ValidationError):
            AvailabilityCfg(auth_failure_ttl=bad)


def test_an_unsupported_version_failure_is_not_cached_at_all(tmp_path):
    """SCN-OCG-06: installing the right major takes effect at the next probe."""
    reason = "unsupported_version: opencode rejected --pure"
    factory, adapter, clock, store, cfg = build(tmp_path, hello_fail("unsupported_version", reason))
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert read_back(tmp_path, store, cfg, clock.now()) is None
    seen = len(adapter.calls)
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert len(adapter.calls) == seen + 4
