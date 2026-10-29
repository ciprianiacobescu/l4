"""A task that names a file `odd.forbidden_paths` forbids (forbidden-path-intake D2; L4-YOLO-092).

No agent step may write a path under a glob of `odd.forbidden_paths`: the write guard removes it after every step. A
task that tells the implementer to create one is therefore refused before any run, with the fix named. `forbidden_named`
reads a unit's spec files (and nothing else) and is pure apart from that read; `tree_has` answers whether a path exists
in the tree being checked.

A blocker needs all of: a pending required task, the task's own text (`task_text`), a file-like token (an extension, no
trailing `/`), absent from the tree, a glob match, and no negation word before the token on its line. Everything else
that matches is a warning, except a ticked task and a line that says not to touch the path, which give nothing.
"""

import re
from collections.abc import Callable, Sequence
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

CODE = "forbidden_path"
_NEGATION = re.compile(r"\b(?:do not|don['’]t|never|must not|without)\b", re.IGNORECASE)
_ANY_PATH = ("**",)  # every path-like token; `forbidden_rule` then walks the parent directories as the guard does
# the spec files a mention outside the tasks is read in, by framework (a path below the unit directory)
_OTHER_FILES = {
    Framework.OPENSPEC: ("proposal.md", "design.md"),
    Framework.KIRO: ("requirements.md", "bugfix.md", "design.md"),
}


@dataclass(frozen=True)
class PathFinding:
    """One match. `body` is the message without its code; a blocker's `message` is `forbidden_path: <body>`, a warning
    is printed as `warning: forbidden_path: <unit>: <body>`."""

    blocker: bool
    path: str
    rule: str
    body: str

    @property
    def message(self) -> str:
        return f"{CODE}: {self.body}"


def _file_like(path: str) -> bool:
    return not path.endswith("/") and PurePosixPath(path).suffix != ""


def _fix(path: str, rule: str) -> str:
    if ProtectedSet().match(path) is not None:  # a contract path: narrowing `odd.forbidden_paths` would not lift it
        return f"have a person commit {path} on the base branch first."
    return (
        f"in .l4/config.yaml on the base branch, set odd.forbidden_paths to an explicit list without {rule} "
        f"(there is no exclusion syntax), or have a person commit {path} on the base branch first."
    )


def _negated(line: str, path: str) -> bool:
    """Whether a negation word comes before the path on its line (before any one of its occurrences)."""
    return any(
        _NEGATION.search(line[: found.start()]) for found in re.finditer(rf"(?<![\w./-]){re.escape(path)}", line)
    )


def _read(path: Path) -> bytes | None:
    try:
        return read_regular_file(path, limit=MAX_TASKS_BYTES)
    except (OSError, UnsafeFile, SpecError):
        return None


def _pending(ref: UnitRef, data: bytes) -> list[tuple[Task, str]]:
    tasks = parse_openspec_tasks(data) if ref.framework is Framework.OPENSPEC else kiro_tasks(data)
    return [(t, task_text(data, t, ref.framework)) for t in tasks if not t.done and not t.optional]


def forbidden_named(ref: UnitRef, tree_has: Callable[[str], bool], globs: Sequence[str]) -> list[PathFinding]:
    """The blockers and warnings of `ref`'s spec files against `globs` (`odd.forbidden_paths`, `extra_forbidden_paths`
    applied). `tree_has(path)`: whether a file or directory exists in the tree checked. At most one finding per source
    and path."""
    if not globs:
        return []
    found: list[PathFinding] = []

    def scan(text: str, where: str, *, task: bool) -> None:
        seen: set[str] = set()
        for line in text.splitlines():
            for path in named_paths(line, _ANY_PATH):
                rule = forbidden_rule(path, globs)
                if rule is None or ".." in path.split("/") or path in seen or _negated(line, path):
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
