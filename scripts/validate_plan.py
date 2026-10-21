#!/usr/bin/env python3
"""Validate the delivery plans of a working tree without the harness: Python standard library only.

    python3 validate_plan.py [--repo DIR] [--frameworks auto|openspec|kiro|openspec,kiro]
                             [--openspec-root DIR] [--kiro-root DIR] [--json]

It reads every `.l4/plans/*.json`, finds the specs the way the harness's providers do, and reports what `l4 yolo check`
would report without a network or a model (yolo-mode design D15, requirement L4-YOLO-019). It never writes. Git is
optional: in a work tree it runs `git ls-files -co --exclude-standard` (read-only) to count only the files the review
sees; without git every file counts.

Exit 0: everything is valid. Exit 1: one line per problem, `error: <plan id>: <code>: <subject>: <text>`, or for the
coverage problems `error: uncovered: <unit> (...)` and `error: covered_twice: <unit> (...)`.
Exit 2: a usage or read error.

A planned unit whose OpenSpec change is archived is not an error here: the script has no plan state, so it cannot tell
a unit that this plan already merged or integrated (which `l4 yolo check` accepts) from a fresh plan that lists an
archived one (which `l4 yolo check` refuses as `unknown_unit`). It prints `finished: <id> (archived: l4 yolo check
refuses it as unknown_unit unless this plan already merged or integrated it)` and the exit code stays 0 if nothing else
is wrong.
"""

from __future__ import annotations

import argparse
import datetime
import decimal
import fnmatch
import heapq
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

SCHEMA = "l4/delivery-plan@1"
PLANS_DIR = ".l4/plans"
PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
CHANGE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # OpenSpec's kebab-case rule
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # a Kiro spec folder
KIRO_SPEC_FILES = ("requirements.md", "bugfix.md", "design.md", "tasks.md")
FIX_NAME = re.compile(r"^(?P<parent>.+)-fix-(?P<n>[1-9][0-9]*)$")
FOLLOW_UP_NAME = re.compile(r"^(?P<parent>.+)-followup-(?P<n>[1-9][0-9]*)$")
ARCHIVED = re.compile(r"^\d{4}-\d\d-\d\d-(?P<name>.+)$")
DEFAULT_OPENSPEC_ROOT = "openspec"
DEFAULT_KIRO_ROOT = ".kiro/specs"
FRAMEWORKS = ("openspec", "kiro")
SPEC_KEY = r"""^(?:spec|"spec"|'spec')\s*:"""  # the top-level key, plain or quoted like YAML allows
# The readiness review's limits and file rules (`l4.yolo.readiness`, `l4.yolo.digest`); a test holds them equal.
MAX_FILE_CHARS = 20_000
MAX_FOLDER_CHARS = 80_000
MAX_DEPENDENCY_CHARS = 20_000
EXCLUDED_DIRS = frozenset({".l4"})
EXCLUDED_FILES = frozenset({"verification.md", "questions.md", "feedback.md"})
TASK_MARKER = re.compile(rb"(?m)^((?:\xef\xbb\xbf)?[ \t\xc2\xa0]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]*\[)[ xX\-~](\])")
# The rules of `l4.specs.openspec` (`MIN_PURPOSE_CHARS`, `MAX_PURPOSE_BYTES`, `_purpose`); a test holds them equal.
MIN_PURPOSE_CHARS = 50
MAX_PURPOSE_BYTES = 256 * 1024
PURPOSE_SECTION = re.compile(r"(?im)^##[ \t]+Purpose[ \t]*\n(.*?)(?=^##[ \t]|\Z)", re.S)
HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
DELTA_SECTION = re.compile(r"^##[ \t]+(MODIFIED|RENAMED|REMOVED)[ \t]+Requirements[ \t]*$", re.M)
MAP_KEY = re.compile(r"""^(?:"([^"\\]+)"|'([^']+)'|([A-Za-z0-9_.-]+)):(?:\s+(.*))?$""")

HELP_EPILOG = """\
What this script checks, with the codes of `l4 yolo check` where the check is the same:
  invalid (schema, file name, limits), duplicate_id, self_dependency, unknown_dependency, cycle, unknown_unit,
  excluded_and_planned, external_dependencies, empty_plan; across the plan files: uncovered (a spec no plan lists,
  planned or excluded, except a <parent>-fix-<n> or <parent>-followup-<n> unit whose parent is listed) and
  covered_twice (a unit planned in two plan files); `yolo.hold` makes a spec it matches count as covered. For each
  OpenSpec unit that a plan file plans:
  spec_no_baseline (a MODIFIED, RENAMED or REMOVED section in a delta `specs/<capability>/spec.md` whose capability
  has no openspec/specs/<capability>/spec.md in the working tree) and spec_no_purpose (the delta of such a capability
  has no `## Purpose` of at least 50 characters); and material_over_budget: a file the readiness review would cut or
  leave out, read the way the review reads it (a planned unit's folder at 80,000 characters, a unit named in a
  depends_on at 20,000, each file at 20,000, or what `yolo.review.max_folder_chars`, `max_dependency_chars` and
  `max_file_chars` of .l4/config.yaml say; harness files and binary files are not read). A cut of a planned unit's
  own folder is a problem (exit 1). A dependency's cut is a line `warning: material_over_budget: ...` on standard
  output that leaves the exit code alone: the review lists it as not shown in full without blocking.

What only `l4 yolo check` can check (it needs git, the target head and the configuration): open questions, the intake
checks of each spec, finished units, acceptance profiles, the target against forge.base_branch, and the merge policy.
Specs are read from this working tree only: a spec that exists only on a branch is unknown here. An archived change
is known to an `exclude`, and a planned unit whose change is archived is accepted too, with a line
`finished: <id> (archived: ...)`: the script has no plan state, so it cannot tell a unit that this plan already
merged or integrated (`l4 yolo check` accepts it) from an archived unit in a fresh plan (`l4 yolo check` refuses it as
unknown_unit).

The frameworks and roots come from .l4/config.yaml (spec.frameworks, spec.openspec.root, spec.kiro.root) when it uses
the block style `l4 init` writes (keys may be quoted, a byte order mark is ignored); anything else falls back to
both frameworks, `openspec` and `.kiro/specs`, with a warning. The flags override the file. `yolo.hold` (unit ids
and fnmatch patterns) is read the same way: a spec it matches counts as covered; a yolo block in another style is
ignored, with a warning.
Exit 0 valid, 1 problems, 2 usage or read error.
"""


class UsageError(Exception):
    """A usage or read error: exit 2."""


class Unsupported(Exception):
    """The configuration uses YAML that the small reader does not handle."""


# --- discovery: the providers' rules, on the working tree ----------------------------------------------------------


def _symlink_on_path(repo: Path, parts: tuple[str, ...]) -> bool:
    """`fsutil.reject_symlinks`: a symlink on any component below `repo` (a missing component stops the walk)."""
    current = repo
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return True
    return False


def _dir(repo: Path, *parts: str) -> Path | None:
    """`detect._dir`: the directory below `repo`, unless the path leaves the checkout or crosses a symlink."""
    if not parts or ".." in parts or Path(*parts).is_absolute():
        return None
    if _symlink_on_path(repo, parts):
        return None
    path = repo.joinpath(*parts)
    return path if path.is_dir() else None


def openspec_units(repo: Path, root: str) -> list[str]:
    """`OpenSpecProvider.list_units`: the directories `<root>/changes/<kebab-name>` except `archive`."""
    relative = Path(root)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise UsageError(f"spec.openspec.root must be a relative path inside the repo, got {root!r}")
    parts = (*relative.parts, "changes")
    if _symlink_on_path(repo, parts):
        return []
    changes = repo.joinpath(*parts)
    if not changes.is_dir():
        return []
    return [
        f"openspec:{entry.name}"
        for entry in sorted(changes.iterdir(), key=lambda p: p.name)
        if entry.is_dir() and not entry.is_symlink() and entry.name != "archive" and CHANGE_NAME.match(entry.name)
    ]


def kiro_units(repo: Path, root: str) -> list[str]:
    """`detect.kiro_spec_dirs`: the directories `<root>/<name>` that hold a regular spec file."""
    base = _dir(repo, *Path(root).parts)
    if base is None:
        return []
    found = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_dir() or not SAFE_NAME.match(entry.name):
            continue
        if any((entry / name).is_file() and not (entry / name).is_symlink() for name in KIRO_SPEC_FILES):
            found.append(f"kiro:{entry.name}")
    return found


def _openspec_active(repo: Path, root: str) -> bool:
    """`detect._openspec`, the modern layout only (the legacy `project.md` layout is reported, never driven)."""
    base = _dir(repo, *Path(root).parts)
    if base is None:
        return False
    if any((base / name).is_file() for name in ("config.yaml", "config.yml")):
        return True
    if (base / "project.md").is_file():
        return False
    return any(_dir(repo, *Path(root).parts, name) for name in ("specs", "changes"))


def active_frameworks(repo: Path, frameworks: object, openspec_root: str, kiro_root: str) -> list[str]:
    """`detect.active_frameworks`: `auto` is what detection finds; a list names the frameworks and needs no files."""
    if frameworks == "auto":
        found = []
        if _openspec_active(repo, openspec_root):
            found.append("openspec")
        if kiro_units(repo, kiro_root):
            found.append("kiro")
        return found
    wanted = set(frameworks) if isinstance(frameworks, (list, tuple)) else set()
    return [f for f in FRAMEWORKS if f in wanted]


def archived_units(repo: Path, root: str) -> set[str]:
    """`openspec:<name>` for each `<root>/changes/archive/<date>-<name>` of the working tree. Not units (the harness
    reads them from the base branch, with a `feedback.md`): they only let an `exclude` name a finished change."""
    relative = Path(root)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return set()
    parts = (*relative.parts, "changes", "archive")
    if _symlink_on_path(repo, parts):
        return set()
    folder = repo.joinpath(*parts)
    if not folder.is_dir():
        return set()
    out = set()
    for entry in folder.iterdir():
        match = ARCHIVED.match(entry.name)
        if match and entry.is_dir() and not entry.is_symlink():
            out.add(f"openspec:{match.group('name')}")
    return out


# --- the OpenSpec deltas of a planned unit ------------------------------------------------------------------------


def _read_text(path: Path, limit: int = MAX_PURPOSE_BYTES) -> str | None:
    """A regular file's text (UTF-8, `replace`), or None when it is missing, a symlink, too big or unreadable."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            return None
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def normal_text(text: str) -> str:
    """A leading BOM and CRLF or CR line endings removed, as OpenSpec reads a spec."""
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def purpose_ok(text: str) -> bool:
    """`openspec._purpose`: the `## Purpose` section, on one line, has at least MIN_PURPOSE_CHARS characters."""
    match = PURPOSE_SECTION.search(normal_text(text))
    if not match:
        return False
    flat = " ".join(HTML_COMMENT.sub(" ", match.group(1)).split()).lstrip("#>*-+ ")
    return len(flat[:1500]) >= MIN_PURPOSE_CHARS


def purpose_problems(repo: Path, openspec_root: str, change: str) -> list[tuple[str, str, str]]:
    """(code, delta file, text) for each delta of the change `<root>/changes/<change>` (L4-ADO-009)."""
    root = Path(openspec_root)
    parts = (*root.parts, "changes", change, "specs")
    if _symlink_on_path(repo, parts):
        return []
    specs = repo.joinpath(*parts)
    if not specs.is_dir():
        return []
    found: list[tuple[str, str, str]] = []
    for entry in sorted(specs.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_dir():
            continue
        text = _read_text(entry / "spec.md")
        if text is None:
            continue
        delta_file = (entry / "spec.md").relative_to(repo).as_posix()
        baseline = (root / "specs" / entry.name / "spec.md").as_posix()
        if (repo / baseline).is_file():
            continue
        for kind in dict.fromkeys(m.group(1) for m in DELTA_SECTION.finditer(normal_text(text))):
            found.append(
                (
                    "spec_no_baseline",
                    delta_file,
                    f"{kind} Requirements, and the working tree has no {baseline}: archive the change that creates "
                    f"{entry.name} first, or write this delta as ## ADDED Requirements with a ## Purpose",
                )
            )
        if not purpose_ok(text):
            found.append(
                (
                    "spec_no_purpose",
                    delta_file,
                    f"{entry.name} is new to {(root / 'specs').as_posix()}/ and the delta has no ## Purpose of at "
                    f"least {MIN_PURPOSE_CHARS} characters (archive would write TBD and fail strict validation)",
                )
            )
    return found


# --- the readiness review's reading of a unit folder (yolo-mode design D4, L4-ADO-010) ---------------------------


class FolderRead:
    """`readiness.FolderText` for the working tree: what the review would show, cut and leave out of a folder."""

    def __init__(self) -> None:
        self.shown: list[tuple[str, int]] = []  # (repository path, characters shown, the cut marker included)
        self.cut: list[tuple[str, int]] = []  # (repository path, characters left out) of a file shown in part
        self.omitted: list[tuple[str, int]] = []  # (repository path, characters) of a file the folder budget dropped
        self.binary: list[str] = []


def _git_files(repo: Path, folder: str) -> list[str] | None:
    """What the review sees below `folder`: the tracked files and the untracked ones that git does not ignore
    (`git ls-files -co --exclude-standard`), or None when git is missing or `repo` is not a work tree."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "-co", "--exclude-standard", "--", folder],
            capture_output=True, timeout=60, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    names = [n.decode("utf-8", "surrogateescape") for n in done.stdout.split(b"\0") if n]
    return sorted(set(names))


def _folder_files(repo: Path, folder: str) -> list[str]:
    """Every file below `folder` that the review reads (repository paths), a symlink as a file, in UTF-8 byte order of
    the path: in a git work tree the tracked files and the untracked files that are not ignored (a file in
    `.gitignore` is not in the review's material), else every file."""
    found = _git_files(repo, folder.strip("/") or ".")
    if found is None:
        base = repo.joinpath(*Path(folder).parts)
        found = []
        for current, dirs, names in os.walk(base):
            here = Path(current)
            for name in [*names, *(d for d in dirs if (here / d).is_symlink())]:
                found.append((here / name).relative_to(repo).as_posix())
    return sorted(found, key=lambda path: path.encode("utf-8", "surrogateescape"))


def _rank(rel: str) -> int:
    """`readiness._rank`: the reading order of a prerequisite, what a dependent needs first and the task list last."""
    parts = Path(rel).parts
    if rel == "proposal.md":
        return 0
    if rel == "requirements.md":
        return 1
    if parts[0] == "specs" and parts[-1] == "spec.md":
        return 2
    return {"bugfix.md": 3, "design.md": 4, "tasks.md": 6}.get(rel, 5)


def read_folder(
    repo: Path, folder: str, *, budget: int, max_file: int = MAX_FILE_CHARS, order: str = "sorted"
) -> FolderRead:
    """`readiness.read_folder` on the working tree: skip the harness's files (`digest.is_excluded`), show a `tasks.md`
    with every task marker as `[ ]`, leave out a binary file, show each file up to `max_file` and the folder up to
    `budget`; a file the budget runs out in is cut (the `[cut: ...]` line counts), one after it is omitted. `order` is
    `"sorted"` (a planned unit's own folder) or `"prerequisite"` (a dependency: proposal, requirements, specs, bugfix,
    design, other files, `tasks.md` last)."""
    root = folder.strip("/")
    out = FolderRead()
    left = budget
    paths = _folder_files(repo, root)
    if order == "prerequisite":
        paths.sort(key=lambda p: _rank(Path(p).relative_to(root).as_posix()))  # stable: sorted within a rank
    for path in paths:
        parts = Path(path).relative_to(root).parts
        if any(p in EXCLUDED_DIRS for p in parts[:-1]) or parts[-1] in EXCLUDED_FILES:
            continue
        full = repo / path
        try:
            data = os.readlink(full).encode("utf-8", "surrogateescape") if full.is_symlink() else full.read_bytes()
        except OSError:
            continue
        if parts[-1] == "tasks.md":
            data = TASK_MARKER.sub(rb"\1 \2", data)
        if b"\0" in data:
            out.binary.append(path)
            continue
        text = data.decode("utf-8", "replace")
        shown = text[: min(max_file, max(left, 0))]
        if len(shown) < len(text):
            if left <= 0:
                out.omitted.append((path, len(text)))
                continue
            out.cut.append((path, len(text) - len(shown)))
            shown += f"\n[cut: {len(text) - len(shown)} characters omitted]"
        left -= len(shown)
        out.shown.append((path, len(shown)))
    return out


def unit_folder(unit_id: str, openspec_root: str, kiro_root: str) -> str:
    framework, _, name = unit_id.partition(":")
    return "/".join(
        [
            *Path(openspec_root if framework == "openspec" else kiro_root).parts,
            *(["changes"] if framework == "openspec" else []),
            name,
        ]
    )


def budget_lines(read: FolderRead) -> list[tuple[str, str]]:
    """(file, what the review does to it) for each cut and each omitted file."""
    return [(path, f"{n} characters cut") for path, n in read.cut] + [
        (path, f"omitted: the folder budget is spent ({size} characters)") for path, size in read.omitted
    ]


# --- the configuration: a small block-style reader -----------------------------------------------------------------


def _strip_comment(value: str) -> str:
    value = value.strip()
    if value.startswith("#"):  # `key:   # note` with its block below: the note is not the key's value
        return ""
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        while value[0] == '"' and end > 0 and value[end - 1] == "\\":
            end = value.find(value[0], end + 1)
        if end < 0:
            raise Unsupported("unterminated quote")
        rest = value[end + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise Unsupported("text after a quoted value")
        return value[: end + 1]
    cut = value.find(" #")
    return (value[:cut] if cut >= 0 else value).strip()


def _scalar(text: str) -> object:
    text = _strip_comment(text)
    if not text:
        return None
    if text[0] in "&*!|>{%@`":
        raise Unsupported(f"unsupported value {text[:12]!r}")
    if text[0] in ("'", '"'):
        inner = text[1:-1]
        return inner.replace("''", "'") if text[0] == "'" else inner.replace('\\"', '"').replace("\\\\", "\\")
    if text.startswith("["):
        if not text.endswith("]"):
            raise Unsupported("a flow list over several lines")
        body = text[1:-1].strip()
        return [_scalar(item) for item in body.split(",")] if body else []
    return None if text in ("~", "null") else text


def _logical_lines(block: list[str]) -> list[tuple[int, str]]:
    lines = []
    for raw in block:
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise Unsupported("a tab in the indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((len(raw) - len(raw.lstrip(" ")), stripped))
    return lines


def _parse_list(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list[object], int]:
    items: list[object] = []
    while i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
        body = lines[i][1][1:].strip()
        if re.match(r"^[^'\"\[{]+:(\s|$)", body):
            raise Unsupported("a mapping inside a list")
        items.append(_scalar(body))
        i += 1
    return items, i


def _parse_map(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict[str, object], int]:
    out: dict[str, object] = {}
    while i < len(lines) and lines[i][0] >= indent:
        ind, text = lines[i]
        if ind > indent:
            raise Unsupported("unexpected indentation")
        match = MAP_KEY.match(text)
        if not match:
            raise Unsupported(f"cannot read {text[:20]!r}")
        key, rest = next(g for g in match.groups()[:3] if g is not None), match.group(4)
        i += 1
        if rest is not None and _strip_comment(rest):
            out[key] = _scalar(rest)
        elif i < len(lines) and lines[i][0] > indent:
            if lines[i][1] == "-" or lines[i][1].startswith("- "):
                out[key], i = _parse_list(lines, i, lines[i][0])
            else:
                out[key], i = _parse_map(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
            out[key], i = _parse_list(lines, i, indent)  # YAML's own dumper puts a list at its key's indent
        else:
            out[key] = None
    return out, i


def _config_rows(repo: Path) -> list[str] | str:
    """The rows of .l4/config.yaml, or the warning that says why they cannot be read."""
    path = repo / ".l4" / "config.yaml"
    try:
        return path.read_text(encoding="utf-8-sig").splitlines()  # a byte order mark is not part of the first key
    except FileNotFoundError:
        return f"{path.relative_to(repo).as_posix()} not found: using the default frameworks and roots"
    except (OSError, UnicodeDecodeError) as exc:
        return f".l4/config.yaml cannot be read ({exc.__class__.__name__}): using the default frameworks and roots"


def _top_block(rows: list[str], key: str) -> tuple[dict[str, object], str | None]:
    """(the mapping under the top-level `key`, why it cannot be read or None). {} when the file has no such key."""
    key_row = r"""^(?:%s|"%s"|'%s')\s*:""" % ((re.escape(key),) * 3)
    start = next((n for n, row in enumerate(rows) if re.match(key_row + r"\s*(#.*)?$", row)), None)
    if start is None:
        if any(re.match(key_row, row) for row in rows):
            return {}, "is not in block style"
        return {}, None
    block = []
    for row in rows[start + 1 :]:
        if row.strip() and not row.startswith((" ", "\t", "#")):
            break
        block.append(row)
    try:
        lines = _logical_lines(block)
        return (_parse_map(lines, 0, lines[0][0])[0] if lines else {}), None
    except Unsupported as exc:
        return {}, f"is not block style ({exc})"


def read_spec_config(repo: Path) -> tuple[dict[str, object], list[str]]:
    """(the `spec` mapping of .l4/config.yaml, warnings). {} when the file has no `spec` key."""
    rows = _config_rows(repo)
    if isinstance(rows, str):
        return {}, [rows]
    parsed, why = _top_block(rows, "spec")
    if why is not None:
        return {}, [f"spec in .l4/config.yaml {why}: using the default frameworks and roots"]
    return parsed, []


def read_review_limits(repo: Path) -> tuple[tuple[int, int, int], list[str]]:
    """((max_file_chars, max_folder_chars, max_dependency_chars), warnings) from `yolo.review` of .l4/config.yaml:
    the module constants where a key is absent or invalid (not an integer, below 1000 for the file and folder
    budgets, below 0 for the dependency budget), with one warning per invalid key."""
    limits = {
        "max_file_chars": MAX_FILE_CHARS,
        "max_folder_chars": MAX_FOLDER_CHARS,
        "max_dependency_chars": MAX_DEPENDENCY_CHARS,
    }
    defaults = (MAX_FILE_CHARS, MAX_FOLDER_CHARS, MAX_DEPENDENCY_CHARS)
    rows = _config_rows(repo)
    if isinstance(rows, str):
        return defaults, []
    parsed, why = _top_block(rows, "yolo")
    if why is not None:
        return defaults, []  # read_yolo_hold has said so
    section = parsed.get("review")
    warnings: list[str] = []
    if section is not None and not isinstance(section, dict):
        warnings.append("yolo.review in .l4/config.yaml is not a mapping: the default review budgets are used")
        section = {}
    for key, floor in (("max_file_chars", 1000), ("max_folder_chars", 1000), ("max_dependency_chars", 0)):
        raw = (section or {}).get(key)
        if raw is None:
            continue
        if isinstance(raw, str) and re.fullmatch(r"-?[0-9]+(?:_[0-9]+)*", raw) and int(raw) >= floor:
            limits[key] = int(raw)
        else:
            warnings.append(
                f"yolo.review.{key} in .l4/config.yaml is not an integer of at least {floor}: "
                f"the default {limits[key]} is used"
            )
    return (limits["max_file_chars"], limits["max_folder_chars"], limits["max_dependency_chars"]), warnings


def read_yolo_hold(repo: Path) -> tuple[list[str], list[str]]:
    """(`yolo.hold` of .l4/config.yaml, warnings): unit ids and fnmatch patterns (L4-ADO-011). A file that is missing
    adds no warning here (`read_spec_config` has said so); one that this reader cannot read holds nothing."""
    rows = _config_rows(repo)
    if isinstance(rows, str):
        return [], []
    parsed, why = _top_block(rows, "yolo")
    if why is not None:
        return [], [f"yolo in .l4/config.yaml {why}: yolo.hold is ignored"]
    hold = parsed.get("hold")
    if hold is None:
        return [], []
    if not isinstance(hold, list) or not all(isinstance(h, str) and h for h in hold):
        return [], ["yolo.hold in .l4/config.yaml is not a list of non-empty strings: yolo.hold is ignored"]
    return [str(h) for h in hold], []


def resolve_discovery(repo: Path, args: argparse.Namespace) -> tuple[object, str, str, list[str]]:
    """(frameworks, openspec root, kiro root, warnings): flags over the file over the defaults."""
    spec, warnings = read_spec_config(repo)
    fell_back = bool(warnings)
    frameworks: object = "auto" if not fell_back else list(FRAMEWORKS)
    openspec_root, kiro_root = DEFAULT_OPENSPEC_ROOT, DEFAULT_KIRO_ROOT
    configured = spec.get("frameworks")
    if configured is not None:
        names = configured if isinstance(configured, list) else [configured]
        if names == ["auto"]:
            frameworks = "auto"
        elif names and all(n in FRAMEWORKS for n in names):
            frameworks = names
        else:
            warnings.append("spec.frameworks in .l4/config.yaml is not auto, openspec or kiro: using both")
            frameworks = list(FRAMEWORKS)
    for key in ("openspec", "kiro"):
        section = spec.get(key)
        if isinstance(section, dict) and isinstance(section.get("root"), str) and section["root"]:
            if key == "openspec":
                openspec_root = section["root"]
            else:
                kiro_root = section["root"]
        elif section is not None and not isinstance(section, dict):
            warnings.append(f"spec.{key} in .l4/config.yaml is not a mapping: using the default root")
    if args.frameworks is not None:
        names = [n.strip() for n in args.frameworks.split(",") if n.strip()]
        if names == ["auto"]:
            frameworks = "auto"
        elif names and all(n in FRAMEWORKS for n in names):
            frameworks = names
        else:
            raise UsageError("--frameworks takes auto, openspec, kiro or openspec,kiro")
    if args.openspec_root is not None:
        openspec_root = args.openspec_root
    if args.kiro_root is not None:
        kiro_root = args.kiro_root
    return frameworks, openspec_root, kiro_root, warnings


def discover_units(repo: Path, args: argparse.Namespace) -> tuple[list[str], set[str], list[str]]:
    """(unit ids, archived ids an exclusion may name, warnings)."""
    frameworks, openspec_root, kiro_root, warnings = resolve_discovery(repo, args)
    active = active_frameworks(repo, frameworks, openspec_root, kiro_root)
    units: list[str] = []
    archived: set[str] = set()
    if "openspec" in active:
        units += openspec_units(repo, openspec_root)
        archived = archived_units(repo, openspec_root)
    if "kiro" in active:
        units += kiro_units(repo, kiro_root)
    return units, archived, warnings


# --- the schema: the rules of model.py, by hand --------------------------------------------------------------------

Problem = tuple[str, str]  # (subject, text)

_DATETIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt_ ](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?(?:([Zz])|([+-])(\d{2}):?(\d{2}))?$"
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_UNIX_TIME = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$")
# The Unix times pydantic accepts as a string (measured against `model.load_plan`, which is the reference): a whole
# number counts as seconds up to 20e9 and as milliseconds above, so it must lie in these milliseconds; a number with a
# point is read as a float, whose limits are these (to within the float's own rounding at the very edge).
_UNIX_MS_MIN, _UNIX_MS_MAX = -62135596800000, 253402300799999
_UNIX_FRACTION_MIN, _UNIX_FRACTION_MAX = decimal.Decimal("-62135596800134860"), decimal.Decimal("253402300799181840")


def _unix_time_ok(value: str) -> bool:
    number = decimal.Decimal(value)
    if "." in value:
        return _UNIX_FRACTION_MIN < number <= _UNIX_FRACTION_MAX
    return _UNIX_MS_MIN <= number <= _UNIX_MS_MAX


def _datetime_problem(value: object) -> str | None:
    """None when `value` is a datetime string with a time zone (pydantic's rules for an ISO 8601 string; a string
    that is a number is a Unix time, which carries its zone)."""
    if not isinstance(value, str):
        return "Input should be a valid datetime"
    if _UNIX_TIME.match(value):
        return None if _unix_time_ok(value) else "Input should be a valid datetime, the Unix time is out of range"
    match = _DATETIME.match(value)
    if not match:
        return "Input should be a valid datetime"
    year, month, day, hour, minute = (int(match.group(n)) for n in range(1, 6))
    second = int(match.group(6) or 0)
    try:
        datetime.date(year, month, day)
    except ValueError:
        return "Input should be a valid datetime, day value is outside expected range"
    if hour > 23 or minute > 59 or second > 59:
        return "Input should be a valid datetime, a time value is outside the expected range"
    if match.group(8):
        if int(match.group(9)) > 23 or int(match.group(10)) > 59:
            return "Input should be a valid datetime, the timezone offset is outside the expected range"
    elif not match.group(7):
        return "the deadline must carry a time zone (for example 2026-12-31T18:00:00Z)"
    return None


def _unknown(obj: dict, allowed: tuple[str, ...], where: str) -> list[Problem]:
    return [(f"{where}{key}", "unknown field") for key in obj if key not in allowed]


def _strings(value: object, where: str) -> list[Problem]:
    if not isinstance(value, list):
        return [(where, "Input should be a valid array")]
    return [
        (f"{where}.{n}", "Input should be a valid string") for n, item in enumerate(value) if not isinstance(item, str)
    ]


def _unit_problems(unit: object, where: str) -> list[Problem]:
    if not isinstance(unit, dict):
        return [(where, "Input should be an object")]
    out = _unknown(unit, ("id", "depends_on", "acceptance_profile"), f"{where}.")
    if "id" not in unit:
        out.append((f"{where}.id", "Field required"))
    elif not isinstance(unit["id"], str):
        out.append((f"{where}.id", "Input should be a valid string"))
    if "depends_on" in unit:
        out += _strings(unit["depends_on"], f"{where}.depends_on")
    if "acceptance_profile" in unit and not isinstance(unit["acceptance_profile"], str):
        out.append((f"{where}.acceptance_profile", "Input should be a valid string"))
    return out


def _batch_problems(batch: object, where: str) -> list[Problem]:
    if not isinstance(batch, dict):
        return [(where, "Input should be an object")]
    out = _unknown(batch, ("id", "depends_on", "acceptance_profile", "units"), f"{where}.")
    if "id" not in batch:
        out.append((f"{where}.id", "Field required"))
    elif not isinstance(batch["id"], str):
        out.append((f"{where}.id", "Input should be a valid string"))
    if "depends_on" in batch:
        out += _strings(batch["depends_on"], f"{where}.depends_on")
    if "acceptance_profile" in batch and not isinstance(batch["acceptance_profile"], str):
        out.append((f"{where}.acceptance_profile", "Input should be a valid string"))
    if "units" not in batch:
        out.append((f"{where}.units", "Field required"))
    elif not isinstance(batch["units"], list):
        out.append((f"{where}.units", "Input should be a valid array"))
    else:
        for n, unit in enumerate(batch["units"]):
            out += _unit_problems(unit, f"{where}.units.{n}")
    return out


def _limits_problems(limits: object) -> list[Problem]:
    if not isinstance(limits, dict):
        return [("limits", "Input should be an object")]
    out = _unknown(limits, ("max_cost_usd", "max_unit_attempts", "max_runs", "deadline"), "limits.")
    cost = limits.get("max_cost_usd")
    if cost is not None and not _is_number(cost):
        out.append(("limits.max_cost_usd", "Input should be a valid number"))
    elif cost is not None and not cost >= 0:
        out.append(("limits.max_cost_usd", "Input should be greater than or equal to 0"))
    if "max_unit_attempts" in limits:
        value = limits["max_unit_attempts"]
        if not _is_int(value):
            out.append(("limits.max_unit_attempts", "Input should be a valid integer"))
        elif value < 1:
            out.append(("limits.max_unit_attempts", "Input should be greater than or equal to 1"))
    runs = limits.get("max_runs")
    if runs is not None and not _is_int(runs):
        out.append(("limits.max_runs", "Input should be a valid integer"))
    elif runs is not None and runs < 1:
        out.append(("limits.max_runs", "Input should be greater than or equal to 1"))
    if limits.get("deadline") is not None and (why := _datetime_problem(limits["deadline"])) is not None:
        out.append(("limits.deadline", why))
    return out


def _exclusion_problems(entry: object, where: str) -> list[Problem]:
    if not isinstance(entry, dict):
        return [(where, "Input should be an object")]
    out = _unknown(entry, ("id", "reason"), f"{where}.")
    if "id" not in entry:
        out.append((f"{where}.id", "Field required"))
    elif not isinstance(entry["id"], str):
        out.append((f"{where}.id", "Input should be a valid string"))
    if "reason" not in entry:
        out.append((f"{where}.reason", "Field required"))
    elif not isinstance(entry["reason"], str):
        out.append((f"{where}.reason", "Input should be a valid string"))
    elif not 1 <= len(entry["reason"]) <= 200:
        out.append((f"{where}.reason", "the reason must have 1 to 200 characters"))
    return out


def schema_problems(raw: dict, file_name: str) -> tuple[list[Problem], str]:
    """(problems, code): what `model.load_plan` refuses for this JSON object. The code is `invalid`, or
    `external_dependencies` when that is the only reason."""
    out: list[Problem] = []
    allowed = ("schema", "schema_id", "plan_id", "target", "merge", "promotion", "limits", "external_dependencies",
               "batches", "exclude")  # fmt: skip
    out += _unknown(raw, allowed, "")
    schema = raw["schema"] if "schema" in raw else raw.get("schema_id")
    if "schema" not in raw and "schema_id" not in raw:
        out.append(("schema", "Field required"))
    elif schema != SCHEMA:
        out.append(("schema", f"Input should be {SCHEMA!r}"))
    for key in ("plan_id", "target"):
        if key not in raw:
            out.append((key, "Field required"))
        elif not isinstance(raw[key], str):
            out.append((key, "Input should be a valid string"))
    if "merge" not in raw:
        out.append(("merge", "Field required"))
    elif raw["merge"] not in ("human", "auto") or not isinstance(raw["merge"], str):
        out.append(("merge", "Input should be 'human' or 'auto'"))
    promotion = raw.get("promotion")
    if promotion is not None:
        if not isinstance(promotion, dict):
            out.append(("promotion", "Input should be an object"))
        else:
            out += _unknown(promotion, ("mode", "target_branch"), "promotion.")
            if "mode" not in promotion:
                out.append(("promotion.mode", "Field required"))
            elif promotion["mode"] != "manual" or not isinstance(promotion["mode"], str):
                out.append(("promotion.mode", "Input should be 'manual'"))
            if "target_branch" not in promotion:
                out.append(("promotion.target_branch", "Field required"))
            elif not isinstance(promotion["target_branch"], str):
                out.append(("promotion.target_branch", "Input should be a valid string"))
    if "limits" in raw:
        out += _limits_problems(raw["limits"])
    external = raw.get("external_dependencies", [])
    if not isinstance(external, list):
        out.append(("external_dependencies", "Input should be a valid array"))
    else:
        out += [
            (f"external_dependencies.{n}", "Input should be an object")
            for n, item in enumerate(external)
            if not isinstance(item, dict)
        ]
    if "batches" not in raw:
        out.append(("batches", "Field required"))
    elif not isinstance(raw["batches"], list):
        out.append(("batches", "Input should be a valid array"))
    else:
        for n, batch in enumerate(raw["batches"]):
            out += _batch_problems(batch, f"batches.{n}")
    if "exclude" in raw:
        if not isinstance(raw["exclude"], list):
            out.append(("exclude", "Input should be a valid array"))
        else:
            for n, entry in enumerate(raw["exclude"]):
                out += _exclusion_problems(entry, f"exclude.{n}")
    if out:
        return out, "invalid"
    problems: list[Problem] = []
    plan_id = raw["plan_id"]
    if not PLAN_ID.match(plan_id):
        problems.append(("plan_id", f"plan_id {plan_id!r} must match {PLAN_ID.pattern}"))
    if file_name != f"{plan_id}.json":
        problems.append(("plan_id", f"the file name must be {plan_id}.json"))
    if raw.get("external_dependencies"):
        if problems:
            return problems, "invalid"
        return [(plan_id, "external dependencies are not supported in this version")], "external_dependencies"
    return problems, "invalid"


# --- the graph: admission's graph ----------------------------------------------------------------------------------

Node = tuple[str, str]  # ("u", unit id) or ("b", batch id)


def build_graph(batches: list[dict]) -> tuple[dict[Node, list[Node]], dict[Node, tuple[int, int]]]:
    """`admit._graph`: edges (node -> the nodes it waits for), without unknown or self references, and tie keys."""
    unit_ids = {u["id"] for b in batches for u in b["units"]}
    batch_ids = {b["id"] for b in batches}
    waits: dict[Node, list[Node]] = {}
    key: dict[Node, tuple[int, int]] = {}
    for bi, batch in enumerate(batches):
        for ui, unit in enumerate(batch["units"]):
            node: Node = ("u", unit["id"])
            deps: list[Node] = [("u", d) for d in unit.get("depends_on", []) if d in unit_ids and d != unit["id"]]
            deps += [("b", d) for d in batch.get("depends_on", []) if d in batch_ids and d != batch["id"]]
            waits[node] = deps
            key[node] = (bi, ui)
        bnode: Node = ("b", batch["id"])
        waits[bnode] = [("u", u["id"]) for u in batch["units"]]
        key[bnode] = (bi, len(batch["units"]))
    return waits, key


def find_cycle(waits: dict[Node, list[Node]], key: dict[Node, tuple[int, int]]) -> list[Node] | None:
    """`admit._find_cycle`: the first cycle found, units tried in file order before batches."""
    starts = sorted(waits, key=lambda n: (n[0] == "b", key[n]))
    state: dict[Node, int] = {}
    path: list[Node] = []

    def visit(node: Node) -> list[Node] | None:
        state[node] = 1
        path.append(node)
        for nxt in sorted(waits[node], key=lambda n: (n[0] == "b", key[n])):
            if state.get(nxt) == 1:
                return path[path.index(nxt) :]
            if nxt not in state and (found := visit(nxt)) is not None:
                return found
        path.pop()
        state[node] = 2
        return None

    for start in starts:
        if start not in state and (found := visit(start)) is not None:
            return found
    return None


def topological(waits: dict[Node, list[Node]], key: dict[Node, tuple[int, int]]) -> list[Node]:
    """`admit._topological`: a heap on (batch position, unit position) among the nodes that are ready."""
    left = {n: len(set(d)) for n, d in waits.items()}
    users: dict[Node, list[Node]] = {n: [] for n in waits}
    for n, deps in waits.items():
        for d in set(deps):
            users[d].append(n)
    ready = [(key[n], n) for n, c in left.items() if c == 0]
    heapq.heapify(ready)
    out: list[Node] = []
    while ready:
        _, node = heapq.heappop(ready)
        out.append(node)
        for user in users[node]:
            left[user] -= 1
            if left[user] == 0:
                heapq.heappush(ready, (key[user], user))
    return out


def waves_of(order: list[Node], waits: dict[Node, list[Node]]) -> list[list[str]]:
    """The wave of a unit is 1 plus the highest wave of what it waits for, a batch node standing for the highest wave
    of its units, and 1 when it waits for nothing. Each wave lists its units in dispatch order."""
    wave: dict[Node, int] = {}
    for node in order:
        deps = [wave[d] for d in waits[node]]
        wave[node] = 1 + max(deps, default=0) if node[0] == "u" else max(deps, default=0)
    out: list[list[str]] = []
    for node in order:
        if node[0] == "u":
            while len(out) < wave[node]:
                out.append([])
            out[wave[node] - 1].append(node[1])
    return out


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup


# --- one plan file -------------------------------------------------------------------------------------------------


class PlanReport:
    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        self.problems: list[tuple[str, str, str]] = []  # (code, subject, text)
        self.order: list[str] | None = None
        self.waves: list[list[str]] | None = None
        self.planned: list[str] = []  # the unit ids the file names in its batches, whatever else is wrong
        self.excluded: list[str] = []
        self.finished: list[str] = []  # planned units whose OpenSpec change is archived
        self.deps: dict[str, list[str]] | None = None  # unit -> depends_on, once the schema passed

    def add(self, code: str, subject: str, text: str) -> None:
        self.problems.append((code, subject, text))


def _raw_ids(raw: dict) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    batches = raw.get("batches")
    for batch in batches if isinstance(batches, list) else []:
        units = batch.get("units") if isinstance(batch, dict) else None
        for unit in units if isinstance(units, list) else []:
            unit_id = unit.get("id") if isinstance(unit, dict) else None
            if isinstance(unit_id, str) and unit_id and unit_id not in ids:
                ids.append(unit_id)
    excluded: list[str] = []
    entries = raw.get("exclude")
    for entry in entries if isinstance(entries, list) else []:
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(entry_id, str) and entry_id and entry_id not in excluded:
            excluded.append(entry_id)
    return ids, excluded


def check_plan(file_name: str, text: str, known: set[str], finished: set[str]) -> PlanReport:
    """Everything `l4 yolo check` finds in one plan file without git, the configuration or the target head.
    `finished` holds the archived changes: an `exclude` may name one, and so may a batch (listed in `report.finished`,
    not an error: only `l4 yolo check` knows whether this plan already merged or integrated it)."""
    stem = file_name[: -len(".json")]
    report = PlanReport(stem)
    try:
        raw = json.loads(text)
    except ValueError as exc:
        report.add("invalid", stem, f"not JSON: {exc}")
        return report
    if not isinstance(raw, dict):
        report.add("invalid", stem, "not a JSON object")
        return report
    ids, excluded = _raw_ids(raw)
    report.planned = [i for i in ids if i not in excluded]  # an excluded unit is not held (design D15)
    report.excluded = excluded
    problems, code = schema_problems(raw, file_name)
    if problems:
        for subject, why in problems:
            report.add(code, subject, why)
        return report
    batches = raw["batches"]
    units = [u for b in batches for u in b["units"]]
    unit_ids = {u["id"] for u in units}
    batch_ids = {b["id"] for b in batches}
    plan_id = raw["plan_id"]
    report.deps = {u["id"]: list(u.get("depends_on", [])) for u in units}
    if not units:
        report.add("empty_plan", plan_id, "the plan has no unit")
    for dup in _duplicates([u["id"] for u in units]):
        report.add("duplicate_id", dup, f"unit {dup} appears more than once")
    for dup in _duplicates([b["id"] for b in batches]):
        report.add("duplicate_id", dup, f"batch {dup} appears more than once")
    exclude_ids = [x["id"] for x in raw.get("exclude", [])]
    for dup in _duplicates(exclude_ids):
        report.add("duplicate_id", dup, f"unit {dup} is excluded more than once")
    for item in dict.fromkeys(exclude_ids):
        if item in unit_ids:
            report.add("excluded_and_planned", item, f"unit {item} is both planned and excluded")
        if item not in known and item not in finished:
            report.add("unknown_unit", item, f"excluded unit {item} was not found by a spec provider")
    for batch in batches:
        for dep in batch.get("depends_on", []):
            if dep == batch["id"]:
                report.add("self_dependency", batch["id"], f"batch {batch['id']} depends on itself")
            elif dep not in batch_ids:
                report.add(
                    "unknown_dependency", batch["id"],
                    f"batch {batch['id']} depends on {dep}, which is not a batch of the plan",
                )  # fmt: skip
        for unit in batch["units"]:
            for dep in unit.get("depends_on", []):
                if dep == unit["id"]:
                    report.add("self_dependency", unit["id"], f"unit {unit['id']} depends on itself")
                elif dep not in unit_ids:
                    report.add(
                        "unknown_dependency", unit["id"],
                        f"unit {unit['id']} depends on {dep}, which is not a unit of the plan",
                    )  # fmt: skip
            if unit["id"] not in known and unit["id"] in finished:
                report.finished.append(unit["id"])
            elif unit["id"] not in known:
                report.add("unknown_unit", unit["id"], f"unit {unit['id']} was not found by a spec provider")
    waits, key = build_graph(batches)
    cycle = find_cycle(waits, key)
    if cycle is not None:
        names = [n[1] for n in cycle]
        report.add("cycle", names[0], "dependency cycle: " + " -> ".join([*names, names[0]]))
    if not report.problems:
        order = topological(waits, key)
        report.order = [n[1] for n in order if n[0] == "u"]
        report.waves = waves_of(order, waits)
    return report


# --- all plan files ------------------------------------------------------------------------------------------------


def derived_parents(unit_id: str) -> list[str]:
    framework, _, name = unit_id.partition(":")
    parents: list[str] = []
    while True:
        match = FIX_NAME.match(name) or FOLLOW_UP_NAME.match(name)
        if match is None:
            return parents
        name = match.group("parent")
        parents.append(f"{framework}:{name}")


def read_plan_files(repo: Path) -> list[tuple[str, str]]:
    """(file name, text) of each `.l4/plans/*.json` in path order; a symlink or a non-file is skipped."""
    folder = repo / PLANS_DIR
    if not folder.is_dir():
        raise UsageError(f"no {PLANS_DIR} folder in {repo}")
    found = []
    for path in sorted(folder.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            found.append((path.name, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageError(f"cannot read {PLANS_DIR}/{path.name}: {exc.__class__.__name__}") from None
    if not found:
        raise UsageError(f"no plan file in {PLANS_DIR}")
    return found


def validate(repo: Path, args: argparse.Namespace) -> dict:
    units, archived, warnings = discover_units(repo, args)
    known = set(units)
    hold, hold_warnings = read_yolo_hold(repo)
    warnings += hold_warnings
    limits, limit_warnings = read_review_limits(repo)
    warnings += limit_warnings
    reports = [check_plan(name, text, known, archived) for name, text in read_plan_files(repo)]
    listed: set[str] = set()
    planned_in: dict[str, list[str]] = {}
    for report in reports:
        listed |= {*report.planned, *report.excluded}
        for unit in report.planned:
            planned_in.setdefault(unit, []).append(report.plan_id)
    coverage: list[tuple[str, str, str]] = []
    for unit in sorted(known):
        if unit in listed or any(p in listed for p in derived_parents(unit)):
            continue
        if not any(fnmatch.fnmatchcase(unit, pattern) for pattern in hold):
            coverage.append(("uncovered", unit, "add it to a plan or to a plan's exclude with a reason"))
    for unit, plans in sorted(planned_in.items()):
        if len(plans) > 1:
            coverage.append(("covered_twice", unit, f"listed in plans {', '.join(plans)}"))
    openspec_root = resolve_discovery(repo, args)[1]
    for report in reports:
        for unit in report.planned:
            if unit in known and unit.startswith("openspec:"):
                for code, delta_file, text in purpose_problems(repo, openspec_root, unit.partition(":")[2]):
                    report.add(code, unit, f"{delta_file}: {text}")
    warnings_budget = budget_problems(repo, args, reports, known, limits)
    problems = [
        {"plan": r.plan_id, "code": c, "subject": s, "text": t} for r in reports for (c, s, t) in r.problems
    ] + [{"plan": None, "code": c, "subject": s, "text": t} for (c, s, t) in coverage]
    finished = sorted({unit for r in reports for unit in r.finished})
    return {
        "ok": not problems,
        "problems": problems,
        "finished": finished,
        "plans": {r.plan_id: {"order": r.order, "waves": r.waves} for r in reports if r.order is not None},
        "units": sorted(known),
        "warnings": warnings,
        "budget_warnings": warnings_budget,
    }


def budget_problems(
    repo: Path, args: argparse.Namespace, reports: list[PlanReport], known: set[str], limits: tuple[int, int, int]
) -> list[str]:
    """Add `material_over_budget` to the plan reports for a planned unit's own folder (a problem) and return the
    warning lines for dependencies (the review lists them as not shown in full without blocking)."""
    _, openspec_root, kiro_root, _ = resolve_discovery(repo, args)
    dependents: dict[str, list[str]] = {}
    for report in reports:
        if report.deps is None:
            continue
        for unit, deps in report.deps.items():
            if unit in known:
                for path, what in budget_lines(
                    read_folder(repo, unit_folder(unit, openspec_root, kiro_root), budget=limits[1], max_file=limits[0])
                ):
                    report.add("material_over_budget", unit, f"{path}: {what}")
            for dep in deps:
                if unit != dep and unit not in dependents.setdefault(dep, []):
                    dependents[dep].append(unit)
    lines = []
    for dep, by in dependents.items():
        if dep in known:
            folder = unit_folder(dep, openspec_root, kiro_root)
            for path, what in budget_lines(
                read_folder(repo, folder, budget=limits[2], max_file=limits[0], order="prerequisite")
            ):
                lines.append(
                    f"warning: material_over_budget: {dep}: {path}: {what} (as a dependency of {', '.join(by)})"
                )
    return lines


def problem_line(problem: dict) -> str:
    if problem["plan"] is None:
        return f"error: {problem['code']}: {problem['subject']} ({problem['text']})"
    return f"error: {problem['plan']}: {problem['code']}: {problem['subject']}: {problem['text']}"


def finished_line(unit: str) -> str:
    return (
        f"finished: {unit} (archived: l4 yolo check refuses it as unknown_unit unless this plan already merged or "
        "integrated it)"
    )


def render(result: dict) -> str:
    finished = [finished_line(unit) for unit in result["finished"]] + result["budget_warnings"]
    if result["problems"]:
        return "\n".join([*(problem_line(p) for p in result["problems"]), *finished])
    lines = []
    for plan_id, shown in result["plans"].items():
        lines.append(f"{plan_id}: valid ({len(shown['order'])} unit(s))")
        lines.append(f"order: {', '.join(shown['order'])}")
        lines += [f"wave {n}: {', '.join(wave)}" for n, wave in enumerate(shown["waves"], start=1)]
    return "\n".join([*lines, *finished])


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate_plan.py",
        description="Validate the delivery plans in .l4/plans of a working tree: schema, graph, order, waves and "
        "coverage. Python standard library only; it never writes or uses the network; its only subprocess is a "
        "read-only `git ls-files`, to count the files the review sees.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo", default=".", help="the working tree (default: the current directory)")
    p.add_argument("--frameworks", help="auto, openspec, kiro or openspec,kiro (default: spec.frameworks)")
    p.add_argument("--openspec-root", help="the OpenSpec root (default: spec.openspec.root, else openspec)")
    p.add_argument("--kiro-root", help="the Kiro root (default: spec.kiro.root, else .kiro/specs)")
    p.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)  # a usage error exits 2
    repo = Path(args.repo)
    try:
        if not repo.is_dir():
            raise UsageError(f"{args.repo} is not a directory")
        result = validate(repo.resolve(), args)
    except UsageError as exc:
        print(f"validate_plan.py: {exc}", file=sys.stderr)
        return 2
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
