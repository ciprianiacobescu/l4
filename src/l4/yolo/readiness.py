"""The readiness review of a delivery plan (design D5, requirement L4-YOLO-004, scenarios SCN-YOLO-08 and -09).

The judge role reviews each unit of a plan (its folder at a revision, its plan entry, the units it depends on) and each
batch with more than one unit (all its units' folders together). The prompt is `prompts/readiness.md`, the answer must
satisfy `schemas/readiness.schema.json`, and `review_plan` returns one `Verdict` per unit and per batch.

The call goes through the same machinery as the verifier's judge: the first usable profile of the review's chain
(`roles.plan_judges`, else `roles.judges`; `Factory.for_profile`, probes, cool-downs, the login gate), an
`AgentJudge`, and the judge's permission policy, which allows no tool at all (stricter than read-only): everything the
judge may see is in the prompt, inside `<l4:data>` blocks, and the process runs in an empty scratch folder outside the
repository, in the agent sandbox. There is no implementer to be independent of, so the independence rule of the
verifier does not apply.

Rules decide the verdict whatever the model says: an empty, unparsable or schema-invalid answer is BLOCKED with a
finding `{criterion: "schema", severity: "blocking", text: "schema_invalid: ..."}`, a blocking finding makes the
verdict at least NEEDS_REVISION, and material the size limits cut makes it at least NEEDS_REVISION with a finding that
names what was left out (R9), because the digest freezes content the judge never saw. Structural validity alone never
makes a verdict READY. A usage limit, a timeout and an error of the judge are not verdicts (R9): the review moves the
call to the next judge of its chain (L4-YOLO-096), and a review with a call no judge answered raises `ReviewIncomplete`
(a `JudgeFailed`, so a `RoleUnavailable`), which carries what was answered so that the caller records it and the next
run asks only the rest (L4-YOLO-099). `RoleUnavailable` is raised plain when the chain is empty.

A unit is read on the revision its digest is taken on (`digest.current_unit_ref`, R3): its branch on `origin` when it
has one, else the target. File names, unit ids, batch ids and the plan's own words reach the prompt only inside
`<l4:data>` blocks, defused (R9); the `source` label of a block is escaped too.
"""

import hashlib
import itertools
import json
import re
import shutil
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from l4.agents.base import AgentAdapter, PermissionPolicy, ProbeCtx, RunRequest
from l4.agents.credentials import no_stored_login
from l4.agents.factory import Factory, Selected
from l4.availability.cooldown import AvailabilityStore, SystemClock
from l4.availability.errors import RoleUnavailable
from l4.config.defaults import cache_root
from l4.config.schema import L4Config, duration_seconds
from l4.context import AppContext
from l4.exitcodes import L4Exit
from l4.implementer.prompt import data_block, defuse
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, Msg, StructuredResult
from l4.proc import run_process
from l4.sandbox.base import Sandbox, SandboxSpec, SandboxUnavailable, expand_credential_paths, runner_tmp_paths
from l4.sandbox.env import build_agent_env
from l4.sandbox.home import spec_paths
from l4.sandbox.select import select_sandbox
from l4.schemacheck import validate
from l4.vcs.git import Git
from l4.yolo.admit import FINISHED_PHASES
from l4.yolo.digest import current_unit_ref, is_excluded, unit_digest
from l4.yolo.model import (
    PROFILE_NONE,
    JudgeFailure,
    Plan,
    PlanBatch,
    PlanUnit,
    ReviewResult,
    UnitInfo,
    Verdict,
    VerdictValue,
)

SCHEMA_ID = "l4/yolo-readiness@1"
# 2: the material changed (tasks.md shown with the digest's normalisation and the note on check marks, prerequisite
# units of a batch, review 7). 3: the units already delivered on the target are listed, with the note that a
# dependency on one of them is satisfied. 4: tasks.md shown as it is; prerequisites spec first and their cut is not
# blocking; material keys. A review recorded with another version is stale,
# `plan.reviewed{prompt_version}`; an event without the key counts as 1.
PROMPT_VERSION = 4
MAX_DELIVERED = 60
MAX_CALLS = 2  # the first answer and one repair prompt
DEFAULT_TIMEOUT_S = 900
MAX_FILE_CHARS = 20_000
MAX_FOLDER_CHARS = 80_000
MAX_DEPENDENCY_CHARS = 20_000
MAX_PROBLEM_CHARS = 800
FAILURE_CHARS = 300  # a failure's detail in the record: its first line, cut here (L4-YOLO-096)
MATERIAL_MARK = "<!-- material -->"
ROLE = "judges"
SCRATCH = "yolo"

DigestOf = Callable[[Git, str, str], str]  # (git, rev, unit folder) -> the unit digest (`l4.yolo.digest.unit_digest`)
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")


class JudgeFailed(RoleUnavailable):
    """The judge timed out or failed (R9). Not a verdict: nothing is recorded and the next run tries again. A
    `RoleUnavailable`, so a caller that waits for a judge to be available waits for this too."""

    def __init__(self, detail: str) -> None:
        super().__init__(ROLE, f"judge_error: {detail}")


def _load_schema() -> dict[str, Any]:
    text = resources.files("l4.yolo").joinpath("schemas/readiness.schema.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def _load_template() -> tuple[str, str]:
    text = resources.files("l4.yolo").joinpath("prompts/readiness.md").read_text(encoding="utf-8")
    system, _, material = text.partition(MATERIAL_MARK)
    return system.strip() + "\n", material.strip() + "\n"


READINESS_SCHEMA = _load_schema()
SYSTEM_TEMPLATE, MATERIAL_TEMPLATE = _load_template()
_SLOT = re.compile(r"\{\{([A-Z_]+)\}\}")


def _fill(template: str, values: Mapping[str, str]) -> str:
    """One pass: text that was substituted is never substituted again (a spec may contain `{{...}}`)."""
    return _SLOT.sub(lambda m: values.get(m.group(1), m.group(0)), template)


# --- the material --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Omission:
    """A file the prompt does not show at all. `size_limit` tells a file left out for the size limits (R9: the review
    cannot be READY) from one that cannot be shown to a text judge (a binary file)."""

    path: str
    reason: str
    size_limit: bool = False


@dataclass(frozen=True)
class Budgets:
    """The size limits of the material (`yolo.review`, design D4): per file, per folder of a subject, and per folder
    of a prerequisite."""

    file: int
    folder: int
    dependency: int
    batch: int = 0  # a batch subject longer than this is reviewed in parts (L4-YOLO-098); 0 (default): no bound

    @classmethod
    def of(cls, cfg: L4Config) -> "Budgets":
        review = cfg.yolo.review
        return cls(review.max_file_chars, review.max_folder_chars, review.max_dependency_chars, review.max_batch_chars)


@dataclass(frozen=True)
class FolderText:
    path: str
    files: tuple[tuple[str, str], ...]  # (repository path, text), in reading order; a cut file is shown up to its limit
    omitted: tuple[Omission, ...] = ()  # files the prompt does not show, and why
    cut: tuple[tuple[str, int], ...] = ()  # (repository path, characters left out) of files shown in part
    sizes: tuple[tuple[str, int], ...] = ()  # (repository path, total characters) of every text file read
    file_budget: int = MAX_FILE_CHARS
    budget: int = MAX_FOLDER_CHARS
    base: str = "the target branch"

    @property
    def empty(self) -> bool:
        return not self.files and not self.omitted

    @property
    def left_out(self) -> tuple[str, ...]:
        """What the size limits kept from the judge, one `material_cut` sentence each (R9, design D4): for a subject."""
        return tuple(
            f"material_cut: {path} has {total} characters; the review shows {self.file_budget} per file and "
            f"{self.budget} per folder (yolo.review.max_file_chars, yolo.review.max_folder_chars). Shorten the file "
            f"(move background out of the unit folder) or raise the limit in .l4/config.yaml on {self.base}. "
            "Splitting it does not help: the implementer reads only proposal.md, design.md, requirements.md, "
            "bugfix.md and specs/*/spec.md."
            for path, total, _ in self._shortened()
        )

    def not_in_full(self, who: str, budget: int) -> tuple[str, ...]:
        """The same files for a prerequisite: listed in `missing`, never blocking (design D4)."""
        return tuple(
            f"not shown in full: {json.dumps(who)}: {path} ({shown} of {total} characters shown; "
            f"dependency budget {budget})"
            for path, total, shown in self._shortened()
        )

    def _shortened(self) -> list[tuple[str, int, int]]:
        """(path, total characters, characters shown) of every file the limits cut or left out."""
        sizes, cut = dict(self.sizes), dict(self.cut)
        found = [(path, sizes[path], sizes[path] - n) for path, n in cut.items()]
        return found + [(o.path, sizes[o.path], 0) for o in self.omitted if o.size_limit]

    @property
    def binary(self) -> tuple[str, ...]:
        return tuple(o.path for o in self.omitted if not o.size_limit)


def _rank(rel: str) -> int:
    """The reading order of a prerequisite (design D4): what a dependent needs first, the task list last."""
    parts = PurePosixPath(rel).parts
    if rel in ("proposal.md", "requirements.md"):
        return 0 if rel == "proposal.md" else 1
    if parts[0] == "specs" and parts[-1] == "spec.md":
        return 2
    return {"bugfix.md": 3, "design.md": 4, "tasks.md": 6}.get(rel, 5)


def read_folder(
    git: Git,
    rev: str,
    folder: str,
    *,
    budget: int,
    file_budget: int = MAX_FILE_CHARS,
    order: str = "sorted",
    base: str = "the target branch",
) -> FolderText:
    """The files of `folder` at `rev` as they are (the check marks of `tasks.md` too, design D6; the digest normalises
    them, the material does not), without what the harness writes (`.l4/**`, `verification.md`, `questions.md`,
    `feedback.md`, at any depth, `digest.is_excluded`) and without binary files; each file and the folder are cut at a
    bounded number of characters, and what was cut is recorded in `cut` and `omitted`. `order` is `"sorted"` (the
    subject) or `"prerequisite"` (proposal, requirements, specs, bugfix, design, other files, `tasks.md` last)."""
    root = folder.strip("/")
    listing = git.run_bytes("ls-tree", "-r", "-z", "--name-only", rev, "--", root + "/", check=False)
    files: list[tuple[str, str]] = []
    omitted: list[Omission] = []
    cut: list[tuple[str, int]] = []
    sizes: list[tuple[str, int]] = []
    left = budget
    paths = sorted(p.decode("utf-8", "replace") for p in listing.split(b"\0") if p)
    if order == "prerequisite":
        paths.sort(key=lambda p: _rank(str(PurePosixPath(p).relative_to(root))))  # stable: sorted within a rank
    for path in paths:
        if is_excluded(PurePosixPath(path).relative_to(root).parts):
            continue
        data = git.run_bytes("show", f"{rev}:{path}", check=False)
        if b"\0" in data:
            omitted.append(Omission(path, "binary file"))
            continue
        text = data.decode("utf-8", "replace")
        sizes.append((path, len(text)))
        shown = text[: min(file_budget, max(left, 0))]
        if len(shown) < len(text):
            if left <= 0:
                omitted.append(Omission(path, f"over the size limit of the folder ({len(text)} characters)", True))
                continue
            cut.append((path, len(text) - len(shown)))
            shown += f"\n[cut: {len(text) - len(shown)} characters omitted]"
        left -= len(shown)
        files.append((path, shown))
    return FolderText(root, tuple(files), tuple(omitted), tuple(cut), tuple(sizes), file_budget, budget, base)


def _label(text: str) -> str:
    """A `source` label for a data block: control characters escaped and tag openers defused (a path may hold both)."""
    return defuse(_CONTROL.sub(lambda m: m.group().encode("unicode_escape").decode("ascii"), text))


def _folder_blocks(folder: FolderText) -> str:
    blocks = [data_block(_label(path), text) for path, text in folder.files]
    blocks += [data_block("not shown", _label(f"{o.path}: {o.reason}")) for o in folder.omitted]
    return "\n\n".join(blocks) or "(the folder has no files)"


def _entry(model: Any) -> str:
    return json.dumps(model.model_dump(by_alias=True), indent=2, sort_keys=True)


@dataclass(frozen=True)
class Subject:
    """One thing to review: its id, its prompt, and what the prompt does not show (R9): `left_out` is what the size
    limits cut (the verdict cannot be READY), `not_shown` the binary files (listed in the verdict's `missing`)."""

    kind: str  # "unit" | "batch"
    id: str
    user: str
    left_out: tuple[str, ...] = ()
    not_shown: tuple[str, ...] = ()
    not_in_full: tuple[str, ...] = ()  # a prerequisite's files the budget cut: listed in `missing`, never blocking (D4)
    groups_only: bool = False  # a batch with no acceptance profile: batch_acceptance does not apply to it
    key_text: str = ""  # `user` with the delivered block left empty: what the material key covers (design D2)
    part: str = ""  # a part of a batch reviewed in parts (L4-YOLO-098): a unit id, or `summary`

    @property
    def name(self) -> str:
        """The subject as the CLI, the events and the cache name it: a unit id, `batch:<id>`, or for a part of a batch
        `batch:<id>/<unit id or summary>`."""
        if self.kind == "unit":
            return self.id
        return f"batch:{self.id}/{self.part}" if self.part else f"batch:{self.id}"


GROUPING_NOTE = (
    "This batch only groups units, has no acceptance profile and states no outcome of its own, so batch_acceptance "
    "does not apply to it. Review what lies between its units: contradiction, duplicate_scope, missing_dependency, "
    "and the interfaces the units share."
)
NOT_APPLICABLE = "batch_acceptance"
TASKS_NOTE = (
    "A ticked task (`[x]`) is already delivered on the revision shown: the harness will not implement it again. "
    "Judge the specification of the open tasks; do not raise a `feasibility` or `duplicate_scope` finding only "
    "because work is already done."
)
ORDER_NOTE = (
    "A prerequisite that is a unit of this plan is delivered and merged into the target before any unit that depends "
    "on it starts: the plan runs one unit at a time, in dependency order."
)


def delivered_on_target(archived: Collection[str], phases: Mapping[str, str | None]) -> dict[str, str]:
    """The units already finished on the target: the OpenSpec changes archived at the target revision
    (`plans.archived_at`) and the units a provider reads as merged or archived (`admit.FINISHED_PHASES`), unit id ->
    "archived" or "finished". The caller already holds both; nothing is discovered here."""
    found = {u: "finished" for u, phase in phases.items() if phase in FINISHED_PHASES}
    found.update(dict.fromkeys(archived, "archived"))
    return found


def _delivered_note(plan: Plan, delivered: Mapping[str, str]) -> str:
    """Harness text on the units already delivered on the target, outside the data blocks except for the names
    (repository text): a dependency on one of them is satisfied. The plan's own units are not listed; the list is
    capped."""
    own = {u.id for u in plan.units()}
    names = sorted(u for u in delivered if u not in own)
    if not names:
        return ""
    shown = "\n".join(f"- {_label(u)} ({delivered[u]})" for u in names[:MAX_DELIVERED])
    more = len(names) - MAX_DELIVERED
    tail = f"\nand {more} more are delivered; the list shows the first {MAX_DELIVERED} names." if more > 0 else ""
    return (
        "Already delivered on the target (a dependency on one of these is satisfied and is not a missing_dependency; "
        "it is not a unit of this plan):\n" + data_block("already delivered", shown) + tail
    )


def _batch_deps(ids: Sequence[str]) -> str:
    return data_block("batch prerequisites", "\n".join(f"- batch {b}" for b in ids)) if ids else ""


def _prerequisites(plan: Plan, deps: Sequence[tuple[str, FolderText | None]]) -> list[str]:
    """The prerequisite units, each as a data block with its folder text (or that its folder is not known), and the
    ordering of the plan in plain words when one of them is a unit of this plan."""
    shown = []
    for dep, dep_folder in deps:
        text = _folder_blocks(dep_folder) if dep_folder is not None else "(its folder is not known)"
        head = data_block("prerequisite", _label(dep + (f" ({dep_folder.path})" if dep_folder else "")))
        shown.append(f"{head}\n{text}")
    in_plan = {u.id for u in plan.units()}
    return [*shown, ORDER_NOTE] if any(dep in in_plan for dep, _ in deps) else shown


def _unit_subject(
    plan: Plan,
    unit: PlanUnit,
    batch: PlanBatch,
    folder: FolderText,
    deps: Sequence[tuple[str, FolderText | None]],
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    dep_budget: int = MAX_DEPENDENCY_CHARS,
) -> Subject:
    prerequisites = _prerequisites(plan, deps)
    context = data_block("context", _label(f"in batch {batch.id}; plan {plan.plan_id}, target {plan.target}"))

    def text(listed: Mapping[str, str]) -> str:
        values = {
            "SUBJECT_KIND": "unit",
            "SUBJECT_ID": data_block("subject", _label(unit.id)),
            "ENTRY": data_block("plan entry", _entry(unit)) + "\n" + context + "\n" + TASKS_NOTE,
            "DEPENDENCIES": "\n\n".join(
                [*prerequisites, _batch_deps(batch.depends_on), _delivered_note(plan, listed)]
            ).strip()
            or "(none: the unit depends on nothing)",
            "FOLDERS": data_block("folder", _label(f"{unit.id} ({folder.path})")) + "\n" + _folder_blocks(folder),
        }
        return _fill(MATERIAL_TEMPLATE, values)

    return Subject(
        "unit", unit.id, text(delivered), folder.left_out, folder.binary, _cut_of(deps, dep_budget),
        key_text=text({}),
    )  # fmt: skip


def _cut_of(deps: Sequence[tuple[str, FolderText | None]], budget: int) -> tuple[str, ...]:
    return tuple(line for who, f in deps if f is not None for line in f.not_in_full(who, budget))


def _batch_subject(
    plan: Plan,
    batch: PlanBatch,
    folders: Mapping[str, FolderText],
    skip: Collection[str] = (),
    deps: Sequence[tuple[str, FolderText | None]] = (),
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    dep_budget: int = MAX_DEPENDENCY_CHARS,
) -> Subject:
    """`deps`: the prerequisites of the units of the batch that are not units of the batch, in plan order."""
    units = [u for u in batch.units if u.id not in skip]
    context = data_block("context", _label(f"plan {plan.plan_id}, target {plan.target}"))
    groups_only = batch.acceptance_profile == PROFILE_NONE

    def text(listed: Mapping[str, str]) -> str:
        values = {
            "SUBJECT_KIND": "batch",
            "SUBJECT_ID": data_block("subject", _label(batch.id)),
            "ENTRY": data_block("plan entry", _entry(batch))
            + "\n"
            + context
            + "\n"
            + TASKS_NOTE
            + ("\n" + GROUPING_NOTE if groups_only else ""),
            "DEPENDENCIES": "\n\n".join(
                [*_prerequisites(plan, deps), _batch_deps(batch.depends_on), _delivered_note(plan, listed)]
            ).strip()
            or "(none: the batch depends on nothing)",
            "FOLDERS": "\n\n".join(
                data_block("folder", _label(f"{u.id} ({folders[u.id].path})")) + "\n" + _folder_blocks(folders[u.id])
                for u in units
            ),
        }
        return _fill(MATERIAL_TEMPLATE, values)

    left_out = tuple(line for u in units for line in folders[u.id].left_out)
    not_shown = tuple(p for u in units for p in folders[u.id].binary)
    return Subject(
        "batch", batch.id, text(delivered), left_out, not_shown, _cut_of(deps, dep_budget), groups_only, text({})
    )


SIBLING_CHARS = 6_000  # what a part of a batch shows of every unit it reads in part (L4-YOLO-098)
_READ_ORDER = "in the order proposal, requirements, specs, bugfix, design, other files, tasks"
PART_NOTE_UNIT = (
    "This call reviews one part of the batch: the unit whose folder is shown in full, with each other unit of the "
    f"batch read in part (its first {SIBLING_CHARS:,} characters, {_READ_ORDER}). Each unit is also reviewed on its "
    "own, and the batch as a whole from every unit read in part, in other calls. Report what lies between the unit "
    "shown in full and the other units: contradiction, duplicate_scope, missing_dependency and the interfaces they "
    "share, and batch_acceptance."
)
PART_NOTE_SUMMARY = (
    f"This call reviews the batch as a whole from every unit read in part (its first {SIBLING_CHARS:,} characters, "
    f"{_READ_ORDER}). Each unit is also reviewed on its own, and in full with the others read in part, in other "
    "calls. Report what lies between the units: contradiction, duplicate_scope, missing_dependency and the "
    "interfaces they share, and batch_acceptance."
)


def _sibling_folder(unit: PlanUnit, folder: FolderText) -> str:
    """A unit of a batch read in part: its first characters, as a prerequisite is read."""
    return data_block("folder", _label(f"{unit.id} ({folder.path}), read in part")) + "\n" + _folder_blocks(folder)


def _batch_part(
    plan: Plan,
    batch: PlanBatch,
    unit: PlanUnit | None,
    folders: Mapping[str, FolderText],
    siblings: Mapping[str, FolderText],
    deps: Sequence[tuple[str, FolderText | None]],
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    dep_budget: int = MAX_DEPENDENCY_CHARS,
    skip: Collection[str] = (),
) -> Subject:
    """One call of a batch reviewed in parts (L4-YOLO-098, design D6). With a `unit`: that unit's folder in full as a
    subject's is shown (its budgets and its cut), its prerequisites outside the batch as a batch shows them, and every
    other unit of the batch read in part. Without one, the summary part: every unit read in part, the batch's
    prerequisites outside it by name, no folder in full. `deps` are the prerequisites outside the batch (of `unit`, or
    of every unit shown). The harness text of a part names no unit and no batch."""
    units = [u for u in batch.units if u.id not in skip]
    context = data_block("context", _label(f"plan {plan.plan_id}, target {plan.target}"))
    groups_only = batch.acceptance_profile == PROFILE_NONE
    note = PART_NOTE_SUMMARY if unit is None else PART_NOTE_UNIT
    read_in_part = [_sibling_folder(u, siblings[u.id]) for u in units if unit is None or u.id != unit.id]
    in_full = []
    if unit is not None:
        shown = data_block("folder", _label(f"{unit.id} ({folders[unit.id].path})"))
        in_full = [shown + "\n" + _folder_blocks(folders[unit.id])]

    def text(listed: Mapping[str, str]) -> str:
        if unit is None:
            names = "\n".join(f"- {_label(d)}" for d, _ in deps)
            before = [data_block("batch prerequisites outside it", names)] if deps else []
        else:
            before = _prerequisites(plan, deps)
        values = {
            "SUBJECT_KIND": "batch",
            "SUBJECT_ID": data_block("subject", _label(batch.id)),
            "ENTRY": data_block("plan entry", _entry(batch))
            + "\n"
            + context
            + "\n"
            + TASKS_NOTE
            + ("\n" + GROUPING_NOTE if groups_only else "")
            + "\n"
            + note,
            "DEPENDENCIES": "\n\n".join([*before, _batch_deps(batch.depends_on), _delivered_note(plan, listed)]).strip()
            or "(none: the batch depends on nothing)",
            "FOLDERS": "\n\n".join([*in_full, *read_in_part]),
        }
        return _fill(MATERIAL_TEMPLATE, values)

    if unit is None:
        return Subject(
            "batch", batch.id, text(delivered), (), (), (), groups_only, text({}), part="summary"
        )  # fmt: skip
    return Subject(
        "batch", batch.id, text(delivered), folders[unit.id].left_out, folders[unit.id].binary,
        _cut_of(deps, dep_budget), groups_only, text({}), part=unit.id,
    )  # fmt: skip


def _batch_summary(
    plan: Plan,
    batch: PlanBatch,
    folders: Mapping[str, FolderText],
    siblings: Mapping[str, FolderText],
    deps: Sequence[tuple[str, FolderText | None]],
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    dep_budget: int = MAX_DEPENDENCY_CHARS,
    skip: Collection[str] = (),
) -> Subject:
    """The summary part of a batch reviewed in parts: every unit read in part, no folder in full (design D6)."""
    return _batch_part(plan, batch, None, folders, siblings, deps, delivered, dep_budget, skip)


IN_PARTS_FINDING = {
    "criterion": "parts",
    "severity": "minor",
    "text": (
        "this batch was reviewed in parts: no judge saw two units' full text together, so defects visible only across "
        "units may be missed"
    ),
}  # the harness's note on a batch verdict made from parts (L4-YOLO-098): a minor finding blocks nothing


_WORST = {"BLOCKED": 2, "NEEDS_REVISION": 1, "READY": 0}


def merge_parts(parts: Sequence[Verdict], cause: str) -> Verdict:
    """The verdict of a batch reviewed in parts (L4-YOLO-098): the worst verdict of the parts as the judge gave them
    (not amended: the rules of L4-YOLO-004 and L4-YOLO-023 run once, on this, with the whole batch's cuts), their
    findings in part order with an exact repeat kept once, their assumptions and `missing` lines joined the same way,
    and the `missing` line that says no call saw two units in full together. A part that says NEEDS_REVISION and names
    no finding gets the harness finding `verdict` first, so another part's minor findings cannot turn the merged verdict
    into READY (`_amend` adds that finding only to a verdict with no finding at all)."""
    parts = [
        replace(p, findings=(_verdict_finding(p),)) if p.verdict == "NEEDS_REVISION" and not p.findings else p
        for p in parts
    ]
    said = max((p.verdict for p in parts), key=_WORST.__getitem__)
    findings: list[dict[str, str]] = []
    for part in parts:
        findings += [f for f in part.findings if f not in findings]
    assumptions = list(dict.fromkeys(a for p in parts for a in p.assumptions))
    missing = list(dict.fromkeys(m for p in parts for m in p.missing))
    missing.append(
        f"judged in {len(parts)} parts (each unit in full with the other units read in part, and every unit read in "
        f"part): no call saw two units of the batch in full together; why: {cause}"
    )
    return Verdict(said, tuple(findings), tuple(assumptions), tuple(missing))


class FreshRefused(Exception):
    """`--fresh` named subjects whose current material is already on the ledger: they are not judged again."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def material_key(kind: str, key_text: str) -> str:
    """The material key of a subject (design D2): the prompt version, the kind and the user text without the delivered
    block, so a verdict is reused exactly when the judge would be shown the same thing. The templates and the response
    schema are part of what it is shown: changing one of them without a `PROMPT_VERSION` bump never reuses a verdict."""
    prompt = json.dumps([SYSTEM_TEMPLATE, MATERIAL_TEMPLATE, READINESS_SCHEMA], sort_keys=True, default=str)
    fingerprint = hashlib.sha256(prompt.encode()).hexdigest()
    return hashlib.sha256(f"{PROMPT_VERSION}\0{fingerprint}\0{kind}\0{key_text}".encode()).hexdigest()[:16]


# --- the answer ----------------------------------------------------------------------------------------------------


def blocked(text: str) -> Verdict:
    """BLOCKED with the harness's own finding (criterion `schema`, which the model cannot produce)."""
    return Verdict("BLOCKED", ({"criterion": "schema", "severity": "blocking", "text": text},))


def verdict_of(answer: Any, *, digest: str | None = None) -> Verdict:
    """The rules of D5 on a parsed answer: a schema break is BLOCKED (`schema_invalid`), and a blocking finding makes a
    READY verdict NEEDS_REVISION."""
    problems = validate(answer, READINESS_SCHEMA) if isinstance(answer, dict) else ["$: expected object"]
    if problems:
        return _with_digest(blocked("schema_invalid: " + "; ".join(problems[:5])), digest)
    findings = tuple({k: str(f[k]) for k in ("criterion", "severity", "text")} for f in answer["findings"])
    said: VerdictValue = answer["verdict"]
    if said == "READY" and any(f["severity"] == "blocking" for f in findings):
        said = "NEEDS_REVISION"
    return Verdict(
        said,
        findings,
        tuple(map(str, answer.get("assumptions", ()))),
        tuple(map(str, answer.get("missing", ()))),
        digest,
    )


def _with_digest(verdict: Verdict, digest: str | None) -> Verdict:
    return Verdict(verdict.verdict, verdict.findings, verdict.assumptions, verdict.missing, digest)


def _verdict_finding(verdict: Verdict) -> dict[str, str]:
    """The harness finding of a NEEDS_REVISION that names no finding (L4-YOLO-023)."""
    shown = "; ".join(verdict.missing) or "nothing"
    text = f"the judge said NEEDS_REVISION and named no finding; missing: {shown}"
    return {"criterion": "verdict", "severity": "major", "text": text}


def _amend(verdict: Verdict, subject: Subject) -> Verdict:
    """What the judge was not shown is the harness's finding, not the model's (R9): material the size limits cut makes
    the verdict at least NEEDS_REVISION (BLOCKED stays BLOCKED) with a blocking finding that names it; the binary files
    are listed in `missing` and so is what a prerequisite's budget cut. Then the rules of L4-YOLO-023: a
    minor or major `batch_acceptance` finding on a unit (any severity on a batch without a
    profile) becomes an assumption; a NEEDS_REVISION with no finding gets the harness
    finding `verdict`; a NEEDS_REVISION whose findings are all minor is READY (the findings stay). The judge's own
    `blocking` and a BLOCKED are not touched."""
    findings, said, missing, assumptions = verdict.findings, verdict.verdict, verdict.missing, verdict.assumptions
    named_none = not findings
    why = (
        "batch_acceptance does not apply (the batch has no acceptance profile)"
        if subject.groups_only
        else "batch_acceptance does not apply to a unit"
        if subject.kind == "unit"
        else ""
    )
    # on a unit only a minor or major note can be moved: a blocking finding is the judge's own and stays (D3)
    moved = tuple(
        f
        for f in findings
        if f["criterion"] == NOT_APPLICABLE and (subject.groups_only or f["severity"] in ("minor", "major"))
    )
    if why and moved:
        # the plan file has nowhere to state a batch outcome: the finding cannot be fixed, so it is kept as a note
        assumptions = (*assumptions, *(f"{why}, {f['severity']}: {f['text']}" for f in moved))
        findings = tuple(f for f in findings if f not in moved)
        if said == "NEEDS_REVISION" and not any(f["severity"] in ("blocking", "major") for f in findings):
            said = "READY"
        if said == "BLOCKED" and not findings and subject.groups_only:
            said = "READY"  # a subject that only groups units: the note was all there was
    if subject.left_out:
        text = " ".join(subject.left_out)
        findings = (*findings, {"criterion": "material", "severity": "blocking", "text": text})
        said = "NEEDS_REVISION" if said == "READY" else said
    if said == "NEEDS_REVISION" and named_none and not findings:
        findings = (_verdict_finding(verdict),)
    elif said == "NEEDS_REVISION" and findings and all(f["severity"] == "minor" for f in findings):
        said = "READY"  # the prompt defines minor as a nit
    if subject.not_shown:
        missing = (*missing, *(f"not shown to the judge (binary file): {path}" for path in subject.not_shown))
    missing = (*missing, *subject.not_in_full)
    return Verdict(said, findings, assumptions, missing, verdict.digest)


# --- the judge call ------------------------------------------------------------------------------------------------


@dataclass
class _Reply:
    """What one `_Calls.ask` came to: a verdict (`status` ok), or why there is none. `length_stop` is an `error` whose
    reply stopped at the model's output limit; `run` is the run that reported a usage limit."""

    status: str
    cost: float
    verdict: Verdict | None = None
    detail: str = ""
    length_stop: bool = False
    run: Any = None


class _Calls:
    """One judge, opened once for the whole review: its request factory writes under the plan's scratch folder."""

    def __init__(
        self,
        app: AppContext,
        cfg: L4Config,
        git: Git,
        plan_id: str,
        selected: Selected,
        sandbox: Sandbox,
        counter: Iterator[int] | None = None,
    ):
        self.app, self.cfg, self.selected, self.sandbox = app, cfg, selected, sandbox
        self.root = cache_root(app.environ, repo=app.repo) / SCRATCH / plan_id / "review"
        self.cwd, self.tmp = self.root / "cwd", self.root / "tmp"
        common = git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        home = Path(app.environ["HOME"]) if app.environ.get("HOME") else Path.home()
        cache = cache_root(app.environ, repo=app.repo)
        logins = expand_credential_paths(cfg.sandbox.credential_paths, home)
        tools, _ = spec_paths(
            app.environ, home=home, cache_root=cache, kind="agent", sandbox_cfg=cfg.sandbox,
            credential_paths=logins, forbid=(self.cwd, Path(common).parent),
        )  # fmt: skip
        self.spec = SandboxSpec(
            "agent", self.cwd, Path(common), self.tmp, home, logins,
            adapter=selected.profile.adapter, network=True, runner_tmp=runner_tmp_paths(app.environ),
            cache_root=cache, tool_paths=tools, hide_own_homes=no_stored_login(selected.profile),  # L4-OCV-018
        )  # fmt: skip
        self.counter = counter if counter is not None else itertools.count(1)  # shared: one raw log per call
        self.judge = AgentJudge(selected.impl, self._request, role=ROLE, profile=selected.profile_name)

    def _request(self, prompt: str, schema: dict[str, Any], timeout_s: int) -> RunRequest:
        for folder in (self.cwd, self.tmp):
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
        raw = self.root / "agent-raw" / self.app.run_id / f"readiness-{next(self.counter)}.jsonl"
        extra = dict(getattr(self.selected.impl, "extra_env", {}))
        return RunRequest(
            profile=self.selected.profile, role="judge", cwd=self.cwd, prompt=prompt,
            result_path=self.tmp / "result.json", raw_events_path=raw,
            env=build_agent_env(self.app.environ, self.spec, extra=extra), result_schema=schema,
            permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
            wrap=lambda argv, env, cwd=None: self.sandbox.wrap(argv, self.spec, env, cwd), host_env=self.app.environ,
        )  # fmt: skip

    def ask(
        self, subject: Subject, *, timeout_s: int, digest: str | None, may_start: Callable[[], bool] | None = None
    ) -> _Reply:
        """At most two calls: a break of the schema gets one repair prompt, which is a call like the first and starts
        only when `may_start` says the job has the time (L4-YOLO-097; the reply is then `no_time`). The reply says what
        came of it and what it cost; the review decides what a failure means (L4-YOLO-096)."""
        first = [Msg("user", self.app.redactor.redact_text(subject.user))]
        messages = first
        system = _fill(SYSTEM_TEMPLATE, {"SUBJECT_KIND": subject.kind})
        cost = 0.0
        detail = ""
        for attempt in range(MAX_CALLS):
            if attempt and may_start is not None and not may_start():
                return _Reply("no_time", cost)
            result: StructuredResult = self.judge.complete_structured(
                system, messages, READINESS_SCHEMA, effort=None, max_tokens=0, timeout_s=timeout_s
            )
            cost += result.usage.cost_usd or 0.0
            if result.status == "ok":
                return _Reply("ok", cost, verdict_of(result.parsed, digest=None))
            if result.status != "schema_invalid":  # limit, timeout or error: not a verdict (R9)
                return _Reply(
                    result.status, cost, detail=result.detail or result.status, length_stop=result.length_stop,
                    run=result.run,
                )  # fmt: skip
            detail = result.detail  # schema_invalid: the paths, never the values
            problem = detail if len(detail) <= MAX_PROBLEM_CHARS else detail[: MAX_PROBLEM_CHARS - 1] + "…"
            rejected = result.raw
            echo = [Msg("assistant", self.app.redactor.redact_text(json.dumps(rejected)))] if rejected else []
            messages = [
                *first,
                *echo,
                Msg(
                    "user", f"Your reply did not satisfy the schema ({problem}). Reply again with the JSON object only."
                ),
            ]
        return _Reply("schema_invalid", cost, detail=detail or "no valid answer")


# --- the walk of the chain -----------------------------------------------------------------------------------------


def review_chain(cfg: L4Config) -> tuple[str, list[str]]:
    """The role and the profiles that review a plan (L4-YOLO-095): `roles.plan_judges` when it is not empty, else
    `roles.judges`. The two lists are never joined."""
    if cfg.roles.plan_judges:
        return "plan_judges", list(cfg.roles.plan_judges)
    return ROLE, list(cfg.roles.judges)


class ReviewIncomplete(JudgeFailed):
    """A review with a call that has no answer (L4-YOLO-099): no judge was left for it (`no_judge`), a call timed out
    (`timeout`) or the CI job had no time for the next call (`job_time`). `answered` holds what this run judged (parts
    included; reuses and verdicts with a harness finding are left out), so the caller can keep it. A `JudgeFailed`, so a
    caller that only knows `RoleUnavailable` keeps working."""

    def __init__(
        self,
        reason: str,
        answered: Mapping[str, Verdict],
        left: Sequence[str],
        failures: Sequence[JudgeFailure],
        cost: float,
    ) -> None:
        self.reason = reason
        self.answered = dict(answered)
        self.left = tuple(left)
        self.failures = tuple(failures)
        self.cost = cost
        why = "; ".join(f"{f.profile}: {f.subject or 'selection'}: {f.kind}: {f.detail}" for f in self.failures)
        head = f"the review is incomplete ({reason}): {len(self.answered)} answered, {len(self.left)} left"
        super().__init__(f"{head}; {why}" if why else head)


@dataclass
class _Call:
    """One call of the review: a unit, a batch asked whole, or (L4-YOLO-098) a part of a batch."""

    name: str
    subject: Subject
    digest: str | None
    key: str


@dataclass
class _Outcome:
    kind: str  # "answered" | "none" | "split": a whole batch the judge could not answer in one call (L4-YOLO-098)
    verdict: Verdict | None = None
    judge: str | None = None  # who answered, or who stopped the whole batch
    why: str = ""  # "length" | "timeout", for a split


def _failure_text(app: AppContext, detail: str) -> str:
    first = (app.redactor.redact_text(detail).strip().splitlines() or [""])[0]
    return first[:FAILURE_CHARS]


class _Walk:
    """The judges of one review (design D2): which are opened, which are out, and what each call has been through."""

    def __init__(
        self,
        app: AppContext,
        cfg: L4Config,
        git: Git,
        plan: Plan,
        *,
        adapters: Mapping[str, AgentAdapter] | None,
        sandbox: Sandbox | None,
        sandbox_for: Callable[[str, str], Sandbox] | None,
        timeout_s: int,
        time_left: Callable[[], float | None] | None,
        failed_before: Mapping[str, Sequence[str]],
    ) -> None:
        self.app, self.cfg, self.git, self.plan = app, cfg, git, plan
        self.adapters, self.sandbox, self.sandbox_for = adapters, sandbox, sandbox_for
        self.timeout_s, self.time_left, self.failed_before = timeout_s, time_left, failed_before
        self.role, chain = review_chain(cfg)
        self.chain = list(dict.fromkeys(chain))
        self.opened: dict[str, _Calls] = {}
        self.unusable: set[str] = set()
        self.out: set[str] = set()  # discarded for the rest of the review (error, limit)
        self.failures: list[JudgeFailure] = []
        self.sandbox_errors: list[L4Exit] = []
        self.cost = 0.0
        self.stop: str | None = None  # "timeout" | "job_time": no further call is asked in this run
        self._factory: Factory | None = None
        self._counter = itertools.count(1)

    def factory(self) -> Factory:
        if self._factory is None:
            app = self.app
            self._factory = Factory(
                self.cfg,
                ProbeCtx(app.environ, cache_root(app.environ, repo=app.repo), run_process, forbid=(app.repo,)),
                adapters=self.adapters,
                availability=AvailabilityStore(cache_root(app.environ, repo=app.repo)),
                clock=SystemClock(),
            )
        return self._factory

    def fail(self, profile: str, call: _Call | None, kind: str, detail: str) -> None:
        self.failures.append(
            JudgeFailure(
                profile, call.name if call else "", kind, _failure_text(self.app, detail), call.key if call else None
            )
        )

    def _open(self, name: str) -> bool:
        """Select the profile alone and make its sandbox; a failure puts it out of the review, named (kind `unusable`
        with the selection's reason, or `sandbox`)."""
        try:
            selected = self.factory().for_profile(self.role, f"plan:{self.plan.plan_id}", name, serves=JUDGE_ADAPTERS)
        except RoleUnavailable as exc:
            self.unusable.add(name)
            self.fail(name, None, "unusable", str(exc))
            return False
        try:
            if self.sandbox_for is not None:
                chosen = self.sandbox_for(selected.profile.adapter, selected.profile_name)
            else:
                chosen = self.sandbox or select_sandbox(self.cfg.sandbox, self.app.environ, repo=self.app.repo)
        except SandboxUnavailable as exc:
            self.unusable.add(name)
            self.sandbox_errors.append(exc)
            self.fail(name, None, "sandbox", str(exc))
            return False
        self.opened[name] = _Calls(self.app, self.cfg, self.git, self.plan.plan_id, selected, chosen, self._counter)
        return True

    def order(self, call: _Call, first: str | None = None) -> list[str]:
        """The chain with the judges that failed this material in an earlier run at the end (D5), and `first`, the judge
        that stopped the whole batch, at the front."""
        bad = set(self.failed_before.get(call.key, ()))
        names = [n for n in self.chain if n not in bad] + [n for n in self.chain if n in bad]
        if first in names and first not in bad:  # a judge that failed this material stays behind the others
            names.remove(first)
            names.insert(0, first)
        return names

    def _pick(self, call: _Call, avoid: Collection[str], first: str | None) -> str | None:
        for name in self.order(call, first):
            if name in self.unusable or name in self.out or name in avoid:
                continue
            if name in self.opened or self._open(name):
                return name
        return None

    def _no_time(self) -> bool:
        left = self.time_left() if self.time_left is not None else None
        if left is not None and left < self.timeout_s:
            self.stop = "job_time"
            return True
        return False

    def ask(self, call: _Call, *, first: str | None = None, splittable: bool = False) -> _Outcome:
        """The first judge of the chain that is not discarded for this call, and the next after each failure (D2). The
        verdict is the judge's as `verdict_of` made it: the caller amends it. A whole batch that `splittable` says can
        be reviewed in parts is not failed by a length stop or a timeout: the outcome is `split` and names the judge
        (D6)."""
        avoid: set[str] = set()
        schema: tuple[str, str] | None = None  # the last judge that broke the schema on this call, and the paths
        while True:
            name = self._pick(call, avoid, first)
            if name is None:
                break
            if self._no_time():
                return _Outcome("none")
            calls = self.opened[name]
            reply = calls.ask(
                call.subject, timeout_s=self.timeout_s, digest=call.digest, may_start=lambda: not self._no_time()
            )
            self.cost += reply.cost
            if reply.status == "no_time":  # the repair had no time left: the review stops, no judge failed
                return _Outcome("none")
            if reply.verdict is not None:
                return _Outcome("answered", replace(reply.verdict, digest=call.digest), name)
            if reply.status == "schema_invalid":
                schema = (name, reply.detail)
                avoid.add(name)
                self.fail(name, call, "schema_invalid", reply.detail)
            elif reply.status == "limit":
                assert reply.run is not None
                self.factory().cool_limited(calls.selected, reply.run)
                self.out.add(name)
                self.fail(name, call, "limit", reply.detail)
            elif reply.status == "timeout" and splittable:
                return _Outcome("split", judge=name, why="timeout")
            elif reply.status == "timeout":
                self.fail(name, call, "timeout", reply.detail)
                self.stop = "timeout"
                return _Outcome("none")
            elif reply.length_stop and splittable:
                return _Outcome("split", judge=name, why="length")
            elif reply.length_stop:
                avoid.add(name)
                self.fail(name, call, "length", reply.detail)
            else:
                self.out.add(name)
                self.fail(name, call, "error", reply.detail)
        if schema is not None:  # a judge answered off the schema and none is left: BLOCKED, as with one judge
            blocked_verdict = _with_digest(blocked(f"schema_invalid: {schema[1]}"), call.digest)
            return _Outcome("answered", blocked_verdict, schema[0])
        return _Outcome("none")


# --- the public functions ------------------------------------------------------------------------------------------


def _unit_revs(git: Git, cfg: L4Config, plan: Plan, units: Mapping[str, UnitInfo], target: str) -> dict[str, str]:
    """The commit each known unit of the plan and each unit it depends on is read on: its branch on `origin` when it
    has one, else the target (`current_unit_ref`, R3). Raises `RevisionMissing` before any model is asked."""
    wanted = dict.fromkeys([u.id for u in plan.units()] + [d for u in plan.units() for d in u.depends_on])
    revs = {}
    for unit_id in (u for u in wanted if u in units):
        ref = current_unit_ref(git, cfg, unit_id, target)
        revs[unit_id] = git.rev_parse(ref) or ref
    return revs


def _given_revs(plan: Plan, units: Mapping[str, UnitInfo], given: Mapping[str, str], rev: str) -> dict[str, str]:
    wanted = dict.fromkeys([u.id for u in plan.units()] + [d for u in plan.units() for d in u.depends_on])
    return {u: given.get(u, rev) for u in wanted if u in units}


NO_REVIEW = ("schema", "unit_missing", "completeness")  # harness findings: a verdict that is no review is never reused


def _reusable(entry: Mapping[str, Any]) -> bool:
    return not any(f.get("criterion") in NO_REVIEW for f in entry.get("findings", ()))


def _reused(entry: Mapping[str, Any], key: str, digest: str | None) -> Verdict:
    """A recorded entry as a verdict again. The `parts` rows of a batch judged in parts come with it (a row that was not
    reused itself was judged when the entry was), so the entry the next `plan.reviewed` records still holds them and
    `--fresh` still finds a batch judged in parts (L4-YOLO-098)."""
    at = entry.get("at") or entry.get("reused_from")
    rows = tuple(
        (
            str(row["part"]),
            Verdict(
                row["verdict"],
                tuple(dict(f) for f in row.get("findings", ())),
                tuple(row.get("assumptions", ())),
                tuple(row.get("missing", ())),
                None,
                row.get("material"),
                row.get("reused_from") or at,
                row.get("judge"),
            ),
        )
        for row in entry.get("parts") or ()
        if isinstance(row, dict) and row.get("part") and row.get("verdict") is not None
    )
    return Verdict(
        entry["verdict"],
        tuple(dict(f) for f in entry.get("findings", ())),
        tuple(entry.get("assumptions", ())),
        tuple(entry.get("missing", ())),
        digest,
        key,
        at,
        entry.get("judge"),
        rows,
    )


def review_plan_costed(
    app: AppContext,
    cfg: L4Config,
    plan: Plan,
    units: Mapping[str, UnitInfo],
    *,
    git: Git,
    rev: str,
    adapters: Mapping[str, AgentAdapter] | None = None,
    digest_of: DigestOf | None = None,
    sandbox: Sandbox | None = None,
    timeout_s: int | None = None,
    done: Collection[str] = (),
    delivered: Mapping[str, str] = {},  # noqa: B006 - read only
    prior: Mapping[str, Mapping[str, Any]] = {},  # noqa: B006 - read only
    fresh: Collection[str] = (),
    revs: Mapping[str, str] | None = None,
    budgets: Budgets | None = None,
    sandbox_for: Callable[[str, str], Sandbox] | None = None,
    refuse_fresh_of_prior: bool = False,
    time_left: Callable[[], float | None] | None = None,
    failed_before: Mapping[str, Sequence[str]] = {},  # noqa: B006 - read only
    kept: Collection[str] = (),
) -> tuple[ReviewResult, float]:
    """`review_plan` and the cost in dollars the judges reported (what the plan step charges to the plan). `done` names
    the units the plan already merged or integrated (`admit.done_units`): the target holds their work, so the judge is
    not asked about them (they are READY, with their digest when their folder is there) and a batch is reviewed on its
    other units. A batch of done units only is READY. `delivered` (`delivered_on_target`) names the units already
    finished on the target; the judge is told a dependency on one of them is satisfied.

    `prior` maps a material key to a recorded entry (`plan.reviewed`, `plan.review_incomplete`): a subject whose key is
    there and whose name (`Subject.name`) is not in `fresh` gets that verdict again (`reused_from`), with no judge call
    and no cost, unless the entry is no review (a harness `schema`, `unit_missing` or `completeness` finding). `revs`
    replaces the revision every unit and prerequisite is read on (the working-tree snapshot).

    The review walks the chain of `review_chain` for each call (L4-YOLO-096): a judge is opened, with its sandbox,
    when a call first reaches it (`sandbox_for(adapter, profile)` replaces `sandbox` and `select_sandbox`), and a
    call a judge cannot answer goes to the next one. `timeout_s` bounds each call (default `yolo.review.timeout`);
    `time_left` is the seconds a CI job has left, and a call starts only when it is at least `timeout_s`;
    `failed_before` maps a material key to the judges that failed it in an earlier run, asked last. `kept` holds the
    material keys an incomplete review kept after the plan's latest `plan.reviewed` (`findings.kept_keys`): a batch
    with a part among them is reviewed in parts; a part that only a finished review recorded is reused when the batch is
    split but never splits it (L4-YOLO-098). A review with
    a call no judge answered raises `ReviewIncomplete` (L4-YOLO-099). With `refuse_fresh_of_prior`, a subject
    named in `fresh` whose material is already in `prior` raises `FreshRefused` before any judge call (a recorded
    review is not re-rolled)."""
    revs = _unit_revs(git, cfg, plan, units, rev) if revs is None else _given_revs(plan, units, revs, rev)
    limits = budgets or Budgets.of(cfg)
    if timeout_s is None:
        timeout_s = duration_seconds(cfg.yolo.review.timeout)
    digest_fn = digest_of or unit_digest  # on the revision a unit is read on: `current_unit_digest` of that unit (R3)
    folders: dict[str, FolderText] = {}
    for unit in plan.units():
        info = units.get(unit.id)
        folders[unit.id] = (
            read_folder(
                git, revs[unit.id], info.folder, budget=limits.folder, file_budget=limits.file, base=plan.target
            )
            if info
            else FolderText("", ())
        )
    read_deps: dict[str, FolderText | None] = {}

    def dependency(dep: str) -> FolderText | None:  # a prerequisite is read once, whoever shows it
        if dep not in read_deps:
            read_deps[dep] = (
                read_folder(
                    git,
                    revs[dep],
                    units[dep].folder,
                    budget=limits.dependency,
                    file_budget=limits.file,
                    order="prerequisite",
                )  # fmt: skip
                if dep in units
                else None
            )
        return read_deps[dep]

    subjects: list[tuple[Subject, str | None]] = []
    result_units: dict[str, Verdict] = {}
    result_batches: dict[str, Verdict] = {}
    batch_info: dict[str, tuple[PlanBatch, list[PlanUnit], list[tuple[str, FolderText | None]]]] = {}
    for batch in plan.batches:
        for unit in batch.units:
            info, folder = units.get(unit.id), folders[unit.id]
            digest = digest_fn(git, revs[unit.id], info.folder) if info and not folder.empty else None
            if unit.id in done:
                result_units[unit.id] = _with_digest(Verdict("READY"), digest)
                continue
            if folder.empty:
                note = (
                    f"the folder of {unit.id} has no files at {revs[unit.id][:10]}"
                    if info
                    else f"{unit.id} is not a known unit"
                )
                result_units[unit.id] = _with_digest(blocked(f"unit_missing: {note}"), digest)
                continue
            deps = [(d, dependency(d)) for d in unit.depends_on]
            subjects.append((_unit_subject(plan, unit, batch, folder, deps, delivered, limits.dependency), digest))
    for batch in plan.batches:
        left = [u for u in batch.units if u.id not in done]
        if len(batch.units) > 1 and not left:
            result_batches[batch.id] = Verdict("READY")
        elif len(batch.units) > 1 and all(not folders[u.id].empty for u in left):
            inside = {u.id for u in batch.units}
            # the prerequisites of the units reviewed that lie outside the batch, once each, in plan order
            outside = dict.fromkeys(d for u in left for d in u.depends_on if d not in inside)
            batch_deps = [(d, dependency(d)) for d in outside]
            batch_info[batch.id] = (batch, left, batch_deps)
            subjects.append(
                (_batch_subject(plan, batch, folders, done, batch_deps, delivered, limits.dependency), None)
            )
    asked: list[tuple[Subject, str | None, str]] = []
    refused: list[str] = []
    for subject, digest in subjects:
        key = material_key(subject.kind, subject.key_text)
        entry = prior.get(key)
        if refuse_fresh_of_prior and subject.name in fresh and entry is not None and _reusable(entry):
            refused.append(subject.name)
        if entry is not None and subject.name not in fresh and _reusable(entry):
            (result_units if subject.kind == "unit" else result_batches)[subject.id] = _reused(entry, key, digest)
        else:
            asked.append((subject, digest, key))
    if refused:
        raise FreshRefused(tuple(refused))
    walk = _Walk(
        app, cfg, git, plan, adapters=adapters, sandbox=sandbox, sandbox_for=sandbox_for, timeout_s=timeout_s,
        time_left=time_left, failed_before=failed_before,
    )  # fmt: skip
    if asked and not walk.chain:
        raise RoleUnavailable(walk.role, "no profile is configured for it under roles")
    answered: dict[str, Verdict] = {}  # what this run judged, for a review that does not finish (L4-YOLO-099)
    left_over: list[str] = []

    def keep(name: str, verdict: Verdict) -> None:
        if _reusable({"findings": verdict.findings}):
            answered[name] = verdict

    siblings: dict[str, FolderText] = {}

    def sibling(unit_id: str) -> FolderText:  # a unit of a batch in parts read within SIBLING_CHARS, once
        if unit_id not in siblings:
            siblings[unit_id] = read_folder(
                git, revs[unit_id], units[unit_id].folder, budget=SIBLING_CHARS, file_budget=SIBLING_CHARS,
                order="prerequisite",
            )  # fmt: skip
        return siblings[unit_id]

    def parts_of(subject: Subject) -> list[tuple[Subject, str]]:
        batch, shown, batch_deps = batch_info[subject.id]
        inside = {u.id for u in batch.units}
        read = {u.id: sibling(u.id) for u in shown}
        built = [
            _batch_part(
                plan, batch, u, folders, read, [(d, dependency(d)) for d in u.depends_on if d not in inside],
                delivered, limits.dependency, done,
            )
            for u in shown
        ]  # fmt: skip
        built.append(_batch_summary(plan, batch, folders, read, batch_deps, delivered, limits.dependency, done))
        return [(part, material_key("batch-part", part.key_text)) for part in built]

    def kept_part(whole: Subject, part: Subject, key: str) -> Mapping[str, Any] | None:
        entry = prior.get(key)
        fresh_ask = whole.name in fresh or part.name in fresh
        return entry if entry is not None and _reusable(entry) and not fresh_ask else None

    def judge_batch(subject: Subject, key: str) -> Verdict | None:
        """A batch in parts or whole (L4-YOLO-098): None when a call has no answer (its names are in `left_over`)."""
        shown = len(batch_info[subject.id][1])
        call = _Call(subject.name, subject, None, key)
        cause: str | None = None
        first: str | None = None
        parts: list[tuple[Subject, str]] | None = None
        if shown >= 2:
            if limits.batch > 0 and len(subject.user) > limits.batch:
                cause = (
                    f"its material has {len(subject.user)} characters, over yolo.review.max_batch_chars "
                    f"({limits.batch})"
                )
            elif kept or subject.name in fresh:
                parts = parts_of(subject)
                whole = prior.get(key)  # `--fresh` on a batch an earlier run judged in parts asks every part again
                redo = subject.name in fresh and whole is not None and bool(whole.get("parts"))
                if redo or any(k in kept and kept_part(subject, part, k) is not None for part, k in parts):
                    cause = "an earlier review run answered a part of it"
        if cause is None:
            outcome = walk.ask(call, splittable=shown >= 2)
            if outcome.kind == "answered" and outcome.verdict is not None:
                verdict = replace(_amend(outcome.verdict, subject), material=key, judge=outcome.judge)
                keep(call.name, verdict)
                return verdict
            if outcome.kind != "split":
                left_over.append(call.name)
                return None
            first = outcome.judge
            what = "stopped at the output limit of" if outcome.why == "length" else "timed out on"
            cause = f"the whole batch {what} {first}"
        parts = parts or parts_of(subject)
        rows: list[tuple[str, Verdict]] = []
        missing: list[str] = []
        for part, part_key in parts:
            entry = kept_part(subject, part, part_key)
            if entry is not None:
                rows.append((part.name, _reused(entry, part_key, None)))
                continue
            outcome = _Outcome("none") if walk.stop is not None else walk.ask(
                _Call(part.name, part, None, part_key), first=first
            )  # fmt: skip
            if outcome.kind != "answered" or outcome.verdict is None:
                missing.append(part.name)
                continue
            raw = replace(outcome.verdict, material=part_key, judge=outcome.judge)
            keep(part.name, raw)
            rows.append((part.name, raw))
        if missing:
            left_over.extend([call.name, *missing])
            return None
        merged = _amend(merge_parts([v for _, v in rows], cause), subject)
        merged = replace(
            merged, findings=(*merged.findings, dict(IN_PARTS_FINDING))
        )  # a note: the verdict is as it was
        judges = ", ".join(dict.fromkeys(v.judge for _, v in rows if v.judge))
        verdict = replace(merged, material=key, judge=judges or None, parts=tuple(rows))
        keep(call.name, verdict)
        return verdict

    for subject, digest, key in asked:
        if walk.stop is not None:
            left_over.append(subject.name)
            continue
        if subject.kind == "batch":
            verdict = judge_batch(subject, key)
        else:
            outcome = walk.ask(_Call(subject.name, subject, digest, key))
            verdict = None
            if outcome.kind == "answered" and outcome.verdict is not None:
                verdict = replace(_amend(outcome.verdict, subject), material=key, judge=outcome.judge)
                keep(subject.name, verdict)
            else:
                left_over.append(subject.name)
        if verdict is not None:
            (result_units if subject.kind == "unit" else result_batches)[subject.id] = verdict
    if left_over:
        if walk.sandbox_errors and not answered and all(f.kind == "sandbox" for f in walk.failures):
            raise walk.sandbox_errors[0]  # every judge was refused its sandbox: exit 3, as with one judge (SCN-YOLO-61)
        reason = walk.stop or "no_judge"
        raise ReviewIncomplete(reason, answered, left_over, walk.failures, walk.cost)
    for batch in plan.batches:  # a batch with a unit that cannot be reviewed is not reviewed as a whole either
        if len(batch.units) > 1 and batch.id not in result_batches:
            result_batches[batch.id] = blocked("unit_missing: a unit of the batch has no folder to review")
    ordered = {u.id: result_units[u.id] for u in plan.units()}
    return ReviewResult(ordered, result_batches, tuple(walk.failures)), walk.cost


def review_plan(
    app: AppContext,
    cfg: L4Config,
    plan: Plan,
    units: Mapping[str, UnitInfo],
    *,
    git: Git,
    rev: str,
    adapters: Mapping[str, AgentAdapter] | None = None,
    digest_of: DigestOf | None = None,
    sandbox: Sandbox | None = None,
) -> ReviewResult:
    """Review every unit of `plan` and every batch of more than one unit, with the judge role, on the folders at `rev`.

    `adapters` replaces the adapters by name (tests and `l4 simulate` inject a `FakeAdapter`). `units` is what
    admission read of each unit (its folder). `rev` is the target: a unit that has a branch on `origin` is read, and
    digested, on that branch (D3, R3). A `Verdict.digest` is the unit digest on the revision the unit was read on:
    `digest_of` when given, else `l4.yolo.digest.unit_digest`. A revision that does not exist raises `RevisionMissing`;
    a judge that fails raises `JudgeFailed`. `sandbox` replaces the selected sandbox."""
    result, _ = review_plan_costed(
        app, cfg, plan, units, git=git, rev=rev, adapters=adapters, digest_of=digest_of, sandbox=sandbox
    )
    return result


__all__ = [
    "READINESS_SCHEMA",
    "Budgets",
    "FolderText",
    "FreshRefused",
    "JudgeFailed",
    "Omission",
    "ReviewIncomplete",
    "Subject",
    "delivered_on_target",
    "material_key",
    "read_folder",
    "review_chain",
    "review_plan",
    "review_plan_costed",
    "verdict_of",
]
