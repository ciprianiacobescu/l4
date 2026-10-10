"""Pure rules of the M1.3 acceptance protocol (G6): which commits and ledger events belong to the unit under test. The
unit branch lists `main`'s history too, so a rule that reads trailers or `[skip ci]` titles must keep to the unit's own
commits (unit tested over the live shapes of the M1.3 retry, job 5480)."""

import re
from collections.abc import Iterable
from typing import Any


def trailers(message: str) -> dict[str, str]:
    return dict(re.findall(r"^(L4-[A-Za-z-]+): (.*)$", message, re.M))


def _family(unit: str, value: str | None) -> bool:
    """`value` names the unit or one of its fix units (`<unit>-fix-<n>`)."""
    return value is not None and (value == unit or re.fullmatch(re.escape(unit) + r"-fix-\d+", value) is not None)


def tdd_of(commits: Iterable[dict[str, Any]], unit: str, task: str) -> list[str]:
    """The `L4-TDD` values of the unit's own commits for `task`, newest first (as GitLab lists them)."""
    found = []
    for c in commits:
        t = trailers(c["message"])
        if t.get("L4-Unit") == unit and t.get("L4-Task") == task and "L4-TDD" in t:
            found.append(t["L4-TDD"])
    return found


def unit_checkpoints(commits: Iterable[dict[str, Any]], unit: str) -> list[dict[str, Any]]:
    """The harness's `[skip ci]` checkpoints of the unit and its fix units; an operator's `[skip ci]` commit on the base
    branch (no `L4-Unit`) is not one."""
    return [c for c in commits if "[skip ci]" in c["title"] and _family(unit, trailers(c["message"]).get("L4-Unit"))]


def of_type(events: Iterable[dict[str, Any]], event_type: str, /, **where: Any) -> list[dict[str, Any]]:
    """The events of one type whose fields equal `where`; `event_type` is positional, so `kind=` filters a field."""
    return [e for e in events if e["type"] == event_type and all(e.get(k) == v for k, v in where.items())]


def handed_off(events: Iterable[dict[str, Any]], commits: Iterable[dict[str, Any]], name: str) -> bool:
    """A phase change reached `in_review`, or the branch has the hand-off commit; a `pr.updated` record (labels on a
    draft) is no hand-off. The run that hands off leaves its tail (with the `in_review` change) in the lock ref, which
    the API cannot read, so the commit `docs(<name>): hand off to review` is the evidence on the branch."""
    if any(e["type"] == "phase.changed" and e.get("to") == "in_review" for e in events):
        return True
    return any(c["title"] == f"docs({name}): hand off to review" for c in commits)


def parent_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The unit's own events: a fix unit's tasks write into the parent's ledger with a `fix_unit` field."""
    return [e for e in events if not e.get("fix_unit")]


def branch_of_step_1(events: Iterable[dict[str, Any]]) -> str | None:
    """`1A` when round 1 PASSed, `1B` when it ended NEEDS_HUMAN, else None (not ended, or a FAIL: neither branch).
    `fix.spawned` alone cannot tell them apart: in 1B the answers of step 2 spawn the fix unit too."""
    first = next((e["verdict"] for e in events if e["type"] == "verify.verdict" and e.get("round") == 1), None)
    return {"PASS": "1A", "NEEDS_HUMAN": "1B"}.get(first) if first else None
