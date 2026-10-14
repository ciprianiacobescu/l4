"""Plan files on the target and the facts admission needs (openspec/changes/yolo-mode, design D1, D2, D10).

The seam between the plan step (`cycle.py`) and the operator commands (`commands.py`):
- `plan_files(repo)` reads `.l4/plans/*.json` from the working tree (in CI the job checks out the target head), and
  `plan_files_at(git, rev)` reads them from a revision (a laptop command reads `origin/<target>`);
- `unit_infos(...)` builds `UnitInfo` for the plan's units from the providers and their snapshots, without writing
  anything: the intake checks a unit's first run would make (the provider's strict validation and, for OpenSpec, the
  scenario conflicts of L4-ODD-004) run here as reads only;
- `load_context(...)` reads a plan's ledger ref and folds it;
- `held_by(...)`, `holds_of(...)` and `active_on(...)` answer which plan holds a unit and which plan is active
  (design D10, R8): a unit listed in a plan file is held while the file is on the target, whatever the plan's status
  (cancelled included; a completed plan has integrated its units and holds nothing); an invalid file holds the unit
  ids its JSON names; a file that is not a JSON object holds nothing and is returned apart so `l4 plan` and
  `l4 yolo status` can show it.
"""

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from l4.gates.odd import scenario_conflicts
from l4.specs.base import Framework, SpecProvider, UnitRef
from l4.specs.criteria import base_criteria, replaced_requirements
from l4.specs.questions import QuestionStatus
from l4.state.status import UnitSnapshot
from l4.vcs.git import Git
from l4.yolo.model import PLANS_DIR, Plan, PlanInvalid, PlanState, UnitInfo, load_plan

log = logging.getLogger(__name__)

FINAL = frozenset({"cancelled", "completed"})  # statuses no command changes any more
RELEASES = "completed"  # the one status that holds no unit: the plan integrated them all (a cancelled plan still holds)
ACTIVATED = ("active", "waiting", "stopped")  # activated and not final: these plans win a unit two files list
INVALID = "invalid"  # the status shown for a plan file that is not a plan and has no ledger


@dataclass(frozen=True)
class PlanFile:
    plan_id: str  # the file stem; equal to the plan's `plan_id` when the file is valid
    path: str  # repository-relative, e.g. `.l4/plans/p1.json`
    text: str
    plan: Plan | None
    invalid: PlanInvalid | None


def _plan_file(path: str, text: str) -> PlanFile:
    loaded = load_plan(text, file_name=path)
    stem = PurePosixPath(path).stem
    if isinstance(loaded, PlanInvalid):
        return PlanFile(stem, path, text, None, loaded)
    return PlanFile(stem, path, text, loaded, None)


def plan_files(repo: Path) -> list[PlanFile]:
    """The plan files of the working tree, sorted by path. A file that cannot be read as text is a `PlanInvalid`."""
    folder = repo / PLANS_DIR
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = f"{PLANS_DIR}/{path.name}"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            found.append(PlanFile(path.stem, rel, "", None, PlanInvalid((f"{path.stem}: unreadable: {exc}",))))
            continue
        found.append(_plan_file(rel, text))
    return found


def plan_files_at(git: Git, rev: str) -> list[PlanFile]:
    """The plan files of a revision (`git ls-tree` + `git show`), sorted by path; [] when the folder is absent."""
    listing = git.run("ls-tree", "--name-only", f"{rev}:{PLANS_DIR}", check=False)
    if listing.returncode != 0:
        return []
    found = []
    for name in sorted(n for n in listing.stdout.splitlines() if n.endswith(".json")):
        rel = f"{PLANS_DIR}/{name}"
        shown = git.run("show", f"{rev}:{rel}", check=False)
        if shown.returncode != 0:
            continue
        found.append(_plan_file(rel, shown.stdout))
    return found


def _open_questions(snapshot: UnitSnapshot | None) -> tuple[str, ...]:
    if snapshot is None or snapshot.questions is None:
        return ()
    return tuple(q.id for q in snapshot.questions.questions if q.status is QuestionStatus.OPEN)


def intake(provider: SpecProvider, ref: UnitRef, repo: Path) -> tuple[bool, str]:
    """The intake checks of a unit's first run, as reads only: the provider's strict validation (ERROR issues) and, for
    OpenSpec, scenario pairs with the same WHEN and a different THEN (which the first run would turn into questions)."""
    try:
        report = provider.validate(ref, strict=True)
    except Exception as exc:  # noqa: BLE001 - a validation that cannot run is an intake failure, never a crash
        return False, f"validation could not run: {type(exc).__name__}: {exc}"[:300]
    errors = [f"{i.path}{f':{i.line}' if i.line else ''}: {i.message}" for i in report.issues if i.level == "ERROR"]
    if errors:
        return False, "; ".join(errors)[:300]
    if ref.framework is Framework.OPENSPEC:
        try:
            base = base_criteria(repo / "openspec" / "specs")
            conflicts = scenario_conflicts(provider.criteria(ref), base, replaced_requirements(ref.path))
        except Exception as exc:  # noqa: BLE001
            return False, f"scenario check could not run: {type(exc).__name__}: {exc}"[:300]
        if conflicts:
            return False, f"{len(conflicts)} pair(s) of scenarios with the same WHEN and a different THEN"
    return True, ""


def unit_infos(
    repo: Path,
    found: Sequence[tuple[SpecProvider, UnitSnapshot]],
    wanted: Iterable[str],
    *,
    check_intake: bool = True,
) -> dict[str, UnitInfo]:
    """`UnitInfo` for each wanted unit id that a provider knows (from `discover`'s result); a unit id no provider
    knows is left out, so admission reports it as `unknown_unit`."""
    by_id = {s.ref.id: (p, s) for p, s in found}
    infos: dict[str, UnitInfo] = {}
    for unit_id in wanted:
        if unit_id not in by_id:
            continue
        provider, snapshot = by_id[unit_id]
        ok, detail = intake(provider, snapshot.ref, repo) if check_intake else (True, "")
        try:
            folder = str(snapshot.ref.path.resolve().relative_to(repo.resolve()))
        except ValueError:
            folder = str(snapshot.ref.path)
        infos[unit_id] = UnitInfo(
            id=unit_id,
            folder=folder,
            open_questions=_open_questions(snapshot),
            phase=snapshot.state.phase,
            intake_ok=ok,
            intake_detail=detail,
        )
    return infos


def readable_unit_ids(text: str) -> list[str] | None:
    """The unit ids a plan file names in `batches[].units[].id`, in file order, whatever else is wrong with it (R8),
    without the ids its `exclude` names (D15: an excluded unit is not held); None when the text is not a JSON object.
    Entries of the wrong shape are skipped."""
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    ids: list[str] = []
    batches = raw.get("batches")
    for batch in batches if isinstance(batches, list) else []:
        units = batch.get("units") if isinstance(batch, dict) else None
        for unit in units if isinstance(units, list) else []:
            unit_id = unit.get("id") if isinstance(unit, dict) else None
            if isinstance(unit_id, str) and unit_id and unit_id not in ids:
                ids.append(unit_id)
    excluded = raw.get("exclude")
    left_out = {x.get("id") for x in excluded if isinstance(x, dict)} if isinstance(excluded, list) else set()
    return [i for i in ids if i not in left_out]


@dataclass(frozen=True)
class PlanHolds:
    held: dict[str, tuple[str, str]]  # unit id -> (plan id, plan status)
    unreadable: list[PlanFile]  # the files that are not a JSON object: they hold nothing


def holds_of(states: Mapping[str, PlanState], files: Sequence[PlanFile]) -> PlanHolds:
    """unit id -> (plan id, plan status) for every unit listed in a plan file (design D10, R8), and the files that
    hold nothing because they are not JSON. A completed plan holds nothing (SCN-YOLO-28). The status is the plan's
    own (`new` without a ledger, `invalid` for a file that is not a plan and has no ledger). A unit listed in a
    plan's `exclude` is not held by it (D15). A unit listed by two plans is held by the plan that is active, waiting
    or stopped when there is one (review #15), else by the first file in path order; admission of the other plan
    refuses it (`held_by_other_plan`)."""
    candidates: dict[str, list[tuple[str, str]]] = {}  # unit id -> (plan id, status) of each file that lists it
    unreadable: list[PlanFile] = []
    for file in files:
        if file.plan is not None:
            left_out = {x.id for x in file.plan.exclude}
            unit_ids: list[str] | None = [u for u in file.plan.unit_ids() if u not in left_out]
            fallback = "new"
        else:
            unit_ids = readable_unit_ids(file.text)
            fallback = INVALID
        if unit_ids is None:
            unreadable.append(file)
            continue
        status = states[file.plan_id].status if file.plan_id in states else fallback
        if status == RELEASES:
            continue
        for unit_id in unit_ids:
            candidates.setdefault(unit_id, []).append((file.plan_id, status))
    # review #15: the plan that is activated and not final holds the unit, whatever its path; else the first file
    held = {
        unit_id: next((c for c in holders if c[1] in ACTIVATED), holders[0]) for unit_id, holders in candidates.items()
    }
    return PlanHolds(held, unreadable)


def held_by(states: Mapping[str, PlanState], files: Sequence[PlanFile]) -> dict[str, tuple[str, str]]:
    """`holds_of(...).held`: unit id -> (plan id, plan status) for every unit a plan file lists (design D10, R8)."""
    return holds_of(states, files).held


def active_on(states: Mapping[str, PlanState], files: Sequence[PlanFile], target: str) -> PlanFile | None:
    """The plan file whose plan is active, waiting or stopped on `target` (at most one may be activated per target);
    None when there is none. A stopped plan still counts: it holds its units and blocks a second activation."""
    for file in files:
        if file.plan is None or file.plan.target != target:
            continue
        if file.plan_id in states and states[file.plan_id].status in ("active", "waiting", "stopped"):
            return file
    return None
