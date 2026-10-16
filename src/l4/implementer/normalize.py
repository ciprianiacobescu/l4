"""Finding and normalizing the implementer's result object (result-contract D3, D4). Contract only: the functions
raise `NotImplementedError` until wave 1."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from l4.agents.base import RunResult

CUT_MARKER = "[cut by L4: {n} characters removed]"
NO_SUMMARY = "(no summary: the agent wrote none)"
SCAN_CHARS = 200_000


@dataclass(frozen=True)
class StepFacts:
    """What L4 knows of the step, so the agent need not say it."""

    phase: str
    task: str | None
    changed_files: Sequence[str]
    last_message: str | None


@dataclass(frozen=True)
class Fix:
    """One repair, as `result.normalized` records it. Never holds text of the agent."""

    field: str
    fix: Literal["set", "replaced", "renamed", "dropped", "cut"]
    from_: str | None = None  # a source or key name
    to: str | None = None  # an allowed status
    was: str | None = None  # a phase name
    count: int | None = None
    length: int | None = None

    def as_event(self) -> dict[str, Any]:
        """The fix as an event dict: leaves out what is `None`, writes `from_` as `from`."""
        data: dict[str, Any] = {"field": self.field, "fix": self.fix, "from": self.from_, "to": self.to}
        data.update(was=self.was, count=self.count, length=self.length)
        return {k: v for k, v in data.items() if v is not None}


@dataclass(frozen=True)
class Found:
    obj: dict[str, Any]
    source: Literal["result", "final_message"]
    text: str | None = None  # the JSON text when the object came from the final text


@dataclass(frozen=True)
class Normalized:
    obj: dict[str, Any]
    fixes: list[Fix] = field(default_factory=list)


def last_result_object(text: str) -> Found | None:
    raise NotImplementedError("result-contract 1.1")


def find_result(run: RunResult) -> Found | None:
    raise NotImplementedError("result-contract 1.1")


def normalize(found: Found, facts: StepFacts) -> Normalized:
    raise NotImplementedError("result-contract 1.2")
