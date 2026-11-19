"""`Factory.for_profile` (L4-YOLO-096, readiness-judge-chain D2): the selection of one profile of a role chain."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, ProbeResult
from l4.agents.factory import Factory, RoleUnavailable
from l4.agents.fake import FakeAdapter
from l4.availability.cooldown import AvailabilityStore, FakeClock
from l4.config.roles import JUDGE_ADAPTERS
from l4.config.schema import L4Config, Profile, RolesCfg


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))


class Spy(FakeAdapter):
    def __init__(self, **kw) -> None:
        super().__init__([], **kw)
        self.probed: list[str] = []

    def probe(self, profile, step, ctx):
        self.probed.append(step)
        return super().probe(profile, step, ctx)


def make(tmp_path: Path, j1: FakeAdapter, j2: FakeAdapter, sink: Sink | None = None) -> Factory:
    cfg = L4Config(
        profiles={
            "j1": Profile(adapter="claude-code", vendor="anthropic"),
            "j2": Profile(adapter="codex", vendor="openai"),
        },
        roles=RolesCfg(judges=["j1", "j2"]),
    )
    clock = FakeClock(datetime(2026, 11, 19, 12, 0, tzinfo=UTC))
    return Factory(
        cfg,
        ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None),
        events=sink,
        adapters={"claude-code": j1, "codex": j2},
        availability=AvailabilityStore(None, clock=clock),
        clock=clock,
    )


def test_for_profile_selects_the_named_profile_without_probing_the_others(tmp_path):
    j1, j2, sink = Spy(), Spy(), Sink()
    picked = make(tmp_path, j1, j2, sink).for_profile("judges", "plan:p1", "j2", serves=JUDGE_ADAPTERS)
    assert picked.profile_name == "j2" and picked.profile.adapter == "codex"
    assert j1.probed == [] and j2.probed
    [(kind, data)] = [e for e in sink.events if e[0] == "availability.selected"]
    assert data["role"] == "judges" and data["selected"] == "j2"


def test_for_profile_sets_the_request_so_that_cool_limited_works(tmp_path):
    from l4.agents.base import LimitSignal
    from l4.availability.cooldown import cooldown_key

    factory = make(tmp_path, Spy(), Spy())
    picked = factory.for_profile("judges", "plan:p1", "j2", serves=JUDGE_ADAPTERS)
    assert picked.request is not None and picked.request.role == "judges" and picked.request.unit == "plan:p1"
    resets = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
    limit = LimitSignal("codex", None, "usage_limit", resets, "test", "")
    _, _, cooldown = factory.cool_limited(picked, limit)
    assert cooldown.until == resets
    assert factory.availability.cooldowns.cooling(
        cooldown_key("j2", picked.profile), datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    )


def test_a_failing_hello_raises_role_unavailable_with_the_reason(tmp_path):
    j2 = Spy(probes={"hello": ProbeResult("hello", False, reason="hello refused")})
    with pytest.raises(RoleUnavailable) as err:
        make(tmp_path, Spy(), j2).for_profile("judges", "plan:p1", "j2", serves=JUDGE_ADAPTERS)
    assert "hello refused" in str(err.value)


def test_a_name_outside_the_chain_is_a_value_error(tmp_path):
    with pytest.raises(ValueError):
        make(tmp_path, Spy(), Spy()).for_profile("judges", "plan:p1", "ghost", serves=JUDGE_ADAPTERS)
    with pytest.raises(ValueError):
        make(tmp_path, Spy(), Spy()).for_profile("nope", "plan:p1", "j1", serves=JUDGE_ADAPTERS)
