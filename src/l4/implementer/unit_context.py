"""What a prompt carries of a unit, read, ranked and cut (kiro-prompt-context, L4-IMP-050 to L4-IMP-054).

`read_sources` reads the unit's spec files and names the ones it could not read whole; `task_block` is the task's
whole text from `tasks.md`. The planner (`plan_context`) fills a character budget in a fixed priority order, by whole
Markdown sections, and reports every cut. One builder (`prompt_inputs`) serves the run, the dry run and doctor, so that
they cannot drift apart. The implementer, the step-9 judge and the clarifier all use the planner.
"""

import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from l4.config.schema import L4Config, Profile
from l4.fsutil import MAX_SOURCE_BYTES as MAX_SOURCE_BYTES  # the one limit, shown here too
from l4.fsutil import UnsafeFile, read_regular_file, read_regular_prefix
from l4.specs.base import Criterion, Framework, Task, UnitRef
from l4.specs.criteria import own_criteria
from l4.specs.kiro import _REF
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.steering import SteeringDecision, decide_steering, openspec_context, read_steering, references_text
from l4.specs.tasks_text import _FENCE, _HEADING, enclosing_headings, task_text

CHARS_PER_TOKEN = 4  # [I] a rough estimate; the budget only bounds the prompt, it does not meter it
Reason = Literal["", "oversize", "symlink", "not_regular"]
# the files of a unit, in the order they are read; the prompt shows them in the order of `KIND_ORDER` below
UNIT_FILES = ("proposal.md", "design.md", "requirements.md", "bugfix.md")


@dataclass(frozen=True)
class SourceFile:
    """One spec file of a unit as it was read. `name` is relative to the unit directory (the block's source), `path`
    relative to the repository (what a person and the agent open). `total_bytes` is the file's size; `reason` says why
    `text` is not the whole file: `oversize` (the first `MAX_SOURCE_BYTES` were read), `symlink` or `not_regular` (not
    read, `text` is empty)."""

    name: str
    path: str
    text: str
    total_bytes: int
    reason: Reason = ""
    kind: str = ""  # narrative | design | proposal | base_spec; empty: decided from the name


def _rel(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.resolve().relative_to(repo.resolve()).as_posix()


def _read_one(path: Path, name: str, repo: Path) -> SourceFile | None:
    """The file `path`, or None when it does not exist. A link or a file that is not regular comes back unread."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    rel = _rel(path, repo)
    if stat.S_ISLNK(info.st_mode):
        return SourceFile(name, rel, "", 0, "symlink")
    if not stat.S_ISREG(info.st_mode):
        return SourceFile(name, rel, "", 0, "not_regular")
    try:
        data, size = read_regular_prefix(path, MAX_SOURCE_BYTES)
    except FileNotFoundError:
        return None
    except (UnsafeFile, OSError):
        return SourceFile(name, rel, "", 0, "not_regular")
    return SourceFile(
        name, rel, data.decode("utf-8", errors="replace"), size, "oversize" if size > MAX_SOURCE_BYTES else ""
    )


def read_sources(unit_dir: Path, repo: Path) -> tuple[SourceFile, ...]:
    """`proposal.md`, `design.md`, a Kiro unit's `requirements.md` and `bugfix.md`, and the spec deltas of the unit, in
    that order. Nothing is skipped silently: a file over `MAX_SOURCE_BYTES` is read up to it (`oversize`), a symbolic
    link or a file that is not regular comes back unread (`symlink`, `not_regular`), because the path is repository
    content. A file that does not exist is no source."""
    found = [s for name in UNIT_FILES if (s := _read_one(unit_dir / name, name, repo)) is not None]
    specs = unit_dir / "specs"
    try:
        info = os.lstat(specs)
    except FileNotFoundError:
        return tuple(found)
    if stat.S_ISLNK(info.st_mode):
        return (*found, SourceFile("specs", _rel(specs, repo), "", 0, "symlink"))
    if stat.S_ISDIR(info.st_mode):
        for directory in sorted(specs.iterdir(), key=lambda p: p.name):
            if directory.is_dir() and not directory.is_symlink():
                one = _read_one(directory / "spec.md", f"specs/{directory.name}/spec.md", repo)
                if one is not None:
                    found.append(one)
    return tuple(found)


def _ancestors(tasks: Sequence[Task], task: Task) -> list[Task]:
    """The tasks above `task` in the tree: the nearest earlier task of each lower depth."""
    stack: list[Task] = []
    for other in tasks:
        if other.line >= task.line:
            break
        while stack and stack[-1].depth >= other.depth:
            stack.pop()
        stack.append(other)
    while stack and stack[-1].depth >= task.depth:
        stack.pop()
    return stack


def task_block(data: bytes, task: Task, tasks: Sequence[Task], framework: Framework) -> str:
    """The task's whole block from `tasks.md` (L4-IMP-050): the Markdown headings that enclose it, each parent task's
    line (a Kiro tree; OpenSpec tasks are flat), then the task's own checkbox line and every line under it up to the
    next task or heading (detail bullets, `_Requirements:_`). Markers are read as `[ ]`. Raises `ValueError` when the
    task's line is not in `data`."""
    headings = "".join(f"{text}\n" for text in enclosing_headings(data, task.line))
    parents = _ancestors(tasks, task) if framework is Framework.KIRO else []
    return (
        headings + "".join(task_text(data, parent, framework) for parent in parents) + task_text(data, task, framework)
    )


@dataclass(frozen=True)
class Section:
    """A heading line through the line before the next heading (the preamble: the text before the first heading).
    Lines are 1-based and both ends are inclusive."""

    start: int
    end: int
    text: str
    heading: bool


def split_sections(text: str) -> list[Section]:
    """The sections of a Markdown text (`#` to `####` headings, outside a ``` or ~~~ fence, the rules of
    `tasks_text`). The pieces join back into `text`. Empty text has none."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    starts: list[int] = []
    fence: str | None = None
    for number, line in enumerate(lines):
        bare = line.rstrip("\r\n").removeprefix("﻿")
        if m := _FENCE.match(bare):
            fence = None if fence == m.group(1) else (fence or m.group(1))
            continue
        if fence is None and _HEADING.match(bare):
            starts.append(number)
    bounds = ([0] if not starts or starts[0] != 0 else []) + starts
    sections = []
    for index, first in enumerate(bounds):
        last = bounds[index + 1] if index + 1 < len(bounds) else len(lines)
        sections.append(Section(first + 1, last, "".join(lines[first:last]), first in starts))
    return sections


# -- which section does the task name (design D3) ----------------------------------------------------------------

_REQUIREMENT_WORD = re.compile(r"\b(?:requirements?|req|validates)\b", re.IGNORECASE)
_TICKED = re.compile(r"`([^`\n]{3,200})`")
_QUOTED = re.compile(r'"([^"\n]{8,200})"')
_PATH_TOKEN = re.compile(r"[\w.@\-/]+")
_EXTENSION = re.compile(r"\.\w{1,8}$")


@dataclass(frozen=True)
class Keys:
    """What names a section: the links of a Kiro leaf, the backticked tokens of the task block, and for an OpenSpec task
    the double-quoted strings of at least 8 characters (the requirement name it quotes)."""

    links: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()
    quoted: tuple[str, ...] = ()


def section_keys(block: str, links: Sequence[str], framework: Framework) -> Keys:
    """The keys of a task block (design D3)."""
    tokens = tuple(dict.fromkeys(m.group(1).strip() for m in _TICKED.finditer(block)))
    found = (m.group(1) for m in _QUOTED.finditer(block))
    quoted = tuple(dict.fromkeys(found)) if framework is Framework.OPENSPEC else ()
    return Keys(tuple(links), tokens, quoted)


def _link_names(number: str, link: str) -> bool:
    """`number` (a standalone number of a line) stands for `link`: the same, the link's requirement, or, for a bare
    link, one of its criteria."""
    if number == link or number == link.split(".")[0]:
        return True
    return "." not in link and number.startswith(f"{link}.")


def is_named(text: str, keys: Keys) -> bool:
    """A section names the task when a line has the word `requirement(s)`, `req` or `validates` and a standalone number
    that stands for one of the links, or when it holds a backticked token or quoted string of the block verbatim."""
    if any(token in text for token in (*keys.tokens, *keys.quoted)):
        return True
    if not keys.links:
        return False
    for line in text.splitlines():
        if _REQUIREMENT_WORD.search(line):
            numbers = _REF.findall(line)
            if any(_link_names(number, link) for number in numbers for link in keys.links):
                return True
    return False


def path_tokens(*texts: str) -> list[str]:
    """The backticked tokens that look like repository paths (a `/` or a file extension), in order, once each."""
    found = []
    for text in texts:
        for match in _TICKED.finditer(text):
            token = match.group(1).strip()
            if _PATH_TOKEN.fullmatch(token) and ("/" in token or _EXTENSION.search(token)) and token not in found:
                found.append(token)
    return found


# -- conventions, cuts and the planner (design D2, D4) -----------------------------------------------------------

MIN_CUT_CHARS = 2_000  # a piece is cut only when at least this much of the budget is left
CONVENTIONS_SHARE = 2  # the conventions may use 1/CONVENTIONS_SHARE of the budget
_GAP_COST = 48  # >= the marker line of a gap (`[not shown: lines A-B]`) with 7-digit line numbers
_CUT_COST = 48  # >= the marker line that ends a cut piece
_MAX_LISTED_RANGES = 8


@dataclass(frozen=True)
class Convention:
    """Project conventions as one piece: a Kiro steering file, an OpenSpec unit's `context`, or the root `AGENTS.md`.
    `path` is the block's source and what the cut list names. `readable` says whether the agent can open the file in
    its sandbox (the masks hide `.kiro/steering`)."""

    path: str
    text: str
    kind: str  # steering | openspec_context | agents_md
    readable: bool
    total_bytes: int = 0
    reason: str = ""  # "oversize" when `text` is the first part of a larger file


@dataclass(frozen=True)
class Cut:
    """A source or convention that is not in the prompt whole, for the cut list and `prompt.truncated`. `omitted` are
    line ranges (1-based, inclusive; `None` ends at the end of a file that was not read to its end)."""

    path: str
    kind: str  # steering | openspec_context | agents_md | narrative | design | proposal | base_spec
    reason: str  # budget | oversize | symlink | not_regular
    shown_chars: int
    total_chars: int
    total_bytes: int
    omitted: tuple[tuple[int, int | None], ...]
    readable: bool

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "path": self.path, "kind": self.kind, "reason": self.reason, "shown_chars": self.shown_chars,
            "total_chars": self.total_chars, "omitted": [list(r) for r in self.omitted], "readable": self.readable,
        }  # fmt: skip
        if self.total_bytes:
            data["total_bytes"] = self.total_bytes
        return data


def _ranges(omitted: Sequence[tuple[int, int | None]]) -> str:
    parts = []
    for start, end in omitted[:_MAX_LISTED_RANGES]:
        if end is None:
            parts.append(f"from line {start}")
        elif start == end:
            parts.append(f"line {start}")
        else:
            parts.append(f"{start}-{end}")
    text = ", ".join(parts)
    if len(omitted) > _MAX_LISTED_RANGES:
        text += f" (+{len(omitted) - _MAX_LISTED_RANGES} more)"
    return f"lines {text}" if text and not text.startswith(("from", "line ")) else text


def cut_line(cut: Cut) -> str:
    """One line of `# Not shown in full` (design D4)."""
    if cut.reason in ("symlink", "not_regular"):
        return f"- {cut.path}: not read ({cut.reason})"
    if cut.reason == "oversize":
        head = f"- {cut.path}: {min(cut.total_bytes, MAX_SOURCE_BYTES)} of {cut.total_bytes} bytes read (oversize)"
    else:
        head = f"- {cut.path}: {cut.shown_chars} of {cut.total_chars} characters shown (budget)"
    if not cut.readable:
        return f"{head}; not readable in this step's sandbox"
    return f"{head}; not shown: {_ranges(cut.omitted)}" if cut.omitted else head


def cut_summary(cut: Cut) -> str:
    """The short form of a cut for the dry run: the path and how much of it is shown."""
    if cut.reason in ("symlink", "not_regular"):
        return f"{cut.path} not read ({cut.reason})"
    if cut.reason == "oversize":
        return f"{cut.path} {min(cut.total_bytes, MAX_SOURCE_BYTES)} of {cut.total_bytes} bytes read (oversize)"
    return f"{cut.path} {cut.shown_chars} of {cut.total_chars} characters shown (budget)"


@dataclass(frozen=True)
class Piece:
    """A run of a planned block: kept text, or the one-line marker of what is not shown (`gap`) or cut (`cut`)."""

    start: int
    end: int
    text: str
    kind: Literal["text", "gap", "cut"]


@dataclass(frozen=True)
class PlannedBlock:
    """One data block of the prompt: its source and the pieces to show, in document order."""

    path: str
    pieces: tuple[Piece, ...]

    def body(self, *, numbered: bool = False) -> str:
        """The block's text. `numbered` puts the file's own line number before each kept line (`<n>: `), so that a
        citation of a line still resolves against the file when parts are left out."""
        out = []
        for piece in self.pieces:
            text = piece.text if piece.text.endswith("\n") else piece.text + "\n"
            if numbered and piece.kind == "text":
                lines = text.splitlines()
                text = "".join(f"{piece.start + i}: {line}\n" for i, line in enumerate(lines))
            out.append(text)
        return "".join(out).rstrip("\n") if out else ""


@dataclass(frozen=True)
class ContextPlan:
    conventions: tuple[PlannedBlock, ...]
    sources: tuple[PlannedBlock, ...]
    cuts: tuple[Cut, ...]


_RENDER_ORDER = {"narrative": 0, "design": 1, "proposal": 2, "base_spec": 3}


def kind_of(name: str) -> str:
    """Narrative (requirements, bugfix items, spec deltas), design, proposal or base spec, from a source's name."""
    base = name.rsplit("/", 1)[-1]
    if base in ("requirements.md", "bugfix.md") or name == "specs" or (base == "spec.md" and "specs/" in name):
        return "narrative"
    return {"design.md": "design", "proposal.md": "proposal"}.get(base, "proposal")


class _Doc:
    """A text being filled: its sections, which are taken and how many lines of a cut one."""

    def __init__(
        self, path: str, name: str, text: str, kind: str, reason: str, total_bytes: int, readable: bool,
        sections: Sequence[Section],
    ) -> None:  # fmt: skip
        self.path, self.name, self.kind, self.reason = path, name, kind, reason
        self.total_bytes, self.readable, self.text = total_bytes, readable, text
        self.sections = list(sections)
        self.lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        self.tail = reason == "oversize"  # the file continues past what was read: an unread run after the last section
        n = len(self.sections)
        self.taken = [0] * n  # lines taken of each section; a section is whole when it equals its line count
        self.size = [s.end - s.start + 1 for s in self.sections]
        self.overhead = len(f'<l4:data source="{name}">\n') + len("\n</l4:data>") + 1
        self.gaps = 0
        self.any = False
        self.cost = 0

    def whole(self, k: int) -> bool:
        return self.taken[k] == self.size[k]

    def _open(self, k: int) -> bool:
        """Section `k` exists and nothing of it is shown (a gap)."""
        return 0 <= k < len(self.sections) and self.taken[k] == 0

    def marginal(self, k: int, chars: int, *, cut: bool) -> int:
        """The characters added to the prompt by taking `chars` of section `k` (a cut one costs a marker too)."""
        left = self._open(k - 1)
        right = self._open(k + 1) or (k == len(self.sections) - 1 and self.tail)
        if not self.any:  # the first piece opens the block and every other section stays a gap
            gaps = (1 if k > 0 else 0) + (1 if k < len(self.sections) - 1 or self.tail else 0)
            return self.overhead + chars + gaps * _GAP_COST + (_CUT_COST if cut else 0)
        return chars + (int(left) + int(right) - 1) * _GAP_COST + (_CUT_COST if cut else 0)

    def take(self, k: int, lines: int, chars: int, cost: int) -> None:
        self.taken[k] = lines
        self.any = True
        self.cost += cost

    def runs(self) -> list[tuple[int, int | None]]:
        """The line ranges that are not shown, merged: the sections left out, the rest of a cut one, the unread tail."""
        out: list[tuple[int, int | None]] = []

        def add(start: int, end: int | None) -> None:
            if out and out[-1][1] is not None and out[-1][1] + 1 == start:
                out[-1] = (out[-1][0], end)
            else:
                out.append((start, end))

        for section, taken in zip(self.sections, self.taken, strict=True):
            if taken == 0:
                add(section.start, section.end)
            elif taken < section.end - section.start + 1:
                add(section.start + taken, section.end)
        if self.tail:
            add(self.lines + 1, None)
        return out

    def shown_text(self, k: int) -> str:
        section, taken = self.sections[k], self.taken[k]
        return section.text if taken == self.size[k] else "".join(section.text.splitlines(keepends=True)[:taken])

    def shown_chars(self) -> int:
        return sum(len(self.shown_text(k)) for k in range(len(self.sections)) if self.taken[k])

    def block(self) -> PlannedBlock | None:
        """The pieces in document order: kept text, a marker for each run left out, a marker after each cut piece."""
        if not self.any:
            return None
        pieces: list[Piece] = []
        gap_start: int | None = None

        def close_gap(end: int | None) -> None:
            nonlocal gap_start
            if gap_start is not None:
                a, b = gap_start, end
                label = f"from line {a}" if b is None else f"lines {a}-{b}"
                pieces.append(Piece(a, b if b is not None else a, f"[not shown: {label}]\n", "gap"))
                gap_start = None

        for k, section in enumerate(self.sections):
            taken = self.taken[k]
            if taken == 0:
                gap_start = section.start if gap_start is None else gap_start
                continue
            close_gap(section.start - 1)
            pieces.append(Piece(section.start, section.start + taken - 1, self.shown_text(k), "text"))
            if taken < self.size[k]:
                a = section.start + taken
                pieces.append(Piece(a, section.end, f"[cut: lines {a}-{section.end} not shown]\n", "cut"))
        close_gap(None if self.tail else self.sections[-1].end)
        if self.tail and gap_start is None:
            pieces.append(Piece(self.lines + 1, self.lines + 1, f"[not shown: from line {self.lines + 1}]\n", "gap"))
        return PlannedBlock(self.name, tuple(pieces))

    def cut(self) -> Cut | None:
        runs = self.runs()
        if not runs and self.reason not in ("symlink", "not_regular"):
            return None
        reason = self.reason if self.reason in ("oversize", "symlink", "not_regular") else "budget"
        readable = self.readable and reason not in ("symlink", "not_regular")
        return Cut(
            self.path, self.kind, reason, self.shown_chars(), len(self.text), self.total_bytes, tuple(runs), readable
        )  # fmt: skip


def _merged_sections(text: str) -> list[Section]:
    """`split_sections`, with a section of blank lines joined to its neighbour, so that blank runs are never a piece."""
    merged: list[Section] = []
    carry = ""
    carry_start = 0
    for section in split_sections(text):
        if not section.text.strip():
            if merged:
                last = merged[-1]
                merged[-1] = Section(last.start, section.end, last.text + section.text, last.heading)
            else:
                carry, carry_start = section.text, section.start
            continue
        if carry:
            section = Section(carry_start, section.end, carry + section.text, section.heading)
            carry = ""
        merged.append(section)
    return merged


def _doc_of_source(source: SourceFile) -> _Doc:
    kind = source.kind or kind_of(source.name)
    readable = source.reason not in ("symlink", "not_regular")
    return _Doc(
        source.path, source.name, source.text, kind, source.reason, source.total_bytes, readable,
        _merged_sections(source.text),
    )  # fmt: skip


def _doc_of_convention(conv: Convention) -> _Doc:
    lines = conv.text.splitlines(keepends=True)
    one = [Section(1, len(lines), conv.text, False)] if lines else []
    return _Doc(
        conv.path, conv.path, conv.text, conv.kind, conv.reason, conv.total_bytes, conv.readable, one
    )  # fmt: skip


def _fill(docs: Sequence[_Doc], order: Sequence[tuple[_Doc, int]], room: int) -> int:
    """Take the pieces in order while they fit (strict: the first that does not fit is cut at a line boundary when at
    least `MIN_CUT_CHARS` of the room is left, else left out, and every later piece is left out). Returns the room
    left."""
    for doc, k in order:
        section = doc.sections[k]
        chars = len(section.text)
        cost = doc.marginal(k, chars, cut=False)
        if cost <= room:
            doc.take(k, doc.size[k], chars, cost)
            room -= cost
            continue
        if room >= MIN_CUT_CHARS:
            lines = section.text.splitlines(keepends=True)
            best = (0, 0, 0)
            used = 0
            for taken, line in enumerate(lines[:-1], 1):  # the last line is the whole piece: that did not fit
                used += len(line)
                partial = doc.marginal(k, used, cut=True)
                if partial > room:
                    break
                best = (taken, used, partial)
            if best[0]:
                doc.take(k, best[0], best[1], best[2])
                room -= best[2]
        break
    return room


def plan_context(
    *, fixed_chars: int, budget_tokens: int, conventions: Sequence[Convention], source_files: Sequence[SourceFile],
    keys: Keys | None,
) -> ContextPlan:  # fmt: skip
    """Fill the budget (`budget_tokens` of `CHARS_PER_TOKEN` characters, less `fixed_chars` already charged) in the
    fixed order of design D2: the conventions first, at most half the budget, then the requirements narrative, the
    design and the proposal, each by whole sections, the sections `keys` name first. Every piece is whole or cut at a
    line boundary, and everything not shown is in `cuts`."""
    budget = max(budget_tokens, 1) * CHARS_PER_TOKEN
    return _plan(max(budget - fixed_chars, 0), budget // CONVENTIONS_SHARE, conventions, source_files, keys)


def _plan(
    room: int, cap: int, conventions: Sequence[Convention], source_files: Sequence[SourceFile], keys: Keys | None
) -> ContextPlan:  # fmt: skip
    convention_docs = [_doc_of_convention(c) for c in conventions]
    left = _fill(convention_docs, [(d, 0) for d in convention_docs if d.sections], min(room, cap))
    room -= min(room, cap) - left
    docs = [_doc_of_source(s) for s in source_files]
    named = lambda d, k: keys is not None and is_named(d.sections[k].text, keys)  # noqa: E731
    by_kind = {kind: [d for d in docs if d.kind == kind] for kind in _RENDER_ORDER}
    order: list[tuple[_Doc, int]] = []
    narrative = by_kind["narrative"]
    order += [(d, k) for d in narrative for k in range(len(d.sections)) if named(d, k)]
    order += [(d, k) for d in narrative for k in range(len(d.sections)) if not named(d, k)]
    design = by_kind["design"]
    order += [(d, k) for d in design for k in range(len(d.sections)) if named(d, k)]
    order += [(d, k) for d in design for k in range(len(d.sections)) if not named(d, k) and not d.sections[k].heading]
    order += [(d, k) for d in design for k in range(len(d.sections)) if not named(d, k) and d.sections[k].heading]
    for kind in ("proposal", "base_spec"):
        order += [(d, k) for d in by_kind[kind] for k in range(len(d.sections))]
    _fill(docs, order, room)
    shown = sorted(docs, key=lambda d: _RENDER_ORDER[d.kind])  # stable: the order the sources were given in
    blocks = tuple(b for d in shown if (b := d.block()) is not None)
    cuts = tuple(c for d in (*convention_docs, *shown) if (c := d.cut()) is not None)
    return ContextPlan(tuple(b for d in convention_docs if (b := d.block()) is not None), blocks, cuts)


# -- the budget and the one builder (design D7, D12) -------------------------------------------------------------


def effective_budget(cfg: L4Config, profile_name: str | None, profile: Profile | None) -> tuple[int, str]:
    """(tokens, source): the selected profile's own `context_budget_tokens` when it sets one, else
    `implementer.context_budget_tokens`. No model window is guessed (L4-IMP-053)."""
    if profile is not None and profile.context_budget_tokens is not None:
        return profile.context_budget_tokens, f"profile:{profile_name}"
    return cfg.implementer.context_budget_tokens, "implementer"


@dataclass(frozen=True)
class PromptInputs:
    """What the implementer's prompt needs of a unit besides the task and the gates; the run, the dry run and doctor all
    read it from `prompt_inputs`."""

    source_files: tuple[SourceFile, ...]
    conventions: tuple[Convention, ...]
    steering: list[dict[str, object]]  # every decision, recorded as `prompt.rendered.steering`
    task_block: str  # "" when `tasks.md` cannot be read: the prompt then falls back to the title and the links line
    budget_tokens: int
    budget_source: str
    unit_rel: str
    criteria: tuple[Criterion, ...]  # what the provider lists for the unit (a family's, for a fix unit)
    own_criteria: tuple[Criterion, ...]  # the unit's own: the links of its tasks name these


def _agents_md(root: Path) -> tuple[Convention | None, SteeringDecision | None]:
    path = root / "AGENTS.md"
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, None
    if stat.S_ISLNK(info.st_mode):
        return None, SteeringDecision("AGENTS.md", "none", False, "symlink")
    if not stat.S_ISREG(info.st_mode):
        return None, SteeringDecision("AGENTS.md", "none", False, "not_regular")
    try:
        data, size = read_regular_prefix(path, MAX_SOURCE_BYTES)
    except (OSError, UnsafeFile):
        return None, SteeringDecision("AGENTS.md", "none", False, "not_regular")
    text = data.decode("utf-8", errors="replace")
    reason = "oversize" if size > MAX_SOURCE_BYTES else ""
    decision = SteeringDecision("AGENTS.md", "agents_md", True, "include_agents_md")
    return Convention("AGENTS.md", text, "agents_md", True, size, reason), decision


def prompt_inputs(
    *, root: Path, provider: Any, ref: UnitRef, task: Task, tasks: Sequence[Task], changed: Sequence[str],
    cfg: L4Config, profile_name: str | None, profile: Profile | None,
) -> PromptInputs:  # fmt: skip
    """The unit's sources, its conventions (steering as Kiro's inclusion rules decide it, an OpenSpec unit's `context`,
    the root `AGENTS.md` when `implementer.include_agents_md` is on), the task's whole block and the budget. `root` is
    the worktree of a run and the checkout in a dry run or doctor; `changed` are the files the unit branch changed so
    far (they decide `fileMatch` steering)."""
    unit_dir = Path(provider.unit_dir(ref))
    sources = read_sources(unit_dir, root)
    try:
        data = read_regular_file(unit_dir / "tasks.md", limit=MAX_TASKS_BYTES)
        block = task_block(data, task, tasks, ref.framework)
        if task.title not in block:  # the file is not the one the task was read from (a dry run reads the checkout)
            block = ""
    except (OSError, UnsafeFile, ValueError):
        block = ""
    keys = section_keys(block or task.title, task.links, ref.framework)
    by_name = {s.name: s.text for s in sources}
    design = by_name.get("design.md", "")
    named_design = "".join(s.text for s in _merged_sections(design) if is_named(s.text, keys))
    paths = [*path_tokens(block or task.title, named_design), *changed]
    references = references_text([block, by_name.get("requirements.md", ""), by_name.get("bugfix.md", ""), design])
    files, decisions = read_steering(root)
    decisions = [*decisions, *decide_steering(files, paths, references)]
    steering = {f.path: f for f in files}
    included = sorted((d for d in decisions if d.included and d.path in steering), key=lambda d: d.bucket)
    conventions = [
        Convention(d.path, (f := steering[d.path]).body, "steering", False, f.total_bytes, f.reason)
        for d in included
    ]  # fmt: skip
    if cfg.implementer.include_agents_md:
        agents, decision = _agents_md(root)
        if decision is not None:
            decisions.append(decision)
        if agents is not None:
            after_always = sum(1 for d in included if d.bucket == 0)
            conventions.insert(after_always, agents)
    if ref.framework is Framework.OPENSPEC:
        context, decision = openspec_context(root, cfg.spec.openspec.root)
        if decision is not None:
            decisions.append(decision)
        if context is not None and decision is not None:
            conventions.append(Convention(decision.path, context, "openspec_context", True))
    tokens, source = effective_budget(cfg, profile_name, profile)
    return PromptInputs(
        sources, tuple(conventions), [d.as_dict() for d in decisions], block, tokens, source, _rel(unit_dir, root),
        tuple(provider.criteria(ref)), tuple(own_criteria(provider, ref)),
    )  # fmt: skip
