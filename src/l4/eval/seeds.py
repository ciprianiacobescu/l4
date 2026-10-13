"""The seed set (L4-EVAL-001): a base project and the units that are run on it, read from a directory.

    <root>/base/                      the project every unit starts from (pyproject.toml, src/, tests/)
    <root>/units/<id>/                an OpenSpec change (proposal.md, tasks.md, specs/<cap>/spec.md, .openspec.yaml)
        expected.json                 {"implementer": {"outcome": "pass"}, "judge": {"verdict": ..., ...}}
        reference/red/<path>          the files of a known red step, relative to the project root
        reference/green/<path>        the files of a known green step
        reference/hidden_check.py     optional: a reviewer's check that the reference does not pass

The seeds live in this repository, so a run is offline and versioned with the harness (plan D1). Changing a byte of
any of them changes `seed_set_sha256`, and the gate refuses to compare across that (L4-EVAL-022).
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.specs.base import Criterion, SpecError
from l4.specs.criteria import openspec_criteria

_SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".venv", ".l4-out", ".ruff_cache", ".git"})
_SKIP_SUFFIXES = (".pyc", ".pyo")
NOT_SEEDS = (".DS_Store",)  # what a desktop writes into a folder: never a seed, never hashed or committed


class SeedError(ValueError):
    """The seed directory is not a valid seed set; the message names the unit or path, never file content."""


@dataclass(frozen=True)
class SeedUnit:
    id: str
    path: Path
    expected: dict[str, Any]
    criteria: tuple[Criterion, ...]
    reference_red: dict[str, bytes]  # project-relative path -> content
    reference_green: dict[str, bytes]
    hidden_check: Path | None

    @property
    def judge_only(self) -> bool:
        return "implementer" not in self.expected


@dataclass(frozen=True)
class SeedSet:
    root: Path
    base: Path
    units: tuple[SeedUnit, ...]

    def unit(self, unit_id: str) -> SeedUnit:
        for unit in self.units:
            if unit.id == unit_id:
                return unit
        raise SeedError(f"unknown unit {unit_id!r} (known: {', '.join(u.id for u in self.units)})")


def _files(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts) or path.name.endswith(_SKIP_SUFFIXES):
            continue
        if path.name in NOT_SEEDS:
            continue
        if path.is_file() and not path.is_symlink():
            out.append(path)
    return out


def _read_reference(unit: Path, kind: str) -> dict[str, bytes]:
    root = unit / "reference" / kind
    if not root.is_dir():
        raise SeedError(f"unit {unit.name}: reference/{kind}/ is missing")
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in _files(root)}
    if not files:
        raise SeedError(f"unit {unit.name}: reference/{kind}/ holds no file")
    return files


def _load_unit(path: Path) -> SeedUnit:
    for name in ("proposal.md", "tasks.md", "expected.json"):
        if not (path / name).is_file():
            raise SeedError(f"unit {path.name}: {name} is missing")
    try:
        expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    except ValueError:
        raise SeedError(f"unit {path.name}: expected.json is not JSON") from None
    if not isinstance(expected, dict):
        raise SeedError(f"unit {path.name}: expected.json is not an object")
    try:
        criteria = tuple(openspec_criteria(path))
    except SpecError as exc:
        raise SeedError(f"unit {path.name}: {exc}") from None
    hidden = path / "reference" / "hidden_check.py"
    return SeedUnit(
        id=path.name, path=path, expected=expected, criteria=criteria,
        reference_red=_read_reference(path, "red"), reference_green=_read_reference(path, "green"),
        hidden_check=hidden if hidden.is_file() else None,
    )  # fmt: skip


def load_seed_set(root: Path) -> SeedSet:
    root = Path(root)
    base, units = root / "base", root / "units"
    if not (base / "pyproject.toml").is_file() or not units.is_dir():
        raise SeedError(f"{root} is not a seed set (needs base/pyproject.toml and units/)")
    loaded = tuple(_load_unit(p) for p in sorted(units.iterdir()) if p.is_dir())
    if not loaded:
        raise SeedError(f"{root} has no unit")
    return SeedSet(root, base, loaded)


def seed_set_sha256(root: Path) -> str:
    """A sha256 over the sorted relative paths and the bytes of every file under `root` (caches excluded), so it
    changes with any byte of a seed and not with where the directory is."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in _files(root):
        data = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0" + str(len(data)).encode() + b"\0")
        digest.update(data)
    return digest.hexdigest()
