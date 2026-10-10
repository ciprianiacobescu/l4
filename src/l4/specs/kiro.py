"""The Kiro provider (SPEC 4.5): `.kiro/specs/<name>/` read from files, tasks written one byte at a time.

Kiro has no spec CLI, so nothing here starts a process. Only `x` is ever written; `-` and `~` are read.
M1: spec-providers 2.8 and 2.9 (fix units as bugfix specs), 1.12 (the `kiro.archive_dir` move), 4.2 (primary).
"""

import dataclasses
import json
import logging
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.specs.base import (
    ArchiveRefused,
    ArchiveReport,
    Criterion,
    Framework,
    GateReport,
    Marker,
    MarkerNotAllowed,
    ParentHasOpenChildren,
    SpecError,
    Task,
    Unit,
    UnitRef,
    ValidationIssue,
    ValidationReport,
)
from l4.specs.criteria import kiro_criteria
from l4.specs.detect import kiro_spec_dirs
from l4.specs.markers import MAX_TASKS_BYTES, Line, split_lines, write_marker

log = logging.getLogger("l4.spec")

KIRO_TASK_RE = re.compile(r"^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$")  # Kiro IDE 1.2.4, verbatim
_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?(?=\s|$)")
_LOOKS_LIKE_TASK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[^\]]*\]")
_REQUIREMENTS = re.compile(r"_Requirements:\s*([^_\n]*)_")
_REF = re.compile(r"\d+(?:\.\d+)*")
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
    heading = _GRAPH_HEADING.search(text)
    if heading is None:
        return None, None
    rest = text[heading.end() :]
    following = _NEXT_SECTION.search(rest)
    section = rest[: following.start()] if following else rest
    fence = _JSON_FENCE.search(section)
    if fence is None:
        return None, "no ```json block under the heading"
    try:
        document = json.loads(fence.group(1))
    except ValueError as exc:
        return None, f"the JSON does not parse ({exc})"
    waves = document.get("waves") if isinstance(document, dict) else None
    if not isinstance(waves, list):
        return None, 'the JSON has no "waves" list'
    by_task: dict[str, int] = {}
    seen_ids: set[int] = set()
    for wave in waves:
        wave_id = wave.get("id") if isinstance(wave, dict) else None
        ids = wave.get("tasks") if isinstance(wave, dict) else None
        if not isinstance(wave_id, int) or isinstance(wave_id, bool) or wave_id in seen_ids:
            return None, "a wave has no integer id, or its id repeats"
        if not isinstance(ids, list) or not all(isinstance(t, str) for t in ids):
            return None, f"wave {wave_id} has no list of task ids"
        seen_ids.add(wave_id)
        for task_id in ids:
            if task_id in by_task:
                return None, f"task {task_id} is in two waves"
            if known is not None and task_id not in known:
                return None, f"wave {wave_id} names task {task_id}, which is not in tasks.md"
            by_task[task_id] = wave_id
    return Waves(by_task), None


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
        self, repo: Path, *, root: str = ".kiro/specs", enforce: bool = False, exempt_kinds: Sequence[str] = ()
    ) -> None:
        relative = Path(root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise SpecError(f"spec.kiro.root must be a relative path inside the repo, got {root!r}")
        self._repo = repo
        self._root = root
        self._parts = relative.parts
        self._enforce = enforce
        self._exempt = tuple(exempt_kinds)

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
        """SPEC-004: required leaves with no `_Requirements:_` link that are not TDD-exempt."""
        return [t for t in required_leaves(self.tasks(unit)) if not t.links and not self.is_exempt(t)]

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
        _, why = parse_waves(text, {t.key for t in tasks})
        if why:
            found.append(ValidationIssue("ERROR", "tasks.md", f"invalid Task Dependency Graph: {why}"))
        aliases = {c.alias for c in self.criteria(unit)}
        for task in tasks:
            for ref in task.links:
                if f"Req {ref}" not in aliases:
                    hint = _form_hint(ref, aliases)
                    message = f"task {task.key} cites _Requirements: {ref}_, which no criterion has{hint}"
                    found.append(ValidationIssue("ERROR", "tasks.md", message, task.line))
        level: Literal["ERROR", "WARNING"] = "ERROR" if self._enforce else "WARNING"
        for task in self.leaves_without_requirements(unit):
            message = f"task {task.key} has no _Requirements:_ line and is not TDD-exempt"
            found.append(ValidationIssue(level, "tasks.md", message, task.line))
        return found
