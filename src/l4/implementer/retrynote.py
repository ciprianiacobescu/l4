"""A person's note on `l4 retry` / `l4 resume`, found again for the step of the task that halted (escalate-and-note
D10, D11). Contract only: the behaviour is task 1.5."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetryNote:
    event: str  # `unit.retried` or `unit.resumed`
    ts: str
    text: str


def retry_note(events: Sequence[Any], task: str, fix_unit: str | None) -> RetryNote | None:
    """The note that reaches a step of `task` (of `fix_unit`, or of the unit itself when None), else None."""
    raise NotImplementedError("escalate-and-note 1.5")


def note_block(note: RetryNote) -> tuple[str, str]:
    """The (title, block) pair of the prompt section for `note`."""
    raise NotImplementedError("escalate-and-note 1.5")
