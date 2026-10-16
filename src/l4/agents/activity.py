"""The agent's liveness during one step (SPEC L4-IMP-023, L4-IMP-024, L4-FAC-012): what a stream line shows about
tool calls, the heartbeat line, and the stall rule's view of open calls. Contract only: behaviour lands in wave 1."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Signal:
    kind: Literal["start", "end", "call"]
    id: str | None = None


StreamReader = Callable[[str], tuple[Signal, ...]]


@dataclass(frozen=True)
class Beat:
    elapsed_s: float
    tool_calls: int
    since_last_s: float
    open_calls: int
    open_for_s: float
    counts: bool  # False: no reader, so only `elapsed_s` is known


def ago(seconds: float) -> str:
    """`0s`..`59s`, `1m`..`59m` (whole minutes, rounded down), then `1h 0m` (design D3)."""
    whole = max(0, int(seconds))
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        return f"{whole // 60}m"
    return f"{whole // 3600}h {whole % 3600 // 60}m"


class ActivityWatch:
    def __init__(
        self, heartbeat_s: float, on_beat: Callable[[Beat], None], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.heartbeat_s = heartbeat_s
        self.on_beat = on_beat
        self.clock = clock
        self.stopped_idle_s: float | None = None

    def start(self, now: float, reader: StreamReader | None) -> None:
        raise NotImplementedError

    def line(self, text: str) -> None:
        raise NotImplementedError

    def tick(self, now: float) -> None:
        raise NotImplementedError

    def has_open_call(self) -> bool:
        raise NotImplementedError

    def snapshot(self, now: float) -> Beat:
        raise NotImplementedError


def opencode_signals(line: str) -> tuple[Signal, ...]:
    raise NotImplementedError


def claude_code_signals(line: str) -> tuple[Signal, ...]:
    raise NotImplementedError


def codex_signals(line: str) -> tuple[Signal, ...]:
    raise NotImplementedError


def kiro_signals(line: str) -> tuple[Signal, ...]:
    raise NotImplementedError
