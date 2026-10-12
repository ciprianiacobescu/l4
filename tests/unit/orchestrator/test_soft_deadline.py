"""L4-IMP-012 between units: `run_units` starts no unit once the soft deadline has passed or the next unit (estimated
as the longest one run so far) would not fit in what is left. The units left are listed, exit 10, untouched."""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from l4 import orchestrator
from l4.availability.cooldown import FakeClock
from l4.exitcodes import ExitCode
from l4.orchestrator import UnitRunResult
from l4.outcome import UnitOutcome

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def _cfg(budget: str = "auto", margin: str = "20m"):
    return SimpleNamespace(
        forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget=budget, soft_deadline_margin=margin)
    )


def _units(*names: str):
    return [(object(), SimpleNamespace(id=f"openspec:{n}")) for n in names]


@pytest.fixture
def clock(monkeypatch):
    clock = FakeClock(START)
    monkeypatch.setattr("l4.services.SystemClock", lambda: clock)
    monkeypatch.setattr(
        orchestrator, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="implementing"))
    )
    return clock


def _run(monkeypatch, clock, cfg, units, *, environ=None, took=(600,), codes=(0,)):
    """Run `units` where the n-th takes `took[n]` seconds (the last repeats) and exits `codes[n]`."""
    ran: list[str] = []

    def fake(app, cfg, git, provider, ref, **kw):
        n = len(ran)
        ran.append(ref.id)
        clock.advance(timedelta(seconds=took[min(n, len(took) - 1)]))
        outcome = UnitOutcome(unit=ref.id, phase_before="ready", phase_after="implemented")
        return UnitRunResult(outcome, codes[min(n, len(codes) - 1)])

    monkeypatch.setattr(orchestrator, "run_unit_in_worktree", fake)
    app = SimpleNamespace(environ=environ or {}, redactor=SimpleNamespace(redact_text=lambda t: t))
    return ran, orchestrator.run_units(app, cfg, None, units, adapters=None)


def test_a_next_unit_that_does_not_fit_in_the_time_left_is_not_started(monkeypatch, clock, caplog):
    """SCN-IMP-62: 40 min budget, 20 min margin: unit a takes 15 of the 20 soft minutes."""
    caplog.set_level(logging.INFO, logger="l4")
    ran, out = _run(monkeypatch, clock, _cfg("40m"), _units("a", "b", "c"), took=(900,))
    assert ran == ["openspec:a"] and out.code == ExitCode.CONTINUE
    a, b, c = out.units
    assert a.exit_reason is None
    for left in (b, c):
        assert left.phase_before == left.phase_after == "implementing"
        assert left.exit_reason == "not started: soft deadline (300 s left, next unit estimated 900 s)"
    assert "soft deadline: 2 unit(s) left for the next run (300 s left, next unit estimated 900 s)" in caplog.text


def test_the_estimate_is_the_longest_unit_of_the_run(monkeypatch, clock):
    ran, out = _run(monkeypatch, clock, _cfg("60m"), _units("a", "b", "c", "d"), took=(300, 900, 300))
    # 40 min of soft time: a 5 min, b 15 min (20 used), c fits (20 left >= 15) and takes 5, d: 15 left >= 15 runs too
    assert ran == ["openspec:a", "openspec:b", "openspec:c", "openspec:d"] and out.code == 0
    ran, out = _run(monkeypatch, clock, _cfg("50m"), _units("a", "b", "c", "d"), took=(300, 900, 300))
    assert ran == ["openspec:a", "openspec:b"] and out.code == ExitCode.CONTINUE  # 10 left < 15
    assert [u.unit for u in out.units if u.exit_reason] == ["openspec:c", "openspec:d"]


def test_without_a_budget_every_unit_runs(monkeypatch, clock):
    """SCN-IMP-63: `auto` outside a GitLab job (no CI_JOB_TIMEOUT) has no deadline."""
    ran, out = _run(monkeypatch, clock, _cfg("auto"), _units("a", "b", "c"), took=(86400,))
    assert len(ran) == 3 and out.code == 0 and all(u.exit_reason is None for u in out.units)


def test_no_time_left_before_the_second_unit_stops_the_run(monkeypatch, clock, caplog):
    """SCN-IMP-64: remaining <= 0 stops the run even before any estimate is trusted; the first unit still started."""
    caplog.set_level(logging.INFO, logger="l4")
    ran, out = _run(monkeypatch, clock, _cfg("30m"), _units("a", "b"), took=(600,))  # 10 min of soft time, 10 used
    assert ran == ["openspec:a"] and out.code == ExitCode.CONTINUE
    assert out.units[1].exit_reason == "not started: soft deadline (0 s left, next unit estimated 600 s)"
    assert "1 unit(s) left for the next run (0 s left, next unit estimated 600 s)" in caplog.text


def test_the_first_unit_always_starts(monkeypatch, clock):
    ran, out = _run(monkeypatch, clock, _cfg("10m"), _units("a"), took=(60,))  # soft time already negative
    assert ran == ["openspec:a"] and out.code == 0


def test_the_job_timeout_and_start_of_a_gitlab_job_set_the_deadline(monkeypatch, clock):
    env = {"CI_JOB_TIMEOUT": "3600", "CI_JOB_STARTED_AT": (START - timedelta(minutes=30)).isoformat()}
    # 60 min job, 20 min margin, 30 min gone before the run: 10 min of soft time; unit a takes 5, b (5) fits
    ran, out = _run(monkeypatch, clock, _cfg(), _units("a", "b", "c"), environ=env, took=(300,))
    assert ran == ["openspec:a", "openspec:b"] and out.code == ExitCode.CONTINUE
    assert out.units[2].unit == "openspec:c" and "not started" in out.units[2].exit_reason


def test_the_exit_code_is_the_most_severe_of_the_units_and_the_continue(monkeypatch, clock):
    ran, out = _run(monkeypatch, clock, _cfg("40m"), _units("a", "b"), took=(900,), codes=(ExitCode.AWAITING_HUMAN,))
    assert out.code == ExitCode.AWAITING_HUMAN  # 11 outranks 10 in the severity order
    ran, out = _run(monkeypatch, clock, _cfg("40m"), _units("a", "b"), took=(900,), codes=(ExitCode.HALTED,))
    assert out.code == ExitCode.HALTED


@pytest.mark.parametrize(
    ("env", "now_s", "want"),
    [
        ({"CI_JOB_TIMEOUT": "1500"}, 0, 300),
        ({"CI_JOB_TIMEOUT": "1500"}, 120, 180),
        ({"CI_JOB_TIMEOUT": "abc"}, 0, None),
        ({}, 0, None),
        ({"CI_JOB_TIMEOUT": "3600", "CI_JOB_STARTED_AT": "2025-12-31T23:30:00Z"}, 0, 600),
        ({"CI_JOB_TIMEOUT": "3600", "CI_JOB_STARTED_AT": "not a time"}, 0, 2400),
    ],
)
def test_job_remaining_s(env, now_s, want):
    now = START + timedelta(seconds=now_s)
    assert orchestrator.job_remaining_s(_cfg(), env, now, START) == want


def test_a_set_time_budget_wins_over_the_job_timeout():
    env = {"CI_JOB_TIMEOUT": "99999"}
    assert orchestrator.job_remaining_s(_cfg("30m", "10m"), env, START, START) == 1200


@pytest.mark.parametrize(
    ("env", "want"),
    [
        ({"L4_JOB_TIMEOUT_MINUTES": "180"}, 180 * 60 - 1200),
        ({"L4_JOB_TIMEOUT_MINUTES": "180h"}, None),
        ({"L4_JOB_TIMEOUT_MINUTES": ""}, None),
        ({"CI_JOB_TIMEOUT": "1500", "L4_JOB_TIMEOUT_MINUTES": "180"}, 300),  # GitLab's variable is read first
        ({"CI_JOB_TIMEOUT": "abc", "L4_JOB_TIMEOUT_MINUTES": "180"}, 180 * 60 - 1200),
    ],
)
def test_github_job_timeout_minutes(env, want):
    """SCN-GHP-04: on GitHub `auto` reads the job env L4_JOB_TIMEOUT_MINUTES (minutes, digits only)."""
    assert orchestrator.job_remaining_s(_cfg(), env, START, START) == want
