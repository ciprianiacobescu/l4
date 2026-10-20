"""The run deadline (L4-IMP-066 to L4-IMP-069, D2 and D3 of run-continuation): one process-wide object, the estimate of
a step, the check before it."""

import ast
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4 import deadline
from l4.availability.cooldown import FakeClock
from l4.deadline import DeadlineReached, RunDeadline, StepMark

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def _arm(clock: FakeClock, left_s: float = 600.0) -> RunDeadline:
    dl = RunDeadline(at=clock.now() + timedelta(seconds=left_s), clock=clock, event=threading.Event(), steps={})
    deadline.arm(dl, timer=lambda s, f: _NoTimer(s, f))
    return dl


class _NoTimer:
    """A timer that never runs and remembers what it was given."""

    def __init__(self, seconds: float, function) -> None:
        self.seconds = seconds
        self.function = function
        self.started = False
        self.cancelled = False
        self.daemon = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def test_the_module_imports_nothing_from_l4() -> None:
    tree = ast.parse(Path(deadline.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("l4"), node.module
            assert node.level == 0
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("l4") for alias in node.names)


def test_remaining_and_fire() -> None:
    clock = FakeClock(START)
    dl = _arm(clock, 600)
    assert dl.remaining_s() == 600
    assert not dl.fired()
    assert not deadline.fired()
    clock.advance(timedelta(seconds=100))
    assert dl.remaining_s() == 500
    dl.fire()
    assert dl.fired()
    assert deadline.fired()


def test_arm_starts_a_timer_and_disarm_cancels_it() -> None:
    clock = FakeClock(START)
    made: list[_NoTimer] = []

    def factory(seconds: float, function) -> _NoTimer:
        made.append(_NoTimer(seconds, function))
        return made[-1]

    dl = RunDeadline(at=clock.now() + timedelta(seconds=90), clock=clock, event=threading.Event(), steps={})
    deadline.arm(dl, timer=factory)
    assert deadline.current() is dl
    assert [t.seconds for t in made] == [90]
    assert made[0].started
    assert made[0].daemon
    made[0].function()  # the timer fires: the event is set
    assert dl.fired()
    deadline.disarm()
    assert made[0].cancelled
    assert deadline.current() is None
    assert not deadline.fired()


def test_the_estimate_has_a_floor_a_cap_and_a_fallback() -> None:
    """SCN-IMP-337."""
    clock = FakeClock(START)
    _arm(clock)
    cap = deadline.cap_s("green", 1800)
    assert deadline.estimate_s("green", [300, 5000], cap) == 3600
    assert deadline.estimate_s("green", [120], cap) == 600
    assert deadline.estimate_s("green", [], cap) == 600
    current = deadline.current()
    assert current is not None
    current.steps["red"] = 1410  # no green measure anywhere: the red's is used
    assert deadline.estimate_s("green", [], cap) == 1410
    assert deadline.estimate_s("green", [], cap, fallback=[2000]) == 1410  # this run's measure comes before a record
    current.steps.clear()
    assert deadline.estimate_s("green", [], cap, fallback=[2000]) == 2000
    assert deadline.estimate_s("green", [300], cap, fallback=[2000]) == 600  # the phase has a measure: no fallback


def test_the_cap_is_per_phase() -> None:
    """SCN-IMP-361."""
    assert deadline.cap_s("verify", 1800) == 7200
    assert deadline.cap_s("green", 1800) == 3600
    assert deadline.cap_s("red", 1800) == 3600
    assert deadline.cap_s("single", 1800, 900) == 2700
    clock = FakeClock(START)
    _arm(clock)
    assert deadline.estimate_s("verify", [7000], deadline.cap_s("verify", 1800)) == 7000


def test_the_first_step_always_starts() -> None:
    """SCN-IMP-336."""
    clock = FakeClock(START)
    dl = _arm(clock, 400)
    deadline.check_before("red", "1.1", 1, None, [1800], False, 3600)
    assert dl.started == 1
    assert dl.step is not None
    assert dl.step.first
    assert dl.step.left_at_start_s == 400
    assert dl.step.estimate_s == 1800


def test_the_first_step_does_not_start_when_no_time_is_left() -> None:
    clock = FakeClock(START)
    dl = _arm(clock, 0)
    with pytest.raises(DeadlineReached) as caught:
        deadline.check_before("red", "1.1", 1, None, [], False, 3600)
    assert caught.value.when == "before"
    assert caught.value.mark is not None
    assert caught.value.mark.first
    assert dl.started == 0
    assert dl.step is None


def test_a_step_that_does_not_fit_raises() -> None:
    """SCN-IMP-335."""
    clock = FakeClock(START)
    dl = _arm(clock, 600)
    deadline.check_before("red", "1.1", 1, None, [], False, 3600)
    dl.steps["red"] = 1410
    deadline.end_step()
    clock.advance(timedelta(seconds=300))
    with pytest.raises(DeadlineReached) as caught:
        deadline.check_before("green", "1.1", 1, None, [], False, 3600)
    exc = caught.value
    assert exc.when == "before"
    assert exc.mark is not None
    assert exc.mark.phase == "green"
    assert exc.mark.left_at_start_s == 300
    assert exc.mark.estimate_s == 1410
    assert dl.step is None
    assert dl.started == 1


def test_a_step_stopped_last_time_starts_only_first() -> None:
    """SCN-IMP-368."""
    clock = FakeClock(START)
    dl = _arm(clock, 9000)
    dl.started = 1
    with pytest.raises(DeadlineReached) as caught:
        deadline.check_before("green", "1.1", 1, None, [], True, 3600)
    assert caught.value.reason == "stopped at the last deadline: it starts only as the first step of a run"
    assert dl.step is None
    dl.started = 0
    deadline.check_before("green", "1.1", 1, None, [], True, 3600)
    assert dl.started == 1
    assert dl.step is not None
    assert dl.step.first


def test_check_before_is_idempotent_for_the_same_step() -> None:
    clock = FakeClock(START)
    dl = _arm(clock, 9000)
    deadline.check_before("green", "1.1", 1, None, [], False, 3600)
    first = dl.step
    clock.advance(timedelta(seconds=5))
    deadline.check_before("green", "1.1", 1, None, [], False, 3600)
    assert dl.started == 1
    assert dl.step is first


def test_a_different_current_mark_is_replaced_unrecorded() -> None:
    clock = FakeClock(START)
    dl = _arm(clock, 9000)
    deadline.check_before("green", "1.1", 1, None, [], False, 3600)
    assert dl.step is not None and dl.step.first
    clock.advance(timedelta(seconds=40))
    deadline.check_before("red", "1.1", 1, None, [], False, 3600)
    assert dl.started == 1
    assert dl.steps == {}  # the green was not measured
    assert dl.step is not None
    assert dl.step.phase == "red"
    assert dl.step.first
    assert dl.step.started_at == clock.now()


def test_the_mark_holds_the_step_and_end_step_clears_it() -> None:
    clock = FakeClock(START)
    dl = _arm(clock, 9000)
    deadline.check_before("green", "1.2", 2, None, [], False, 3600)
    mark = dl.step
    assert mark == StepMark(
        phase="green", task="1.2", attempt=2, round=None, started_at=START, first=True,
        left_at_start_s=9000, estimate_s=600,
    )  # fmt: skip
    clock.advance(timedelta(seconds=77))
    assert deadline.end_step() == 77
    assert dl.step is None
    assert dl.steps == {"green": 77}
    assert deadline.end_step() == 0  # nothing current


def test_no_deadline_no_check() -> None:
    """SCN-IMP-338."""
    assert deadline.current() is None
    deadline.check_before("green", "1.1", 1, None, [], True, 3600)
    assert deadline.end_step() == 0
    assert not deadline.fired()


def test_deadline_reached_is_not_an_exception() -> None:
    assert issubclass(DeadlineReached, BaseException)
    assert not issubclass(DeadlineReached, Exception)


def test_no_l4_job_variable_reaches_a_test() -> None:
    assert not [name for name in os.environ if name.startswith("L4_JOB_")]
