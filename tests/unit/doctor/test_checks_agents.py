from pathlib import Path

import pytest

from l4.agents import factory as factory_module
from l4.agents.base import ProbeResult
from l4.agents.fake import FakeAdapter
from l4.config.schema import L4Config, Profile, RolesCfg
from l4.doctor import checks_agents
from l4.doctor.registry import REGISTRY, load_check_modules, run_checks


class Scripted(FakeAdapter):
    """Probe results by profile vendor; records which (vendor, step) pairs ran."""

    log: list[tuple[str | None, str]] = []

    def __init__(self, failing: dict[str, tuple[str, str]]) -> None:
        super().__init__([])
        self.failing = failing

    def probe(self, profile, step, ctx):
        self.log.append((profile.vendor, step))
        bad = self.failing.get(profile.vendor or "")
        if bad and bad[0] == step:
            return ProbeResult(step, False, reason=bad[1])
        return ProbeResult(step, True, {"ms": 7} if step == "hello" else {})


def cfg(**roles: list[str]) -> L4Config:
    return L4Config(
        profiles={"impl": Profile(adapter="fake", vendor="a"), "judge": Profile(adapter="fake", vendor="b")},
        roles=RolesCfg(**roles),
    )


@pytest.fixture
def scripted(monkeypatch):
    def install(failing=None):
        Scripted.log = []
        adapter = Scripted(failing or {})
        monkeypatch.setitem(factory_module.ADAPTERS, "fake", lambda: adapter)
        return adapter

    return install


def test_live001_hello_first_profile_and_no_duplicate_env_ids(make_ctx, scripted):
    scripted()
    load_check_modules()
    ids = [c.id for c in REGISTRY.checks()]
    assert ids.count("LIVE-001") == 1 and ids.count("ENV-004") == 1  # ENV-004 is registered by checks_env only
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"], judges=["judge"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert live.status == "pass" and live.severity == "error"
    assert "implementer: impl" in live.message and "judges: judge" in live.message
    assert Scripted.log == [
        ("a", "binary"),
        ("a", "auth"),
        ("a", "quota"),
        ("a", "hello"),
        ("b", "binary"),
        ("b", "auth"),
        ("b", "quota"),
        ("b", "hello"),
    ]


def test_live001_is_a_live_only_check(make_ctx, scripted):
    scripted()
    load_check_modules()
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"], judges=["judge"]))
    assert "LIVE-001" not in [o.id for o in run_checks(ctx)]


def test_live001_names_the_role_profile_step_and_reason_of_a_failure(make_ctx, scripted):
    scripted({"b": ("auth", "claude is not logged in")})
    load_check_modules()
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"], judges=["judge"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert live.status == "fail"
    assert "judges" in live.message and "judge" in live.message and "auth" in live.message
    assert "claude is not logged in" in live.message and live.fix_hint


def test_live001_reports_every_failing_role_not_just_the_first(make_ctx, scripted):
    scripted({"a": ("binary", "codex not found on PATH"), "b": ("hello", "timeout")})
    load_check_modules()
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"], judges=["judge"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert "codex not found" in live.message and "timeout" in live.message


def test_live001_with_no_roles_configured_is_a_config_matter_not_a_probe(make_ctx, scripted):
    scripted()
    load_check_modules()
    ctx, _ = make_ctx(cfg=L4Config())
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert live.status == "fail" and "no profile" in live.message


def test_the_probe_scratch_directory_is_outside_the_repository(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"]))
    with checks_agents.scratch_dir(ctx.repo) as scratch:
        assert Path(scratch).is_dir() and ctx.repo not in Path(scratch).parents
    assert not Path(scratch).exists()


def test_live001_names_a_slow_step_with_its_duration(make_ctx, scripted, monkeypatch):
    """kiro-judge live finding 1: the next slow step is visible in the readiness line."""
    import time

    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    adapter = scripted()
    plain = adapter.probe

    def slow(profile, step, ctx):
        now[0] += 27.4 if step == "quota" else 0.0
        return plain(profile, step, ctx)

    monkeypatch.setattr(adapter, "probe", slow)
    load_check_modules()
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"], judges=["judge"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert live.status == "pass"
    assert "implementer: impl ok (hello 7 ms; quota 27400 ms)" in live.message
    assert "judges: judge ok (hello 7 ms; quota 27400 ms)" in live.message


def test_live001_line_is_unchanged_when_every_step_is_fast(make_ctx, scripted):
    scripted()
    load_check_modules()
    ctx, _ = make_ctx(cfg=cfg(implementer=["impl"], judges=["judge"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert live.message == "implementer: impl ok (hello 7 ms); judges: judge ok (hello 7 ms)"
