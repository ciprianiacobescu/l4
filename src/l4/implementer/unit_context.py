"""What a prompt carries of a unit, read, ranked and cut (kiro-prompt-context, L4-IMP-050 to L4-IMP-054).

`read_sources` reads the unit's spec files and names the ones it could not read whole; `task_block` is the task's
whole text from `tasks.md`. The planner (`plan_context`) fills a character budget in a fixed priority order, by whole
Markdown sections, and reports every cut. One builder (`prompt_inputs`) serves the run, the dry run and doctor, so that
they cannot drift apart. The implementer, the step-9 judge and the clarifier all use the planner.
"""

import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.fsutil import MAX_SOURCE_BYTES as MAX_SOURCE_BYTES  # the one limit, shown here too
from l4.fsutil import UnsafeFile, read_regular_prefix
from l4.specs.base import Framework, Task
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
