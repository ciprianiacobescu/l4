"""The GitHub job summary (L4-OBS-005): one Markdown list line for each task that ends.

A ledger observer. It writes ids, codes, numbers and the profile name only; never a note, a reason or any text of an
agent or of a person. GitLab has no job summary file, so no observer is made there.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from l4.agents.activity import ago
from l4.state.ledger import LedgerEvent

log = logging.getLogger(__name__)

_Key = tuple[str | None, str | None]


class StepSummary:
    """Callable `LedgerEvent -> None`; appends to the file at `path` and never raises."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._steps: dict[_Key, int] = {}
        self._agents: dict[_Key, str] = {}
        self._started: dict[_Key, datetime] = {}
        self._warned = False

    def __call__(self, event: LedgerEvent) -> None:
        try:
            line = self._line(event)
        except Exception:  # an observer must never stop the run
            log.debug("step summary: could not read %s", event.type, exc_info=True)
            return
        if line:
            self._append(line)

    def _line(self, e: LedgerEvent) -> str | None:
        d = e.data
        fix = _text(d.get("fix_unit"))
        key: _Key = (fix, _text(d.get("task")))
        if e.type == "task.started":
            self._started[key] = e.ts
            return None
        if e.type == "step.started":
            self._steps[key] = self._steps.get(key, 0) + 1
            if d.get("agent"):
                self._agents[key] = str(d["agent"])
            return None
        who = f"{e.unit} [{fix}]" if fix else e.unit
        task = f" task {key[1]}" if key[1] else ""
        if e.type == "task.red_ok" and d.get("tdd") == "already-satisfied":
            return f"- {who}{task}: already satisfied (no green step)"
        if e.type == "check.inconclusive":  # ids and codes only: never the reason (L4-OBS-005)
            return (
                f"- {who}{task}: held ({_text(d.get('check')) or 'a'} check inconclusive, {_text(d.get('question'))})"
            )
        if e.type == "breaker.tripped":
            return f"- {who}{task}: halted ({_text(d.get('reason')) or 'unknown'})"
        if e.type == "task.done":
            if d.get("tdd") == "already-satisfied":
                return None  # `task.red_ok` already wrote the line
            if d.get("tdd") == "already-done" or d.get("closed"):
                return f"- {who}{task}: done (closed with no open required task)"
            n = self._steps.get(key, 0)
            started = self._started.get(key)
            took = ago((e.ts - started).total_seconds()) if started else "?"
            profile = self._agents.get(key, "?")
            return f"- {who}{task}: done ({n} attempts, {profile}, {took})"
        return None

    def _append(self, line: str) -> None:
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            if not self._warned:
                self._warned = True
                log.warning("job summary not written (%s): %s", self._path, exc.strerror or type(exc).__name__)


def _text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def step_summary_for(environ: Mapping[str, str]) -> StepSummary | None:
    """A `StepSummary` only for `GITHUB_ACTIONS=true` and a set `GITHUB_STEP_SUMMARY`."""
    path = environ.get("GITHUB_STEP_SUMMARY")
    if environ.get("GITHUB_ACTIONS") == "true" and path:
        return StepSummary(path)
    return None
