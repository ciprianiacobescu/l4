#!/usr/bin/env python3
"""Validate the delivery plans of a working tree without the harness: Python standard library only.

    python3 validate_plan.py [--repo DIR] [--frameworks auto|openspec|kiro|openspec,kiro]
                             [--openspec-root DIR] [--kiro-root DIR] [--json]

It reads every `.l4/plans/*.json`, finds the specs the way the harness's providers do, and reports what `l4 yolo check`
would report without git, a network or a model (yolo-mode design D15, requirement L4-YOLO-019). It never writes.

Exit 0: everything is valid. Exit 1: one line per problem, `<plan id>: <code>: <subject>: <text>`, or for the coverage
problems `uncovered: <unit> (...)` and `covered_twice: <unit> (...)`. Exit 2: a usage or read error.
"""

from __future__ import annotations

import argparse
import datetime
import heapq
import json
import os
import re
import stat
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

HELP_EPILOG = """\
What this script checks, with the codes of `l4 yolo check` where the check is the same:
  invalid (schema, file name, limits), duplicate_id, self_dependency, unknown_dependency, cycle, unknown_unit,
  excluded_and_planned, external_dependencies, empty_plan; across the plan files: uncovered (a spec no plan lists,
  planned or excluded, except a <parent>-fix-<n> or <parent>-followup-<n> unit whose parent is listed) and
  covered_twice (a unit planned in two plan files).

What only `l4 yolo check` can check (it needs git, the target head and the configuration): open questions, the intake
checks of each spec, finished units, acceptance profiles, the target against forge.base_branch, and the merge policy.
Specs are read from this working tree only: a spec that exists only on a branch is unknown here, and an archived
change is known only to an `exclude` (the harness reads archived changes from the base branch).

The frameworks and roots come from .l4/config.yaml (spec.frameworks, spec.openspec.root, spec.kiro.root) when it uses
the block style `l4 init` writes; anything else falls back to both frameworks, `openspec` and `.kiro/specs`, with a
warning. The flags override the file. Exit 0 valid, 1 problems, 2 usage or read error.
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


# --- the configuration: a small block-style reader -----------------------------------------------------------------


def _strip_comment(value: str) -> str:
    value = value.strip()
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
        match = re.match(r"^([A-Za-z0-9_.-]+):(?:\s+(.*))?$", text)
        if not match:
            raise Unsupported(f"cannot read {text[:20]!r}")
        key, rest = match.group(1), match.group(2)
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


def read_spec_config(repo: Path) -> tuple[dict[str, object], list[str]]:
    """(the `spec` mapping of .l4/config.yaml, warnings). {} when the file has no `spec` key."""
    path = repo / ".l4" / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, [f"{path.relative_to(repo).as_posix()} not found: using the default frameworks and roots"]
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [
            f".l4/config.yaml cannot be read ({exc.__class__.__name__}): using the default frameworks and roots"
        ]
    rows = text.splitlines()
    start = next((n for n, row in enumerate(rows) if re.match(r"^spec\s*:\s*(#.*)?$", row)), None)
    if start is None:
        if any(re.match(r"^spec\s*:", row) for row in rows):
            return {}, ["spec in .l4/config.yaml is not in block style: using the default frameworks and roots"]
        return {}, []
    block = []
    for row in rows[start + 1 :]:
        if row.strip() and not row.startswith((" ", "\t", "#")):
            break
        block.append(row)
    try:
        lines = _logical_lines(block)
        parsed = _parse_map(lines, 0, lines[0][0])[0] if lines else {}
    except Unsupported as exc:
        return {}, [f"spec in .l4/config.yaml is not block style ({exc}): using the default frameworks and roots"]
    return parsed, []


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


def _datetime_problem(value: object) -> str | None:
    """None when `value` is a datetime string with a time zone (pydantic's rules for an ISO 8601 string; a string of
    digits is a Unix time, which carries its zone)."""
    if not isinstance(value, str):
        return "Input should be a valid datetime"
    if value.isdigit() and value.isascii():
        return None
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
    """Everything `l4 yolo check` finds in one plan file without git, the configuration or the target head."""
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
            if unit["id"] not in known:
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
    reports = [check_plan(name, text, known, archived) for name, text in read_plan_files(repo)]
    listed: set[str] = set()
    planned_in: dict[str, list[str]] = {}
    for report in reports:
        listed |= {*report.planned, *report.excluded}
        for unit in report.planned:
            planned_in.setdefault(unit, []).append(report.plan_id)
    coverage: list[tuple[str, str, str]] = []
    for unit in sorted(known):
        if unit not in listed and not any(p in listed for p in derived_parents(unit)):
            coverage.append(("uncovered", unit, "add it to a plan or to a plan's exclude with a reason"))
    for unit, plans in sorted(planned_in.items()):
        if len(plans) > 1:
            coverage.append(("covered_twice", unit, f"listed in plans {', '.join(plans)}"))
    problems = [
        {"plan": r.plan_id, "code": c, "subject": s, "text": t} for r in reports for (c, s, t) in r.problems
    ] + [{"plan": None, "code": c, "subject": s, "text": t} for (c, s, t) in coverage]
    return {
        "ok": not problems,
        "problems": problems,
        "plans": {r.plan_id: {"order": r.order, "waves": r.waves} for r in reports if r.order is not None},
        "units": sorted(known),
        "warnings": warnings,
    }


def problem_line(problem: dict) -> str:
    if problem["plan"] is None:
        return f"{problem['code']}: {problem['subject']} ({problem['text']})"
    return f"{problem['plan']}: {problem['code']}: {problem['subject']}: {problem['text']}"


def render(result: dict) -> str:
    if result["problems"]:
        return "\n".join(problem_line(p) for p in result["problems"])
    lines = []
    for plan_id, shown in result["plans"].items():
        lines.append(f"{plan_id}: valid ({len(shown['order'])} unit(s))")
        lines.append(f"order: {', '.join(shown['order'])}")
        lines += [f"wave {n}: {', '.join(wave)}" for n, wave in enumerate(shown["waves"], start=1)]
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate_plan.py",
        description="Validate the delivery plans in .l4/plans of a working tree: schema, graph, order, waves and "
        "coverage. Python standard library only; it never writes, runs git or uses the network.",
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
