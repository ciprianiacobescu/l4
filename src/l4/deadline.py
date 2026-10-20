"""The run's soft deadline (L4-IMP-012, L4-IMP-066 to L4-IMP-069): one process-wide object that `l4 run` arms when the
CI job's budget is known. A leaf module (it imports nothing from `l4`), like `l4.cancel`: every process a unit starts
(`ProcRunner._wait`) and every step (`check_before`) reads the same state, so no event is threaded through a
constructor.

`DeadlineReached` is a `BaseException`, like `RunCancelled`: no `except Exception` of a part of a step (the verifier
ladder has several) turns a stop into a failure. `Orchestrator.run_unit` is the one place that catches it."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

FLOOR_S = 600  # the smallest estimate of a step
MAX_STOPS = 2  # counted stops of one task and phase before the unit halts
HISTORY = 10  # the recorded steps of a phase the estimate reads
AGENT_TIMEOUT_S = 1800  # the agent's time limit (`RunRequest.timeout_s`), which no configuration key sets
STOPPED_LAST_REASON = "stopped at the last deadline: it starts only as the first step of a run"


class Clock(Protocol):
    def now(self) -> datetime: ...  # tz-aware UTC


class _Timer(Protocol):
    daemon: bool

    def start(self) -> None: ...
    def cancel(self) -> None: ...


@dataclass(frozen=True)
class StepMark:
    """What the raise sites cannot know about the step that was running (review M1)."""

    phase: str  # red | green | single | verify
    task: str | None
    attempt: int | None
    round: int | None
    started_at: datetime  # on the factory clock
    first: bool  # the first step of its run
    left_at_start_s: float
    estimate_s: float


class DeadlineReached(BaseException):  # noqa: N818 - like RunCancelled: it must pass `except Exception`
    def __init__(
        self,
        when: Literal["before", "during"],
        *,
        during: Literal["agent", "judge", "gate"] | None = None,
        gate: str | None = None,
        reason: str | None = None,
        mark: StepMark | None = None,
    ) -> None:
        super().__init__(f"soft deadline reached ({when}{' ' + during if during else ''})")
        self.when = when
        self.during = during  # set by the raise sites of D4
        self.gate = gate
        self.reason = reason  # a `before` deferral that is not about time
        self.mark = mark  # a `before` deferral: the mark of the step that was not started (never set as `step`)


@dataclass
class RunDeadline:
    at: datetime  # the soft deadline, on the factory clock
    clock: Clock
    event: threading.Event  # set at `at` by the timer, or by `fire()`
    steps: dict[str, float] = field(default_factory=dict)  # phase -> the longest step of that phase measured here
    started: int = 0  # steps started in this run (any unit)
    step: StepMark | None = None  # the step running now; None between steps

    def remaining_s(self) -> float:
        return (self.at - self.clock.now()).total_seconds()

    def fired(self) -> bool:
        return self.event.is_set()

    def fire(self) -> None:
        self.event.set()


_state: dict[str, object] = {"deadline": None, "timer": None}


def arm(deadline: RunDeadline, *, timer: Callable[[float, Callable[[], None]], _Timer] = threading.Timer) -> None:
    """Make `deadline` the run's, and start a daemon timer that fires it at `at` (a past `at` fires at once)."""
    disarm()
    _state["deadline"] = deadline
    if deadline.fired():
        return
    started = timer(max(0.0, deadline.remaining_s()), deadline.fire)
    started.daemon = True
    started.start()
    _state["timer"] = started


def disarm() -> None:
    timer = _state["timer"]
    if timer is not None:
        timer.cancel()  # type: ignore[attr-defined]
    _state["timer"] = None
    _state["deadline"] = None


def current() -> RunDeadline | None:
    value = _state["deadline"]
    return value if isinstance(value, RunDeadline) else None


def fired() -> bool:
    now = current()
    return now is not None and now.fired()


def cap_s(phase: str, gates_timeout_s: float, agent_timeout_s: float = AGENT_TIMEOUT_S) -> float:
    """The most a step of `phase` is expected to need: the agent's time limit plus one gate for red, green and single;
    a verification round runs several gates and its judges, so four gates."""
    if phase == "verify":
        return 4 * gates_timeout_s
    return agent_timeout_s + gates_timeout_s


def estimate_s(phase: str, recorded: Sequence[float], cap: float, *, fallback: Sequence[float] = ()) -> float:
    """The step's estimate: the longest measure of its phase (this run's, then the unit's `recorded` ones), at least
    `FLOOR_S` and at most `cap`. With no measure of the phase, the longest of any phase: this run's, then the
    `fallback` records (the unit's recorded steps of every phase)."""
    now = current()
    steps = now.steps if now is not None else {}
    own = max(steps.get(phase, 0.0), max(recorded, default=0.0))
    if own <= 0:
        own = max(steps.values(), default=0.0)
    if own <= 0:
        own = max(fallback, default=0.0)
    return min(cap, max(float(FLOOR_S), own))


def check_before(
    phase: str,
    task: str | None,
    attempt: int | None,
    round: int | None,  # noqa: A002 - the contract's name
    recorded: Sequence[float],
    stopped_last: bool,
    cap: float,
    *,
    fallback: Sequence[float] = (),
) -> None:
    """Start the step or defer it (D3). A no-op without a deadline. Raises `DeadlineReached("before")` and sets no
    `step` when the step does not fit; otherwise it counts the step and makes it the current one."""
    dl = current()
    if dl is None:
        return
    held = dl.step
    if held is not None:
        if (held.phase, held.task, held.attempt, held.round) == (phase, task, attempt, round):
            return  # the same step, already marked (the top check of `run_task`)
        dl.step = None  # another step's mark: nothing ran in between, so it is ended unrecorded
        dl.started -= 1
    left = dl.remaining_s()
    estimate = estimate_s(phase, recorded, cap, fallback=fallback)
    first = dl.started == 0
    mark = StepMark(phase, task, attempt, round, dl.clock.now(), first, left, estimate)
    if first:
        if left <= 0:
            raise DeadlineReached("before", mark=mark)
    elif left < estimate:
        raise DeadlineReached("before", mark=mark)
    elif stopped_last:
        raise DeadlineReached("before", mark=mark, reason=STOPPED_LAST_REASON)
    dl.started += 1
    dl.step = mark


def end_step() -> float:
    """End the current step: record its length as its phase's measure, clear it, return the seconds (0 if none)."""
    dl = current()
    if dl is None or dl.step is None:
        return 0.0
    mark = dl.step
    seconds = max(0.0, (dl.clock.now() - mark.started_at).total_seconds())
    dl.steps[mark.phase] = max(dl.steps.get(mark.phase, 0.0), seconds)
    dl.step = None
    return seconds
