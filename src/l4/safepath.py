"""PATH hygiene for harness-side tools (L4-SEC-006): a repository or worktree must never supply the binary we run.

An empty PATH entry or a relative one (`.`, `./node_modules/.bin`) resolves against the child's cwd, which is the
checkout; an absolute entry that lies inside a checkout does the same by another route.
"""

import os
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from l4.exitcodes import ExitCode, L4Exit


def _inside(path: Path, roots: Iterable[Path]) -> bool:
    real = path.resolve()
    return any(real == root or root in real.parents for root in (r.resolve() for r in roots))


def safe_path(environ: Mapping[str, str], *, forbid: Iterable[Path] = ()) -> str:
    """`environ["PATH"]` without empty, non-absolute and forbidden-directory entries."""
    forbidden = tuple(forbid)
    kept = [
        entry
        for entry in environ.get("PATH", "").split(os.pathsep)
        if entry and os.path.isabs(entry) and not _inside(Path(entry), forbidden)
    ]
    return os.pathsep.join(kept)


def resolve_tool(name: str, environ: Mapping[str, str], *, forbid: Iterable[Path] = ()) -> str | None:
    """Real path (symlinks resolved) of `name` on the safe PATH: a tool may look for its helpers next to the path it
    was started by (macOS Codex finds codex-code-mode-host there), and a symlink on PATH hides them. A hit whose
    real path is inside `forbid` (a symlink planted from a trusted directory into the checkout) ends the run with
    exit 3 instead of running it."""
    forbidden = tuple(forbid)
    found = shutil.which(name, path=safe_path(environ, forbid=forbidden))
    if found is None:
        return None
    if _inside(Path(found), forbidden):
        raise L4Exit(ExitCode.DOCTOR_FAILED, f"{name} resolves to {found}, which is inside the repository")
    return os.path.realpath(found)
