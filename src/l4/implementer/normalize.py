"""Finding and normalizing the implementer's result object (result-contract D3, D4)."""

import copy
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from l4.agents.base import RunResult
from l4.agents.codex import drop_nulls
from l4.implementer.result import RESULT_SCHEMA

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


# The limits, enums and pattern come from the canonical schema, not from a second copy (D4).
_PROPS: dict[str, Any] = RESULT_SCHEMA["properties"]
_STATUSES: tuple[str, ...] = tuple(_PROPS["status"]["enum"])
_PHASES: tuple[str, ...] = tuple(_PROPS["phase"]["enum"])
_KINDS: tuple[str, ...] = tuple(_PROPS["questions"]["items"]["properties"]["kind"]["enum"])
_MAX_QUESTIONS: int = _PROPS["questions"]["maxItems"]
_CRITERION = re.compile(_PROPS["criteria_ids"]["items"]["pattern"])
_SUMMARY_MAX: int = _PROPS["summary"]["maxLength"]
_NOTES_MAX: int = _PROPS["notes_for_verifier"]["maxLength"]
_REASON_MAX: int = _PROPS["suppressions"]["items"]["properties"]["reason"]["maxLength"]
_ALIASES = (("notes", "notes_for_verifier"), ("suppressions_list", "suppressions"))


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _question(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and isinstance(item.get("context"), str)
        and isinstance(item.get("kind"), str)
        and item["kind"] in _KINDS
    )


def _suppression(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("file"), str)
        and isinstance(item.get("line"), int)
        and not isinstance(item["line"], bool)
        and isinstance(item.get("rule"), str)
        and isinstance(item.get("reason"), str)
    )


def _exemption(value: Any) -> bool:
    return isinstance(value, dict) and ("reason" not in value or isinstance(value["reason"], str))


def _lessons(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict) and all(isinstance(item[key], str) for key in ("text", "scope") if key in item)
        for item in value
    )


def _cut(text: str, limit: int) -> str:
    """`text` within `limit`: its longest start that leaves room for the marker, then the marker (D4 rule 13)."""
    for kept in range(min(len(text), limit), -1, -1):
        marker = CUT_MARKER.format(n=len(text) - kept)
        if kept + len(marker) <= limit:
            return text[:kept] + marker
    return CUT_MARKER.format(n=len(text))[:limit]  # unreachable for a real limit; never longer than the limit


def _aliases(obj: dict[str, Any], fixes: list[Fix]) -> None:
    """Rule 1: an alias key moves to the real key when that is absent, else it is dropped."""
    for alias, real in _ALIASES:
        if alias not in obj:
            continue
        value = obj.pop(alias)
        if real in obj:
            fixes.append(Fix(alias, "dropped"))
        else:
            obj[real] = value
            fixes.append(Fix(real, "renamed", from_=alias))


def _harness_fields(obj: dict[str, Any], facts: StepFacts, fixes: list[Fix]) -> None:
    """Rules 2 to 5: what L4 knows. Setting a field the agent left out, or replacing a valid list, is not a fix."""
    if "phase" in obj and obj["phase"] != facts.phase:
        fixes.append(Fix("phase", "replaced"))
    obj["phase"] = facts.phase
    if facts.task is not None:
        if "task_ids" in obj and obj["task_ids"] != [facts.task]:
            fixes.append(Fix("task_ids", "replaced"))
        obj["task_ids"] = [facts.task]
    elif not (_strings(obj.get("task_ids")) and obj["task_ids"]):  # no task key (not a caller's case): keep the schema
        fixes.append(Fix("task_ids", "replaced"))
        obj["task_ids"] = ["unknown"]
    if "files_changed" in obj and not _strings(obj["files_changed"]):
        fixes.append(Fix("files_changed", "replaced"))
    obj["files_changed"] = list(facts.changed_files)
    if "tests_added" in obj and not _strings(obj["tests_added"]):
        fixes.append(Fix("tests_added", "dropped"))
    obj["tests_added"] = []


def _questions(obj: dict[str, Any], fixes: list[Fix]) -> None:
    """Rule 6: keep the well-formed questions, at most three. Never add, never change a text."""
    if "questions" not in obj:
        return
    given = obj["questions"]
    if not isinstance(given, list):
        del obj["questions"]
        fixes.append(Fix("questions", "dropped"))
        return
    kept = [dict(item) for item in given if _question(item)]
    if len(given) > len(kept):
        fixes.append(Fix("questions", "dropped", count=len(given) - len(kept)))
    for key in ("options", "blocking_tasks"):
        bad = [item for item in kept if key in item and not _strings(item[key])]
        for item in bad:
            del item[key]
        if bad:
            fixes.append(Fix(f"questions.{key}", "dropped", count=len(bad)))
    if len(kept) > _MAX_QUESTIONS:
        fixes.append(Fix("questions", "cut", count=len(kept) - _MAX_QUESTIONS))
    obj["questions"] = kept[:_MAX_QUESTIONS]


def _status(obj: dict[str, Any], fixes: list[Fix]) -> None:
    """Rule 7: an allowed status in another form keeps its value; anything else is `blocked` when a question is
    left, else `done`. A present allowed status is never changed to another."""
    given = obj.get("status")
    folded = given.strip().lower() if isinstance(given, str) else None
    if folded in _STATUSES:
        if given != folded:
            fixes.append(Fix("status", "replaced"))
        obj["status"] = folded
        return
    to = "blocked" if obj.get("questions") else "done"
    obj["status"] = to
    fixes.append(Fix("status", "set", to=to, was=folded if folded in _PHASES else None))


def _summary(obj: dict[str, Any], found: Found, facts: StepFacts, fixes: list[Fix]) -> None:
    """Rule 8: a summary that is not a non-empty string becomes the final message, else the notes, else a fixed text."""
    given = obj.get("summary")
    if isinstance(given, str) and given.strip():
        return
    message = facts.last_message or ""
    if found.source == "final_message" and found.text:
        message = message.replace(found.text, "")
    notes = obj.get("notes_for_verifier")
    if message.strip():
        obj["summary"], source = message.strip(), "final_message"
    elif isinstance(notes, str) and notes.strip():
        obj["summary"], source = notes, "notes_for_verifier"
    else:
        obj["summary"], source = NO_SUMMARY, "none"
    fixes.append(Fix("summary", "set", from_=source))


def _drops(obj: dict[str, Any], fixes: list[Fix]) -> None:
    """Rules 9 to 12: what does not hold the shape is dropped, never repaired."""
    if "notes_for_verifier" in obj and not isinstance(obj["notes_for_verifier"], str):
        del obj["notes_for_verifier"]
        fixes.append(Fix("notes_for_verifier", "dropped"))
    for key, keep in (("criteria_ids", lambda v: isinstance(v, str) and _CRITERION.search(v)),
                      ("suppressions", _suppression)):  # fmt: skip
        if key not in obj:
            continue
        if not isinstance(obj[key], list):
            del obj[key]
            fixes.append(Fix(key, "dropped"))
            continue
        kept = [item for item in obj[key] if keep(item)]
        if len(kept) < len(obj[key]):
            fixes.append(Fix(key, "dropped", count=len(obj[key]) - len(kept)))
        obj[key] = kept
    for key, ok in (("tdd_exemption", _exemption), ("lesson_proposals", _lessons)):
        if key in obj and not ok(obj[key]):
            del obj[key]
            fixes.append(Fix(key, "dropped"))


def _cuts(obj: dict[str, Any], fixes: list[Fix]) -> None:
    """Rule 13: an over-long text keeps its start and ends with the marker, the whole within the limit."""
    for key, limit in (("summary", _SUMMARY_MAX), ("notes_for_verifier", _NOTES_MAX)):
        if isinstance(obj.get(key), str) and len(obj[key]) > limit:
            fixes.append(Fix(key, "cut", length=len(obj[key])))
            obj[key] = _cut(obj[key], limit)
    for item in obj.get("suppressions", []):
        if len(item["reason"]) > _REASON_MAX:
            fixes.append(Fix("suppressions.reason", "cut", length=len(item["reason"])))
            item["reason"] = _cut(item["reason"], _REASON_MAX)


def normalize(found: Found, facts: StepFacts) -> Normalized:
    """The rules 1 to 13 of D4, in order, on a copy of the object. It never adds a question, a criterion, a
    suppression or an exemption, never changes a present allowed status, and touches no file."""
    obj: dict[str, Any] = drop_nulls(copy.deepcopy(found.obj))  # `null` means absent
    fixes: list[Fix] = []
    if found.source == "final_message":  # the agent wrote no usable result file: a person should see that
        fixes.append(Fix(field="result", fix="set", from_="final_message"))
    _aliases(obj, fixes)
    _harness_fields(obj, facts, fixes)
    _questions(obj, fixes)
    _status(obj, fixes)
    _summary(obj, found, facts, fixes)
    _drops(obj, fixes)
    _cuts(obj, fixes)
    return Normalized(obj, fixes)
