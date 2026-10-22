import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.availability.cooldown import (
    AvailabilityStore,
    CooldownRegistry,
    FakeClock,
    ProbeCache,
    SystemClock,
    cooldown_key,
    identity_hash,
)
from l4.config.schema import Profile

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def registry(tmp_path: Path, clock: FakeClock | None = None) -> CooldownRegistry:
    return CooldownRegistry(tmp_path / "availability.json", clock=clock or FakeClock(T0))


def test_cooldown_keyed_by_model_does_not_block_sibling_model(tmp_path):
    reg = registry(tmp_path)
    reg.record(
        "claude-opus", ("claude-code", "opus"), T0 + timedelta(hours=2), "usage_limit", "claude.rate_limit_event"
    )
    assert reg.cooling(("claude-code", "opus")) is not None
    assert reg.cooling(("claude-code", "sonnet")) is None
    assert reg.cooling(("codex", "opus")) is None


def test_a_whole_tool_entry_cools_every_model_and_clear_removes_it(tmp_path):
    reg = registry(tmp_path)
    reg.record("c", ("codex", None), T0 + timedelta(hours=1), "usage_limit", "s")
    assert reg.cooling(("codex", "gpt-6")) is not None and reg.cooling(("codex", None)) is not None
    assert reg.clear(("codex", "gpt-6")) is True  # removes what cools this key, the whole-tool entry included
    assert reg.cooling(("codex", "gpt-6")) is None
    assert reg.clear(("codex", "gpt-6")) is False


def test_expired_entries_are_ignored_and_pruned(tmp_path):
    clock = FakeClock(T0)
    reg = registry(tmp_path, clock)
    reg.record("a", ("codex", "m"), T0 + timedelta(minutes=30), "rate_limit", "s")
    assert reg.cooling(("codex", "m")) is not None
    clock.advance(timedelta(minutes=31))
    assert reg.cooling(("codex", "m")) is None and reg.entries() == []
    reg.record("b", ("claude-code", "x"), clock.now() + timedelta(hours=1), "rate_limit", "s")
    stored = json.loads((tmp_path / "availability.json").read_text())
    assert list(stored["cooldowns"]) == ["claude-code|x"]  # the expired one is gone from the file


def test_a_record_never_shortens_a_cooldown(tmp_path):
    reg = registry(tmp_path)
    reg.record("a", ("codex", "m"), T0 + timedelta(hours=5), "usage_limit", "s")
    reg.record("a", ("codex", "m"), T0 + timedelta(hours=1), "usage_limit", "s")
    assert reg.cooling(("codex", "m")).until == T0 + timedelta(hours=5)


def test_entry_shape_carries_the_spec_fields(tmp_path):
    reg = registry(tmp_path)
    reg.record("codex-sol", ("codex", "gpt-6.1-sol"), T0 + timedelta(hours=1), "usage_limit", "codex.rateLimits", "r-1")
    raw = json.loads((tmp_path / "availability.json").read_text())
    assert raw["version"] == 1
    assert raw["cooldowns"]["codex|gpt-6.1-sol"] == {
        "profile": "codex-sol", "tool": "codex", "model": "gpt-6.1-sol", "until": "2026-10-04T13:00:00Z",
        "kind": "usage_limit", "source": "codex.rateLimits", "recorded_by_run": "r-1",
    }  # fmt: skip


def test_a_corrupt_file_reads_as_empty_with_a_warning_and_is_rewritten(tmp_path, caplog):
    path = tmp_path / "availability.json"
    path.write_text("{not json")
    reg = registry(tmp_path)
    with caplog.at_level("WARNING", logger="l4.availability"):
        assert reg.entries() == []
    assert "unreadable" in caplog.text
    reg.record("a", ("codex", "m"), T0 + timedelta(hours=1), "rate_limit", "s")
    assert json.loads(path.read_text())["cooldowns"]
    path.write_text('["a list"]')  # valid JSON that is not an object is also "empty", not an error
    assert registry(tmp_path).cooling(("codex", "m")) is None


def test_cooldown_event_and_earliest_reset(tmp_path):
    reg = registry(tmp_path)
    assert reg.earliest_reset() is None
    reg.record("a", ("codex", "m"), T0 + timedelta(hours=3), "usage_limit", "s")
    reg.record("b", ("claude-code", "n"), T0 + timedelta(hours=1), "usage_limit", "s")
    assert reg.earliest_reset() == T0 + timedelta(hours=1)
    assert reg.earliest_reset([("codex", "m")]) == T0 + timedelta(hours=3)
    assert reg.earliest_reset([("opencode", "z")]) is None


def test_concurrent_writers_lose_no_entries(tmp_path):
    path = tmp_path / "availability.json"

    def write(index: int) -> None:  # one registry (one lock descriptor) per writer, as in separate jobs
        CooldownRegistry(path).record(
            f"p{index}", ("tool", f"m{index}"), datetime.now(UTC) + timedelta(hours=1), "rate_limit", "s"
        )

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(write, range(24)))
    assert len(CooldownRegistry(path).entries()) == 24


def test_probe_cache_ttl_and_invalidate(tmp_path):
    clock = FakeClock(T0)
    cache = ProbeCache(tmp_path / "availability.json", clock=clock)
    cache.put("codex-a", "id1", {"ok": True})
    cache.put("codex-a", "id2", {"ok": False, "step": "auth"})  # failures are cached too
    cache.put("claude-b", "id1", {"ok": True})
    assert cache.get("codex-a", "id1", 900) == {"ok": True}
    assert cache.get("codex-a", "id2", 900) == {"ok": False, "step": "auth"}
    clock.advance(timedelta(seconds=899))
    assert cache.get("codex-a", "id1", 900) is not None
    clock.advance(timedelta(seconds=2))
    assert cache.get("codex-a", "id1", 900) is None  # past the TTL
    cache.put("codex-a", "id1", {"ok": True})
    cache.invalidate("codex-a")
    assert cache.get("codex-a", "id1", 900) is None and cache.get("codex-a", "id2", 900) is None
    assert cache.get("claude-b", "id1", 900) is None  # expired meanwhile, but invalidate left it alone
    cache.put("claude-b", "id1", {"ok": True})
    assert cache.get("claude-b", "id1", 900) is not None


def test_cooldowns_and_probes_share_one_file_without_clobbering(tmp_path):
    store = AvailabilityStore(tmp_path, clock=FakeClock(T0))
    store.cooldowns.record("a", ("codex", "m"), T0 + timedelta(hours=1), "rate_limit", "s")
    store.probes.put("a", "i", {"ok": True})
    store.cooldowns.record("b", ("codex", "n"), T0 + timedelta(hours=1), "rate_limit", "s")
    assert store.path == tmp_path / "availability.json"
    assert store.probes.get("a", "i", 60) == {"ok": True} and len(store.cooldowns.entries()) == 2


def test_an_in_memory_store_writes_no_file():
    store = AvailabilityStore(None, clock=FakeClock(T0))
    store.cooldowns.record("a", ("codex", "m"), T0 + timedelta(hours=1), "rate_limit", "s")
    assert store.path is None and store.cooldowns.cooling(("codex", "m")) is not None


def test_fake_clock_is_timezone_aware_and_advances():
    clock = FakeClock(T0)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == T0 + timedelta(minutes=5) and clock.now().tzinfo is not None
    assert SystemClock().now().tzinfo is not None
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 1, 1))


def test_identity_hash_not_reversible_and_stable(tmp_path):
    profile = Profile(adapter="claude-code", model="m", auth="subscription")
    env = {"HOME": str(tmp_path), "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-SECRET-123456"}
    first = identity_hash(profile, env)
    assert first == identity_hash(profile, dict(env)) and len(first) == 16
    assert "SECRET" not in first and "123456" not in first
    assert identity_hash(profile, {**env, "CLAUDE_CODE_OAUTH_TOKEN": "other"}) != first
    assert identity_hash(profile, {**env, "HOME": str(tmp_path / "x")}) != first
    assert identity_hash(profile.model_copy(update={"auth": "api_key"}), env) != first
    other_tool = identity_hash(Profile(adapter="codex", model="m", auth="subscription"), env)
    assert other_tool != first


def test_identity_hash_never_reaches_the_cache_file(tmp_path):
    profile = Profile(adapter="codex", auth="api_key", api_key_env="MY_KEY")
    env = {"HOME": str(tmp_path), "MY_KEY": "supersecretvalue"}
    store = AvailabilityStore(tmp_path, clock=FakeClock(T0))
    store.probes.put("p", identity_hash(profile, env), {"ok": True})
    assert "supersecretvalue" not in store.path.read_text()


def test_cooldown_key_distinguishes_fake_profiles_without_a_model_but_not_real_tools():
    assert cooldown_key("a", Profile(adapter="fake")) != cooldown_key("b", Profile(adapter="fake"))
    assert cooldown_key("a", Profile(adapter="codex")) == ("codex", None)
    assert cooldown_key("a", Profile(adapter="codex", model="m")) == ("codex", "m")
    assert cooldown_key("x", Profile(backend="openai-chat", model="m"))[0] == "backend:openai-chat"


def test_identity_hash_of_a_copilot_profile_changes_with_the_token(tmp_path):
    profile = Profile(adapter="copilot-cli", model="claude-sonnet-5.5", auth="api_key", vendor="anthropic")
    env = {"HOME": str(tmp_path), "COPILOT_GITHUB_TOKEN": "fake-copilot-token-one"}
    first = identity_hash(profile, env)
    assert first == identity_hash(profile, dict(env)) and "fake-copilot" not in first
    assert identity_hash(profile, {**env, "COPILOT_GITHUB_TOKEN": "fake-copilot-token-two"}) != first
    assert identity_hash(profile, {"HOME": str(tmp_path)}) != first
    assert identity_hash(profile, {**env, "GH_TOKEN": "x"}) == first  # forge tokens are not its identity
