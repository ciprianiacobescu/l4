"""Scripted adapters and a config builder for the selection tests."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from l4.agents.base import LimitSignal, ProbeCtx, ProbeResult
from l4.agents.fake import FakeAdapter, Step
from l4.availability.cooldown import AvailabilityStore, FakeClock
from l4.config.schema import L4Config, Profile, RolesCfg

T0 = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
RESET = datetime(2026, 10, 3, 14, 32, tzinfo=UTC)


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.run_id = "r-20261003T1200Z-abcd"

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))

    def of(self, name: str) -> list[dict[str, Any]]:
        return [d for n, d in self.events if n == name]


class Scripted(FakeAdapter):
    """Probes answer per `profile.model`: `plan[model][step]` is a ProbeResult (or a callable returning one); a step
    that is not scripted passes. Every call is recorded in `calls` as (model, step)."""

    def __init__(self, plan: dict[str, dict[str, Any]] | None = None, script: list[Step] | None = None) -> None:
        super().__init__(script or [])
        self.plan = plan or {}
        self.calls: list[tuple[str | None, str]] = []

    def probe(self, profile, step, ctx):
        self.calls.append((profile.model, step))
        outcome = self.plan.get(profile.model or "", {}).get(step)
        if callable(outcome):
            outcome = outcome()
        return outcome if outcome is not None else ProbeResult(step, True)

    def probed(self, model: str) -> list[str]:
        return [step for m, step in self.calls if m == model]


def healthy(model: str, *, used: int = 49, window: str = "session", ms: int = 2104, version: str = "2.1.288"):
    return {
        model: {
            "binary": ProbeResult("binary", True, {"version": version}),
            "auth": ProbeResult("auth", True, {"logged_in": True, "auth_method": "claude.ai"}),
            "quota": ProbeResult("quota", True, {"quota_used_percent": used, "quota_window": window}),
            "hello": ProbeResult("hello", True, {"ms": ms}),
        }
    }


def exhausted(model: str, *, resets: datetime = RESET):
    limit = LimitSignal("codex", model, "usage_limit", resets, "codex.rateLimits", "", 300, 100)
    return {
        model: {
            "binary": ProbeResult("binary", True, {"version": "0.160.0"}),
            "auth": ProbeResult("auth", True, {"logged_in": True, "auth_method": "chatgpt"}),
            "quota": ProbeResult("quota", False, {}, "5h window 100% used, 0% remaining", limit),
        }
    }


def config(profiles: dict[str, Profile], **roles: list[str]) -> L4Config:
    return L4Config(profiles=profiles, roles=RolesCfg(**roles))


def fake_profile(model: str, *, vendor: str = "test", auth: str | None = None) -> Profile:
    return Profile(adapter="fake", model=model, vendor=vendor, auth=auth)  # type: ignore[arg-type]


def probe_ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin", "HOME": str(tmp_path)}, cwd=tmp_path, run=lambda *a: None)


def world(tmp_path: Path, start: datetime = T0) -> tuple[FakeClock, AvailabilityStore]:
    clock = FakeClock(start)
    return clock, AvailabilityStore(tmp_path / "cache", clock=clock)


def later(clock: FakeClock, **delta: float) -> None:
    clock.advance(timedelta(**delta))


Maker = Callable[..., Any]
