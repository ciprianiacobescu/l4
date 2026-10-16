"""A person's note on `l4 retry` / `l4 resume`, found again for the step of the task that halted (escalate-and-note
D10, D11, D12). The note is person-written text that reaches an LLM prompt: it is redacted, cut at 300 characters
and wrapped in a data block that defuses any `l4:data` tag."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from l4.implementer.prompt import data_block
from l4.state.ledger import TS_FORMAT

NOTE_EVENTS = ("unit.retried", "unit.resumed")
MAX_NOTE = 300


@dataclass(frozen=True)
class RetryNote:
    event: str  # `unit.retried` or `unit.resumed`
    ts: str
    text: str


def _bound(text: str, redact: Callable[[str], str] | None) -> str:
    """Redacted first, then cut: a cut must not leave half a secret that the redactor no longer recognises."""
    return (redact(text) if redact is not None else text).strip()[:MAX_NOTE]


def retry_note(
    events: Sequence[Any], task: str, fix_unit: str | None, *, redact: Callable[[str], str] | None = None
) -> RetryNote | None:
    """The note that reaches a step of `task` (of `fix_unit`, or of the unit itself when None), else None."""
    latest = None
    for event in events:
        if event.type in NOTE_EVENTS and event.data.get("note_task"):
            latest = event
    if latest is None or latest.data["note_task"] != task or latest.data.get("note_fix_unit") != fix_unit:
        return None
    for event in events[events.index(latest) + 1 :]:
        if event.type == "unit.restarted":
            return None
        if event.type == "task.done" and event.data.get("task") == task and event.data.get("fix_unit") == fix_unit:
            return None
    reason = latest.data.get("reason")
    if not isinstance(reason, str):
        return None
    text = _bound(reason, redact)
    if not text:
        return None
    return RetryNote(latest.type, latest.ts.strftime(TS_FORMAT), text)


def note_block(note: RetryNote, *, redact: Callable[[str], str] | None = None) -> tuple[str, str]:
    """The (title, block) pair of the prompt section for `note`."""
    text = _bound(note.text, redact)
    return "a person's note", data_block("retry note", "A person's note on this retry: " + text)
