"""Stage B wiring of the Factory: the new adapters are registered, and an adapter that cannot report the served model
or is experimental says so once in the ledger."""

from pathlib import Path
from typing import ClassVar

import pytest

from l4.agents.base import ProbeCtx
from l4.agents.command import CommandAdapter
from l4.agents.factory import ADAPTERS, Factory
from l4.agents.fake import FakeAdapter
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.opencode import OpenCodeAdapter
from l4.config.schema import L4Config, Profile, RolesCfg


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))

    def named(self, name: str) -> list[dict]:
        return [d for n, d in self.events if n == name]


@pytest.fixture
def ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)


class Unverified(FakeAdapter):
    model_unverified: ClassVar[bool] = True


class Experimental(Unverified):
    experimental: ClassVar[bool] = True


def config(adapter: str) -> L4Config:
    return L4Config(
        profiles={"free": Profile(adapter=adapter, model="opencode/big-pickle", vendor="unknown")},
        roles=RolesCfg(implementer=["free"]),
    )


def test_stage_b_adapters_are_registered():
    assert ADAPTERS["opencode"] is OpenCodeAdapter and ADAPTERS["kiro-cli"] is KiroCliAdapter
    assert ADAPTERS["command"] is CommandAdapter


def test_model_unverified_is_logged_at_each_selection(ctx):
    sink = Sink()
    factory = Factory(config("opencode"), ctx, events=sink, adapters={"opencode": Unverified([])})
    factory.for_role("implementer", "u1")
    factory.for_role("implementer", "u1")
    assert sink.named("availability.model_unverified") == [
        {"role": "implementer", "profile": "free", "model": "opencode/big-pickle", "vendor": "unknown"}
    ] * 2


def test_experimental_is_logged_once_per_factory(ctx):
    sink = Sink()
    factory = Factory(config("kiro-cli"), ctx, events=sink, adapters={"kiro-cli": Experimental([])})
    factory.for_role("implementer", "u1")
    factory.for_role("implementer", "u1")
    [event] = sink.named("agent.experimental")
    assert event["profile"] == "free" and event["adapter"] == "kiro-cli"


def test_a_verified_adapter_writes_neither_event(ctx):
    sink = Sink()
    Factory(config("fake"), ctx, events=sink, adapters={"fake": FakeAdapter([])}).for_role("implementer", "u1")
    assert not sink.named("availability.model_unverified") and not sink.named("agent.experimental")


def test_an_unrecorded_cli_version_is_logged_at_selection(ctx, monkeypatch):
    from l4 import recordedversions
    from l4.agents.base import ProbeResult

    monkeypatch.setattr(recordedversions, "load", lambda: {"opencode": ["1.18.33"]})
    sink = Sink()
    probes = {"binary": ProbeResult("binary", True, {"version": "1.18.34"})}
    adapters = {"opencode": FakeAdapter([], probes=probes)}
    Factory(config("opencode"), ctx, events=sink, adapters=adapters).for_role("implementer", "u1")
    assert sink.named("availability.unrecorded_version") == [
        {"role": "implementer", "profile": "free", "adapter": "opencode", "version": "1.18.34", "recorded": ["1.18.33"]}
    ]
    probes = {"binary": ProbeResult("binary", True, {"version": "1.18.33"})}
    adapters = {"opencode": FakeAdapter([], probes=probes)}
    sink = Sink()
    Factory(config("opencode"), ctx, events=sink, adapters=adapters).for_role("implementer", "u1")
    assert not sink.named("availability.unrecorded_version")
