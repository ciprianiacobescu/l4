"""`l4 yolo draft`: scaffold or update a plan file from the specs of the working tree (design D15, L4-YOLO-018).

Pure text work: the units the providers found and the plan files of the working tree go in, the new file text and what
was added come out. It never orders units and never adds a `depends_on`: an ordering is a claim about the specs that a
person or an agent makes with evidence. The command (`commands.run_draft`) does the reading and the one write.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from l4.specs.fixmark import split_fix_name
from l4.specs.followup import split_follow_up_name
from l4.yolo.admit import FINISHED_PHASES
from l4.yolo.model import SCHEMA, MergeMode
from l4.yolo.plans import PlanFile, listed_ids

BATCH = "unplanned"


@dataclass(frozen=True)
class Found:
    """One unit a spec provider found in the working tree, and its phase."""

    id: str
    phase: str | None


@dataclass(frozen=True)
class Draft:
    text: str | None  # the new file; None when an update has nothing to add (the file stays as it is)
    added: tuple[str, ...] = ()  # unit ids put into batch `unplanned`
    excluded: tuple[tuple[str, str], ...] = ()  # (unit id, reason) put into `exclude`
    gone: tuple[str, ...] = ()  # listed in the file, found by no provider (kept)


def derived_parents(unit_id: str) -> list[str]:
    """The unit ids a derived unit is named after, nearest first: `openspec:a-fix-2` -> [`openspec:a`]; a unit that is
    no fix or follow-up unit has none. The parent of a derived unit may itself be derived."""
    framework, _, name = unit_id.partition(":")
    parents: list[str] = []
    while True:
        split = split_fix_name(name) or split_follow_up_name(name)
        if split is None:
            return parents
        name = split[0]
        parents.append(f"{framework}:{name}")


def unlisted(found: Iterable[Found], files: Sequence[PlanFile]) -> list[Found]:
    """The found units that no plan file lists (planned or excluded) and that are not derived units whose parent is
    listed, by this draft's own additions too; in id order."""
    listed: set[str] = set()
    for file in files:
        listed |= listed_ids(file)
    todo = sorted((u for u in found if u.id not in listed), key=lambda u: u.id)
    # a parent this draft adds covers its derived units, so that only the parent is added
    adding = {u.id for u in todo if not derived_parents(u.id)}
    return [u for u in todo if not any(parent in listed | adding for parent in derived_parents(u.id))]


def _split(units: Iterable[Found]) -> tuple[list[str], list[tuple[str, str]]]:
    open_ids, finished = [], []
    for unit in units:
        if unit.phase in FINISHED_PHASES:
            finished.append((unit.id, f"already {unit.phase}"))
        else:
            open_ids.append(unit.id)
    return open_ids, finished


def _entry(unit_id: str) -> dict[str, object]:
    return {"id": unit_id, "depends_on": []}


def dump(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def new_draft(
    plan_id: str, *, target: str, merge: MergeMode, found: Iterable[Found], files: Sequence[PlanFile]
) -> Draft:
    """A new plan file: unplanned units in batch `unplanned`, no dependency; finished ones in `exclude`."""
    open_ids, finished = _split(unlisted(found, files))
    data: dict[str, object] = {
        "schema": SCHEMA, "plan_id": plan_id, "target": target, "merge": merge,
        "batches": [{"id": BATCH, "depends_on": [], "units": [_entry(u) for u in open_ids]}],
    }  # fmt: skip
    if finished:
        data["exclude"] = [{"id": u, "reason": why} for u, why in finished]
    return Draft(dump(data), tuple(open_ids), tuple(finished))


def update_draft(data: dict[str, object], found: Iterable[Found], files: Sequence[PlanFile], own: PlanFile) -> Draft:
    """The plan file `data` (loaded as a dict, so that its key order and every other value survive) with the new units
    appended: to batch `unplanned` (created last when missing) or to `exclude` (created last when missing). Listed
    units that no provider finds are reported in `gone` and kept."""
    seen = list(found)
    here = {u.id for u in seen}
    gone = tuple(sorted(listed_ids(own) - here))
    open_ids, finished = _split(unlisted(seen, files))
    if not open_ids and not finished:
        return Draft(None, gone=gone)
    if open_ids:
        batches = data.setdefault("batches", [])
        assert isinstance(batches, list)
        target = next((b for b in batches if isinstance(b, dict) and b.get("id") == BATCH), None)
        if target is None:
            target = {"id": BATCH, "depends_on": [], "units": []}
            batches.append(target)
        target.setdefault("units", []).extend(_entry(u) for u in open_ids)
    if finished:
        data.setdefault("exclude", [])
        assert isinstance(data["exclude"], list)
        data["exclude"].extend({"id": u, "reason": why} for u, why in finished)
    return Draft(dump(data), tuple(open_ids), tuple(finished), gone)
