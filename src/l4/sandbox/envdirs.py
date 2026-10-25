"""The project environment directories of a work tree (SPEC L4-SEC-035): `.venv` at the root and every `node_modules`.

A gate that does not build the environment sees these read-only, and the harness compares them after every step and
gate (`l4.implementer.envguard`). This module only finds them; it imports nothing of the implementer.
"""

import os
import shutil
from collections.abc import Collection
from pathlib import Path

ENV_DIR_NAMES = (".venv", "node_modules")
# inside a node_modules, empty at every gate: `.cache` and `.vite` hold vite's pre-bundled deps and friends,
# `.vite-temp` is where Vite 5+ bundles a TypeScript config before loading it (it tolerates only EACCES there), and
# `.vitest-cache` is Vitest 5's module cache (`fsModuleCache` is on by default and nothing catches its mkdir error)
TOOL_CACHE_DIRS = (".cache", ".vite", ".vite-temp", ".vitest-cache")
_NOT_ENTERED = frozenset({".git", ".venv", "node_modules", ".l4-out"})


def _tracked_below(rel: str, tracked: Collection[str]) -> bool:
    prefix = rel + "/"
    return any(path == rel or path.startswith(prefix) for path in tracked)


def env_dirs(tree: Path, tracked: Collection[str] = ()) -> list[Path]:
    """`.venv` at the tree root and every directory named `node_modules` below it, sorted. A directory git tracks a file
    in (`tracked`: paths relative to `tree`) is source, not an environment, and is left out. A symlink with such a name
    is returned (the harness removes it) and never mounted. The walk does not enter `.git`, `.venv`, a `node_modules`,
    `.l4-out` or a symlinked directory."""
    found: list[Path] = []
    venv = tree / ".venv"
    if os.path.lexists(venv) and not _tracked_below(".venv", tracked):
        found.append(venv)
    for top, dirs, _files in os.walk(tree):
        here = Path(top)
        keep: list[str] = []
        for name in dirs:
            path = here / name
            if name == "node_modules":
                rel = path.relative_to(tree).as_posix()
                if not _tracked_below(rel, tracked):
                    found.append(path)
                continue
            if name in _NOT_ENTERED or path.is_symlink():
                continue
            keep.append(name)
        dirs[:] = keep
    return sorted(found)


def read_only_mounts(tree: Path, tracked: Collection[str] = ()) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """(the real environment directories, the `TOOL_CACHE_DIRS` that exist as real directories inside each
    `node_modules`): what a gate that does not build the environment gets as read-only binds and as tmpfs."""
    real = [p for p in env_dirs(tree, tracked) if p.is_dir() and not p.is_symlink()]
    caches = [
        cache
        for path in real
        if path.name == "node_modules"
        for name in TOOL_CACHE_DIRS
        if (cache := path / name).is_dir() and not cache.is_symlink()
    ]
    return tuple(real), tuple(caches)


def reset_tool_caches(tree: Path, tracked: Collection[str] = ()) -> None:
    """Every `node_modules/.cache`, `.vite`, `.vite-temp` and `.vitest-cache` becomes an empty real directory (a symlink
    is unlinked first, a missing one is made): under bwrap a tmpfs goes over it and needs the mount point, and under
    `sandbox.mode: none` the reset is the whole protection, because vitest loads pre-bundled modules from `.vite/deps`
    [I]. Vite 5+ bundles a TypeScript config into `.vite-temp` and tolerates only EACCES there. Vitest 5 keeps its
    transformed modules in `.vitest-cache`, reads them back without any further check and does not catch the mkdir
    error."""
    for path in env_dirs(tree, tracked):
        if path.name != "node_modules" or path.is_symlink() or not path.is_dir():
            continue
        for name in TOOL_CACHE_DIRS:
            cache = path / name
            if cache.is_symlink() or cache.is_file():
                cache.unlink()
            elif cache.is_dir():
                shutil.rmtree(cache)
            cache.mkdir()
