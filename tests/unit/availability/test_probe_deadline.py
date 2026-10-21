"""C-m2: a probe cannot be stopped once it runs (`run_process` knows nothing of the run deadline), so none is started
once the run deadline has fired: before the probe and before each of its steps."""

from pathlib import Path

import pytest

from l4 import deadline
from l4.agents.base import ProbeCtx, ProbeResult
from l4.agents.factory import Factory
from l4.availability.probes import ProbeLadder
from l4.config.schema import L4Config, Profile
from l4.provision.readiness import adapter_readiness

from .test_probes import _spy_adapter, claude_profile


def test_no_probe_step_starts_after_the_deadline(make_ctx, armed_deadline):
    ctx, _ = make_ctx({})
    armed_deadline().fire()
    seen: list[str] = []
    with pytest.raises(deadline.DeadlineReached) as caught:
        ProbeLadder(ctx, ["binary", "auth"]).run(_spy_adapter({}, seen), claude_profile)
    assert caught.value.when == "before" and seen == []


def test_a_deadline_that_fires_between_two_steps_stops_before_the_second(make_ctx, armed_deadline):
    ctx, _ = make_ctx({})
    dl = armed_deadline()
    seen: list[str] = []

    def fire_after_binary(step):
        dl.fire()
        return ProbeResult(step, True)

    adapter = _spy_adapter({}, seen)
    real = adapter.probe
    adapter.probe = lambda profile, step, ctx: fire_after_binary(step) if real(profile, step, ctx) else None
    with pytest.raises(deadline.DeadlineReached):
        ProbeLadder(ctx, ["binary", "auth", "quota"]).run(adapter, claude_profile)
    assert seen == ["binary"]


def test_without_a_deadline_or_before_it_the_probes_run(make_ctx, armed_deadline):
    ctx, _ = make_ctx({})
    seen: list[str] = []
    ProbeLadder(ctx, ["binary", "auth"]).run(_spy_adapter({}, seen), claude_profile)
    armed_deadline()  # armed, not fired
    ProbeLadder(ctx, ["binary", "auth"]).run(_spy_adapter({}, seen), claude_profile)
    assert seen == ["binary", "auth", "binary", "auth"]


class _Scripted:
    name = "scripted"

    def __init__(self) -> None:
        self.steps: list[str] = []

    def probe(self, profile, step, ctx):
        self.steps.append(step)
        return ProbeResult(step, True, {"logged_in": True})


def test_the_readiness_probes_of_a_profile_do_not_start_after_the_deadline(armed_deadline):
    ctx = ProbeCtx({}, Path("."), lambda *a: None)
    adapter = _Scripted()
    factory = Factory(L4Config(), ctx, adapters={"codex": adapter})
    armed_deadline().fire()
    with pytest.raises(deadline.DeadlineReached):
        adapter_readiness("c", Profile(adapter="codex", auth="subscription"), factory, ctx)
    assert adapter.steps == []
