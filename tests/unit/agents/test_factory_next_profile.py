"""`Factory.next_profile` (escalate-and-note D5, SCN-IMP-176, SCN-IMP-180): the move to the next rung of a chain."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, ProbeResult
from l4.agents.factory import Factory, RoleUnavailable, WaitingCapacity
from l4.agents.fake import FakeAdapter
from l4.availability.cooldown import AvailabilityStore, FakeClock, cooldown_key
from l4.config.schema import L4Config, Profile, RolesCfg

FIRST, SECOND, THIRD = "deepseek", "glm", "claude-sonnet"


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))

    def of(self, name: str) -> list[dict]:
        return [d for n, d in self.events if n == name]


def config(chain: list[str]) -> L4Config:
    return L4Config(
        profiles={
            FIRST: Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek"),
            SECOND: Profile(adapter="opencode", model="opencode-go/glm-5.3-flash", vendor="zhipu"),
            THIRD: Profile(adapter="fake", vendor="anthropic"),
        },
        roles=RolesCfg(implementer=chain),
    )


@pytest.fixture
def ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


def make(ctx, clock, sink, chain=(FIRST, SECOND), adapters=None) -> Factory:
    adapters = adapters or {"opencode": FakeAdapter([]), "fake": FakeAdapter([])}
    return Factory(
        config(list(chain)),
        ctx,
        events=sink,
        adapters=adapters,
        availability=AvailabilityStore(None, clock=clock),
        clock=clock,
    )


def test_the_second_profile_of_one_adapter_is_selected_as_an_escalation(ctx, clock, caplog):
    sink = Sink()
    factory = make(ctx, clock, sink)
    with caplog.at_level(logging.INFO):
        picked = factory.next_profile("implementer", "openspec:x", FIRST)
    assert picked.profile_name == SECOND and picked.fallback_from is None
    [event] = sink.of("availability.selected")
    assert event["role"] == "implementer" and event["selected"] == SECOND and event["escalated_from"] == FIRST
    assert "fallback_from" not in event and event["skipped"] == [] and event["cached"] is False
    assert SECOND in event["probes"]
    assert any(r.getMessage().endswith(f"→ selected, escalated from {FIRST}") for r in caplog.records)
    assert not any("fallback #" in r.getMessage() for r in caplog.records)
    assert picked.request is not None and picked.request.role == "implementer"


def test_a_cooling_second_profile_raises_role_unavailable_and_records_no_unavailable_event(ctx, clock):
    sink = Sink()
    factory = make(ctx, clock, sink)
    cfg = config([FIRST, SECOND])
    factory.availability.cooldowns.record(
        SECOND, cooldown_key(SECOND, cfg.profiles[SECOND]), clock.now() + timedelta(hours=1), "rate_limit", "test"
    )
    with pytest.raises(RoleUnavailable) as err:
        factory.next_profile("implementer", "openspec:x", FIRST)
    assert not isinstance(err.value, WaitingCapacity) and SECOND in str(err.value)
    assert sink.of("availability.unavailable") == [] and sink.of("availability.selected") == []


def test_a_constraint_veto_skips_a_profile_with_its_reason(ctx, clock):
    sink = Sink()
    factory = make(ctx, clock, sink, chain=(FIRST, SECOND, THIRD))

    def no_glm(name, profile):
        return "would not be independent" if name == SECOND else None

    picked = factory.next_profile("implementer", "openspec:x", FIRST, constraints=(no_glm,))
    assert picked.profile_name == THIRD
    [event] = sink.of("availability.selected")
    assert event["escalated_from"] == FIRST
    assert [(s["profile"], s["step"], s["reason"]) for s in event["skipped"]] == [
        (SECOND, "constraint", "would not be independent")
    ]


def test_the_profiles_before_and_at_after_are_never_considered(ctx, clock):
    probed: list[str] = []

    class Spy(FakeAdapter):
        def probe(self, profile, step, ctx):
            probed.append(profile.model or "")
            return ProbeResult(step, True)

    sink = Sink()
    factory = make(ctx, clock, sink, adapters={"opencode": Spy([]), "fake": Spy([])})
    factory.next_profile("implementer", "u", FIRST)
    assert set(probed) == {"opencode-go/glm-5.3-flash"}


def test_nothing_is_cooled_by_a_selection_or_a_refusal(ctx, clock):
    sink = Sink()
    factory = make(ctx, clock, sink)
    factory.next_profile("implementer", "u", FIRST)
    with pytest.raises(RoleUnavailable):
        factory.next_profile("implementer", "u", SECOND)
    assert sink.of("availability.cooldown") == []
    assert factory.availability.cooldowns.entries(clock.now()) == []


def test_an_after_that_is_last_or_not_in_the_chain_raises_at_once(ctx, clock):
    sink = Sink()
    factory = make(ctx, clock, sink)
    for after in (SECOND, "nowhere"):
        with pytest.raises(RoleUnavailable):
            factory.next_profile("implementer", "u", after)
    assert sink.events == []


def test_a_failing_later_profile_is_skipped_and_no_unavailable_event_is_written(ctx, clock):
    class Down(FakeAdapter):
        def probe(self, profile, step, ctx):
            return ProbeResult(step, False, reason="logged out")

    sink = Sink()
    factory = make(ctx, clock, sink, adapters={"opencode": Down([]), "fake": Down([])})
    with pytest.raises(RoleUnavailable) as err:
        factory.next_profile("implementer", "u", FIRST)
    assert "logged out" in str(err.value) and sink.of("availability.unavailable") == []
