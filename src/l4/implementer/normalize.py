"""Finding and normalizing the implementer's result object (result-contract D3, D4)."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from l4.agents.base import RunResult

CUT_MARKER = "[cut by L4: {n} characters removed]"
NO_SUMMARY = "(no summary: the agent wrote none)"
SCAN_CHARS = 200_000
_SCAN_WORK = 4_000_000  # [G] characters that failed decodes may read in all: a text of nested openers is quadratic


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
    """The last result-like JSON object of the agent's text (D3): scan the last `SCAN_CHARS` characters from the
    start, try a decode at each `{`, keep a decoded object with a top-level `status` or `summary` key and go on after
    its end (so what it holds is never taken alone), else go on at the next character."""
    text = text[-SCAN_CHARS:]
    decoder = json.JSONDecoder()
    last: Found | None = None
    at = work = 0
    while (start := text.find("{", at)) >= 0 and work <= _SCAN_WORK:
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError as exc:
            work += exc.pos - start + 1
            at = start + 1
            continue
        except RecursionError:
            work += len(text) - start
            at = start + 1
            continue
        if isinstance(obj, dict) and ("status" in obj or "summary" in obj):
            last = Found(obj, "final_message", text[start:end])
            at = end
        else:
            at = start + 1
    return last


def find_result(run: RunResult) -> Found | None:
    """Where the result is (D3), in order: the delivered result, the object a native schema refused, the last
    result-like object of the final text. Never a file of the worktree or any other path. A run that is not `ok` and
    has no `result_problem` did not finish: not a caller's case."""
    if run.status == "ok" and run.structured is not None:
        return Found(run.structured, "result")
    if run.status != "ok" and run.result_problem is None:
        return None
    if run.result_problem == "invalid" and run.rejected is not None:
        return Found(run.rejected, "result")
    return last_result_object(run.final_text or "")


def normalize(found: Found, facts: StepFacts) -> Normalized:
    raise NotImplementedError("result-contract 1.2")
