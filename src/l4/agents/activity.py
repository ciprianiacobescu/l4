"""The agent's liveness during one step (SPEC L4-IMP-023, L4-IMP-024, L4-FAC-012): what a stream line shows about
tool calls, the heartbeat line, and the stall rule's view of open calls. The watch keeps numbers, times and call ids,
never the text of a stream line."""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

log = logging.getLogger("l4.agents.activity")


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


def beat_text(beat: Beat) -> str:
    """The message tail of the heartbeat line (design D3): counts and times only."""
    text = f"working {ago(beat.elapsed_s)}"
    if not beat.counts:
        return text
    text += f", {beat.tool_calls} tool calls, last activity {ago(beat.since_last_s)} ago"
    if beat.open_calls:
        noun = "tool call" if beat.open_calls == 1 else "tool calls"
        text += f", {beat.open_calls} {noun} open for {ago(beat.open_for_s)}"
    return text


class ActivityWatch:
    def __init__(
        self, heartbeat_s: float, on_beat: Callable[[Beat], None], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.heartbeat_s = heartbeat_s
        self.on_beat = on_beat
        self.clock = clock
        self.stopped_idle_s: float | None = None
        self._lock = threading.Lock()
        self._reader: StreamReader | None = None
        self._started = 0.0
        self._last_line = 0.0
        self._lines = 0
        self._tool_calls = 0
        self._open: dict[str, float] = {}  # call id -> start time
        self._next_beat: float | None = None

    def start(self, now: float, reader: StreamReader | None) -> None:
        with self._lock:
            self._reader = reader
            self._started = self._last_line = now
            self._next_beat = now + self.heartbeat_s if self.heartbeat_s > 0 else None

    def line(self, text: str) -> None:
        at = self.clock()
        reader = self._reader
        try:
            signals = reader(text) if reader else ()
        except Exception:  # a reader never fails a step; the line still counts as activity
            signals = ()
        with self._lock:
            self._last_line = at
            self._lines += 1
            for signal in signals:
                if signal.kind == "end":
                    if signal.id is not None and signal.id in self._open:
                        del self._open[signal.id]
                    else:
                        self._tool_calls += 1
                elif signal.kind == "start":
                    if signal.id is None:
                        self._tool_calls += 1
                    elif signal.id not in self._open:
                        self._tool_calls += 1
                        self._open[signal.id] = at
                else:
                    self._tool_calls += 1

    def tick(self, now: float) -> None:
        with self._lock:
            due = self._next_beat
            if due is None or now < due:
                return
            missed = int((now - due) // self.heartbeat_s) + 1
            self._next_beat = due + missed * self.heartbeat_s
            beat = self._snapshot(now)
        try:
            self.on_beat(beat)
        except Exception as exc:
            log.debug("the heartbeat callback failed: %s", type(exc).__name__)

    def has_open_call(self) -> bool:
        with self._lock:
            return bool(self._open)

    def snapshot(self, now: float) -> Beat:
        with self._lock:
            return self._snapshot(now)

    def _snapshot(self, now: float) -> Beat:
        oldest = min(self._open.values(), default=None)
        return Beat(
            elapsed_s=now - self._started,
            tool_calls=self._tool_calls,
            since_last_s=max(0.0, now - self._last_line),
            open_calls=len(self._open),
            open_for_s=0.0 if oldest is None else max(0.0, now - oldest),
            counts=self._reader is not None,
        )


def _object(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _dicts(value: object) -> list[dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def opencode_signals(line: str) -> tuple[Signal, ...]:
    event = _object(line)
    return (Signal("call"),) if event and event.get("type") == "tool_use" else ()


def claude_code_signals(line: str) -> tuple[Signal, ...]:
    event = _object(line)
    if not event:
        return ()
    kind = event.get("type")
    message = event.get("message")
    if kind not in ("assistant", "user") or not isinstance(message, dict):
        return ()
    signal: Literal["start", "end"] = "start" if kind == "assistant" else "end"
    block_type, key = ("tool_use", "id") if kind == "assistant" else ("tool_result", "tool_use_id")
    return tuple(
        Signal(signal, _id(block.get(key)))
        for block in _dicts(message.get("content"))
        if block.get("type") == block_type
    )


_CODEX_TOOLS = {"command_execution", "file_change", "mcp_tool_call", "web_search"}


def codex_signals(line: str) -> tuple[Signal, ...]:
    event = _object(line)
    if not event or event.get("type") not in ("item.started", "item.completed"):
        return ()
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") not in _CODEX_TOOLS:
        return ()
    return (Signal("start" if event["type"] == "item.started" else "end", _id(item.get("id"))),)


def kiro_signals(line: str) -> tuple[Signal, ...]:
    event = _object(line)
    data = event.get("data") if event and event.get("type") == "sessionUpdate" else None
    update = data.get("update") if isinstance(data, dict) else None
    if not isinstance(update, dict):
        return ()
    call_id = _id(update.get("toolCallId"))
    if update.get("sessionUpdate") == "tool_call":
        return (Signal("start", call_id),)
    if update.get("sessionUpdate") == "tool_call_update" and update.get("status") in ("completed", "failed"):
        return (Signal("end", call_id),)
    return ()
