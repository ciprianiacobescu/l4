"""The marker of a follow-up unit (`<unit>/.l4/followup.json`, `l4/followup@1`; L4-FBK-010, design D11) and the naming.

A follow-up `<parent>-followup-<n>` is a unit of its own that the harness makes for feedback a person gave on a
`merged` unit. Unlike a fix unit it has its own branch, ledger, phase and pull request, so it carries this marker and
not `.l4/fix.json`. The marker says which unit it follows, which items of the parent's `feedback.md` it took (id and
content hash, the dedupe key of the next base run) and which of its findings are chores (the same lists a fix unit's
marker keeps, so the implementer runs a refactor task without a red test).

`feedback_home` is the one place that answers "where is the `feedback.md` this unit judges": its own folder, or for a
follow-up the parent's folder in the same tree, where the harness sets the items `taken` and later `addressed`.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file

MARKER_SCHEMA = "l4/followup@1"
MARKER_PATH = (".l4", "followup.json")
MAX_MARKER_BYTES = 64 * 1024
_NAME = re.compile(r"^(?P<parent>.+)-followup-(?P<n>[1-9][0-9]*)$")
_DATED = re.compile(r"^\d{4}-\d\d-\d\d-(?P<name>.+)$")


@dataclass(frozen=True)
class FollowUpMarker:
    parent: str  # the parent's unit id, e.g. `kiro:add-reorder-quantity`
    items: tuple[tuple[str, str], ...]  # (item id, content sha256) of the parent's feedback.md that it took
    chores: tuple[str, ...] = ()  # the finding ids whose tasks run in a single phase (as `FixMarker.chores`)
    test_chores: tuple[str, ...] = ()
    refactors: tuple[str, ...] = ()


def follow_up_name(parent: str, n: int) -> str:
    return f"{parent}-followup-{n}"


def split_follow_up_name(name: str) -> tuple[str, int] | None:
    """(parent name, ordinal) for a name of the form `<parent>-followup-<n>`."""
    match = _NAME.match(name)
    return (match.group("parent"), int(match.group("n"))) if match else None


def write_follow_up_marker(unit_dir: Path, marker: FollowUpMarker) -> None:
    target = unit_dir.joinpath(*MARKER_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": MARKER_SCHEMA, "parent": marker.parent,
        "items": [{"id": i, "sha256": sha} for i, sha in marker.items],
        "chores": list(marker.chores), "test_chores": list(marker.test_chores), "refactors": list(marker.refactors),
    }  # fmt: skip
    atomic_write_bytes(target, (json.dumps(body, indent=2) + "\n").encode("utf-8"))


def parse_follow_up_marker(raw: bytes) -> FollowUpMarker | None:
    """None for anything that is not a marker of this schema. Repo content: nothing here may raise."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != MARKER_SCHEMA or not isinstance(data.get("parent"), str):
        return None
    items = tuple(
        (i["id"], i["sha256"])
        for i in (data.get("items") if isinstance(data.get("items"), list) else [])
        if isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("sha256"), str)
    )
    return FollowUpMarker(
        data["parent"], items, _strings(data.get("chores")), _strings(data.get("test_chores")),
        _strings(data.get("refactors")),
    )  # fmt: skip


def read_follow_up_marker(unit_dir: Path) -> FollowUpMarker | None:
    try:
        raw = read_regular_file(unit_dir.joinpath(*MARKER_PATH), limit=MAX_MARKER_BYTES)
    except (FileNotFoundError, UnsafeFile, OSError):
        return None
    return parse_follow_up_marker(raw)


def _strings(value: object) -> tuple[str, ...]:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def parent_folder(unit_dir: Path, marker: FollowUpMarker) -> Path | None:
    """The parent's folder in the follow-up's own tree: a sibling folder (a Kiro spec, an OpenSpec change that is not
    archived yet), else the newest `archive/<date>-<name>/` of the changes folder. None when the tree holds neither."""
    name = marker.parent.partition(":")[2]
    here = unit_dir.parent
    home = here.parent if here.name == "archive" else here  # a follow-up that is itself archived
    if (sibling := home / name).is_dir() and not sibling.is_symlink():
        return sibling
    archive = home / "archive"
    if not archive.is_dir() or archive.is_symlink():
        return None
    dated = sorted(
        d for d in archive.iterdir()
        if d.is_dir() and not d.is_symlink() and (m := _DATED.match(d.name)) is not None and m.group("name") == name
    )  # fmt: skip
    return dated[-1] if dated else None


def feedback_home(unit_dir: Path) -> Path:
    """The folder whose `feedback.md` the unit takes, judges and marks: its own, except for a follow-up, whose items
    are the parent's (the parent's file as it is on the follow-up's branch)."""
    marker = read_follow_up_marker(unit_dir)
    if marker is None:
        return unit_dir
    return parent_folder(unit_dir, marker) or unit_dir
