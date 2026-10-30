"""A task that names a file `odd.forbidden_paths` forbids (forbidden-path-intake D2; L4-YOLO-092).

No agent step may write a path under a glob of `odd.forbidden_paths`: the write guard removes it after every step. A
task that tells the implementer to create one is therefore refused before any run, with the fix named. `forbidden_named`
reads a unit's spec files (and nothing else) and is pure apart from that read; `tree_has` answers whether a path exists
in the tree being checked.

A blocker needs all of: a pending required task, the task's own text (`task_text`), a file-like token (an extension, no
trailing `/`), absent from the tree, a glob match, and no negation word before the token on its line. Everything else
that matches is a warning, except a ticked task and a line that says not to touch the path, which give nothing.
"""

import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from l4.fsutil import UnsafeFile, read_regular_file
from l4.security.protected import ProtectedSet, forbidden_rule
from l4.specs.base import Framework, SpecError, Task, UnitRef
from l4.specs.kiro import kiro_tasks
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.paths import named_paths
from l4.specs.tasks_text import task_text
from l4.vcs.errors import GitError
from l4.vcs.git import Git

CODE = "forbidden_path"
# the phases of a unit that has not started implementing: the only ones in which the plan side refuses it
INTAKE_PHASES = frozenset({None, "intake", "ready"})
_NEGATION = re.compile(r"\b(?:do not|don['’]t|never|must not|without)\b", re.IGNORECASE)
# a line that says a person delivers the file: the task does not ask an agent to write it (before or after the path)
_PERSON_DELIVERS = re.compile(r"\b(?:a person (?:commits|adds)|committed by a person)\b", re.IGNORECASE)
_ANY_PATH = ("**",)  # every path-like token; `forbidden_rule` then walks the parent directories as the guard does
# the spec files a mention outside the tasks is read in, by framework (a path below the unit directory)
_OTHER_FILES = {
    Framework.OPENSPEC: ("proposal.md", "design.md"),
    Framework.KIRO: ("requirements.md", "bugfix.md", "design.md"),
}


@dataclass(frozen=True)
class PathFinding:
    """One match. `body` is the message without its code; a blocker's `message` is `<code>: <body>`
    (`forbidden_path`; `test_path` for the warnings of `l4.yolo.testpaths`), a warning is printed as
    `warning: <code>: <unit>: <body>`."""

    blocker: bool
    path: str
    rule: str
    body: str
    code: str = CODE

    @property
    def message(self) -> str:
        return f"{self.code}: {self.body}"


class TreeIndex:
    """The files a revision tracks, read once and on first use (a repository can be large and most plans name no
    forbidden path). `has(path)`: a tracked file, or a directory some tracked file is below; `nested(path)`: a tracked
    file whose path ends with `/<path>` (the same file one directory deeper, as in a monorepo). If `load` fails the
    answer is `fallback`'s (the files on disk), and `nested` is False: an unreadable tree must not block a unit."""

    def __init__(self, load: Callable[[], Iterable[str]], fallback: Callable[[str], bool] | None = None) -> None:
        self._load, self._fallback = load, fallback
        self._files: frozenset[str] | None = None
        self._dirs: frozenset[str] = frozenset()
        self._failed = False

    def _read(self) -> None:
        if self._files is not None:
            return
        try:
            files = frozenset(self._load())
        except (OSError, GitError):
            self._failed, self._files = True, frozenset()
            return
        self._files = files
        self._dirs = frozenset(parent for path in files for parent in PurePosixPath(path).parents if str(parent) != ".")

    def has(self, path: str) -> bool:
        self._read()
        if self._failed:
            return self._fallback(path) if self._fallback is not None else False
        assert self._files is not None
        name = path.rstrip("/")
        return name in self._files or PurePosixPath(name) in self._dirs

    def nested(self, path: str) -> bool:
        self._read()
        assert self._files is not None
        suffix = "/" + path.rstrip("/")
        return not self._failed and any(file.endswith(suffix) for file in self._files)


def tracked_tree(git: Git, rev: str | None = None) -> TreeIndex:
    """The tracked files of `rev` (`git ls-tree`), or of the index when there is no revision (a working-tree check: a
    staged file counts, an untracked one does not)."""

    def load() -> list[str]:
        args = ("ls-tree", "-r", "-z", "--name-only", rev) if rev else ("ls-files", "-z")
        return [os.fsdecode(name) for name in git.run_bytes(*args).split(b"\0") if name]

    return TreeIndex(load, lambda path: os.path.lexists(git.repo / path))


def _file_like(path: str) -> bool:
    return not path.endswith("/") and PurePosixPath(path).suffix != ""


def _fix(path: str, rule: str) -> str:
    reword = f"reword the task (for example `Do not create {path}`; a person commits it)"
    if ProtectedSet().match(path) is not None:  # a contract path: narrowing `odd.forbidden_paths` would not lift it
        return f"have a person commit {path} on the base branch first, or {reword}."
    return (
        f"in .l4/config.yaml on the base branch, set odd.forbidden_paths to an explicit list without {rule} "
        f"(there is no exclusion syntax), or have a person commit {path} on the base branch first, or {reword}."
    )


def _negated(line: str, path: str) -> bool:
    """Whether the line says to leave the path alone: a negation word before one of its occurrences (a `./` before the
    path is part of the occurrence), or a person delivering it anywhere on the line."""
    if _PERSON_DELIVERS.search(line):
        return True
    return any(
        _NEGATION.search(line[: found.start()])
        for found in re.finditer(rf"(?<![\w./-])(?:\./)?{re.escape(path)}", line)
    )


def _host_like(path: str) -> bool:
    """`github.com/org/repo/...`: the first segment of a path with a slash has a dot and does not start with one."""
    head = path.split("/", 1)[0]
    return "/" in path and "." in head and not head.startswith(".")


def _read(path: Path) -> bytes | None:
    try:
        return read_regular_file(path, limit=MAX_TASKS_BYTES)
    except (OSError, UnsafeFile, SpecError):
        return None


def _pending(ref: UnitRef, data: bytes) -> list[tuple[Task, str]]:
    tasks = parse_openspec_tasks(data) if ref.framework is Framework.OPENSPEC else kiro_tasks(data)
    return [(t, task_text(data, t, ref.framework)) for t in tasks if not t.done and not t.optional]


def forbidden_named(
    ref: UnitRef,
    tree_has: Callable[[str], bool],
    globs: Sequence[str],
    *,
    nested: Callable[[str], bool] | None = None,
) -> list[PathFinding]:
    """The blockers and warnings of `ref`'s spec files against `globs` (`odd.forbidden_paths`, `extra_forbidden_paths`
    applied). `tree_has(path)`: whether a file or directory exists in the tree checked; `nested(path)`: whether a
    tracked file ends with `/<path>` (a monorepo: the task may mean that one). At most one finding per source and
    path."""
    if not globs:
        return []
    found: list[PathFinding] = []

    def scan(text: str, where: str, *, task: bool) -> None:
        seen: set[str] = set()
        for line in text.splitlines():
            for path in named_paths(line, _ANY_PATH):
                rule = forbidden_rule(path, globs)
                if rule is None or ".." in path.split("/") or path in seen or _host_like(path):
                    continue
                if _negated(line, path):
                    continue
                seen.add(path)
                named = (
                    f"{where} names {path}, which odd.forbidden_paths rule {rule} forbids: no agent step may write it"
                )
                if not task:
                    found.append(PathFinding(False, path, rule, f"{named} (mentioned outside the tasks)"))
                elif not _file_like(path):
                    found.append(PathFinding(False, path, rule, f"{named} (a directory)"))
                elif tree_has(path):
                    found.append(PathFinding(False, path, rule, f"{named} (the file already exists in the tree)"))
                elif nested is not None and nested(path):
                    why = "a tracked file with that name exists below another directory"
                    found.append(PathFinding(False, path, rule, f"{named} ({why})"))
                else:
                    found.append(PathFinding(True, path, rule, f"{named}. Fix: {_fix(path, rule)}"))

    data = _read(ref.path / "tasks.md")
    if data is not None:
        for task, text in _pending(ref, data):
            scan(text, f"task {task.key}", task=True)
    names = list(_OTHER_FILES[ref.framework])
    if ref.framework is Framework.OPENSPEC and (ref.path / "specs").is_dir():
        names += sorted(p.relative_to(ref.path).as_posix() for p in (ref.path / "specs").rglob("spec.md"))
    for name in names:
        if (other := _read(ref.path / name)) is not None:
            scan(other.decode("utf-8", "replace"), name, task=False)
    return found
