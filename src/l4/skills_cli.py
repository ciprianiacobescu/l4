"""`l4 skills install|status` (L4-SKL-003): put the `l4` skill that ships in this package into every coding agent's
skill folder. No network. Each target folder `<skills dir>/l4/` gets the skill files and a manifest `.l4-skill.json`
(the version and one sha256 per file); nothing outside that folder is ever touched, and a symbolic link, as the folder
or as anything inside it, is refused."""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import click

from l4 import __version__
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit

MANIFEST = ".l4-skill.json"
SKILL_NAME = "l4"
AGENTS = ("claude-code", "codex", "opencode", "kiro")

# the repository's copy, next to `src/`: what a source checkout (an editable install, which has no force-include) reads
_SOURCE_SKILL = Path(__file__).resolve().parents[2] / "plugins" / "l4" / "skills" / "l4"

# agent -> (home folders whose presence means the agent is used, CLI names on PATH)
_DETECT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "claude-code": ((".claude",), ("claude",)),
    "codex": ((".agents", ".codex"), ("codex",)),
    "opencode": ((".config/opencode", ".opencode"), ("opencode",)),
    "kiro": ((".kiro",), ("kiro-cli",)),
}
# agent -> skills folder relative to the home folder (user scope) and to the repository root (project scope)
_USER_DIRS = {
    "claude-code": ".claude/skills",
    "codex": ".agents/skills",
    "opencode": ".config/opencode/skills",
    "kiro": ".kiro/skills",
}
_PROJECT_DIRS = {
    "claude-code": ".claude/skills",
    "codex": ".agents/skills",
    "opencode": ".opencode/skills",
    "kiro": ".kiro/skills",
}
_CODEX_EXTRA = ".codex/skills"  # written too (user scope) when it already exists: sources disagree on Codex's path


class SkillSourceError(RuntimeError):
    """The skill folder is neither packaged nor next to `src/`."""


# --- the bundled skill -----------------------------------------------------------------------------------------------


def _packaged_skill() -> Path | None:
    """`l4/_skill/l4` inside the installed package (hatch `force-include` puts it there in a wheel), or None."""
    try:
        folder = resources.files("l4") / "_skill" / SKILL_NAME
        if folder.is_dir() and (folder / "SKILL.md").is_file():
            return Path(str(folder))
    except (ModuleNotFoundError, FileNotFoundError, NotADirectoryError, OSError):
        pass
    return None


def bundled_skill_dir() -> Path:
    """The packaged skill; without it (a source checkout) the repository's `plugins/l4/skills/l4` next to `src/`."""
    packaged = _packaged_skill()
    if packaged is not None:
        return packaged
    if (_SOURCE_SKILL / "SKILL.md").is_file():
        return _SOURCE_SKILL
    raise SkillSourceError(
        f"the l4 skill is not in this installation (looked at the package data and {_SOURCE_SKILL}): reinstall l4"
    )


def _walk(folder: Path) -> dict[str, Path]:
    """Relative posix path -> file, for every file under `folder` (no bytecode)."""
    return {
        p.relative_to(folder).as_posix(): p
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundled_files() -> dict[str, tuple[Path, str]]:
    try:
        folder = bundled_skill_dir()
    except SkillSourceError as exc:
        raise L4Exit(ExitCode.INTERNAL_ERROR, f"skills: {exc}") from None
    return {rel: (path, _digest(path)) for rel, path in _walk(folder).items()}


# --- targets ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    agent: str
    scope: str  # "user" | "project"
    path: Path  # <skills dir>/l4


def _home(environ: Mapping[str, str]) -> Path:
    return Path(environ["HOME"]) if environ.get("HOME") else Path.home()


def repo_root(start: Path) -> Path:
    """The repository root: the nearest folder at or above `start` that holds `.git`, else `start`."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return start


def _on_path(name: str, environ: Mapping[str, str]) -> bool:
    return shutil.which(name, path=environ.get("PATH", "")) is not None


def detect_agents(home: Path, environ: Mapping[str, str]) -> list[str]:
    """The agents whose home folder exists or whose CLI is on PATH."""
    found = []
    for agent, (folders, clis) in _DETECT.items():
        if any((home / f).is_dir() for f in folders) or any(_on_path(c, environ) for c in clis):
            found.append(agent)
    return found


def targets_for(agents: list[str], *, scope: str, home: Path, root: Path | None) -> list[Target]:
    out: list[Target] = []
    for agent in agents:
        if scope == "project":
            assert root is not None
            out.append(Target(agent, scope, root / _PROJECT_DIRS[agent] / SKILL_NAME))
            continue
        out.append(Target(agent, scope, home / _USER_DIRS[agent] / SKILL_NAME))
        if agent == "codex" and (home / _CODEX_EXTRA).is_dir():
            out.append(Target(agent, scope, home / _CODEX_EXTRA / SKILL_NAME))
    return out


def all_targets(home: Path, root: Path | None) -> list[Target]:
    """Every place a copy may live: user scope, and project scope when `root` is a repository."""
    found = targets_for(list(AGENTS), scope="user", home=home, root=None)
    if root is not None:
        found += targets_for(list(AGENTS), scope="project", home=home, root=root)
    return found


# --- reading a target ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Inspection:
    exists: bool
    refused: str | None = None  # a symbolic link: the path that was met
    version: str | None = None
    has_manifest: bool = False
    edited: tuple[str, ...] = ()  # relative paths: changed, missing or extra
    files: Mapping[str, str] | None = None  # the hashes found on disk (without the manifest)


def _first_symlink(target: Path) -> Path | None:
    if target.is_symlink():
        return target
    if not target.is_dir():
        return None
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        for name in (*dirnames, *filenames):
            if (Path(dirpath) / name).is_symlink():
                return Path(dirpath) / name
    return None


def _read_manifest(target: Path) -> dict | None:
    try:
        data = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None
    return data


def inspect(target: Path, bundle: Mapping[str, tuple[Path, str]] | None = None) -> Inspection:
    """What is at `target`. `edited` is every file whose hash differs from the manifest, every file the manifest names
    that is missing, and every file it does not name. A folder with files and no manifest (a hand copy) is compared
    with the bundled files instead (`bundle`), so a copy that equals the bundle is not edited."""
    link = _first_symlink(target)
    if link is not None:
        return Inspection(True, refused=str(link))
    if not target.is_dir():
        return Inspection(False)
    on_disk = {rel: _digest(p) for rel, p in _walk(target).items() if rel != MANIFEST}
    # a bytecode file or a __pycache__ is not skill content; nothing else is excluded
    manifest = _read_manifest(target)
    if manifest is None:
        if not on_disk:
            return Inspection(True, files=on_disk)
        expected = {rel: h for rel, (_, h) in (bundle if bundle is not None else bundled_files()).items()}
        has_manifest, version = False, None
    else:
        expected = {str(k): str(v) for k, v in manifest["files"].items()}
        has_manifest, version = True, str(manifest.get("version", ""))
    edited = sorted(
        {rel for rel, h in on_disk.items() if expected.get(rel) != h} | {rel for rel in expected if rel not in on_disk}
    )
    return Inspection(True, None, version, has_manifest, tuple(edited), on_disk)


def _version_key(version: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in (version or "").split("."))
    except ValueError:
        return None


def compare(installed: str | None) -> str:
    """`current`, `old` or `newer` than the running l4 (an unreadable version is `old`)."""
    have, want = _version_key(installed), _version_key(__version__)
    if have is None or want is None or have < want:
        return "old"
    return "current" if have == want else "newer"


@dataclass(frozen=True)
class Copy:
    agent: str
    scope: str
    path: Path
    version: str | None
    edited: tuple[str, ...]


def installed_copies(home: Path, root: Path | None) -> list[Copy]:
    """The copies with a manifest, user scope and (with `root`) project scope: what `status` and doctor SKL-003 read."""
    found = []
    for t in all_targets(home, root):
        seen = inspect(t.path, {})
        if seen.exists and seen.refused is None and seen.has_manifest:
            found.append(Copy(t.agent, t.scope, t.path, seen.version, seen.edited))
    return found


# --- writing ---------------------------------------------------------------------------------------------------------


def _write_atomic(dest: Path, data: bytes, mode: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".l4-tmp-", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _install(target: Path, bundle: Mapping[str, tuple[Path, str]], present: Mapping[str, str]) -> None:
    for rel, (source, _) in bundle.items():
        mode = 0o755 if os.access(source, os.X_OK) else 0o644
        _write_atomic(target / rel, source.read_bytes(), mode)
    for rel in present:  # a file of an older version (or, with --force, an extra one) goes
        if rel not in bundle:
            (target / rel).unlink(missing_ok=True)
    for folder in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    manifest = {"name": SKILL_NAME, "version": __version__, "files": {rel: h for rel, (_, h) in sorted(bundle.items())}}
    _write_atomic(target / MANIFEST, (json.dumps(manifest, indent=2) + "\n").encode(), 0o644)


# --- the commands ----------------------------------------------------------------------------------------------------


def _say(text: str, *, err: bool = False) -> None:
    click.echo(text, err=err)


def run_skills_install(
    app: AppContext, *, agent: str = "auto", project: bool = False, force: bool = False, dry_run: bool = False
) -> ExitCode:
    """`l4 skills install`: one line per target; exit 2 when a target was refused (an edited copy, a symbolic link)."""
    home = _home(app.environ)
    scope = "project" if project else "user"
    if agent == "auto":
        agents = detect_agents(home, app.environ)
        if not agents:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                "skills install: no coding agent found (no ~/.claude, ~/.agents, ~/.codex, ~/.config/opencode, "
                "~/.opencode or ~/.kiro folder, and none of claude, codex, opencode, kiro-cli on PATH); "
                "name one with --agent claude-code|codex|opencode|kiro, or use --agent all",
            )
    elif agent == "all":
        agents = list(AGENTS)
    elif agent in AGENTS:
        agents = [agent]
    else:
        raise L4Exit(ExitCode.USAGE_ERROR, f"skills install: unknown agent {agent!r}")
    bundle = bundled_files()
    root = repo_root(app.repo) if project else None
    refused = 0
    for t in targets_for(agents, scope=scope, home=home, root=root):
        label = f"{t.agent} ({t.scope}) {t.path}"
        seen = inspect(t.path, bundle)
        if seen.refused is not None:
            _say(f"{label}: refused, {seen.refused} is a symbolic link; l4 does not follow it", err=True)
            refused += 1
            continue
        if seen.edited and not force:
            _say(f"{label}: refused, edited: {', '.join(seen.edited)}; --force replaces them", err=True)
            refused += 1
            continue
        same = seen.has_manifest and seen.version == __version__ and not seen.edited
        same = same and (seen.files or {}) == {rel: h for rel, (_, h) in bundle.items()}
        if same:
            _say(f"{label}: unchanged ({__version__})")
            continue
        verb = "installed" if not seen.exists else "updated"
        if dry_run:
            _say(f"{label}: would install" if not seen.exists else f"{label}: would update")
            continue
        try:
            _install(t.path, bundle, seen.files or {})
        except OSError as exc:
            _say(f"{label}: refused, {exc}", err=True)
            refused += 1
            continue
        _say(f"{label}: {verb} ({__version__})")
    return ExitCode.USAGE_ERROR if refused else ExitCode.OK


def run_skills_status(app: AppContext) -> ExitCode:
    """`l4 skills status`: each copy with its version, `current`/`old`/`newer`, and `edited` with the paths."""
    home = _home(app.environ)
    root = repo_root(app.repo)
    rows = []
    for t in all_targets(home, root if (root / ".git").exists() else None):
        seen = inspect(t.path, {})
        if not seen.exists:
            continue
        if seen.refused is not None:
            rows.append(f"{t.agent}\t{t.scope}\t{t.path}\trefused: {seen.refused} is a symbolic link")
        elif not seen.has_manifest:
            rows.append(f"{t.agent}\t{t.scope}\t{t.path}\tno manifest (not installed by l4)")
        else:
            state = compare(seen.version)
            edited = f"\tedited: {', '.join(seen.edited)}" if seen.edited else ""
            rows.append(f"{t.agent}\t{t.scope}\t{t.path}\t{seen.version}\t{state}{edited}")
    if not rows:
        _say("no l4 skill is installed; run `l4 skills install`")
    for row in rows:
        _say(row)
    return ExitCode.OK
