from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, ProbeResult
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.factory import ADAPTERS, Factory, RoleUnavailable
from l4.agents.fake import FakeAdapter
from l4.config.schema import L4Config, Profile, RolesCfg
from l4.exitcodes import ExitCode, L4Exit


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))


def config(**roles: list[str]) -> L4Config:
    return L4Config(
        profiles={
            "codex-a": Profile(adapter="codex", model="m1", auth="subscription", vendor="openai"),
            "claude-j": Profile(adapter="claude-code", model="m2", auth="subscription", vendor="anthropic"),
            "fake-1": Profile(adapter="fake", vendor="test"),
            "fake-2": Profile(adapter="fake", vendor="test"),
            "api": Profile(backend="openai-chat", model="x"),
        },
        roles=RolesCfg(**roles),
    )


@pytest.fixture
def ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)


def test_registry_has_the_m0_adapters():
    assert ADAPTERS["codex"] is CodexAdapter and ADAPTERS["claude-code"] is ClaudeCodeAdapter
    assert ADAPTERS["fake"]().name == "fake"


def test_for_role_returns_first_usable_and_lists_skipped(ctx):
    first = FakeAdapter([])
    sink = Sink()
    factory = Factory(config(implementer=["fake-1", "fake-2"]), ctx, events=sink, adapters={"fake": first})
    picked = factory.for_role("implementer", "openspec:add-x")
    assert picked.profile_name == "fake-1" and picked.impl is first and picked.fallback_index == 0
    assert picked.skipped == [] and picked.cached is False and picked.fallback_from is None
    assert list(picked.probes) == ["binary", "auth", "quota", "hello"]  # step -> detail, the configured ladder
    [(name, data)] = sink.events
    assert name == "availability.selected"
    assert data == {
        "role": "implementer", "selected": "fake-1", "fallback_index": 0, "skipped": [],
        "probes": {"fake-1": {}}, "cached": False, "quota_window": None,
    }  # fmt: skip


def test_probe_steps_run_in_order_and_stop_at_the_first_failure(ctx):
    seen: list[str] = []

    class Spy(FakeAdapter):
        def probe(self, profile, step, ctx):
            seen.append(step)
            return ProbeResult(step, step != "auth", reason=None if step != "auth" else "logged out")

    sink = Sink()
    factory = Factory(config(implementer=["fake-1", "fake-2"]), ctx, events=sink, adapters={"fake": Spy([])})
    with pytest.raises(RoleUnavailable) as err:
        factory.for_role("implementer", "openspec:x")
    assert seen == ["binary", "auth"] * 2  # hello is never spent on a profile that is not logged in; both are tried
    assert err.value.code == ExitCode.WAITING_CAPACITY
    assert "fake-1" in str(err.value) and "auth" in str(err.value) and "logged out" in str(err.value)
    assert [name for name, _ in sink.events] == ["availability.unavailable"]  # no `selected`: none happened (M1.8 R5)
    assert sink.events[0][1]["role"] == "implementer" and len(sink.events[0][1]["skipped"]) == 2


def test_the_whole_chain_is_walked_when_every_profile_fails(ctx):
    seen: list[str] = []

    class Spy(FakeAdapter):
        def probe(self, profile, step, ctx):
            seen.append(profile.vendor or "")
            return ProbeResult(step, False, reason="down")

    with pytest.raises(RoleUnavailable):
        Factory(
            config(judges=["codex-a", "claude-j"]), ctx, adapters={"codex": Spy([]), "claude-code": Spy([])}
        ).for_role("judges", "u")
    assert seen == ["openai", "anthropic"]  # a failing profile is skipped and the walk goes on


def test_a_missing_chain_or_unknown_role_is_not_a_crash(ctx):
    with pytest.raises(RoleUnavailable, match="no profile"):
        Factory(config(), ctx).for_role("implementer", "u")
    with pytest.raises(ValueError, match="not a role"):
        Factory(config(), ctx).for_role("nonsense", "u")


def test_backend_profiles_and_unknown_adapters_are_refused_with_a_clear_exit(ctx):
    with pytest.raises(L4Exit) as err:
        Factory(config(judges=["api"]), ctx).for_role("judges", "u")
    assert err.value.code == ExitCode.USAGE_ERROR and "backend" in str(err.value)
    cfg = L4Config(profiles={"x": Profile(adapter="gemini-cli")}, roles=RolesCfg(implementer=["x"]))
    with pytest.raises(L4Exit, match="gemini-cli") as err2:
        Factory(cfg, ctx).for_role("implementer", "u")
    assert err2.value.code == ExitCode.USAGE_ERROR


def test_the_probe_context_carries_the_configured_timeout_and_hello_prompt(tmp_path):
    seen = []

    class Spy(FakeAdapter):
        def probe(self, profile, step, ctx):
            seen.append((ctx.timeout_s, ctx.hello_prompt))
            return ProbeResult(step, True)

    cfg = config(implementer=["fake-1"])
    base = ProbeCtx(environ={}, cwd=tmp_path, run=lambda *a: None)
    Factory(cfg, base, adapters={"fake": Spy([])}).for_role("implementer", "u")
    assert seen[0] == (60.0, "Reply with exactly: L4-OK")


def test_a_chain_naming_an_undefined_profile_is_a_usage_error(ctx):
    cfg = L4Config(roles=RolesCfg(implementer=["ghost"]))
    with pytest.raises(L4Exit, match="ghost") as err:
        Factory(cfg, ctx).for_role("implementer", "u")
    assert err.value.code == ExitCode.USAGE_ERROR
