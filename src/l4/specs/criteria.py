"""Acceptance criteria and their stable ids (SPEC 4.7, L4-CRT-001)."""

import hashlib
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from l4.fsutil import UnsafeFile, read_regular_file
from l4.gates.junit import TestCase
from l4.specs.base import SAFE_NAME, Criterion, CriterionIdCollision, Framework, SpecError
from l4.specs.fixmark import read_fix_marker
from l4.vcs.git import Git

MAX_SPEC_BYTES = 1024 * 1024
ALIAS_SEPARATOR = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "

_SECTION = re.compile(r"^##\s+(ADDED|MODIFIED|REMOVED|RENAMED)\s+Requirements\s*$")
_BASE_SECTION = re.compile(r"^##\s+(Requirements)\s*$")  # the heading of an archived spec in `openspec/specs/`
_REQUIREMENT = re.compile(r"^###\s+Requirement:\s*(.+?)\s*$")
_SCENARIO = re.compile(r"^####\s+Scenario:\s*(.+?)\s*$")
_HEADING = re.compile(r"^#{1,6}\s")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CRITERIA_SECTIONS = ("ADDED", "MODIFIED")
_RENAMED_FROM = re.compile(r"^\s*[-*]\s*FROM:\s*`?###\s+Requirement:\s*(.+?)`?\s*$")
_NAMING = {"REMOVED": _REQUIREMENT, "RENAMED": _RENAMED_FROM}  # the delta sections that name a requirement going away


def normalise(text: str) -> str:
    """NFC, trimmed, whitespace runs collapsed to one space; case is kept. Changing this re-keys every id."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def criterion_id(framework: str, container: str, requirement: str, leaf: str) -> str:
    parts = "|".join(normalise(p) for p in (framework, container, requirement, leaf))
    return "C-" + hashlib.sha256(parts.encode("utf-8")).hexdigest()[:8]


def _scenarios(
    text: str, *, sections: tuple[str, ...] = _CRITERIA_SECTIONS, heading: re.Pattern[str] = _SECTION
) -> list[tuple[str, str, str, int]]:
    """(requirement, scenario, body, line) for every scenario under an ADDED or MODIFIED section."""
    found: list[tuple[str, str, str, int]] = []
    section: str | None = None
    requirement: str | None = None
    open_scenario: tuple[str, int] | None = None
    body: list[str] = []
    in_fence = False

    def close() -> None:
        nonlocal open_scenario, body
        if open_scenario and requirement is not None:
            found.append((requirement, open_scenario[0], "\n".join(body).strip(), open_scenario[1]))
        open_scenario, body = None, []

    for number, raw in enumerate(text.removeprefix("﻿").split("\n"), 1):
        line = raw.rstrip("\r")
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and _HEADING.match(line):
            close()
            if m := heading.match(line):
                section, requirement = m.group(1), None
            elif line.startswith("## "):
                section, requirement = None, None
            elif section in sections and (m := _REQUIREMENT.match(line)):
                requirement = m.group(1)
            elif section in sections and requirement is not None and (m := _SCENARIO.match(line)):
                open_scenario = (m.group(1), number)
            continue
        if open_scenario:
            body.append(line)
    close()
    return found


def openspec_criteria(unit_dir: Path) -> list[Criterion]:
    """Criteria of an OpenSpec change from its `specs/<capability>/spec.md` deltas, ordered by capability then line."""
    specs = unit_dir / "specs"
    if not specs.is_dir() or specs.is_symlink():
        return []
    criteria: list[Criterion] = []
    seen: dict[str, str] = {}
    for capability_dir in sorted(specs.iterdir(), key=lambda p: p.name):
        if not capability_dir.is_dir() or capability_dir.is_symlink() or not SAFE_NAME.match(capability_dir.name):
            continue
        spec = capability_dir / "spec.md"
        try:
            text = read_regular_file(spec, limit=MAX_SPEC_BYTES).decode("utf-8", "replace")
        except FileNotFoundError:
            continue
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None
        for requirement, scenario, body, line in _scenarios(text):
            alias = ALIAS_SEPARATOR.join((capability_dir.name, requirement, scenario))
            cid = criterion_id(Framework.OPENSPEC.value, capability_dir.name, requirement, scenario)
            if cid in seen:
                raise CriterionIdCollision(f"criteria {seen[cid]!r} and {alias!r} get the same id {cid}")
            seen[cid] = alias
            criteria.append(
                Criterion(
                    id=cid, alias=alias, framework=Framework.OPENSPEC, capability=capability_dir.name,
                    requirement=requirement, scenario=scenario, text=body,
                    source_path=f"specs/{capability_dir.name}/spec.md", source_line=line,
                )
            )  # fmt: skip
    return criteria


_KIRO_REQUIREMENT = re.compile(r"^###\s+Requirement\s+(\d+)\s*[:.\-\u2013\u2014]?\s*(.*?)\s*$", re.IGNORECASE)
_KIRO_CRITERIA_HEADING = re.compile(r"^####\s+Acceptance Criteria\s*:?\s*$", re.IGNORECASE)
_KIRO_ITEM = re.compile(r"^\s*(?:[-*]\s+)?(\d+)[.)]\s+(\S.*)$")  # `1. WHEN` and `1) WHEN`
# `1.1. WHEN`, `1.1) WHEN` and `1.1 WHEN`: the way Kiro and humans number a criterion by its requirement. Only the item
# of the requirement being read counts, so a decimal that starts a wrapped line is not taken for one; and only in a
# requirement with no plain `N.` / `N)` item, so a requirement read before this form existed keeps every id and alias
# (its `1.1 ...` sub-lines stay part of the criterion they continue).
_KIRO_DOTTED_ITEM = re.compile(r"^\s*(?:[-*]\s+)?(\d+)\.(\d+)[.)]?\s+(\S.*)$")
_KIRO_BUG_ITEM = re.compile(r"^\s*(?:[-*]\s+)?(\d+\.\d+)\.?\s+(\S.*)$")
# `(parent Req 1.2, C-1a2b3c4d)` at the end of a fix unit's Expected Behavior item: the item restates that criterion
_PARENT_ID = re.compile(r"\([^()]*\b(C-[0-9a-f]{8})\)\s*$")
_KIRO_STORY = re.compile(r"\*\*User Story:\*\*\s*(.+)$")
_KIRO_SECTION = re.compile(r"^#{2,3}\s+(.+?)\s*$")


def _kiro_item(line: str, bugfix: bool, number: str, dotted: bool) -> tuple[str, str] | None:
    """(written number, text) of a criterion line, or None. See `_KIRO_ITEM` and `_KIRO_DOTTED_ITEM`; `dotted`: the
    requirement being read has no plain item, so the dotted form counts."""
    if bugfix:
        m = _KIRO_BUG_ITEM.match(line)
        return (m.group(1), m.group(2)) if m else None
    if m := _KIRO_ITEM.match(line):
        return m.group(1), m.group(2)
    if dotted and (m := _KIRO_DOTTED_ITEM.match(line)) and m.group(1) == number:
        return f"{m.group(1)}.{m.group(2)}", m.group(3)
    return None


def _kiro_items(text: str, *, bugfix: bool) -> list[tuple[str, str, str, int]]:
    """(requirement title, alias number, criterion text, line) for every EARS line of a Kiro requirements or bugfix
    document. Feature specs number a criterion by its place in its requirement, bugfix specs write `N.M` themselves.
    Two readings: the plain items first; then the dotted form counts in the requirements that gave none."""
    plain = _kiro_scan(text, bugfix=bugfix, dotted=lambda _heading: False)
    if bugfix:
        return [item[:4] for item in plain]
    read = {item[4] for item in plain}  # the requirements (by heading line) a plain item was read in
    return [item[:4] for item in _kiro_scan(text, bugfix=False, dotted=lambda heading: heading not in read)]


def _kiro_scan(text: str, *, bugfix: bool, dotted: Callable[[int], bool]) -> list[tuple[str, str, str, int, int]]:
    """`_kiro_items` with the line of each item's `### Requirement N` heading (0 before any) last; `dotted(heading)`
    says whether the dotted form counts in that requirement."""
    found: list[tuple[str, str, str, int, int]] = []
    number, title, story, ordinal, heading = "", "", "", 0, 0
    section = ""  # bugfix: the `##`/`###` heading the item sits under
    in_list, in_fence = bugfix, False
    pending: tuple[str, int] | None = None  # (alias number, line) of the item being read
    parts: list[str] = []

    def requirement() -> str:
        return section if bugfix else (title or story or f"Requirement {number}")

    def flush() -> None:
        nonlocal pending, parts
        if pending is not None:
            found.append((requirement(), pending[0], " ".join(parts), pending[1], heading))
        pending, parts = None, []

    for line_no, raw in enumerate(text.removeprefix("\ufeff").split("\n"), 1):
        line = raw.rstrip("\r")
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _HEADING.match(line):
            flush()
            if bugfix:
                if m := _KIRO_SECTION.match(line):
                    section = normalise(m.group(1))
            elif m := _KIRO_REQUIREMENT.match(line):
                number, title, story, ordinal, in_list = m.group(1), normalise(m.group(2)), "", 0, False
                heading = line_no
            else:
                in_list = bool(_KIRO_CRITERIA_HEADING.match(line))
            continue
        if not bugfix and not in_list and (m := _KIRO_STORY.search(line)):
            story = normalise(m.group(1))
        elif in_list and (item := _kiro_item(line, bugfix, number, dotted(heading))):
            flush()
            if bugfix:
                label = item[0]
            else:
                ordinal += 1
                label = f"{number}.{ordinal}"  # by position, whatever the author wrote: aliases and ids stay put
            pending, parts = (label, line_no), [normalise(item[1])]
        elif pending is not None and line.strip() and line[:1] in " \t":
            parts.append(normalise(line))
        elif not line.strip():
            flush()
    flush()
    return found


def kiro_criteria(unit_dir: Path) -> list[Criterion]:
    """Criteria of a Kiro spec: the EARS lines of `requirements.md` (under each requirement's `Acceptance Criteria`)
    and `bugfix.md`. The id hashes the criterion's normalised text, never its number, so a criterion inserted between
    two others renumbers the aliases but moves no id (L4-CRT-001, SCN-CRT-05). In the `bugfix.md` of a fix unit only the
    `2.n` and `3.n` items are criteria (the `1.n` are the defect); any other bugfix spec keeps its `1.n`, which its
    tasks cite (review #1). In a fix unit (it has the harness's `.l4/fix.json`) a `2.n` item that ends in
    `(parent Req 1.2, C-1a2b3c4d)` has that id: the family counts the parent's criterion once (L4-FBK-008)."""
    criteria: list[Criterion] = []
    seen: dict[str, str] = {}
    fix_unit = read_fix_marker(unit_dir) is not None  # only the harness's marker lets an item name another id
    for filename, bugfix in (("requirements.md", False), ("bugfix.md", True)):
        try:
            text = read_regular_file(unit_dir / filename, limit=MAX_SPEC_BYTES).decode("utf-8", "replace")
        except FileNotFoundError:
            continue
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None
        for requirement, label, body, line in _kiro_items(text, bugfix=bugfix):
            if bugfix and fix_unit and label.startswith("1."):
                continue  # in a fix unit the Current Behavior (Defect) describes the bug; the criteria are 2.n and 3.n
            alias = f"Req {label}"
            cid = criterion_id(Framework.KIRO.value, unit_dir.name, requirement, body)
            if bugfix and fix_unit and label.startswith("2.") and (restated := _PARENT_ID.search(body)):
                cid = restated.group(1)  # a restated criterion of the parent is that criterion: counted once
            if cid in seen:
                raise CriterionIdCollision(f"criteria {seen[cid]!r} and {alias!r} get the same id {cid}")
            seen[cid] = alias
            criteria.append(
                Criterion(
                    id=cid, alias=alias, framework=Framework.KIRO, capability=unit_dir.name, requirement=requirement,
                    scenario=body, text=body, source_path=filename, source_line=line,
                )
            )  # fmt: skip
    return criteria


def _base_scenarios(capability: str, text: str) -> list[Criterion]:
    found: list[Criterion] = []
    for requirement, scenario, body, line in _scenarios(text, sections=("Requirements",), heading=_BASE_SECTION):
        alias = ALIAS_SEPARATOR.join((capability, requirement, scenario))
        found.append(
            Criterion(
                id=criterion_id(Framework.OPENSPEC.value, capability, requirement, scenario), alias=alias,
                framework=Framework.OPENSPEC, capability=capability, requirement=requirement,
                scenario=scenario, text=body, source_path=f"openspec/specs/{capability}/spec.md",
                source_line=line,
            )
        )  # fmt: skip
    return found


def base_criteria(specs_dir: Path) -> list[Criterion]:
    """The scenarios of the archived specs under `openspec/specs/<capability>/spec.md`. Their `source_path` is
    relative to the repository, not to a unit; nothing here raises for a damaged file: this is read for a lint
    that must not stop a run, so an unreadable or oversized spec is skipped. This reads the WORKTREE: the verifier's
    baseline must come from `base_criteria_at` instead (HB-3)."""
    if not specs_dir.is_dir() or specs_dir.is_symlink():
        return []
    found: list[Criterion] = []
    for capability_dir in sorted(specs_dir.iterdir(), key=lambda p: p.name):
        if not capability_dir.is_dir() or capability_dir.is_symlink() or not SAFE_NAME.match(capability_dir.name):
            continue
        try:
            text = read_regular_file(capability_dir / "spec.md", limit=MAX_SPEC_BYTES).decode("utf-8", "replace")
        except (UnsafeFile, OSError):
            continue
        found += _base_scenarios(capability_dir.name, text)
    return found


_BASE_SPEC_PATH = re.compile(r"openspec/specs/([^/]+)/spec\.md")


def base_criteria_at(git: Git, rev: str) -> list[Criterion]:
    """`base_criteria` as committed at `rev` (the unit's base commit), read from git: what the agent put in the
    worktree or committed after `rev` cannot make a criterion look unchanged (L4-VER-009, HB-3). A rev git does not
    know,
    a missing directory, a symlink and an oversized or damaged spec all give no criteria for that part."""
    listed = git.run("ls-tree", "-r", "-z", rev, "--", "openspec/specs/", check=False)
    if listed.returncode != 0:
        return []
    found: list[Criterion] = []
    entries = sorted(rec.partition("\t") for rec in listed.stdout.split("\0") if rec)
    for meta, _, path in sorted(entries, key=lambda e: e[2]):
        match = _BASE_SPEC_PATH.fullmatch(path)
        if not match or not SAFE_NAME.match(match.group(1)) or meta.split(" ")[0] not in {"100644", "100755"}:
            continue
        shown = git.run("show", f"{rev}:{path}", check=False)
        if shown.returncode != 0 or len(shown.stdout.encode("utf-8", "replace")) > MAX_SPEC_BYTES:
            continue
        found += _base_scenarios(match.group(1), shown.stdout)
    return found


def replaced_requirements(unit_dir: Path) -> frozenset[tuple[str, str]]:
    """(capability, requirement) of every requirement the change REMOVEs or RENAMEs away from: the change takes them
    out of the archived specs, so their scenarios no longer apply. Tolerant like `base_criteria`: it feeds a lint."""
    specs = unit_dir / "specs"
    if not specs.is_dir() or specs.is_symlink():
        return frozenset()
    found: set[tuple[str, str]] = set()
    for capability_dir in sorted(specs.iterdir(), key=lambda p: p.name):
        if not capability_dir.is_dir() or capability_dir.is_symlink() or not SAFE_NAME.match(capability_dir.name):
            continue
        try:
            text = read_regular_file(capability_dir / "spec.md", limit=MAX_SPEC_BYTES).decode("utf-8", "replace")
        except (UnsafeFile, OSError):
            continue
        section, in_fence = None, False
        for raw in text.removeprefix("\ufeff").split("\n"):
            line = raw.rstrip("\r")
            if _FENCE.match(line):
                in_fence = not in_fence
            elif in_fence:
                continue
            elif m := _SECTION.match(line):
                section = m.group(1)
            elif line.startswith("## "):
                section = None
            elif (pattern := _NAMING.get(section or "")) and (m := pattern.match(line)):
                found.add((capability_dir.name, normalise(m.group(1))))
    return frozenset(found)


# `C-xxxxxxxx`, `C_xxxxxxxx` and `c_xxxxxxxx` (any case) in a test id; the harness names `test_l4_c_<hex>` and
# `test_l4_audit_c_<hex>` are instances. Not embedded in a longer word or hex run.
_TRACE_ID = re.compile(r"(?<![A-Za-z0-9])C[-_]([0-9a-f]{8})(?![0-9a-f])", re.IGNORECASE)


def trace_ids(case: TestCase) -> frozenset[str]:
    """The criterion ids a reported test traces to (L4-CRT-002): the `l4` marker properties and the ids in its name or
    classname. Comments and failure messages never trace."""
    named = {f"C-{m.group(1).lower()}" for m in _TRACE_ID.finditer(case.id)}
    return frozenset(named | set(case.criteria))
