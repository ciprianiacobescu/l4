"""The project environment as evidence (SPEC L4-SEC-036): a manifest of `.venv` and every `node_modules`, a compare, and
the classification of what changed.

No guard looks at `.venv` or `node_modules`, `git clean` keeps them and `uv sync --frozen` leaves a file that no
installed distribution owns, so a `.pth` file written there decides the verdict of every later gate. The protection is
that the harness takes a manifest after each passing `gates.setup` command, compares it after every agent step and
every other gate, and removes an environment that differs, so the next setup builds it again. The classification
(`classify`) only decides how a removal is reported; it never decides whether to remove.

ctime is the tamper evidence: a process of the same user can reset mtime with `utime` but not ctime, and a replacement
by rename changes the inode.
"""

import base64
import contextlib
import csv
import fnmatch
import hashlib
import json
import os
import posixpath
import shutil
import tomllib
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from l4.sandbox.envdirs import TOOL_CACHE_DIRS, env_dirs

LOCK_FILES = (
    "uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "yarn.lock", "bun.lock", "bun.lockb",
)  # fmt: skip
MANIFEST_FILES = ("pyproject.toml", "setup.py", "setup.cfg", "package.json")
_HOOK_NAMES = ("sitecustomize.py", "usercustomize.py")
_IGNORED = frozenset({".venv/.lock"})  # uv's own lock file, touched by `uv run`; it holds no code
MAX_REPORTED = 20


@dataclass(frozen=True)
class Entry:
    kind: str  # "file" | "dir" | "link" | "other"
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    ino: int
    target: str | None = None


EnvManifest = dict[str, Entry]


@dataclass(frozen=True)
class EnvDiff:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.added or self.changed or self.removed)


def _entry(path: Path) -> Entry:
    info = os.lstat(path)
    mode = info.st_mode
    kind = "link" if (mode & 0o170000) == 0o120000 else "dir" if (mode & 0o170000) == 0o040000 else (
        "file" if (mode & 0o170000) == 0o100000 else "other"
    )  # fmt: skip
    target = os.readlink(path) if kind == "link" else None
    return Entry(kind, mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, target)


def _walk(base: Path, tree: Path, out: EnvManifest) -> None:
    rel = base.relative_to(tree).as_posix()
    with contextlib.suppress(OSError):
        out[rel] = _entry(base)
    if base.is_symlink() or not base.is_dir():
        return
    for top, dirs, files in os.walk(base, followlinks=False):
        here = Path(top)
        skip = base.name == "node_modules" and here == base
        keep = []
        for name in dirs:
            path = here / name
            if skip and name in TOOL_CACHE_DIRS:
                continue  # empty and writable at every gate: the harness resets it (l4.sandbox.envdirs)
            with contextlib.suppress(OSError):
                out[path.relative_to(tree).as_posix()] = _entry(path)
            if not path.is_symlink():
                keep.append(name)
        dirs[:] = keep
        for name in files:
            path = here / name
            with contextlib.suppress(OSError):
                out[path.relative_to(tree).as_posix()] = _entry(path)


def take_manifest(tree: Path, tracked: Collection[str] = ()) -> EnvManifest:
    """The lstat of every entry of every environment directory (a symlink is recorded, not followed)."""
    out: EnvManifest = {}
    for base in env_dirs(tree, tracked):
        _walk(base, tree, out)
    return {path: entry for path, entry in out.items() if path not in _IGNORED}


def diff_manifest(before: Mapping[str, Entry], after: Mapping[str, Entry]) -> EnvDiff:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(path for path in set(before) & set(after) if before[path] != after[path])
    return EnvDiff(tuple(added), tuple(changed), tuple(removed))


def remove_env_dir(path: Path) -> None:
    """An environment directory goes: `unlink` for a symlink, else `rmtree` (read-only files included)."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return

    for top, dirs, _files in os.walk(path):  # a read-only directory (a package cache) could not be emptied
        with contextlib.suppress(OSError):
            os.chmod(top, 0o700)
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(top, d))]
    shutil.rmtree(path)


# --- what the agent declared ---------------------------------------------------------------------------------------


def _is_lock(path: str) -> bool:
    return posixpath.basename(path) in LOCK_FILES


def _is_requirements(path: str) -> bool:
    return fnmatch.fnmatch(posixpath.basename(path), "requirements*.txt")


def lock_changed(changed_files: Collection[str]) -> bool:
    """The step wrote a lock file: it declared an install (a dependency change goes through `uv add`, `npm install`)."""
    return any(_is_lock(p) for p in changed_files)


_PACKAGE_JSON_SECTIONS = (
    "dependencies", "devDependencies", "peerDependencies", "optionalDependencies", "bundleDependencies",
    "bundledDependencies", "overrides", "resolutions",
)  # fmt: skip


def _sections(path: str, data: bytes | None) -> object:
    """The dependency sections of a manifest, or a marker for a file that is absent or that does not parse."""
    if data is None:
        return None
    name = posixpath.basename(path)
    try:
        if name == "package.json":
            doc = json.loads(data)
            return {k: doc.get(k) for k in _PACKAGE_JSON_SECTIONS} if isinstance(doc, dict) else "unparsed"
        if name == "pyproject.toml":
            doc = tomllib.loads(data.decode("utf-8"))
            project = doc.get("project", {})
            return {
                "dependencies": project.get("dependencies"),
                "optional-dependencies": project.get("optional-dependencies"),
                "dependency-groups": doc.get("dependency-groups"),
                "tool.uv": doc.get("tool", {}).get("uv"),
            }
    except (ValueError, UnicodeDecodeError):
        return "unparsed"
    return data  # setup.py / setup.cfg: any change counts


def manifest_changed(
    tree: Path, changed_files: Collection[str], read_head: Callable[[str], bytes | None] | None
) -> bool:
    """A dependency manifest changed in this step: `requirements*.txt` in any way, a `package.json` or `pyproject.toml`
    in a dependency section (or in a way that cannot be read). `read_head(path)` is the file at HEAD, None when it is
    not there; without it every changed manifest counts."""
    for path in changed_files:
        if _is_requirements(path):
            return True
        if posixpath.basename(path) not in MANIFEST_FILES:
            continue
        if read_head is None:
            return True
        try:
            now: bytes | None = (tree / path).read_bytes()
        except OSError:
            now = None
        if _sections(path, now) != _sections(path, read_head(path)):
            return True
    return False


# --- RECORD files --------------------------------------------------------------------------------------------------


def _record_index(tree: Path) -> dict[str, str]:
    """tree-relative path -> the sha256 (urlsafe base64, no padding) that a `RECORD` of the current `.venv` lists for it
    ('' for the RECORD file itself, which lists no hash)."""
    index: dict[str, str] = {}
    venv = tree / ".venv"
    for record in sorted(venv.glob("lib/python*/site-packages/*.dist-info/RECORD")) + sorted(
        venv.glob("Lib/site-packages/*.dist-info/RECORD")
    ):
        site = record.parent.parent
        with (
            contextlib.suppress(OSError, csv.Error, UnicodeDecodeError),
            record.open(newline="", encoding="utf-8") as handle,
        ):
            for row in csv.reader(handle):
                if len(row) < 2 or not row[0]:
                    continue
                target = posixpath.normpath(posixpath.join(site.relative_to(tree).as_posix(), row[0]))
                algo, _, digest = row[1].partition("=")
                index[target] = digest if algo == "sha256" else ""
    return index


def _sha256(path: Path) -> str | None:
    try:
        raw = hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return None
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _listed(rel: str, tree: Path, index: Mapping[str, str]) -> bool:
    if rel not in index:
        return False
    return index[rel] == "" or index[rel] == _sha256(tree / rel)


def _is_hook(rel: str) -> bool:
    name = posixpath.basename(rel)
    return name.endswith((".pth", ".pyc")) or name in _HOOK_NAMES


@dataclass(frozen=True)
class Plants:
    violations: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()
    declared: bool = False  # a lock file was written
    manifest_changed: bool = False


def classify(
    tree: Path,
    diff: EnvDiff,
    changed_files: Collection[str],
    *,
    read_head: Callable[[str], bytes | None] | None = None,
) -> Plants:
    """Which added or changed paths are not explained by an install, and how each is reported.

    * a lock file changed (`declared`): an install the agent declared. A path under `.venv` still has to be listed, with
      a matching hash, in a `RECORD` of the current environment; a path under `node_modules` is accepted;
    * no lock file, but a dependency manifest changed (Q4): a path under `node_modules` or `.venv` that is not a
      Python startup hook (`*.pth`, `sitecustomize.py`, `usercustomize.py`, `*.pyc`) and not in a `RECORD` is a
      **notice** (`guard.notice`), not a violation;
    * otherwise it is a violation. A startup hook is a violation unless a `RECORD` lists it with its hash *and* the
      install was declared.
    Directories are never reported on their own; a file the compare found is what is."""
    declared = lock_changed(changed_files)
    manifest = manifest_changed(tree, changed_files, read_head)
    index = _record_index(tree)
    violations: list[str] = []
    notices: list[str] = []
    for rel in sorted({*diff.added, *diff.changed}):
        path = tree / rel
        if path.is_dir() and not path.is_symlink():
            continue
        under_venv = rel == ".venv" or rel.startswith(".venv/")
        hook = _is_hook(rel)
        listed = under_venv and _listed(rel, tree, index)
        if hook:
            if declared and listed:
                continue
            violations.append(rel)
        elif under_venv:
            if listed:
                continue
            (notices if manifest and not declared else violations).append(rel)
        else:  # node_modules
            if declared:
                continue
            (notices if manifest else violations).append(rel)
    return Plants(tuple(violations), tuple(notices), declared, manifest)


def planted(
    tree: Path,
    diff: EnvDiff,
    changed_files: Collection[str],
    *,
    read_head: Callable[[str], bytes | None] | None = None,
) -> list[str]:
    """The paths `classify` reports as violations (the plants)."""
    return list(classify(tree, diff, changed_files, read_head=read_head).violations)
