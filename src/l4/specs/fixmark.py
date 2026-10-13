"""The marker of a fix unit (`<fix>/.l4/fix.json`, `l4/fix-unit@1`, G5) and the naming of fix units.

A fix unit lives inside its parent's run, branch and ledger (D1). The marker is how a later reader tells it from a unit
of its own: after a merge `main` holds `<parent>-fix-<n>/` with every task done, and the planner must not verify it.
It also records which findings are `[chore]` tasks: that tag comes from the harness, never from the task's text.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file
from l4.specs.followup import read_follow_up_marker

MARKER_SCHEMA = "l4/fix-unit@1"
MARKER_PATH = (".l4", "fix.json")
MAX_MARKER_BYTES = 64 * 1024
_FIX_NAME = re.compile(r"^(?P<parent>.+)-fix-(?P<n>[1-9][0-9]*)$")


@dataclass(frozen=True)
class FixMarker:
    parent: str  # the parent's unit id, e.g. `openspec:add-login`
    round: int  # the ordinal of the fix unit: `<parent>-fix-<round>`
    findings: tuple[str, ...]
    chores: tuple[str, ...]  # the finding ids whose tasks run in a single phase
    test_chores: tuple[str, ...] = ()  # the chores among them that add tests (a coverage hold's); absent: fix chores
    refactors: tuple[str, ...] = ()  # the chores among them that are behaviour-preserving refactors (feedback, D5)
    retakes: tuple[str, ...] = ()  # the feedback tasks among them whose item was taken before (review #8 follow-up)


def fix_name(parent: str, ordinal: int) -> str:
    return f"{parent}-fix-{ordinal}"


def split_fix_name(name: str) -> tuple[str, int] | None:
    """(parent name, ordinal) for a name of the form `<parent>-fix-<n>`."""
    match = _FIX_NAME.match(name)
    return (match.group("parent"), int(match.group("n"))) if match else None


def write_fix_marker(unit_dir: Path, marker: FixMarker) -> None:
    target = unit_dir.joinpath(*MARKER_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": MARKER_SCHEMA, "parent": marker.parent, "round": marker.round, "findings": list(marker.findings),
        "chores": list(marker.chores), "test_chores": list(marker.test_chores),
        "refactors": list(marker.refactors), "retakes": list(marker.retakes),
    }  # fmt: skip
    atomic_write_bytes(target, (json.dumps(body, indent=2) + "\n").encode("utf-8"))


def read_fix_marker(unit_dir: Path) -> FixMarker | None:
    """None when the folder has no readable marker of this schema. Repo content: nothing here may raise."""
    try:
        data = json.loads(read_regular_file(unit_dir.joinpath(*MARKER_PATH), limit=MAX_MARKER_BYTES))
    except (FileNotFoundError, UnsafeFile, ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("schema") != MARKER_SCHEMA:
        return None
    parent, ordinal = data.get("parent"), data.get("round")
    if not isinstance(parent, str) or not isinstance(ordinal, int) or isinstance(ordinal, bool):
        return None
    return FixMarker(
        parent, ordinal, _strings(data.get("findings")), _strings(data.get("chores")),
        _strings(data.get("test_chores")), _strings(data.get("refactors")), _strings(data.get("retakes")),
    )  # fmt: skip


def _strings(value: object) -> tuple[str, ...]:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def task_marker(unit_dir: Path) -> FixMarker | None:
    """The marker that tags a unit's `[chore]` tasks: a fix unit's `.l4/fix.json`, else a follow-up's
    `.l4/followup.json` (its chore lists, read as a fix marker of round 0). Only the first makes a fix unit."""
    if (marker := read_fix_marker(unit_dir)) is not None:
        return marker
    follow = read_follow_up_marker(unit_dir)
    if follow is None:
        return None
    return FixMarker(
        follow.parent, 0, tuple(i for i, _ in follow.items), follow.chores, follow.test_chores, follow.refactors
    )


def chore_kind(unit_dir: Path, title: str) -> Literal["fix", "tests", "refactor"] | None:
    """What kind of chore the task `title` is: `tests` when every chore finding it cites is one of the marker's
    `test_chores` (a coverage hold's task adds tests), `refactor` when every one is one of its `refactors` (feedback:
    the tests stay as they are), `fix` for any other chore (a marker with no `test_chores` key,
    as an older harness wrote it, reads so), None for a task that is no chore."""
    found = chore_findings(unit_dir, title)
    if not found:
        return None
    marker = task_marker(unit_dir)
    assert marker is not None
    if all(f in marker.test_chores for f in found):
        return "tests"
    return "refactor" if all(f in marker.refactors for f in found) else "fix"


def chore_findings(unit_dir: Path, title: str) -> tuple[str, ...]:
    """The finding ids of `title` that the unit's marker tags `[chore]`: a task is one only when the harness said so
    when it wrote the fix unit, never because of what its text says. Empty for a unit that is not a fix unit."""
    marker = task_marker(unit_dir)
    return tuple(f for f in (*marker.chores, *marker.refactors) if f in title) if marker else ()


def refactor_findings(unit_dir: Path, title: str) -> tuple[str, ...]:
    """The finding ids of `title` that the marker tags as refactors. A refactor id is a chore id too."""
    marker = task_marker(unit_dir)
    return tuple(f for f in marker.refactors if f in title) if marker else ()


def chore_retakes(unit_dir: Path, title: str) -> bool:
    """True when every chore finding of the task `title` is one of the marker's `retakes`: its feedback item was taken
    into an earlier fix unit already, so the work may be done and "nothing left to change" completes the task. False
    for a task that is no chore, and for a marker with no `retakes` key (an older harness wrote it)."""
    found = chore_findings(unit_dir, title)
    marker = task_marker(unit_dir)
    return bool(found) and marker is not None and all(f in marker.retakes for f in found)
