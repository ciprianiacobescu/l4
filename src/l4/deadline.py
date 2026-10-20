"""The run's soft deadline (L4-IMP-012, L4-IMP-066 to L4-IMP-069): one process-wide object that `l4 run` arms when the
CI job's budget is known. A leaf module (it imports nothing from `l4`), like `l4.cancel`: every process a unit starts
(`ProcRunner._wait`) and every step (`check_before`) reads the same state, so no event is threaded through a
constructor.

`DeadlineReached` is a `BaseException`, like `RunCancelled`: no `except Exception` of a part of a step (the verifier
ladder has several) turns a stop into a failure. `Orchestrator.run_unit` is the one place that catches it."""

import contextlib
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

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
        self.fix_unit: str | None = None  # set by `run_task` of a fix unit's workbench: the stop belongs to that unit


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


# --- what the callers share: the records, the check with its inputs, the timing of a step ------------------------


def recorded_seconds(events: Sequence[Any], phase: str | None = None) -> list[float]:
    """The unit's last `HISTORY` measures of `phase` (every phase when None), oldest first: the `seconds` of its
    `step.timed` events and the `ran_s` of its stops (`deadline.reached{when: during}`, a lower bound of a step's
    length). `events` are ledger events (`.type`, `.data`)."""
    found: list[float] = []
    for event in events:
        if phase is not None and event.data.get("phase") != phase:
            continue
        if event.type == "step.timed":
            value = event.data.get("seconds")
        elif event.type == "deadline.reached" and event.data.get("when") == "during":
            value = event.data.get("ran_s")
        else:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            found.append(float(value))
    return found[-HISTORY:]


def check(
    phase: str,
    task: str | None,
    attempt: int | None,
    round: int | None,  # noqa: A002 - the contract's name
    *,
    read_events: Callable[[], Sequence[Any]],
    gates_timeout_s: float,
    stopped_last: bool = False,
    fix_unit: str | None = None,
) -> None:
    """`check_before` with its inputs read from the unit's events (only when a deadline is armed): the records of the
    phase, the records of every phase as the fallback, the phase's cap, and whether the newest event of this task and
    phase in its window is a stop (`stopped_last`, D7: it then starts only as the first step of a run)."""
    if current() is None:
        return
    events = read_events()
    check_before(
        phase, task, attempt, round, recorded_seconds(events, phase),
        stopped_last or last_is_stop(events, task, phase, fix_unit=fix_unit), cap_s(phase, gates_timeout_s),
        fallback=recorded_seconds(events),
    )  # fmt: skip


# --- the window of a task and phase: the count of stops, "first only after a stop" (D7, L4-IMP-071) -----------------

COMMITS = (
    "task.red_committed",
    "task.green_committed",
    "task.done",
)  # a checkpoint of the task: its window starts anew
RESETS = ("unit.retried", "unit.resumed", "unit.restarted")  # a person's retry, resume or restart: every window does


def window(events: Sequence[Any], task: str | None, *, fix_unit: str | None = None) -> list[Any]:
    """The events after the last checkpoint of `task` (`COMMITS`, of the same fix unit) or after the last retry, resume
    or restart. `task` None is a verification round: its boundary is the last `verify.verdict`."""
    start = 0
    for index, event in enumerate(events):
        if event.type in RESETS:
            start = index + 1
        elif task is None:
            if event.type == "verify.verdict":
                start = index + 1
        elif event.type in COMMITS and event.data.get("task") == task and event.data.get("fix_unit") == fix_unit:
            start = index + 1
    return list(events[start:])


def _of_step(event: Any, task: str | None, phase: str, fix_unit: str | None) -> bool:
    data = event.data
    return data.get("phase") == phase and data.get("task") == task and data.get("fix_unit") == fix_unit


def is_counted(data: Mapping[str, Any]) -> bool:
    """A stop counts toward `deadline_repeated` when the step was the first of its run, or started with at least its
    estimate left. A step not started, or a stop with no step, never does."""
    left, estimate = data.get("left_at_start_s"), data.get("estimate_s")
    fits = isinstance(left, (int, float)) and isinstance(estimate, (int, float)) and left >= estimate
    return bool(data.get("first") is True or fits)


def stops(events: Sequence[Any], task: str | None, phase: str, *, fix_unit: str | None = None) -> list[Any]:
    """The counted stops (`deadline.reached{when: during}`) of `task` and `phase` in their window."""
    return [
        e for e in window(events, task, fix_unit=fix_unit)
        if e.type == "deadline.reached" and e.data.get("when") == "during" and _of_step(e, task, phase, fix_unit)
        and is_counted(e.data)
    ]  # fmt: skip


def last_is_stop(events: Sequence[Any], task: str | None, phase: str, *, fix_unit: str | None = None) -> bool:
    """The newest event of `task` and `phase` in the window, among the stops and the `step.timed` records, is a stop
    (any stop, counted or not): the step starts only as the first step of a run until an attempt of it ran to its
    end."""
    for event in reversed(window(events, task, fix_unit=fix_unit)):
        if not _of_step(event, task, phase, fix_unit):
            continue
        if event.type == "step.timed":
            return False
        if event.type == "deadline.reached" and event.data.get("when") == "during":
            return True
    return False


def finish_step() -> dict[str, Any] | None:
    """End the current step and return the fields of its `step.timed` event (None when no step is current)."""
    dl = current()
    mark = dl.step if dl is not None else None
    if mark is None:
        return None
    seconds = end_step()
    fields: dict[str, Any] = {
        "phase": mark.phase, "task": mark.task, "attempt": mark.attempt, "round": mark.round,
        "seconds": round(seconds, 1),
    }  # fmt: skip
    return {key: value for key, value in fields.items() if value is not None}


def _emit_timed(emit: Callable[..., None]) -> None:
    if (fields := finish_step()) is not None:
        emit("step.timed", **fields)


@contextmanager
def timed(emit: Callable[..., None]) -> Iterator[None]:
    """Around one step: when it returns or raises anything but `DeadlineReached`, the step ends and `step.timed` is
    recorded. A stop keeps the mark: `Orchestrator._defer` reads it to fill `deadline.reached`."""
    try:
        yield
    except DeadlineReached:
        raise
    except BaseException:
        with contextlib.suppress(Exception):  # the original error is the one to report
            _emit_timed(emit)
        raise
    _emit_timed(emit)


def release_task(emit: Callable[..., None], task: str) -> None:
    """A mark of `task` that no step ended (a resume that did its setup and found nothing left to run) ends recorded."""
    dl = current()
    if dl is not None and dl.step is not None and dl.step.task == task:
        _emit_timed(emit)
