"""The Kiro provider (SPEC 4.5): `.kiro/specs/<name>/` read from files, tasks written one byte at a time.

Kiro has no spec CLI, so nothing here starts a process. Only `x` is ever written; `-` and `~` are read.
M1: spec-providers 2.8 and 2.9 (fix units as bugfix specs), 1.12 (the `kiro.archive_dir` move), 4.2 (primary).
"""

import dataclasses
import json
import logging
import re
import shutil
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.specs.base import (
    MAX_DECISION_CHARS,
    SAFE_NAME,
    ArchiveRefused,
    ArchiveReport,
    Criterion,
    Finding,
    FixUnitExists,
    FixUnitInvalid,
    Framework,
    GateReport,
    Marker,
    MarkerNotAllowed,
    ParentHasOpenChildren,
    SpecDelta,
    SpecError,
    Task,
    Unit,
    UnitRef,
    ValidationIssue,
    ValidationReport,
)
from l4.specs.criteria import kiro_criteria
from l4.specs.detect import kiro_spec_dirs
from l4.specs.fixmark import FixMarker, chore_findings, fix_name, read_fix_marker, split_fix_name, write_fix_marker
from l4.specs.followup import FollowUpMarker, follow_up_name, write_follow_up_marker
from l4.specs.markers import MAX_TASKS_BYTES, Line, split_lines, write_marker

log = logging.getLogger("l4.spec")

KIRO_TASK_RE = re.compile(r"^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$")  # Kiro IDE 1.2.4, verbatim
_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?(?=\s|$)")
_LOOKS_LIKE_TASK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[^\]]*\]")
_REQUIREMENTS = re.compile(r"_Requirements:\s*([^_\n]*)_")
# a reference stands alone: not inside a word or a dotted name (`ADR-0014.8`, `AC3`), L4-KSP-006
_REF = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)*(?!\w)")
_GRAPH_HEADING = re.compile(r"^##\s+Task Dependency Graph\s*$", re.MULTILINE)
_NEXT_SECTION = re.compile(r"^##\s", re.MULTILINE)
_JSON_FENCE = re.compile(r"^```json[ \t]*\r?\n(.*?)^```", re.MULTILINE | re.DOTALL)
_TAB_WIDTH = 4


def _indent_depths(raw: Sequence[tuple[int, int | None]]) -> list[int]:
    """Depth of every task: the dotted number when it has one, else its place among the indents seen so far (a task
    indented deeper than the previous one is its child). `raw` is (indent, depth from the number or None)."""
    stack: list[tuple[int, int]] = []
    depths: list[int] = []
    for indent, numbered in raw:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        depth = numbered if numbered is not None else (stack[-1][1] + 1 if stack else 0)
        stack.append((indent, depth))
        depths.append(depth)
    return depths


def parse_kiro_tasks(data: bytes) -> list[Task]:
    """Every task line in document order. `depth` is normalised so the OpenSpec-era selector works: the number of
    dots in the task number when any task is numbered, else the indentation rank. A task under an optional task is
    optional too (the whole branch is skippable). `links` hold the refs of the `_Requirements:_` lines below a task."""
    lines = split_lines(data)
    found: list[tuple[Line, re.Match[str], int]] = []  # (line, match on the text without its BOM, BOM width)
    for line in lines:
        text = line.text.removeprefix("﻿")
        if match := KIRO_TASK_RE.match(text):
            found.append((line, match, len(line.text) - len(text)))
    numbers = [_NUMBER.match(m.group(5)) for _, m, _ in found]
    any_numbered = any(numbers)
    depths = _indent_depths(
        [
            (len(m.group(1).expandtabs(_TAB_WIDTH)), n.group(1).count(".") if n and any_numbered else None)
            for (_, m, _), n in zip(found, numbers, strict=True)
        ]
    )
    tasks: list[Task] = []
    optional_depths: list[int] = []  # depths of the optional ancestors that are still open
    for (line, match, bom), number, depth in zip(found, numbers, depths, strict=True):
        while optional_depths and optional_depths[-1] >= depth:
            optional_depths.pop()
        optional = bool(match.group(4)) or bool(optional_depths)
        if match.group(4):
            optional_depths.append(depth)
        bracket = match.start(3)
        tasks.append(
            Task(
                key=number.group(1) if number else f"L{line.number}",
                number=number.group(1) if number else None,
                title=match.group(5).strip(),
                done=match.group(3) in "xX",
                marker_char=match.group(3),
                depth=depth,
                line=line.number,
                marker_offset=line.offset_of(bracket + bom),
                optional=optional,
                started=match.group(3) in ("-", "~"),
                links=_links_below(lines, line.number),
            )
        )
    return tasks


def _links_below(lines: Sequence[Line], line_number: int) -> tuple[str, ...]:
    """The refs of `_Requirements: 2.1, 3.3_` lines between this task and the next task or heading."""
    refs: list[str] = []
    for line in lines[line_number:]:
        text = line.text.removeprefix("﻿")
        if KIRO_TASK_RE.match(text) or text.startswith("#"):
            break
        for match in _REQUIREMENTS.finditer(text):
            refs.extend(_REF.findall(match.group(1)))
    return tuple(dict.fromkeys(refs))


def _cites(link: str, requirement: str) -> bool:
    """A link `2.3` cites criterion 2.3; a link `2` cites every 2.x."""
    return link == requirement or requirement.startswith(f"{link}.")


def cited_by_changed(tasks: Sequence[Task], changed: Collection[str]) -> list[str]:
    """The keys of the done tasks that L4-OPS-015 reopens, in document order: every task whose `_Requirements:_` links
    cite a changed criterion (with its descendants when it is a parent), and the parents of those."""
    if not changed:
        return []
    cited: set[int] = set()
    for index, task in enumerate(tasks):
        if any(_cites(link, number) for link in task.links for number in changed):
            end = index + 1
            while end < len(tasks) and tasks[end].depth > task.depth:  # the descendants follow their parent
                end += 1
            cited.update(range(index, end))
    parents: set[int] = set()
    for index in cited:
        depth = tasks[index].depth
        for above in range(index - 1, -1, -1):
            if tasks[above].depth < depth:
                parents.add(above)
                depth = tasks[above].depth
    return [tasks[i].key for i in sorted(cited | parents) if tasks[i].done]


def descendants(tasks: Sequence[Task], index: int) -> list[Task]:
    out = []
    for task in tasks[index + 1 :]:
        if task.depth <= tasks[index].depth:
            break
        out.append(task)
    return out


def required_leaves(tasks: Sequence[Task]) -> list[Task]:
    return [t for i, t in enumerate(tasks) if not t.optional and not descendants(tasks, i)]


# --- dependency waves (L4-KSP-002) -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Waves:
    by_task: Mapping[str, int]  # task key -> wave id


def parse_waves(text: str, known: Collection[str] | None = None) -> tuple[Waves | None, str | None]:
    """(waves, why-not). No graph section: (None, None). A section that is not a valid graph: (None, reason). With
    `known` (the task keys), a task id that names no task makes the graph invalid."""
    waves, why, _ = _read_graph(text, known)
    return waves, why


def _read_graph(text: str, known: Collection[str] | None) -> tuple[Waves | None, str | None, bool]:
    """`parse_waves` and whether a reason is that the block is not JSON at all (L4-KSP-006): no ```json fence, or a
    fence that does not parse. Any other reason is a JSON graph that is wrong."""
    heading = _GRAPH_HEADING.search(text)
    if heading is None:
        return None, None, False
    rest = text[heading.end() :]
    following = _NEXT_SECTION.search(rest)
    section = rest[: following.start()] if following else rest
    fence = _JSON_FENCE.search(section)
    if fence is None:
        return None, "no ```json block under the heading", True
    try:
        document = json.loads(fence.group(1))
    except ValueError as exc:
        return None, f"the JSON does not parse ({exc})", True
    waves = document.get("waves") if isinstance(document, dict) else None
    if not isinstance(waves, list):
        return None, 'the JSON has no "waves" list', False
    by_task: dict[str, int] = {}
    seen_ids: set[int] = set()
    for wave in waves:
        wave_id = wave.get("id") if isinstance(wave, dict) else None
        ids = wave.get("tasks") if isinstance(wave, dict) else None
        if not isinstance(wave_id, int) or isinstance(wave_id, bool) or wave_id in seen_ids:
            return None, "a wave has no integer id, or its id repeats", False
        if not isinstance(ids, list) or not all(isinstance(t, str) for t in ids):
            return None, f"wave {wave_id} has no list of task ids", False
        seen_ids.add(wave_id)
        for task_id in ids:
            if task_id in by_task:
                return None, f"task {task_id} is in two waves", False
            if known is not None and task_id not in known:
                return None, f"wave {wave_id} names task {task_id}, which is not in tasks.md", False
            by_task[task_id] = wave_id
    return Waves(by_task), None, False


def read_waves(text: str, known: Collection[str] | None = None) -> Waves | None:
    waves, why = parse_waves(text, known)
    if why:
        log.warning("invalid Task Dependency Graph (%s); using document order", why)
    return waves


def with_waves(tasks: Sequence[Task], waves: Waves | None) -> list[Task]:
    if waves is None:
        return list(tasks)
    return [dataclasses.replace(t, wave=waves.by_task.get(t.key)) for t in tasks]


def order_by_wave(pending: Sequence[Task]) -> list[Task]:
    """`pending` (in document order), wave by wave (document order inside a wave). A task the graph does not list
    stays at its document position: right after the nearest earlier pending task, or first."""
    order = sorted((i for i, t in enumerate(pending) if t.wave is not None), key=lambda i: (pending[i].wave, i))
    for i, task in enumerate(pending):  # by position: task keys need not be unique
        if task.wave is None:
            order.insert(0 if i == 0 else order.index(i - 1) + 1, i)
    return [pending[i] for i in order]


def order_leaves(tasks: Sequence[Task]) -> list[Task]:
    """The pending required leaves in the order the harness runs them."""
    return order_by_wave([t for t in required_leaves(tasks) if not t.done])


def kiro_tasks(data: bytes) -> list[Task]:
    """The tasks of a `tasks.md` as the harness reads them: the grammar, then the waves of its dependency graph."""
    tasks = parse_kiro_tasks(data)
    return with_waves(tasks, read_waves(data.decode("utf-8", "replace"), {t.key for t in tasks}))


# --- the provider ------------------------------------------------------------------------------------------------


CRITERION_FORM = (
    "expected a `### Requirement N` heading, a `#### Acceptance Criteria` heading and numbered lines under it such as "
    "`1. WHEN ...`, `1) WHEN ...` or `1.1. WHEN ...`"
)
NO_CRITERIA_HINT = f"no acceptance criteria were read from requirements.md; {CRITERION_FORM}"


def _form_hint(ref: str, aliases: set[str]) -> str:
    """What SPEC-002 adds to a citation no criterion has: the expected form, when nothing was read at all or nothing
    under the cited requirement (a wrong form there); nothing when the requirement has criteria (a wrong number)."""
    if not aliases:
        return f"; {NO_CRITERIA_HINT}"
    requirement = ref.split(".", 1)[0]
    if any(a.startswith(f"Req {requirement}.") for a in aliases):
        return ""
    return f"; no acceptance criterion was read under Requirement {requirement}; {CRITERION_FORM}"


class KiroProvider:
    """Kiro units of one checkout. The unit name is the directory name (never `.config.kiro` `specId`)."""

    framework = Framework.KIRO

    def __init__(
        self,
        repo: Path,
        *,
        root: str = ".kiro/specs",
        enforce: bool = False,
        exempt_kinds: Sequence[str] = (),
        uuid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        relative = Path(root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise SpecError(f"spec.kiro.root must be a relative path inside the repo, got {root!r}")
        self._repo = repo
        self._root = root
        self._parts = relative.parts
        self._enforce = enforce
        self._exempt = tuple(exempt_kinds)
        self._uuid = uuid_factory

    def list_units(self) -> list[UnitRef]:
        return [UnitRef(Framework.KIRO, d.name, d) for d in kiro_spec_dirs(self._repo, self._root)]

    def unit_dir(self, unit: UnitRef) -> Path:
        try:
            reject_symlinks(self._repo, *self._parts, unit.name)
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None
        return self._repo.joinpath(*self._parts, unit.name)

    def _tasks_text(self, unit: UnitRef) -> tuple[bytes, str]:
        try:
            data = read_regular_file(self.unit_dir(unit) / "tasks.md", limit=MAX_TASKS_BYTES)
        except FileNotFoundError:
            return b"", ""
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None
        return data, data.decode("utf-8", "replace")

    def tasks(self, unit: UnitRef) -> list[Task]:
        return kiro_tasks(self._tasks_text(unit)[0])

    def criteria(self, unit: UnitRef) -> list[Criterion]:
        return kiro_criteria(self.unit_dir(unit))

    def load(self, unit: UnitRef) -> Unit:
        return Unit(unit, tuple(self.tasks(unit)), tuple(self.criteria(unit)))

    def set_marker(self, unit: UnitRef, task_key: str, marker: Marker) -> None:
        """Tick a task, then every parent whose required children are now all done, each as its own one-byte write."""
        if marker is not Marker.DONE:
            raise MarkerNotAllowed(f"Kiro tasks are only marked done by the harness, not {marker.name.lower()}")
        tasks = self.tasks(unit)
        matches = [i for i, t in enumerate(tasks) if t.key == task_key]
        if not matches:
            raise SpecError(f"{unit.id} has no task {task_key}")
        if len(matches) > 1:
            raise MarkerNotAllowed(f"task id {task_key} is ambiguous in {unit.id} ({len(matches)} checkboxes)")
        (index,) = matches
        task = tasks[index]
        if task.done:
            raise MarkerNotAllowed(f"task {task_key} of {unit.id} is already done")
        open_children = [c for c in descendants(tasks, index) if not c.optional and not c.done]
        if open_children:
            raise ParentHasOpenChildren(
                f"task {task_key} of {unit.id} cannot be closed: required child {open_children[0].key} is open"
            )
        path = self.unit_dir(unit) / "tasks.md"
        self._write_done(path, task)
        while (parent := self._closable_parent(self.tasks(unit))) is not None:
            self._write_done(path, parent)

    def reopen(self, unit: UnitRef, changed: Collection[str]) -> list[str]:
        """L4-OPS-015: the done tasks that cite a changed criterion, and their parents, go back to `[ ]`
        (`cited_by_changed`); their keys. One byte each, like the ticks; nothing is written when none cites one."""
        tasks = self.tasks(unit)
        keys = cited_by_changed(tasks, changed)
        path = self.unit_dir(unit) / "tasks.md"
        for task in tasks:
            if task.key in keys:
                assert task.marker_offset is not None  # the Kiro grammar admits exactly one marker byte
                write_marker(path, task.marker_offset, task.marker_char.encode(), b" ")
        return keys

    @staticmethod
    def _write_done(path: Path, task: Task) -> None:
        assert task.marker_offset is not None  # the Kiro grammar admits exactly one marker byte
        write_marker(path, task.marker_offset, task.marker_char.encode(), b"x")

    @staticmethod
    def _closable_parent(tasks: Sequence[Task]) -> Task | None:
        """The innermost open parent (at least one descendant, optional or not) whose required descendants are all
        done: vacuously true when every descendant is optional, so such a parent is closed and never executed."""
        for i in range(len(tasks) - 1, -1, -1):
            kids = descendants(tasks, i)
            if kids and not tasks[i].done and not tasks[i].optional and all(c.done for c in kids if not c.optional):
                return tasks[i]
        return None

    def create_fix_unit(
        self, parent: UnitRef, round: int, findings: Sequence[Finding], spec_delta: SpecDelta | None
    ) -> UnitRef:
        """`<parent>-fix-<round>` as a Kiro bugfix spec (L4-KSP-005, L4-FBK-008): `bugfix.md`, `design.md`, `tasks.md`,
        `.config.kiro` and the fix marker, then the provider's own validation. The whole folder is removed again when
        it does not validate, and nothing is ever written outside it. Takes what the OpenSpec writer takes."""
        return self._create_spec(fix_name(parent.name, round), parent, round, findings, spec_delta, None)

    def create_follow_up(
        self, parent: UnitRef, n: int, findings: Sequence[Finding], spec_delta: SpecDelta | None,
        items: Sequence[tuple[str, str]],
    ) -> UnitRef:  # fmt: skip
        """`<parent>-followup-<n>` as a Kiro bugfix spec (L4-FBK-010): written like a fix unit is, with
        `.l4/followup.json` for the marker (`items`: the (id, sha256) of the parent's feedback items it takes), so it is
        a unit that `l4 run` selects and not a fix unit of the parent."""
        return self._create_spec(follow_up_name(parent.name, n), parent, n, findings, spec_delta, tuple(items))

    def _create_spec(
        self, name: str, parent: UnitRef, round: int, findings: Sequence[Finding], spec_delta: SpecDelta | None,
        follow_items: tuple[tuple[str, str], ...] | None,
    ) -> UnitRef:  # fmt: skip
        what = "follow-up" if follow_items is not None else "fix unit"
        if not SAFE_NAME.match(name):
            raise SpecError(f"{name!r} is not a valid spec name")
        ref = UnitRef(Framework.KIRO, name, self._repo.joinpath(*self._parts, name))
        folder = self.unit_dir(ref)
        if folder.exists():
            raise FixUnitExists(f"{ref.id} exists; a {what} is never overwritten")
        if not findings:
            raise SpecError(f"a {what} needs at least one finding")
        try:
            self._scaffold(parent, ref, round, findings, spec_delta, follow_items)
            report = self.validate(ref, strict=True)
            if not report.valid:
                errors = [i for i in report.issues if i.level == "ERROR"] or list(report.issues)
                shown = "; ".join(f"{i.path}: {i.message}"[:200] for i in errors[:3])
                raise FixUnitInvalid(f"{ref.id} does not validate: {shown or 'no detail'}")
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return ref

    def _scaffold(
        self, parent: UnitRef, ref: UnitRef, round: int, findings: Sequence[Finding], delta: SpecDelta | None,
        follow_items: tuple[tuple[str, str], ...] | None = None,
    ) -> None:  # fmt: skip
        folder = ref.path
        folder.mkdir(parents=True)
        chores = (
            tuple(i for f in findings if f.chore for i in f.ids),
            tuple(i for f in findings if f.chore and f.tests for i in f.ids),
            tuple(i for f in findings if f.chore and f.refactor for i in f.ids),
        )
        if follow_items is not None:  # a unit of its own: no restated criteria of the parent, no fix marker
            write_follow_up_marker(folder, FollowUpMarker(parent.id, follow_items, *chores))
            known: dict[str, tuple[str, Criterion]] = {}
        else:
            # the marker first: a fix unit's `2.n` item is read as the parent's criterion only where the marker is
            retakes = tuple(i for f in findings if f.chore and f.retake for i in f.ids)
            repairs = tuple(i for f in findings if f.chore and f.repair for i in f.ids)
            write_fix_marker(
                folder,
                FixMarker(parent.id, round, tuple(i for f in findings for i in f.ids), *chores, retakes, repairs),
            )
            known = self._known_criteria(parent)
        items = _FixItems(parent.name, findings, delta, known)
        (folder / "bugfix.md").write_text(items.bugfix(), encoding="utf-8")
        (folder / "design.md").write_text(
            _fix_design(parent, round, findings, follow_up=follow_items is not None), encoding="utf-8"
        )
        ids = {c.alias: c.id for c in self.criteria(ref)}
        (folder / "tasks.md").write_text(_fix_tasks(findings, items.refs, ids), encoding="utf-8")
        config = {"specId": self._uuid(), "workflowType": "requirements-first", "specType": "bugfix"}
        (folder / ".config.kiro").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    def _known_criteria(self, parent: UnitRef) -> dict[str, tuple[str, Criterion]]:
        """Criterion id -> (where it is written, the criterion): the parent's, then those of its earlier fix units. A
        fix task can cite either, since the verifier plans against the family."""
        known: dict[str, tuple[str, Criterion]] = {}
        for unit in self.list_units():
            split = split_fix_name(unit.name)
            if unit.name == parent.name:
                label = "parent"
            elif split is not None and split[0] == parent.name and (m := read_fix_marker(unit.path)) is not None:
                label = unit.name if m.parent == parent.id else ""
            else:
                label = ""
            if label:
                for c in self.criteria(unit):
                    known.setdefault(c.id, (label, c))
        return known

    def done_gate(self, unit: UnitRef) -> GateReport:
        """Every required leaf done; optional leaves and open optional branches do not count (L4-KSP-001)."""
        leaves = required_leaves(self.tasks(unit))
        if not leaves:
            return GateReport(False, ("the unit has no required tasks",))
        open_leaves = [t for t in leaves if not t.done]
        return GateReport(not open_leaves, tuple(f"task {t.key} is not done ({t.title})" for t in open_leaves))

    def archive(self, unit: UnitRef) -> ArchiveReport:
        """Kiro has no archive command: this checks the done-gate and reports. The caller records `archived` in the
        ledger. M1: spec-providers 1.12 (moving the folder to `kiro.archive_dir`)."""
        gate = self.done_gate(unit)
        if not gate.passed:
            raise ArchiveRefused(f"{unit.id} is not done: {'; '.join(gate.reasons)}")
        return ArchiveReport(unit.name, False)

    def is_exempt(self, task: Task) -> bool:
        """A human-written `[docs]`-style tag in the title that `tdd.exempt_task_kinds` lists (L4-IMP-003)."""
        tags = {m.lower() for m in re.findall(r"\[([A-Za-z0-9_-]+)\]", task.title)}
        return bool(tags & {k.lower() for k in self._exempt})

    def leaves_without_requirements(self, unit: UnitRef) -> list[Task]:
        """SPEC-004: the pending required leaves with no `_Requirements:_` link that are not TDD-exempt; a done leaf is
        finished history, which validation only warns about (L4-KSP-006)."""
        return [t for t in self._unlinked(unit) if not t.done]

    def _unlinked(self, unit: UnitRef) -> list[Task]:
        """Required leaves with no `_Requirements:_` link that are not TDD-exempt, done or not. A chore of a fix unit is
        the harness's own (its finding id is in the marker's `chores`), so it needs no link whatever the configured
        exempt kinds are (L4-FBK-008)."""
        directory = self.unit_dir(unit)
        return [
            t for t in required_leaves(self.tasks(unit))
            if not t.links and not self.is_exempt(t) and not chore_findings(directory, t.title)
        ]  # fmt: skip

    def validate(self, unit: UnitRef, strict: bool = True) -> ValidationReport:
        """File presence, task grammar, the graph JSON and that every `_Requirements:_` ref resolves. A leaf with no
        ref is an error under `sdd.enforce` and a warning otherwise."""
        directory = self.unit_dir(unit)
        has = {name: (directory / name).is_file() for name in ("tasks.md", "requirements.md", "bugfix.md", "design.md")}
        issues: list[ValidationIssue] = []
        if not has["tasks.md"]:
            issues.append(ValidationIssue("ERROR", "tasks.md", "tasks.md missing"))
        if not (has["requirements.md"] or has["bugfix.md"]):
            issues.append(ValidationIssue("ERROR", "requirements.md", "requirements.md or bugfix.md missing"))
        if not has["design.md"]:
            issues.append(ValidationIssue("WARNING", "design.md", "design.md missing"))
        if has["tasks.md"]:
            issues.extend(self._task_issues(unit, strict=strict))
        return ValidationReport(not any(i.level == "ERROR" for i in issues), tuple(issues))

    def _task_issues(self, unit: UnitRef, *, strict: bool) -> list[ValidationIssue]:
        data, text = self._tasks_text(unit)
        found: list[ValidationIssue] = []
        grammar: Literal["ERROR", "WARNING"] = "ERROR" if strict else "WARNING"
        for line in split_lines(data):
            body = line.text.removeprefix("\ufeff")
            if _LOOKS_LIKE_TASK.match(body) and not KIRO_TASK_RE.match(body):
                found.append(ValidationIssue(grammar, "tasks.md", "not a task under Kiro's grammar", line.number))
        tasks = parse_kiro_tasks(data)
        _, why, not_json = _read_graph(text, {t.key for t in tasks})
        if why:  # a block that is not JSON (a diagram) is read in document order, as the reader does (L4-KSP-006)
            found.append(
                ValidationIssue("WARNING" if not_json else "ERROR", "tasks.md", f"invalid Task Dependency Graph: {why}")
            )
        aliases = {c.alias for c in self.criteria(unit)}
        for task in tasks:
            for ref in task.links:
                if f"Req {ref}" not in aliases and not any(a.startswith(f"Req {ref}.") for a in aliases):
                    hint = _form_hint(ref, aliases)
                    message = f"task {task.key} cites _Requirements: {ref}_, which no criterion has{hint}"
                    found.append(ValidationIssue("WARNING" if task.done else "ERROR", "tasks.md", message, task.line))
        level: Literal["ERROR", "WARNING"] = "ERROR" if self._enforce else "WARNING"
        for task in self._unlinked(unit):
            message = f"task {task.key} has no _Requirements:_ line and is not TDD-exempt"
            found.append(ValidationIssue("WARNING" if task.done else level, "tasks.md", message, task.line))
        return found


# --- fix units (L4-FBK-008) ------------------------------------------------------------------------------------


# a finding's detail and the decisions in front of it, as much as OpenSpec's proposal keeps
MAX_ITEM_CHARS = 600 + MAX_DECISION_CHARS + 400
_DECIDED = ("Decided by ", "Requested by ")
_CONTINUE_TO = re.compile(r"\bTHEN\b.*\bSHALL CONTINUE TO\b")
MAX_REQUEST_LINE = 1800  # "Requested by <By> in FB-NNN (<kind>, <places>): " and the text, whole up to 1,200 characters
MAX_CODE_LINE = 600
# an unnumbered sentence: a criterion no test can trace would fail traceability (L4-FBK-008)
GENERIC_UNCHANGED = "The system SHALL CONTINUE TO satisfy every other acceptance criterion of {parent}."


def _line(text: str, limit: int = 160) -> str:
    """One line of plain text: model- and person-written text must not open a heading, a list or a numbered item."""
    one = " ".join(text.replace("[", "(").replace("]", ")").split()).lstrip("#>*-+ ")  # no `[tag]` from model text
    return one if len(one) <= limit else one[: limit - 3].rstrip() + "..."


def _sentence(scenario: str) -> str:
    """`- **WHEN** x` and `- **THEN** y` lines as the one line `WHEN x THEN y`."""
    return _line(" ".join(ln.strip().removeprefix("- ") for ln in scenario.splitlines()).replace("**", ""), 600)


class _FixItems:
    """The numbered items of a fix unit's `bugfix.md`: `2.n` per criterion a task fixes and per scenario, and one
    `3.n` per scenario that says `SHALL CONTINUE TO`. Everything else of the parent is kept by an unnumbered sentence.
    `refs[i]` are the item numbers the task of `findings[i]` cites (`2.1`); a chore cites none (its `[chore]` tag
    makes it TDD-exempt, SPEC-004)."""

    def __init__(
        self,
        parent: str,
        findings: Sequence[Finding],
        delta: SpecDelta | None,
        known: Mapping[str, tuple[str, Criterion]],
    ) -> None:
        self.parent, self.findings = parent, findings
        self.expected: list[str] = []
        self.unchanged: list[str] = []
        self.refs: list[list[str]] = [[] for _ in findings]
        for refs, finding in zip(self.refs, findings, strict=True):
            for cid in dict.fromkeys(finding.criteria):
                refs.append(self._add(self.expected, "2", self._restated(cid, known.get(cid))))
        for requirement in delta.requirements if delta else ():
            for scenario in requirement.scenarios:
                text = _sentence(scenario.text)
                kind, items = ("3", self.unchanged) if _CONTINUE_TO.search(text) else ("2", self.expected)
                ref = self._add(items, kind, text)
                for refs, finding in zip(self.refs, findings, strict=True):
                    if scenario.finding in finding.ids and ref not in refs:
                        refs.append(ref)
        for refs in self.refs:
            refs.sort(key=lambda r: tuple(int(n) for n in r.split(".")))

    @staticmethod
    def _add(items: list[str], kind: str, text: str) -> str:
        if text not in items:
            items.append(text)
        return f"{kind}.{items.index(text) + 1}"

    @staticmethod
    def _restated(cid: str, known: tuple[str, Criterion] | None) -> str:
        """The criterion's own text, where it is written and its id: the harness reads the item as that criterion."""
        if known is None:
            return f"WHEN criterion {cid} is exercised THEN the system SHALL satisfy it (parent criterion {cid})"
        label, criterion = known
        return f"{_line(criterion.text, MAX_ITEM_CHARS)} ({label} {criterion.alias}, {cid})"

    def bugfix(self) -> str:
        defects = "\n".join(f"1.{n} {_defect(f)}" for n, f in enumerate(self.findings, 1))
        expected = "\n".join(f"2.{n} {text}" for n, text in enumerate(self.expected, 1))
        generic = GENERIC_UNCHANGED.format(parent=self.parent)
        unchanged = "\n".join([generic, *([""] if self.unchanged else []), *(
            f"3.{n} {text}" for n, text in enumerate(self.unchanged, 1)
        )])  # fmt: skip
        return (
            "# Bugfix Requirements Document\n\n## Bug Analysis\n\n### Current Behavior (Defect)\n\n"
            f"{defects}\n\n### Expected Behavior (Correct)\n\n{expected or _NO_EXPECTED}\n\n"
            f"### Unchanged Behavior (Regression Prevention)\n\n{unchanged}\n"
        )


_NO_EXPECTED = "Every task of this fix unit is a chore: no behaviour is added, and the unchanged behavior below holds."


def _defect(finding: Finding) -> str:
    """The finding's title and detail on one line, the human's decisions first when the detail starts with them."""
    ids, title, detail = ", ".join(finding.ids), _line(finding.title), _line(finding.detail, MAX_ITEM_CHARS)
    if finding.request:  # a person's request first, whole, then the lines they quoted (L4-FBK-005)
        code = f" Quoted code: {_line(finding.code, MAX_CODE_LINE)}" if finding.code.strip() else ""
        return f"{_line(finding.request, MAX_REQUEST_LINE)}{code} ({title}; {ids})"
    if detail.startswith(_DECIDED):
        return f"{detail} ({title}; {ids})"
    return f"{title}: {detail} ({ids})" if detail else f"{title} ({ids})"


def _fix_design(parent: UnitRef, round: int, findings: Sequence[Finding], *, follow_up: bool = False) -> str:
    what = (
        f"Follow-up {round} of `{parent.name}`. `{parent.name}` was merged, and a person asked for the changes below "
        "in its `feedback.md`; each task of tasks.md names the findings it answers"
        if follow_up
        else f"Fix unit {round} of `{parent.name}`. The verifier found the problems below in `{parent.name}`; each "
        "task of tasks.md names the findings it answers"
    )
    parts = [
        "# Design Document\n\n## Overview\n",
        f"{what}, and bugfix.md says what must change and what must not.\n",
        "## Findings and Decisions\n",
    ]
    for finding in findings:
        parts.append(f"### {', '.join(finding.ids)}: {_line(finding.title)}\n")
        parts.append(
            f"Severity: {finding.severity}. {'Chore: a single phase, no red test.' if finding.chore else ''}".strip()
        )
        if finding.detail:
            parts.append("\n" + _line(finding.detail, MAX_ITEM_CHARS))
        if finding.request:
            parts.append("\n" + _line(finding.request, MAX_REQUEST_LINE))
            if finding.code.strip():  # an indented block: no line of it can open a heading or a fence
                quoted = (f"    {line}" if line.strip() else "" for line in finding.code.splitlines())
                parts.append("\n" + "\n".join(quoted))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _fix_tasks(findings: Sequence[Finding], refs: Sequence[Sequence[str]], ids: Mapping[str, str]) -> str:
    """One leaf per finding group under a parent, each with its `_Requirements:_` line, and a one-wave graph. The
    title cites the finding ids and the criteria the task fixes; a chore carries `[chore]` and the finding ids."""
    lines = ["# Implementation Plan", "", "- [ ] 1. Fix the findings of the verifier"]
    leaves: list[str] = []
    for number, (finding, cited) in enumerate(zip(findings, refs, strict=True), 1):
        criteria = [ids[f"Req {r}"] for r in cited if f"Req {r}" in ids]
        cites = "; ".join([", ".join(finding.ids), *([", ".join(dict.fromkeys(criteria))] if criteria else [])])
        tag = "[chore] " if finding.chore else ""
        lines.append(f"  - [ ] 1.{number} {tag}{_line(finding.title)} ({cites})")
        if cited:  # a chore cites nothing: its tag makes it TDD-exempt
            lines.append(f"    - _Requirements: {', '.join(cited)}_")
        leaves.append(f"1.{number}")
    graph = json.dumps({"waves": [{"id": 0, "tasks": leaves}]})
    return "\n".join(lines) + f"\n\n## Task Dependency Graph\n\n```json\n{graph}\n```\n"
