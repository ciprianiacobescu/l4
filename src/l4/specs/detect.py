"""Which spec frameworks a repository uses (SPEC 4.1): deterministic, from files only.

Nothing here starts a process or opens a socket; `Path.is_dir`/`is_file`/`iterdir` are the whole toolbox. A symlinked
root is not a signal: it would let repository content point detection at files outside the checkout.
M1: spec-providers 4.2 (`primary_framework`).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from l4.config.schema import L4Config
from l4.fsutil import UnsafeFile, reject_symlinks
from l4.specs.base import SAFE_NAME, Framework, NoFrameworkError, SpecProvider, UnitRef

KIRO_SPEC_FILES = ("requirements.md", "bugfix.md", "design.md", "tasks.md")
SPECKIT_SIGNALS = ("memory/constitution.md", "init-options.json", "templates")
_ORDER = (Framework.OPENSPEC, Framework.KIRO)


@dataclass(frozen=True)
class DetectionResult:
    frameworks: tuple[Framework, ...]  # supported and active, in `openspec`, `kiro` order
    legacy_openspec: bool  # `openspec/project.md` without a config file: reported, never driven
    speckit: bool  # detected, never driven in v1


def _dir(repo: Path, *parts: str) -> Path | None:
    if not parts or ".." in parts or Path(*parts).is_absolute():
        return None  # a configured root is still repository content: it must stay inside the checkout
    try:
        reject_symlinks(repo, *parts)
    except UnsafeFile:
        return None
    path = repo.joinpath(*parts)
    return path if path.is_dir() else None


def _openspec(repo: Path, root: str) -> tuple[bool, bool]:
    """(modern, legacy)."""
    base = _dir(repo, *Path(root).parts)
    if base is None:
        return False, False
    config = any((base / name).is_file() for name in ("config.yaml", "config.yml"))
    if config:
        return True, False
    if (base / "project.md").is_file():
        return False, True
    return any(_dir(repo, *Path(root).parts, name) for name in ("specs", "changes")), False


def kiro_spec_dirs(repo: Path, root: str) -> list[Path]:
    """Directories under the Kiro root that hold at least one of the four spec files, sorted by name."""
    base = _dir(repo, *Path(root).parts)
    if base is None:
        return []
    found = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_dir() or not SAFE_NAME.match(entry.name):
            continue
        if any((entry / name).is_file() and not (entry / name).is_symlink() for name in KIRO_SPEC_FILES):
            found.append(entry)
    return found


def _speckit(repo: Path) -> bool:
    base = _dir(repo, ".specify")
    return base is not None and any((base / signal).exists() for signal in SPECKIT_SIGNALS)


def detect_frameworks(
    repo: Path, *, openspec_root: str = "openspec", kiro_root: str = ".kiro/specs"
) -> DetectionResult:
    modern, legacy = _openspec(repo, openspec_root)
    kiro = bool(kiro_spec_dirs(repo, kiro_root))
    frameworks = tuple(f for f, on in ((Framework.OPENSPEC, modern), (Framework.KIRO, kiro)) if on)
    return DetectionResult(frameworks, legacy, _speckit(repo))


def detect_for(cfg: L4Config, repo: Path) -> DetectionResult:
    return detect_frameworks(repo, openspec_root=cfg.spec.openspec.root, kiro_root=cfg.spec.kiro.root)


def active_frameworks(cfg: L4Config, repo: Path) -> tuple[Framework, ...]:
    """`spec.frameworks: auto` is what detection finds; a list names the frameworks and needs no files (a repository
    about to receive its first spec is still configured for one)."""
    if cfg.spec.frameworks == "auto":
        return detect_for(cfg, repo).frameworks
    wanted = {Framework(name) for name in cfg.spec.frameworks}
    return tuple(f for f in _ORDER if f in wanted)


def require_framework(cfg: L4Config, repo: Path) -> None:
    """L4-DET-003: `sdd.enforce` and nothing to drive is exit 14, before any branch or agent call."""
    if not cfg.sdd.enforce or active_frameworks(cfg, repo):
        return
    found = detect_for(cfg, repo)
    if found.legacy_openspec:
        raise NoFrameworkError(
            "OpenSpec < 1.0 layout (openspec/project.md without a config file): run the OpenSpec migration"
        )
    raise NoFrameworkError("no spec framework (OpenSpec or Kiro) was found in this repository; run `l4 init`")


def collect_units(providers: Iterable[SpecProvider]) -> list[UnitRef]:
    """Every unit of every active provider; ids are `<framework>:<name>`, so frameworks never collide."""
    units = [unit for provider in providers for unit in provider.list_units()]
    return sorted(units, key=lambda u: (_ORDER.index(u.framework), u.name))
