"""Kiro polish (b): every remaining implementer is cooling for a short time, so the run waits for it in place
(`availability.wait_in_run`, L4-AVL-011) instead of exiting 12 and leaving the unit to the next pipeline."""

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.agents.kiro_cli import throttle_signal
from l4.exitcodes import ExitCode

from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH

ONE = {"roles": {"implementer": ["impl"]}}


def throttled(clock, **over: object) -> Step:
    limit = throttle_signal("Internal error (code -32603): The request was throttled by the service", clock.now())
    return Step(status="rate_limited", limit=limit, **over)


def test_a_short_cooldown_of_the_only_implementer_is_waited_out_in_the_run(run_l4, fake_clock, capsys):
    run = run_l4([throttled(fake_clock, writes={"leftover.txt": "x"}), red_step(), green_step()], **ONE)
    assert run.code == 0
    assert fake_clock.slept == [120]
    (waited,) = run.events("availability.wait_in_run")
    assert (waited["profile"], waited["waited_s"]) == ("impl", 120) and waited["kind"] == "rate_limit"
    assert "[l4] waiting 120s for impl (rate_limit)" in capsys.readouterr().err
    assert run.events("task.attempt_failed") == []
    assert [e["status"] for e in run.events("step.finished")][:1] == ["rate_limited"]
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


def test_a_thirty_minute_cooldown_still_exits_12_without_waiting(run_l4, fake_clock):
    limit = LimitSignal("fake", None, "rate_limit", None, "claude.http_429", "429")
    run = run_l4([red_step(), Step(status="rate_limited", limit=limit)], **ONE)
    assert run.code == ExitCode.WAITING_CAPACITY
    assert fake_clock.slept == [] and run.events("availability.wait_in_run") == []


def test_zero_switches_the_wait_off(run_l4, fake_clock):
    run = run_l4([throttled(fake_clock)], **ONE | {"availability": {"wait_in_run": "0"}})
    assert run.code == ExitCode.WAITING_CAPACITY and fake_clock.slept == []


def test_the_waits_of_one_run_are_capped_in_total(run_l4, fake_clock):
    script = [throttled(fake_clock), throttled(fake_clock), red_step(), green_step()]
    run = run_l4(script, **ONE | {"availability": {"wait_in_run_max_total": "3m"}})
    assert run.code == ExitCode.WAITING_CAPACITY  # 120 s fit, another 120 s would make 240 s of 180
    assert fake_clock.slept == [120]


def test_a_wait_never_outlasts_the_jobs_remaining_time(run_l4, fake_clock, tdd_repo):
    # 40 min of job, 20 min soft-deadline margin: 20 min left, 2 fit; the step after the wait needs its 10-minute floor
    # (L4-IMP-067: a step that is not the run's first starts only when its estimate fits; 5 min left would hand it back)
    tdd_repo.environ["CI_JOB_TIMEOUT"] = "2400"
    ok = run_l4([throttled(fake_clock), red_step(), green_step()], **ONE)
    assert ok.code == 0 and fake_clock.slept == [120]


@pytest.mark.parametrize("timeout", ["1250", "1230"])
def test_no_wait_when_the_job_has_less_time_than_the_wait(run_l4, fake_clock, tdd_repo, timeout):
    tdd_repo.environ["CI_JOB_TIMEOUT"] = timeout  # under 2 min left after the margin
    run = run_l4([throttled(fake_clock)], **ONE)
    assert run.code == ExitCode.WAITING_CAPACITY and fake_clock.slept == []


def test_every_unit_of_one_run_shares_the_wait_budget(monkeypatch):
    """`wait_in_run_max_total` bounds the run, not each unit: `run_units` hands one `RunWaits` to every unit."""
    from types import SimpleNamespace

    from l4 import orchestrator
    from l4.orchestrator import UnitRunResult
    from l4.outcome import UnitOutcome

    monkeypatch.setattr(
        orchestrator, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="implementing"))
    )
    seen = []

    def fake(app, cfg, git, provider, ref, **kw):
        seen.append(kw.get("waits"))
        return UnitRunResult(UnitOutcome(unit=ref.id, phase_before="ready", phase_after="implemented"), 0)

    monkeypatch.setattr(orchestrator, "run_unit_in_worktree", fake)
    units = [(object(), SimpleNamespace(id=f"openspec:{n}")) for n in ("a", "b")]
    cfg = SimpleNamespace(ci=SimpleNamespace(time_budget="auto", soft_deadline_margin="20m"))
    orchestrator.run_units(SimpleNamespace(environ={}), cfg, None, units, adapters=None)
    first, second = seen
    assert isinstance(first, orchestrator.RunWaits) and first is second


def test_a_unit_sees_what_earlier_units_of_the_run_waited(run_l4, fake_clock, monkeypatch):
    from l4 import orchestrator

    real = orchestrator.RunWaits
    monkeypatch.setattr(orchestrator, "RunWaits", lambda: real(waited_s=120))  # what an earlier unit waited
    run = run_l4([throttled(fake_clock)], **ONE | {"availability": {"wait_in_run_max_total": "3m"}})
    assert run.code == ExitCode.WAITING_CAPACITY  # 120 s already waited by an earlier unit: 120 more would make 240
    assert fake_clock.slept == []
