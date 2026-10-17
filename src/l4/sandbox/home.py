"""Which paths come back, read-only, after the tmpfs over the real home and the runner cache (SPEC L4-SEC-030..033).

The sandboxes hide `$HOME` and `$L4_CACHE`; a tool that lives under one of them (uv in `~/.local/bin`, the agent CLIs in
`$L4_HOME`, a pnpm in `~/setup-pnpm`) has to be put back, or every gate fails with "command not found". This module owns
the one derivation of those paths (design D4); the argv builders only bind what a `SandboxSpec` carries.
"""

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from l4.config.defaults import CREDENTIAL_PATHS, l4_home
from l4.exitcodes import ExitCode, L4Exit
from l4.safepath import safe_path
from l4.sandbox.base import SandboxSpec, expand_credential_paths

Kind = Literal["agent", "gate"]


def hidden_roots(spec: SandboxSpec) -> tuple[Path, ...]:
    """The directories the sandbox covers with a tmpfs: the home, and the runner cache when it lies outside the home."""
    roots = [spec.home]
    if cache_is_covered(spec.cache_root, spec.home):
        roots.append(spec.cache_root)
    return tuple(roots)


def cache_is_covered(cache_root: Path, home: Path) -> bool:
    """A runner cache gets its own tmpfs when it exists, is not `/` and is not inside the home (already covered)."""
    if not cache_root.is_absolute() or cache_root == Path("/") or not cache_root.is_dir():
        return False
    return not _inside(cache_root, home)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _expand(raw: str, home: Path) -> Path:
    return home / raw[2:] if raw.startswith("~/") else Path(raw)


def _credential_paths(home: Path, extra: Iterable[Path]) -> list[Path]:
    builtin = expand_credential_paths({k: list(v) for k, v in CREDENTIAL_PATHS.items()}, home)
    return [*(p for paths in builtin.values() for p in paths), *extra]


def _checked(
    key: str, configured: Sequence[str], *, home: Path, cache_root: Path, credentials: Iterable[Path]
) -> list[Path]:
    """The configured entries as absolute paths. An entry that is the home or `/`, contains the runner cache, or
    equals, contains or lies inside a login ends the run (exit 2); the message names the key, never the path."""
    logins = _credential_paths(home, credentials)
    out: list[Path] = []
    for raw in configured:
        path = Path(os.path.normpath(_expand(raw, home)))
        bad = (
            not path.is_absolute()
            or path == Path("/")
            or _inside(home, path)  # the home itself, or a parent of it
            or _inside(cache_root, path)
            or any(_inside(path, login) or _inside(login, path) for login in logins)
        )
        if bad:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"sandbox.{key}: an entry is the home, contains the runner cache, or overlaps a login",
            )
        out.append(path)
    return out


def _install_root(target: Path) -> Path:
    """Where a tool symlink's real file lives as a unit: the parent of the outermost `node_modules` on its path (an npm
    global install: the package and its siblings), else the file's directory."""
    parts = target.parts
    if "node_modules" in parts:
        return Path(*parts[: parts.index("node_modules")])
    return target.parent


def tool_paths(
    host_env: Mapping[str, str],
    *,
    home: Path,
    cache_root: Path,
    kind: Kind,
    configured: Sequence[str] = (),
    forbid: Iterable[Path] = (),
    credentials: Iterable[Path] = (),
) -> tuple[Path, ...]:
    """Every existing path under `home` or `cache_root` that a tool of this sandbox needs, read-only (design D4, items
    1-9 in that order). A path inside an earlier one, a duplicate, a path inside `forbid` (the worktree, the main
    checkout) and a path that is or holds a hidden root are dropped. `credentials` are the configured login paths,
    for the check of `configured` (`sandbox.tool_paths`)."""
    roots = [home, cache_root]
    forbidden = tuple(Path(os.path.realpath(p)) for p in forbid)
    ordered: list[Path] = []

    def under_hidden(path: Path) -> bool:
        return any(_inside(path, root) for root in roots)

    def add(path: Path) -> None:
        if not path.exists() or not under_hidden(path):
            return
        if any(path == root or path in root.parents for root in roots):
            return  # the home itself (or its parent): that would undo the tmpfs
        real = Path(os.path.realpath(path))
        if any(_inside(real, f) or _inside(f, real) for f in forbidden):
            return
        ordered.append(path)

    for text in safe_path(host_env, forbid=forbid).split(os.pathsep):
        if not text:
            continue
        entry = Path(text)
        add(entry)
        if entry.is_symlink():
            add(Path(os.path.realpath(entry)))
        if entry.name == ".bin" and entry.parent.name == "node_modules":
            add(entry.parent)
        if entry.is_dir() and under_hidden(entry):
            for child in sorted(entry.iterdir()):
                if not child.is_symlink():
                    continue
                target = Path(os.path.realpath(child))
                if target.is_file() and under_hidden(target) and not _inside(target, entry):
                    add(_install_root(target))
    add(l4_home(host_env))
    data = Path(host_env["XDG_DATA_HOME"]) if host_env.get("XDG_DATA_HOME") else home / ".local" / "share"
    add(Path(host_env["UV_PYTHON_INSTALL_DIR"]) if host_env.get("UV_PYTHON_INSTALL_DIR") else data / "uv" / "python")
    add(Path(host_env["UV_TOOL_DIR"]) if host_env.get("UV_TOOL_DIR") else data / "uv" / "tools")
    add(Path(host_env["COREPACK_HOME"]) if host_env.get("COREPACK_HOME") else home / ".cache" / "node" / "corepack")
    from l4.gates import coverage, trace  # late: the gates package imports the sandbox package

    add(trace.plugin_dir())
    add(coverage.plugin_dir())
    if kind == "agent":
        add(home / ".serena")
    for path in _checked("tool_paths", configured, home=home, cache_root=cache_root, credentials=credentials):
        add(path)
    out: list[Path] = []
    for path in ordered:
        if any(_inside(path, kept) for kept in out):
            continue
        out = [kept for kept in out if not _inside(kept, path)]
        out.append(path)
    return tuple(out)


def setup_paths(
    *,
    home: Path,
    cache_root: Path,
    configured: Sequence[str] = (),
    credentials: Iterable[Path] = (),
) -> tuple[Path, ...]:
    """`sandbox.setup_paths` as existing absolute paths, for the gate sandbox of a `gates.setup` command only."""
    checked = _checked("setup_paths", configured, home=home, cache_root=cache_root, credentials=credentials)
    return tuple(dict.fromkeys(p for p in checked if p.exists()))


def spec_paths(
    host_env: Mapping[str, str],
    *,
    home: Path,
    cache_root: Path,
    kind: Kind,
    sandbox_cfg: object,
    credential_paths: Mapping[str, Sequence[Path]],
    forbid: Iterable[Path],
    builds_env: bool = False,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """(tool paths, setup paths) of one sandbox spec from `cfg.sandbox`: the single call every spec builder makes."""
    logins = [p for paths in credential_paths.values() for p in paths]
    tools = tool_paths(
        host_env, home=home, cache_root=cache_root, kind=kind,
        configured=getattr(sandbox_cfg, "tool_paths", ()), forbid=forbid, credentials=logins,
    )  # fmt: skip
    setup = (
        setup_paths(
            home=home, cache_root=cache_root, configured=getattr(sandbox_cfg, "setup_paths", ()), credentials=logins
        )
        if builds_env and kind == "gate"
        else ()
    )
    return tools, setup
